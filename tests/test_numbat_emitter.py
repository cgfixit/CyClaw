"""Tests for the Numbat dual-write emitter (#959 / #961).

The emitter is a projection: audit.jsonl stays authoritative, and every
failure path must degrade rather than raise.
"""

from __future__ import annotations

import ast
import json
import logging
import os
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path
from unittest import mock

import pytest
import yaml

from utils import numbat_emitter
from utils.logger import reset_config_cache
from utils.numbat_emitter import (
    SCHEMA_VERSION,
    build_endpoint,
    build_event,
    close_numbat_handles,
    emit_numbat_command,
    emit_numbat_event,
    posix_path,
    redact_argv_for_numbat,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_CORE = ("gate.py", "gate_ops.py", "gate_auth.py", "gate_memory.py", "graph.py", "mcp_hybrid_server.py")
_REQUIRED = {
    "schema_version",
    "record_type",
    "run_id",
    "endpoint",
    "event_id",
    "source_agent",
    "source_type",
    "event_type",
    "confidence",
    "evidence",
}


@pytest.fixture(autouse=True)
def _clear_config_cache():
    reset_config_cache()
    yield
    # write_ndjson now caches its append handle per output path (mirroring
    # utils/logger.py's _AUDIT_HANDLES) instead of open/close per event --
    # release it here so tmp_path teardown can remove the directory (Windows
    # cannot delete a file that is still open).
    close_numbat_handles()
    reset_config_cache()


@pytest.fixture
def numbat_cfg(tmp_path: Path) -> tuple[str, Path]:
    out = tmp_path / "numbat-events.ndjsonl"
    cfg = {
        "logging": {"audit_file": str(tmp_path / "audit.jsonl")},
        "numbat": {
            "enabled": True,
            "output_path": str(out),
            "source_agent": "unknown",
            "source_type": "hook",
        },
    }
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return str(path), out


def test_redact_argv_strips_reason_and_sql() -> None:
    joined = redact_argv_for_numbat(
        ["python", "-m", "agentic.cli", "--reason=secret reason", "--sql", "SELECT 1"]
    )
    assert "secret reason" not in joined
    assert "SELECT 1" not in joined
    assert "--reason=<redacted>" in joined
    assert "<redacted>" in joined


def test_redact_argv_strips_an_fsconnect_search_pattern() -> None:
    # /ops/fsconnect's grep text reached the stream verbatim while fsconnect's
    # own audit record leaves it out; a search can be for a secret.
    argv = ["python", "-m", "agentic.fsconnect.cli", "grep", "--root=docs", "--path=notes.md",
            "--pattern=AKIAEXAMPLEKEY123"]
    joined = redact_argv_for_numbat(argv)
    assert "AKIAEXAMPLEKEY123" not in joined
    assert "--pattern=<redacted>" in joined
    assert "--root=docs" in joined and "--path=notes.md" in joined  # rules key on these
    assert "AKIAEXAMPLEKEY123" not in redact_argv_for_numbat(["fsconnect", "--pattern", "AKIAEXAMPLEKEY123"])


def test_redact_argv_is_one_shell_word_per_token() -> None:
    """The pinned CLI parses ``command`` as shell. A bare ``<redacted>`` read
    as a redirect and failed the whole event (issue #1458 Phase 4)."""
    import shlex

    argv = ["python", "-m", "agentic.cli", "--reason=r", "--instruction", "i", "--path", "/tmp/my dir", "a;b|c"]
    joined = redact_argv_for_numbat(argv)
    assert shlex.split(joined) == [
        "python", "-m", "agentic.cli", "--reason=<redacted>", "--instruction", "<redacted>",
        "--path", "/tmp/my dir", "a;b|c",
    ]
    # Plain tokens stay unquoted, so ordinary commands read exactly as before.
    assert redact_argv_for_numbat(["python", "-m", "pytest", "-q", "--tb=short"]) == "python -m pytest -q --tb=short"


def test_build_event_caps_content_preview_at_the_schema_limit() -> None:
    record = build_event("prompt.user", content_preview="x" * 500)
    assert record["content_preview"] == "x" * numbat_emitter.CONTENT_PREVIEW_MAX_CHARS
    assert record["content_preview_truncated"] is True


def test_build_event_marks_only_real_truncation() -> None:
    fits = build_event("prompt.user", content_preview="y" * numbat_emitter.CONTENT_PREVIEW_MAX_CHARS)
    assert "content_preview_truncated" not in fits
    flagged = build_event("prompt.user", content_preview="{}", content_preview_truncated=True)
    assert flagged["content_preview_truncated"] is True
    # A truncation flag with no preview to describe is dropped, not emitted alone.
    orphan = build_event("prompt.user", content_preview_truncated=True)
    assert "content_preview_truncated" not in orphan


def test_posix_path_normalizes_backslashes() -> None:
    assert posix_path(r"C:\Users\x\file") == "C:/Users/x/file"
    assert posix_path("") is None
    assert posix_path(None) is None


def test_build_event_is_schema_legal() -> None:
    record = build_event(
        "command.exec",
        command="python -m pytest -q",
        exit_code=0,
        file_path="/tmp/worktree",
        tags=["executor"],
        artifact_type="executor",
    )
    assert set(_REQUIRED) <= set(record)
    assert record["schema_version"] == SCHEMA_VERSION
    assert SCHEMA_VERSION == "0.3.0"
    assert record["record_type"] == "event"
    assert record["source_agent"] == "unknown"
    assert record["source_type"] == "hook"
    assert record["tags"][0] == "cyclaw"
    assert "executor" in record["tags"]
    assert set(record["endpoint"]) <= {"hostname", "os", "arch", "username", "uid", "device_id"}
    for key in ("hostname", "os", "arch", "username", "uid"):
        assert record["endpoint"][key]
    assert record["evidence"]["artifact_type"] == "executor"
    assert record["evidence"]["local_path"]
    assert "exit_code" not in record
    assert "file_path" not in record


def test_command_result_keeps_exit_code() -> None:
    record = build_event(
        "command.result",
        command="python -m pytest -q",
        exit_code=0,
        duration_ms=12,
        tags=["executor"],
        artifact_type="executor",
    )
    assert record["exit_code"] == 0
    assert record["duration_ms"] == 12
    assert record["command"] == "python -m pytest -q"


def test_source_agent_cyclaw_is_forced_to_unknown() -> None:
    record = build_event("file.read", cfg={"numbat": {"source_agent": "cyclaw"}})
    assert record["source_agent"] == "unknown"


def test_unknown_event_type_raises_in_builder_but_emit_swallows() -> None:
    with pytest.raises(ValueError, match="unsupported event_type"):
        build_event("not.a.type")
    emit_numbat_event("not.a.type")  # must not raise


def test_emit_writes_one_ndjson_line(numbat_cfg: tuple[str, Path]) -> None:
    config_path, out = numbat_cfg
    emit_numbat_command(
        "python -m ruff check .",
        exit_code=0,
        tool_name="executor",
        tags=["executor", "ruff"],
        config_path=config_path,
    )
    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    exec_record = json.loads(lines[0])
    result_record = json.loads(lines[1])
    assert exec_record["event_type"] == "command.exec"
    assert exec_record["command"] == "python -m ruff check ."
    assert "exit_code" not in exec_record
    assert result_record["event_type"] == "command.result"
    assert result_record["exit_code"] == 0
    assert "cyclaw" in exec_record["tags"]


def test_disabled_is_a_noop(tmp_path: Path) -> None:
    out = tmp_path / "numbat-events.ndjsonl"
    cfg = {"numbat": {"enabled": False, "output_path": str(out)}}
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    emit_numbat_event("command.exec", command="echo hi", config_path=str(path))
    assert not out.exists()


def test_executor_emits_command_exec(tmp_path: Path, numbat_cfg: tuple[str, Path]) -> None:
    from agentic.executor import Check, run_verification

    config_path, out = numbat_cfg
    cfg = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
    report = run_verification(
        tmp_path,
        [Check("ok", ("python", "-c", "print(1)"))],
        config_path=config_path,
        cfg=cfg,
    )
    assert report.ok
    records = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    # The mainline audit trail now projects into the same file
    # (artifact_type "cyclaw_audit_jsonl"); this test asserts the executor's
    # action-plane records, so exclude the audit projection.
    records = [r for r in records if r["evidence"]["artifact_type"] != "cyclaw_audit_jsonl"]
    assert len(records) == 2
    assert records[0]["event_type"] == "command.exec"
    assert records[0]["tool_name"] == "executor"
    assert "exit_code" not in records[0]
    assert records[1]["event_type"] == "command.result"
    assert records[1]["exit_code"] == 0


def test_ops_runner_redacts_reason(monkeypatch: pytest.MonkeyPatch, numbat_cfg: tuple[str, Path]) -> None:
    import subprocess

    from utils import ops_runner

    config_path, out = numbat_cfg
    cfg = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
    monkeypatch.setattr(ops_runner, "_get_config", lambda *_a, **_k: cfg)
    monkeypatch.setattr("utils.numbat_emitter._get_config", lambda *_a, **_k: cfg)

    def _fake_run(argv, *, timeout_sec=None):
        del timeout_sec
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout="{}", stderr="")

    monkeypatch.setattr(ops_runner, "_run", _fake_run)
    ops_runner.run_agentic_op(
        "apply-skill",
        name="demo",
        desc="desc",
        reason="super secret reason",
        confirm=True,
    )
    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    blob = "\n".join(lines)
    assert "super secret reason" not in blob
    record = json.loads(lines[0])
    assert "--reason=<redacted>" in record["command"]
    assert record["tags"][-1] == "apply-skill"
    assert json.loads(lines[1])["event_type"] == "command.result"


