"""Process-boundary delivery tests for the canonical telemetry-safe env.

test_telemetry_kill.py proves the IMPORT-TIME half (each entry point applies
the block before heavy imports). This file proves the DELIVERY half from
issue #1135: the canonical environment exists before a child interpreter or
external tool initializes, at every boundary that builds an env by hand --
the agentic verifier, the gh spawn sites, the sync indexer child, the
Dockerfile/compose images, the launchers, and every generated launchd plist /
Windows task / cron line. The sitecustomize probe is the strongest form: a
temporary sitecustomize.py snapshots os.environ at INTERPRETER STARTUP,
before any user code (or any import-time kill) could run, so what it records
is exactly what the delivery mechanism itself provided. No network anywhere.
"""

from __future__ import annotations

import json
import os
import plistlib
import subprocess
import sys
from pathlib import Path

import pytest

from utils.telemetry_kill import (
    SCRUBBED_ENV_KEYS,
    TELEMETRY_KILL,
    UPDATE_CHECK_OPT_OUT,
    build_telemetry_safe_env,
    scheduler_env_overlay,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

_CANONICAL = {**TELEMETRY_KILL, **UPDATE_CHECK_OPT_OUT}


# ---------------------------------------------------------------------------
# sitecustomize probe -- values present at interpreter startup
# ---------------------------------------------------------------------------


def _probe_at_interpreter_startup(env: dict[str, str], tmp_path: Path) -> dict[str, str | None]:
    """Launch ``python -c pass`` with *env*; a sitecustomize.py on PYTHONPATH
    dumps the canonical names before any user code executes."""
    probe_dir = tmp_path / "probe"
    probe_dir.mkdir(exist_ok=True)
    out_file = tmp_path / "snapshot.json"
    names = sorted(set(_CANONICAL) | set(SCRUBBED_ENV_KEYS))
    (probe_dir / "sitecustomize.py").write_text(
        "import json, os\n"
        f"names = {names!r}\n"
        f"with open({str(out_file)!r}, 'w') as fh:\n"
        "    json.dump({n: os.environ.get(n) for n in names}, fh)\n",
        encoding="utf-8",
    )
    child_env = dict(env)
    # The probe dir must be the interpreter's sitecustomize source; anything
    # the mechanism itself put in PYTHONPATH is irrelevant to this assertion.
    child_env["PYTHONPATH"] = str(probe_dir)
    completed = subprocess.run(
        [sys.executable, "-c", "pass"],
        env=child_env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(out_file.read_text(encoding="utf-8"))


def _assert_canonical_at_startup(snapshot: dict[str, str | None]) -> None:
    wrong = {k: snapshot.get(k) for k, v in _CANONICAL.items() if snapshot.get(k) != v}
    assert not wrong, f"canonical values not present at interpreter startup: {wrong}"
    leaked = [k for k in SCRUBBED_ENV_KEYS if snapshot.get(k) is not None]
    assert not leaked, f"scrubbed names visible at interpreter startup: {leaked}"


def test_sitecustomize_probe_build_telemetry_safe_env(tmp_path, monkeypatch):
    monkeypatch.setenv("GH_TELEMETRY", "true")
    monkeypatch.setenv("OTEL_CONFIG_FILE", "/tmp/evil.yaml")
    _assert_canonical_at_startup(_probe_at_interpreter_startup(build_telemetry_safe_env(), tmp_path))


def test_sitecustomize_probe_scheduler_overlay(tmp_path):
    """A generated job's env is the overlay + whatever the scheduler adds;
    the overlay alone must already pin every canonical value at startup."""
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), **scheduler_env_overlay()}
    snapshot = _probe_at_interpreter_startup(env, tmp_path)
    wrong = {k: snapshot.get(k) for k, v in _CANONICAL.items() if snapshot.get(k) != v}
    assert not wrong, wrong


@pytest.mark.skipif(os.name == "nt", reason="POSIX shell eval semantics")
def test_sitecustomize_probe_export_cli_roundtrip(tmp_path):
    """The launchers' mechanism end to end: eval the --export output in a
    shell, then prove the values at a child interpreter's startup."""
    probe_dir = tmp_path / "probe"
    probe_dir.mkdir()
    out_file = tmp_path / "snapshot.json"
    names = sorted(set(_CANONICAL) | set(SCRUBBED_ENV_KEYS))
    (probe_dir / "sitecustomize.py").write_text(
        "import json, os\n"
        f"names = {names!r}\n"
        f"with open({str(out_file)!r}, 'w') as fh:\n"
        "    json.dump({n: os.environ.get(n) for n in names}, fh)\n",
        encoding="utf-8",
    )
    script = (
        f'set -e\ncd "{REPO_ROOT}"\n'
        f'eval "$("{sys.executable}" -m utils.telemetry_kill --export shell)"\n'
        f'export PYTHONPATH="{probe_dir}"\n'
        f'exec "{sys.executable}" -c pass\n'
    )
    completed = subprocess.run(
        ["/bin/bash", "-c", script],
        capture_output=True,
        text=True,
        timeout=60,
        env={
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            # Hostile ambient values the eval'd block must overwrite/remove.
            "GH_TELEMETRY": "true",
            "OTEL_CONFIG_FILE": "/tmp/evil.yaml",
        },
    )
    assert completed.returncode == 0, completed.stderr
    _assert_canonical_at_startup(json.loads(out_file.read_text(encoding="utf-8")))


