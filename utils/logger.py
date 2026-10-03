"""Append-only audit logging with query hashing and privacy redaction,
plus standard Python logging setup for operational diagnostics.

Every query, miss, escalation, and error gets a JSONL line. When
logging.audit_fields.include_query_hash is true (the shipped default),
query text is SHA256-hashed so the audit log cannot become a data
exfiltration vector; setting that toggle false stores the raw query text
(PII redaction still applies) and is privacy-affecting — see config.yaml
logging.audit_fields and the invariant in tests/test_due_diligence_invariants.py.
"""

import atexit
import hashlib
import json
import logging
import os
import re
import sys
import threading
import time
import weakref
from collections import deque
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, TextIO

import yaml

logger = logging.getLogger("cyclaw.logger")

_logging_initialized = False
_AUDIT_WRITE_LOCK = threading.Lock()
# Anchor relative config_path lookups to the repo root, mirroring gate.py's
# _BASE_DIR pattern. Without this, audit_log()/setup_logging() callers that
# don't pass cfg explicitly (graph.py, utils/personality.py) resolve the
# default "config.yaml" against the process CWD, which raises
# FileNotFoundError whenever cyclaw-server is invoked from outside the repo
# root — exactly the fragility _BASE_DIR exists to prevent in gate.py itself.
_REPO_ROOT = Path(__file__).resolve().parent.parent

# audit_log() previously opened, wrote, and closed the audit file on every
# single call — each event paid a fresh open() (path resolution, inode
# lookup, possible file creation) plus a close(). Under sustained query
# volume that syscall overhead dominates the write itself. Instead, keep one
# append-mode handle open per resolved audit-file path and reuse it across
# calls; still flush() after every write so readers observe each event
# immediately (audit_log's synchronous-visibility contract is unchanged —
# only the repeated open/close is eliminated, not the durability guarantee).
_AUDIT_HANDLES: dict[str, TextIO] = {}


def _audit_handle(log_path: Path) -> TextIO:
    """Return the cached append-mode handle for log_path, opening it if needed.

    Caller must hold _AUDIT_WRITE_LOCK.
    """
    key = str(log_path)
    handle = _AUDIT_HANDLES.get(key)
    if handle is None or handle.closed:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        # Intentionally long-lived: cached in _AUDIT_HANDLES and reused across
        # every subsequent audit_log() call for this path (see module docstring
        # above). A static file-not-closed check cannot see across that
        # module-level lifetime from this function alone, so the close is
        # registered right here (not only in the batch close_audit_handles()
        # below) -- closing an already-closed file object is a no-op, so the
        # two closers never conflict.
        handle = open(log_path, "a", encoding="utf-8")  # noqa: SIM115  # codeql[py/file-not-closed] closed via atexit.register below and close_audit_handles()
        atexit.register(handle.close)
        _AUDIT_HANDLES[key] = handle
    return handle


def close_audit_handles() -> None:
    """Flush and close all cached audit file handles.

    Called automatically at process exit; also useful for tests that need to
    release file descriptors before deleting their tmp_path audit files.
    """
    with _AUDIT_WRITE_LOCK:
        for handle in _AUDIT_HANDLES.values():
            try:
                handle.close()
            except OSError:
                # Best-effort at process-exit/test-teardown: a handle that fails to
                # close (e.g. its underlying fd was already torn down) has nothing
                # else useful to do here, and _AUDIT_HANDLES.clear() below still
                # drops our reference so a future audit_log() call reopens cleanly.
                pass
        _AUDIT_HANDLES.clear()


atexit.register(close_audit_handles)


def _anchor(path_str: str) -> Path:
    """Resolve path_str against the repo root when it isn't already absolute.

    Mirrors _get_config's own anchoring (see _REPO_ROOT above) so log_file/
    audit_file values read from config.yaml don't depend on the process cwd.
    """
    path = Path(path_str).expanduser()
    return path if path.is_absolute() else _REPO_ROOT / path


def audit_file_path(cfg: dict) -> Path:
    """The audit trail's path, resolved exactly as audit_log resolves it to write.

    For readers (gate.py's /audit/summary, gate_auth.py's /auth/audit/summary):
    joining the configured value onto a root by hand skipped expanduser, so an
    ``audit_file: ~/...`` made both views read ``<repo>/~/...`` and report an
    empty trail. Looks _anchor up at call time, so tests that redirect it
    redirect readers and writer together.
    """
    return _anchor(cfg["logging"]["audit_file"])