def test_core_modules_do_not_import_emitter() -> None:
    for name in _CORE:
        tree = ast.parse((_REPO_ROOT / name).read_text(encoding="utf-8"), filename=name)
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
        assert not any("numbat_emitter" in item for item in imported), name


def test_emitter_does_not_import_core() -> None:
    tree = ast.parse((_REPO_ROOT / "utils" / "numbat_emitter.py").read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module.split(".", 1)[0])
    assert not ({"gate", "gate_ops", "gate_auth", "gate_memory", "graph", "mcp_hybrid_server"} & set(imported))


def test_endpoint_shape() -> None:
    endpoint = build_endpoint()
    assert set(endpoint) >= {"hostname", "os", "arch", "username", "uid"}
    assert set(endpoint) <= {"hostname", "os", "arch", "username", "uid", "device_id"}


def test_tool_result_strips_illegal_action_fields() -> None:
    record = build_event(
        "tool.result",
        command="echo hi",
        file_path="/tmp/x",
        exit_code=0,
        duration_ms=5,
        tool_name="fsconnect",
    )
    assert "command" not in record
    assert "file_path" not in record
    assert "exit_code" not in record
    assert "duration_ms" not in record
    assert record["tool_name"] == "fsconnect"


def test_file_read_keeps_path_drops_command() -> None:
    record = build_event(
        "file.read",
        file_path="README.md",
        command="cat README.md",
        exit_code=0,
        tool_name="fsconnect",
    )
    assert record["file_path"] == "README.md"
    assert record["tool_name"] == "fsconnect"
    assert "command" not in record
    assert "exit_code" not in record


