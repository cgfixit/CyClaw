"""Shared pytest fixtures for CyClaw test suite.

Mocks: LLM services, embedding model, retriever, test config.
No live services required — all external deps are mocked.
"""

import contextlib
import copy
import logging
import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from retrieval.hybrid_search import SearchResult
from utils import logger as _logger_mod
from utils import numbat_emitter as _numbat_emitter_mod
from utils import spend as _spend_mod

_REPO_ROOT = Path(__file__).resolve().parent.parent
# What the suite must leave exactly as it found it: logs/, where every runtime
# sink defaults, and the placeholder dir TEST_CONFIG's un-overridden paths name
# (a subprocess handed a dumped TEST_CONFIG would write there).
_GUARDED_DIRS = ("logs", "OVERRIDDEN-PER-TEST")
# Every module holding a reference to utils.logger._anchor, the single
# resolver the runtime log sinks use (audit_file, log_file, spend_file, the
# Numbat stream). numbat_emitter and spend import it by name, so each binding
# is redirected, not just the one in utils.logger.
_ANCHOR_MODULES = (_logger_mod, _numbat_emitter_mod, _spend_mod)
_REAL_ANCHOR = _logger_mod._anchor


# Set in pytest_configure, read by _repo_logs_untouched and pytest_unconfigure.
_SESSION_LOGS: dict[str, object] = {}


def _anchor_under(sink_root: Path):
    def _anchor_under_sink(path_str: str) -> Path:
        path = Path(path_str).expanduser()
        return path if path.is_absolute() else sink_root / path

    return _anchor_under_sink


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "real_log_anchor: run with utils.logger._anchor's real repo-root anchoring "
        "(tests OF the anchoring); see pytest_configure in tests/conftest.py",
    )
    # Tests exercise production code with configs whose log paths are relative
    # ("logs/audit.jsonl", the Numbat stream's "logs/numbat-events.ndjsonl",
    # and TEST_CONFIG's OVERRIDDEN-PER-TEST placeholders). The real _anchor
    # resolves those against the REPO ROOT on purpose (never cwd), so a full
    # run used to write ~1.8 MB into the working tree's logs/ from ~600 tests,
    # and concurrent runs from other checkouts raced on the same files.
    # Most offenders are agentic fixtures that copy the shipped config.yaml,
    # so fixing the config dicts one by one would not have reached them.
    #
    # A structural backstop instead: for the whole run, relative sink paths
    # resolve under a per-run temp dir; absolute paths (every test's own
    # tmp_path) are untouched. It is installed HERE, not in a session fixture,
    # because five test modules import gate at module level and gate.py calls
    # setup_logging(cfg) at import: that happens during collection, before any
    # fixture exists, and would otherwise attach a root FileHandler on
    # <repo>/logs/cyclaw.log that every later test's log lines flow into.
    # Tests of the anchoring itself opt out with @pytest.mark.real_log_anchor;
    # a subprocess cannot see this patch and needs absolute tmp paths in the
    # config it is handed. _repo_logs_untouched fails the run if anything
    # still reaches the repo.
    _SESSION_LOGS["before"] = _repo_logs_snapshot()
    sink_root = Path(tempfile.mkdtemp(prefix="cyclaw-test-logs-"))
    patcher = pytest.MonkeyPatch()
    for module in _ANCHOR_MODULES:
        patcher.setattr(module, "_anchor", _anchor_under(sink_root))
    _SESSION_LOGS.update(sink_root=sink_root, patcher=patcher)


def pytest_unconfigure(config):
    patcher = _SESSION_LOGS.pop("patcher", None)
    if isinstance(patcher, pytest.MonkeyPatch):
        patcher.undo()
    sink_root = _SESSION_LOGS.pop("sink_root", None)
    if isinstance(sink_root, Path):
        # ignore_errors: a logging FileHandler may still hold a file open,
        # which Windows refuses to delete.
        shutil.rmtree(sink_root, ignore_errors=True)


@pytest.fixture(autouse=True)
def _real_log_anchor_when_marked(request, monkeypatch):
    if request.node.get_closest_marker("real_log_anchor"):
        for module in _ANCHOR_MODULES:
            monkeypatch.setattr(module, "_anchor", _REAL_ANCHOR)


