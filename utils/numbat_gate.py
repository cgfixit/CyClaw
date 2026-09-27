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
binary that is not the pinned release, a missing or empty rules directory, a
rule set with no enabled rule, a rules file or directory that cannot be read,
rules directories too large to read within the engine's limits, a rule that
does not compile, a duplicate rule id, a timeout, a non-zero exit, or output
this module cannot parse is a deny.
An allow also needs positive evidence that Numbat evaluated THIS call: the
engine adds its own always-matching canary rule (id ``cyclaw.gate.canary``,
reserved), and a run that does not report it -- ``/bin/true``, a CLI that
skipped the event -- denies, where exit 0 with empty output used to read as
"nothing matched". The rules Numbat evaluates are a byte snapshot, the same
bytes this module classifies, so a rule edited mid-request cannot pair one
version's enforce flag with another version's match. It can only shrink what
the I3 triple gate already allowed.

Stdlib + PyYAML only; the binary runs as a list-form subprocess with no
shell. Numbat is never imported (it is a Go binary, not a library).
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import signal
import subprocess  # nosec B404 - list-form only, no shell, operator-configured binary
import tempfile
import threading
import time
from collections.abc import Callable
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
# be reached, so a rule keyed on event.url sees the host the call goes to.
_DEFAULT_PROVIDER_URLS = {
    "grok": "https://api.x.ai/v1",
    "claude": "https://api.anthropic.com/v1",
}
_PROVIDER_TO_VENDOR = {"grok": "xai", "claude": "anthropic"}
_QUERY_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_RULE_SUFFIXES = (".yaml", ".yml")
_READINESS_TTL_SEC = 30.0
# Budget for one whole /health readiness check, on top of the hook's own
# timeout_sec, which the probe decision gets: the version check (5 s),
# `rules check` (10 s) and reading rules_dirs (_READINESS_READ_SEC).
_READINESS_BUDGET_SEC = 30.0
# The call /health's probe decision proposes. Any provider works: the probe
# exercises the decision path, and its verdict (allow or deny) is not used.
_PROBE_PROVIDER = "grok"
_PROBE_MODEL = "cyclaw-health-probe"
_PROBE_HASH = "0" * 64
_MAX_REASON_CHARS = 300

# The engine's own evidence rule: it matches every event, so each evaluated call
# reports it. Reserved -- an operator rule with this id is refused.
CANARY_RULE_ID = "cyclaw.gate.canary"
_CANARY_RULE = f"""id: {CANARY_RULE_ID}
version: "1.0"
title: CyClaw pre-action gate canary (engine-internal; proves the call was evaluated)
severity: info
expr: "true"
"""


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
    a disagreement between the two loaders can only deny, never allow. Raises
    OSError when a rules file or directory cannot be read, _RulesTooLarge past
    the walk limits, and _RulesDeadline past /health's read budget.
    """
    known, enforcing, _ = _classify(dirs)
    return known, enforcing


def _classify(dirs: list[Path]) -> tuple[set[str], set[str], set[str]]:
    """(every rule id, the ids that can deny, the ids that are enabled) for live dirs.

    Reads the way the decision path does (same limits, a worker thread, a
    budget of _READINESS_READ_SEC), and raises where it would deny, so /health
    does not call ready a rule set every call denies on.
    """
    return _classify_files(_read_rules(dirs, deadline=time.monotonic() + _READINESS_READ_SEC))


def _classify_files(files: list[tuple[int, Path, Path, bytes]]) -> tuple[set[str], set[str], set[str]]:
    """(every rule id, the ids that can deny, the ids that are enabled) for rule files read by _read_rules."""
    known: set[str] = set()
    enforcing: set[str] = set()
    active: set[str] = set()
    for *_, data in files:
        identity = _rule_identity(data)
        if identity is None:
            continue
        known.add(identity[0])
        if identity[1]:
            enforcing.add(identity[0])
        if identity[2]:
            active.add(identity[0])
    return known, enforcing, active


# Limits on reading rules_dirs, across all of them together. The decision path
# reads the rule files on every call and /health reads them too, so a directory
# set too broadly (a home directory, "/") must not stall either: past any of
# these caps the gate denies and /health says why. The decision path also stops
# at the call's deadline, for a slow or stalled mount (see _read_rules). A real
# rule set sits far below all three.
_MAX_RULE_WALK_ENTRIES = 20_000
_MAX_RULE_FILES = 1_000
_MAX_RULE_BYTES = 8 * 1024 * 1024
# Worker threads reading rules_dirs at once, per process. The cap only binds
# when reads are stuck: it stops every new call adding another thread blocked
# on the same mount.
_MAX_RULE_READERS = 4
_RULE_READERS = threading.BoundedSemaphore(_MAX_RULE_READERS)
# /health's own budget for reading rules_dirs, as long as its `rules check`
# timeout.
_READINESS_READ_SEC = 10.0


class _RulesTooLarge(Exception):
    """rules_dirs holds more than the gate will read for one decision."""


class _RulesDeadline(Exception):
    """The decision's time budget ran out while reading rules_dirs."""


