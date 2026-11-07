"""Pins CyClaw-Sandbox corpus construction and failure reporting.

Codex review on #1401: initializing `chunks = []` before the try still left
the list empty when `rank_bm25` was missing, so Chroma recorded a pass with
zero documents. Chunk text must be built before BM25-only imports.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import types
from pathlib import Path
from typing import Any

import pytest
import yaml

_REPO = Path(__file__).resolve().parents[1]
_CLAUDE = _REPO / ".claude" / "skills" / "CyClaw-Sandbox" / "run_full_verification.py"
_CODEX = _REPO / ".agents" / "skills" / "cyclaw-sandbox" / "run_full_verification.py"


def _load_claude_verifier():
    spec = importlib.util.spec_from_file_location("cyclaw_sandbox_verifier_test", _CLAUDE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_codex_verifier():
    spec = importlib.util.spec_from_file_location("cyclaw_codex_sandbox_verifier_test", _CODEX)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _stub_codex_phases_except_queries(module, monkeypatch, query_fn) -> None:
    monkeypatch.setattr(module, "phase_execute_queries", query_fn)
    for name, phase_name in (
        ("phase_config_invariants", "Config Invariants"),
        ("phase_telemetry_kill", "Telemetry Kill"),
        ("phase_build_corpus", "Corpus & Index"),
        ("phase_triple_gate", "Triple-Gate Online API"),
        ("phase_audit_integrity", "Audit Integrity"),
        ("phase_key_redaction", "Key Redaction"),
        ("phase_metrics_and_invariants", "Metrics & Invariants"),
        ("phase_terminal_consoles", "Terminal Consoles"),
        ("phase_terminal_html", "Terminal HTML Contract"),
    ):
        monkeypatch.setattr(
            module,
            name,
            lambda phase_name=phase_name: module.PhaseResult(phase_name, [module.Check("ok", True)]),
        )


def _phase3(text: str) -> str:
    start = text.index("def phase_build_corpus")
    end = text.index("def phase_execute_queries")
    return text[start:end]


def test_claude_swarm_builds_chunks_before_stemmer_import() -> None:
    phase = _phase3(_CLAUDE.read_text(encoding="utf-8"))
    assert phase.index('chunks.append({"text": text') < phase.index("from retrieval.stemmer import tokenize_and_stem")
    assert 'raise ValueError("no chunks to index")' in phase


def test_codex_swarm_builds_chunks_before_stemmer_import() -> None:
    phase = _phase3(_CODEX.read_text(encoding="utf-8"))
    assert phase.index('chunks.append({"text": text') < phase.index("from retrieval.stemmer import tokenize_and_stem")
    assert 'raise ValueError("no chunks to index")' in phase


def test_claude_swarm_writes_report_when_query_phase_raises(tmp_path, monkeypatch) -> None:
    module = _load_claude_verifier()

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(module, "_install_stubs", lambda: None)
    monkeypatch.setattr(module, "_ensure_repo", lambda: None)

    def query_failure():
        raise RuntimeError("query phase failed")

    monkeypatch.setattr(module, "phase_execute_queries", query_failure)
    for name, phase_name in (
        ("phase_config_invariants", "Config Invariants"),
        ("phase_telemetry_kill", "Telemetry Kill"),
        ("phase_build_corpus", "Corpus & Index"),
        ("phase_triple_gate", "Triple-Gate Online API"),
        ("phase_audit_integrity", "Audit Integrity"),
        ("phase_key_redaction", "Key Redaction"),
        ("phase_metrics_and_invariants", "Metrics & Invariants"),
        ("phase_terminal_consoles", "Terminal Consoles"),
        ("phase_terminal_html", "Terminal HTML Contract"),
    ):
        monkeypatch.setattr(
            module,
            name,
            lambda phase_name=phase_name: module.PhaseResult(phase_name, [module.Check("ok", True)]),
        )

    assert module.main() == 1
    report = json.loads((tmp_path / "verification_report.json").read_text(encoding="utf-8"))
    assert any(
        check["name"] == "phase_error" and check["detail"] == "query phase failed"
        for phase in report["phases"]
        for check in phase["checks"]
    )


def test_claude_swarm_default_clone_uses_fixed_destination(tmp_path, monkeypatch) -> None:
    module = _load_claude_verifier()
    clone = tmp_path / "CyClaw"
    calls = []

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CYCLAW_REPO", raising=False)
    monkeypatch.setattr(module, "CYCLAW_DIR", clone)
    monkeypatch.setattr(module.shutil, "which", lambda name: "/usr/bin/git")
    monkeypatch.setattr(module.subprocess, "run", lambda argv, **kwargs: calls.append((argv, kwargs)))

    module._ensure_repo()

    assert calls == [
        (
            ["/usr/bin/git", "clone", "--depth", "1", "--branch", "main", module.REPO_URL, "."],
            {"cwd": clone, "check": True, "capture_output": True},
        )
    ]


def test_claude_swarm_import_does_not_create_temp_clone(monkeypatch) -> None:
    import tempfile

    monkeypatch.delenv("CYCLAW_REPO", raising=False)
    before = set(Path(tempfile.gettempdir()).glob("cyclaw-sandbox-*"))
    module = _load_claude_verifier()
    after = set(Path(tempfile.gettempdir()).glob("cyclaw-sandbox-*"))
    assert after == before
    assert module.CYCLAW_DIR is None
    assert module._OWNED_TEMP_ROOT is None


def test_claude_swarm_removes_owned_temp_clone(tmp_path, monkeypatch) -> None:
    module = _load_claude_verifier()
    owned = tmp_path / "owned"
    clone = owned / "CyClaw"
    clone.mkdir(parents=True)
    (clone / "query_results.json").write_text("{}", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CYCLAW_REPO", raising=False)
    monkeypatch.setattr(module, "CYCLAW_DIR", clone)
    monkeypatch.setattr(module, "_OWNED_TEMP_ROOT", owned)
    monkeypatch.setattr(module, "_install_stubs", lambda: None)
    monkeypatch.setattr(module, "_ensure_repo", lambda: None)

    def query_failure():
        raise RuntimeError("query phase failed")

    monkeypatch.setattr(module, "phase_execute_queries", query_failure)
    for name, phase_name in (
        ("phase_config_invariants", "Config Invariants"),
        ("phase_telemetry_kill", "Telemetry Kill"),
        ("phase_build_corpus", "Corpus & Index"),
        ("phase_triple_gate", "Triple-Gate Online API"),
        ("phase_audit_integrity", "Audit Integrity"),
        ("phase_key_redaction", "Key Redaction"),
        ("phase_metrics_and_invariants", "Metrics & Invariants"),
        ("phase_terminal_consoles", "Terminal Consoles"),
        ("phase_terminal_html", "Terminal HTML Contract"),
    ):
        monkeypatch.setattr(
            module,
            name,
            lambda phase_name=phase_name: module.PhaseResult(phase_name, [module.Check("ok", True)]),
        )

    assert module.main() == 1
    assert not owned.exists()
    report = json.loads((tmp_path / "verification_report.json").read_text(encoding="utf-8"))
    assert report["total_checks"] >= 1
    assert (tmp_path / "query_results.json").is_file()


def test_codex_swarm_default_clone_uses_assigned_destination(tmp_path, monkeypatch) -> None:
    module = _load_codex_verifier()
    clone = tmp_path / "CyClaw"
    calls = []

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CYCLAW_REPO", raising=False)
    monkeypatch.delenv("CYCLAW_SKIP_ENSURE", raising=False)
    monkeypatch.setattr(module, "CYCLAW_DIR", clone)
    monkeypatch.setattr(module.shutil, "which", lambda name: "/usr/bin/git")
    monkeypatch.setattr(module.subprocess, "run", lambda argv, **kwargs: calls.append((argv, kwargs)))

    module._ensure_repo()

    assert calls == [
        (
            ["/usr/bin/git", "clone", "--depth", "1", "--branch", "main", module.REPO_URL, "."],
            {"cwd": clone, "check": True, "capture_output": True},
        )
    ]


def test_codex_swarm_import_does_not_create_temp_clone(monkeypatch) -> None:
    import tempfile

    monkeypatch.delenv("CYCLAW_REPO", raising=False)
    monkeypatch.delenv("CYCLAW_SKIP_ENSURE", raising=False)
    before = set(Path(tempfile.gettempdir()).glob("cyclaw-sandbox-*"))
    module = _load_codex_verifier()
    after = set(Path(tempfile.gettempdir()).glob("cyclaw-sandbox-*"))
    assert after == before
    assert module.CYCLAW_DIR is None
    assert module._OWNED_TEMP_ROOT is None


def test_codex_swarm_removes_owned_temp_clone(tmp_path, monkeypatch) -> None:
    module = _load_codex_verifier()
    owned = tmp_path / "owned"
    clone = owned / "CyClaw"
    clone.mkdir(parents=True)
    (clone / "query_results.json").write_text("{}", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CYCLAW_REPO", raising=False)
    monkeypatch.delenv("CYCLAW_SKIP_ENSURE", raising=False)
    monkeypatch.setattr(module, "CYCLAW_DIR", clone)
    monkeypatch.setattr(module, "_OWNED_TEMP_ROOT", owned)
    monkeypatch.setattr(module, "_install_stubs", lambda: None)
    monkeypatch.setattr(module, "_ensure_repo", lambda: None)
    monkeypatch.setattr(module, "_install_deps", lambda: False)

    def query_failure():
        raise RuntimeError("query phase failed")

    _stub_codex_phases_except_queries(module, monkeypatch, query_failure)

    assert module.main() == 1
    assert not owned.exists()
    report = json.loads((tmp_path / "verification_report.json").read_text(encoding="utf-8"))
    assert report["total_checks"] >= 1
    assert (tmp_path / "query_results.json").is_file()
    assert not (tmp_path / "cyclaw-sandbox-query-results.json").exists()
    assert module.CYCLAW_DIR is None
    assert module._OWNED_TEMP_ROOT is None
    new_dir = module._resolve_cyclaw_dir()
    try:
        assert new_dir != clone
        assert module._OWNED_TEMP_ROOT is not None
        assert new_dir.parent == module._OWNED_TEMP_ROOT
        assert module._OWNED_TEMP_ROOT.exists()
        assert not clone.exists()
    finally:
        if module._OWNED_TEMP_ROOT is not None:
            shutil.rmtree(module._OWNED_TEMP_ROOT, ignore_errors=True)
            module._OWNED_TEMP_ROOT = None
            module.CYCLAW_DIR = None


def test_codex_swarm_does_not_persist_stale_shared_results_file(tmp_path, monkeypatch) -> None:
    module = _load_codex_verifier()
    owned = tmp_path / "owned"
    clone = owned / "CyClaw"
    clone.mkdir(parents=True)
    start_cwd = tmp_path / "invoke"
    start_cwd.mkdir()

    stale = tmp_path / "shared" / "cyclaw-sandbox-query-results.json"
    stale.parent.mkdir()
    stale.write_text('{"stale": true}', encoding="utf-8")

    monkeypatch.chdir(start_cwd)
    monkeypatch.delenv("CYCLAW_REPO", raising=False)
    monkeypatch.delenv("CYCLAW_SKIP_ENSURE", raising=False)
    monkeypatch.setattr(module, "CYCLAW_DIR", clone)
    monkeypatch.setattr(module, "_OWNED_TEMP_ROOT", owned)
    monkeypatch.setattr(module, "RESULTS_FILE", stale)
    monkeypatch.setattr(module, "_install_stubs", lambda: None)
    monkeypatch.setattr(module, "_ensure_repo", lambda: None)
    monkeypatch.setattr(module, "_install_deps", lambda: False)

    def query_failure():
        raise RuntimeError("query phase failed")

    _stub_codex_phases_except_queries(module, monkeypatch, query_failure)

    assert module.main() == 1
    assert not owned.exists()
    assert not (start_cwd / "cyclaw-sandbox-query-results.json").exists()
    assert not (start_cwd / stale.name).exists()
    assert not (start_cwd / "query_results.json").exists()


@pytest.mark.parametrize("failure", [None, "dropped_audit", "failed_flush", "non_object"])
def test_claude_audit_phase_requires_current_sanitized_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str | None,
) -> None:
    from utils import logger, numbat_emitter

    module = _load_claude_verifier()
    monkeypatch.chdir(tmp_path)
    cfg = yaml.safe_load((_REPO / "config.yaml").read_text(encoding="utf-8"))
    audit = tmp_path / "audit.jsonl"
    cfg["logging"]["audit_file"] = str(audit)
    cfg["numbat"]["output_path"] = str(tmp_path / "numbat.ndjson")
    (tmp_path / "config.yaml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
    for index in range(5):
        logger.audit_log({"event": "rag_query", "query": f"synthetic-{index}"}, cfg=cfg)
    if failure == "dropped_audit":
        monkeypatch.setattr(logger, "audit_log", lambda *_args, **_kwargs: None)
    elif failure == "failed_flush":
        monkeypatch.setattr(numbat_emitter, "flush_numbat_writes", lambda: False)
    elif failure == "non_object":
        with audit.open("a", encoding="utf-8") as stream:
            stream.write("[]\n")

    result = module.phase_audit_integrity()

    assert result.passed is (failure is None), [(check.name, check.passed) for check in result.checks]
    assert "sandbox-audit-query" not in audit.read_text(encoding="utf-8")
    assert "sandbox-secret-token" not in audit.read_text(encoding="utf-8")


@pytest.mark.parametrize("failure", [None, "error", "no_call", "wrong_answer", "extra_call"])
def test_claude_query_verdicts_and_custom_report_need_no_local_listener(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str | None,
) -> None:
    module = _load_claude_verifier()

    def answer(state: dict[str, str], llm: Any, model: str) -> dict[str, str]:
        text = llm.response if failure == "no_call" else llm.generate(state["query"])
        if failure == "extra_call":
            llm.generate(state["query"])
        result = {"answer_model": model, "answer": "wrong answer" if failure == "wrong_answer" else text}
        if failure == "error":
            result["error"] = "ENDPOINT_TRUST: synthetic refusal"
        return result

    graph = types.ModuleType("graph")
    graph.retrieve_node = lambda *_args: {"retrieved_docs": ["fixture"]}
    graph.route_by_score_node = lambda state, *_args: {
        "needs_user_confirm": state["query"] not in {"what is CyClaw", "explain CyClaw security"},
    }
    graph.local_llm_node = lambda state, llm, _cfg: answer(state, llm, "local")
    graph.user_gate_node = lambda *_args: {"needs_user_confirm": True}
    graph.offline_best_effort_node = lambda state, llm, _cfg: answer(state, llm, "offline-best-effort")
    graph.audit_logger_node = lambda *_args: {}
    embeddings = types.ModuleType("retrieval.embeddings")
    retrieval = types.ModuleType("retrieval")
    retrieval.embeddings = embeddings
    hybrid = types.ModuleType("retrieval.hybrid_search")
    hybrid.HybridRetriever = lambda: object()
    for name, stub in {
        "graph": graph, "retrieval": retrieval, "retrieval.embeddings": embeddings,
        "retrieval.hybrid_search": hybrid, "chromadb": types.ModuleType("chromadb"),
    }.items():
        monkeypatch.setitem(sys.modules, name, stub)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.yaml").write_text("{}", encoding="utf-8")
    report = tmp_path / "external" / "queries.json"
    monkeypatch.setattr(module, "RESULTS_FILE", report)
    monkeypatch.setattr("urllib.request.urlopen", lambda *_a, **_k: pytest.fail("unexpected listener probe"))

    result = module.phase_execute_queries()
    assert [check.passed for check in result.checks] == [failure is None] * 3 + [True, True]
    assert report.read_bytes() == (tmp_path / "query_results.json").read_bytes()
    assert json.loads(report.read_text(encoding="utf-8"))["ollama_tier"] == 0

    if failure is None:
        graph.route_by_score_node = lambda *_args: {"needs_user_confirm": False}
        result = module.phase_execute_queries()
        assert [check.passed for check in result.checks] == [True, True, False, False, False]


def test_claude_telemetry_phase_detects_unapplied_values(monkeypatch: pytest.MonkeyPatch) -> None:
    from utils import telemetry_kill

    module = _load_claude_verifier()
    monkeypatch.chdir(_REPO)
    monkeypatch.setattr(telemetry_kill, "apply_telemetry_kill", lambda: {})

    result = module.phase_telemetry_kill()

    assert not result.passed
    assert any(check.name.startswith("telemetry_kill_value_") and not check.passed for check in result.checks)


def test_claude_skip_ensure_requires_prepared_checkout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_claude_verifier()
    monkeypatch.setenv("CYCLAW_SKIP_ENSURE", "1")
    monkeypatch.delenv("CYCLAW_REPO", raising=False)
    with pytest.raises(RuntimeError, match="requires CYCLAW_REPO"):
        module._resolve_cyclaw_dir()
    assert module._OWNED_TEMP_ROOT is None
    monkeypatch.setenv("CYCLAW_REPO", str(tmp_path))
    with pytest.raises(RuntimeError, match="existing git checkout"):
        module._ensure_repo()
    (tmp_path / ".git").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(module.subprocess, "run", lambda *_a, **_k: pytest.fail("unexpected git operation"))
    module._ensure_repo()
    assert module.CYCLAW_DIR == tmp_path


def test_claude_missing_graph_dependency_refuses_synthetic_replacement(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins

    module = _load_claude_verifier()
    real_import = builtins.__import__

    def without_langgraph(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "langgraph.graph":
            raise ImportError("synthetic missing dependency")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_langgraph)
    with pytest.raises(RuntimeError, match="project dependencies are missing"):
        module._install_stubs()


def test_claude_empty_phase_cannot_report_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_claude_verifier()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(module, "_install_stubs", lambda: None)
    monkeypatch.setattr(module, "_ensure_repo", lambda: None)
    _stub_codex_phases_except_queries(module, monkeypatch, lambda: module.PhaseResult("5 Queries"))

    assert module.main() == 1
    report = json.loads((tmp_path / "verification_report.json").read_text(encoding="utf-8"))
    assert report["ollama_tier"] == 0
    assert report["phases"][3]["passed"] is False
