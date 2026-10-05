"""Linux launcher: CYCLAW_API_KEY generation, storage, and reload (behavior).

Contract (e2e-fixes card, PR B "linux-launcher", macos/invoke-cyclaw.sh Linux
branch):

* No CYCLAW_API_KEY -> the launcher generates one.
* It is stored with ``secret-tool`` (libsecret) when available, otherwise in a
  file under ``$XDG_CONFIG_HOME/cyclaw/``; never in a tracked ``.env``.
* The next run loads the stored key into the gate process instead of
  generating a new one.

Follow-up contract (Advisor FAIL on PR #1561, Expert DECISION):

* A relative or empty ``XDG_CONFIG_HOME`` is ignored (XDG Base Directory spec: only
  absolute paths are valid), so the key lives in ``$HOME/.config/cyclaw/``
  and nothing is created in the folder the launcher was started from. An
  absolute ``XDG_CONFIG_HOME`` is still honoured.
* A loaded key (key file or libsecret) must be exactly 40 lowercase hex chars,
  the shape the launcher generates; anything else fails closed: the launcher
  exits nonzero without starting the gate, reports it on stderr with
  ``[cyclaw] error: refusing ...`` (path, never the value), and leaves the
  stored value as it was (no regeneration over it). The helper returns 2.
* The key folder's mode is parsed zero-padded, so a folder whose ``stat``
  mode prints as ``22`` / ``20`` / ``2`` (0o022 / 0o020 / 0o002) is refused
  like 0o770 is (helper return code 2), not misread as safe.
* ``--print-pairing-url`` prints the one-time URL on stdout. On a terminal
  that is all; when stdout is not a terminal it still prints the URL on
  stdout and also warns on stderr (``[cyclaw] warn : --print-pairing-url``,
  without the code).

Security properties of the same change (0600 mode, key absent from output,
pairing URL absent from non-TTY output) are PyShield's, in tests/security*;
this file only checks behavior.

Each run executes the real launcher with a temp HOME / XDG_CONFIG_HOME /
CYCLAW_HOME, a temp repo holding a stub ``gate.py`` (``macos/`` and ``utils/``
symlinked from this checkout so helpers beside the launcher resolve), and a
fake ``$CYCLAW_HOME/venv/bin/python``: ``gate.py`` records the key it was
started with and exits; every other invocation is handed to the real
interpreter. PATH is a shadow of the host PATH with ``secret-tool`` and
``curl`` removed, so "no secret-tool" holds even on hosts that have one; tests
that want libsecret put a recording stub first on PATH.

Interface assumptions PyForge should align with (or change here) are the
module constants below.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import select
import shlex
import shutil
import stat
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Interface assumptions (keep in step with the implementation)
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent
LAUNCHER = _REPO_ROOT / "macos" / "invoke-cyclaw.sh"
# --no-browser: no pairing code, no xdg-open; the launcher still loads/generates the key.
LAUNCH_ARGS: tuple[str, ...] = ("--no-browser",)
KEY_ENV_VAR = "CYCLAW_API_KEY"
# File fallback lives in $XDG_CONFIG_HOME/<CONFIG_SUBDIR>/ ($HOME/.config when XDG_CONFIG_HOME is unset).
CONFIG_SUBDIR = "cyclaw"
# Proposed fallback file name. None = accept any single file in CONFIG_SUBDIR holding the key.
KEY_FILE_NAME: str | None = "api-key"


# Attributes the launcher passes to `secret-tool store/lookup`, as a flat
# attr/value tuple (Expert DECISION, e2e-fixes PR B): service/account mirror the
# macOS Keychain -s/-a pair from utils/secret-policy.tsv; account is `id -un`.
def _login_name() -> str:
    """What `id -un` prints (the launcher's account attribute); "" off Linux."""
    if not sys.platform.startswith("linux"):
        return ""
    import pwd

    return pwd.getpwuid(os.getuid()).pw_name


SECRET_TOOL_ATTRS: tuple[str, ...] | None = ("service", "com.cgfixit.cyclaw.api-key", "account", _login_name())

# Sourced key helper beside the launcher (PyForge, PR B); exercised directly
# only for the folder-mode return code.
KEY_HELPER = _REPO_ROOT / "macos" / "cyclaw-linux-key.sh"
# cyclaw_linux_load_api_key return codes (PyForge contract): 1 no key stored,
# 2 refused (bad folder/file mode or a key that is not 40 lowercase hex).
HELPER_MISSING_RC = 1
HELPER_REFUSED_RC = 2
# Every refusal is reported on stderr with this prefix, naming the path, never the value.
REFUSED_PREFIX = "[cyclaw] error: refusing "
# --print-pairing-url with stdout not a terminal: stderr warning prefix.
PAIRING_PIPE_WARNING_PREFIX = "[cyclaw] warn : --print-pairing-url"
PAIRING_ARGS: tuple[str, ...] = ("--no-browser", "--print-pairing-url")

# ---------------------------------------------------------------------------

_BASH = shutil.which("bash")
pytestmark = [
    pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux launcher branch only"),
    pytest.mark.skipif(_BASH is None, reason="requires bash"),
]

# Names hidden from the shadow PATH. curl is replaced by a stub that answers
# the launcher's /health probe so a run ends deterministically when the fake
# gate exits.
_HIDDEN_TOOLS = frozenset({"secret-tool", "curl"})

_SECRET_TOOL_STUB = r'''#!{python}
"""Recording secret-tool stand-in: store reads the secret from stdin, lookup prints it."""
import json, sys
from pathlib import Path

state = Path({state!r})
calls = state / "calls.jsonl"
store = state / "store.json"
args = sys.argv[1:]
cmd = args[0] if args else ""
rest = args[1:]
label = None
attrs = []
i = 0
while i < len(rest):
    a = rest[i]
    if a.startswith("--label="):
        label = a.split("=", 1)[1]
    elif a == "--label" and i + 1 < len(rest):
        label = rest[i + 1]
        i += 1
    else:
        attrs.append(a)
    i += 1
key = json.dumps(sorted(zip(attrs[0::2], attrs[1::2])))
db = json.loads(store.read_text()) if store.exists() else {{}}
secret = sys.stdin.read() if cmd == "store" else ""
with calls.open("a") as fh:
    fh.write(json.dumps({{"cmd": cmd, "attrs": attrs, "label": label, "stdin_len": len(secret)}}) + "\n")
if cmd == "store":
    if (state / "fail_store").exists():
        sys.stderr.write("secret-tool: Cannot autolaunch D-Bus without X11 $DISPLAY\n")
        sys.exit(1)
    if not secret:
        sys.stderr.write("secret-tool stub: empty secret on stdin\n")
        sys.exit(1)
    db[key] = secret
    store.write_text(json.dumps(db))
    sys.exit(0)
if cmd == "lookup":
    if key in db:
        sys.stdout.write(db[key])
        sys.exit(0)
    sys.exit(1)
if cmd == "clear":
    db.pop(key, None)
    store.write_text(json.dumps(db))
    sys.exit(0)
sys.exit(2)
'''


@pytest.fixture(scope="module")
def shadow_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A directory of symlinks to every host PATH executable except _HIDDEN_TOOLS."""
    shadow = tmp_path_factory.mktemp("shadow-bin")
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        d = Path(entry)
        if not entry or not d.is_dir():
            continue
        for item in d.iterdir():
            if item.name in _HIDDEN_TOOLS or (shadow / item.name).exists():
                continue
            if item.is_file() and os.access(item, os.X_OK):
                (shadow / item.name).symlink_to(item)
    return shadow


@dataclass
class _Sandbox:
    root: Path
    shadow: Path
    with_secret_tool: bool = False
    set_xdg: bool = True
    extra_env: dict[str, str] = field(default_factory=dict)
    home: Path = field(init=False)
    xdg: Path = field(init=False)
    cyclaw_home: Path = field(init=False)
    repo: Path = field(init=False)
    stub_bin: Path = field(init=False)
    st_state: Path = field(init=False)
    record_state: Path = field(init=False)
    record_key: Path = field(init=False)
    record_pair: Path = field(init=False)
    launch_dir: Path = field(init=False)

    def __post_init__(self) -> None:
        self.home = self.root / "home"
        self.xdg = self.root / "xdg-config"
        self.cyclaw_home = self.root / "cyclaw-home"
        self.repo = self.root / "repo"
        self.stub_bin = self.root / "stub-bin"
        self.st_state = self.root / "secret-tool-state"
        self.record_state = self.root / "gate-key-state"
        self.record_key = self.root / "gate-key"
        self.record_pair = self.root / "gate-pairing-code"
        # The cwd every run starts from: not HOME, not the repo, empty.
        self.launch_dir = self.root / "launch"
        for d in (self.home, self.repo, self.stub_bin, self.st_state, self.launch_dir):
            d.mkdir(parents=True)
        (self.repo / "gate.py").write_text("# launcher probe; never executed\n", encoding="utf-8")
        (self.repo / "macos").symlink_to(_REPO_ROOT / "macos", target_is_directory=True)
        (self.repo / "utils").symlink_to(_REPO_ROOT / "utils", target_is_directory=True)

        fake_python = self.cyclaw_home / "venv" / "bin" / "python"
        fake_python.parent.mkdir(parents=True)
        # gate.py: record what the gate would see, stay up briefly, exit 0.
        # Anything else (helpers, key generation) runs on the real interpreter.
        fake_python.write_text(
            "#!/bin/sh\n"
            'if [ "$1" = "gate.py" ]; then\n'
            f'  if [ -n "${{{KEY_ENV_VAR}+x}}" ]; then printf set; else printf unset; fi > {shlex.quote(str(self.record_state))}\n'
            f'  printf %s "${{{KEY_ENV_VAR}-}}" > {shlex.quote(str(self.record_key))}\n'
            f'  printf %s "${{CYCLAW_CONSOLE_PAIRING_CODE-}}" > {shlex.quote(str(self.record_pair))}\n'
            "  sleep 1\n"
            "  exit 0\n"
            "fi\n"
            f'exec {shlex.quote(sys.executable)} "$@"\n',
            encoding="utf-8",
        )
        fake_python.chmod(0o755)

        curl = self.stub_bin / "curl"
        curl.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        curl.chmod(0o755)
        if self.with_secret_tool:
            st = self.stub_bin / "secret-tool"
            st.write_text(_SECRET_TOOL_STUB.format(python=sys.executable, state=str(self.st_state)), encoding="utf-8")
            st.chmod(0o755)

    @property
    def config_dir(self) -> Path:
        base = self.xdg if self.set_xdg else self.home / ".config"
        return base / CONFIG_SUBDIR

    def env(self, preset_key: str | None = None) -> dict[str, str]:
        env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith("CYCLAW_") and k not in {"XDG_CONFIG_HOME", "DBUS_SESSION_BUS_ADDRESS", KEY_ENV_VAR}
        }
        env["HOME"] = str(self.home)
        env["CYCLAW_HOME"] = str(self.cyclaw_home)
        env["PATH"] = f"{self.stub_bin}{os.pathsep}{self.shadow}"
        env["CYCLAW_GATE_PORT"] = "18797"
        # No desktop: the launcher never hands a pairing URL to xdg-open here.
        env.pop("DISPLAY", None)
        env.pop("WAYLAND_DISPLAY", None)
        if self.set_xdg:
            env["XDG_CONFIG_HOME"] = str(self.xdg)
        if self.with_secret_tool:
            # A session bus "exists" from the launcher's point of view; the stub needs none.
            env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={self.root / 'fake-bus'}"
        env.update(self.extra_env)
        if preset_key is not None:
            env[KEY_ENV_VAR] = preset_key
        return env

    def _argv(self, args: tuple[str, ...]) -> list[str]:
        assert _BASH is not None
        return [_BASH, str(LAUNCHER), "--repo", str(self.repo), *args]

    def _reset_records(self) -> None:
        for record in (self.record_state, self.record_key, self.record_pair):
            record.unlink(missing_ok=True)

    def run_raw(
        self, preset_key: str | None = None, args: tuple[str, ...] = LAUNCH_ARGS
    ) -> subprocess.CompletedProcess[str]:
        """Run the launcher once from ``launch_dir``, stdout/stderr on pipes; no assertions."""
        self._reset_records()
        return subprocess.run(
            self._argv(args),
            cwd=self.launch_dir,
            env=self.env(preset_key),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )

    def run_pty(self, preset_key: str | None = None, args: tuple[str, ...] = PAIRING_ARGS) -> tuple[int, str, str]:
        """Run the launcher with stdout on a pseudo-terminal and stderr on a pipe.

        Returns (exit code, terminal output, stderr).
        """
        self._reset_records()
        master, slave = os.openpty()
        try:
            proc = subprocess.Popen(
                self._argv(args),
                cwd=self.launch_dir,
                env=self.env(preset_key),
                stdin=subprocess.DEVNULL,
                stdout=slave,
                stderr=subprocess.PIPE,
            )
        finally:
            os.close(slave)
        assert proc.stderr is not None
        err_fd = proc.stderr.fileno()
        out = bytearray()
        err = bytearray()
        open_fds = {master, err_fd}
        deadline = time.monotonic() + 60
        try:
            while open_fds and time.monotonic() < deadline:
                ready, _, _ = select.select(list(open_fds), [], [], 0.5)
                for fd in ready:
                    try:
                        data = os.read(fd, 4096)
                    except OSError:  # EIO on the pty master once every writer has closed it
                        data = b""
                    if not data:
                        open_fds.discard(fd)
                    elif fd == master:
                        out += data
                    else:
                        err += data
            if open_fds:
                proc.kill()
            rc = proc.wait(timeout=10)
        finally:
            os.close(master)
            proc.stderr.close()
        assert not open_fds, f"launcher did not finish within 60s under a pty\nout:\n{out.decode(errors='replace')}"
        return rc, out.decode(errors="replace"), err.decode(errors="replace")

    def gate_started(self) -> bool:
        return self.record_state.exists()

    def run(self, preset_key: str | None = None) -> tuple[subprocess.CompletedProcess[str], str]:
        """Run the launcher once; return (process, key the gate was started with)."""
        proc = self.run_raw(preset_key)
        assert self.record_state.exists(), (
            f"launcher never started gate.py (rc={proc.returncode})\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )
        if self.record_state.read_text(encoding="utf-8") != "set":
            return proc, ""
        return proc, self.record_key.read_text(encoding="utf-8")

    def secret_tool_calls(self) -> list[dict[str, Any]]:
        calls = self.st_state / "calls.jsonl"
        if not calls.exists():
            return []
        return [json.loads(line) for line in calls.read_text(encoding="utf-8").splitlines() if line.strip()]

    def secret_tool_store(self) -> dict[str, str]:
        store = self.st_state / "store.json"
        return json.loads(store.read_text(encoding="utf-8")) if store.exists() else {}

    def files_holding(self, key: str) -> list[Path]:
        """Every regular file under the config dir whose content contains ``key``."""
        if not self.config_dir.is_dir():
            return []
        return [p for p in self.config_dir.rglob("*") if p.is_file() and key in p.read_text(errors="replace")]

    def dotenv_files_holding(self, key: str) -> list[Path]:
        candidates = [self.repo / ".env", self.cyclaw_home / ".env", self.home / ".env"]
        return [p for p in candidates if p.is_file() and key in p.read_text(errors="replace")]


def _assert_plausible_key(key: str) -> None:
    assert key, "gate.py was started without CYCLAW_API_KEY (no key generated or loaded)"
    assert len(key) >= 16 and key == key.strip() and not any(c.isspace() for c in key), (
        f"generated key does not look like a token (len={len(key)})"
    )


def _assert_single_key_file(sb: _Sandbox, key: str) -> Path:
    holders = sb.files_holding(key)
    assert len(holders) == 1, (
        f"expected exactly one file under {sb.config_dir} holding the key, found {[str(p) for p in holders]}"
    )
    path = holders[0]
    if KEY_FILE_NAME is not None:
        assert path == sb.config_dir / KEY_FILE_NAME, f"key file is {path}, expected {sb.config_dir / KEY_FILE_NAME}"
    assert path.read_text(encoding="utf-8").strip() == key
    return path


def _stores(calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [c for c in calls if c["cmd"] == "store"]


def _lookups(calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [c for c in calls if c["cmd"] == "lookup"]


# ---------------------------------------------------------------------------
# No secret-tool: file fallback under $XDG_CONFIG_HOME/cyclaw/
# ---------------------------------------------------------------------------


def test_first_run_without_secret_tool_generates_and_persists_key(tmp_path: Path, shadow_path: Path) -> None:
    sb = _Sandbox(tmp_path / "a", shadow_path)
    _proc, key = sb.run()

    _assert_plausible_key(key)
    _assert_single_key_file(sb, key)
    assert not sb.dotenv_files_holding(key), "key was written into a .env"

    # Generated, not a constant: a second fresh install gets a different key.
    other = _Sandbox(tmp_path / "b", shadow_path)
    _proc2, other_key = other.run()
    _assert_plausible_key(other_key)
    assert other_key != key


def test_second_run_without_secret_tool_loads_stored_key(tmp_path: Path, shadow_path: Path) -> None:
    sb = _Sandbox(tmp_path, shadow_path)
    _proc1, first = sb.run()
    _assert_plausible_key(first)
    key_file = _assert_single_key_file(sb, first)

    _proc2, second = sb.run()

    assert second == first, "second run did not load the stored key (regenerated or dropped it)"
    assert key_file.read_text(encoding="utf-8").strip() == first
    assert sb.files_holding(first) == [key_file]


def test_key_file_defaults_to_home_config_when_xdg_unset(tmp_path: Path, shadow_path: Path) -> None:
    # XDG Base Directory default: $HOME/.config when XDG_CONFIG_HOME is unset
    # (most desktop sessions never export it).
    sb = _Sandbox(tmp_path, shadow_path, set_xdg=False)
    _proc1, first = sb.run()
    _assert_plausible_key(first)
    _assert_single_key_file(sb, first)

    _proc2, second = sb.run()
    assert second == first


def test_preset_key_is_used_without_generating_or_storing(tmp_path: Path, shadow_path: Path) -> None:
    sb = _Sandbox(tmp_path, shadow_path, with_secret_tool=True)
    preset = "preset-operator-key-0123456789abcdef"
    _proc, key = sb.run(preset_key=preset)

    assert key == preset
    assert not _stores(sb.secret_tool_calls()), "a preset key must not trigger generation/storage"
    assert not (sb.config_dir.is_dir() and any(p.is_file() for p in sb.config_dir.rglob("*"))), (
        "a preset key must not create a fallback key file"
    )


# ---------------------------------------------------------------------------
# secret-tool (libsecret) available
# ---------------------------------------------------------------------------


def test_secret_tool_stores_key_and_next_run_looks_it_up(tmp_path: Path, shadow_path: Path) -> None:
    sb = _Sandbox(tmp_path, shadow_path, with_secret_tool=True)

    _proc1, first = sb.run()
    _assert_plausible_key(first)
    run1 = sb.secret_tool_calls()
    stores = _stores(run1)
    assert len(stores) == 1, f"expected one secret-tool store on first run, got {run1}"
    stored = list(sb.secret_tool_store().values())
    assert len(stored) == 1 and stored[0].rstrip("\n") == first, "secret-tool did not receive the key on stdin"
    store_attrs = stores[0]["attrs"]
    if SECRET_TOOL_ATTRS is not None:
        assert tuple(store_attrs) == SECRET_TOOL_ATTRS
    assert not sb.files_holding(first), "secret-tool stored the key, so no file fallback may be written"

    _proc2, second = sb.run()

    assert second == first, "second run did not load the key from secret-tool"
    run2 = sb.secret_tool_calls()[len(run1) :]
    assert not _stores(run2), f"second run re-stored (regenerated?) the key: {run2}"
    lookups = _lookups(run2)
    assert lookups, f"second run never looked the key up with secret-tool: {run2}"
    assert any(sorted(c["attrs"]) == sorted(store_attrs) for c in lookups), (
        f"lookup attributes {[c['attrs'] for c in lookups]} do not match store attributes {store_attrs}"
    )
    assert not sb.files_holding(first)


def test_secret_tool_store_failure_falls_back_to_key_file(tmp_path: Path, shadow_path: Path) -> None:
    # secret-tool installed but no usable keyring (headless box, no D-Bus
    # secret service): the key must still persist, via the file fallback.
    sb = _Sandbox(tmp_path, shadow_path, with_secret_tool=True)
    (sb.st_state / "fail_store").touch()

    _proc1, first = sb.run()
    _assert_plausible_key(first)
    _assert_single_key_file(sb, first)

    _proc2, second = sb.run()
    assert second == first


def test_secret_tool_disabled_by_env_hook_uses_key_file_only(tmp_path: Path, shadow_path: Path) -> None:
    # CYCLAW_SECRET_TOOL=none (Expert DECISION, e2e-fixes PR B) turns libsecret
    # off even when secret-tool is installed: never call it, persist via the file.
    sb = _Sandbox(tmp_path, shadow_path, with_secret_tool=True, extra_env={"CYCLAW_SECRET_TOOL": "none"})

    _proc1, first = sb.run()
    _assert_plausible_key(first)
    key_file = _assert_single_key_file(sb, first)

    _proc2, second = sb.run()
    assert second == first
    assert sb.files_holding(first) == [key_file]
    assert not sb.secret_tool_calls(), (
        f"secret-tool was called despite CYCLAW_SECRET_TOOL=none: {sb.secret_tool_calls()}"
    )


# ---------------------------------------------------------------------------
# Follow-up contract (Advisor FAIL on PR #1561): XDG, key shape, folder mode,
# pairing URL
# ---------------------------------------------------------------------------

# A well-formed stored key: 40 lowercase hex chars, the shape the launcher generates.
# Built at runtime so no key-shaped literal sits in source (DevSkim DS173237); the
# fixed "af" tail guarantees a letter so the uppercase variant always differs.
_HEX40 = secrets.token_hex(19) + "af"
# Loose match for a "stdout is not a terminal" warning; "terminal.html" (the
# console page name) does not count.
_TTY_WARNING = re.compile(r"(?i)\b(tty|terminal(?!\.html)|pairing)\b")
_PAIR_URL = re.compile(r"#pair=([A-Za-z0-9_-]+)")


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.lstat().st_mode)


def _plant_key_file(sb: _Sandbox, content: str, *, file_mode: int = 0o600) -> Path:
    """Write ``content`` verbatim as the stored key file (folder 0700)."""
    sb.config_dir.mkdir(parents=True, mode=0o700)
    sb.config_dir.chmod(0o700)
    key_file = sb.config_dir / (KEY_FILE_NAME or "api-key")
    key_file.write_bytes(content.encode("utf-8"))
    key_file.chmod(file_mode)
    return key_file


def _plant_keyring_value(sb: _Sandbox, value: str) -> None:
    """Seed the recording secret-tool stub so `lookup` returns ``value``."""
    assert SECRET_TOOL_ATTRS is not None
    attrs = list(SECRET_TOOL_ATTRS)
    key = json.dumps(sorted(zip(attrs[0::2], attrs[1::2], strict=True)))
    (sb.st_state / "store.json").write_text(json.dumps({key: value}), encoding="utf-8")


def _secret_fragments(value: str) -> list[str]:
    """Runs of 8+ key-ish chars in ``value``: none may show up in launcher output."""
    return re.findall(r"[0-9A-Za-z]{8,}", value)


def _refusal_lines(stderr: str) -> list[str]:
    return [line for line in stderr.splitlines() if line.startswith(REFUSED_PREFIX)]


def _assert_failed_closed(
    sb: _Sandbox, proc: subprocess.CompletedProcess[str], bad_value: str, *, names: Path | None = None
) -> None:
    """Launcher stopped (nonzero, no gate), said why on stderr, and printed no part of the value."""
    output = proc.stdout + proc.stderr
    assert proc.returncode != 0, (
        f"launcher exited 0 with an invalid stored key (it must fail closed)\nstderr:\n{proc.stderr}"
    )
    assert not sb.gate_started(), (
        "launcher started gate.py although the stored key was refused "
        f"(gate saw CYCLAW_API_KEY {'set' if sb.record_key.exists() and sb.record_key.read_text() else 'unset'})"
    )
    leaked = [frag for frag in _secret_fragments(bad_value) if frag in output]
    assert not leaked, "launcher printed (part of) the refused key value"
    refusals = _refusal_lines(proc.stderr)
    assert refusals, f"no stderr line starting {REFUSED_PREFIX!r}\nstderr:\n{proc.stderr}"
    if names is not None:
        assert any(str(names) in line for line in refusals), f"refusal does not name {names}: {refusals}"


def test_absolute_xdg_config_home_is_honoured_and_home_config_untouched(tmp_path: Path, shadow_path: Path) -> None:
    # Regression guard for the relative-XDG fix: an absolute XDG_CONFIG_HOME
    # still wins over $HOME/.config.
    sb = _Sandbox(tmp_path, shadow_path)
    _proc, key = sb.run()
    _assert_plausible_key(key)
    key_file = _assert_single_key_file(sb, key)
    assert key_file == sb.xdg / CONFIG_SUBDIR / (KEY_FILE_NAME or key_file.name)
    assert not (sb.home / ".config").exists(), "absolute XDG_CONFIG_HOME set, but $HOME/.config was created"


@pytest.mark.parametrize(
    "relative_xdg", ["conf", "./conf", "conf/sub", ""], ids=["conf", "dot-conf", "conf-sub", "empty"]
)
def test_relative_xdg_config_home_is_ignored_for_home_config(
    tmp_path: Path, shadow_path: Path, relative_xdg: str
) -> None:
    # XDG Base Directory spec: a relative XDG_CONFIG_HOME is invalid and must be
    # ignored, otherwise the key lands wherever the launcher happened to start.
    # An empty value means unset.
    sb = _Sandbox(tmp_path, shadow_path, set_xdg=False, extra_env={"XDG_CONFIG_HOME": relative_xdg})
    assert sb.launch_dir not in (sb.repo, sb.home)

    _proc1, first = sb.run()

    created = sorted(p.name for p in sb.launch_dir.iterdir())
    assert not created, f"relative XDG_CONFIG_HOME={relative_xdg!r} created {created} in the launch folder"
    for name in ("conf", CONFIG_SUBDIR):
        assert not (sb.repo / name).exists(), f"relative XDG_CONFIG_HOME created {name}/ in the repo"
    _assert_plausible_key(first)
    key_file = _assert_single_key_file(sb, first)
    assert key_file.parent == sb.home / ".config" / CONFIG_SUBDIR
    assert _mode(key_file) == 0o600, oct(_mode(key_file))
    assert _mode(key_file.parent) == 0o700, oct(_mode(key_file.parent))

    # And the next run loads it from the same place.
    _proc2, second = sb.run()
    assert second == first
    assert not any(sb.launch_dir.iterdir())


def test_valid_40_hex_key_file_is_loaded_as_is(tmp_path: Path, shadow_path: Path) -> None:
    # Positive control for the shape check: the generated shape, newline-terminated
    # the way the launcher writes it, loads unchanged.
    sb = _Sandbox(tmp_path, shadow_path)
    key_file = _plant_key_file(sb, _HEX40 + "\n")
    _proc, key = sb.run()
    assert key == _HEX40
    assert key_file.read_text(encoding="utf-8") == _HEX40 + "\n"


_INVALID_FILE_KEYS = {
    "empty": "",
    "39-hex": _HEX40[:-1],
    "41-hex": _HEX40 + "8",
    "40-with-non-hex": _HEX40[:-1] + "g",
    "40-with-inner-space": _HEX40[:20] + " " + _HEX40[21:],
    "leading-tab": "\t" + _HEX40,
    "trailing-space": _HEX40 + " ",
    "trailing-cr": _HEX40 + "\r",
    "split-across-lines": _HEX40[:20] + "\n" + _HEX40[20:],
    "uppercase-40-hex": _HEX40.upper(),
}


@pytest.mark.parametrize("content", list(_INVALID_FILE_KEYS.values()), ids=list(_INVALID_FILE_KEYS))
def test_invalid_key_file_fails_closed(tmp_path: Path, shadow_path: Path, content: str) -> None:
    sb = _Sandbox(tmp_path, shadow_path)
    key_file = _plant_key_file(sb, content + "\n")
    before = key_file.read_bytes()

    proc = sb.run_raw()

    _assert_failed_closed(sb, proc, content, names=key_file)
    assert key_file.read_bytes() == before, "the refused key file was rewritten"
    assert sorted(p.name for p in sb.config_dir.iterdir()) == [key_file.name], "extra files next to the key file"
    assert _mode(key_file) == 0o600


_INVALID_KEYRING_KEYS = {
    "39-hex": _HEX40[:-1],
    "41-hex": _HEX40 + "8",
    "40-with-non-hex": _HEX40[:-1] + "g",
    "40-with-inner-space": _HEX40[:20] + " " + _HEX40[21:],
    "inner-newline": _HEX40[:20] + "\n" + _HEX40[20:],
    "uppercase-40-hex": _HEX40.upper(),
}


@pytest.mark.parametrize("value", list(_INVALID_KEYRING_KEYS.values()), ids=list(_INVALID_KEYRING_KEYS))
def test_invalid_keyring_key_fails_closed(tmp_path: Path, shadow_path: Path, value: str) -> None:
    sb = _Sandbox(tmp_path, shadow_path, with_secret_tool=True)
    _plant_keyring_value(sb, value)

    proc = sb.run_raw()

    _assert_failed_closed(sb, proc, value)
    assert list(sb.secret_tool_store().values()) == [value], "the refused keyring value was replaced"
    assert not _stores(sb.secret_tool_calls()), "launcher stored a new key over the refused keyring value"
    assert not (sb.config_dir.is_dir() and any(sb.config_dir.iterdir())), (
        "launcher fell back to a key file instead of failing closed on a bad keyring value"
    )


# `stat -c %a` prints these as "22", "20", "2": a positional parse that expects
# three digits misreads them as safe.
_ZERO_PADDED_WRITABLE_DIR_MODES = [0o022, 0o020, 0o002]


@pytest.mark.parametrize("dir_mode", _ZERO_PADDED_WRITABLE_DIR_MODES, ids=oct)
def test_group_or_other_writable_key_folder_is_refused_by_launcher(
    tmp_path: Path, shadow_path: Path, dir_mode: int
) -> None:
    sb = _Sandbox(tmp_path, shadow_path)
    key_file = _plant_key_file(sb, _HEX40 + "\n")
    sb.config_dir.chmod(dir_mode)
    try:
        proc = sb.run_raw()
        mode_after = _mode(sb.config_dir)
    finally:
        sb.config_dir.chmod(0o700)

    assert proc.returncode != 0, f"key folder mode {oct(dir_mode)} accepted\nstderr:\n{proc.stderr}"
    assert not sb.gate_started(), f"launcher started gate.py with key folder mode {oct(dir_mode)}"
    refusals = _refusal_lines(proc.stderr)
    assert any(str(sb.config_dir) in line for line in refusals), (
        f"no {REFUSED_PREFIX!r} line naming {sb.config_dir}\nstderr:\n{proc.stderr}"
    )
    assert mode_after == dir_mode, f"launcher repaired the refused folder to {oct(mode_after)} instead of stopping"
    assert key_file.read_text(encoding="utf-8") == _HEX40 + "\n", "the key in a refused folder was replaced"
    assert sorted(p.name for p in sb.config_dir.iterdir()) == [key_file.name]
    assert _HEX40 not in proc.stdout + proc.stderr


def _helper_load(sb: _Sandbox) -> subprocess.CompletedProcess[str]:
    """Source the key helper and call cyclaw_linux_load_api_key with libsecret off."""
    assert _BASH is not None
    script = (
        f". {shlex.quote(str(KEY_HELPER))} || exit 97\n"
        "cyclaw_linux_load_api_key; rc=$?\n"
        '[ -n "${CYCLAW_API_KEY:-}" ] && echo KEY_EXPORTED\n'
        "exit $rc\n"
    )
    env = sb.env()
    env["CYCLAW_SECRET_TOOL"] = "none"
    return subprocess.run(
        [_BASH, "-c", script],
        cwd=sb.launch_dir,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )


@pytest.mark.parametrize("dir_mode", _ZERO_PADDED_WRITABLE_DIR_MODES, ids=oct)
def test_key_helper_load_returns_refused_for_zero_padded_writable_folder(
    tmp_path: Path, shadow_path: Path, dir_mode: int
) -> None:
    sb = _Sandbox(tmp_path, shadow_path)
    _plant_key_file(sb, _HEX40 + "\n")
    sb.config_dir.chmod(dir_mode)
    try:
        result = _helper_load(sb)
    finally:
        sb.config_dir.chmod(0o700)
    assert result.returncode == HELPER_REFUSED_RC, (
        f"folder mode {oct(dir_mode)}: rc={result.returncode}, expected {HELPER_REFUSED_RC}\nstderr:\n{result.stderr}"
    )
    assert "KEY_EXPORTED" not in result.stdout
    assert any(str(sb.config_dir) in line for line in _refusal_lines(result.stderr)), result.stderr


def test_key_helper_load_return_codes_missing_valid_and_bad_key(tmp_path: Path, shadow_path: Path) -> None:
    # 1 = nothing stored (the launcher then generates), 0 = loaded, 2 = refused.
    missing = _helper_load(_Sandbox(tmp_path / "missing", shadow_path))
    assert missing.returncode == HELPER_MISSING_RC, missing.stderr
    assert "KEY_EXPORTED" not in missing.stdout

    good = _Sandbox(tmp_path / "good", shadow_path)
    _plant_key_file(good, _HEX40 + "\n")
    loaded = _helper_load(good)
    assert loaded.returncode == 0, loaded.stderr
    assert "KEY_EXPORTED" in loaded.stdout

    for name in ("39-hex", "uppercase-40-hex", "40-with-non-hex"):
        sb = _Sandbox(tmp_path / name, shadow_path)
        bad = _INVALID_FILE_KEYS[name]
        key_file = _plant_key_file(sb, bad + "\n")
        result = _helper_load(sb)
        assert result.returncode == HELPER_REFUSED_RC, f"{name}: rc={result.returncode}\nstderr:\n{result.stderr}"
        assert "KEY_EXPORTED" not in result.stdout, name
        assert any(str(key_file) in line for line in _refusal_lines(result.stderr)), (name, result.stderr)
        assert bad not in result.stdout + result.stderr, f"{name}: helper printed the refused value"


@pytest.mark.parametrize("file_mode", [0o022, 0o066], ids=oct)
def test_zero_padded_group_or_other_key_file_mode_is_refused(tmp_path: Path, shadow_path: Path, file_mode: int) -> None:
    # The file check must not share the folder check's positional-parse bug.
    sb = _Sandbox(tmp_path, shadow_path)
    key_file = _plant_key_file(sb, _HEX40 + "\n", file_mode=file_mode)
    try:
        proc = sb.run_raw()
    finally:
        key_file.chmod(0o600)
    assert proc.returncode != 0, f"key file mode {oct(file_mode)} accepted"
    assert not sb.gate_started()
    assert any(str(key_file) in line for line in _refusal_lines(proc.stderr)), proc.stderr
    assert key_file.read_text(encoding="utf-8") == _HEX40 + "\n"
    assert _HEX40 not in proc.stdout + proc.stderr


def _recorded_pairing_code(sb: _Sandbox) -> str:
    assert sb.record_pair.exists(), "launcher never started gate.py"
    code = sb.record_pair.read_text(encoding="utf-8")
    assert code, "gate.py was started without a pairing code although --print-pairing-url was passed"
    return code


def test_print_pairing_url_on_a_terminal_prints_url_without_warning(tmp_path: Path, shadow_path: Path) -> None:
    sb = _Sandbox(tmp_path, shadow_path)
    rc, terminal, stderr = sb.run_pty(preset_key=_HEX40)

    assert rc == 0, f"rc={rc}\nterminal:\n{terminal}\nstderr:\n{stderr}"
    code = _recorded_pairing_code(sb)
    assert code in _PAIR_URL.findall(terminal), "pairing URL with the gate's code was not printed to the terminal"
    warnings = [
        line
        for line in stderr.splitlines()
        if _TTY_WARNING.search(line) or line.startswith(PAIRING_PIPE_WARNING_PREFIX)
    ]
    assert not warnings, f"stdout is a terminal, yet the launcher warned: {warnings}"
    assert code not in stderr


def test_print_pairing_url_to_a_pipe_prints_url_and_warns_on_stderr(tmp_path: Path, shadow_path: Path) -> None:
    sb = _Sandbox(tmp_path, shadow_path)
    proc = sb.run_raw(preset_key=_HEX40, args=PAIRING_ARGS)

    assert proc.returncode == 0, proc.stderr
    code = _recorded_pairing_code(sb)
    assert code in _PAIR_URL.findall(proc.stdout), "explicit --print-pairing-url must still print the URL to stdout"
    warnings = [line for line in proc.stderr.splitlines() if line.startswith(PAIRING_PIPE_WARNING_PREFIX)]
    assert warnings, f"stdout is a pipe, but stderr has no {PAIRING_PIPE_WARNING_PREFIX!r} line:\n{proc.stderr}"
    assert code not in proc.stdout.replace(f"#pair={code}", ""), "pairing code printed outside the URL"
    assert code not in proc.stderr, "the pairing code reached stderr"