def test_session_start_strips_action_fields() -> None:
    record = build_event(
        "session.start",
        command="python",
        file_path="/tmp",
        exit_code=0,
        tool_name="executor",
        actor="system",
    )
    assert "command" not in record
    assert "file_path" not in record
    assert "exit_code" not in record
    assert "tool_name" not in record
    assert record["actor"] == "system"


def test_forbidden_map_covers_every_event_type() -> None:
    from utils import numbat_emitter as ne

    assert set(ne._EVENT_TYPE_FORBIDDEN_FIELDS) == ne._EVENT_TYPES
    exec_forbidden = ne._EVENT_TYPE_FORBIDDEN_FIELDS["command.exec"]
    assert {"exit_code", "file_path", "duration_ms"} <= exec_forbidden
    assert "command" not in exec_forbidden
    result_forbidden = ne._EVENT_TYPE_FORBIDDEN_FIELDS["tool.result"]
    assert {"command", "exit_code", "duration_ms", "file_path"} <= result_forbidden


# --- size-based rollover ------------------------------------------------------


def _rollover_cfg(tmp_path: Path, max_bytes: int) -> tuple[str, Path]:
    out = tmp_path / "numbat-events.ndjsonl"
    cfg = {
        "logging": {"audit_file": str(tmp_path / "audit.jsonl")},
        "numbat": {
            "enabled": True,
            "output_path": str(out),
            "max_bytes": max_bytes,
            "source_agent": "unknown",
            "source_type": "hook",
        },
    }
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return str(path), out


