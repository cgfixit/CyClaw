"""Exercise the shared hook scanner without importing the application."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[1] / ".githooks" / "_security.sh"
BASH = shutil.which("bash") or ""
pytestmark = pytest.mark.skipif(sys.platform == "win32" or not BASH, reason="needs POSIX bash")

MEDIA = "png jpg jpeg gif webp heic bmp ico tif tiff mp4 mov m4a mp3 wav avi mkv webm pdf woff woff2 ttf otf".split()
NON_MEDIA = "docx xlsx pptx zip tar tgz gz bz2 xz 7z rar jar whl so dll dylib exe txt".split()
MARKS = ["\u202e".encode(), "\U000e0061".encode()]


@pytest.fixture(params=sorted({BASH, "/bin/bash"} - {""}))
def shell(request: pytest.FixtureRequest, tmp_path: Path) -> str:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, capture_output=True)  # noqa: S603, S607
    return str(request.param)


def _run(shell: str, tmp_path: Path, script: str, data: bytes, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(  # noqa: S603 - fixed scripts and separate positional arguments
        [shell, "-euo", "pipefail", "-c", '. "$1"; sec__quiet=1; ' + script, "hook-probe", str(HOOK), *args],
        input=data,
        capture_output=True,
        cwd=tmp_path,
        env={**os.environ, "HOME": str(tmp_path), "XDG_CONFIG_HOME": str(tmp_path), "LC_ALL": "C"},
        timeout=30,
        check=False,
    )


@pytest.mark.parametrize("path,reminder", [
    (".agents/skills/x/agents/openai.yaml", True),
    (".agents/skills/x/references/guide.md", True),
    (".agent/skills/x/agents/openai.yaml", True),
    ("docs/guide.md", False),
])
def test_staged_agent_metadata_gets_instruction_reminder(
    shell: str, tmp_path: Path, path: str, reminder: bool,
) -> None:
    result = _run(
        shell, tmp_path,
        'sec__quiet=0; mkdir -p "$(dirname "$2")"; cat > "$2"; git add "$2"; sec_pre_commit',
        b"Synthetic fixture\n", path,
    )
    assert result.returncode == 0, result.stderr
    assert (b"agent instruction surface changed" in result.stderr) is reminder


@pytest.mark.parametrize("mark", MARKS, ids=["bidi", "tag"])
@pytest.mark.parametrize("extension", MEDIA + NON_MEDIA)
def test_invalid_utf8_skip_is_media_only(shell: str, tmp_path: Path, extension: str, mark: bytes) -> None:
    if extension in MEDIA and not shutil.which("iconv"):
        pytest.skip("media exception requires iconv")
    result = _run(
        shell,
        tmp_path,
        'hits="$(cat)"; sec__drop_binary_paths "$hits"',
        f"nested/file name.{extension.upper()}:7:".encode() + b"\xff" + mark + b"\n",
    )
    assert result.returncode == 0
    assert result.stdout.count(b"\n") == (0 if extension in MEDIA else 1)


@pytest.mark.parametrize("mark", MARKS, ids=["bidi", "tag"])
@pytest.mark.parametrize("missing_iconv", [False, True])
def test_valid_utf8_media_and_missing_iconv_keep_hits(
    shell: str,
    tmp_path: Path,
    mark: bytes,
    missing_iconv: bool,
) -> None:
    script = 'hits="$(cat)"; '
    if missing_iconv:
        script += 'PATH=""; '
    result = _run(
        shell,
        tmp_path,
        script + 'sec__drop_binary_paths "$hits"',
        b"document.pdf:1:" + (b"\xff" if missing_iconv else b"") + mark + b"\n",
    )
    assert result.returncode == 0
    assert result.stdout.count(b"\n") == 1


@pytest.mark.parametrize("producer", ["diff", "blob"])
@pytest.mark.parametrize(
    "name,blocked",
    [
        ("fake.png:evil.whl", True),
        ("fake.PNG:1:evil.exe", True),
        ("nested/prefix:real.PNG", False),
    ],
)
def test_filename_colons_cannot_spoof_media(
    shell: str,
    tmp_path: Path,
    producer: str,
    name: str,
    blocked: bool,
) -> None:
    if not blocked and not shutil.which("iconv"):
        pytest.skip("media exception requires iconv")
    data = b"\xff" + MARKS[0] + b"\n"
    if producer == "diff":
        data = f"diff --git a/{name} b/{name}\n--- a/{name}\n+++ b/{name}\n@@ -0,0 +1 @@\n+".encode() + data
        script = "sec__scan_diff probe"
    else:
        script = 'hits="$(sec__label_lines "$2")"; sec__scan_added probe "$hits"'
    result = _run(shell, tmp_path, script, data, name)
    assert result.returncode == int(blocked)
    assert result.stdout == b""
    if blocked:
        assert f"{name.replace(':', '%3A')}:1".encode() in result.stderr
        assert MARKS[0] not in result.stderr


@pytest.mark.parametrize("object_type", ["tag", "blob"])
@pytest.mark.parametrize("hidden", [False, True])
def test_ref_names_are_not_media_filenames(shell: str, tmp_path: Path, object_type: str, hidden: bool) -> None:
    script = 'obj="$(git hash-object -w --stdin)"; '
    if object_type == "tag":
        script = (
            'tree="$(git mktree </dev/null)"; obj="$( { '
            'printf "object %s\ntype tree\ntag banner.png\ntagger Test <test@example.com> 1 +0000\n\n" "$tree"; cat; '
            '} | git hash-object -t tag -w --stdin)"; '
        )
    script += 'sec_pre_push_ref origin refs/tags/banner.png "$obj" refs/tags/banner.png ' + "0" * 40
    result = _run(shell, tmp_path, script, b"\xff" + (MARKS[0] if hidden else b"ordinary message") + b"\n")
    assert result.returncode == int(hidden)
    assert result.stdout == b""
    assert MARKS[0] not in result.stderr


def test_media_secret_patterns_still_block(shell: str, tmp_path: Path) -> None:
    data = b"\xff" + ("xai-" + "A" * 40).encode() + b"\n"
    result = _run(shell, tmp_path, 'hits="$(sec__label_lines image.png)"; sec__scan_added probe "$hits"', data)
    assert result.returncode == 1
    assert b"credential-shaped string" in result.stderr
    assert b"image.png:1" in result.stderr
    assert b"A" * 40 not in result.stderr


@pytest.mark.parametrize("mark", MARKS, ids=["bidi", "tag"])
@pytest.mark.parametrize("entrypoint", ["commit", "push"])
@pytest.mark.parametrize("extension", ["exe", "whl"])
def test_media_rename_rescans_destination(
    shell: str,
    tmp_path: Path,
    mark: bytes,
    entrypoint: str,
    extension: str,
) -> None:
    script = (
        "cat > payload.png; git add payload.png; "
        "git -c user.name=Fixture -c user.email=fixture@example.com commit -qm initial; "
        'base="$(git rev-parse HEAD)"; git config diff.renames true; git mv payload.png "$2"; '
    )
    if entrypoint == "commit":
        script += "sec_pre_commit"
    else:
        script += (
            "git -c user.name=Fixture -c user.email=fixture@example.com commit -qm renamed; "
            'sec_pre_push_ref origin refs/heads/codex/probe "$(git rev-parse HEAD)" refs/heads/codex/probe "$base"'
        )
    name = f"payload.{extension}"
    result = _run(shell, tmp_path, script, b"\xff" + mark + b"\n", name)
    assert result.returncode == 1
    assert result.stdout == b""
    assert b"invisible bidi-override" in result.stderr
    assert f"{name}:1".encode() in result.stderr
    assert mark not in result.stderr
