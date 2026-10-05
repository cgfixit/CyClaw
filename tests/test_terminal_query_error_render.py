"""POST /query 200 + body.error: the gateway shape, and how the console renders it.

Contract (e2e-fixes card, PR A "terminal-error"):

* Server: when the LLM fails, ``/query`` still answers HTTP 200, ``body.error``
  carries the stamped ``"{code}: {message}"`` (scrubbed by ``public_error()``),
  and ``body.answer`` carries the ``[LLM Error: ...]`` stub.
* Console: on a 200 whose body has ``error`` set, ``static/terminal.js`` shows
  the error and stops presenting the degraded answer as a normal reply (no
  ``answer-entry`` carrying the ``[LLM Error:`` stub).

The server half drives the real graph (``graph.build_graph``) behind a mocked
gateway, with a local LLM client that raises ``LLMServiceError`` -- the same
exception a dead or erroring Ollama produces in ``llm/client.py``.

The console half runs the shipped ``static/auth_admin.js`` + ``static/terminal.js``
under Node in a ``vm`` context with a minimal DOM (element ids taken from
``static/terminal.html``) and a stubbed ``fetch``, calls ``submitQuery()``, and
inspects the entries appended to ``#results``. It asserts rendered output only,
not how terminal.js is written, and skips where ``node`` is not on PATH.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.conftest import MOCK_HIGH_SCORE_RESULTS, MockRetriever, _mocked_gateway
from utils.errors import LLMServiceError

_REPO = Path(__file__).resolve().parent.parent
_STATIC = _REPO / "static"
_NODE = shutil.which("node")

# Own loopback rate-limit bucket (see conftest._mocked_gateway's docstring).
_PEER = ("127.0.0.73", 51234)  # DevSkim: ignore DS162092,DS137138 - test loopback peer

_LLM_FAILURE = "Ollama returned 500 after 3 retries"
_LLM_CODE = "LLM_SERVICE_ERROR"
_ERROR_STUB = "[LLM Error:"

# What gate.py returns for a degraded local answer (the tests/test_runtime_errors.py
# Group 2 shape, as the QueryResponse JSON the browser receives).
_CANNED_ERROR_BODY: dict[str, object] = {
    "answer": f"[LLM Error: {_LLM_FAILURE}]",
    "model_used": "local",
    "llm_model": "qwen-test",
    "retrieval_mode": "hybrid",
    "hit_count": 2,
    "needs_confirm": False,
    "sources": [],
    "error": f"{_LLM_CODE}: {_LLM_FAILURE}",
}

_CANNED_OK_BODY: dict[str, object] = {
    "answer": "Veeam uses chattr +i for immutability.",
    "model_used": "local",
    "llm_model": "qwen-test",
    "retrieval_mode": "hybrid",
    "hit_count": 2,
    "needs_confirm": False,
    "sources": [],
    "error": None,
}


class _RaisingLocalLLM:
    """LocalLLMClient stand-in whose generate() fails like an erroring Ollama."""

    def generate(self, prompt: str, **kwargs: object) -> str:
        raise LLMServiceError(_LLM_FAILURE)


def _llm_error_body_from_gateway(tmp_path: Path) -> tuple[int, dict[str, object]]:
    """POST /query through the mocked gateway with a real graph and a failing LLM."""
    from graph import build_graph

    with _mocked_gateway(tmp_path, peer=_PEER) as (test_client, _mock_graph):
        import gate

        gate.compiled_graph = build_graph(
            retriever=MockRetriever(MOCK_HIGH_SCORE_RESULTS),  # type: ignore[no-untyped-call, arg-type]
            llm=_RaisingLocalLLM(),  # type: ignore[arg-type]
            grok=None,
            cfg=gate.cfg,
        )
        resp = test_client.post("/query", json={"query": "What is Veeam immutability?"})
        return resp.status_code, resp.json()


# ---------------------------------------------------------------------------
# Server half: the 200 + body.error shape the console consumes
# ---------------------------------------------------------------------------


def test_query_llm_failure_answers_200_with_error_field(tmp_path: Path) -> None:
    status, body = _llm_error_body_from_gateway(tmp_path)

    assert status == 200, body
    assert body["needs_confirm"] is False
    assert body["model_used"] == "local"
    error = body.get("error")
    answer = body.get("answer")
    assert isinstance(error, str) and error.startswith(f"{_LLM_CODE}: "), body
    assert _LLM_FAILURE in error
    assert isinstance(answer, str) and _ERROR_STUB in answer, body


# ---------------------------------------------------------------------------
# Console half: static/terminal.js under Node with a minimal DOM
# ---------------------------------------------------------------------------

# Loads the page's scripts in terminal.html order, answers POST /query with the
# configured status/body, leaves every other fetch pending (so checkHealth()
# at load does nothing), and never fires timers (so the 790 s client abort
# cannot keep Node alive). Prints the #results entries as JSON.
_HARNESS_JS = r"""
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const cfg = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const html = fs.readFileSync(path.join(cfg.static, 'terminal.html'), 'utf8');
const pageIds = new Set([...html.matchAll(/\sid="([^"]+)"/g)].map((m) => m[1]));

function escapeText(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}
function stripTags(s) {
  return String(s).replace(/<[^>]*>/g, '').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');
}

class FakeClassList {
  constructor(el) { this.el = el; }
  _list() { return this.el.className.split(/\s+/).filter(Boolean); }
  _set(list) { this.el.className = list.join(' '); }
  add(...c) { const l = this._list(); for (const x of c) if (!l.includes(x)) l.push(x); this._set(l); }
  remove(...c) { this._set(this._list().filter((x) => !c.includes(x))); }
  contains(c) { return this._list().includes(c); }
  toggle(c, force) {
    const on = force === undefined ? !this.contains(c) : !!force;
    if (on) this.add(c); else this.remove(c);
    return on;
  }
}

class FakeElement {
  constructor(tag, id) {
    this.tagName = String(tag).toUpperCase();
    this.id = id || '';
    this.className = '';
    this.children = [];
    this.parentNode = null;
    this.style = {};
    this.dataset = {};
    this.attributes = {};
    this.hidden = false;
    this.disabled = false;
    this.checked = false;
    this.value = '';
    this.scrollTop = 0;
    this.scrollHeight = 0;
    this.listeners = {};
    this.classList = new FakeClassList(this);
    this._text = '';
    this._html = null;
  }
  get textContent() {
    if (this._html !== null) return stripTags(this._html);
    return this._text + this.children.map((c) => c.textContent).join('');
  }
  set textContent(v) { this._text = v == null ? '' : String(v); this._html = null; this.children = []; }
  get innerText() { return this.textContent; }
  set innerText(v) { this.textContent = v; }
  get innerHTML() {
    if (this._html !== null) return this._html;
    return escapeText(this._text) + this.children.map((c) => c.outerHTML).join('');
  }
  set innerHTML(v) { this._html = String(v); this._text = ''; this.children = []; }
  get outerHTML() {
    const tag = this.tagName.toLowerCase();
    return `<${tag} class="${this.className}">${this.innerHTML}</${tag}>`;
  }
  get firstChild() { return this.children[0] || null; }
  get lastChild() { return this.children[this.children.length - 1] || null; }
  appendChild(c) {
    if (c.parentNode) c.remove();
    c.parentNode = this;
    this.children.push(c);
    return c;
  }
  append(...cs) { for (const c of cs) if (c instanceof FakeElement) this.appendChild(c); }
  prepend(...cs) { for (const c of cs.reverse()) if (c instanceof FakeElement) { c.parentNode = this; this.children.unshift(c); } }
  insertBefore(c, ref) {
    const i = ref ? this.children.indexOf(ref) : -1;
    c.parentNode = this;
    if (i < 0) this.children.push(c); else this.children.splice(i, 0, c);
    return c;
  }
  removeChild(c) { const i = this.children.indexOf(c); if (i >= 0) this.children.splice(i, 1); c.parentNode = null; return c; }
  replaceChildren(...cs) { this.children = []; this._text = ''; this._html = null; this.append(...cs); }
  remove() { if (this.parentNode) this.parentNode.removeChild(this); }
  setAttribute(k, v) { this.attributes[k] = String(v); if (k === 'id') this.id = String(v); if (k === 'class') this.className = String(v); }
  getAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attributes, k) ? this.attributes[k] : null; }
  removeAttribute(k) { delete this.attributes[k]; }
  hasAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attributes, k); }
  addEventListener(t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); }
  removeEventListener() {}
  dispatchEvent() { return true; }
  querySelector() { return null; }
  querySelectorAll() { return []; }
  closest() { return null; }
  contains(o) { return o === this; }
  focus() {}
  blur() {}
  click() {}
  select() {}
  scrollIntoView() {}
  showModal() {}
  close() {}
  getBoundingClientRect() { return { top: 0, left: 0, right: 0, bottom: 0, width: 0, height: 0 }; }
}

