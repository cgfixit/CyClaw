"""Unit tests for utils/logger.py — audit logging + logging setup.

Focuses on the cwd-independence of relative logging.log_file / audit_file
config values (_anchor / _REPO_ROOT). _get_config already anchored the
config.yaml *file itself* to _REPO_ROOT; these guard the values *inside* it,
which previously stayed cwd-relative -- silent until CyClaw is launched from
a cwd other than the repo root (the same fragility gate.py's _BASE_DIR exists
to prevent for config.yaml/static/).
"""
import pathlib
import logging

import json
import subprocess
import sys
import textwrap
import threading
import weakref

import pytest

from utils import logger


@pytest.fixture(autouse=True)
def _isolate_logger_state():
    # audit_log() caches one append-mode file handle per resolved path in a
    # module-level dict; close it around each test so a test's tmp_path file
    # can be deleted and the next test starts with a clean cache.
    logger.close_audit_handles()
    logger.reset_config_cache()
    yield
    logger.close_audit_handles()
    logger.reset_config_cache()


@pytest.mark.real_log_anchor
class TestAnchor:
    def test_relative_path_anchored_to_repo_root(self):
        assert logger._anchor("logs/audit.jsonl") == logger._REPO_ROOT / "logs/audit.jsonl"

    def test_absolute_path_passed_through(self, tmp_path):
        absolute = tmp_path / "audit.jsonl"
        assert logger._anchor(str(absolute)) == absolute

    def test_user_expansion(self, monkeypatch, tmp_path):
        # posixpath.expanduser reads HOME; Windows' ntpath.expanduser reads
        # USERPROFILE (falling back to HOMEDRIVE+HOMEPATH) and never reads HOME
        # at all (verified against CPython's ntpath.py) -- set both so this
        # passes on every CI leg instead of silently no-op'ing on windows-latest.
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        assert logger._anchor("~/audit.jsonl") == tmp_path / "audit.jsonl"


class TestAuditLogPathAnchoring:
    @pytest.mark.real_log_anchor
    def test_relative_audit_file_resolves_regardless_of_cwd(self, tmp_path, monkeypatch):
        # Regression: audit_log() previously did Path(cfg["logging"]["audit_file"])
        # directly, resolving a relative path against the process cwd instead
        # of the repo root.
        monkeypatch.setattr(logger, "_REPO_ROOT", tmp_path)
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)

        cfg = {"logging": {"audit_file": "relative_audit.jsonl", "audit_fields": {}}}
        logger.audit_log({"event": "test_event"}, cfg=cfg)
        logger.close_audit_handles()

        expected = tmp_path / "relative_audit.jsonl"
        assert expected.exists()
        assert not (elsewhere / "relative_audit.jsonl").exists()
        record = json.loads(expected.read_text().splitlines()[0])
        assert record["event"] == "test_event"

    def test_absolute_audit_file_unaffected(self, tmp_path):
        absolute = tmp_path / "abs_audit.jsonl"
        cfg = {"logging": {"audit_file": str(absolute), "audit_fields": {}}}
        logger.audit_log({"event": "test_event"}, cfg=cfg)
        logger.close_audit_handles()
        assert absolute.exists()


class TestAuditLogWriteFailure:
    """audit_logger is the unconditional terminal node every graph path
    converges on (invariant I4), running AFTER the answer is already
    computed. A disk/permission failure writing the audit line must degrade
    to a warning, not raise -- an already-good response should never become
    an HTTP 500 purely because the audit trail couldn't be persisted."""

    def test_write_failure_does_not_raise(self, tmp_path, monkeypatch, caplog):
        cfg = {"logging": {"audit_file": str(tmp_path / "audit.jsonl"), "audit_fields": {}}}

        def _boom(_log_path):
            raise OSError("simulated disk full")

        monkeypatch.setattr(logger, "_audit_handle", _boom)
        with caplog.at_level("WARNING", logger="cyclaw.logger"):
            logger.audit_log({"event": "test_event"}, cfg=cfg)  # must not raise
        assert "audit_log write failed" in caplog.text

    def test_write_failure_leaves_no_partial_file_state(self, tmp_path, monkeypatch):
        # A failed handle open must not leave the caller's dict mutated or
        # raise something other than the documented fail-soft path.
        cfg = {"logging": {"audit_file": str(tmp_path / "audit.jsonl"), "audit_fields": {}}}
        event = {"event": "test_event"}
        monkeypatch.setattr(logger, "_audit_handle", lambda _log_path: (_ for _ in ()).throw(OSError("boom")))
        logger.audit_log(event, cfg=cfg)
        assert event == {"event": "test_event"}  # caller's dict is never mutated