def _ndjson_lines(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_rollover_renames_at_max_bytes_and_events_keep_flowing(tmp_path: Path) -> None:
    """Past max_bytes the stream renames to .1 and starts fresh -- with no
    event lost across the boundary (each record lands whole in exactly one
    generation, because the check runs before the write under the lock)."""
    config_path, out = _rollover_cfg(tmp_path, max_bytes=2000)
    rolled = out.with_name(out.name + ".1")

    emitted = 0
    while not rolled.exists() and emitted < 50:
        emit_numbat_event("command.exec", command="echo hi", config_path=config_path)
        emitted += 1
    assert rolled.exists(), "rollover never happened within 50 events"

    emit_numbat_event("command.exec", command="echo after", config_path=config_path)
    emitted += 1

    fresh, archived = _ndjson_lines(out), _ndjson_lines(rolled)
    assert fresh, "stream stopped flowing after rollover"
    assert len(fresh) + len(archived) == emitted, "an event was lost across the rollover"
    assert out.stat().st_size < rolled.stat().st_size


def test_rollover_keeps_a_single_generation(tmp_path: Path) -> None:
    config_path, out = _rollover_cfg(tmp_path, max_bytes=1200)
    rolled = out.with_name(out.name + ".1")
    for _ in range(30):  # enough for several rollovers at 1200 bytes
        emit_numbat_event("command.exec", command="echo hi", config_path=config_path)
    assert rolled.exists()
    generations = [p for p in out.parent.iterdir() if p.name.startswith(out.name) and p != out]
    assert generations == [rolled], "only the single .1 generation may exist"


def test_zero_max_bytes_disables_rollover(tmp_path: Path) -> None:
    config_path, out = _rollover_cfg(tmp_path, max_bytes=0)
    for _ in range(20):
        emit_numbat_event("command.exec", command="echo hi", config_path=config_path)
    assert out.stat().st_size > 1200  # grew well past any small threshold
    assert not out.with_name(out.name + ".1").exists()


@pytest.mark.skipif(
    os.name == "nt",
    reason="POSIX rename-over-open-file semantics; Windows locks an open file, so the "
           "cross-process rollover this guards against cannot occur there",
)
def test_rollover_by_another_process_does_not_orphan_the_cached_handle(tmp_path: Path) -> None:
    """Regression: a rename underneath a cached handle must force a reopen.

    The handle cache is keyed on the path string, but a rename moves that name
    off the inode the handle holds. The action plane rolls this same stream over
    from ops_runner child processes while a long-lived gate.py holds its handle
    open. Without an inode check the server keeps appending into the .1
    generation for the rest of its uptime -- and the next rollover deletes that
    whole backlog, silently ending the mainline plane's projection.
    """
    config_path, out = _rollover_cfg(tmp_path, max_bytes=0)
    rolled = out.with_name(out.name + ".1")

    emit_numbat_event("command.exec", command="echo before", config_path=config_path)
    assert out.exists()

    # Stand in for another process's rollover: rename the file out from under us.
    os.replace(out, rolled)
    emit_numbat_event("command.exec", command="echo after", config_path=config_path)

    assert out.exists(), "live stream must be reopened, not abandoned"
    fresh = out.read_text(encoding="utf-8")
    assert "echo after" in fresh, "post-rename events must land in the live file"
    assert "echo before" in rolled.read_text(encoding="utf-8")


def test_rollover_does_not_clobber_the_archive_when_another_writer_wins(tmp_path: Path) -> None:
    """A second writer must not replace the .1 generation with the fresh file.

    _WRITE_LOCK is process-local, but ops_runner children write this same path.
    Before the rollover lock, a writer that measured the file as oversized and
    then lost the race would still run os.replace -- moving the WINNER's newly
    created (tiny) live file over the archive and destroying the generation.
    Reproduced as 500 archived lines replaced by a 14-byte file.
    """
    live = tmp_path / "numbat-events.ndjsonl"
    live.write_text("ARCHIVE-LINE\n" * 500, encoding="utf-8")
    archive = live.with_name(live.name + ".1")
    max_bytes = 100

    original_acquire = numbat_emitter._acquire_rollover_lock
    gate = threading.Event()

    def stalling_acquire(lock_path):
        # The loser stat'd the old oversized file, then stalls before the lock --
        # exactly the window that destroyed the archive.
        if threading.current_thread().name == "loser":
            gate.wait(5)
        return original_acquire(lock_path)

    def winner() -> None:
        numbat_emitter._rollover_if_needed(live, max_bytes)
        live.write_text("tiny-new-line\n", encoding="utf-8")
        gate.set()

    def loser() -> None:
        numbat_emitter._rollover_if_needed(live, max_bytes)

    with mock.patch.object(numbat_emitter, "_acquire_rollover_lock", stalling_acquire):
        t_lose = threading.Thread(target=loser, name="loser")
        t_lose.start()
        time.sleep(0.05)  # let the loser get past its size check first
        t_win = threading.Thread(target=winner, name="winner")
        t_win.start()
        t_win.join(timeout=10)
        t_lose.join(timeout=10)

    assert archive.read_text(encoding="utf-8").count("ARCHIVE-LINE") == 500
    assert live.read_text(encoding="utf-8") == "tiny-new-line\n"
    assert not live.with_name(live.name + ".rollover.lock").exists()


def test_rollover_skips_while_another_writer_holds_the_lock(tmp_path: Path) -> None:
    """A held lock makes this writer stand down rather than rotate concurrently."""
    live = tmp_path / "numbat-events.ndjsonl"
    live.write_text("x" * 500, encoding="utf-8")
    lock_path = live.with_name(live.name + ".rollover.lock")
    lock_path.write_text("", encoding="utf-8")  # a live holder

    numbat_emitter._rollover_if_needed(live, 100)

    assert live.exists(), "the live file must not be rotated while the lock is held"
    assert not live.with_name(live.name + ".1").exists()


def test_rollover_reclaims_an_abandoned_lock(tmp_path: Path) -> None:
    """A lock left behind by a crashed writer must not disable rollover forever."""
    live = tmp_path / "numbat-events.ndjsonl"
    live.write_text("x" * 500, encoding="utf-8")
    lock_path = live.with_name(live.name + ".rollover.lock")
    lock_path.write_text("", encoding="utf-8")
    stale = time.time() - (numbat_emitter._ROLLOVER_LOCK_STALE_SEC + 30)
    os.utime(lock_path, (stale, stale))

    numbat_emitter._rollover_if_needed(live, 100)

    assert live.with_name(live.name + ".1").exists(), "abandoned lock should be reclaimed"
    assert not lock_path.exists()


@pytest.mark.parametrize(("url", "expected"), [
    ("https://api.x.ai/v1", "https://api.x.ai"),
    ("https://token@api.x.ai/v1", "https://api.x.ai"),
    ("https://api.x.ai/proxy/sk-secret-token/v1", "https://api.x.ai"),
    ("https://user:pw@api.x.ai:8443/v1?key=abc#frag", "https://api.x.ai:8443"),
    ("https://[::1]:8080/x?y=1", "https://[::1]:8080"),
    ("https://API.Anthropic.com/v1/", "https://api.anthropic.com"),
    ("not a url", None),
    ("https://host:99999/", None),
    ("", None),
    (None, None),
])
def test_redact_url_for_numbat_keeps_only_the_origin(url, expected):
    from utils.numbat_emitter import redact_url_for_numbat

    assert redact_url_for_numbat(url) == expected



# ---------------------------------------------------------------------------
# The stream's single writer thread: a stalled filesystem under
# numbat.output_path must not hold the caller (the audit step of every /query).
# ---------------------------------------------------------------------------


@pytest.fixture
def writer(monkeypatch: pytest.MonkeyPatch) -> numbat_emitter._StreamWriter:
    """A writer of this test's own, so stalling it leaves the module's alone."""
    fresh = numbat_emitter._StreamWriter()
    monkeypatch.setattr(numbat_emitter, "_WRITER", fresh)
    return fresh


def _stall_writes(monkeypatch: pytest.MonkeyPatch, *, hold_lock: bool = False) -> tuple[threading.Event, threading.Event]:
    """Make the first write block until ``release`` is set; ``entered`` says it began.

    With ``hold_lock`` it blocks holding _WRITE_LOCK, as a real append stuck on
    a stalled mount does.
    """
    real_write = numbat_emitter._write_line
    entered, release = threading.Event(), threading.Event()
    first = [True]

    def _write(path: Path, line: str, max_bytes: int) -> None:
        if first[0]:
            first[0] = False
            if hold_lock:
                with numbat_emitter._WRITE_LOCK:
                    entered.set()
                    release.wait(30)
            else:
                entered.set()
                release.wait(30)
        real_write(path, line, max_bytes)

    monkeypatch.setattr(numbat_emitter, "_write_line", _write)
    return entered, release


class _LogWaiter(logging.Handler):
    """Sets ``seen`` once cyclaw.numbat_emitter logs a record containing ``text``, on any thread."""

    def __init__(self, text: str) -> None:
        super().__init__(logging.WARNING)
        self.text = text
        self.seen = threading.Event()

    def emit(self, record: logging.LogRecord) -> None:
        if self.text in record.getMessage():
            self.seen.set()


def _in_thread(fn, *args) -> threading.Thread:
    thread = threading.Thread(target=fn, args=args, daemon=True)
    thread.start()
    thread.join(10)
    return thread


def test_a_healthy_write_is_in_the_file_when_the_call_returns(tmp_path: Path, writer) -> None:
    out = tmp_path / "s.ndjsonl"
    numbat_emitter.write_ndjson({"n": 1}, out)
    assert _ndjson_lines(out) == [{"n": 1}]


def test_a_stalled_write_does_not_hold_its_caller(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, writer,
                                                  caplog: pytest.LogCaptureFixture) -> None:
    out = tmp_path / "s.ndjsonl"
    monkeypatch.setattr(numbat_emitter, "_WRITE_WAIT_SEC", 0.05)
    entered, release = _stall_writes(monkeypatch)
    try:
        with caplog.at_level(logging.WARNING, logger="cyclaw.numbat_emitter"):
            # Returns after the 0.05 s wait although only the finally below
            # releases the write.
            numbat_emitter.write_ndjson({"n": 1}, out)
            assert entered.wait(10)
            assert "was not written within 0.05s" in caplog.text
            # The stream is now known to be stalled: the next caller does not
            # wait at all, even with an hour-long wait configured.
            monkeypatch.setattr(numbat_emitter, "_WRITE_WAIT_SEC", 3600.0)
            second = _in_thread(numbat_emitter.write_ndjson, {"n": 2}, out)
            assert not second.is_alive()
            assert writer.flush(0.05) is False
    finally:
        release.set()
    assert writer.flush(10)
    assert _ndjson_lines(out) == [{"n": 1}, {"n": 2}]
    assert "a write finished after" in caplog.text


def test_callers_already_waiting_stop_when_the_stall_is_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                             writer) -> None:
    # The first caller waits with an hour-long wait on its own stuck write.
    # When a second caller times out and finds the stream stalled, the first
    # stops waiting too instead of sitting out its hour.
    out = tmp_path / "s.ndjsonl"
    monkeypatch.setattr(numbat_emitter, "_WRITE_WAIT_SEC", 3600.0)
    entered, release = _stall_writes(monkeypatch)
    first = threading.Thread(target=numbat_emitter.write_ndjson, args=({"n": 1}, out), daemon=True)
    try:
        first.start()
        # The writer took line 1 only after the first caller released the lock
        # to wait, so the first caller is waiting now.
        assert entered.wait(10)
        monkeypatch.setattr(numbat_emitter, "_WRITE_WAIT_SEC", 0.05)
        numbat_emitter.write_ndjson({"n": 2}, out)
        first.join(10)
        assert not first.is_alive()
    finally:
        release.set()
    assert writer.flush(10)
    assert _ndjson_lines(out) == [{"n": 1}, {"n": 2}]