class _WalkBudget:
    """Directory entries seen and rule files found so far, across every rules dir of one read."""

    def __init__(self) -> None:
        self.entries = 0
        self.files = 0


def _rule_files(root: Path, walk: _WalkBudget, *, deadline: float | None = None) -> list[Path]:
    """The rule-suffixed files under ``root``, found within the walk limits.

    Only ``*.yaml`` / ``*.yml`` files are returned: nothing else can be a rule
    or a companion test. Symlinked subdirectories are not followed, as
    ``Path.rglob`` did not follow them either. Raises _RulesTooLarge past the
    entry or file cap, _RulesDeadline once ``deadline`` has passed, and
    OSError for a directory it cannot list: the rules in it would otherwise
    drop out of the decision unseen, as an unreadable file would.

    Entries are counted one at a time as os.scandir yields them. os.walk
    lists a whole directory before yielding it, so one very wide directory
    would be read in full before any cap or the deadline could stop it.
    """
    found: list[Path] = []
    pending = [root]
    while pending:
        directory = pending.pop()
        subdirs: list[str] = []
        rule_files: list[Path] = []
        with os.scandir(directory) as entries:
            for entry in entries:
                if deadline is not None and time.monotonic() > deadline:
                    raise _RulesDeadline
                walk.entries += 1
                if walk.entries > _MAX_RULE_WALK_ENTRIES:
                    raise _RulesTooLarge(f"more than {_MAX_RULE_WALK_ENTRIES} entries")
                if entry.is_dir(follow_symlinks=False):
                    subdirs.append(entry.path)
                elif Path(entry.name).suffix in _RULE_SUFFIXES and entry.is_file():
                    rule_files.append(Path(entry.path))
                    walk.files += 1
                    if walk.files > _MAX_RULE_FILES:
                        raise _RulesTooLarge(f"more than {_MAX_RULE_FILES} rule files")
        # Sorted, depth first, as os.walk visited them, so the order of the
        # rules does not depend on the order the filesystem lists them in.
        found.extend(sorted(rule_files))
        pending.extend(Path(path) for path in sorted(subdirs, reverse=True))
    return found


def _read_rule(path: Path, total_bytes: int) -> bytes:
    """One rule file's bytes, keeping everything read for one decision under _MAX_RULE_BYTES.

    The size is checked before the read, so one huge file is never read in
    full, and again after, in case the file grew in between.
    """
    if total_bytes + path.stat().st_size > _MAX_RULE_BYTES:
        raise _RulesTooLarge(f"more than {_MAX_RULE_BYTES} bytes of rules")
    data = path.read_bytes()
    if total_bytes + len(data) > _MAX_RULE_BYTES:
        raise _RulesTooLarge(f"more than {_MAX_RULE_BYTES} bytes of rules")
    return data


def _rule_identity(data: bytes) -> tuple[str, bool, bool] | None:
    """(rule id, can deny, enabled) for one rules file's bytes; None when it is not a rule.

    A rule is enabled unless it sets ``enabled: false``, and it can deny when
    it is enabled and sets ``enforce: true``. Companion ``*_tests.yaml`` files
    carry ``rule_id``, never ``id``.
    """
    try:
        doc = yaml.safe_load(data.decode("utf-8"))
    except (UnicodeError, yaml.YAMLError):
        return None
    if not isinstance(doc, dict) or not isinstance(doc.get("id"), str):
        return None
    enabled = doc.get("enabled", True) is not False
    return doc["id"], doc.get("enforce") is True and enabled, enabled