def _repo_logs_snapshot(
    root: Path = _REPO_ROOT, dirs: tuple[str, ...] = _GUARDED_DIRS
) -> dict[str, tuple[int, int]]:
    """{path relative to root: (size, mtime_ns)} for every file under root/<dirs>."""
    snapshot: dict[str, tuple[int, int]] = {}
    for name in dirs:
        base = root / name
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            try:
                if path.is_file():
                    stat = path.stat()
                    snapshot[path.relative_to(root).as_posix()] = (stat.st_size, stat.st_mtime_ns)
            except OSError:
                # A file vanishing mid-walk is itself a change the next
                # snapshot reports; it must not crash the guard.
                continue
    return snapshot


def _repo_logs_changes(before: dict[str, tuple[int, int]], after: dict[str, tuple[int, int]]) -> list[str]:
    """Files created, modified, or deleted between two snapshots."""
    return sorted(name for name in set(before) | set(after) if before.get(name) != after.get(name))


@pytest.fixture(scope="session", autouse=True)
def _numbat_writes_wait_like_before():
    # The Numbat stream's writer thread (utils/numbat_emitter._StreamWriter)
    # makes a caller wait at most _WRITE_WAIT_SEC (1 s) for its line. Tests
    # read the stream straight after writing, as they did when writes were
    # synchronous, so a runner slow enough to take a second over one append
    # would read too early. Tests of the stalled path set their own short wait
    # with monkeypatch.
    saved = _numbat_emitter_mod._WRITE_WAIT_SEC
    _numbat_emitter_mod._WRITE_WAIT_SEC = 30.0
    yield
    _numbat_emitter_mod._WRITE_WAIT_SEC = saved


@pytest.fixture(scope="session", autouse=True)
def _repo_logs_untouched():
    # Guard for the backstop in pytest_configure: the run must leave <repo>/logs
    # (and the placeholder dir) exactly as it found them. The "before" snapshot
    # is taken in pytest_configure, so collection-time writes count too; the
    # comparison runs once, after the last test. Stat-only, never per test, so
    # a test's own os.stat monkeypatch can never trip it. A server running from
    # this same checkout writes there too; set CYCLAW_TEST_ALLOW_REPO_LOGS=1 to
    # skip the guard for that run.
    if os.environ.get("CYCLAW_TEST_ALLOW_REPO_LOGS") == "1":
        yield
        return
    before = _SESSION_LOGS.get("before")
    if not isinstance(before, dict):
        before = _repo_logs_snapshot()
    yield
    changed = _repo_logs_changes(before, _repo_logs_snapshot())
    if changed:
        pytest.fail(
            f"tests created, modified, or deleted files under {_REPO_ROOT}: {changed}. "
            "Route the writer's paths to tmp_path (tests/conftest.py's pytest_configure "
            "redirects in-process sinks; a subprocess needs a config with absolute tmp "
            "paths). If a server running from this checkout wrote them, rerun with "
            "CYCLAW_TEST_ALLOW_REPO_LOGS=1.",
            pytrace=False,
        )