def test_the_writer_limits_come_from_the_numbat_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                      writer) -> None:
    # config.yaml's numbat block sets the limits (no hardcoded tunables): with
    # max_queued_writes: 1 and a stuck write, the second queued event is
    # dropped, and the configured drain is what exit will wait.
    out = tmp_path / "s.ndjsonl"
    cfg = {"numbat": {"enabled": True, "output_path": str(out), "write_wait_sec": 0.05,
                      "max_queued_writes": 1, "drain_wait_sec": 0.25}}
    entered, release = _stall_writes(monkeypatch)
    try:
        emit_numbat_event("tool.result", tool_name="a", cfg=cfg)
        assert entered.wait(10)  # "a" is the stuck write
        emit_numbat_event("tool.result", tool_name="b", cfg=cfg)  # fills the queue of one
        emit_numbat_event("tool.result", tool_name="c", cfg=cfg)  # dropped
        assert writer.dropped == 1
        assert writer.drain_sec() == 0.25
    finally:
        release.set()
    assert writer.flush(10)
    assert [line["tool_name"] for line in _ndjson_lines(out)] == ["a", "b"]


@pytest.mark.parametrize("bad", [0, -1, "1s", True, None, float("nan"), float("inf"), 1e300])
def test_an_unusable_writer_limit_falls_back_to_its_default(bad) -> None:
    settings = numbat_emitter._writer_settings({"numbat": {"write_wait_sec": bad, "max_queued_writes": bad,
                                                           "drop_log_interval_sec": bad, "drain_wait_sec": bad}})
    assert settings == numbat_emitter._WriterSettings(
        numbat_emitter._WRITE_WAIT_SEC, numbat_emitter._MAX_QUEUED_WRITES,
        numbat_emitter._DROP_LOG_INTERVAL_SEC, numbat_emitter._DRAIN_WAIT_SEC)