def setup_logging(cfg: dict | None = None, *, background_console: bool = False) -> None:
    global _logging_initialized
    if _logging_initialized:
        return
    if cfg is None:
        cfg = _get_config()
    log_cfg = cfg.get("logging", {})
    level = getattr(logging, log_cfg.get("level", "INFO").upper(), logging.INFO)
    log_file = log_cfg.get("log_file", "")

    root = logging.getLogger("cyclaw")
    root.setLevel(level)

    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-8s [%(name)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    max_queued, drain_wait_sec = _log_writer_settings(log_cfg)
    # The console is written on the caller's thread by default: tools that run
    # an agentic CLI read its stderr once it exits (see the agentic_logger
    # comment below), so those lines must be written before the process ends.
    # gate.py passes background_console=True instead. Its request threads log
    # cyclaw.* records here at the shipped DEBUG level, and a launchd service's
    # stderr is a file (macos/generate_service_plist.py) that can stall with
    # the log volume, so its console is written from a writer thread, bounded
    # like the log file below (Codex review on #1482).
    console: logging.Handler
    if background_console:
        console = _BackgroundConsoleHandler(max_queued=max_queued, drain_wait_sec=drain_wait_sec)
    else:
        console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)

    # agentic.* (and the other out-of-band packages' loggers) are first-party
    # CyClaw code -- I6 only forbids the core six *importing* them, it says
    # nothing about their log records being "third-party". Give "agentic" its
    # own level and console handler here, unconditionally and before the
    # log_file branch below:
    #   - setLevel must win over whatever _capture_third_party sets on the
    #     REAL root logger further down -- a logger's own explicit level
    #     always overrides an inherited one, so setting it here first means
    #     "agentic" is never silently gated to the third-party floor just
    #     because it has no ancestor level of its own.
    #   - addHandler(console) preserves stderr visibility. Before this call
    #     ran at all, agentic.* relied on Python's lastResort fallback
    #     (stderr) because no handler existed anywhere in its ancestor chain
    #     -- but attaching a handler to ANY ancestor of a logger (this one,
    #     or -- via capture_third_party below -- the real root) silences
    #     lastResort for it too. Tools that shell out to an agentic CLI and
    #     capture its stderr (e.g. /ops/fsconnect relaying pathsafe's
    #     incomplete-listing warning in its response body) depend on that
    #     stream staying populated (codex review on #1239).
    agentic_logger = logging.getLogger("agentic")
    agentic_logger.setLevel(level)
    agentic_logger.addHandler(console)

    if log_file:
        anchored_log_file = _anchor(log_file)
        anchored_log_file.parent.mkdir(parents=True, exist_ok=True)
        # _capture_third_party attaches a file handler to the REAL root, and its
        # filter deliberately passes cyclaw.* through at any level and agentic.*
        # through at WARNING+ (see _ThirdPartyFloor) -- so when it attaches,
        # that single handler already writes cyclaw, agentic (at WARNING and
        # above), and third-party records to this path. A second file handler on
        # the "cyclaw" logger would then write every CyClaw line twice (once
        # here, once at root via propagation) and hold two fds on one file.
        # Only own the file directly when third-party capture is switched off
        # and nothing else will. Either way the file is written by a
        # _BackgroundFileHandler (see the comment above it).
        if not _capture_third_party(log_cfg, anchored_log_file, fmt):
            fh = _BackgroundFileHandler(anchored_log_file, max_queued=max_queued, drain_wait_sec=drain_wait_sec)
            fh.setFormatter(fmt)
            root.addHandler(fh)
            # With capture_third_party off, the real root logger has no
            # handler of its own (see above), so agentic.* records -- which
            # never propagate through the "cyclaw" logger, only through their
            # own "agentic" ancestor -- would otherwise go nowhere durable
            # even though an operator turning this switch off is asking to
            # silence noisy externals (chromadb/httpx/uvicorn/langgraph), not
            # CyClaw's own out-of-band subsystems. Reuse the same handler
            # rather than opening a second fd on the same path.
            agentic_logger.addHandler(fh)

    _logging_initialized = True


# The application log (logging.log_file) is written by one writer thread.
#
# logging.FileHandler writes on the caller's thread while holding the
# handler's lock (logging.Handler.handle holds it around emit). When the
# filesystem under log_file stalls, the first thread to log blocks inside
# write(), and every other thread that logs to that handler waits on the lock
# behind it: request threads included (graph.py's DEBUG lines, gate.py's
# warnings, the Numbat writer's own stall warnings). _BackgroundFileHandler
# formats each record on the caller's thread, as FileHandler does, and queues
# the finished line for a writer thread that owns the file, so a caller only
# ever takes a short in-memory lock. On a healthy disk the writer is
# microseconds behind.
#
# Bounded: with logging.max_queued_records lines waiting, a new line is
# dropped and counted. The first drop of a backlog is noted on stderr, from a
# thread of its own (see _StderrNotes), and the count is written into the log
# once the writer catches up (or noted on stderr at close, if it never does).
#
# Exit: logging.shutdown() runs from atexit, registered when logging was first
# imported, so it runs after CyClaw's own atexit hooks, which may still log.
# It calls flush() and then close() on each handler, and each of those waits
# at most logging.drain_wait_sec (close() once more for its note on stderr),
# so a write stuck on a stalled disk delays exit instead of hanging it.
#
# Closed is not final. logging.config.dictConfig closes every handler (it runs
# logging.shutdown() over all of them) and leaves each attached to its
# loggers. uvicorn.run() does that when `python gate.py` starts serving, after
# setup_logging has run. FileHandler reopens its file on the next line, and so
# does this handler: the line clears the closed state, the writer opens the
# file again on its own thread, and the handler rejoins the list that
# logging.shutdown() closes at exit, which dictConfig also empties (Codex
# review on #1482).
#
# Not logging.handlers.QueueHandler with a QueueListener: QueueListener.stop()
# joins its thread with no timeout, and its target (a FileHandler) is itself
# registered with logging.shutdown(), which takes that handler's lock at exit,
# the lock a stuck write holds. Either would hang exit on the very stall this
# handler exists for. Here the writer's file object is not a handler at all.
#
# The console: an agentic CLI's is written on the caller's thread, since
# tools read its stderr once it exits. The gateway's is a
# _BackgroundConsoleHandler, the same writer aimed at stderr, since a launchd
# service's stderr is a file that can stall too (see setup_logging). It writes
# below stderr's buffer, as the notes on stderr do (see _write_below_buffer).
#
# These defaults apply when the logging block does not set a value, or sets
# one boot validation would refuse; they match the shipped config.
_DEFAULT_MAX_QUEUED_RECORDS = 10000
_DEFAULT_LOG_DRAIN_WAIT_SEC = 2.0