# DevSkim: ignore DS162092,DS137138 - test fixtures; loopback addresses are intentional
TEST_CONFIG = {
    "app": {"name": "cyclaw-test", "env": "test", "mode": "offline", "debug": True},
    "models": {
        "local_llm": {"provider": "ollama", "base_url": "http://127.0.0.1:11434/v1",
                      "model": "test-model", "max_tokens": 256, "temperature": 0.1, "timeout_sec": 10},
        "embeddings": {"provider": "sentence-transformers", "model": "all-MiniLM-L6-v2",
                       "dim": 384, "cache_dir": None},
        "grok": {"enabled": False, "base_url": "https://api.x.ai/v1", "model": "grok-4.5",
                 "timeout_sec": 10, "max_tokens": 256, "temperature": 0.2},
        "claude": {"enabled": False, "base_url": "https://api.anthropic.com/v1",
                   "model": "claude-sonnet-5", "anthropic_version": "2023-06-01",
                   "timeout_sec": 10, "max_tokens": 256}
    },
    "corpus": {"path": "data/corpus", "extensions": [".md", ".txt"]},
    "indexing": {"chroma_path": "", "bm25_path": "", "collection_name": "test_kb",
                 "chunk_size": 512, "chunk_overlap": 50, "batch_size": 10},
    "retrieval": {"top_k_semantic": 3, "top_k_keyword": 3, "rrf_k": 60,
                   "max_context_tokens": 1000, "min_score": 0.75},
    "policy": {
        "fallback": {"enabled": True, "require_user_confirm": True,
                     "send_local_context_to_grok": False,
                     "send_local_context_to_claude": False},
        "prompt_filter": {"enabled": True,
                          "banned_patterns": ["ignore previous instructions", "system prompt:"],
                          "max_input_chars": 4000},
        "privacy": {"redact_emails": True, "redact_ips": True,
                    "redact_secrets_like": ["AKIA[0-9A-Z]{16}"]}
    },
    "api": {"host": "127.0.0.1", "port": 8787},  # DevSkim: ignore DS162092
    # audit_file is a deliberately-nonexistent placeholder, never a real path.
    # Every consumer overrides it per-test (the test_config fixture below and the
    # autouse audit-routing fixtures in test_graph.py / test_due_diligence_
    # invariants.py all point it at tmp_path). The old value called
    # tempfile.mkdtemp() at module import — leaking one orphan /tmp dir per
    # pytest collection for a path nothing ever wrote to. If a future test uses
    # TEST_CONFIG raw and writes audit lines, this placeholder fails loudly
    # (missing directory) instead of scattering files under /tmp.
    "logging": {"level": "DEBUG", "log_file": "", "audit_file": "OVERRIDDEN-PER-TEST/audit.jsonl",
                "spend_file": "OVERRIDDEN-PER-TEST/spend.jsonl",
                "audit_fields": {"include_query_hash": True}},
    # Explicit so the derived stream is a visible part of the test config, not
    # an implicit default: numbat_emitter treats a missing block as enabled
    # with the repo-relative logs/numbat-events.ndjsonl. Kept ENABLED so the
    # mainline plane (every audit_log -> project_audit_record) stays exercised;
    # only the destination is per-test, like audit_file above.
    "numbat": {"enabled": True, "output_path": "OVERRIDDEN-PER-TEST/numbat-events.ndjsonl"},
    "security": {"require_env": ["GROK_API_KEY"],
                 "allowed_origins": ["http://127.0.0.1", "http://localhost"]},  # DevSkim: ignore DS162092,DS137138
    "personality": {"enabled": False, "soul_path": "", "db_path": "", "interaction_ttl_days": 90}
}


@pytest.fixture(autouse=True)
def _disarm_agentic_write_execution(request, monkeypatch):
    # Structural backstop against the unit lane opening a real pull request.
    #
    # agentic/writer.py's EXECUTION_ENABLED ships True (operator enablement,
    # 2026-08-07), and the real-repo CLI fixtures copy the shipped config.yaml
    # -- which now carries mode: "write" + writes_enabled: true -- and then set
    # enabled = True to exercise the pipeline. The only remaining thing between
    # a mis-stubbed test and a live `gh pr create --repo cgfixit/CyClaw` is
    # whether that individual test remembered to stub or monkeypatch. `gh` is
    # absent from most dev containers but IS preinstalled on GitHub Actions
    # runners, so "it didn't fire locally" is not evidence.
    #
    # Before the flag was armed this role was played by a source constant that
    # no test could accidentally satisfy. This fixture restores that property
    # at the suite level rather than leaving it to per-test discipline.
    #
    # Tests that are ABOUT the armed posture opt out with:
    #     @pytest.mark.uses_shipped_execution_flag
    # and are then responsible for their own stubbing.
    if request.node.get_closest_marker("uses_shipped_execution_flag"):
        return
    try:
        import agentic.writer as _writer
    except ModuleNotFoundError as exc:
        # Only the absent agentic package itself means "nothing to disarm".
        # A ModuleNotFoundError naming anything else is a broken transitive
        # import INSIDE agentic/writer.py -- swallowing it would leave
        # EXECUTION_ENABLED armed for the whole session, so re-raise.
        if exc.name == "agentic" or (exc.name or "").startswith("agentic."):
            return
        raise
    monkeypatch.setattr(_writer, "EXECUTION_ENABLED", False)


