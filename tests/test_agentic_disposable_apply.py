"""Disposable-copy acceptance proof before real-repo finalize."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from agentic.executor.apply import prove_disposable_copy
from agentic.executor.manifest import build_manifest, git_head
from utils.errors import AgenticError

# Matches RUN_ID_RE (32 hex). Repeated zeros, not a high-entropy token (DS173237).
_RUN = "0" * 32


def _git_init(root: Path) -> None:
    git_bin = shutil.which("git")
    assert git_bin is not None
    subprocess.run([git_bin, "init"], cwd=str(root), check=True, capture_output=True)
    subprocess.run([git_bin, "config", "user.name", "t"], cwd=str(root), check=True, capture_output=True)
    subprocess.run([git_bin, "config", "user.email", "t@t"], cwd=str(root), check=True, capture_output=True)
    # No background maintenance after the commit below: git >= 2.47 detaches
    # it, and it holds .git/objects/maintenance.lock while this test copies
    # the repo.
    subprocess.run([git_bin, "config", "maintenance.auto", "false"], cwd=str(root), check=True, capture_output=True)
    (root / "keep.txt").write_text("k\n", encoding="utf-8")
    subprocess.run([git_bin, "add", "keep.txt"], cwd=str(root), check=True, capture_output=True)
    subprocess.run([git_bin, "commit", "-m", "i"], cwd=str(root), check=True, capture_output=True)


def test_matching_copy_allows(tmp_path: Path) -> None:
    _git_init(tmp_path)
    (tmp_path / "a.txt").write_text("hello\n", encoding="utf-8")
    head = git_head(tmp_path)
    _, digest = build_manifest(tmp_path, ["a.txt"], run_id=_RUN, base_head=head)
    assert (
        prove_disposable_copy(
            tmp_path,
            ["a.txt"],
            run_id=_RUN,
            base_head=head,
            expected_digest=digest,
        )
        == digest
    )


def test_mutated_copy_denies(tmp_path: Path) -> None:
    _git_init(tmp_path)
    (tmp_path / "a.txt").write_text("hello\n", encoding="utf-8")
    head = git_head(tmp_path)
    _, digest = build_manifest(tmp_path, ["a.txt"], run_id=_RUN, base_head=head)
    (tmp_path / "a.txt").write_text("mutated\n", encoding="utf-8")
    with pytest.raises(AgenticError, match="digest mismatch"):
        prove_disposable_copy(
            tmp_path,
            ["a.txt"],
            run_id=_RUN,
            base_head=head,
            expected_digest=digest,
        )


def test_missing_worktree_denies(tmp_path: Path) -> None:
    missing = tmp_path / "no-such-tree"
    with pytest.raises(AgenticError, match="not a directory"):
        prove_disposable_copy(
            missing,
            ["a.txt"],
            run_id=_RUN,
            base_head="abc",
            expected_digest="0" * 64,
        )


def _copy_through(monkeypatch: pytest.MonkeyPatch, copy) -> None:
    """Route every file copytree makes through ``copy``.

    copytree recurses by calling the module-level ``shutil.copytree`` with
    positional arguments, so the wrapper takes its full signature.
    """
    real_copytree = shutil.copytree

    def _copytree(src, dst, symlinks=False, ignore=None, copy_function=shutil.copy2,
                  ignore_dangling_symlinks=False, dirs_exist_ok=False):
        return real_copytree(src, dst, symlinks, ignore, copy, ignore_dangling_symlinks, dirs_exist_ok)

    monkeypatch.setattr(shutil, "copytree", _copytree)


def test_a_git_lock_that_vanishes_mid_copy_does_not_fail_the_proof(tmp_path: Path, monkeypatch) -> None:
    # Background git maintenance deletes objects/maintenance.lock while the
    # copy runs. Here every lock copytree lists fails to copy as if it had
    # just vanished; the proof must not depend on it.
    _git_init(tmp_path)
    (tmp_path / "a.txt").write_text("hello\n", encoding="utf-8")
    head = git_head(tmp_path)
    _, digest = build_manifest(tmp_path, ["a.txt"], run_id=_RUN, base_head=head)
    (tmp_path / ".git" / "objects" / "maintenance.lock").write_text("", encoding="utf-8")
    (tmp_path / ".git" / "index.lock").write_text("", encoding="utf-8")

    def _copy(src, dst, *args, **kwargs):
        if str(src).endswith(".lock"):
            raise FileNotFoundError(2, "No such file or directory", str(src))
        return shutil.copy2(src, dst, *args, **kwargs)

    _copy_through(monkeypatch, _copy)
    assert prove_disposable_copy(tmp_path, ["a.txt"], run_id=_RUN, base_head=head, expected_digest=digest) == digest


def test_worktree_lock_files_are_still_copied(tmp_path: Path, monkeypatch) -> None:
    # Only locks inside .git are skipped: a Cargo.lock is candidate content,
    # and dropping it would change the digest.
    _git_init(tmp_path)
    (tmp_path / "Cargo.lock").write_text("[[package]]\n", encoding="utf-8")
    head = git_head(tmp_path)
    _, digest = build_manifest(tmp_path, ["Cargo.lock"], run_id=_RUN, base_head=head)
    copied: list[str] = []

    def _copy(src, dst, *args, **kwargs):
        copied.append(Path(src).name)
        return shutil.copy2(src, dst, *args, **kwargs)

    _copy_through(monkeypatch, _copy)
    assert prove_disposable_copy(tmp_path, ["Cargo.lock"], run_id=_RUN, base_head=head, expected_digest=digest) == digest
    assert "Cargo.lock" in copied