# Every handler, so a forked child can reset them (see _reset_log_writers_after_fork).
_BACKGROUND_HANDLERS: weakref.WeakSet["_BackgroundFileHandler"] = weakref.WeakSet()


def _log_writer_settings(log_cfg: dict[str, Any]) -> tuple[int, float]:
    """logging.max_queued_records and logging.drain_wait_sec, each falling back to its default."""
    max_queued = log_cfg.get("max_queued_records")
    if isinstance(max_queued, bool) or not isinstance(max_queued, int) or max_queued < 1:
        max_queued = _DEFAULT_MAX_QUEUED_RECORDS
    drain = log_cfg.get("drain_wait_sec")
    # The chained comparison refuses NaN (it fails every comparison), .inf and
    # anything past threading.TIMEOUT_MAX, the longest timed wait the platform
    # accepts. Comparing an int is exact, so a huge one never reaches float().
    if isinstance(drain, bool) or not isinstance(drain, int | float) or not 0 < drain <= threading.TIMEOUT_MAX:
        drain = _DEFAULT_LOG_DRAIN_WAIT_SEC
    return max_queued, float(drain)


# Without PYTHONUNBUFFERED (the launchd plist does not set it; the Docker image
# does), sys.stderr is a TextIOWrapper over an io.BufferedWriter, which holds a
# lock for as long as a write to the file below it takes. A thread stuck there
# on a stalled stderr keeps that lock, and the next flush of sys.stderr waits
# for it: at exit, logging.shutdown() flushes logging.lastResort, whose stream
# is sys.stderr, so exit would wait out the stall (adversarial review on
# #1482). The raw file under the buffer takes no lock, so a write stuck there
# holds nothing but its own thread. A stderr with no buffer (unbuffered, or a
# test's capture object) has no such lock and is written as usual.
def _write_below_buffer(stream: TextIO, text: str) -> None:
    """Write ``text`` to the raw file under ``stream``'s buffer, or through ``stream`` when there is none."""
    raw = getattr(getattr(stream, "buffer", None), "raw", None)
    if raw is None:
        stream.write(text)
        stream.flush()
        return
    # Encoded as the TextIOWrapper would: Python's sys.stderr writes "\n" as
    # os.linesep ("\r\n" on Windows).
    data = memoryview(text.replace("\n", os.linesep).encode(stream.encoding or "utf-8", "backslashreplace"))
    while data:
        written = raw.write(data)
        if not written:  # None: a non-blocking stderr with no room
            raise OSError(f"stderr took none of {len(data)} byte(s)")
        data = data[written:]


def _write_to_stderr(message: str) -> None:
    try:
        _write_below_buffer(sys.stderr, f"cyclaw logging: {message}\n")
    except (AttributeError, OSError, ValueError):
        # No stderr (None under pythonw), or a closed or broken one: there is
        # nowhere left to say it.
        return


# Notes about a log file reach stderr from one daemon thread, never from a
# logging caller or close(). stderr can be a file too: the launchd service
# points StandardErrorPath at one (macos/generate_service_plist.py), which can
# stall along with the log volume. emit() runs under the handler's lock, so a
# note stuck on stderr there would hold every thread that logs through the
# handler (Codex review on #1482). A caller only queues its note. Past
# _MAX_QUEUED_NOTES waiting, notes are dropped, and the next one written says
# how many. The bound caps memory on a rare path (a note per state change of a
# handler) rather than tuning anything, so it is not in config.yaml.
_MAX_QUEUED_NOTES = 100


