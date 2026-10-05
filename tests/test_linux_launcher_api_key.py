"""Linux launcher: CYCLAW_API_KEY generation, storage, and reload (behavior).

Contract (e2e-fixes card, PR B "linux-launcher", macos/invoke-cyclaw.sh Linux
branch):

* No CYCLAW_API_KEY -> the launcher generates one.
* It is stored with ``secret-tool`` (libsecret) when available, otherwise in a
  file under ``$XDG_CONFIG_HOME/cyclaw/``; never in a tracked ``.env``.
* The next run loads the stored key into the gate process instead of
  generating a new one.

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
import shlex
import shutil
import subprocess
import sys
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

    def __post_init__(self) -> None:
        self.home = self.root / "home"
        self.xdg = self.root / "xdg-config"
        self.cyclaw_home = self.root / "cyclaw-home"
        self.repo = self.root / "repo"
        self.stub_bin = self.root / "stub-bin"
        self.st_state = self.root / "secret-tool-state"
        self.record_state = self.root / "gate-key-state"
        self.record_key = self.root / "gate-key"
        for d in (self.home, self.repo, self.stub_bin, self.st_state):
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
        if self.set_xdg:
            env["XDG_CONFIG_HOME"] = str(self.xdg)
        if self.with_secret_tool:
            # A session bus "exists" from the launcher's point of view; the stub needs none.
            env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={self.root / 'fake-bus'}"
        env.update(self.extra_env)
        if preset_key is not None:
            env[KEY_ENV_VAR] = preset_key
        return env

    def run(self, preset_key: str | None = None) -> tuple[subprocess.CompletedProcess[str], str]:
        """Run the launcher once; return (process, key the gate was started with)."""
        self.record_state.unlink(missing_ok=True)
        self.record_key.unlink(missing_ok=True)
        assert _BASH is not None
        proc = subprocess.run(
            [_BASH, str(LAUNCHER), "--repo", str(self.repo), *LAUNCH_ARGS],
            cwd=self.root,
            env=self.env(preset_key),
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
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
