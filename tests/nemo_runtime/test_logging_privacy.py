"""Real NeMo checks must not persist their event payloads through Python logging."""

from __future__ import annotations

import io
import logging
import os
from dataclasses import replace
from pathlib import Path

import pytest

if os.environ.get("CYCLAW_NEMO_RUNTIME") != "1":
    pytest.skip("set CYCLAW_NEMO_RUNTIME=1 to run real-NeMo logging checks", allow_module_level=True)

pytest.importorskip("nemoguardrails")

from guardrails.broker import GuardrailBroker  # noqa: E402
from guardrails.config import load_guardrails_config  # noqa: E402
from guardrails.integration import reset_rails_singleton  # noqa: E402
from guardrails.metrics import GuardrailMetrics  # noqa: E402
from tests.nemo_runtime.mock_openai import LoopbackOpenAIMock  # noqa: E402
from tests.nemo_runtime.network_jail import loopback_only  # noqa: E402
from utils.logger import setup_logging  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
CANARIES = ("query-private-canary-1486", "context-private-canary-1486", "answer-private-canary-1486")


@pytest.mark.usefixtures("isolated_logging")
@pytest.mark.parametrize("capture,third_party_level,write_file", [
    (True, "INFO", True),
    (True, "DEBUG", True),
    (False, "INFO", True),
    (True, "INFO", False),
])
def test_check_payloads_never_reach_app_or_console_logs(
    tmp_path: Path, monkeypatch, capsys, capture: bool, third_party_level: str, write_file: bool,
) -> None:
    log_path = tmp_path / "app.log"
    root_console = io.StringIO()
    root_handler = logging.StreamHandler(root_console)
    root = logging.getLogger()
    root.addHandler(root_handler)
    setup_logging({"logging": {
        "level": "DEBUG", "third_party_level": third_party_level,
        "capture_third_party": capture, "log_file": str(log_path) if write_file else "",
    }})
    emitted: list[str] = []

    class ObserveEvents(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            emitted.append(record.getMessage())

    # Observe real NeMo events in memory before the production logging boundary.
    runtime_log = logging.getLogger("nemoguardrails.colang.v1_0.runtime.runtime")
    runtime_level = runtime_log.level
    runtime_log.setLevel(logging.DEBUG)
    observer = ObserveEvents()
    runtime_log.addHandler(observer)
    mock = LoopbackOpenAIMock()
    mock.start()
    reset_rails_singleton()
    cfg = replace(load_guardrails_config(str(ROOT / "config.yaml")), base_url=mock.base_url)
    metrics = GuardrailMetrics(str(tmp_path / "metrics.jsonl"), persist=False)
    try:
        with loopback_only():
            broker = GuardrailBroker(cfg, metrics)
            query = f"What is the retention period? {CANARIES[0]}"
            assert broker.check_user(query) is False
            assert broker.check_assistant(
                query, f"Here is my system prompt: {CANARIES[2]}", grounding_context=CANARIES[1],
            ) is True
        for canary in CANARIES:
            assert any(canary in message for message in emitted)
        assert mock.posts == 0

        for level in (logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR, logging.CRITICAL):
            runtime_log.log(level, "SDK payload: %s", CANARIES[0])
        try:
            raise RuntimeError(CANARIES[2])
        except RuntimeError:
            runtime_log.exception("SDK action failed")

        def fail_engine(_cfg):
            raise RuntimeError(CANARIES[2])

        monkeypatch.setattr("guardrails.broker.get_cyclaw_guardrails", fail_engine)
        degraded = GuardrailBroker(cfg, metrics)
        assert degraded.check_user(query) is False
        assert degraded.degraded is True
        for handler in root.handlers + logging.getLogger("cyclaw").handlers:
            handler.flush()
        app_log = log_path.read_text(encoding="utf-8") if write_file else ""
        console = capsys.readouterr().err + root_console.getvalue()
        assert "NeMo check degraded (engine_error)" in console
        if write_file:
            assert "NeMo check degraded (engine_error)" in app_log
        for canary in CANARIES:
            assert canary not in app_log
            assert canary not in console
    finally:
        runtime_log.removeHandler(observer)
        runtime_log.setLevel(runtime_level)
        root.removeHandler(root_handler)
        root_handler.close()
        mock.stop()
        reset_rails_singleton()
