"""Stdlib regression checks for sandbox verdicts; no app, services or installs."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "sandbox_verifier", Path(__file__).with_name("run_full_verification.py")
)
verifier = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = verifier
spec.loader.exec_module(verifier)


class VerificationContract(unittest.TestCase):
    def test_changed_queries_cannot_default_to_pass(self):
        # Execute the real query phase with controlled node outcomes. Three
        # miss queries used to bypass assertions after their text changed.
        graph = types.ModuleType("graph")
        graph.retrieve_node = lambda state, *_: {"retrieved_docs": ["fixture"]}
        graph.audit_logger_node = lambda *_: {}
        graph.local_llm_node = lambda *_: {"answer_model": "local"}
        graph.user_gate_node = lambda *_: {"needs_user_confirm": True}
        retrieval = types.ModuleType("retrieval")
        retrieval.embeddings = types.ModuleType("retrieval.embeddings")
        hybrid = types.ModuleType("retrieval.hybrid_search")
        hybrid.HybridRetriever = lambda: object()
        modules = {
            "graph": graph, "retrieval": retrieval,
            "retrieval.embeddings": retrieval.embeddings,
            "retrieval.hybrid_search": hybrid,
            "yaml": types.SimpleNamespace(safe_load=lambda _: {}),
        }
        cases = (
            (False, "offline-best-effort", [True] * 5),
            (True, "offline-best-effort", [True, True, False, False, False]),
            (False, "wrong-model", [True, True, False, True, True]),
        )
        with tempfile.TemporaryDirectory() as tmp, contextlib.chdir(tmp), patch.dict(sys.modules, modules):
            Path("config.yaml").write_text("{}", encoding="utf-8")
            with patch.object(verifier, "RESULTS_FILE", Path(tmp) / "queries.json"):
                for force_local, offline_model, expected in cases:
                    with self.subTest(force_local=force_local, offline_model=offline_model):
                        graph.route_by_score_node = lambda state, *_, force_local=force_local: {
                            "needs_user_confirm": not force_local and state["query"] not in
                            {"what is CyClaw", "explain CyClaw security"}
                        }
                        graph.offline_best_effort_node = lambda *_, offline_model=offline_model: {"answer_model": offline_model}
                        with contextlib.redirect_stdout(io.StringIO()):
                            result = verifier.phase_execute_queries()
                        self.assertEqual([check.passed for check in result.checks], expected)

    def test_report_survives_phase_failure_and_labels_its_own_results(self):
        phases = (
            "phase_config_invariants", "phase_telemetry_kill", "phase_build_corpus",
            "phase_execute_queries", "phase_triple_gate", "phase_audit_integrity",
            "phase_key_redaction", "phase_metrics_and_invariants",
            "phase_terminal_consoles", "phase_terminal_html",
        )
        for broken_query_phase in (False, True):
            with self.subTest(broken_query_phase=broken_query_phase), contextlib.ExitStack() as stack:
                tmp = stack.enter_context(tempfile.TemporaryDirectory())
                stack.enter_context(contextlib.chdir(tmp))
                for setup in ("_install_stubs", "_ensure_repo", "_install_deps"):
                    stack.enter_context(patch.object(verifier, setup, return_value=False))
                for phase_name in phases:
                    def fake_phase(name=phase_name, broken_query_phase=broken_query_phase):
                        if name == "phase_execute_queries" and broken_query_phase:
                            raise RuntimeError("synthetic query phase failure")
                        return verifier.PhaseResult(name, [verifier.Check(
                            f"check-{n}", name != "phase_key_redaction"
                        ) for n in range(5)])
                    fake_phase.__name__ = phase_name
                    stack.enter_context(patch.object(verifier, phase_name, fake_phase))
                # No listener may turn in-process mocks into real-model evidence.
                stack.enter_context(patch("urllib.request.urlopen", side_effect=AssertionError("unexpected probe")))
                output = stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
                stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
                self.assertEqual(verifier.main(), 1)
                report = json.loads(Path("verification_report.json").read_text(encoding="utf-8"))
                self.assertEqual(report["ollama_tier"], 0)
                self.assertIn("\nphase_key_redaction: FAIL\n", output.getvalue())
                self.assertIn("\nphase_audit_integrity: PASS\n", output.getvalue())
                if broken_query_phase:
                    self.assertFalse(report["phases"][3]["passed"])
                    self.assertIn("synthetic query phase failure", report["phases"][3]["checks"][0]["detail"])


if __name__ == "__main__":
    unittest.main()
