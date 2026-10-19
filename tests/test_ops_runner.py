"""Tests for utils.ops_runner — the subprocess shim behind /ops/sync and /ops/fsconnect.

Most cases replace ``_run`` to capture argv and return a synthetic result.
The isolation test uses a real child interpreter; it contacts no external service.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from utils import ops_runner
from utils.ops_runner import OpsError, run_fsconnect_op, run_sync_op


def _fake_run(returncode: int = 0, stdout: str = "", stderr: str = ""):
    """Return a (_run replacement, captured-argv list) pair."""
    captured: list[list[str]] = []

    def _runner(argv: list[str], *, timeout_sec: int | None = None) -> subprocess.CompletedProcess[str]:
        # timeout_sec is accepted so run_sync_op's config-aligned budget
        # does not TypeError the stub (production _run takes the same kwarg).
        del timeout_sec
        captured.append(argv)
        return subprocess.CompletedProcess(args=argv, returncode=returncode, stdout=stdout, stderr=stderr)

    return _runner, captured


# --------------------------------------------------------------------------- sync


def test_sync_unknown_action_raises() -> None:
    with pytest.raises(OpsError):
        run_sync_op("rm-rf")


def test_sync_status_argv(monkeypatch: pytest.MonkeyPatch) -> None:
    runner, captured = _fake_run(returncode=0, stdout="ok")
    monkeypatch.setattr(ops_runner, "_run", runner)
    res = run_sync_op("status")
    argv = captured[0]
    assert argv[0] == sys.executable
    assert argv[1:3] == ["-m", "sync.cli"]
    assert "--config" in argv and argv[-1] == "status"
    assert res.ok is True and res.label == "ok" and res.exit_code == 0


def test_sync_dry_run_appends_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    runner, captured = _fake_run()
    monkeypatch.setattr(ops_runner, "_run", runner)
    run_sync_op("sync", dry_run=True)
    assert captured[0][-1] == "--dry-run"
    assert captured[0][-2] == "sync"


def test_sync_action_uses_config_aligned_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """POST /ops/sync must not hard-kill at 120s when sync.sync_timeout_sec is 3600."""
    captured: list[tuple[list[str], int | None]] = []

    def _runner(argv: list[str], *, timeout_sec: int | None = None) -> subprocess.CompletedProcess[str]:
        captured.append((argv, timeout_sec))
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(ops_runner, "_run", _runner)
    monkeypatch.setattr(ops_runner, "sync_timeout_sec", lambda: 3660)
    run_sync_op("sync")
    assert captured[0][1] == 3660
    # Non-transfer actions keep the short default path (timeout_sec=_TIMEOUT_SEC).
    run_sync_op("status")
    assert captured[1][1] == ops_runner._TIMEOUT_SEC


def test_sync_dry_run_ignored_for_non_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    runner, captured = _fake_run()
    monkeypatch.setattr(ops_runner, "_run", runner)
    run_sync_op("status", dry_run=True)  # dry_run must NOT leak onto status
    assert "--dry-run" not in captured[0]


@pytest.mark.parametrize(
    "code,ok,label",
    [(0, True, "ok"), (10, True, "ok_reindex_needed"), (1, False, "safety_abort"),
     (2, False, "failed"), (3, False, "env_config"), (99, False, "unknown")],
)
def test_sync_exit_code_labels(monkeypatch: pytest.MonkeyPatch, code: int, ok: bool, label: str) -> None:
    runner, _ = _fake_run(returncode=code, stderr="boom" if code else "")
    monkeypatch.setattr(ops_runner, "_run", runner)
    res = run_sync_op("sync")
    assert res.ok is ok and res.label == label and res.exit_code == code


def test_to_dict_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    runner, _ = _fake_run(returncode=0, stdout="ok")
    monkeypatch.setattr(ops_runner, "_run", runner)
    d = run_sync_op("status").to_dict()
    assert set(d) == {"subsystem", "action", "exit_code", "ok", "label", "stdout", "stderr", "parsed"}


def test_to_dict_redacts_subprocess_output(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = {
        "policy": {
            "privacy": {
                "redact_emails": False,
                "redact_ips": False,
                "redact_secrets_like": [r"sk-[A-Za-z0-9]{8,}", r"Bearer\s+[A-Za-z0-9\-_.]+"],
            }
        }
    }
    monkeypatch.setattr(ops_runner, "_get_config", lambda *_args, **_kwargs: cfg)
    res = ops_runner.OpsResult(
        "sync", "status", 0, True, "ok",
        "stdout sk-testsecret123",
        "stderr Bearer abc.def-ghi",
        {"nested": ["sk-nestedsecret123"]},
    )

    d = res.to_dict()

    assert "sk-testsecret123" not in d["stdout"]
    assert "abc.def-ghi" not in d["stderr"]
    assert "sk-nestedsecret123" not in d["parsed"]["nested"][0]
    assert "[REDACTED_SECRET]" in d["stdout"]
    assert "[REDACTED_SECRET]" in d["stderr"]
    assert "[REDACTED_SECRET]" in d["parsed"]["nested"][0]


# --------------------------------------------------------------------- fsconnect


def test_fsconnect_unknown_action_raises() -> None:
    with pytest.raises(OpsError):
        run_fsconnect_op("rm-rf")


def test_fsconnect_status_argv(monkeypatch: pytest.MonkeyPatch) -> None:
    runner, captured = _fake_run(returncode=0, stdout="ok")
    monkeypatch.setattr(ops_runner, "_run", runner)
    res = run_fsconnect_op("status")
    argv = captured[0]
    assert argv[0] == sys.executable
    assert argv[1:3] == ["-m", "agentic.fsconnect.cli"]
    assert "--config" in argv and argv[-1] == "status"
    assert res.ok is True and res.label == "ok"


def test_fsconnect_list_argv(monkeypatch: pytest.MonkeyPatch) -> None:
    runner, captured = _fake_run(returncode=0, stdout='[{"name": "file.txt"}]')
    monkeypatch.setattr(ops_runner, "_run", runner)
    res = run_fsconnect_op("list", root="/data", path="subdir")
    argv = captured[0]
    # --opt=value single-token form (so a leading-dash value binds to its option).
    assert "--root=/data" in argv
    assert "--path=subdir" in argv
    assert res.parsed == [{"name": "file.txt"}]


def test_fsconnect_grep_argv(monkeypatch: pytest.MonkeyPatch) -> None:
    runner, captured = _fake_run(returncode=0, stdout='{"matches": []}')
    monkeypatch.setattr(ops_runner, "_run", runner)
    run_fsconnect_op("grep", root="/data", path="file.txt", pattern="hello")
    argv = captured[0]
    assert "--pattern=hello" in argv
    assert "--regex" not in argv


def test_fsconnect_leading_dash_pattern_bound_to_option(monkeypatch: pytest.MonkeyPatch) -> None:
    # An operator grepping their notes for a literal dash-leading string
    # ("--dry-run", "-v" — the kind of flag text an ops corpus contains) must
    # travel as one --pattern=value token, else the child argparse rejects the
    # value as a stray flag and the op fails instead of returning matches.
    runner, captured = _fake_run(returncode=0, stdout='{"matches": []}')
    monkeypatch.setattr(ops_runner, "_run", runner)
    run_fsconnect_op("grep", path="notes.md", pattern="--dry-run")
    argv = captured[0]
    assert "--pattern=--dry-run" in argv
    assert "--pattern" not in argv    # no two-token form remains
    assert "--dry-run" not in argv    # the bare value is never a standalone token


def test_fsconnect_regex_rejected() -> None:
    with pytest.raises(OpsError, match="regex grep is CLI-only"):
        run_fsconnect_op("grep", path="file.txt", pattern="(a+)+$", regex=True)

def test_ops_fsconnect_request_rejects_regex_true() -> None:
    from pydantic import ValidationError
    from schemas.api import OpsFsConnectRequest

    with pytest.raises(ValidationError):
        OpsFsConnectRequest(action="grep", path="file.txt", pattern="(a+)+$", regex=True)


def test_fsconnect_glob_no_recursive(monkeypatch: pytest.MonkeyPatch) -> None:
    runner, captured = _fake_run(returncode=0, stdout="[]")
    monkeypatch.setattr(ops_runner, "_run", runner)
    run_fsconnect_op("glob", root="/data", pattern="*.md", recursive=False)
    assert "--no-recursive" in captured[0]


@pytest.mark.parametrize(
    "code,ok,label",
    [(0, True, "ok"), (2, False, "failed"), (3, False, "env_config"),
     (4, False, "write_refused"), (99, False, "unknown")],
)
def test_fsconnect_exit_code_labels(monkeypatch: pytest.MonkeyPatch, code: int, ok: bool, label: str) -> None:
    runner, _ = _fake_run(returncode=code)
    monkeypatch.setattr(ops_runner, "_run", runner)
    res = run_fsconnect_op("status")
    assert res.ok is ok and res.label == label


# ----------------------------------------------------------------------- isolation


def test_importing_shim_does_not_import_out_of_band_packages() -> None:
    """Hard invariant: importing the shim must not import sync/ or agentic/.

    Run in a clean interpreter so prior test imports cannot mask a regression.
    """
    code = (
        "import sys; import utils.ops_runner; "
        "assert 'sync' not in sys.modules, 'ops_runner imported sync'; "
        "assert 'agentic' not in sys.modules, 'ops_runner imported agentic'; "
        "print('ISOLATED_OK')"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(ops_runner._REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "ISOLATED_OK" in proc.stdout


# --------------------------------------------------------------------------- sync budget

def test_sync_timeout_sec_single_budget_without_post_sync_check(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        ops_runner, "_get_config",
        lambda _path: {"sync": {"sync_timeout_sec": 3600}},
    )
    assert ops_runner.sync_timeout_sec() == 3600 + 60


def test_sync_timeout_sec_doubles_when_post_sync_check_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    # The runner can hold the lock for one full sync_timeout_sec of rclone sync
    # PLUS a second full timeout for rclone check; the shim must not kill a
    # healthy run mid-check (mirrors sync.runner._lock_stale_after_sec).
    monkeypatch.setattr(
        ops_runner, "_get_config",
        lambda _path: {"sync": {"sync_timeout_sec": 3600, "post_sync_check": True}},
    )
    assert ops_runner.sync_timeout_sec() == 2 * 3600 + 60


def test_sync_timeout_sec_fallback_on_unreadable_config(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(_path):
        raise OSError("config missing")

    monkeypatch.setattr(ops_runner, "_get_config", _boom)
    assert ops_runner.sync_timeout_sec() == 3600 + 60


def test_sync_timeout_sec_never_raises_on_a_malformed_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """gate.py's /health calls this unguarded, so a config.yaml that parses to a
    non-mapping must degrade to the shipped budget rather than 500 the probe."""
    monkeypatch.setattr(ops_runner, "_get_config", lambda _path: "not-a-mapping")
    assert ops_runner.sync_timeout_sec() == 3660
