"""Lock freshness must detect input and transitive-output drift offline."""

import json
import shutil
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
