<#
.SYNOPSIS
  Removes the CyClaw integration from the current user's environment.

.DESCRIPTION
  Windows 10/11 + Server 2019/2022, Windows PowerShell 5.1 or PowerShell 7+.
  Removes the `cyclaw` profile function and the %USERPROFILE%\.CyClaw\bin PATH
  entry. The home directory (sessions, venv, repo clone) is KEPT by default so
  no data is lost; pass -RemoveHome to delete it (prompts first).

.PARAMETER RemoveFsConnect
  Prompt before deleting %USERPROFILE%\CyClaw-FS (the confined read jail).

.PARAMETER RemoveCredentials
  Delete every CyClaw Credential Manager target named in utils/secret-policy.tsv
  (the prompt lists them and their count). Prompts y/N unless
  -Yes is also passed (the macOS twin is --remove-keychain / --yes). Plaintext
  lines are left in place so the purge is not also the only copy. This switch
  never writes a credential. Without it, uninstall only removes a plaintext
  line whose value matches the item already stored.

.PARAMETER Yes
  Confirm -RemoveCredentials without a prompt. Does not by itself delete
  credentials, the home directory, or the fsconnect jail.

.EXAMPLE
  .\Uninstall-CyClaw.ps1              # keep ~/.CyClaw data w/ uninstall
  .\Uninstall-CyClaw.ps1 -RemoveHome  # also delete ~/.CyClaw
  .\Uninstall-CyClaw.ps1 -RemoveFsConnect
  .\Uninstall-CyClaw.ps1 -RemoveCredentials
  .\Uninstall-CyClaw.ps1 -RemoveCredentials -Yes
#>
[CmdletBinding()]
param(
    [switch]$RemoveHome,
    [switch]$RemoveFsConnect,
    [switch]$RemoveCredentials,
    [switch]$Yes
)

$ErrorActionPreference = "Stop"
$Home_ = Join-Path $env:USERPROFILE ".CyClaw"
$Bin   = Join-Path $Home_ "bin"
$FsConnectDir = Join-Path $env:USERPROFILE "CyClaw-FS"

# Known Task Scheduler names CyClaw generators / sync.cli own. Never a
# wildcard delete — only these exact /TN values. The gate name is listed so
# a generated (never auto-registered) listener cannot outlive uninstall if
# the operator did load it by hand; "CyClaw harness" is the retired coding
# console's task name, kept so an older install's task is still removed.
$KnownTaskNames = @(
    "CyClaw Dropbox Sync",
    "CyClaw fsconnect-trash",
    "CyClaw telegram-poll",
    "CyClaw telegram-health",
    "CyClaw gate",
    "CyClaw harness",
    "CyClaw opentweet"
)

function Unschedule-SyncJob {
    $py = Join-Path $Home_ "venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $py)) {
        $cmd = Get-Command python -ErrorAction SilentlyContinue
        if ($cmd) { $py = $cmd.Source } else { return }
    }
    $cfg = Join-Path $Home_ "repo\config.yaml"
    if (-not (Test-Path -LiteralPath $cfg)) { return }
    Write-Host "[cyclaw] checking for a registered sync schedule..."
    $repo = Join-Path $Home_ "repo"
    Push-Location $repo
    try {
        & $py -m sync.cli --config $cfg unschedule  # DevSkim: ignore DS104456 — call operator, not IEX
        if ($LASTEXITCODE -ne 0) {
            Write-Host "[cyclaw] WARNING: could not clean up the sync schedule; remove it manually with 'python -m sync.cli unschedule' if needed" -ForegroundColor Yellow
        }
    } catch {
        Write-Host "[cyclaw] WARNING: could not clean up the sync schedule; remove it manually with 'python -m sync.cli unschedule' if needed" -ForegroundColor Yellow
    } finally {
        Pop-Location
    }
}

function Unschedule-KnownTasks {
    $schtasks = Get-Command schtasks.exe -ErrorAction SilentlyContinue
    if (-not $schtasks) { return }
    foreach ($name in $KnownTaskNames) {
        Write-Host "[cyclaw] checking scheduled task '$name'..."
        # Route through cmd.exe with inner stdout/stderr discarded so
        # Windows PowerShell 5.1 cannot wrap schtasks stderr as a
        # terminating NativeCommandError ("ERROR: The system cannot find
        # the file specified."). Missing task is a no-op (macOS twin:
        # launchctl bootout … || true). Names are a fixed literal list.
        # Do not flip $ErrorActionPreference — it leaks into the caller
        # when GitHub Actions dot-sources the CI wrapper.
        $safeName = $name.Replace('"', '')
        cmd.exe /c "schtasks.exe /Query /TN `"$safeName`" >NUL 2>&1" | Out-Null
        if ($LASTEXITCODE -ne 0) { continue }
        cmd.exe /c "schtasks.exe /Delete /TN `"$safeName`" /F >NUL 2>&1" | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Write-Host "[cyclaw] WARNING: could not delete scheduled task '$name'; remove it manually with schtasks /Delete /TN '$name' /F if needed" -ForegroundColor Yellow
        }
    }
}

Unschedule-SyncJob
Unschedule-KnownTasks