# ---------------------------------------------------------------------------
# Docker surfaces (static -- no docker daemon in CI)
# ---------------------------------------------------------------------------


def _dockerfile_env_pairs() -> dict[str, str]:
    pairs: dict[str, str] = {}
    text = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8").replace("\\\n", " ")
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("ENV "):
            continue
        import re

        for m in re.finditer(r'([A-Za-z_][A-Za-z0-9_]*)=("[^"]*"|\S*)', line[4:]):
            value = m.group(2)
            pairs[m.group(1)] = value[1:-1] if value.startswith('"') else value
    return pairs


def test_dockerfile_delivers_canonical_env():
    pairs = _dockerfile_env_pairs()
    assert "CYCLAW_TELEMETRY_KILL" not in pairs, "decorative marker must stay removed"
    wrong = {k: pairs.get(k) for k, v in _CANONICAL.items() if pairs.get(k) != v}
    assert not wrong, f"Dockerfile ENV disagrees with the canonical maps: {wrong}"


def test_compose_delivers_canonical_env():
    text = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    pairs: dict[str, str] = {}
    for raw in text.splitlines():
        stripped = raw.strip()
        if stripped.startswith("- ") and "=" in stripped:
            name, _, value = stripped[2:].partition("=")
            pairs[name.strip()] = value
    assert "CYCLAW_TELEMETRY_KILL" not in pairs, "decorative marker must stay removed"
    wrong = {k: pairs.get(k) for k, v in _CANONICAL.items() if pairs.get(k) != v}
    assert not wrong, f"compose environment disagrees with the canonical maps: {wrong}"


# ---------------------------------------------------------------------------
# Generated launchd plists / Windows tasks / cron
# ---------------------------------------------------------------------------


def test_service_plist_generator_carries_overlay(tmp_path, monkeypatch, capsys):
    sys.path.insert(0, str(REPO_ROOT / "macos"))
    try:
        import generate_service_plist as gsp
    finally:
        sys.path.pop(0)
    home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(gsp.platform, "system", lambda: "Darwin")
    code = gsp.main([
        "--service", "gate", "--confirm", "--reason", "delivery test",
    ])
    assert code == 0
    plist_path = home / "Library" / "LaunchAgents" / "com.cgfixit.cyclaw.gate.plist"
    document = plistlib.loads(plist_path.read_bytes())
    env = document["EnvironmentVariables"]
    for key, value in _CANONICAL.items():
        assert env.get(key) == value, f"{key} missing/wrong in generated plist"


def test_windows_cmd_launcher_set_lines(tmp_path):
    from utils.win_schtasks import write_cmd_launcher

    path = tmp_path / "task.cmd"
    write_cmd_launcher(path, ["python.exe", "-m", "sync.cli", "sync"], env=scheduler_env_overlay())
    content = path.read_bytes().decode("utf-8")
    assert 'set "GH_TELEMETRY=false"' in content
    assert 'set "POWERSHELL_TELEMETRY_OPTOUT=1"' in content
    assert 'set "POWERSHELL_UPDATECHECK=Off"' in content
    # cmd cannot express empty-but-present: `set "NAME="` DELETES the var --
    # the deliberate, documented form for the two blank CHROMA_OTEL_* names.
    assert 'set "CHROMA_OTEL_COLLECTION_ENDPOINT="' in content
    assert 'set "CHROMA_OTEL_SERVICE_NAME="' in content
    # Inherited scrubbed names are deleted before the env block (Task
    # Scheduler jobs inherit machine/user env; set "NAME=" deletes).
    assert 'set "OTEL_CONFIG_FILE="' in content
    assert 'set "LANGSMITH_API_KEY="' in content
    assert content.index('set "OTEL_CONFIG_FILE="') < content.index('set "GH_TELEMETRY=false"')
    assert content.index('set "GH_TELEMETRY=false"') < content.index("python.exe")