const staticEls = new Map();
const created = [];
function walkFind(el, id) {
  if (el.id === id) return el;
  for (const c of el.children) { const hit = walkFind(c, id); if (hit) return hit; }
  return null;
}
const document = {
  hidden: false,
  visibilityState: 'visible',
  cookie: '',
  body: new FakeElement('body'),
  documentElement: new FakeElement('html'),
  getElementById(id) {
    if (pageIds.has(id)) {
      if (!staticEls.has(id)) staticEls.set(id, new FakeElement('div', id));
      return staticEls.get(id);
    }
    for (const root of staticEls.values()) { const hit = walkFind(root, id); if (hit) return hit; }
    return null;
  },
  createElement(tag) { const el = new FakeElement(tag); created.push(el); return el; },
  createTextNode(t) { const el = new FakeElement('#text'); el.textContent = t; return el; },
  createDocumentFragment() { return new FakeElement('#fragment'); },
  addEventListener() {},
  removeEventListener() {},
  querySelector() { return null; },
  querySelectorAll() { return []; },
};

const storage = { getItem() { return null; }, setItem() {}, removeItem() {} };
let timerId = 0;
function jsonResponse(status, body) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: String(status),
    headers: { get() { return 'application/json'; } },
    json: async () => body,
    text: async () => JSON.stringify(body),
  };
}
const fetchCalls = [];
async function fetchStub(url, opts) {
  fetchCalls.push({ url: String(url), method: (opts && opts.method) || 'GET' });
  if (String(url).endsWith('/query')) return jsonResponse(cfg.status, cfg.body);
  return new Promise(() => {});
}

