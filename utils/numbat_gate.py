"""Numbat verdict engine for the pre-action hook (issue #1458 Phase 1).

Selected by ``policy.fallback.pre_action_hook.engine: numbat``. It exists
because ``numbat hook EVENT --agent NAME`` -- the argv config.yaml used to
suggest -- cannot make a policy decision about a CyClaw call. That subcommand
speaks the hook protocol of the agent hosts Numbat supports (Claude Code,
Codex, Qwen Code, ...), and CyClaw is not one. Verified against the pinned
0.2.0 binary with CyClaw's payload on stdin:

* ``--agent cyclaw`` (the old suggestion) prints ``hook: unknown agent
  "cyclaw"`` and exits 0; so does a mistyped event name for a real agent;
* a real agent parses the payload as its own generic ``tool.call``, and the
  provider, URL and query hash never reach a rule (checked with the claude
  and qwen adapters) -- an enforce rule on ``event.model_provider == "xai"``
  never fires;
* hooks never deny unless ``--enforce``; even then Claude-style hosts return
  the deny as JSON on stdout with exit 0, and only nine hosts (Qwen Code,
  Kimi Code, Goose, ...) use exit 2; any decision error exits 0.

CyClaw's hook contract reads exit 0 as allow, so the most ``numbat hook``
can do here is deny every call through an exit-2 host's adapter -- the same
as disabling the provider -- while any error allows. This engine asks Numbat
a question it answers deterministically instead: the proposed call is built
as a schema-0.3.0
``network.indicator`` event with the same builder the Numbat stream uses,
``numbat rules test`` evaluates it against the operator's rule directories
only (``--no-builtin-rules``; the shipped catalog is detection-only), and a
match of a rule marked ``enforce: true`` denies -- Numbat's own blocking
semantics. A rule without ``enforce: true`` is a monitor rule: its match is
reported and the call is allowed, which is how a new policy gets an
observe-only trial before it can deny.

Unlike ``numbat hook``, every failure here fails CLOSED: a missing binary, a
missing or empty rules directory, a rule that does not compile, a duplicate
rule id, a timeout, a non-zero exit, or output this module cannot parse is a
deny. It can only shrink what the I3 triple gate already allowed.

Stdlib + PyYAML only; the binary runs as a list-form subprocess with no
shell. Numbat is never imported (it is a Go binary, not a library).
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess  # nosec B404 - list-form only, no shell, operator-configured binary
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger("cyclaw.numbat_gate")

_REPO_ROOT = Path(__file__).resolve().parent.parent

# The pinned CLI. Must match the `numbat version` line numbat-rules.yml checks
# (tests/test_numbat_gate.py asserts the two agree).
PINNED_VERSION_LINE = "numbat 0.2.0 (schema 0.3.0)"
DEFAULT_BINARY = "numbat"

# Same pins as utils/endpoint_trust.py's online allowlist: only these hosts can
# be reached, so a rule keyed on event.url sees exactly where the call goes.
_DEFAULT_PROVIDER_URLS = {
    "grok": "https://api.x.ai/v1",
    "claude": "https://api.anthropic.com/v1",
}
_PROVIDER_TO_VENDOR = {"grok": "xai", "claude": "anthropic"}
_QUERY_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_RULE_SUFFIXES = (".yaml", ".yml")
_READINESS_TTL_SEC = 30.0
_MAX_REASON_CHARS = 300


def _gate_cfg(cfg: dict[str, Any] | None) -> dict[str, Any]:
    """policy.fallback.pre_action_hook.numbat, or {} when absent or malformed."""
    if not isinstance(cfg, dict):
        return {}
    policy = cfg.get("policy")
    fallback = policy.get("fallback") if isinstance(policy, dict) else None
    hook = fallback.get("pre_action_hook") if isinstance(fallback, dict) else None
    block = hook.get("numbat") if isinstance(hook, dict) else None
    return block if isinstance(block, dict) else {}


def _anchor(raw: str) -> Path:
    """Relative paths resolve against the repo root, never the process cwd."""
    path = Path(raw).expanduser()
    return path if path.is_absolute() else _REPO_ROOT / path


def resolve_binary(cfg: dict[str, Any] | None) -> str | None:
    """Absolute path of the configured numbat binary, or None if it is absent.

    A bare name (the default, ``numbat``) is looked up on PATH; anything with
    a path separator is a file path, relative ones anchored at the repo root.
    """
    raw = _gate_cfg(cfg).get("binary", DEFAULT_BINARY)
    if not isinstance(raw, str) or not raw.strip():
        return None
    raw = raw.strip()
    if os.sep in raw or (os.altsep and os.altsep in raw):
        candidate = _anchor(raw)
        return str(candidate) if candidate.is_file() and os.access(candidate, os.X_OK) else None
    return shutil.which(raw)


def rules_dirs(cfg: dict[str, Any] | None) -> list[Path] | None:
    """The configured rule directories, anchored; None when the key is malformed."""
    raw = _gate_cfg(cfg).get("rules_dirs", [])
    if not isinstance(raw, list) or not all(isinstance(item, str) and item.strip() for item in raw):
        return None
    return [_anchor(item.strip()) for item in raw]


def classify_rules(dirs: list[Path]) -> tuple[set[str], set[str]]:
    """Return (every rule id found, the ids whose rules can deny).

    A rule can deny when it sets ``enforce: true`` and is not ``enabled:
    false`` -- the same effect Numbat gives the flag. This walk only labels
    rules; Numbat's own loader decides what is valid. Anything Numbat would
    reject (a parse error, a string "true", a duplicate id) fails its run, and
    a match this walk did not see is treated as a failure by ``evaluate``, so
    a disagreement between the two loaders can only deny, never allow.
    """
    known: set[str] = set()
    enforcing: set[str] = set()
    for root in dirs:
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix not in _RULE_SUFFIXES:
                continue
            try:
                doc = yaml.safe_load(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, yaml.YAMLError):
                continue
            # Companion *_tests.yaml files carry rule_id, never id.
            if not isinstance(doc, dict) or not isinstance(doc.get("id"), str):
                continue
            known.add(doc["id"])
            if doc.get("enforce") is True and doc.get("enabled", True) is not False:
                enforcing.add(doc["id"])
    return known, enforcing


def _provider_url(provider: str, cfg: dict[str, Any] | None) -> str:
    models = cfg.get("models") if isinstance(cfg, dict) else None
    section = models.get(provider) if isinstance(models, dict) else None
    url = section.get("base_url") if isinstance(section, dict) else None
    return url if isinstance(url, str) and url else _DEFAULT_PROVIDER_URLS.get(provider, "")


def _include_query_hash(cfg: dict[str, Any] | None) -> bool:
    """logging.audit_fields.include_query_hash, default True, tolerant of any shape.

    An operator who opted out of the hash keeps it out of the gate's temp
    fixture too, the same as utils/external_pre_hook.py's verdict events.
    """
    logging_cfg = cfg.get("logging") if isinstance(cfg, dict) else None
    audit_fields = logging_cfg.get("audit_fields") if isinstance(logging_cfg, dict) else None
    if not isinstance(audit_fields, dict):
        return True
    return bool(audit_fields.get("include_query_hash", True))


def build_gate_event(provider: str, model: str, query_hash: str, cfg: dict[str, Any] | None) -> dict[str, Any]:
    """The proposed external call as one schema-0.3.0 event, for rules to see.

    Rules can key on ``event.model_provider`` ("xai" / "anthropic"),
    ``event.model``, ``event.url``, ``event.tags`` (``pre_action_hook`` plus
    the provider) and the ``event.endpoint`` host fields. The query is only
    ever present as its SHA-256, inside ``content_preview``.
    """
    from utils.numbat_emitter import build_event  # lazy: keeps this module's import surface stdlib + yaml

    preview = None
    if _include_query_hash(cfg) and _QUERY_HASH_RE.fullmatch(query_hash or ""):
        preview = json.dumps({"query_hash": query_hash}, separators=(",", ":"))
    return build_event(
        "network.indicator",
        url=_provider_url(provider, cfg) or None,
        tool_name="external_llm_call",
        decision="asked",
        model=model or None,
        model_provider=_PROVIDER_TO_VENDOR.get(provider, provider),
        entrypoint="cyclaw",
        actor="system",
        tags=["pre_action_hook", provider],
        content_preview=preview,
        artifact_type="pre_action_hook",
        cfg=cfg,
    )


def _deny(reason_code: str, reason: str) -> dict[str, Any]:
    return {"verdict": "deny", "reason_code": reason_code, "reason": reason[:_MAX_REASON_CHARS]}


def _first_line(text: str) -> str:
    for line in (text or "").splitlines():
        if line.strip():
            return line.strip()
    return ""


def evaluate(provider: str, model: str, query_hash: str, cfg: dict[str, Any] | None, *, timeout: float) -> dict[str, Any]:
    """Decide one proposed external call. Never raises; every failure denies.

    Returns ``{"verdict": "allow" | "deny", "reason_code": ..., "reason": ...}``
    plus, for an allow with monitor-rule matches, ``"monitor_matches"``.
    """
    try:
        return _evaluate(provider, model, query_hash, cfg, timeout=timeout)
    except Exception as exc:  # noqa: BLE001 - the gate fails closed, whatever broke
        logger.warning("numbat gate raised %s; denying", type(exc).__name__)
        return _deny("hook_error", f"numbat gate error: {type(exc).__name__}")


def _evaluate(provider: str, model: str, query_hash: str, cfg: dict[str, Any] | None, *, timeout: float) -> dict[str, Any]:
    dirs = rules_dirs(cfg)
    if not dirs:
        return _deny("hook_misconfigured", "numbat engine needs a non-empty list of rules_dirs")
    missing = [str(d) for d in dirs if not d.is_dir()]
    if missing:
        return _deny("hook_misconfigured", f"numbat rules dir not found: {missing[0]}")
    binary = resolve_binary(cfg)
    if binary is None:
        return _deny("hook_error", "numbat binary not found (policy.fallback.pre_action_hook.numbat.binary)")

    event = build_gate_event(provider, model, query_hash, cfg)
    known, enforcing = classify_rules(dirs)
    fd, fixture = tempfile.mkstemp(prefix="cyclaw-pre-action-", suffix=".ndjson")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(event, separators=(",", ":"), ensure_ascii=False) + "\n")
        argv = [binary, "rules", "test", "--fixture", fixture, "--no-builtin-rules"]
        for directory in dirs:
            argv += ["--rules-dir", str(directory)]
        try:
            proc = subprocess.run(  # noqa: S603  # nosec B603 - list-form, no shell
                argv, capture_output=True, text=True, timeout=timeout, check=False,
            )
        except subprocess.TimeoutExpired:
            return _deny("hook_timeout", f"numbat rules test timed out after {timeout:g}s")
        except (OSError, ValueError) as exc:
            return _deny("hook_error", f"numbat could not run: {type(exc).__name__}")
    finally:
        try:
            os.unlink(fixture)
        except OSError:
            # A leftover temp fixture holds one hashed event and nothing else;
            # it must not turn a decided verdict into an exception.
            pass

    if proc.returncode != 0:
        return _deny("hook_failure", f"numbat rules test exited {proc.returncode}: {_first_line(proc.stderr)}")

    matched: list[str] = []
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        rule_id, sep, event_id = line.partition("\t")
        if not sep or event_id.strip() != event["event_id"] or not rule_id.strip():
            return _deny("hook_failure", "numbat rules test printed output this engine cannot parse")
        matched.append(rule_id.strip())

    unknown = sorted(set(matched) - known)
    if unknown:
        return _deny("hook_failure", f"numbat matched a rule this engine cannot classify: {unknown[0]}")
    denying = sorted(set(matched) & enforcing)
    if denying:
        return _deny("hook_denied", f"denied by Numbat rule(s): {', '.join(denying)}")
    result: dict[str, Any] = {"verdict": "allow", "reason_code": "hook_allowed", "reason": "no enforce rule matched"}
    monitored = sorted(set(matched))
    if monitored:
        result["monitor_matches"] = monitored
        result["reason"] = f"monitor rule(s) matched, not enforced: {', '.join(monitored)}"
    return result


_READINESS_LOCK = threading.Lock()
_READINESS_CACHE: dict[tuple[Any, ...], tuple[float, tuple[bool, str | None]]] = {}


def readiness(cfg: dict[str, Any] | None) -> tuple[bool, str | None]:
    """Whether the engine could decide a call right now, and why not if not.

    For /health, so it runs no rule evaluation and is cached for 30 s per
    (binary, dirs): /health is unauthenticated and polled, and each check
    spawns the binary twice. Problems are fixed phrases: no path, rule text,
    or Numbat stderr, which would publish the server's layout. The same
    ``numbat`` command run by hand gives the detail.
    """
    binary = resolve_binary(cfg)
    dirs = rules_dirs(cfg)
    key = (binary, tuple(str(d) for d in dirs) if dirs is not None else None)
    now = time.monotonic()
    with _READINESS_LOCK:
        cached = _READINESS_CACHE.get(key)
        if cached and now - cached[0] < _READINESS_TTL_SEC:
            return cached[1]
    verdict = _readiness(binary, dirs)
    with _READINESS_LOCK:
        _READINESS_CACHE[key] = (now, verdict)
    return verdict


def _readiness(binary: str | None, dirs: list[Path] | None) -> tuple[bool, str | None]:
    if not dirs:
        return False, "numbat engine has no rules_dirs, so every external call is denied"
    if any(not d.is_dir() for d in dirs):
        return False, "a numbat rules_dirs entry does not exist, so every external call is denied"
    if binary is None:
        return False, "numbat binary not found, so every external call is denied"
    try:
        version = subprocess.run(  # noqa: S603  # nosec B603 - list-form, no shell
            [binary, "version"], capture_output=True, text=True, timeout=5, check=False,
        )
        # A version string names no path, so it is safe to echo.
        if _first_line(version.stdout) != PINNED_VERSION_LINE:
            return False, f"numbat reports {_first_line(version.stdout)[:60]!r}, not the pinned {PINNED_VERSION_LINE!r}"
        argv = [binary, "rules", "check", "--no-builtin-rules"]
        for directory in dirs:
            argv += ["--rules-dir", str(directory)]
        check = subprocess.run(  # noqa: S603  # nosec B603 - list-form, no shell
            argv, capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        return False, f"numbat could not run: {type(exc).__name__}"
    if check.returncode != 0:
        return False, "numbat rules check failed on the configured rules_dirs, so every external call is denied"
    _, enforcing = classify_rules(dirs)
    if not enforcing:
        return False, "no enabled enforce: true rule, so the gate cannot deny anything"
    return True, None


def clear_readiness_cache() -> None:
    """Drop cached readiness results (tests, and after editing rules)."""
    with _READINESS_LOCK:
        _READINESS_CACHE.clear()


__all__ = [
    "DEFAULT_BINARY",
    "PINNED_VERSION_LINE",
    "build_gate_event",
    "classify_rules",
    "clear_readiness_cache",
    "evaluate",
    "readiness",
    "resolve_binary",
    "rules_dirs",
]