def test_a_wait_longer_than_the_platform_allows_falls_back() -> None:
    # Condition.wait raises OverflowError past threading.TIMEOUT_MAX, and
    # float() of a huge int raises it too, so neither may reach the writer.
    huge = numbat_emitter._writer_settings({"numbat": {"write_wait_sec": 10**400, "drop_log_interval_sec": 10**400,
                                                       "drain_wait_sec": 10**400}})
    assert (huge.wait_sec, huge.drop_log_interval_sec, huge.drain_sec) == (
        numbat_emitter._WRITE_WAIT_SEC, numbat_emitter._DROP_LOG_INTERVAL_SEC, numbat_emitter._DRAIN_WAIT_SEC)
    longest = numbat_emitter._writer_settings({"numbat": {"write_wait_sec": threading.TIMEOUT_MAX}})
    assert longest.wait_sec == threading.TIMEOUT_MAX


def test_the_shipped_config_sets_the_writer_limits_to_the_defaults() -> None:
    # Read the defaults from the source, not the module: tests/conftest.py
    # raises _WRITE_WAIT_SEC for the test session.
    tree = ast.parse((_REPO_ROOT / "utils" / "numbat_emitter.py").read_text(encoding="utf-8"))
    defaults = {
        node.targets[0].id: ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id in {"_WRITE_WAIT_SEC", "_MAX_QUEUED_WRITES", "_DROP_LOG_INTERVAL_SEC", "_DRAIN_WAIT_SEC"}
    }
    block = yaml.safe_load((_REPO_ROOT / "config.yaml").read_text(encoding="utf-8"))["numbat"]
    assert block["write_wait_sec"] == defaults["_WRITE_WAIT_SEC"]
    assert block["max_queued_writes"] == defaults["_MAX_QUEUED_WRITES"]
    assert block["drop_log_interval_sec"] == defaults["_DROP_LOG_INTERVAL_SEC"]
    assert block["drain_wait_sec"] == defaults["_DRAIN_WAIT_SEC"]


