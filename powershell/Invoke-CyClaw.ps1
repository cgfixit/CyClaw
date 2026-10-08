<#
.SYNOPSIS
  Launches the CyClaw RAG gateway (installed by Install-CyClaw.ps1).

.DESCRIPTION
  Windows 10/11 + Server 2019/2022, Windows PowerShell 5.1 or PowerShell 7+.

  Runs gate.py (gate.main(): loopback bind guard, api.tls certfile/keyfile,
  proxy_headers=False) on the host/port from config.yaml using the per-user venv
  under %USERPROFILE%\.CyClaw\venv and the repo at %CYCLAW_REPO% (or
  %USERPROFILE%\.CyClaw\repo), then opens the terminal console in the default
  browser. Ctrl+C stops the server.

.PARAMETER NoBrowser
  Do not open the browser; just serve.

.PARAMETER Repo
  Explicit path to the CyClaw checkout (overrides CYCLAW_REPO and the default).

.EXAMPLE
  cyclaw                 # via the installed shim / profile function
  .\Invoke-CyClaw.ps1 -NoBrowser
#>
[CmdletBinding()]
param(
    [switch]$NoBrowser,
    [string]$Repo = ""
)


function Write-CyClawHost {
    # Operator-facing console text for install/uninstall/launch scripts.
    # Write-Host (PowerShell 5.0+) writes to the information stream and is shown
    # whatever $InformationPreference says, so `*> install.log`, `6>&1` and
    # Start-Transcript all capture it. Writing to the console object directly
    # those streams and lost the messages from redirected logs. This is the one
    # sanctioned Write-Host call site, hence the scoped suppression.
    [Diagnostics.CodeAnalysis.SuppressMessageAttribute('PSAvoidUsingWriteHost', '', Justification='Single sanctioned wrapper: routes operator text through the information stream so it is redirectable, transcribed and always shown.')]
    [CmdletBinding()]
    param(
        [Parameter(Position = 0, ValueFromRemainingArguments = $true)]
        [object[]]$Object,
        [ConsoleColor]$ForegroundColor
    )
    $msg = (@($Object) | ForEach-Object { "$_" }) -join " "
    if ($PSBoundParameters.ContainsKey("ForegroundColor")) {
        Write-Host $msg -ForegroundColor $ForegroundColor
    } else {
        Write-Host $msg
    }
}

$ErrorActionPreference = "Stop"

$Home_ = if ($env:CYCLAW_HOME) { $env:CYCLAW_HOME } else { Join-Path $env:USERPROFILE ".CyClaw" }
if ($Repo -eq "") {
    $Repo = if ($env:CYCLAW_REPO) { $env:CYCLAW_REPO } else { Join-Path $Home_ "repo" }
}
$VenvPy = Join-Path $Home_ "venv\Scripts\python.exe"

if (-not (Test-Path (Join-Path $Repo "gate.py"))) {
    throw "CyClaw repo not found at '$Repo'. Run Install-CyClaw.ps1 first (or pass -Repo)."
}
if (-not (Test-Path $VenvPy)) {
    # Same 3.12 gate as Install-CyClaw.ps1. A generic `python` on PATH is
    # often the Store stub or 3.11/3.13; CyClaw requires 3.12.
    $fallback = $null
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        $exe = & py -3.12 -c "import sys; print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $exe) { $fallback = "$exe".Trim() }
    }
    if (-not $fallback) {
        $python = Get-Command python -ErrorAction SilentlyContinue
        if ($python) {
            $v = & python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
            if ($LASTEXITCODE -eq 0 -and $v -eq "3.12") { $fallback = $python.Source }
        }
    }
    if (-not $fallback) {
        throw "No venv at $Home_\venv and no Python 3.12.x on PATH. Re-run Install-CyClaw.ps1."
    }
    $VenvPy = $fallback
}

$env:CYCLAW_HOME = $Home_
$env:CYCLAW_REPO = $Repo
# Non-secret dotenv settings, then Credential Manager into THIS process.
# Secret lines in .env are ignored. Browser paste cannot set the server env.
# Darwin twin: macos/invoke-cyclaw.sh + macos/cyclaw-keychain-load.sh.
$secretStore = Join-Path $PSScriptRoot "CyClaw-SecretStore.ps1"
if (-not (Test-Path -LiteralPath $secretStore)) {
    $secretStore = Join-Path $Repo "powershell\CyClaw-SecretStore.ps1"
}
if (-not (Test-Path -LiteralPath $secretStore)) {
    throw "CyClaw-SecretStore.ps1 not found beside the launcher or in $Repo\powershell"
}
. $secretStore

# Chained on the result, not existence: a refused HOME file must not shadow the repo copy.
$homeEnv = Join-Path $Home_ ".env"
$repoEnv = Join-Path $Repo ".env"
if (-not (Import-CyclawDotenv $homeEnv)) {
    Import-CyclawDotenv $repoEnv | Out-Null
}
Import-CyclawCredentialSecrets
Write-CyclawPlaintextSecretWarning $homeEnv
Write-CyclawPlaintextSecretWarning $repoEnv

