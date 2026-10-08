"""Contract tests for powershell/ Windows parity glue.

No real schtasks, Credential Manager, or ACL mutation. Most tests read the
scripts as text; the installer regression uses a disposable home and fake git.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_PS = _REPO_ROOT / "powershell"


def test_secret_store_imports_policy_targets_and_skips_secret_dotenv(tmp_path: Path) -> None:
    shell = shutil.which("powershell") if os.name == "nt" else shutil.which("pwsh")
    if shell is None:
        pytest.skip("PowerShell is not installed")
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "CYCLAW_GATE_PORT=8788\n"
        "CYCLAW_SQL_DSN=plaintext-dsn\n"
        "CYCLAW_DB_URL=plaintext-db\n"
        "GH_PAT=plaintext-pat\n"
        "DB_CREDENTIALS=plaintext-credentials\n",
        encoding="utf-8",
    )
    script = r"""
$ErrorActionPreference = 'Stop'
. ./powershell/CyClaw-SecretStore.ps1
function Test-CyclawDotenvOwnerOnly([string]$Path) { return $true }
function Test-CyclawWindowsHost { return $true }
function Read-CyclawCredential([string]$Target) {
    return [pscustomobject]@{ Status = 'readable'; Secret = ('vault-' + $Target); Win32 = 0 }
}
foreach ($name in $script:CyclawSecretTargets.Keys) {
    Remove-Item -Path ('Env:' + $name) -ErrorAction SilentlyContinue
}
foreach ($name in @('GH_PAT', 'DB_CREDENTIALS', 'CYCLAW_GATE_PORT')) {
    Remove-Item -Path ('Env:' + $name) -ErrorAction SilentlyContinue
}
if (-not (Import-CyclawDotenv $env:CYCLAW_TEST_DOTENV)) { throw 'dotenv not loaded' }
if ($env:CYCLAW_GATE_PORT -ne '8788') { throw 'public setting not imported' }
foreach ($name in @('CYCLAW_SQL_DSN', 'CYCLAW_DB_URL', 'GH_PAT', 'DB_CREDENTIALS')) {
    if ([Environment]::GetEnvironmentVariable($name)) { throw "dotenv leaked $name" }
    if (-not (Test-CyclawSecretName $name)) { throw "classifier missed $name" }
}
Import-CyclawCredentialSecrets
foreach ($name in @('CYCLAW_SQL_DSN', 'CYCLAW_DB_URL', 'CYCLAW_VECTOR_DB_URL',
                    'CYCLAW_RATELIMIT_DB_URL', 'CYCLAW_AUTH_DB_URL')) {
    $expected = 'vault-' + $script:CyclawSecretTargets[$name]
    if ([Environment]::GetEnvironmentVariable($name) -cne $expected) {
        throw "Credential Manager target not loaded for $name"
    }
}
foreach ($name in @('GH_PAT', 'DB_CREDENTIALS')) {
    if ([Environment]::GetEnvironmentVariable($name)) { throw "unmapped $name was loaded" }
}
'OK'
"""
    env = os.environ.copy()
    env["CYCLAW_TEST_DOTENV"] = str(dotenv)
    result = subprocess.run(
        [shell, "-NoProfile", "-Command", script], cwd=_REPO_ROOT, env=env,
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[-1] == "OK"


def test_installer_update_checks_git_exit() -> None:
    text = (_PS / "Install-CyClaw.ps1").read_text(encoding="utf-8")
    update = text.split('Write-Step "repo already present at $Repo (pulling latest main)"', 1)[1]
    update = update.split("Assert-SafeRepoPath $Repo", 1)[0]
    assert re.search(
        r"& git -C \$Repo pull --ff-only --no-autostash\r?\n"
        r'\s*if \(\$LASTEXITCODE -ne 0\) \{ throw "git pull failed',
        update,
    )


@pytest.mark.skipif(os.name != "nt", reason="requires Windows PowerShell 5.1")
def test_installer_git_failure_stops_before_launcher(tmp_path: Path) -> None:
    home = tmp_path / "operator"
    server = home / ".CyClaw" / "repo" / "gate.py"
    server.parent.mkdir(parents=True)
    server.write_text("", encoding="utf-8")

    shim_dir = tmp_path / "bin"
    shim_dir.mkdir()
    (shim_dir / "git.cmd").write_text("@echo off\r\nexit /b 37\r\n", encoding="ascii")

    system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    powershell = system_root / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    if not powershell.is_file():
        pytest.skip("Windows PowerShell 5.1 is unavailable")

    env = os.environ.copy()
    env["USERPROFILE"] = str(home)
    env["PATH"] = str(shim_dir) + os.pathsep + env.get("PATH", "")
    result = subprocess.run(
        [
            str(powershell),
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(_PS / "Install-CyClaw.ps1"),
            "-SkipPythonDeps",
            "-NoProfileEdit",
            "-NoPathEdit",
        ],
        cwd=_REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "git pull failed (exit 37)" in output
    assert not (home / ".CyClaw" / "bin" / "Invoke-CyClaw.ps1").exists()


def test_uninstall_deletes_only_known_task_names() -> None:
    text = (_PS / "Uninstall-CyClaw.ps1").read_text(encoding="utf-8")
    assert "Unschedule-KnownTasks" in text
    assert "Unschedule-SyncJob" in text
    assert "schtasks.exe" in text
    assert "/Delete" in text
    assert "/TN" in text
    for name in (
        "CyClaw Dropbox Sync",
        "CyClaw fsconnect-trash",
        "CyClaw telegram-poll",
        "CyClaw telegram-health",
        "CyClaw gate",
        "CyClaw harness",
        "CyClaw opentweet",
    ):
        assert name in text
    assert "*" not in text.split("KnownTaskNames")[1].split(")")[0]
    assert "/Delete /TN *" not in text
    assert "wildcard" in text.lower()


def test_uninstall_missing_schtasks_delete_is_noop_under_ps51() -> None:
    """Bare `/Delete` under `$ErrorActionPreference=Stop` aborts PS 5.1.

    schtasks writes 'ERROR: The system cannot find the file specified.' to
    stderr when the task is absent; Windows PowerShell 5.1 turns that into a
    terminating NativeCommandError. The body must query first and relax Stop
    around the native calls (macOS twin: `launchctl bootout … || true`).
    """
    text = (_PS / "Uninstall-CyClaw.ps1").read_text(encoding="utf-8")
    body = text.split("function Unschedule-KnownTasks", 1)[1]
    body = body.split("Unschedule-SyncJob", 1)[0]
    assert "/Query" in body
    assert "cmd.exe" in body
    assert "ErrorActionPreference =" not in body
    assert "cannot find" in body
    assert "2>$null | Out-Null" not in body
    assert "exit 0" in text


def test_invoke_loads_persisted_api_key_from_dotenv() -> None:
    """Invoke loads non-secrets from .env and secrets from Credential Manager."""
    text = (_PS / "Invoke-CyClaw.ps1").read_text(encoding="utf-8")
    store = (_PS / "CyClaw-SecretStore.ps1").read_text(encoding="utf-8")
    install = (_PS / "Install-CyClaw.ps1").read_text(encoding="utf-8")
    uninstall = (_PS / "Uninstall-CyClaw.ps1").read_text(encoding="utf-8")
    assert 'Join-Path $Home_ ".env"' in text
    assert 'Join-Path $Repo ".env"' in text
    assert "Import-CyclawDotenv" in text
    assert "Import-CyclawCredentialSecrets" in text
    assert "Test-CyclawSecretName" in store
    assert "CyclawSecretTargets.ContainsKey" in store or "CyclawSecretTargets.ContainsKey($Name)" in store
    policy = (_REPO_ROOT / "utils" / "secret-policy.tsv").read_text(encoding="utf-8")
    assert "utils/secret-policy.tsv" in store
    assert "foreach ($suffix in $script:CyclawSecretSuffixes)" in store
    for suffix in ("API_KEY", "TOKEN", "SECRET", "PASSWORD", "DSN", "DB_URL", "PAT", "CREDENTIALS"):
        assert f"suffix\t{suffix}\t" in policy
    assert "Test-CyclawDotenvOwnerOnly" in store
    assert "WindowsIdentity" in store
    assert "GetCurrent().User" in store
    assert "SecurityIdentifier" in store
    assert "BUILTIN\\Users" not in store
    assert "FileSystemRights]::ReadData" not in store
    assert "(R,W)" in store
    assert "refusing to source" in store
    assert "ACL is not owner-only" in store
    assert "No backup was written" in store
    assert "Ensure-CyclawPublicEnvFile" in store
    assert "-WriteEnvFile" in install or "[switch]$WriteEnvFile" in install
    assert "Sync-CyclawPlaintextToCredentialManager" in install
    assert "Sync-CyclawPlaintextToCredentialManager" not in uninstall
    assert "Write-CyclawCredential" not in uninstall
    assert "Remove-CyclawPlaintextIfCredentialMatches" in uninstall
    assert "RemoveCredentials" in uninstall
    assert "$env:CYCLAW_REPO" not in uninstall
    assert "CredDelete" in store
    assert "StringComparison]::Ordinal" in store
    assert "Get-CyclawEnvLineAssignments" in store
    assert "source $Home_\\.env" not in text
    load_idx = text.index("Import-CyclawDotenv")
    cred_idx = text.index("Import-CyclawCredentialSecrets")
    start_idx = text.index("& $VenvPy gate.py")
    assert load_idx < cred_idx < start_idx
    warn = "Typing the key in the browser cannot configure the server"
    assert warn in text
    assert load_idx < text.index(warn)


def test_invoke_fallback_requires_python_312() -> None:
    """A missing %USERPROFILE%\\.CyClaw\\venv must not launch under any python."""
    text = (_PS / "Invoke-CyClaw.ps1").read_text(encoding="utf-8")
    fallback = text.split("if (-not (Test-Path $VenvPy)) {", 1)[1]
    fallback = fallback.split("$env:CYCLAW_HOME = $Home_", 1)[0]
    assert "py -3.12" in fallback
    assert 'print(sys.executable)' in fallback
    assert '$v -eq "3.12"' in fallback
    assert "no Python 3.12.x on PATH" in fallback
    assert "(Get-Command python -ErrorAction SilentlyContinue).Source" not in fallback


def test_invoke_starts_gate_through_main_not_bare_uvicorn() -> None:
    """Only gate.main() -> _serve() applies the loopback bind guard, api.tls
    certfile/keyfile, and proxy_headers=False; a bare `uvicorn gate:app` would
    serve plaintext with forwarded headers trusted (Codex review, PR #1367).
    The console URL comes from config.yaml (api.port, api.tls) with a fallback
    to the shipped default, and is resolved before it is printed or opened."""
    text = (_PS / "Invoke-CyClaw.ps1").read_text(encoding="utf-8")
    assert "& $VenvPy gate.py" in text
    assert "-m uvicorn" not in text
    assert "$Port" not in text
    probe_idx = text.index('"utils\\gateway_url.py"')
    assert "http://127.0.0.1:8787" in text  # fallback only
    assert probe_idx < text.index("[cyclaw] console : $Url")
    # The browser opens the probed URL (plus the one-time #pair= fragment).
    assert probe_idx < text.index("$OpenUrl = $Url")
    # Prefer $using: so PSUseUsingScopeModifierInNewRunspaces stays clean.
    assert "$using:OpenUrl" in text
    assert "Start-Job -ScriptBlock" in text


@pytest.mark.skipif(os.name != "nt", reason="requires Windows PowerShell")
def test_invoke_url_probe_honors_host_tls_and_environment_port(tmp_path: Path) -> None:
    powershell = shutil.which("powershell")
    if not powershell:
        pytest.skip("Windows PowerShell is unavailable")
    repo = tmp_path / "checkout with spaces"
    helper = repo / "utils" / "gateway_url.py"
    helper.parent.mkdir(parents=True)
    shutil.copyfile(_REPO_ROOT / "utils" / "gateway_url.py", helper)
    (repo / "config.yaml").write_text(
        'api:\n  host: 127.0.0.2\n  port: 9876\n  tls:\n    enabled: true\n', encoding="utf-8",
    )
    source = (_PS / "Invoke-CyClaw.ps1").read_text(encoding="utf-8")
    probe = source.split('$Url = & $VenvPy', 1)[1].split('$Url = "$Url".Trim()', 1)[0]
    script = tmp_path / "probe.ps1"
    script.write_text(
        'param([string]$Repo, [string]$VenvPy)\n$Url = & $VenvPy' + probe + '\nWrite-Output $Url\n',
        encoding="utf-8",
    )
    result = subprocess.run(
        [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
         "-Repo", str(repo), "-VenvPy", sys.executable],
        cwd=tmp_path, env={**os.environ, "CYCLAW_GATE_PORT": "8999"},
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "https://127.0.0.2:8999"


def test_installer_requires_explicit_flag_to_replace_existing_repo() -> None:
    """A stale %USERPROFILE%\\.CyClaw\\repo must not be silently Remove-Item'd."""
    text = (_PS / "Install-CyClaw.ps1").read_text(encoding="utf-8")
    assert "[switch]$ReplaceRepo" in text
    assert "re-run with -ReplaceRepo to overwrite it" in text
    assert "if (Test-Path $Repo) { Remove-Item -Recurse -Force $Repo }" not in text


@pytest.mark.skipif(os.name != "nt", reason="requires Windows PowerShell 5.1")
def test_installer_preserves_an_unusable_default_repo_without_replace_flag(tmp_path: Path) -> None:
    """Default clone path must fail closed before deleting existing data."""
    home = tmp_path / "operator"
    repo = home / ".CyClaw" / "repo"
    repo.mkdir(parents=True)
    sentinel = repo / "operator-data.txt"
    sentinel.write_text("keep me", encoding="utf-8")

    system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    powershell = system_root / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    if not powershell.is_file():
        pytest.skip("Windows PowerShell 5.1 is unavailable")

    env = os.environ.copy()
    env["USERPROFILE"] = str(home)
    result = subprocess.run(
        [
            str(powershell),
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(_PS / "Install-CyClaw.ps1"),
            "-SkipPythonDeps",
            "-NoProfileEdit",
            "-NoPathEdit",
        ],
        cwd=_REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert sentinel.read_text(encoding="utf-8") == "keep me"
    assert "-ReplaceRepo" in output


def test_credman_marshal_sites_carry_devskim_suppression() -> None:
    """GHAS DevSkim DS104456 flags Marshal/PtrToStructure as restricted.

    CredRead/CredWrite cannot be done fail-closed via cmdkey (argv leak).
    Each PowerShell Marshal / call-operator site must carry an inline ignore.
    """
    env_text = (_PS / "CyClaw-CredMan-Env.ps1").read_text(encoding="utf-8")
    set_text = (_PS / "CyClaw-CredMan-Set.ps1").read_text(encoding="utf-8")
    store_text = (_PS / "CyClaw-SecretStore.ps1").read_text(encoding="utf-8")
    for line in env_text.splitlines():
        if "InteropServices.Marshal" in line or "PtrToStructure" in line:
            assert "DevSkim: ignore DS104456" in line, line
    for blob in (set_text, store_text):
        for line in blob.splitlines():
            if "InteropServices.Marshal" in line or "PtrToStructure" in line or "Marshal.WriteByte" in line:
                assert "DevSkim: ignore DS104456" in line, line
    assert "Dispose()" in set_text
    assert not re.search(r"(?m)^\s*cmdkey\b", store_text, re.IGNORECASE)


def test_credman_set_ps7_ctrl_c_registers_cancel_keypress() -> None:
    """PS7 Ctrl+C must run the same wipe path as finally, then exit 130.

    Windows PowerShell 5.1 often skips finally on Ctrl+C. The handler is
    gated on PSVersion.Major -ge 7 so 5.1 cannot hang on e.Cancel=$true.
    """
    text = (_PS / "CyClaw-CredMan-Set.ps1").read_text(encoding="utf-8")
    assert "function Invoke-CyclawCredCleanup" in text
    assert "CancelKeyPress" in text
    assert "RegisterCancelHandler" in text
    assert "private static void HandleCancel" in text
    assert "$PSVersionTable.PSVersion.Major -ge 7" in text
    assert "eventArgs.Cancel = true" in text
    assert "Environment.Exit(130)" in text
    assert "Marshal.WriteByte" in text
    assert "Interlocked.Exchange" in text
    assert "UnregisterCancelHandler" in text
    assert "[ConsoleCancelEventHandler]{" not in text
    assert "Do not install this on Windows PowerShell" in text


def test_uninstall_and_setup_never_enable_writes_or_indexing() -> None:
    combined = "\n".join(
        (_PS / name).read_text(encoding="utf-8")
        for name in ("Setup-FsConnect.ps1", "Uninstall-CyClaw.ps1", "Install-CyClaw.ps1")
    )
    assert "writes_enabled: true" not in combined
    assert "index_enabled: true" not in combined
    assert "writes_enabled = $true" not in combined


def test_setup_fsconnect_is_prepare_only_safe() -> None:
    setup = (_PS / "Setup-FsConnect.ps1").read_text(encoding="utf-8")
    assert "PrepareOnly" in setup
    assert "_enable_fsconnect_readlist.py" in setup
    assert "CyClaw-FS" in setup
    assert "SetAccessRuleProtection" in setup


def test_credman_set_never_uses_cmdkey_pass() -> None:
    set_text = (_PS / "CyClaw-CredMan-Set.ps1").read_text(encoding="utf-8")
    env_text = (_PS / "CyClaw-CredMan-Env.ps1").read_text(encoding="utf-8")
    assert not re.search(r"(?m)^\s*cmdkey\b", set_text, re.IGNORECASE)
    assert not re.search(r"(?m)^\s*cmdkey\b", env_text, re.IGNORECASE)
    assert "CredWrite" in set_text
    assert "Read-Host" in set_text
    assert "AsSecureString" in set_text
    assert "CredRead" in env_text
    assert re.search(r"\s--\s", env_text) or '"--"' in env_text
    assert "IsInputRedirected" in set_text


def test_credman_env_validates_env_var_name() -> None:
    text = (_PS / "CyClaw-CredMan-Env.ps1").read_text(encoding="utf-8")
    assert r"^[A-Za-z_][A-Za-z0-9_]*$" in text


def test_remove_credentials_prompts_unless_yes() -> None:
    """-RemoveCredentials asks y/N; -Yes confirms that purge and nothing else."""
    text = (_PS / "Uninstall-CyClaw.ps1").read_text(encoding="utf-8")
    readme = (_PS / "README.md").read_text(encoding="utf-8")
    assert "[switch]$Yes" in text
    assert "if ($script:Yes)" in text
    assert "kept Credential Manager items" in text
    # The prompt's count and list come from the same policy-derived target set
    # the purge walks (utils/secret-policy.tsv), never a hard-coded number.
    targets = text.index("$credTargets = @($script:CyclawSecretTargets.Values")
    call = text.index('Confirm-CyclawDestructive "Delete these $($credTargets.Count) CyClaw Credential Manager items?"')
    kept = text.index("kept Credential Manager items")
    remove = text.index("Remove-CyclawCredential")
    assert targets < call < kept < remove
    assert "foreach ($credTarget in $credTargets)" in text[kept:]
    assert "five documented" not in text
    confirm = text.split("function Confirm-CyclawDestructive", 1)[1].split("\n}", 1)[0]
    assert confirm.index("if ($script:Yes)") < confirm.index("Read-Host")
    assert "(y/N)" in confirm
    home = text.split("# -- home directory", 1)[1]
    assert "$Yes" not in home
    assert "-Yes" in readme
    assert "y/N" in readme


def test_powershell_readme_documents_credman_and_known_task_names() -> None:
    readme = (_PS / "README.md").read_text(encoding="utf-8")
    assert "CyClaw-CredMan-Set.ps1" in readme
    assert "CyClaw-CredMan-Env.ps1" in readme
    assert "Setup-FsConnect.ps1" in readme
    assert "CyClaw Dropbox Sync" in readme
    assert "wildcard" in readme.lower()
    assert "never writes a credential" in readme
    assert "-RemoveCredentials" in readme


def test_env_line_parser_matches_the_shell_cases() -> None:
    """The PowerShell helper sees every assignment the shell helper sees."""
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        pytest.skip("pwsh is not installed")
    script = r"""
$ErrorActionPreference = 'Stop'
. ./powershell/CyClaw-SecretStore.ps1
function Dump([string]$Line) {
  foreach ($row in @(Get-CyclawEnvLineAssignments $Line)) {
    Write-Output ("{0}|{1}|{2}" -f $row.Name, $row.Op, $row.Value)
  }
}
Dump "FOO=1 BAR=2"
Dump "FOO+=suffix"
Dump "export FOO='a b'; GROK_API_KEY=secret"
Dump "declare -x FOO=1"
Dump "typeset FOO=1"
Dump "readonly FOO=1"
Dump "echo NAME=value"
$bom = [char]0xFEFF
Dump ($bom + "CYCLAW_GATE_PORT=8788")
Dump "FOO='abc'\''def'"
"""
    result = subprocess.run(
        [pwsh, "-NoProfile", "-Command", script],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "FOO|=|1",
        "BAR|=|2",
        "FOO|+=|suffix",
        "FOO|=|a b",
        "GROK_API_KEY|=|secret",
        "FOO|=|1",
        "FOO|=|1",
        "FOO|=|1",
        "CYCLAW_GATE_PORT|=|8788",
        "FOO|=|abc'def",
    ]