const sandbox = {
  document,
  console,
  fetch: fetchStub,
  location: { origin: 'http://127.0.0.1:8787', href: 'http://127.0.0.1:8787/', protocol: 'http:', host: '127.0.0.1:8787' },
  localStorage: storage,
  sessionStorage: storage,
  navigator: { userAgent: 'node-harness', clipboard: { writeText: async () => {} } },
  performance: { now: () => 0 },
  setTimeout: () => ++timerId,
  clearTimeout: () => {},
  setInterval: () => ++timerId,
  clearInterval: () => {},
  requestAnimationFrame: () => ++timerId,
  AbortController,
  URL,
  URLSearchParams,
  Promise,
  JSON,
  Map,
  Set,
  Date,
  Math,
  alert: () => {},
  confirm: () => false,
};
vm.createContext(sandbox);
vm.runInContext('globalThis.window = globalThis; globalThis.self = globalThis;', sandbox);
for (const name of ['auth_admin.js', 'terminal.js']) {
  const src = fs.readFileSync(path.join(cfg.static, name), 'utf8');
  vm.runInContext(src, sandbox, { filename: name });
}

const driver = `
  (async () => {
    input.value = ${JSON.stringify(cfg.query)};
    await submitQuery();
    return resultsEl.children.map((el) => ({
      id: el.id, className: el.className, html: el.innerHTML, text: el.textContent,
    }));
  })()
`;
vm.runInContext(driver, sandbox).then((entries) => {
  process.stdout.write(JSON.stringify({ entries, fetchCalls }));
}).catch((err) => {
  process.stderr.write(String(err && err.stack || err));
  process.exit(3);
});
"""


def _render_in_console(tmp_path: Path, status: int, body: dict[str, object]) -> list[dict[str, str]]:
    """Run terminal.js submitQuery() against a stubbed /query; return #results entries."""
    assert _NODE is not None
    harness = tmp_path / "terminal_harness.js"
    harness.write_text(_HARNESS_JS, encoding="utf-8")
    cfg_path = tmp_path / "harness_cfg.json"
    cfg_path.write_text(
        json.dumps({"static": str(_STATIC), "status": status, "body": body, "query": "What is Veeam immutability?"}),
        encoding="utf-8",
    )
    proc = subprocess.run(
        [_NODE, str(harness), str(cfg_path)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, f"node harness failed ({proc.returncode}):\n{proc.stderr}"
    out = json.loads(proc.stdout)
    assert any(c["url"].endswith("/query") and c["method"] == "POST" for c in out["fetchCalls"]), out["fetchCalls"]
    entries: list[dict[str, str]] = out["entries"]
    return entries


def _entries_of_type(entries: list[dict[str, str]], entry_type: str) -> list[dict[str, str]]:
    return [e for e in entries if f"{entry_type}-entry" in e["className"].split()]


def _assert_error_shown_not_answer(entries: list[dict[str, str]], failure_text: str) -> None:
    errors = _entries_of_type(entries, "error")
    assert errors, f"no error entry rendered for a 200 carrying body.error; entries={entries}"
    assert any(_LLM_CODE in e["text"] or failure_text in e["text"] for e in errors), (
        f"error entry does not name the failure ({_LLM_CODE} / {failure_text!r}); errors={errors}"
    )
    degraded = [e for e in _entries_of_type(entries, "answer") if _ERROR_STUB in e["text"]]
    assert not degraded, (
        "the degraded '[LLM Error: ...]' answer is still presented as a normal reply "
        f"(answer-entry); entries={degraded}"
    )


@pytest.mark.skipif(_NODE is None, reason="node is not on PATH; console half needs it")
def test_console_happy_path_renders_answer_entry(tmp_path: Path) -> None:
    # Control: proves the harness sees a normal reply, so the error test below
    # cannot pass just because nothing rendered.
    entries = _render_in_console(tmp_path, 200, _CANNED_OK_BODY)
    answers = _entries_of_type(entries, "answer")
    assert len(answers) == 1, entries
    assert "chattr +i" in answers[0]["text"]
    assert not _entries_of_type(entries, "error"), entries


@pytest.mark.skipif(_NODE is None, reason="node is not on PATH; console half needs it")
def test_console_shows_body_error_on_200_instead_of_normal_answer(tmp_path: Path) -> None:
    entries = _render_in_console(tmp_path, 200, _CANNED_ERROR_BODY)
    _assert_error_shown_not_answer(entries, _LLM_FAILURE)


@pytest.mark.skipif(_NODE is None, reason="node is not on PATH; console half needs it")
def test_console_renders_gateway_llm_error_body_end_to_end(tmp_path: Path) -> None:
    # The body the real gateway produced for a failing LLM, fed to the console.
    status, body = _llm_error_body_from_gateway(tmp_path)
    assert status == 200 and body.get("error"), body
    entries = _render_in_console(tmp_path, status, body)
    _assert_error_shown_not_answer(entries, _LLM_FAILURE)


@pytest.mark.skipif(_NODE is None, reason="node is not on PATH; console half needs it")
def test_console_keeps_citation_wrapped_real_answer_when_error_rides_along(tmp_path: Path) -> None:
    # A real answer that happens to open and close with citations ("[1] ... [2]")
    # is not a stand-in placeholder: with an upstream error riding along it must
    # still render as an ANSWER (plus the error entry), not be hidden.
    real_answer = "[1] Veeam hardened repositories set chattr +i on backup files [2]"
    body = {**_CANNED_OK_BODY, "answer": real_answer, "error": "RETRIEVAL_DEGRADED: vector store unavailable"}
    entries = _render_in_console(tmp_path, 200, body)
    answers = _entries_of_type(entries, "answer")
    assert len(answers) == 1 and "chattr +i" in answers[0]["text"], (
        f"citation-wrapped real answer was hidden because an error rode along; entries={entries}"
    )
    assert _entries_of_type(entries, "error"), f"the upstream error was not shown; entries={entries}"


@pytest.mark.skipif(_NODE is None, reason="node is not on PATH")
@pytest.mark.parametrize("label", ["LLM Error", "Grok Error", "Claude Error", "Guardrail Error",
                                   "External call denied by pre-action hook"])
def test_console_suppresses_complete_graph_placeholder(tmp_path: Path, label: str) -> None:
    body = {**_CANNED_ERROR_BODY, "answer": f"[{label}: failure [detail]\ncontinued]"}
    entries = _render_in_console(tmp_path, 200, body)
    assert not _entries_of_type(entries, "answer"), entries
    assert len(_entries_of_type(entries, "error")) == 1, entries


@pytest.mark.skipif(_NODE is None, reason="node is not on PATH")
@pytest.mark.parametrize("answer", [
    "[LLM Error] is the label used for a failed local call.",
    "[Guardrail Error: failed] is an example, not this answer's status.",
    "[External call denied] describes a policy decision.",
    "[LLM Error: incomplete quotation",
])
def test_console_keeps_prose_about_error_labels(tmp_path: Path, answer: str) -> None:
    entries = _render_in_console(tmp_path, 200, {**_CANNED_ERROR_BODY, "answer": answer})
    assert len(_entries_of_type(entries, "answer")) == 1, entries
    assert len(_entries_of_type(entries, "error")) == 1, entries


@pytest.mark.skipif(_NODE is None, reason="node is not on PATH")
def test_console_keeps_placeholder_shaped_answer_without_error(tmp_path: Path) -> None:
    entries = _render_in_console(tmp_path, 200, {**_CANNED_ERROR_BODY, "error": None})
    assert len(_entries_of_type(entries, "answer")) == 1, entries
    assert not _entries_of_type(entries, "error"), entries