def test_a_full_queue_drops_new_events_and_reports_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, writer,
                                                        caplog: pytest.LogCaptureFixture) -> None:
    out = tmp_path / "s.ndjsonl"
    monkeypatch.setattr(numbat_emitter, "_WRITE_WAIT_SEC", 0.05)
    monkeypatch.setattr(numbat_emitter, "_MAX_QUEUED_WRITES", 2)
    entered, release = _stall_writes(monkeypatch)
    try:
        numbat_emitter.write_ndjson({"n": 1}, out)
        assert entered.wait(10)  # line 1 is the stuck write, so 2 and 3 fill the queue
        with caplog.at_level(logging.WARNING, logger="cyclaw.numbat_emitter"):
            for n in (2, 3, 4, 5):
                numbat_emitter.write_ndjson({"n": n}, out)
    finally:
        release.set()
    assert writer.dropped == 2
    drops = [r for r in caplog.records if "dropped" in r.getMessage()]
    assert len(drops) == 1 and "dropped 1 event(s)" in drops[0].getMessage()
    # The second drop, held back by the interval, is reported once the queue
    # drains, so both losses reach the log. The writer logs after releasing
    # its lock, so the report on the last line can land just after flush()
    # returns: wait for the record itself.
    waiter = _LogWaiter("dropped 1 more event(s) since the last report, 2 in all")
    emitter_log = logging.getLogger("cyclaw.numbat_emitter")
    emitter_log.addHandler(waiter)
    try:
        with caplog.at_level(logging.WARNING, logger="cyclaw.numbat_emitter"):
            assert writer.flush(10)
            assert waiter.seen.wait(10)
    finally:
        emitter_log.removeHandler(waiter)
    assert _ndjson_lines(out) == [{"n": 1}, {"n": 2}, {"n": 3}]


def test_close_reports_drops_still_unreported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, writer,
                                              caplog: pytest.LogCaptureFixture) -> None:
    # Exit comes before the queue drains: the held-back count is reported
    # then instead of being lost with the process.
    out = tmp_path / "s.ndjsonl"
    monkeypatch.setattr(numbat_emitter, "_WRITE_WAIT_SEC", 0.05)
    monkeypatch.setattr(numbat_emitter, "_MAX_QUEUED_WRITES", 1)
    monkeypatch.setattr(numbat_emitter, "_DRAIN_WAIT_SEC", 0.05)
    entered, release = _stall_writes(monkeypatch)
    try:
        numbat_emitter.write_ndjson({"n": 1}, out)
        assert entered.wait(10)
        for n in (2, 3, 4):  # 2 fills the queue of one; 3 is reported, 4 held back
            numbat_emitter.write_ndjson({"n": n}, out)
        with caplog.at_level(logging.WARNING, logger="cyclaw.numbat_emitter"):
            closer = _in_thread(close_numbat_handles)
        assert not closer.is_alive()
        assert "dropped 1 more event(s) since the last report, 2 in all" in caplog.text
    finally:
        release.set()
    assert writer.flush(10)


