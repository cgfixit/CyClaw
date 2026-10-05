"""Linux launcher: the API key and the pairing code must not leak.

Contract (e2e-fixes card, PR B; interface posted by PyForge):

* ``macos/cyclaw-linux-key.sh`` is sourced, never executed. It stores a
  generated key in libsecret (``secret-tool``, secret on stdin only) or, when
  that is unavailable, in ``${XDG_CONFIG_HOME:-~/.config}/cyclaw/api-key``
  written under umask 077: folder 0700, file 0600.
* ``cyclaw_linux_load_api_key`` returns 2 and exports nothing when the key file
  is a symlink, is readable or writable by group/other, or sits in a folder
  that group/other can write (a same-group user could swap it).
* The key value is never printed, never passed as a command-line argument.
* ``invoke-cyclaw.sh`` prints the one-time pairing URL only to a TTY, or to
  stdout when ``--print-pairing-url`` is passed; never to stderr, and never to
  non-TTY output by default (journald, nohup.out, CI logs).

``CYCLAW_SECRET_TOOL=<path>|none`` is the helper's test hook. Nothing here
touches the real keyring or the real ``~/.config``.
"""

from __future__ import annotations

import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_HELPER = _REPO / "macos" / "cyclaw-linux-key.sh"
_LAUNCHER = _REPO / "macos" / "invoke-cyclaw.sh"
_BASH = shutil.which("bash") or "bash"
# The helper's test hook that turns libsecret off (a switch, not a secret).
_NO_KEYRING = {"CYCLAW_SECRET_TOOL": "none"}
_SERVICE = "com.cgfixit.cyclaw.api-key"
_PAIR_SENTINEL = "PAIRSENTINEL-shield-7f3a9c"

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="Linux-only launcher branch and POSIX modes"
)


def _env(tmp_path: Path, **extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("CYCLAW_")}
    for name in ("DISPLAY", "WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS"):
        env.pop(name, None)
    env["HOME"] = str(tmp_path / "home")
    env["XDG_CONFIG_HOME"] = str(tmp_path / "xdg")
    (tmp_path / "home").mkdir(exist_ok=True)
    env.update(extra)
    return env


def _key_file(tmp_path: Path) -> Path:
    return tmp_path / "xdg" / "cyclaw" / "api-key"