class _StderrNotes:
    def __init__(self, max_queued: int) -> None:
        self.max_queued = max_queued
        self._reset()

    def _reset(self) -> None:
        self._cond = threading.Condition()
        self._pending: deque[tuple[int, str]] = deque()
        self._queued = 0
        self._written = 0
        self._dropped = 0
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the thread now: late in interpreter shutdown, after atexit, Python refuses new threads."""
        with self._cond:
            self._ensure_running()

    def note(self, message: str) -> None:
        with self._cond:
            if len(self._pending) >= self.max_queued or not self._ensure_running():
                self._dropped += 1
                return
            self._queued += 1
            self._pending.append((self._queued, message))
            self._cond.notify_all()

    def wait(self, timeout: float) -> bool:
        """Wait up to ``timeout`` s for every note queued so far; True once they are all written."""
        with self._cond:
            target = self._queued
            deadline = time.monotonic() + timeout
            while self._written < target:
                if not self._running():
                    return False
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._cond.wait(remaining)
            return True

    def _running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _ensure_running(self) -> bool:
        if self._running():
            return True
        thread = threading.Thread(target=self._run, name="cyclaw-log-notes", daemon=True)
        try:
            thread.start()
        except RuntimeError:
            return False
        self._thread = thread
        return True

    def _run(self) -> None:
        while True:
            with self._cond:
                while not self._pending:
                    self._cond.wait()
                seq, message = self._pending.popleft()
                dropped, self._dropped = self._dropped, 0
            if dropped:
                message = f"{message} ({dropped} earlier note(s) dropped while stderr was behind)"
            _write_to_stderr(message)
            with self._cond:
                self._written = seq
                self._cond.notify_all()


_STDERR_NOTES = _StderrNotes(_MAX_QUEUED_NOTES)


def _note_on_stderr(message: str) -> None:
    """Tell the operator about the log file itself, somewhere other than the log file.

    Not through logging: a record about a stalled log file would only join the
    backlog it describes. Queued for the stderr thread above; never waits.
    """
    _STDERR_NOTES.note(message)


def _register_for_shutdown(handler: logging.Handler) -> None:
    """Put ``handler`` back on the list logging.shutdown() closes at exit, unless it is still there."""
    # Handler.__init__ put it there; dictConfig empties the list after closing
    # every handler on it (see the comment above _BackgroundFileHandler).
    handler_refs = getattr(logging, "_handlerList", None)
    add_ref = getattr(logging, "_addHandlerRef", None)
    if handler_refs is None or add_ref is None:
        return
    if any(ref() is handler for ref in list(handler_refs)):
        return
    add_ref(handler)


class _BackgroundFileHandler(logging.Handler):
    """Append formatted records to ``path`` from one writer thread (see the comment above)."""

    def __init__(self, path: Path, *, max_queued: int, drain_wait_sec: float) -> None:
        super().__init__()
        self.path = path
        self.max_queued = max_queued
        self.drain_wait_sec = drain_wait_sec
        # Lines dropped because the queue was full or no writer could start,
        # and lines whose write raised (lost, as with FileHandler).
        self.dropped = 0
        self.failed = 0
        # Opened here, on the thread that sets logging up, as FileHandler opens
        # its file: a bad path fails setup, and the file exists once setup
        # returns. close() closes it, unless a write is still stuck in it, and
        # the writer opens it again for a line logged after that.
        self._stream: TextIO | None = self._open_stream()
        self._reset_queue()
        _BACKGROUND_HANDLERS.add(self)
        # Started now so a line logged during interpreter shutdown, when Python
        # refuses new threads, still has a writer; emit() restarts it if needed.
        # The stderr thread likewise, for a note raised that late.
        self._start()
        _STDERR_NOTES.start()

    def _reset_queue(self) -> None:
        self._cond = threading.Condition()
        self._pending: deque[tuple[int, str]] = deque()
        # Sequence numbers: the last line queued, and the last line the writer
        # finished with (written, or failed).
        self._queued = 0
        self._written = 0
        # Drops not yet counted into the file.
        self._dropped_unreported = 0
        self._failing = False
        self._closing = False
        self._thread: threading.Thread | None = None

    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = self.format(record) + "\n"
        except Exception:  # noqa: BLE001 - as logging.StreamHandler.emit does
            self.handleError(record)
            return
        note: str | None = None
        with self._cond:
            # A line after close() reopens the handler (see the comment above
            # the class). The writer opens the file again if close() closed it.
            reopened, self._closing = self._closing, False
            if len(self._pending) >= self.max_queued:
                note = self._drop_locked(f"{len(self._pending)} are still waiting to be written")
            elif self._running() or self._start():
                self._queued += 1
                self._pending.append((self._queued, line))
                self._cond.notify_all()
            else:
                # No writer thread can start (interpreter shutdown, or the
                # process is out of threads). Writing here would put the caller
                # back behind the disk, so the line is dropped like one past a
                # full queue.
                note = self._drop_locked("no writer thread could start")
        if reopened:
            _register_for_shutdown(self)
        if note:
            _note_on_stderr(note)

    def _drop_locked(self, cause: str) -> str | None:
        """Count a dropped line (lock held); a note for the first drop of a backlog."""
        self.dropped += 1
        self._dropped_unreported += 1
        if self._dropped_unreported > 1:
            return None
        return (f"dropping lines for {self.where} because {cause}; the count is written into it "
                "once its writer catches up")

    def flush(self) -> None:
        """Wait up to logging.drain_wait_sec for every line queued so far to reach the file."""
        self.drain(self.drain_wait_sec)

    def drain(self, timeout: float) -> bool:
        """Wait up to ``timeout`` s for every line queued so far; True once the writer finished them all."""
        with self._cond:
            target = self._queued
            deadline = time.monotonic() + timeout
            while self._written < target:
                if not self._running():
                    return False
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._cond.wait(remaining)
            return True

    def close(self) -> None:
        """Let the writer finish, waiting at most logging.drain_wait_sec, then close the file.

        A write still stuck after that keeps the file open: the writer is
        inside it, and the OS closes the file at exit. A line logged after
        close() reopens the handler (see emit).
        """
        # Under the handler's lock, as FileHandler.close() is, so no caller's
        # emit() reopens the handler halfway through. logging.shutdown()
        # already holds it; it is reentrant. The writer never takes it.
        self.acquire()
        try:
            with self._cond:
                already_closing = self._closing
                self._closing = True
                self._cond.notify_all()
                thread = self._thread
            if not already_closing:
                if thread is not None and thread is not threading.current_thread():
                    thread.join(self.drain_wait_sec)
                with self._cond:
                    stuck = self._running()
                    unwritten = self._queued - self._written
                    uncounted, self._dropped_unreported = self._dropped_unreported, 0
                    stream = None if stuck else self._stream
                    if not stuck:
                        self._stream = None
                if unwritten or uncounted:
                    _note_on_stderr(f"closing {self.where} with {unwritten} queued line(s) not written and "
                                    f"{uncounted} dropped line(s) not yet counted in it "
                                    f"({self.dropped} dropped in all)")
                # A process exiting now would lose a note still queued, such as
                # this one or the writer's report of a last write that failed
                # (Codex review on #1482), so wait for them, as long as for the
                # file and no longer. With nothing queued this returns at once.
                _STDERR_NOTES.wait(self.drain_wait_sec)
                if stream is not None:
                    self._close_stream(stream)
        finally:
            self.release()
        super().close()

    @property
    def where(self) -> str:
        """What the notes on stderr call this handler's target."""
        return str(self.path)

    def _open_stream(self) -> TextIO | None:
        return open(self.path, "a", encoding="utf-8")  # noqa: SIM115  # codeql[py/file-not-closed] closed in _close_stream()

    def _close_stream(self, stream: TextIO) -> None:
        try:
            stream.close()
        except OSError:
            # Best-effort, as close_audit_handles(): nothing else to do.
            pass

    def _running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _start(self) -> bool:
        thread = threading.Thread(target=self._run, name="cyclaw-log-writer", daemon=True)
        try:
            thread.start()
        except RuntimeError:
            return False
        self._thread = thread
        return True

    def _write(self, line: str) -> Exception | None:
        try:
            if self._stream is None:
                # close() closed it and a line came after, or a forked child
                # could not open it again. Opened here, not on the caller's
                # thread: opening a file on a stalled volume can block too.
                self._stream = self._open_stream()
            stream = self._stream
            if stream is None:
                raise ValueError(f"{self.where} is not open")  # sys.stderr is None under pythonw
            self._write_line(stream, line)
        except Exception as exc:  # noqa: BLE001 - the writer outlives any one bad write
            return exc
        return None

    def _write_line(self, stream: TextIO, line: str) -> None:
        stream.write(line)
        stream.flush()

    def _drop_report(self, count: int, total: int) -> str:
        record = logging.LogRecord(
            "cyclaw.logger", logging.WARNING, __file__, 0,
            "dropped %d log line(s) while the log writer was behind, %d in all", (count, total), None,
        )
        return self.format(record) + "\n"

    def _run(self) -> None:
        while True:
            with self._cond:
                while not self._pending and not self._closing:
                    self._cond.wait()
                if not self._pending:
                    # Closing, and every queued line is written. Cleared under
                    # the lock, so a line that reopens the handler from here on
                    # finds no writer running and starts one.
                    if self._thread is threading.current_thread():
                        self._thread = None
                    return
                seq, line = self._pending.popleft()
            error = self._write(line)
            reported = total = 0
            if error is None:
                # The queue just emptied: count the drops into the file now,
                # before this line is marked written, so whoever flush()es
                # finds the count there too.
                with self._cond:
                    if not self._pending and self._dropped_unreported:
                        reported, self._dropped_unreported = self._dropped_unreported, 0
                        total = self.dropped
                if reported:
                    error = self._write(self._drop_report(reported, total))
            note: str | None = None
            with self._cond:
                if error is None:
                    if self._failing:
                        note = f"writing {self.where} works again ({self.failed} line(s) lost in all)"
                    self._failing = False
                else:
                    self.failed += 1
                    if reported:
                        self._dropped_unreported += reported  # counted in at the next chance
                    if not self._failing:
                        note = f"writing {self.where} failed ({error}); lines are lost until a write succeeds"
                    self._failing = True
                if note:
                    # Queued before the line counts as written, so whoever
                    # drain()s finds the note queued already (adversarial review
                    # on #1482). _StderrNotes never takes a handler's lock.
                    _note_on_stderr(note)
                self._written = seq
                self._cond.notify_all()