def _snapshot_rules(
    dirs: list[Path], dest: Path, *, deadline: float,
) -> tuple[list[Path], set[str], set[str], set[str]]:
    """Copy the rule files under each rules dir into ``dest`` and classify the copies.

    Numbat then evaluates the snapshot, so the rules it runs are byte-for-byte
    the rules classified here. Reading the live files twice (once to classify,
    once in the CLI) let a mid-request edit mix two versions: promote rule R
    to enforce and retire rule Q in one change, and a call both versions deny
    was allowed, because the CLI reported only R and the stale classification
    said R could not deny. Each root is resolved once, so swapping a symlink to
    a new rules directory is an atomic way to change several rules at once.
    Raises OSError when a rules file or directory cannot be read: a rule the
    gate cannot see must deny, never vanish from both sides. Only rule files
    are copied, within the walk limits and the call's ``deadline``
    (_RulesTooLarge, _RulesDeadline).

    Returns (snapshot dirs, every rule id, the ids that can deny, the ids that
    are enabled).
    """
    files = _read_rules(dirs, deadline=deadline)
    snapshot = [dest / f"rules-{index}" for index in range(len(dirs))]
    for target_root in snapshot:
        target_root.mkdir()
    for index, real_root, path, data in files:
        target = snapshot[index] / path.relative_to(real_root)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return (snapshot, *_classify_files(files))


def _collect_rules(dirs: list[Path], *, deadline: float) -> list[tuple[int, Path, Path, bytes]]:
    """(rules dir index, resolved root, file, bytes) for every rule file, within the walk limits.

    Checks ``deadline`` between filesystem operations. Each root is resolved
    once, so every file of a root comes from the same directory even if a
    symlink to it is swapped mid-read.
    """
    walk = _WalkBudget()
    total_bytes = 0
    files: list[tuple[int, Path, Path, bytes]] = []
    for index, root in enumerate(dirs):
        real_root = root.resolve()
        for path in _rule_files(real_root, walk, deadline=deadline):
            if time.monotonic() > deadline:
                raise _RulesDeadline
            data = _read_rule(path, total_bytes)
            total_bytes += len(data)
            files.append((index, real_root, path, data))
    return files