def test_lines_from_one_thread_land_in_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, writer) -> None:
    out = tmp_path / "s.ndjsonl"
    monkeypatch.setattr(numbat_emitter, "_WRITE_WAIT_SEC", 0.05)
    entered, release = _stall_writes(monkeypatch)
    try:
        for n in range(20):  # everything after the first queues behind the stuck write
            numbat_emitter.write_ndjson({"n": n}, out)
        assert entered.wait(10)
    finally:
        release.set()
    assert writer.flush(10)
    assert [line["n"] for line in _ndjson_lines(out)] == list(range(20))


def test_close_does_not_hang_on_a_stuck_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, writer,
                                              caplog: pytest.LogCaptureFixture) -> None:
    # At exit (atexit runs close_numbat_handles) a write stuck on a stalled
    # mount holds the write lock; exit waits for it only _DRAIN_WAIT_SEC.
    monkeypatch.setattr(numbat_emitter, "_WRITE_WAIT_SEC", 0.05)
    monkeypatch.setattr(numbat_emitter, "_DRAIN_WAIT_SEC", 0.05)
    entered, release = _stall_writes(monkeypatch, hold_lock=True)
    try:
        numbat_emitter.write_ndjson({"n": 1}, tmp_path / "s.ndjsonl")
        assert entered.wait(10)
        with caplog.at_level(logging.WARNING, logger="cyclaw.numbat_emitter"):
            closer = _in_thread(close_numbat_handles)
        assert not closer.is_alive()
        assert "a write is still stuck" in caplog.text
    finally:
        release.set()
    assert writer.flush(10)


def test_a_failed_write_is_logged_and_the_writer_keeps_going(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                             writer, caplog: pytest.LogCaptureFixture) -> None:
    out = tmp_path / "s.ndjsonl"
    real_write = numbat_emitter._write_line
    calls = [0]

    def _fail_first(path: Path, line: str, max_bytes: int) -> None:
        calls[0] += 1
        if calls[0] == 1:
            raise OSError("disk full")
        real_write(path, line, max_bytes)

    monkeypatch.setattr(numbat_emitter, "_write_line", _fail_first)
    with caplog.at_level(logging.WARNING, logger="cyclaw.numbat_emitter"):
        numbat_emitter.write_ndjson({"n": 1}, out)
        numbat_emitter.write_ndjson({"n": 2}, out)
    assert _ndjson_lines(out) == [{"n": 2}]
    assert "failed: disk full" in caplog.text
    # flush says "every queued event is in the stream"; line 1 is not.
    assert writer.failed == 1
    assert writer.flush(10) is False


def test_a_write_falls_back_to_the_caller_when_no_thread_can_start(tmp_path: Path,
                                                                   monkeypatch: pytest.MonkeyPatch,
                                                                   writer) -> None:
    # At interpreter shutdown Python refuses to start threads; the line is
    # then written on the caller's thread, as before.
    monkeypatch.setattr(writer, "_start", lambda: False)
    out = tmp_path / "s.ndjsonl"
    numbat_emitter.write_ndjson({"n": 1}, out)
    assert _ndjson_lines(out) == [{"n": 1}]
    assert writer._thread is None


@pytest.mark.skipif(not hasattr(os, "fork"), reason="POSIX fork only")
def test_a_forked_child_gets_a_write_lock_nobody_holds(tmp_path: Path) -> None:
    # The parent holds the write lock at the fork, as its writer thread would
    # mid-append. Without the at-fork reset the child's line never lands: its
    # writer waits on a lock no thread in the child will ever release.
    out = tmp_path / "child.ndjsonl"
    script = textwrap.dedent(f"""
        import os, sys, warnings
        from pathlib import Path
        from utils import numbat_emitter as e
        warnings.simplefilter("ignore", DeprecationWarning)
        e._WRITE_LOCK.acquire()
        pid = os.fork()
        if pid == 0:
            e.write_ndjson({{"child": True}}, Path({str(out)!r}))
            e.close_numbat_handles()
            os._exit(0)
        _, status = os.waitpid(pid, 0)
        sys.exit(os.waitstatus_to_exitcode(status))
    """)
    proc = subprocess.run([sys.executable, "-c", script], cwd=_REPO_ROOT, timeout=60,  # noqa: S603 - fixed argv
                          capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stderr
    assert _ndjson_lines(out) == [{"child": True}]