def _source(program: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    script = f'. "{_HELPER}" || exit 97\n{program}'
    return subprocess.run([_BASH, "-c", script], env=env, capture_output=True, text=True, timeout=20, check=False)


def _fake_secret_tool(tmp_path: Path, *, store_rc: int = 0, readable: bool = True) -> tuple[Path, Path, Path]:
    """A secret-tool stand-in that logs argv and stdin to separate files.

    ``lookup`` returns what ``store`` received (exit 1 when nothing is stored),
    unless ``readable`` is False: a keyring that accepts writes it can't read back.
    """
    argv_log = tmp_path / "secret-tool.argv"
    stdin_log = tmp_path / "secret-tool.stdin"
    vault = tmp_path / "secret-tool.vault"
    tool = tmp_path / "bin" / "secret-tool"
    tool.parent.mkdir(exist_ok=True)
    lookup = f'[ -s "{vault}" ] && cat "{vault}" && exit 0; exit 1' if readable else "exit 1"
    tool.write_text(
        "#!/bin/sh\n"
        f'printf "%s\\n" "$*" >> "{argv_log}"\n'
        'case "$1" in\n'
        f'  store) tee -a "{stdin_log}" > "{vault}"; exit {store_rc} ;;\n'
        f"  lookup) {lookup} ;;\n"
        "esac\n"
        "exit 1\n",
        encoding="utf-8",
    )
    tool.chmod(0o755)
    return tool, argv_log, stdin_log


# --- helper: storage -------------------------------------------------------


def test_helper_refuses_direct_execution(tmp_path: Path) -> None:
    result = subprocess.run(
        [_BASH, str(_HELPER)],
        env=_env(tmp_path, **_NO_KEYRING),
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode != 0
    assert not _key_file(tmp_path).exists()


def test_file_fallback_is_0600_in_0700_folder_and_never_printed(tmp_path: Path) -> None:
    env = _env(tmp_path, **_NO_KEYRING)
    result = _source(
        'cyclaw_linux_ensure_api_key > "$OUT" 2>&1; rc=$?\n'
        'kf="$(cyclaw_linux_key_file)"\n'
        '[ "$CYCLAW_API_KEY" = "$(cat "$kf")" ] && echo EXPORTED_MATCHES_FILE\n'
        "exit $rc",
        {**env, "OUT": str(tmp_path / "ensure.out")},
    )
    assert result.returncode == 0, result.stderr
    assert "EXPORTED_MATCHES_FILE" in result.stdout

    key_file = _key_file(tmp_path)
    key = key_file.read_text(encoding="utf-8").strip()
    assert re.fullmatch(r"[0-9a-f]{40}", key), "key must be 40 hex chars from a CSPRNG"
    assert stat.S_IMODE(key_file.stat().st_mode) == 0o600
    assert stat.S_IMODE(key_file.parent.stat().st_mode) == 0o700
    assert not key_file.is_symlink()
    leftovers = [p.name for p in key_file.parent.iterdir() if p.name != "api-key"]
    assert leftovers == [], f"temp files left behind: {leftovers}"

    printed = (tmp_path / "ensure.out").read_text(encoding="utf-8") + result.stderr
    assert key not in printed


def test_two_generated_keys_differ(tmp_path: Path) -> None:
    keys = []
    for run in ("a", "b"):
        root = tmp_path / run
        root.mkdir()
        result = _source("cyclaw_linux_ensure_api_key >/dev/null 2>&1", _env(root, **_NO_KEYRING))
        assert result.returncode == 0, result.stderr
        keys.append(_key_file(root).read_text(encoding="utf-8").strip())
    assert keys[0] != keys[1]


def test_libsecret_gets_key_on_stdin_only(tmp_path: Path) -> None:
    tool, argv_log, stdin_log = _fake_secret_tool(tmp_path)
    env = _env(tmp_path, CYCLAW_SECRET_TOOL=str(tool))
    result = _source(
        'cyclaw_linux_ensure_api_key > "$OUT" 2>&1 || exit $?\nprintf "%s" "$CYCLAW_API_KEY" > "$KEYDUMP"',
        {**env, "OUT": str(tmp_path / "ensure.out"), "KEYDUMP": str(tmp_path / "keydump")},
    )
    assert result.returncode == 0, result.stderr
    key = (tmp_path / "keydump").read_text(encoding="utf-8")
    assert re.fullmatch(r"[0-9a-f]{40}", key)

    argv = argv_log.read_text(encoding="utf-8")
    assert "store" in argv and _SERVICE in argv
    assert key not in argv, "the key must never be a command-line argument"
    assert stdin_log.read_text(encoding="utf-8").strip() == key
    assert not _key_file(tmp_path).exists(), "no plaintext file when libsecret worked"
    assert key not in (tmp_path / "ensure.out").read_text(encoding="utf-8") + result.stderr


def test_unreadable_keyring_falls_back_to_0600_file(tmp_path: Path) -> None:
    """A headless keyring that accepts a write but can't read it back is not storage."""
    tool, _argv, _stdin = _fake_secret_tool(tmp_path, readable=False)
    result = _source(
        "cyclaw_linux_ensure_api_key >/dev/null 2>&1",
        _env(tmp_path, CYCLAW_SECRET_TOOL=str(tool)),
    )
    assert result.returncode == 0, result.stderr
    assert stat.S_IMODE(_key_file(tmp_path).stat().st_mode) == 0o600


def test_libsecret_failure_falls_back_to_0600_file(tmp_path: Path) -> None:
    tool, _argv, _stdin = _fake_secret_tool(tmp_path, store_rc=1)
    result = _source(
        "cyclaw_linux_ensure_api_key >/dev/null 2>&1",
        _env(tmp_path, CYCLAW_SECRET_TOOL=str(tool)),
    )
    assert result.returncode == 0, result.stderr
    key_file = _key_file(tmp_path)
    assert stat.S_IMODE(key_file.stat().st_mode) == 0o600
    assert stat.S_IMODE(key_file.parent.stat().st_mode) == 0o700


# --- helper: refusing an unsafe key file -----------------------------------

# A fresh valid-shaped key per run: the leak checks need a distinctive value,
# and nothing secret-looking is committed for scanners to flag.
_PLANTED = secrets.token_hex(20)


def _plant(tmp_path: Path, *, file_mode: int = 0o600, dir_mode: int = 0o700) -> Path:
    key_file = _key_file(tmp_path)
    key_file.parent.mkdir(parents=True)
    key_file.write_text(_PLANTED + "\n", encoding="utf-8")
    key_file.chmod(file_mode)
    key_file.parent.chmod(dir_mode)
    return key_file


def _load(tmp_path: Path) -> subprocess.CompletedProcess[str]:
    return _source(
        'cyclaw_linux_load_api_key; rc=$?\n[ -n "${CYCLAW_API_KEY:-}" ] && echo KEY_EXPORTED\nexit $rc',
        _env(tmp_path, **_NO_KEYRING),
    )


def test_load_accepts_0600_and_0400(tmp_path: Path) -> None:
    for mode in (0o600, 0o400):
        root = tmp_path / oct(mode)
        root.mkdir()
        _plant(root, file_mode=mode)
        result = _load(root)
        assert result.returncode == 0, (oct(mode), result.stderr)
        assert "KEY_EXPORTED" in result.stdout


@pytest.mark.parametrize("mode", [0o640, 0o644, 0o604, 0o660, 0o666])
def test_load_refuses_group_or_world_access(tmp_path: Path, mode: int) -> None:
    _plant(tmp_path, file_mode=mode)
    result = _load(tmp_path)
    assert result.returncode == 2
    assert "KEY_EXPORTED" not in result.stdout
    assert _PLANTED not in result.stdout + result.stderr


@pytest.mark.parametrize("dir_mode", [0o770, 0o777, 0o730])
def test_load_refuses_key_in_shared_writable_folder(tmp_path: Path, dir_mode: int) -> None:
    _plant(tmp_path, dir_mode=dir_mode)
    try:
        result = _load(tmp_path)
    finally:
        _key_file(tmp_path).parent.chmod(0o700)
    assert result.returncode == 2
    assert "KEY_EXPORTED" not in result.stdout


def _foreign_owner_stat(tmp_path: Path, target: str) -> dict[str, str]:
    """PATH with a ``stat`` that reports uid 4242 as the owner of ``target``.

    Without root, a test can't chown a file to another user. The helper reads
    ownership through ``stat -c %u``, so this stub fakes a foreign owner for
    exactly one path suffix and passes every other call to the real stat.
    """
    real = shutil.which("stat")
    assert real, "stat is required"
    stub = tmp_path / "stub-bin" / "stat"
    stub.parent.mkdir(exist_ok=True)
    stub.write_text(
        "#!/bin/sh\n"
        "for last; do :; done\n"
        f'if [ "$1" = "-c" ] && [ "$2" = "%u" ] && [ "${{last%{target}}}" != "$last" ]; then\n'
        "  echo 4242; exit 0\n"
        "fi\n"
        f'exec "{real}" "$@"\n',
        encoding="utf-8",
    )
    stub.chmod(0o755)
    return {"PATH": f"{stub.parent}{os.pathsep}{os.environ.get('PATH', '')}"}


@pytest.mark.parametrize("target", ["/cyclaw", "/api-key"], ids=["folder", "file"])
def test_load_refuses_foreign_owned_folder_or_file(tmp_path: Path, target: str) -> None:
    _plant(tmp_path)
    result = _source(
        'cyclaw_linux_load_api_key; rc=$?\n[ -n "${CYCLAW_API_KEY:-}" ] && echo KEY_EXPORTED\nexit $rc',
        _env(tmp_path, **_NO_KEYRING, **_foreign_owner_stat(tmp_path, target)),
    )
    assert result.returncode == 2, result.stderr
    assert "KEY_EXPORTED" not in result.stdout
    assert _PLANTED not in result.stdout + result.stderr


def test_foreign_owner_stub_is_not_vacuous(tmp_path: Path) -> None:
    """Control: the same stub aimed at no real path leaves a good key loadable."""
    _plant(tmp_path)
    result = _source(
        'cyclaw_linux_load_api_key; rc=$?\n[ -n "${CYCLAW_API_KEY:-}" ] && echo KEY_EXPORTED\nexit $rc',
        _env(tmp_path, **_NO_KEYRING, **_foreign_owner_stat(tmp_path, "/no-such-suffix")),
    )
    assert result.returncode == 0, result.stderr
    assert "KEY_EXPORTED" in result.stdout


def test_load_refuses_symlinked_key_file(tmp_path: Path) -> None:
    target = tmp_path / "elsewhere"
    target.write_text(_PLANTED + "\n", encoding="utf-8")
    target.chmod(0o600)
    key_file = _key_file(tmp_path)
    key_file.parent.mkdir(parents=True, mode=0o700)
    key_file.symlink_to(target)
    result = _load(tmp_path)
    assert result.returncode == 2
    assert "KEY_EXPORTED" not in result.stdout
    assert _PLANTED not in result.stdout + result.stderr


def test_ensure_does_not_overwrite_a_refused_file(tmp_path: Path) -> None:
    """A refused file is an error to surface, not something to silently replace."""
    key_file = _plant(tmp_path, file_mode=0o644)
    result = _source("cyclaw_linux_ensure_api_key", _env(tmp_path, **_NO_KEYRING))
    assert result.returncode != 0
    assert key_file.read_text(encoding="utf-8").strip() == _PLANTED


# --- static ----------------------------------------------------------------


@pytest.mark.parametrize("path", [_HELPER, _LAUNCHER], ids=lambda p: p.name)
def test_scripts_never_enable_xtrace(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    code = "\n".join(line.split("#", 1)[0] for line in text.splitlines())
    assert not re.search(r"\bset\s+-[a-wyz]*x|\bset\s+-o\s+xtrace", code)


def test_helper_refuses_to_run_under_xtrace(tmp_path: Path) -> None:
    """Under ``set -x`` bash would echo the key into stderr; the helper must refuse."""
    _plant(tmp_path)
    result = _source(
        "set -x\ncyclaw_linux_ensure_api_key",
        _env(tmp_path, **_NO_KEYRING),
    )
    assert result.returncode != 0
    assert _PLANTED not in result.stdout + result.stderr


# --- launcher --------------------------------------------------------------


def _launcher_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    home = tmp_path / "cyhome"
    fake_python = home / "venv" / "bin" / "python"
    fake_python.parent.mkdir(parents=True)
    status = tmp_path / "gate.status"
    fake_python.write_text(
        "#!/bin/sh\n"
        'for a in "$@"; do case "$a" in *token_urlsafe*)'
        f' printf "%s\\n" "{_PAIR_SENTINEL}"; exit 0 ;; esac; done\n'
        'case "$1" in -c) exit 0 ;; -S|*/gateway_url.py) exit 1 ;; esac\n'
        f'kf="{_key_file(tmp_path)}"\n'
        'if [ -n "${CYCLAW_API_KEY:-}" ] && [ -f "$kf" ] && [ "$CYCLAW_API_KEY" = "$(cat "$kf")" ];'
        f' then echo key-from-file > "{status}"; else echo other > "{status}"; fi\n'
        "sleep 4\n"
        "exit 0\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "gate.py").write_text("# launcher probe\n", encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    opened = tmp_path / "opened"
    for opener in ("xdg-open", "open"):
        stub = bin_dir / opener
        stub.write_text(f'#!/bin/sh\nprintf "%s\\n" "$*" >> "{opened}"\n', encoding="utf-8")
        stub.chmod(0o755)
    return home, repo, opened


def _launch(
    tmp_path: Path, *args: str, api_key: str | None = None, display: str | None = None
) -> subprocess.CompletedProcess[str]:
    home, repo, _opened = _launcher_fixture(tmp_path)
    env = _env(
        tmp_path,
        CYCLAW_HOME=str(home),
        **_NO_KEYRING,
        PATH=f"{tmp_path / 'bin'}{os.pathsep}{os.environ.get('PATH', '')}",
    )
    if api_key is not None:
        env["CYCLAW_API_KEY"] = api_key
    if display is not None:
        env["DISPLAY"] = display  # the stub xdg-open on PATH receives the URL
    return subprocess.run(
        [_BASH, str(_LAUNCHER), "--repo", str(repo), "--gate-port", "8997", *args],
        cwd=_REPO,
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_pairing_url_absent_from_non_tty_output_by_default(tmp_path: Path) -> None:
    result = _launch(tmp_path, api_key="k" * 40, display=":99")
    assert _PAIR_SENTINEL not in result.stdout + result.stderr
    assert "#pair=" not in result.stdout + result.stderr
    # Non-vacuous: a code was minted and went to the opener, not the logs.
    opened = tmp_path / "opened"
    assert opened.exists() and _PAIR_SENTINEL in opened.read_text(encoding="utf-8")


def test_pairing_url_absent_from_non_tty_output_without_a_desktop(tmp_path: Path) -> None:
    """Headless and piped (systemd, nohup, CI): nothing may print the code."""
    result = _launch(tmp_path, api_key="k" * 40)
    assert _PAIR_SENTINEL not in result.stdout + result.stderr
    assert "#pair=" not in result.stdout + result.stderr


def test_print_pairing_url_flag_goes_to_stdout_only(tmp_path: Path) -> None:
    result = _launch(tmp_path, "--no-browser", "--print-pairing-url", api_key="k" * 40)
    assert _PAIR_SENTINEL in result.stdout
    assert _PAIR_SENTINEL not in result.stderr


def test_linux_launcher_generates_key_without_printing_it(tmp_path: Path) -> None:
    result = _launch(tmp_path, "--no-browser")
    key_file = _key_file(tmp_path)
    assert key_file.exists(), result.stderr
    assert stat.S_IMODE(key_file.stat().st_mode) == 0o600
    key = key_file.read_text(encoding="utf-8").strip()
    assert key not in result.stdout + result.stderr
    assert (tmp_path / "gate.status").read_text(encoding="utf-8").strip() == "key-from-file"