class TestAuditLogSerializationFailure:
    """audit_log() has ~100 call sites across the repo; a non-JSON-serializable
    field or a non-string "query" value anywhere in the event dict must degrade
    to a warning like the OSError write-failure path, not raise -- same I4
    rationale as TestAuditLogWriteFailure, extended to record-building."""

    def test_non_serializable_field_does_not_raise(self, tmp_path, caplog):
        cfg = {"logging": {"audit_file": str(tmp_path / "audit.jsonl"), "audit_fields": {}}}
        event = {"event": "test_event", "bad_field": object()}
        with caplog.at_level("WARNING", logger="cyclaw.logger"):
            logger.audit_log(event, cfg=cfg)  # must not raise
        assert "audit_log failed to build event" in caplog.text
        assert not (tmp_path / "audit.jsonl").exists()

    def test_non_string_query_does_not_raise(self, tmp_path, caplog):
        cfg = {"logging": {"audit_file": str(tmp_path / "audit.jsonl"), "audit_fields": {}}}
        event = {"event": "test_event", "query": 12345}
        with caplog.at_level("WARNING", logger="cyclaw.logger"):
            logger.audit_log(event, cfg=cfg)  # must not raise
        assert "audit_log failed to build event" in caplog.text

    def test_failure_leaves_caller_dict_unmutated(self, tmp_path):
        cfg = {"logging": {"audit_file": str(tmp_path / "audit.jsonl"), "audit_fields": {}}}
        event = {"event": "test_event", "bad_field": object()}
        original_keys = set(event.keys())
        logger.audit_log(event, cfg=cfg)
        assert set(event.keys()) == original_keys

    def test_valid_event_still_writes_normally(self, tmp_path):
        """Regression guard: the new try block must not change the happy path."""
        cfg = {"logging": {"audit_file": str(tmp_path / "audit.jsonl"), "audit_fields": {}}}
        logger.audit_log({"event": "test_event", "detail": "fine"}, cfg=cfg)
        logger.close_audit_handles()
        record = json.loads((tmp_path / "audit.jsonl").read_text().splitlines()[0])
        assert record["event"] == "test_event"
        assert record["detail"] == "fine"


@pytest.mark.real_log_anchor
class TestSetupLoggingPathAnchoring:
    @pytest.mark.usefixtures("isolated_logging")
    def test_relative_log_file_resolves_regardless_of_cwd(self, tmp_path, monkeypatch):
        monkeypatch.setattr(logger, "_REPO_ROOT", tmp_path)
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)

        cfg = {"logging": {"level": "INFO", "log_file": "relative.log"}}
        logger.setup_logging(cfg)

        assert (tmp_path / "relative.log").exists()
        assert not (elsewhere / "relative.log").exists()