# The loggers utils/logger.setup_logging attaches handlers to: the real root
# (the log file, while logging.capture_third_party is on), "cyclaw" (a console
# handler, plus the log file when capture is off) and "agentic" (the same
# console handler, and the log file when capture is off).
_SETUP_LOGGING_LOGGERS = ("", "cyclaw", "agentic")


@pytest.fixture(autouse=True)
def _remove_logging_handlers_the_test_added():
    # After every test, takes each handler the test added off the three
    # loggers above, and closes it. One handler can sit on two of them (the
    # console handler always, the log file when capture is off), so it comes
    # off both before it is closed, once. Handlers there before the test, such
    # as the ones gate.py's import-time setup_logging call attaches when a
    # module imports gate at collection, are left alone.
    #
    # Autouse, because setup_logging attaches handlers only on its first call
    # in a process, so which test does it depends on the run. In the full
    # suite, gate's import at collection makes that call before any test. In
    # a run that collects no module importing gate, the first test to reach
    # it does, often through an agentic CLI's main() without knowing it: when
    # only the files that mention setup_logging run, that is
    # tests/test_agentic_cli.py's test_status_runs. Its console handler stayed
    # on "cyclaw" and "agentic", bound to that test's capsys stream, which
    # pytest closes after the test, and a later test that flushed those
    # loggers' handlers failed with "I/O operation on closed file".
    #
    # The run-once guard is left as the test left it, so a later call is a
    # no-op, as in the full suite; isolated_logging below clears it for a test
    # that needs setup_logging to run. The logger levels setup_logging sets
    # are not restored.
    loggers = [logging.getLogger(name) for name in _SETUP_LOGGING_LOGGERS]
    before = [list(each.handlers) for each in loggers]
    yield
    added = []
    for each, kept in zip(loggers, before, strict=True):
        for handler in list(each.handlers):
            if handler not in kept:
                each.removeHandler(handler)
                if handler not in added:
                    added.append(handler)
    for handler in added:
        handler.close()


@pytest.fixture
def isolated_logging(monkeypatch):
    # For a test that runs setup_logging, directly or through a CLI's main():
    # clears its run-once guard, so the call attaches handlers even after an
    # earlier call in this process, and monkeypatch puts the session's value
    # back afterwards. The autouse fixture above removes what it attaches.
    monkeypatch.setattr(_logger_mod, "_logging_initialized", False)


@pytest.fixture
def test_config(tmp_path):
    # Deep-copy so each test gets a fully independent config tree. The old
    # ``TEST_CONFIG.copy()`` was a SHALLOW copy that only hand-cloned the
    # ``indexing`` and ``logging`` sub-dicts; every other nested dict (models,
    # policy, retrieval, security, ...) was a shared reference to the module-level
    # TEST_CONFIG. A test mutating e.g. ``cfg["models"]["grok"]["enabled"]`` or
    # appending to ``cfg["policy"]["prompt_filter"]["banned_patterns"]`` would
    # poison the global and leak into every later test (order-dependent flakes,
    # amplified under pytest-xdist). deepcopy removes that whole class of bug.
    cfg = copy.deepcopy(TEST_CONFIG)
    cfg["indexing"]["chroma_path"] = str(tmp_path / "chroma_db")
    cfg["indexing"]["bm25_path"] = str(tmp_path / "bm25.json")
    cfg["logging"]["log_file"] = str(tmp_path / "cyclaw.log")
    cfg["logging"]["audit_file"] = str(tmp_path / "audit.jsonl")
    cfg["logging"]["spend_file"] = str(tmp_path / "spend.jsonl")
    cfg["numbat"]["output_path"] = str(tmp_path / "numbat-events.ndjsonl")
    config_file = tmp_path / "config.yaml"
    with open(config_file, "w") as f:
        yaml.dump(cfg, f)
    return cfg, str(config_file)


# =============================================================================
# Class-style mocks + result constants used by test_graph.py / test_gate.py.
#
# These mirror the dependency-injection contract of build_graph(retriever, llm,
# grok, cfg, personality): each mock exposes the same call surface the graph
# nodes touch (retriever.hybrid_search / llm.generate / grok.generate) and the
# LLM/Grok mocks record their last prompt so tests can assert on prompt content.
# =============================================================================

