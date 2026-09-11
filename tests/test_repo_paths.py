"""Tests for utils.repo_paths — the stdlib-only read-path mirror of the write jail.

``utils.ops_runner`` gates ``real-repo-run --read-file`` through
``canonical_repo_relative_path`` and must not import ``agentic`` (I6), so this
acceptance rule is duplicated rather than shared. The module carried no test at
all after the drift test it named was removed with the coding-harness console
(#1367); these pin both halves of its contract — the base rule it shares with
``repo_workspace.canonical_repo_path``, and the deliberately stricter
trailing-dot/space rule the write jail does not need.
"""

from __future__ import annotations

import pytest

from utils.repo_paths import canonical_repo_relative_path


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("README.md", "README.md"),
        ("docs/guide.md", "docs/guide.md"),
        ("./README.md", "README.md"),
        ("docs/./guide.md", "docs/guide.md"),
        ("docs//guide.md", "docs/guide.md"),
        # Backslashes are normalized so a Windows-spelled path canonicalizes
        # to the same string the POSIX spelling produces.
        ("docs\\guide.md", "docs/guide.md"),
    ],
)
def test_accepts_and_canonicalizes_repo_relative_paths(raw: str, expected: str) -> None:
    assert canonical_repo_relative_path(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "a\x00b",
        "/etc/passwd",
        "C:\\Windows\\System32\\config",
        "-rf",
        "../etc/passwd",
        "docs/../../etc/passwd",
        "..",
        "stream:alt",
        # Nothing but droppable segments leaves no path at all.
        ".",
        "./",
    ],
)
def test_rejects_escapes_and_flag_injection(raw: str) -> None:
    assert canonical_repo_relative_path(raw) is None


@pytest.mark.parametrize("raw", [123, None, b"README.md", ["README.md"]])
def test_rejects_non_str_input(raw: object) -> None:
    # `object`, not `str`: the point of this test is the runtime isinstance
    # guard, which exists for callers that violate the annotation. The ignore
    # marks that violation as the subject under test rather than an oversight.
    assert canonical_repo_relative_path(raw) is None  # type: ignore[arg-type]


@pytest.mark.parametrize("raw", ["README.md.", "README.md ", "docs./guide.md", "docs /guide.md"])
def test_rejects_trailing_dot_or_space_segments(raw: str) -> None:
    """The stricter-than-the-write-jail rule, and the reason it exists.

    Windows silently strips a trailing dot or space from a path component, so
    ``README.md.`` and ``README.md`` open the same file. Rejecting outright
    keeps a declared read file from validating here, being staged and
    confirmed, and then failing silently in the reader.
    """
    assert canonical_repo_relative_path(raw) is None


def test_rejection_never_launders_an_absolute_path_into_a_relative_one() -> None:
    """Returning None rather than a cleaned string is the whole point.

    Stripping the leading slash would turn ``/etc/passwd`` into the perfectly
    valid repo-relative ``etc/passwd`` and hand the caller a path it would
    happily read.
    """
    assert canonical_repo_relative_path("/etc/passwd") != "etc/passwd"
    assert canonical_repo_relative_path("/etc/passwd") is None