class TestThirdPartyLogCapture:
    """logging.level is DEBUG for CyClaw's own modules; third-party loggers
    reach the same file but are held at a floor.

    The gap is a security control, not a noise preference: httpcore's DEBUG
    output is wire-level and carries the Authorization header of every outbound
    Grok/Claude/Ollama call, so a single shared DEBUG level would write live API
    keys into logs/cyclaw.log.
    """

    def test_cyclaw_records_pass_below_the_floor(self):
        from utils.logger import _ThirdPartyFloor

        floor = _ThirdPartyFloor(logging.INFO)
        record = logging.LogRecord(
            "cyclaw.graph", logging.DEBUG, __file__, 1, "chunk budget", None, None
        )
        assert floor.filter(record) is True

    def test_third_party_debug_is_dropped(self):
        from utils.logger import _ThirdPartyFloor

        floor = _ThirdPartyFloor(logging.INFO)
        leaky = logging.LogRecord(
            "httpcore.http11", logging.DEBUG, __file__, 1,
            "send_request_headers.started request=<Request [b'POST']> "
            "headers=[(b'authorization', b'Bearer sk-live-secret')]",
            None, None,
        )
        assert floor.filter(leaky) is False

    def test_third_party_warnings_still_reach_the_file(self):
        """The floor holds DEBUG back; it must not silence real problems."""
        from utils.logger import _ThirdPartyFloor

        floor = _ThirdPartyFloor(logging.INFO)
        for level in (logging.INFO, logging.WARNING, logging.ERROR):
            record = logging.LogRecord("chromadb", level, __file__, 1, "x", None, None)
            assert floor.filter(record) is True

    def test_shipped_config_keeps_the_gap(self):
        """config.yaml must not set third_party_level to DEBUG. If someone
        raises it, this fails loudly rather than leaking keys quietly."""
        import yaml

        root = pathlib.Path(__file__).resolve().parents[1]
        cfg = yaml.safe_load((root / "config.yaml").read_text(encoding="utf-8"))
        log_cfg = cfg["logging"]
        assert log_cfg["level"] == "DEBUG"
        assert log_cfg["third_party_level"] != "DEBUG"

    @pytest.mark.usefixtures("isolated_logging")
    def test_stray_loggers_land_in_the_configured_file(self, tmp_path):
        """The actual ask: a logger outside the cyclaw.* namespace must end up in
        cyclaw.log rather than only on stderr."""
        import utils.logger as logger_mod

        log_path = tmp_path / "cyclaw.log"
        real_root = logging.getLogger()
        logger_mod.setup_logging({"logging": {
            "level": "DEBUG",
            "log_file": str(log_path),
            "capture_third_party": True,
            "third_party_level": "INFO",
        }})
        logging.getLogger("chromadb.telemetry").warning("third-party line")
        logging.getLogger("cyclaw.graph").debug("cyclaw debug line")
        for handler in real_root.handlers:
            handler.flush()
        text = log_path.read_text(encoding="utf-8")
        assert "third-party line" in text
        assert "cyclaw debug line" in text

    @pytest.mark.usefixtures("isolated_logging")
    def test_cyclaw_lines_are_written_to_the_file_exactly_once(self, tmp_path):
        """Presence is not enough -- count it.

        _capture_third_party attaches its handler to the REAL root, and
        _ThirdPartyFloor passes cyclaw.* at any level. cyclaw.* records also
        propagate up to root. So a second FileHandler on the "cyclaw" logger
        writing the same path put every CyClaw line in the file TWICE (and held
        two fds on one file). The sibling test above only asserted `in text`, so
        it passed either way and the duplication shipped unnoticed.
        """

        log_path = tmp_path / "cyclaw.log"
        real_root = logging.getLogger()
        logger.setup_logging({"logging": {
            "level": "DEBUG",
            "log_file": str(log_path),
            "capture_third_party": True,
            "third_party_level": "INFO",
        }})
        logging.getLogger("cyclaw.graph").info("count-me-once")
        logging.getLogger("chromadb.telemetry").warning("third-party-once")
        for handler in real_root.handlers + logging.getLogger("cyclaw").handlers:
            handler.flush()
        text = log_path.read_text(encoding="utf-8")
        assert text.count("count-me-once") == 1, "CyClaw line duplicated in the log file"
        assert text.count("third-party-once") == 1, "third-party line duplicated in the log file"

    @pytest.mark.usefixtures("isolated_logging")
    def test_cyclaw_still_reaches_the_file_when_third_party_capture_is_off(
        self, tmp_path,
    ):
        """The opt-out path must keep its own handler.

        With capture_third_party false, _capture_third_party attaches nothing --
        so setup_logging still has to own the file itself, or turning the
        third-party switch off would silently stop logging CyClaw to disk too.
        """

        log_path = tmp_path / "cyclaw.log"
        cyclaw_logger = logging.getLogger("cyclaw")
        logger.setup_logging({"logging": {
            "level": "DEBUG",
            "log_file": str(log_path),
            "capture_third_party": False,
        }})
        logging.getLogger("cyclaw.graph").info("offline-marker")
        for handler in cyclaw_logger.handlers:
            handler.flush()
        text = log_path.read_text(encoding="utf-8")
        assert text.count("offline-marker") == 1

    def test_agentic_still_reaches_the_file_when_third_party_capture_is_off(
        self, tmp_path, monkeypatch,
    ):
        """agentic.* is first-party CyClaw code, not a third-party library.

        Before this fix, turning capture_third_party off left setup_logging
        owning a FileHandler on only the "cyclaw" logger -- agentic.* records
        (agentic.fsconnect.pathsafe, agentic.fsconnect.trash, etc.) propagate
        through their own "agentic" ancestor instead, which had no handler on
        this branch, so they reached only Python's stderr last-resort handler
        even though the operator only meant to silence noisy externals like
        chromadb/httpx, not CyClaw's own out-of-band subsystems (codex review
        on #1239).
        """

        log_path = tmp_path / "cyclaw.log"
        monkeypatch.setattr(logger, "_logging_initialized", False)
        cyclaw_logger = logging.getLogger("cyclaw")
        agentic_logger = logging.getLogger("agentic")
        real_root = logging.getLogger()
        before_root = list(real_root.handlers)
        before_cyclaw = list(cyclaw_logger.handlers)
        before_agentic = list(agentic_logger.handlers)
        try:
            logger.setup_logging({"logging": {
                "level": "DEBUG",
                "log_file": str(log_path),
                "capture_third_party": False,
            }})
            logging.getLogger("agentic.fsconnect.pathsafe").warning("agentic-offline-marker")
            for handler in agentic_logger.handlers:
                handler.flush()
            text = log_path.read_text(encoding="utf-8")
        finally:
            for logger_obj, before in (
                (real_root, before_root),
                (cyclaw_logger, before_cyclaw),
                (agentic_logger, before_agentic),
            ):
                for handler in list(logger_obj.handlers):
                    if handler not in before:
                        logger_obj.removeHandler(handler)
                        handler.close()
            logger._logging_initialized = False
        assert text.count("agentic-offline-marker") == 1

    def test_agentic_still_reaches_stderr_once_a_file_handler_is_attached(
        self, tmp_path, monkeypatch, capsys,
    ):
        """Attaching a durable handler anywhere in agentic's ancestor chain
        must not silence its stderr visibility.

        Before this fix, setup_logging attached a FileHandler to "agentic"
        (capture_third_party off) or to the real root (capture_third_party
        on) but never a StreamHandler of its own -- and attaching ANY handler
        anywhere in a logger's ancestor chain stops Python from falling back
        to lastResort (stderr), which is what agentic.* relied on before
        setup_logging ever ran in these entrypoints at all. Tools that shell
        out to an agentic CLI and capture its stderr (e.g. /ops/fsconnect
        relaying pathsafe's incomplete-listing warning in its response body)
        depend on that stream staying populated (codex review on #1239).
        """
        log_path = tmp_path / "cyclaw.log"
        monkeypatch.setattr(logger, "_logging_initialized", False)
        cyclaw_logger = logging.getLogger("cyclaw")
        agentic_logger = logging.getLogger("agentic")
        real_root = logging.getLogger()
        before_root = list(real_root.handlers)
        before_cyclaw = list(cyclaw_logger.handlers)
        before_agentic = list(agentic_logger.handlers)
        try:
            logger.setup_logging({"logging": {
                "level": "DEBUG",
                "log_file": str(log_path),
                "capture_third_party": True,
                "third_party_level": "INFO",
            }})
            capsys.readouterr()  # discard setup noise, if any
            logging.getLogger("agentic.fsconnect.pathsafe").warning("agentic-stderr-marker")
            err = capsys.readouterr().err
        finally:
            for logger_obj, before in (
                (real_root, before_root),
                (cyclaw_logger, before_cyclaw),
                (agentic_logger, before_agentic),
            ):
                for handler in list(logger_obj.handlers):
                    if handler not in before:
                        logger_obj.removeHandler(handler)
                        handler.close()
            logger._logging_initialized = False
        assert "agentic-stderr-marker" in err

    def test_agentic_warnings_survive_a_raised_third_party_level(
        self, tmp_path, monkeypatch,
    ):
        """A raised third_party_level must not silence agentic.* warnings.

        capture_third_party stays on, but the operator has raised
        third_party_level above WARNING to quiet noisy externals (chromadb,
        httpx). Before this fix, "agentic" had no explicit level of its own,
        so it inherited the real root's raised level and the WARNING record
        was never even created -- and even fixing that alone is not enough,
        because _ThirdPartyFloor's filter would still hold a WARNING record
        back at a floor above WARNING. Both the logger's own level and the
        filter need the agentic exemption for this to actually work.
        """
        log_path = tmp_path / "cyclaw.log"
        monkeypatch.setattr(logger, "_logging_initialized", False)
        cyclaw_logger = logging.getLogger("cyclaw")
        agentic_logger = logging.getLogger("agentic")
        real_root = logging.getLogger()
        before_root = list(real_root.handlers)
        before_cyclaw = list(cyclaw_logger.handlers)
        before_agentic = list(agentic_logger.handlers)
        try:
            logger.setup_logging({"logging": {
                "level": "DEBUG",
                "log_file": str(log_path),
                "capture_third_party": True,
                "third_party_level": "ERROR",
            }})
            logging.getLogger("agentic.fsconnect.trash").warning("agentic-raised-floor-marker")
            for handler in real_root.handlers:
                handler.flush()
            text = log_path.read_text(encoding="utf-8")
        finally:
            for logger_obj, before in (
                (real_root, before_root),
                (cyclaw_logger, before_cyclaw),
                (agentic_logger, before_agentic),
            ):
                for handler in list(logger_obj.handlers):
                    if handler not in before:
                        logger_obj.removeHandler(handler)
                        handler.close()
            logger._logging_initialized = False
        assert "agentic-raised-floor-marker" in text

    def test_agentic_sub_warning_records_still_respect_a_raised_floor(
        self, tmp_path, monkeypatch,
    ):
        """The agentic exemption is WARNING+ only, not a blanket passthrough.

        Unlike cyclaw.*, agentic's DEBUG/INFO output has not been audited
        line-by-line for secrets (see _ThirdPartyFloor's docstring), so a
        sub-WARNING agentic record must still be held back by a raised
        third_party_level exactly like a genuine third-party one would be.
        """
        log_path = tmp_path / "cyclaw.log"
        monkeypatch.setattr(logger, "_logging_initialized", False)
        cyclaw_logger = logging.getLogger("cyclaw")
        agentic_logger = logging.getLogger("agentic")
        real_root = logging.getLogger()
        before_root = list(real_root.handlers)
        before_cyclaw = list(cyclaw_logger.handlers)
        before_agentic = list(agentic_logger.handlers)
        try:
            logger.setup_logging({"logging": {
                "level": "DEBUG",
                "log_file": str(log_path),
                "capture_third_party": True,
                "third_party_level": "ERROR",
            }})
            logging.getLogger("agentic.fsconnect.trash").info("agentic-info-below-floor-marker")
            for handler in real_root.handlers:
                handler.flush()
            text = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
        finally:
            for logger_obj, before in (
                (real_root, before_root),
                (cyclaw_logger, before_cyclaw),
                (agentic_logger, before_agentic),
            ):
                for handler in list(logger_obj.handlers):
                    if handler not in before:
                        logger_obj.removeHandler(handler)
                        handler.close()
            logger._logging_initialized = False
        assert "agentic-info-below-floor-marker" not in text