function Confirm-CyclawDestructive([string]$Prompt) {
    # -Yes confirms an already-requested destructive switch. It does not
    # invent one. Empty input is N, matching macos/uninstall-cyclaw.sh.
    if ($Yes) { return $true }
    $answer = Read-Host "$Prompt (y/N)"
    return ($answer -eq "y" -or $answer -eq "Y")
}

# Never write Credential Manager during uninstall. -RemoveCredentials purges
# every target named in secret-policy.tsv only after a y/N prompt (or -Yes) that
# lists them, and skips the plaintext strip, so both copies are not destroyed
# together. Otherwise a line is removed only when the stored value matches.
# Scope is the home dotenv and the install layout %USERPROFILE%\.CyClaw\repo
# dotenv. The checkout environment variable is not followed.
$secretStore = Join-Path $PSScriptRoot "CyClaw-SecretStore.ps1"
if (Test-Path -LiteralPath $secretStore) {
    . $secretStore
    if ($RemoveCredentials) {
        Write-Host "[cyclaw] -RemoveCredentials: leaving plaintext secret lines in place so the Credential Manager purge is not also the only copy."
        # Target names only (never a secret value), derived from the same
        # policy file the purge walks, so the prompt can't drift from it.
        $credTargets = @($script:CyclawSecretTargets.Values | Where-Object { $_ } | Sort-Object -Unique)
        Write-Host "[cyclaw] -RemoveCredentials targets these $($credTargets.Count) Credential Manager items:"
        foreach ($credTarget in $credTargets) { Write-Host "[cyclaw]   $credTarget" }
        if (-not (Confirm-CyclawDestructive "Delete these $($credTargets.Count) CyClaw Credential Manager items?")) {
            Write-Host "[cyclaw] kept Credential Manager items"
        } elseif (Test-CyclawWindowsHost) {
            foreach ($credTarget in $credTargets) {
                if (Remove-CyclawCredential $credTarget) {
                    Write-Host "[cyclaw] removed Credential Manager item $credTarget"
                }
            }
        } else {
            Write-Host "[cyclaw] WARNING: -RemoveCredentials is a no-op off Windows." -ForegroundColor Yellow
        }
    } else {
        $repoForEnv = Join-Path $Home_ "repo"
        Remove-CyclawPlaintextIfCredentialMatches -HomeDir $Home_ -RepoDir $repoForEnv
    }
}

# -- profile block --------------------------------------------------------------
$Marker = "# >>> cyclaw harness >>>"
if (Test-Path $PROFILE.CurrentUserAllHosts) {
    $text = Get-Content $PROFILE.CurrentUserAllHosts -Raw
    if ($text -match [regex]::Escape($Marker)) {
        $pattern = "(?s)\r?\n?" + [regex]::Escape($Marker) + ".*?# <<< cyclaw harness <<<"
        $cleaned = [regex]::Replace($text, $pattern, "")
        Set-Content -Path $PROFILE.CurrentUserAllHosts -Value $cleaned -Encoding UTF8
        Write-Host "[cyclaw] removed profile function from $($PROFILE.CurrentUserAllHosts)"
    }
}

# -- PATH entry -------------------------------------------------------------------
$UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($UserPath -and (($UserPath -split ";") -contains $Bin)) {
    $entries = $UserPath -split ";" | Where-Object { $_ -ne $Bin -and $_ -ne "" }
    [Environment]::SetEnvironmentVariable("Path", ($entries -join ";"), "User")
    Write-Host "[cyclaw] removed $Bin from the user PATH"
}

# -- home directory -----------------------------------------------------------------
if ($RemoveHome -and (Test-Path $Home_)) {
    $answer = Read-Host "Delete $Home_ including all sessions and the venv? (y/N)"
    if ($answer -eq "y" -or $answer -eq "Y") {
        Remove-Item -Recurse -Force $Home_
        Write-Host "[cyclaw] removed $Home_"
    }
    else {
        Write-Host "[cyclaw] kept $Home_"
    }
}

if ($RemoveFsConnect -and (Test-Path -LiteralPath $FsConnectDir)) {
    $fsItem = Get-Item -LiteralPath $FsConnectDir -Force
    $expected = Join-Path $env:USERPROFILE "CyClaw-FS"
    if (($fsItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -or ($FsConnectDir -ne $expected)) {
        Write-Host "[cyclaw] WARNING: refusing unexpected fsconnect target: $FsConnectDir" -ForegroundColor Yellow
        exit 1
    }
    $answer = Read-Host "Delete $FsConnectDir and every file in the fsconnect jail? (y/N)"
    if ($answer -eq "y" -or $answer -eq "Y") {
        Remove-Item -LiteralPath $FsConnectDir -Recurse -Force
        Write-Host "[cyclaw] removed $FsConnectDir (config remains fail-closed until setup is rerun)"
    }
    else {
        Write-Host "[cyclaw] kept $FsConnectDir"
    }
}
elseif (-not $RemoveFsConnect -and (Test-Path -LiteralPath $FsConnectDir)) {
    Write-Host "[cyclaw] kept $FsConnectDir (pass -RemoveFsConnect to remove it)"
}

Write-Host "[cyclaw] uninstall complete."
# Explicit success: the last native schtasks query of a missing name leaves
# $LASTEXITCODE=1. GitHub Actions' Windows PowerShell wrapper uses that as
# the step exit code even when this script otherwise completed.
exit 0