class _BackgroundConsoleHandler(_BackgroundFileHandler):
    """stderr, written from a writer thread as the log file is: the gateway's console (see setup_logging)."""

    def __init__(self, *, max_queued: int, drain_wait_sec: float) -> None:
        super().__init__(Path("<stderr>"), max_queued=max_queued, drain_wait_sec=drain_wait_sec)

    @property
    def where(self) -> str:
        return "stderr"

    def _open_stream(self) -> TextIO | None:
        # Bound once, as logging.StreamHandler binds it. None under pythonw:
        # the writes then fail and are counted.
        return sys.stderr

    def _close_stream(self, stream: TextIO) -> None:
        # stderr is the process's, not this handler's, to close.
        return None

    def _write_line(self, stream: TextIO, line: str) -> None:
        _write_below_buffer(stream, line)


def _reset_log_writers_after_fork() -> None:
    """A forked child gets a fresh queue, lock, file object and writer thread per handler.

    The parent's writer thread does not exist in the child, a lock held at the
    fork would stay held there, and the parent's file object may be mid-write.
    Lines the parent queued are the parent's to write. The stderr thread's
    queue and lock are reset for the same reasons.
    """
    _STDERR_NOTES._reset()
    for handler in list(_BACKGROUND_HANDLERS):
        closing = handler._closing
        handler._reset_queue()
        handler._closing = closing
        if closing:
            continue
        try:
            handler._stream = handler._open_stream()
        except OSError:
            handler._stream = None  # the writer tries again for the next line