MOCK_HIGH_SCORE_RESULTS = [
    SearchResult(text="Veeam uses chattr +i to make backups immutable.", score=0.92,
                 source="veeam-immutability.md", chunk_id=0, stem_tags=["veeam", "immut"],
                 retrieval_mode="hybrid", rrf_score=0.92, semantic_score=0.92, semantic_rank=0),
    SearchResult(text="Immutable backups cannot be modified or deleted.", score=0.81,
                 source="veeam-immutability.md", chunk_id=1, stem_tags=["immut", "backup"],
                 retrieval_mode="hybrid", rrf_score=0.81, semantic_score=0.81, semantic_rank=1),
]

MOCK_LOW_SCORE_RESULTS = [
    SearchResult(text="A weakly related passage about unrelated topics.", score=0.30,
                 source="misc.md", chunk_id=0, stem_tags=["misc"],
                 retrieval_mode="hybrid", rrf_score=0.30, semantic_score=0.30, semantic_rank=0),
]

MOCK_EMPTY_RESULTS: list[SearchResult] = []


class MockRetriever:
    """Stand-in for HybridRetriever that returns a fixed result list.

    ``rerank`` is what rerank_scores answers: None (reranker off, the default),
    a list of logits (cut to the number of texts asked about), or an exception
    instance, raised as the degraded reranker would raise it.
    """
    def __init__(self, results, rerank=None):
        self.results = results
        self.rerank = rerank
        self.rerank_calls = []

    def hybrid_search(self, query):
        return self.results

    def rerank_scores(self, query, texts):
        self.rerank_calls.append((query, list(texts)))
        if isinstance(self.rerank, BaseException):
            raise self.rerank
        if self.rerank is None:
            return None
        return list(self.rerank)[: len(texts)]

    def semantic_search(self, query, k=None):
        return self.results

    def keyword_search(self, query, k=None):
        return self.results


class MockLocalLLM:
    """Stand-in for LocalLLMClient; records the last prompt it was given."""
    def __init__(self, response="This is a test answer from the local LLM."):
        self.response = response
        self.last_prompt = None

    def generate(self, prompt, **kwargs):
        self.last_prompt = prompt
        self.last_spend_context = kwargs.get("spend_context")
        return self.response


class MockGrokClient:
    """Stand-in for GrokClient; records the last prompt it was given.

    ``available`` mirrors the real ``GrokClient.is_available()`` (True when a
    ``GROK_API_KEY`` is present). It defaults to True so existing routing tests
    still reach grok_fallback; set ``available=False`` to simulate Grok enabled
    in config but with no API key.
    """
    def __init__(self, response="This is a test answer from Grok.", available=True):
        self.response = response
        self.last_prompt = None
        self._available = available

    def is_available(self):
        return self._available

    def generate(self, prompt, **kwargs):
        self.last_prompt = prompt
        self.last_spend_context = kwargs.get("spend_context")
        return self.response


class MockClaudeClient(MockGrokClient):
    """Stand-in for ClaudeClient; same generate/is_available contract."""