# Follow api.host/api.tls and gate.main()'s CYCLAW_GATE_PORT override. A probe
# failure keeps the shipped default rather than blocking gateway startup.
$Url = & $VenvPy (Join-Path $Repo "utils\gateway_url.py") (Join-Path $Repo "config.yaml") 2>$null
if ($LASTEXITCODE -ne 0 -or -not $Url) { $Url = "http://127.0.0.1:8787" }
$Url = "$Url".Trim()

Write-CyClawHost "[cyclaw] repo    : $Repo" -ForegroundColor Cyan
Write-CyClawHost "[cyclaw] home    : $Home_" -ForegroundColor Cyan
Write-CyClawHost "[cyclaw] console : $Url  (Ctrl+C to stop)" -ForegroundColor Cyan
# First run on this machine: no key in Credential Manager yet. Generate one
# (20 random bytes as hex, the shape macos/setup-cyclaw-keys.sh makes with
# `openssl rand -hex 20`) and store it, so the gateway does not start keyless.
# Write-CyclawCredential takes it in memory; it is never an argv token.
if (-not $env:CYCLAW_API_KEY -and (Test-CyclawWindowsHost)) {
    $keyBytes = New-Object byte[] 20
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($keyBytes) } finally { $rng.Dispose() }
    $newKey = -join ($keyBytes | ForEach-Object { $_.ToString("x2") })
    if (Write-CyclawCredential "com.cgfixit.cyclaw.api-key" $newKey) {
        $env:CYCLAW_API_KEY = $newKey
        Write-CyClawHost "[cyclaw] key     : generated CYCLAW_API_KEY and stored it in Credential Manager (target com.cgfixit.cyclaw.api-key)" -ForegroundColor Cyan
    }
    $newKey = $null
}

if (-not $env:CYCLAW_API_KEY) {
    Write-CyClawHost "[cyclaw] warn    : CYCLAW_API_KEY is not in Credential Manager (target com.cgfixit.cyclaw.api-key) and was not already set. Soul / ops state-changing routes will 401. Typing the key in the browser cannot configure the server. This launcher does not read that secret from .env." -ForegroundColor Yellow
}

if (-not $NoBrowser) {
    # One-time pairing code: the browser opens at #pair=<code> and trades it
    # for the console cookie, so operator tools are unlocked without the key
    # ever reaching the page (utils/console_session.py). gate.py inherits the
    # code below and takes it out of its own environment at import.
    $OpenUrl = $Url
    if ($env:CYCLAW_API_KEY) {
        $pairBytes = New-Object byte[] 24
        $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
        try { $rng.GetBytes($pairBytes) } finally { $rng.Dispose() }
        $pairCode = [Convert]::ToBase64String($pairBytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
        $env:CYCLAW_CONSOLE_PAIRING_CODE = $pairCode
        $OpenUrl = $Url.TrimEnd('/') + "/#pair=" + $pairCode
    }
    # Open the browser slightly after the server starts; the page retries
    # until the API answers, so a race here is harmless.
    Start-Job -ScriptBlock {
        Start-Sleep -Seconds 2
        Start-Process $using:OpenUrl
    } | Out-Null
}

Push-Location $Repo
try {
    # Canonical telemetry/update-check block, set in THIS process so the
    # gateway (and every child it spawns) inherits it before any interpreter
    # starts. Single source of truth: utils/telemetry_kill.py renders the
    # lines; nothing here hand-copies a key. Positioned after the .env import
    # above so canonical values overwrite any hostile dotenv value, mirroring
    # apply_telemetry_kill()'s own overwrite semantics. Non-fatal on failure:
    # every entry point re-applies the block at import anyway. Note this
    # cannot un-send THIS PowerShell host's own startup telemetry -- pwsh
    # reads POWERSHELL_TELEMETRY_OPTOUT once, at its own launch, which is why
    # the cmd shim written by Install-CyClaw.ps1 sets it before powershell
    # starts.
    # Parsed as DATA, never executed: only two rigid line shapes act (a
    # set-literal and a remove-literal over a validated env-var name), so a
    # compromised or garbled export cannot inject code the way piping it to
    # Invoke-Expression could (DevSkim DS104456).
    # -S -E: no site init in the helper interpreter (a venv sitecustomize/.pth
    # hook must not fire before the module emits the safe values) and no
    # ambient PYTHONPATH; the module is stdlib-only and repo-local.
    $killLines = & $VenvPy -S -E -m utils.telemetry_kill --export powershell 2>$null
    if ($LASTEXITCODE -eq 0 -and $killLines) {
        foreach ($line in @($killLines)) {
            if ($line -match "^\`$env:([A-Za-z_][A-Za-z0-9_]*) = '(.*)'$") {
                Set-Item -Path ("Env:" + $Matches[1]) -Value $Matches[2]
            } elseif ($line -match "^Remove-Item -ErrorAction SilentlyContinue Env:([A-Za-z_][A-Za-z0-9_]*)$") {
                Remove-Item -ErrorAction SilentlyContinue -Path ("Env:" + $Matches[1])
            }
        }
    } else {
        Write-CyClawHost "[cyclaw] warn    : could not export telemetry-kill block (children still self-apply at import)" -ForegroundColor Yellow
    }
    # gate.py, not `uvicorn gate:app`: only main() -> _serve() applies the
    # loopback bind guard, api.tls certfile/keyfile, and proxy_headers=False
    # (Codex review on PR #1367).
    & $VenvPy gate.py
}
finally {
    Pop-Location
}