if hasattr(os, "register_at_fork"):  # POSIX only
    os.register_at_fork(after_in_child=_reset_log_writers_after_fork)


# Loggers outside the "cyclaw" namespace: httpx, chromadb, uvicorn, langgraph.
# Their records never reach the handlers attached to the "cyclaw" logger above,
# so before this they went wherever the process's root logger happened to point
# -- in practice stderr, i.e. nowhere durable.
_THIRD_PARTY_DEFAULT_LEVEL = "INFO"


class _ThirdPartyFloor(logging.Filter):
    """Let ``cyclaw.*`` through at any level, ``agentic.*`` through at WARNING
    and above; hold everything else at a floor.

    This exists for a security reason, not a noise one. ``logging.level`` is now
    DEBUG so CyClaw's own modules are fully traced, but attaching that same
    level to third-party libraries would put ``httpcore``'s wire-level DEBUG
    output -- which includes the ``Authorization:`` header on every outbound
    Grok/Claude/Ollama call -- into a file on disk. CyClaw's own DEBUG lines
    were audited for this: the four in graph.py log chunk counts and budget
    arithmetic, never query text, prompts, or answers.

    ``agentic.*`` gets a narrower exemption than ``cyclaw.*``: WARNING and
    above only, not a full DEBUG passthrough. It is first-party CyClaw code
    (I6 only forbids the core six *importing* it, not its logging being
    treated as third-party) -- setup_logging's own ``agentic_logger.setLevel``
    call would otherwise be defeated at exactly the operators who most need
    it: someone who raises ``third_party_level`` above WARNING to quiet noisy
    externals would also silence agentic's own warnings and errors, since a
    logger's effective level only gates whether a record is CREATED, not
    whether this filter later lets it through a shared handler. Unlike the
    four graph.py DEBUG lines above, agentic's DEBUG-level output has not been
    audited line-by-line for secrets, so it still respects the configured
    floor rather than bypassing it outright (codex review on #1239).
    """

    def __init__(self, floor: int) -> None:
        super().__init__()
        self.floor = floor

    def filter(self, record: logging.LogRecord) -> bool:
        if record.name == "cyclaw" or record.name.startswith("cyclaw."):
            return True
        if record.levelno >= logging.WARNING and (
            record.name == "agentic" or record.name.startswith("agentic.")
        ):
            return True
        return record.levelno >= self.floor


def _capture_third_party(
    log_cfg: dict, log_path: Path, fmt: logging.Formatter,
) -> bool:
    """Route non-CyClaw loggers into the same file, at a safer level.

    Opt-out via ``logging.capture_third_party: false``. The floor is
    ``logging.third_party_level`` (default INFO) rather than the global DEBUG --
    see ``_ThirdPartyFloor`` for why that gap is deliberate.

    ONE file handler, on the real root logger. Records from cyclaw.* propagate up
    to root and ``_ThirdPartyFloor`` passes them at any level, so this handler is
    the file's single writer for both namespaces -- setup_logging deliberately
    does NOT also attach one to the "cyclaw" logger while this is active, or
    every CyClaw line would land in the file twice.

    Returns True when the handler was attached, False on the opt-out path, so
    the caller knows whether it still needs its own file handler.
    """
    if log_cfg.get("capture_third_party") is False:
        return False
    floor_name = str(log_cfg.get("third_party_level", _THIRD_PARTY_DEFAULT_LEVEL)).upper()
    floor = getattr(logging, floor_name, logging.INFO)

    real_root = logging.getLogger()
    max_queued, drain_wait_sec = _log_writer_settings(log_cfg)
    handler = _BackgroundFileHandler(log_path, max_queued=max_queued, drain_wait_sec=drain_wait_sec)
    handler.setFormatter(fmt)
    handler.addFilter(_ThirdPartyFloor(floor))
    # The handler's own level stays at the floor; the filter is what allows
    # cyclaw.* records through below it. Both are needed -- a handler level
    # above a record's level drops it before any filter runs.
    handler.setLevel(min(floor, logging.DEBUG))
    real_root.addHandler(handler)
    if real_root.level == logging.NOTSET or real_root.level > floor:
        real_root.setLevel(floor)
    return True