def _read_rules(dirs: list[Path], *, deadline: float) -> list[tuple[int, Path, Path, bytes]]:
    """_collect_rules on a worker thread, abandoned if it is still running at ``deadline``.

    A read blocked in the kernel (a stalled network mount) cannot be
    interrupted, so the caller stops waiting at the deadline instead and
    denies. The worker only holds what it read in memory, never the call's
    temp directory, so one that wakes up later changes nothing.
    _RULE_READERS caps how many can be stuck at once: past it, a call waits
    for a free slot until its deadline rather than adding another thread on
    the same mount. Raises _RulesDeadline, or whatever _collect_rules raised.
    """
    remaining = deadline - time.monotonic()
    if remaining <= 0 or not _RULE_READERS.acquire(timeout=remaining):
        raise _RulesDeadline
    outcome: list[list[tuple[int, Path, Path, bytes]] | Exception] = []

    def _work() -> None:
        try:
            outcome.append(_collect_rules(dirs, deadline=deadline))
        except Exception as exc:  # noqa: BLE001 - handed to the waiting caller below
            outcome.append(exc)
        finally:
            _RULE_READERS.release()

    worker = threading.Thread(target=_work, name="numbat-rules-read", daemon=True)
    try:
        worker.start()
    except BaseException:
        _RULE_READERS.release()
        raise
    worker.join(max(0.0, deadline - time.monotonic()))
    if worker.is_alive() or not outcome:
        raise _RulesDeadline
    result = outcome[0]
    if isinstance(result, Exception):
        raise result
    return result


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
    # lazy: keeps this module's import surface stdlib + yaml
    from utils.numbat_emitter import build_event, redact_url_for_numbat

    preview = None
    if _include_query_hash(cfg) and _QUERY_HASH_RE.fullmatch(query_hash or ""):
        preview = json.dumps({"query_hash": query_hash}, separators=(",", ":"))
    return build_event(
        "network.indicator",
        url=redact_url_for_numbat(_provider_url(provider, cfg)),
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


# Cap on what the numbat binary may print on each stream. Until it has printed
# the pinned version it is just some program: `yes` would fill memory at
# hundreds of MB a second. Numbat's real output is a line per matched rule.
_MAX_CLI_OUTPUT = 1024 * 1024
_CLI_READ_CHUNK = 64 * 1024
# Reader threads for the binary's output, across all calls. A process the
# binary leaves behind can hold its pipes open past the kill (one that left
# its process group, or any child on Windows), and its readers stay until it
# closes them. The cap stops those piling up: at the cap, a call waits for a
# free slot until its deadline and then times out.
_MAX_CLI_READERS = 32
_CLI_READER_SLOTS = threading.BoundedSemaphore(_MAX_CLI_READERS)


class _CliOutputTooLarge(Exception):
    """The numbat binary printed more than _MAX_CLI_OUTPUT on one stream."""


def _run_cli(argv: list[str], *, timeout: float) -> subprocess.CompletedProcess[str]:
    """``subprocess.run(argv, capture_output=True, text=True, timeout=...)``, bounded.

    Everything, reading the output included, happens within ``timeout``:
    past it, or once either stream passes _MAX_CLI_OUTPUT, the binary and
    anything left in its process group are killed, and
    subprocess.TimeoutExpired or _CliOutputTooLarge is raised. A child that
    keeps the pipes open after the binary exits counts as not finished. A
    killed process is not waited on.
    """
    deadline = time.monotonic() + timeout
    if not _acquire_reader_slots(2, deadline):
        raise subprocess.TimeoutExpired(argv, timeout)
    try:
        proc = subprocess.Popen(  # noqa: S603  # nosec B603 - list-form, no shell
            argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            start_new_session=True,  # its own process group, so a kill reaches its children (POSIX)
        )
    except BaseException:
        _CLI_READER_SLOTS.release()
        _CLI_READER_SLOTS.release()
        raise
    captured = (bytearray(), bytearray())
    overflow = threading.Event()

    def _pump(stream: Any, sink: bytearray) -> None:
        try:
            with stream:
                while chunk := os.read(stream.fileno(), _CLI_READ_CHUNK):
                    if len(sink) + len(chunk) > _MAX_CLI_OUTPUT:
                        overflow.set()
                        _kill_tree(proc)
                        return
                    sink.extend(chunk)
        finally:
            _CLI_READER_SLOTS.release()

    pumps = [
        threading.Thread(target=_pump, args=(stream, sink), name="numbat-cli-output", daemon=True)
        for stream, sink in zip((proc.stdout, proc.stderr), captured, strict=True)
    ]
    for started, pump in enumerate(pumps):
        try:
            pump.start()
        except BaseException:
            _kill_tree(proc)
            for _ in pumps[started:]:
                _CLI_READER_SLOTS.release()
            raise
    try:
        returncode = proc.wait(timeout=max(0.0, deadline - time.monotonic()))
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        raise
    # The output ends when every process holding the pipes has closed them,
    # which a child the binary left running may never do: wait only until the
    # deadline, then kill what is left of its group and give up on the output.
    for pump in pumps:
        pump.join(max(0.0, deadline - time.monotonic()))
    if any(pump.is_alive() for pump in pumps):
        _kill_tree(proc)
        raise subprocess.TimeoutExpired(argv, timeout)
    if overflow.is_set():
        raise _CliOutputTooLarge
    stdout, stderr = (bytes(sink).decode("utf-8", errors="replace") for sink in captured)
    return subprocess.CompletedProcess(argv, returncode, stdout=stdout, stderr=stderr)


def _acquire_reader_slots(count: int, deadline: float) -> bool:
    """Take ``count`` reader slots, waiting no later than ``deadline``; all or none."""
    taken = 0
    while taken < count:
        if not _CLI_READER_SLOTS.acquire(timeout=max(0.0, deadline - time.monotonic())):
            for _ in range(taken):
                _CLI_READER_SLOTS.release()
            return False
        taken += 1
    return True


def _kill_tree(proc: subprocess.Popen[bytes]) -> None:
    """Kill the binary and, on POSIX, everything still in its process group."""
    if os.name == "posix":
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass  # the group is already gone
    try:
        proc.kill()
    except OSError:
        pass  # it has already exited, so there is nothing left to kill
    proc.poll()  # reap it if it is already dead; otherwise subprocess reaps it later


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
    The whole decision runs within ``timeout`` (see _within).
    """
    try:
        return _within(timeout, lambda: _evaluate(provider, model, query_hash, cfg, timeout=timeout))
    except _Stalled:
        return _deny("hook_timeout", f"numbat gate did not decide within {timeout:g}s")
    except Exception as exc:  # noqa: BLE001 - the gate fails closed, whatever broke
        logger.warning("numbat gate raised %s; denying", type(exc).__name__)
        return _deny("hook_error", f"numbat gate error: {type(exc).__name__}")


# Decisions (and /health checks) run on worker threads, at most this many at
# once per process. The cap only binds when workers are stuck: then a new
# call waits for a slot until its deadline instead of adding another.
_MAX_GATE_WORKERS = 8
_GATE_WORKER_SLOTS = threading.BoundedSemaphore(_MAX_GATE_WORKERS)
# Slack past the budget before the caller stops waiting, so a decision that
# ends on time with its own reason is not cut off by this outer bound.
_GATE_WORKER_GRACE_SEC = 0.25


class _Stalled(Exception):
    """A gate worker did not finish within its budget."""


def _within[T](timeout: float, work: Callable[[], T]) -> T:
    """Run ``work`` on a worker thread and stop waiting after ``timeout``.

    Every step of a decision can block on the filesystem: checking that the
    rules directories exist, finding the binary, the exec of the binary
    itself, reading rules. On a stalled network mount any of them can block
    for good, and no deadline check between steps interrupts one. So the
    whole decision runs on a worker that the caller abandons at the deadline
    (_Stalled). The steps inside still bound themselves, so a worker that
    wakes up later only finishes cleaning up after itself.
    """
    deadline = time.monotonic() + timeout + _GATE_WORKER_GRACE_SEC
    if not _GATE_WORKER_SLOTS.acquire(timeout=max(0.0, deadline - time.monotonic())):
        raise _Stalled
    outcome: list[Any] = []

    def _run() -> None:
        try:
            outcome.append((True, work()))
        except Exception as exc:  # noqa: BLE001 - handed to the waiting caller below
            # Anything else (SystemExit in this thread) leaves outcome empty,
            # which the caller reads as _Stalled and denies.
            outcome.append((False, exc))
        finally:
            _GATE_WORKER_SLOTS.release()

    worker = threading.Thread(target=_run, name="numbat-gate", daemon=True)
    try:
        worker.start()
    except BaseException:
        _GATE_WORKER_SLOTS.release()
        raise
    worker.join(max(0.0, deadline - time.monotonic()))
    if worker.is_alive() or not outcome:
        raise _Stalled
    ok, value = outcome[0]
    if not ok:
        raise value
    return value  # type: ignore[no-any-return]


def _evaluate(provider: str, model: str, query_hash: str, cfg: dict[str, Any] | None, *, timeout: float) -> dict[str, Any]:
    # One budget for the whole decision: the version check and the rules run
    # share timeout_sec rather than each getting all of it.
    deadline = time.monotonic() + timeout
    dirs = rules_dirs(cfg)
    if not dirs:
        return _deny("hook_misconfigured", "numbat engine needs a non-empty list of rules_dirs")
    missing = [str(d) for d in dirs if not d.is_dir()]
    if missing:
        return _deny("hook_misconfigured", f"numbat rules dir not found: {missing[0]}")
    binary = resolve_binary(cfg)
    if binary is None:
        return _deny("hook_error", "numbat binary not found (policy.fallback.pre_action_hook.numbat.binary)")

    # readiness() checks the version too, but only for /health, which advises
    # and cannot enforce. A wrong binary must deny here, on the call itself.
    try:
        version = _run_cli([binary, "version"], timeout=timeout)
    except subprocess.TimeoutExpired:
        return _deny("hook_timeout", f"numbat version check timed out after {timeout:g}s")
    except _CliOutputTooLarge:
        return _deny("hook_misconfigured", f"numbat binary is not the pinned {PINNED_VERSION_LINE!r}")
    except (OSError, ValueError) as exc:
        return _deny("hook_error", f"numbat could not run: {type(exc).__name__}")
    if _first_line(version.stdout) != PINNED_VERSION_LINE:
        return _deny("hook_misconfigured", f"numbat binary is not the pinned {PINNED_VERSION_LINE!r}")

    event = build_gate_event(provider, model, query_hash, cfg)
    with tempfile.TemporaryDirectory(prefix="cyclaw-pre-action-", ignore_cleanup_errors=True) as work:
        workdir = Path(work)
        try:
            snapshot, known, enforcing, active = _snapshot_rules(dirs, workdir, deadline=deadline)
        except _RulesDeadline:
            return _deny("hook_timeout", f"numbat gate ran out of its {timeout:g}s budget reading rules_dirs")
        except _RulesTooLarge as exc:
            return _deny("hook_misconfigured", f"rules_dirs is too large for the gate ({exc}); point it at the rules directory")
        except OSError as exc:
            return _deny("hook_error", f"numbat rules could not be read: {type(exc).__name__}")
        if CANARY_RULE_ID in known:
            return _deny("hook_misconfigured", f"rule id {CANARY_RULE_ID} is reserved for the engine")
        # The canary gives `rules test` something to run even when no operator
        # rule is enabled, so "no enforce rule matched" would then allow every
        # call. With nothing enabled there is nothing to decide with: deny,
        # as an all-disabled rule set did before the canary existed.
        if not active:
            return _deny("hook_misconfigured", "no enabled rule in rules_dirs, so the gate has nothing to decide with")
        canary_dir = workdir / "canary"
        canary_dir.mkdir()
        (canary_dir / "cyclaw_gate_canary.yaml").write_text(_CANARY_RULE, encoding="utf-8")
        fixture = workdir / "event.ndjson"
        fixture.write_text(json.dumps(event, separators=(",", ":"), ensure_ascii=False) + "\n", encoding="utf-8")
        argv = [binary, "rules", "test", "--fixture", str(fixture), "--no-builtin-rules"]
        for directory in [*snapshot, canary_dir]:
            argv += ["--rules-dir", str(directory)]
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return _deny("hook_timeout", f"numbat gate ran out of its {timeout:g}s budget")
        try:
            proc = _run_cli(argv, timeout=remaining)
        except subprocess.TimeoutExpired:
            return _deny("hook_timeout", f"numbat rules test timed out after {timeout:g}s")
        except _CliOutputTooLarge:
            return _deny("hook_failure", "numbat rules test printed more output than the engine reads")
        except (OSError, ValueError) as exc:
            return _deny("hook_error", f"numbat could not run: {type(exc).__name__}")

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

    # Positive evidence: exit 0 with no output is also what /bin/true, or a
    # CLI that skipped the event, would produce. Only the canary's match
    # shows the rules actually ran against this call.
    if CANARY_RULE_ID not in matched:
        return _deny("hook_failure", "numbat rules test did not evaluate the proposed call (no canary match)")
    matched = [rule for rule in matched if rule != CANARY_RULE_ID]

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
# Keys whose check is running now (see readiness).
_READINESS_RUNNING: set[tuple[Any, ...]] = set()


def readiness(cfg: dict[str, Any] | None, *, timeout: float = 5.0) -> tuple[bool, str | None]:
    """Whether the engine could decide a call right now, and why not if not.

    For /health, so it is cached for 30 s per configuration and runs at most
    once at a time (see bounded_readiness): /health is unauthenticated and
    polled, and each check spawns the binary. It ends with one probe
    decision within ``timeout`` (the hook's timeout_sec, 5 s by default like
    the hook's), so a setup whose every call would time out is not reported
    ready. Problems are fixed phrases: no path, rule text, or Numbat stderr,
    which would publish the server's layout. The same ``numbat`` command run
    by hand gives the detail.
    """
    return bounded_readiness(_readiness_key(cfg, timeout), _READINESS_BUDGET_SEC + timeout,
                             lambda: _readiness(cfg, timeout))


def _readiness_key(cfg: dict[str, Any] | None, timeout: float) -> tuple[Any, ...]:
    # Built from the raw settings, not the resolved binary or directories:
    # resolving touches the filesystem, which belongs inside the bounded
    # check. PATH is part of it because a bare binary name resolves on it.
    block = _gate_cfg(cfg)
    dirs = block.get("rules_dirs")
    return ("numbat", repr(block.get("binary", DEFAULT_BINARY)),
            repr(dirs if isinstance(dirs, list) else dirs), os.environ.get("PATH", ""), timeout)


def bounded_readiness(key: tuple[Any, ...], budget: float,
                      check: Callable[[], tuple[bool, str | None]]) -> tuple[bool, str | None]:
    """Run a /health readiness ``check`` bounded, coalesced and cached.

    Shared by both hook engines. The check runs on a worker thread that is
    abandoned after ``budget`` seconds (see _within), so a stalled mount under
    the binary, a PATH entry or rules_dirs reports "not ready" instead of
    holding the /health worker. One check per ``key`` runs at a time: a
    burst of /health calls while it runs gets the previous result, or "not
    ready" before the first, rather than each starting a check. Results are
    cached for 30 s.
    """
    with _READINESS_LOCK:
        cached = _READINESS_CACHE.get(key)
        if cached and time.monotonic() - cached[0] < _READINESS_TTL_SEC:
            return cached[1]
        if key in _READINESS_RUNNING:
            return cached[1] if cached else (False, "the pre-action hook readiness check is still running")
        _READINESS_RUNNING.add(key)
    try:
        try:
            verdict = _within(budget, check)
        except _Stalled:
            verdict = (False, f"the pre-action hook readiness check did not finish within {budget:g} s, "
                              "so external calls are likely to time out and be denied")
        with _READINESS_LOCK:
            _READINESS_CACHE[key] = (time.monotonic(), verdict)
    finally:
        with _READINESS_LOCK:
            _READINESS_RUNNING.discard(key)
    return verdict


def _readiness(cfg: dict[str, Any] | None, timeout: float) -> tuple[bool, str | None]:
    binary = resolve_binary(cfg)
    dirs = rules_dirs(cfg)
    if not dirs:
        return False, "numbat engine has no rules_dirs, so every external call is denied"
    if any(not d.is_dir() for d in dirs):
        return False, "a numbat rules_dirs entry does not exist, so every external call is denied"
    if binary is None:
        return False, "numbat binary not found, so every external call is denied"
    try:
        version = _run_cli([binary, "version"], timeout=5)
        # A fixed phrase, never what the binary printed: until it prints the
        # pinned line it is an unverified program, and its output could hold
        # a path or a token that unauthenticated /health must not publish.
        if _first_line(version.stdout) != PINNED_VERSION_LINE:
            return False, f"numbat binary is not the pinned {PINNED_VERSION_LINE!r}, so every external call is denied"
        argv = [binary, "rules", "check", "--no-builtin-rules"]
        for directory in dirs:
            argv += ["--rules-dir", str(directory)]
        check = _run_cli(argv, timeout=10)
    except _CliOutputTooLarge:
        return False, "numbat printed more output than the gate reads, so every external call is denied"
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        return False, f"numbat could not run: {type(exc).__name__}"
    if check.returncode != 0:
        return False, "numbat rules check failed on the configured rules_dirs, so every external call is denied"
    try:
        known, enforcing, active = _classify(dirs)
    except _RulesTooLarge:
        return False, "rules_dirs is too large for the gate to read, so every external call is denied"
    except _RulesDeadline:
        return False, (f"rules_dirs could not be read within {_READINESS_READ_SEC:g} s, "
                       "so external calls are likely to time out and be denied")
    except OSError:
        return False, "a rules file or directory could not be read, so every external call is denied"
    if CANARY_RULE_ID in known:
        # _evaluate refuses the reserved id before every call, whatever the
        # rule says; `rules check` accepts it as an ordinary rule.
        return False, f"a rule uses the reserved id {CANARY_RULE_ID}, so every external call is denied"
    if not active:
        return False, "no enabled rule in rules_dirs, so every external call is denied"
    if not enforcing:
        return False, "no enabled enforce: true rule, so the gate cannot deny anything"
    # The checks above each have their own bound, not the hook's timeout_sec.
    # One real decision within timeout_sec shows calls can be decided in it:
    # on a slow disk, or with a short timeout_sec, every call can time out
    # while each check above passes.
    probe = _evaluate(_PROBE_PROVIDER, _PROBE_MODEL, _PROBE_HASH, cfg, timeout=timeout)
    if probe["reason_code"] == "hook_timeout":
        return False, (f"a probe decision did not finish within timeout_sec ({timeout:g} s), "
                       "so external calls are likely to time out and be denied")
    if probe["reason_code"] not in ("hook_allowed", "hook_denied"):
        return False, f"a probe decision failed ({probe['reason_code']}), so every external call is denied"
    return True, None


def clear_readiness_cache() -> None:
    """Drop cached readiness results (tests, and after editing rules)."""
    with _READINESS_LOCK:
        _READINESS_CACHE.clear()


__all__ = [
    "CANARY_RULE_ID",
    "DEFAULT_BINARY",
    "PINNED_VERSION_LINE",
    "bounded_readiness",
    "build_gate_event",
    "classify_rules",
    "clear_readiness_cache",
    "evaluate",
    "readiness",
    "resolve_binary",
    "rules_dirs",
]