@contextlib.contextmanager
def _mocked_gateway(tmp_path, *, peer=("127.0.0.1", 51234)):  # DevSkim: ignore DS162092,DS137138 - test loopback peer
    """Mocked-gateway TestClient shared by test_gate.py / test_edge_cases.py.

    Yields ``(test_client, mock_graph)``; per-test behavior differences are
    expressed by overriding ``mock_graph.invoke`` (return_value/side_effect).

    gate.py binds its config at module import time, so patching gate.open /
    gate.yaml.safe_load here would be dead code -- the real mechanism is the
    direct module-global assignment below, wrapped in save/restore so no mock
    leaks into the next test.

    ``peer`` is a parameter, not a constant, because gate's rate limiter is a
    process-global keyed per client IP with a 60 req/60 s budget: every file
    sharing one peer shares one budget, and a full-suite run can starve a
    later test (429 where 200/409 was asserted). Each consuming file picks its
    own loopback IP (127.0.0.0/8 is all loopback -- see
    gate._is_loopback_host).
    """
    # Lazy: conftest must import cleanly in minimal-dep CI jobs (e.g.
    # ollama-mock-smoke) that never install fastapi -- a top-level import
    # broke collection there (exit 4) on the first push of this fixture.
    from fastapi.testclient import TestClient

    from utils.logger import reset_config_cache
    reset_config_cache()

    cfg = copy.deepcopy(TEST_CONFIG)
    cfg["logging"]["audit_file"] = str(tmp_path / "audit.jsonl")
    cfg["logging"]["log_file"] = str(tmp_path / "gateway.log")
    cfg["numbat"]["output_path"] = str(tmp_path / "numbat-events.ndjsonl")

    with patch("gate.cfg", cfg), \
         patch("gate.HybridRetriever"), \
         patch("gate.LocalLLMClient"), \
         patch("gate.ClaudeClient"), \
         patch("gate.build_graph") as mock_build, \
         patch("gate.check_input", side_effect=lambda q: q), \
         patch("gate.check_all", return_value=[]):

        mock_graph = MagicMock()
        mock_graph.invoke.return_value = {
            "query": "test query",
            "answer": "Test answer from local LLM.",
            "answer_model": "local",
            "answer_sources": [
                {"source": "test.md", "score": 0.9, "chunk_id": 0, "stem_tags": ["test"], "text": "...", "mode": "hybrid"}
            ],
            "retrieved_docs": [{"text": "...", "score": 0.9, "source": "test.md", "chunk_id": 0, "stem_tags": [], "mode": "hybrid"}],
            "top_score": 0.9,
            "retrieval_mode": "hybrid",
            "needs_user_confirm": False,
            "audit_event": {}
        }
        mock_build.return_value = mock_graph

        import gate
        gate.cfg = cfg
        _globals = ("retriever", "local_llm", "grok", "claude", "compiled_graph")
        _saved = {k: getattr(gate, k, None) for k in _globals}
        try:
            gate.retriever = MockRetriever(MOCK_HIGH_SCORE_RESULTS)
            gate.local_llm = MockLocalLLM()
            gate.grok = None
            gate.claude = None
            gate.compiled_graph = mock_graph

            # base_url uses an allowed Host (localhost) so TrustedHostMiddleware
            # (added at import from the real config.yaml allowed_hosts) admits the
            # request; the default "testserver" host would otherwise 400.
            test_client = TestClient(
                gate.app,
                base_url="http://localhost",  # DevSkim: ignore DS162092,DS137138 - test loopback host
                # Starlette defaults the peer to ("testclient", 50000), which is
                # deliberately NOT loopback under _is_loopback_peer. A real
                # loopback peer exercises the ordinary local-operator case; the
                # non-loopback case is asserted explicitly in test_gate.py's
                # TestApiKeyOptionalPeer.
                client=peer,
            )
            yield test_client, mock_graph
        finally:
            for k, v in _saved.items():
                setattr(gate, k, v)

    reset_config_cache()


@pytest.fixture
def client(request, tmp_path):
    """Default mocked-gateway client: the (127.0.0.1, 51234) rate-limit bucket
    is the one test_gate.py has always used -- do not point a second file's
    fixture at it; give each file its own loopback IP via _mocked_gateway.

    Supports indirect parametrization: @pytest.mark.parametrize("client",
    [peer], indirect=True) overrides the peer, e.g. to give one test class its
    own rate-limit bucket. Direct use keeps the historical default peer."""
    peer = getattr(request, "param", ("127.0.0.1", 51234))
    with _mocked_gateway(tmp_path, peer=peer) as pair:
        yield pair


@pytest.fixture(autouse=True)
def _inject_argv_list_sandbox_except_hard_sandbox(request, monkeypatch):
    """Keep Linux/macOS CI green without a production software fallback.

    ``test_agentic_hard_sandbox.py`` is the only file allowed to call the real
    ``production_sandbox()`` factory so fail-closed stays covered.
    """
    path = getattr(request.node, "fspath", None)
    if path is not None and "test_agentic_hard_sandbox" in str(path):
        return
    from tests.executor_sandbox_double import inject_argv_list_sandbox

    inject_argv_list_sandbox(monkeypatch)