def resolve_config_path(config_path: str = "config.yaml") -> Path:
    """Resolve a config path exactly as ``_get_config`` loads it.

    Relative paths anchor to the repo root (``_REPO_ROOT``), never the process
    cwd, so a caller that records "which config did I load" gets the SAME file
    the loader opened. The sync scheduler relies on this: it re-invokes the CLI
    with the recorded path, and a cwd-anchored ``os.path.abspath`` could name a
    different (or missing) file than the one actually read (codex #592 P1).
    """
    path = Path(config_path).expanduser()
    if not path.is_absolute():
        path = _REPO_ROOT / path
    return path.resolve()


@lru_cache(maxsize=8)
def _get_config(config_path: str = "config.yaml") -> dict:
    with open(resolve_config_path(config_path), encoding="utf-8") as f:
        return yaml.safe_load(f)

def reset_config_cache() -> None:
    clear = getattr(_get_config, "cache_clear", None)
    if clear is not None:
        clear()

def hash_query(query: str) -> str:
    return hashlib.sha256(query.encode("utf-8")).hexdigest()


def include_query_hash(cfg: dict[str, Any] | None) -> bool:
    """logging.audit_fields.include_query_hash, default True, tolerant of any shape.

    The one reader of this opt-out. audit_log and every derived stream
    (graph.py's fallback spend context, the pre-action hook, the Numbat gate
    and CEL monitor) must agree, or a stream would carry the hash an operator
    disabled. A missing, null or non-mapping block keeps the hash on:
    commenting out the only key under ``audit_fields:`` makes YAML read the
    block as null, and that previously made audit_log drop every event that
    carries a query instead of writing it.
    """
    logging_cfg = cfg.get("logging") if isinstance(cfg, dict) else None
    audit_fields = logging_cfg.get("audit_fields") if isinstance(logging_cfg, dict) else None
    if not isinstance(audit_fields, dict):
        return True
    return bool(audit_fields.get("include_query_hash", True))