# ---------------------------------------------------------------------------
# logging.log_file is written by one writer thread (_BackgroundFileHandler),
# so a stalled disk under it cannot hold a thread that logs. Each stall is an
# Event the test releases, never a sleep racing a timeout.
# ---------------------------------------------------------------------------


class _StallingStream:
    """A text stream whose writes wait for ``release``; ``entered`` says one began."""

    def __init__(self, *, fail_first: bool = False) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.lines: list[str] = []
        self.closed = False
        self._fail_first = fail_first

    def write(self, text: str) -> int:
        self.entered.set()
        self.release.wait(30)
        if self._fail_first:
            self._fail_first = False
            raise OSError("disk full")
        self.lines.append(text)
        return len(text)

    def flush(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def background(tmp_path):
    """Build handlers on an isolated logger; close them all afterwards."""
    made: list[tuple[logging.Logger, logger._BackgroundFileHandler]] = []

    def build(stream=None, *, max_queued: int = 100, drain: float = 10.0):
        handler = logger._BackgroundFileHandler(tmp_path / f"app{len(made)}.log", max_queued=max_queued,
                                                 drain_wait_sec=drain)
        handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
        if stream is not None:
            real, handler._stream = handler._stream, stream
            real.close()
        log = logging.getLogger(f"cyclaw.test_background.{len(made)}")
        log.propagate = False
        log.setLevel(logging.DEBUG)
        log.addHandler(handler)
        made.append((log, handler))
        return log, handler

    yield build
    for log, handler in made:
        log.removeHandler(handler)
        stream = handler._stream
        if isinstance(stream, _StallingStream):
            stream.release.set()
        handler.close()


def _in_thread(fn, *args) -> threading.Thread:
    thread = threading.Thread(target=fn, args=args, daemon=True)
    thread.start()
    thread.join(10)
    return thread


class TestBackgroundLogWriter:
    def test_a_stalled_disk_does_not_hold_threads_that_log(self, background):
        # With a FileHandler the first caller would sit in write() holding the
        # handler lock, and the second would wait on that lock behind it.
        stream = _StallingStream()
        log, handler = background(stream)
        try:
            first = _in_thread(log.warning, "first")
            assert not first.is_alive()
            assert stream.entered.wait(10)  # the writer thread is the one stuck
            second = _in_thread(log.warning, "second")
            assert not second.is_alive()
            assert stream.lines == []
        finally:
            stream.release.set()
        handler.flush()
        assert stream.lines == ["WARNING first\n", "WARNING second\n"]

    def test_a_healthy_file_has_the_line_once_flush_returns(self, background):
        log, handler = background()
        log.info("on disk")
        handler.flush()
        assert handler.path.read_text(encoding="utf-8") == "INFO on disk\n"

    def test_a_full_queue_drops_notes_once_and_counts_into_the_log(self, background, capsys):
        stream = _StallingStream()
        log, handler = background(stream, max_queued=2)
        try:
            log.warning("1")
            assert stream.entered.wait(10)  # line 1 is the stuck write, so 2 and 3 fill the queue
            for n in (2, 3, 4, 5):
                log.warning(str(n))
            assert handler.dropped == 2
            assert capsys.readouterr().err.count("dropping lines for") == 1
        finally:
            stream.release.set()
        assert handler.drain(10)
        # The count is written before the line that emptied the queue is
        # marked written, so it is already there when drain() returns.
        assert stream.lines == ["WARNING 1\n", "WARNING 2\n", "WARNING 3\n",
                                "WARNING dropped 2 log line(s) while the log writer was behind, 2 in all\n"]

    def test_exit_does_not_hang_on_a_stalled_disk(self, background, capsys):
        # logging.shutdown() is what atexit runs: it takes each handler's lock,
        # then calls flush() and close(). Both wait at most drain_wait_sec.
        stream = _StallingStream()
        log, handler = background(stream, drain=0.05)
        try:
            log.warning("stuck")
            assert stream.entered.wait(10)
            log.warning("queued")
            shutdown = _in_thread(logging.shutdown, [weakref.ref(handler)])
            assert not shutdown.is_alive()
            assert "with 2 queued line(s) not written" in capsys.readouterr().err
            assert not stream.closed  # the writer is inside write(); the OS closes the file at exit
        finally:
            stream.release.set()

    def test_close_waits_for_the_queue_then_closes_the_file(self, background):
        log, handler = background()
        for n in range(50):
            log.info("line %d", n)
        handler.close()
        assert handler._stream is None
        assert handler.path.read_text(encoding="utf-8").count("\n") == 50
        log.info("after close")  # dropped, never raised
        assert handler.dropped == 1

    def test_a_failed_write_is_noted_once_and_the_writer_keeps_going(self, background, capsys):
        stream = _StallingStream(fail_first=True)
        stream.release.set()
        log, handler = background(stream)
        log.warning("lost")
        log.warning("kept")
        assert handler.drain(10)
        assert stream.lines == ["WARNING kept\n"]
        assert handler.failed == 1
        err = capsys.readouterr().err
        assert "failed (disk full)" in err and "works again (1 line(s) lost in all)" in err

    def test_an_event_is_dropped_when_no_writer_thread_can_start(self, background, monkeypatch, capsys):
        stream = _StallingStream()
        log, handler = background(stream)
        handler.close()  # stop the writer started at construction
        handler._reset_queue()
        handler._stream = stream
        monkeypatch.setattr(handler, "_start", lambda: False)
        caller = _in_thread(log.warning, "nowhere to go")
        assert not caller.is_alive()
        assert not stream.entered.is_set()  # nothing was written on the caller's thread
        assert handler.dropped == 1
        assert "because no writer thread could start" in capsys.readouterr().err

    @pytest.mark.skipif(not hasattr(__import__("os"), "fork"), reason="POSIX fork only")
    def test_a_forked_child_gets_a_fresh_writer(self, tmp_path):
        # Another thread holds the handler's queue lock at the fork, as the
        # writer or a caller mid-emit would. That thread does not exist in the
        # child, so without the at-fork reset the child's emit waits on the
        # lock forever (the alarm then kills it, and the test fails). The
        # holder must not be the forking thread: the lock is reentrant, so the
        # forking thread would simply take it again in the child.
        out = tmp_path / "child.log"
        script = textwrap.dedent(f"""
            import logging, os, signal, sys, threading, warnings
            from pathlib import Path
            from utils import logger as L
            warnings.simplefilter("ignore", DeprecationWarning)
            h = L._BackgroundFileHandler(Path({str(out)!r}), max_queued=10, drain_wait_sec=10.0)
            h.setFormatter(logging.Formatter("%(message)s"))
            log = logging.getLogger("forktest")
            log.propagate = False
            log.addHandler(h)
            held, done = threading.Event(), threading.Event()
            def hold():
                with h._cond:
                    held.set()
                    done.wait()
            threading.Thread(target=hold, daemon=True).start()
            held.wait()
            pid = os.fork()
            if pid == 0:
                signal.alarm(30)
                log.warning("from the child")
                os._exit(0 if h.drain(10) else 3)
            done.set()
            _, status = os.waitpid(pid, 0)
            sys.exit(os.waitstatus_to_exitcode(status))
        """)
        repo = pathlib.Path(__file__).resolve().parents[1]
        proc = subprocess.run([sys.executable, "-c", script], cwd=repo, timeout=60,  # noqa: S603 - fixed argv
                              capture_output=True, text=True, check=False)
        assert proc.returncode == 0, proc.stderr
        assert out.read_text(encoding="utf-8") == "from the child\n"


class TestLogWriterSettings:
    def test_setup_logging_writes_the_file_from_a_background_handler(self, tmp_path, monkeypatch):
        log_path = tmp_path / "cyclaw.log"
        monkeypatch.setattr(logger, "_logging_initialized", False)
        real_root = logging.getLogger()
        before = list(real_root.handlers)
        try:
            logger.setup_logging({"logging": {
                "level": "DEBUG", "log_file": str(log_path), "capture_third_party": True,
                "third_party_level": "INFO", "max_queued_records": 7, "drain_wait_sec": 0.5,
            }})
            added = [h for h in real_root.handlers if h not in before]
            assert len(added) == 1
            handler = added[0]
            assert isinstance(handler, logger._BackgroundFileHandler)
            assert (handler.max_queued, handler.drain_wait_sec) == (7, 0.5)
            assert any(isinstance(f, logger._ThirdPartyFloor) for f in handler.filters)
        finally:
            for handler in list(real_root.handlers):
                if handler not in before:
                    real_root.removeHandler(handler)
                    handler.close()
            logger._logging_initialized = False

    @pytest.mark.parametrize("bad", [0, -1, "10", True, None, float("nan"), float("inf"), 1e300])
    def test_an_unusable_limit_falls_back_to_its_default(self, bad):
        assert logger._log_writer_settings({"max_queued_records": bad, "drain_wait_sec": bad}) == (
            logger._DEFAULT_MAX_QUEUED_RECORDS, logger._DEFAULT_LOG_DRAIN_WAIT_SEC)

    def test_a_fractional_queue_size_falls_back(self):
        assert logger._log_writer_settings({"max_queued_records": 2.5})[0] == logger._DEFAULT_MAX_QUEUED_RECORDS

    def test_a_drain_longer_than_a_timed_wait_allows_falls_back(self):
        # float() of a huge int raises OverflowError; the comparison does not.
        assert logger._log_writer_settings({"drain_wait_sec": 10**400})[1] == logger._DEFAULT_LOG_DRAIN_WAIT_SEC
        assert logger._log_writer_settings({"drain_wait_sec": threading.TIMEOUT_MAX})[1] == threading.TIMEOUT_MAX

    def test_the_shipped_config_sets_the_defaults(self):
        import yaml

        root = pathlib.Path(__file__).resolve().parents[1]
        log_cfg = yaml.safe_load((root / "config.yaml").read_text(encoding="utf-8"))["logging"]
        assert log_cfg["max_queued_records"] == logger._DEFAULT_MAX_QUEUED_RECORDS
        assert log_cfg["drain_wait_sec"] == logger._DEFAULT_LOG_DRAIN_WAIT_SEC
