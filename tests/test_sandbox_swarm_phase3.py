"""Pins CyClaw-Sandbox corpus construction and failure reporting.

Codex review on #1401: initializing `chunks = []` before the try still left
the list empty when `rank_bm25` was missing, so Chroma recorded a pass with
zero documents. Chunk text must be built before BM25-only imports.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_CLAUDE = _REPO / ".claude" / "skills" / "CyClaw-Sandbox" / "run_full_verification.py"
_CODEX = _REPO / ".codex" / "skills" / "Cyclaw-Sandbox" / "run_full_verification.py"


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
    monkeypatch.setattr(module, "_probe_ollama_tier", lambda: 0)

    def query_failure():
        raise RuntimeError("query phase failed")

    monkeypatch.setattr(module, "phase_execute_queries", query_failure)
    for name, phase_name in (
        ("phase_config_invariants", "Config Invariants"),
        ("phase_telemetry_kill", "Telemetry Kill"),
        ("phase_build_corpus", "Corpus & Index"),
        ("phase_triple_gate", "Triple-Gate Online API"),
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
    monkeypatch.setattr(module, "_probe_ollama_tier", lambda: 0)

    def query_failure():
        raise RuntimeError("query phase failed")

    monkeypatch.setattr(module, "phase_execute_queries", query_failure)
    for name, phase_name in (
        ("phase_config_invariants", "Config Invariants"),
        ("phase_telemetry_kill", "Telemetry Kill"),
        ("phase_build_corpus", "Corpus & Index"),
        ("phase_triple_gate", "Triple-Gate Online API"),
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