@lru_cache(maxsize=8)
def _compiled_redactors(
    redact_emails: bool,
    redact_ips: bool,
    secret_patterns: tuple[tuple[int, str], ...],
    invalid_secret_patterns: tuple[tuple[int, str], ...],
) -> tuple[tuple[re.Pattern, str], ...]:
    """Compile the active redaction patterns once per privacy configuration.

    redact_sensitive runs on every audited field of every query; recompiling
    these regexes each call was pure overhead. Keyed on the (hashable) privacy
    settings so a config change still produces a fresh pattern set.
    """
    compiled = []
    if redact_emails:
        compiled.append((re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'),
                         '[REDACTED_EMAIL]'))
    if redact_ips:
        compiled.append((re.compile(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b'),
                         '[REDACTED_IP]'))
    for idx, pattern_type in invalid_secret_patterns:
        logger.warning(
            "privacy redaction pattern #%d has non-string type %s; it is "
            "skipped, so matching values pass through un-redacted until it "
            "is corrected.",
            idx, pattern_type,
        )
    for idx, pattern in secret_patterns:
        try:
            compiled.append((re.compile(pattern), '[REDACTED_SECRET]'))
        except re.error as exc:
            # Silently dropping an invalid pattern disables redaction for that
            # shape with no signal — matching values then reach audit.jsonl and
            # /ops/* output verbatim. Warn instead (mirroring the sanitizer's
            # warn-on-degrade) so a config typo is visible rather than a silent
            # security regression. Log only the entry index and the compile
            # error (which carries the position of the fault) — never the
            # pattern text itself: it comes from privacy config and echoing
            # config values into logs is exactly what clear-text-logging
            # scanners flag. Cached per config, so it fires once per bad entry.
            logger.warning(
                "privacy redaction pattern #%d failed to compile (%s); it is "
                "skipped, so matching values pass through un-redacted until it "
                "is corrected.",
                idx, exc,
            )
    return tuple(compiled)

def _resolve_redactors(cfg: dict) -> tuple[tuple[re.Pattern, str], ...]:
    """Resolve cfg's privacy settings to a compiled redactor tuple.

    Split out of redact_sensitive so a caller redacting many strings against
    the same cfg (audit_log's per-event walk over every field, recursing into
    nested dicts/lists) can resolve this once instead of re-deriving it --
    re-enumerating redact_secrets_like into two fresh tuples and re-hashing
    the 4-element lru_cache key -- for every string in the record.
    """
    privacy = cfg.get("policy", {}).get("privacy", {})
    configured_patterns = privacy.get("redact_secrets_like", []) or []
    return _compiled_redactors(
        privacy.get("redact_emails", False),
        privacy.get("redact_ips", False),
        tuple((idx, pattern) for idx, pattern in enumerate(configured_patterns) if isinstance(pattern, str)),
        tuple(
            (idx, type(pattern).__name__)
            for idx, pattern in enumerate(configured_patterns)
            if not isinstance(pattern, str)
        ),
    )


def redact_sensitive(text: str, cfg: dict | None = None) -> str:
    if cfg is None:
        cfg = _get_config()
    for pattern, replacement in _resolve_redactors(cfg):
        text = pattern.sub(replacement, text)
    return text


# Keys whose top-level value must NOT be redacted: query_hash is already a SHA-256
# digest, timestamp is structural ISO-8601, and event is the event-type tag.
# Applied only at the OUTER record level — nested fields named the same inside a
# dict/list value have no special meaning and pass through normal redaction.
_AUDIT_SKIP_KEYS = frozenset(("query_hash", "timestamp", "event"))


def _redact_value(value: object, redactors: tuple[tuple[re.Pattern, str], ...]) -> object:
    """Recursively redact strings inside dicts and lists.

    audit_log previously only redacted top-level string fields, so an event
    like {"details": {"email": "u@example.com"}} or {"errors": ["...@..."]}
    landed in audit.jsonl with the email intact. Defense-in-depth: structured
    payloads from CLI shims and exception details can contain redact-eligible
    strings that the simple top-level loop walked past. Recurses through dict
    values and list/tuple elements; tuples are returned as lists because
    json.dumps emits both identically and the on-disk format must stay JSON.
    Non-string scalars (int/float/bool/None) pass through unchanged.

    Takes the already-resolved redactor tuple (see _resolve_redactors) rather
    than cfg, so audit_log's recursive per-field walk resolves it once per
    event instead of once per string.
    """
    if isinstance(value, str):
        for pattern, replacement in redactors:
            value = pattern.sub(replacement, value)
        return value
    if isinstance(value, dict):
        return {k: _redact_value(v, redactors) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact_value(v, redactors) for v in value]
    return value


def audit_log(event: dict, config_path: str = "config.yaml", cfg: dict | None = None) -> None:
    if cfg is None:
        cfg = _get_config(config_path)
    log_path = _anchor(cfg["logging"]["audit_file"])
    try:
        record = dict(event)  # work on a shallow copy — never mutate the caller's dict
        if "query" in record and include_query_hash(cfg):
            raw_query = record.pop("query")
            record["query_hash"] = hash_query(raw_query)
        redactors = _resolve_redactors(cfg)
        for key, value in list(record.items()):
            if key in _AUDIT_SKIP_KEYS:
                continue
            record[key] = _redact_value(value, redactors)
        record["timestamp"] = datetime.now(UTC).isoformat()
        line = json.dumps(record) + "\n"
    except (TypeError, ValueError, AttributeError, UnicodeError) as exc:
        # audit_logger is the unconditional terminal node every graph path
        # converges on (invariant I4) -- it runs AFTER the answer is already
        # computed. This function has ~100 call sites across the repo, several
        # passing through caller-supplied **fields; a non-string "query" value
        # (hash_query()'s .encode('utf-8') would raise) or any non-JSON-
        # serializable field anywhere in `event` must not turn an already-good
        # response into an HTTP 500 purely because the audit trail couldn't be
        # built. Same rationale as the OSError guard below, extended to cover
        # record-building/serialization, not just the write.
        logger.warning("audit_log failed to build event %r: %s", event.get("event"), exc)
        return
    try:
        with _AUDIT_WRITE_LOCK:
            handle = _audit_handle(log_path)
            handle.write(line)
            handle.flush()
    except OSError as exc:
        # Letting a disk-full/permission failure here escape would turn an
        # already-good response into an HTTP 500 purely because the audit
        # trail couldn't be persisted. Degrade loudly to the app log instead
        # of raising; the caller still gets its answer.
        logger.warning("audit_log write failed for %s: %s", log_path, exc)
    # Derived Numbat NDJSON projection (top-level numbat: block, shipped
    # enabled). audit.jsonl stays authoritative; the projection is fail-soft
    # and independent. Lazy import: utils/numbat_emitter.py imports _anchor
    # and _get_config from THIS module, so a top-level import would be
    # circular; keeping it inside the call also means gate.py/graph.py gain
    # no import-time numbat surface (I6 hygiene).
    #
    # The import itself is inside the guard, not just the call: it is the one
    # statement here that runs outside project_audit_record's own internal
    # Exception handler, and a derived stream must never be able to raise out
    # of the terminal audit step. Same rationale as the two guards above -- a
    # failure to project must not turn an already-good response into an
    # HTTP 500.
    try:
        from utils.numbat_emitter import project_audit_record

        project_audit_record(record, cfg=cfg)
    except Exception as exc:  # noqa: BLE001 -- derived stream, never fatal
        logger.warning("numbat projection failed for %r: %s", record.get("event"), exc)