def test_sync_cron_line_uses_short_telemetry_safe_launcher(monkeypatch, tmp_path):
    import sync.scheduler as scheduler

    monkeypatch.setattr(scheduler.platform, "system", lambda: "Linux")
    long_root = str(tmp_path / ("repo-" + "x" * 800))
    monkeypatch.setattr(scheduler, "_repo_root", lambda cfg: long_root)

    class _Cfg:
        _config_path = None
        log_dir = str(tmp_path)
        local_path = long_root
        schedule_min = 30
        schedule_hour = 3
        schedule_frequency = "daily"

    line = scheduler.CronScheduler(_Cfg())._our_line()
    launcher = tmp_path / "cyclaw_sync.sh"
    content = launcher.read_text(encoding="utf-8")

    assert len(line) < 256
    assert str(launcher) in line
    if scheduler.os.name != "nt":
        assert launcher.stat().st_mode & 0o100
    assert " env " in f" {content} "
    # shlex.quote leaves shell-safe tokens unquoted -- assert the pair itself.
    assert "GH_TELEMETRY=false" in content
    assert "OTEL_SDK_DISABLED=true" in content
    assert "CHROMA_OTEL_COLLECTION_ENDPOINT=" in content
    # Inherited scrubbed names must be REMOVED pre-interpreter: positive
    # assignments cannot do that, so the launcher carries env -u unsets.
    assert "-u OTEL_CONFIG_FILE" in content
    assert "-u OTEL_EXPERIMENTAL_CONFIG_FILE" in content
    assert "-u LANGSMITH_API_KEY" in content
    assert content.index("-u OTEL_CONFIG_FILE") < content.index("GH_TELEMETRY=false")
    assert content.index(" env ") < content.index("-m sync.scheduled"), "env prefix must precede the interpreter"


def test_sync_windows_bat_set_lines(tmp_path, monkeypatch):
    import sync.scheduler as scheduler

    class _Cfg:
        _config_path = None
        log_dir = str(tmp_path)
        local_path = str(REPO_ROOT)

    monkeypatch.setattr(scheduler, "_repo_root", lambda cfg: str(REPO_ROOT))
    bat_path = scheduler._write_windows_launcher(_Cfg())
    content = Path(bat_path).read_text(encoding="utf-8")
    assert 'set "GH_TELEMETRY=false"' in content
    assert 'set "OTEL_SDK_DISABLED=true"' in content
    assert 'set "OTEL_CONFIG_FILE="' in content, "inherited scrub names must be deleted"
    assert content.index('set "OTEL_CONFIG_FILE="') < content.index('set "GH_TELEMETRY=false"')
    assert content.index('set "GH_TELEMETRY=false"') < content.index("-m sync.scheduled")


def test_sync_launchd_plist_carries_overlay(tmp_path, monkeypatch):
    import sync.scheduler as scheduler

    class _Cfg:
        _config_path = None
        log_dir = str(tmp_path / "logs")
        local_path = str(REPO_ROOT)

    sched = scheduler.LaunchdScheduler(_Cfg())
    monkeypatch.setattr(scheduler.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
    # The schedule/argv helpers read many RcloneConfig fields irrelevant to
    # env delivery -- stub them so this test pins exactly one thing: the
    # generated document's EnvironmentVariables.
    monkeypatch.setattr(scheduler, "_launchd_calendar_interval", lambda cfg: {"Hour": 3, "Minute": 30})
    monkeypatch.setattr(scheduler, "_launchd_program_arguments", lambda cfg: ["/usr/bin/python3", "-m", "sync.cli", "sync"])
    monkeypatch.setattr(scheduler, "_repo_root", lambda cfg: str(REPO_ROOT))
    sched.install()
    plist_path = tmp_path / "home" / "Library" / "LaunchAgents" / f"{scheduler.LAUNCHD_LABEL}.plist"
    document = plistlib.loads(plist_path.read_bytes())
    assert document["EnvironmentVariables"] == scheduler_env_overlay()


# ---------------------------------------------------------------------------
# Launcher scripts (static text -- .sh/.ps1 cannot execute cross-platform here)
# ---------------------------------------------------------------------------


def test_macos_launcher_exports_canonical_block():
    text = (REPO_ROOT / "macos" / "invoke-cyclaw.sh").read_text(encoding="utf-8")
    # -S -E is part of the contract: no site init in the helper interpreter.
    assert "-S -E -m utils.telemetry_kill --export shell" in text
    # Overwrite semantics: the eval must come AFTER the dotenv sourcing.
    assert text.index("_source_dotenv") < text.index("--export shell")
    # And BEFORE the servers start. Darwin invoke now runs gate.py (not uvicorn).
    assert text.index("--export shell") < text.index('"$VENV_PY" gate.py &')


def test_powershell_launcher_exports_canonical_block():
    text = (REPO_ROOT / "powershell" / "Invoke-CyClaw.ps1").read_text(encoding="utf-8")
    assert "-S -E -m utils.telemetry_kill --export powershell" in text
    assert text.index("Import-CyclawDotenv") < text.index("--export powershell")
    assert text.index("--export powershell") < text.index("& $VenvPy gate.py")


def test_install_shim_sets_pwsh_optouts_before_powershell_starts():
    text = (REPO_ROOT / "powershell" / "Install-CyClaw.ps1").read_text(encoding="utf-8")
    shim_start = text.index("cyclaw.cmd")
    ps_line = text.index("powershell -NoProfile", shim_start)
    assert shim_start < text.index('set "POWERSHELL_TELEMETRY_OPTOUT=1"', shim_start) < ps_line
    assert shim_start < text.index('set "POWERSHELL_UPDATECHECK=Off"', shim_start) < ps_line
