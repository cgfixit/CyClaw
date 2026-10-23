"""Lock freshness must detect input and transitive-output drift offline."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.check_lock_contract import catalog, check, contract, publish


@pytest.fixture
def lock_tree(tmp_path):
    root = Path(__file__).resolve().parents[1]
    inputs = set()
    for group in ("runtime", "ci"):
        inputs.update(contract(root, group, root / "locks")["inputs"])
    for relative in inputs:
        dest = tmp_path / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / relative, dest)
    shutil.copytree(root / "locks", tmp_path / "locks")
    return tmp_path


def test_constraints_change_requires_new_lock_records(lock_tree):
    check(lock_tree)
    with (lock_tree / "constraints.txt").open("a") as stream:
        stream.write("\n# operator input changed\n")
    with pytest.raises(ValueError, match="inputs/outputs changed"):
        check(lock_tree)


def test_transitive_change_cannot_silently_keep_old_record(lock_tree):
    path = lock_tree / "locks/requirements-lock-windows.txt"
    path.write_text(path.read_text().replace("aiohappyeyeballs==2.7.1", "aiohappyeyeballs==2.7.2"))
    with pytest.raises(ValueError):
        check(lock_tree)


def test_incomplete_refresh_leaves_published_set_unchanged(lock_tree, tmp_path):
    before = {p.name: p.read_bytes() for p in (lock_tree / "locks").iterdir() if p.is_file()}
    staged = tmp_path / "stage"
    staged.mkdir()
    first = next(iter(catalog("runtime")))
    shutil.copy2(lock_tree / "locks" / first, staged / first)
    with pytest.raises(FileNotFoundError):
        publish(lock_tree, "runtime", staged)
    assert before == {p.name: p.read_bytes() for p in (lock_tree / "locks").iterdir() if p.is_file()}


def test_all_platform_constraints_are_checked_even_if_records_are_rewritten(lock_tree):
    path = lock_tree / "locks/requirements-lock-macos.txt"
    path.write_text(path.read_text().replace("numpy==1.26.4", "numpy==1.26.3"))
    record = lock_tree / "locks/runtime-inputs.json"
    record.write_text(json.dumps({}))
    with pytest.raises(ValueError, match="numpy"):
        contract(lock_tree, "runtime", lock_tree / "locks")


def test_windows_checkout_line_endings_are_not_dependency_drift(lock_tree):
    paths = set()
    for group in ("runtime", "ci"):
        paths.update(contract(lock_tree, group, lock_tree / "locks")["inputs"])
        paths.update("locks/" + name for name in catalog(group))
    for relative in paths:
        path = lock_tree / relative
        path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    check(lock_tree)


@pytest.fixture
def refresh_env(lock_tree):
    if os.name == "nt":
        pytest.skip("refresh scripts run on a POSIX host")
    tools = lock_tree / "tools"
    tools.mkdir()
    uname = tools / "uname"
    uname.write_text('#!/bin/sh\ncase "$1" in -s) echo Darwin;; -m) echo arm64;; esac\n')
    uname.chmod(0o755)
    uv = tools / "uv"
    uv.write_text('#!/bin/sh\nexec "$PYTHON_BIN" "$FAKE_UV" "$@"\n')
    uv.chmod(0o755)
    fake_uv = tools / "uv.py"
    fake_uv.write_text(
        "import json, os, sys\nfrom pathlib import Path\n"
        "args = sys.argv[1:]\n"
        "output = Path(args[args.index('--output-file') + 1])\n"
        "with open(os.environ['UV_CALLS'], 'a') as log:\n"
        "    log.write(json.dumps({'args': args, 'seeded': output.is_file()}) + '\\n')\n"
    )
    return {
        **os.environ, "PATH": str(tools) + os.pathsep + os.environ["PATH"],
        "UV_BIN": str(uv), "PYTHON_BIN": sys.executable, "FAKE_UV": str(fake_uv),
        "UV_CALLS": str(lock_tree / "uv-calls.jsonl"),
    }


@pytest.mark.parametrize("script", ["refresh-runtime-lock.sh", "refresh-ci-locks.sh"])
@pytest.mark.parametrize("targets", [[], ["certifi", "opentelemetry-api"]])
def test_refresh_forwards_only_targeted_upgrades_to_seeded_non_torch_locks(lock_tree, refresh_env, script, targets):
    args = [value for target in targets for value in ("--upgrade-package", target)]
    result = subprocess.run(
        ["/bin/bash", str(lock_tree / "scripts" / script), *args], env=refresh_env,
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    calls = [json.loads(line) for line in Path(refresh_env["UV_CALLS"]).read_text().splitlines()]
    assert len(calls) == len(catalog("runtime" if "runtime" in script else "ci"))
    for call in calls:
        assert call["seeded"]
        argv = call["args"]
        output = argv[argv.index("--output-file") + 1]
        upgrades = [argv[i + 1] for i, arg in enumerate(argv) if arg == "--upgrade-package"]
        assert upgrades == ([] if "requirements-torch-lock-" in output else targets)
        assert "--upgrade" not in argv


@pytest.mark.parametrize("script", ["refresh-runtime-lock.sh", "refresh-ci-locks.sh"])
@pytest.mark.parametrize("args", [["--upgrade"], ["--upgrade-package"], ["--upgrade-package", "--index-url"]])
def test_refresh_rejects_invalid_targets_before_compiling(lock_tree, refresh_env, script, args):
    before = {p.name: p.read_bytes() for p in (lock_tree / "locks").iterdir() if p.is_file()}
    result = subprocess.run(
        ["/bin/bash", str(lock_tree / "scripts" / script), *args], env=refresh_env,
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 2
    assert "usage:" in result.stderr
    assert not Path(refresh_env["UV_CALLS"]).exists()
    assert before == {p.name: p.read_bytes() for p in (lock_tree / "locks").iterdir() if p.is_file()}
