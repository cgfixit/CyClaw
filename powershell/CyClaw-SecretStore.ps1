<#
.SYNOPSIS
  Credential Manager access and dotenv handling for the Windows launcher.

.DESCRIPTION
  Dot-sourced by Invoke-CyClaw.ps1, Install-CyClaw.ps1, and Uninstall-CyClaw.ps1.
  ~/.CyClaw/.env stays the home for ordinary settings (ports, paths, mode
  flags, model names, feature toggles). Secret-classified names are not
  imported. A name is secret when it is on the allowlist below, or when it
  ends in _API_KEY, _TOKEN, _SECRET, or _PASSWORD. Allowlisted secrets are
  read from Credential Manager into the CyClaw process only, and removed
  from an existing .env after a confirmed copy. No backup is written.
  Values are never printed. A pattern match with no Credential Manager
  target is left in the file.

  Windows PowerShell 5.1 and PowerShell 7+. Not a launcher.
#>

$script:CyclawSecretTargets = @{
    CYCLAW_API_KEY     = "com.cgfixit.cyclaw.api-key"
    TELEGRAM_BOT_TOKEN = "com.cgfixit.cyclaw.telegram-bot-token"
    GROK_API_KEY       = "com.cgfixit.cyclaw.grok-api-key"
    ANTHROPIC_API_KEY  = "com.cgfixit.cyclaw.anthropic-api-key"
    GH_TOKEN           = "com.cgfixit.cyclaw.gh-token"
    GITHUB_TOKEN       = "com.cgfixit.cyclaw.gh-token"
    # Scrubbed so an old file cannot export it. llm/client.py does not read it.
    # Empty target: not copied into Credential Manager.
    CLAUDE_API_KEY     = ""
}

# Allowlist (hashtable above) OR suffix *_API_KEY / *_TOKEN / *_SECRET / *_PASSWORD.
function Test-CyclawSecretName([string]$Name) {
    if ([string]::IsNullOrEmpty($Name)) { return $false }
    if ($script:CyclawSecretTargets.ContainsKey($Name)) { return $true }
    if ($Name -like '*_API_KEY' -or $Name -like '*_TOKEN' -or $Name -like '*_SECRET' -or $Name -like '*_PASSWORD') {
        return $true
    }
    return $false
}

$script:CyclawPublicEnvHeader = @(
    '# CyClaw non-secret settings.',
    '# Ports, paths, mode flags, model names, and feature toggles belong here.',
    '# Secret-classified names do not: the allowlist in CyClaw-SecretStore.ps1,',
    '# plus any name ending in _API_KEY, _TOKEN, _SECRET, or _PASSWORD.',
    '# Those are read from Credential Manager when cyclaw starts.'
)

function Test-CyclawWindowsHost {
    return ([Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT)
}

function Test-CyclawDotenvOwnerOnly([string]$Path) {
    try {
        $acl = Get-Acl -LiteralPath $Path
        $me = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
    } catch {
        return $false
    }
    if (-not $me) { return $false }
    $allowCount = 0
    foreach ($ace in $acl.Access) {
        if ($ace.AccessControlType -ne 'Allow') { continue }
        $allowCount++
        try {
            $sid = $ace.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier])
        } catch {
            return $false
        }
        if ($sid -ne $me) { return $false }
    }
    return ($allowCount -gt 0)
}

function Import-CyclawDotenv([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return $false }
    if (-not (Test-CyclawDotenvOwnerOnly $Path)) {
        Write-Host "[cyclaw] warn    : refusing to source $Path (ACL is not owner-only; want current-user only). Fix with: icacls `"$Path`" /inheritance:r /grant:r `"${env:USERNAME}:(R,W)`"" -ForegroundColor Yellow
        return $false
    }
    Get-Content -LiteralPath $Path | ForEach-Object {
        $line = $_.Trim()
        if ($line -eq '' -or $line.StartsWith('#')) { return }
        if ($line.StartsWith('export ')) { $line = $line.Substring(7).Trim() }
        $eq = $line.IndexOf('=')
        if ($eq -lt 1) { return }
        $name = $line.Substring(0, $eq).Trim()
        if ($name -notmatch '^[A-Za-z_][A-Za-z0-9_]*$') { return }
        # Secret-classified names stay out of this process. Credential Manager is the source.
        if (Test-CyclawSecretName $name) { return }
        $val = $line.Substring($eq + 1).Trim()
        if ($val.Length -ge 2 -and (($val.StartsWith("'") -and $val.EndsWith("'")) -or ($val.StartsWith('"') -and $val.EndsWith('"')))) {
            $val = $val.Substring(1, $val.Length - 2).Replace("'\''", "'")
        }
        Set-Item -Path ("Env:" + $name) -Value $val
    }
    return $true
}

function Initialize-CyclawSecretStoreNative {
    if (-not (Test-CyclawWindowsHost)) { return }
    if ('CyClawSecretStoreNative' -as [type]) { return }
    Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;

public static class CyClawSecretStoreNative {
    public const int CRED_TYPE_GENERIC = 1;
    public const int CRED_PERSIST_LOCAL_MACHINE = 2;

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    public struct CREDENTIAL {
        public int Flags;
        public int Type;
        public string TargetName;
        public string Comment;
        public System.Runtime.InteropServices.ComTypes.FILETIME LastWritten;
        public int CredentialBlobSize;
        public IntPtr CredentialBlob;
        public int Persist;
        public int AttributeCount;
        public IntPtr Attributes;
        public string TargetAlias;
        public string UserName;
    }

    [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern bool CredRead(string target, int type, int flags, out IntPtr credentialPtr);

    [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern bool CredWrite(ref CREDENTIAL credential, int flags);

    [DllImport("advapi32.dll", SetLastError = true)]
    public static extern void CredFree(IntPtr buffer);
}
"@
}

function Read-CyclawCredential([string]$Target) {
    # Status: missing, readable, empty, error. Secret is set only for readable.
    $result = New-Object psobject -Property @{ Status = "error"; Secret = $null; Win32 = 0 }
    if (-not (Test-CyclawWindowsHost)) {
        $result.Status = "error"
        return $result
    }
    Initialize-CyclawSecretStoreNative
    $credPtr = [IntPtr]::Zero
    try {
        $ok = [CyClawSecretStoreNative]::CredRead($Target, [CyClawSecretStoreNative]::CRED_TYPE_GENERIC, 0, [ref]$credPtr)
        if (-not $ok) {
            $err = [Runtime.InteropServices.Marshal]::GetLastWin32Error()  # DevSkim: ignore DS104456 — CredRead last-error; not a secret
            $result.Win32 = $err
            # 1168 ERROR_NOT_FOUND, 2 ERROR_FILE_NOT_FOUND: the item is absent.
            if ($err -eq 1168 -or $err -eq 2) { $result.Status = "missing" } else { $result.Status = "error" }
            return $result
        }
        $cred = [Runtime.InteropServices.Marshal]::PtrToStructure($credPtr, [type][CyClawSecretStoreNative+CREDENTIAL])  # DevSkim: ignore DS104456 — CredRead CREDENTIAL; not shellcode
        if ($cred.CredentialBlob -eq [IntPtr]::Zero -or $cred.CredentialBlobSize -le 0) {
            $result.Status = "empty"
            return $result
        }
        $result.Secret = [Runtime.InteropServices.Marshal]::PtrToStringUni($cred.CredentialBlob, [int]($cred.CredentialBlobSize / 2))  # DevSkim: ignore DS104456 — CredRead blob; caller wipes it
        if ([string]::IsNullOrEmpty($result.Secret)) { $result.Status = "empty" } else { $result.Status = "readable" }
        return $result
    } finally {
        if ($credPtr -ne [IntPtr]::Zero) {
            [CyClawSecretStoreNative]::CredFree($credPtr)
        }
    }
}

function Write-CyclawCredential([string]$Target, [string]$Secret) {
    if ([string]::IsNullOrEmpty($Secret)) { return $false }
    Initialize-CyclawSecretStoreNative
    $secure = New-Object System.Security.SecureString
    $bstr = [IntPtr]::Zero
    $blob = [IntPtr]::Zero
    $blobSize = 0
    try {
        foreach ($ch in $Secret.ToCharArray()) { $secure.AppendChar($ch) }
        $secure.MakeReadOnly()
        $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)  # DevSkim: ignore DS104456 — in-memory secret to CredWrite; never argv
        $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)  # DevSkim: ignore DS104456 — BSTR to CredWrite bytes; wiped below
        $bytes = [Text.Encoding]::Unicode.GetBytes($plain)
        $plain = $null
        $blobSize = $bytes.Length
        $blob = [Runtime.InteropServices.Marshal]::AllocHGlobal($blobSize)  # DevSkim: ignore DS104456 — CredWrite blob
        [Runtime.InteropServices.Marshal]::Copy($bytes, 0, $blob, $blobSize)  # DevSkim: ignore DS104456 — copy into CredWrite blob
        for ($i = 0; $i -lt $bytes.Length; $i++) { $bytes[$i] = 0 }
        $cred = New-Object CyClawSecretStoreNative+CREDENTIAL
        $cred.Type = [CyClawSecretStoreNative]::CRED_TYPE_GENERIC
        $cred.TargetName = $Target
        $cred.UserName = $env:USERNAME
        $cred.CredentialBlobSize = $blobSize
        $cred.CredentialBlob = $blob
        $cred.Persist = [CyClawSecretStoreNative]::CRED_PERSIST_LOCAL_MACHINE
        $cred.Comment = "CyClaw secret; read only via CyClaw-SecretStore / CyClaw-CredMan-Env"
        if (-not [CyClawSecretStoreNative]::CredWrite([ref]$cred, 0)) {
            $err = [Runtime.InteropServices.Marshal]::GetLastWin32Error()  # DevSkim: ignore DS104456 — CredWrite last-error; not a secret
            Write-Host "[cyclaw] WARNING: CredWrite failed for target $Target (win32=$err). Plaintext line left in place." -ForegroundColor Yellow
            return $false
        }
        return $true
    } finally {
        if ($blob -ne [IntPtr]::Zero) {
            for ($i = 0; $i -lt $blobSize; $i++) {
                [Runtime.InteropServices.Marshal]::WriteByte($blob, $i, 0)  # DevSkim: ignore DS104456 — zero CredWrite blob before FreeHGlobal
            }
            [Runtime.InteropServices.Marshal]::FreeHGlobal($blob)  # DevSkim: ignore DS104456 — free zeroed CredWrite blob
        }
        if ($bstr -ne [IntPtr]::Zero) {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)  # DevSkim: ignore DS104456 — zero CredWrite BSTR
        }
        if ($secure) { $secure.Dispose() }
    }
}

function Import-CyclawCredentialSecrets {
    if (-not (Test-CyclawWindowsHost)) {
        Write-Host "[cyclaw] warn    : Credential Manager is unavailable. Plaintext .env secrets are not used." -ForegroundColor Yellow
        if (-not $env:CYCLAW_API_KEY) {
            Write-Host "[cyclaw] warn    : CYCLAW_API_KEY is unset. Soul / ops state-changing routes will 401. Typing the key in the browser cannot configure the server." -ForegroundColor Yellow
        }
        return
    }
    $failed = $false
    foreach ($name in @("CYCLAW_API_KEY", "TELEGRAM_BOT_TOKEN", "GROK_API_KEY", "ANTHROPIC_API_KEY", "GH_TOKEN")) {
        if ([Environment]::GetEnvironmentVariable($name)) { continue }
        $target = $script:CyclawSecretTargets[$name]
        $read = Read-CyclawCredential $target
        if ($read.Status -eq "missing") {
            $read.Secret = $null
            continue
        }
        if ($read.Status -eq "readable") {
            Set-Item -Path ("Env:" + $name) -Value $read.Secret
            $read.Secret = $null
            continue
        }
        $read.Secret = $null
        Write-Host "[cyclaw] error   : Credential Manager item for $name (target $target) is $($read.Status) (win32=$($read.Win32)). Not falling back to .env." -ForegroundColor Red
        $failed = $true
    }
    if ($env:GH_TOKEN -and -not $env:GITHUB_TOKEN) {
        $env:GITHUB_TOKEN = $env:GH_TOKEN
    }
    if ($failed) {
        throw "cyclaw: Credential Manager secret could not be read. The gateway was not started."
    }
    if (-not $env:CYCLAW_API_KEY) {
        Write-Host "[cyclaw] warn    : CYCLAW_API_KEY is not in Credential Manager (target com.cgfixit.cyclaw.api-key) and was not already set. Soul / ops state-changing routes will 401. Typing the key in the browser cannot configure the server. This launcher does not read that secret from .env." -ForegroundColor Yellow
    }
}

function Get-CyclawDotenvAssignments([string]$Path) {
    # Name -> value. Caller must not print values.
    $map = @{}
    if (-not (Test-Path -LiteralPath $Path)) { return $map }
    foreach ($raw in @(Get-Content -LiteralPath $Path)) {
        $line = $raw.Trim()
        if ($line -eq '' -or $line.StartsWith('#')) { continue }
        if ($line.StartsWith('export ')) { $line = $line.Substring(7).Trim() }
        $eq = $line.IndexOf('=')
        if ($eq -lt 1) { continue }
        $name = $line.Substring(0, $eq).Trim()
        if ($name -notmatch '^[A-Za-z_][A-Za-z0-9_]*$') { continue }
        $val = $line.Substring($eq + 1).Trim()
        if ($val.Length -ge 2 -and (($val.StartsWith("'") -and $val.EndsWith("'")) -or ($val.StartsWith('"') -and $val.EndsWith('"')))) {
            $val = $val.Substring(1, $val.Length - 2).Replace("'\''", "'")
        }
        $map[$name] = $val
    }
    return $map
}

function Remove-CyclawSecretLines([string]$Path, [string[]]$Names) {
    if (-not (Test-Path -LiteralPath $Path)) { return }
    if (-not $Names -or $Names.Count -eq 0) { return }
    $kept = New-Object System.Collections.Generic.List[string]
    $removed = New-Object System.Collections.Generic.List[string]
    $assignLeft = $false
    foreach ($raw in @(Get-Content -LiteralPath $Path)) {
        $line = $raw.Trim()
        $body = $line
        if ($body.StartsWith('export ')) { $body = $body.Substring(7).Trim() }
        $eq = $body.IndexOf('=')
        $drop = $false
        if ($eq -gt 0 -and -not $line.StartsWith('#')) {
            $n = $body.Substring(0, $eq).Trim()
            if ($Names -contains $n) {
                $drop = $true
                if (-not $removed.Contains($n)) { $removed.Add($n) }
            } elseif ($n -match '^[A-Za-z_][A-Za-z0-9_]*$') {
                $assignLeft = $true
            }
        }
        if (-not $drop) { $kept.Add($raw) }
    }
    if ($removed.Count -eq 0) { return }
    if (-not $assignLeft) {
        # Keep the file. Comments stay. An empty remainder gets the public header.
        $nonblank = $false
        foreach ($line in $kept) {
            if (-not [string]::IsNullOrWhiteSpace($line)) { $nonblank = $true; break }
        }
        if (-not $nonblank) {
            $kept = New-Object System.Collections.Generic.List[string]
            foreach ($headerLine in $script:CyclawPublicEnvHeader) { $kept.Add($headerLine) }
        }
    }
    Set-Content -LiteralPath $Path -Value $kept.ToArray() -Encoding UTF8
    # A rewrite inherits a broader ACL. Put it back to the current user.
    # .NET, not icacls: Windows PowerShell 5.1 treats native stderr as terminating.
    try {
        $acl = Get-Acl -LiteralPath $Path
        $acl.SetAccessRuleProtection($true, $false)
        foreach ($ace in @($acl.Access)) { [void]$acl.RemoveAccessRule($ace) }
        $me = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
        $rule = New-Object System.Security.AccessControl.FileSystemAccessRule($me, "Modify", "Allow")
        $acl.AddAccessRule($rule)
        Set-Acl -LiteralPath $Path -AclObject $acl
    } catch {
        Write-Host "[cyclaw] WARNING: could not restrict the ACL on $Path after removing secret lines." -ForegroundColor Yellow
    }
    Write-Host "[cyclaw] removed plaintext $($removed -join ', ') from $Path (Credential Manager holds it). No backup was written."
}

function Ensure-CyclawPublicEnvFile([string]$Path) {
    if ([string]::IsNullOrEmpty($Path)) { return }
    if (Test-Path -LiteralPath $Path) { return }
    $dir = Split-Path -Parent $Path
    if ($dir -and -not (Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
    Set-Content -LiteralPath $Path -Value $script:CyclawPublicEnvHeader -Encoding UTF8
    if (-not (Test-CyclawWindowsHost)) { return }
    try {
        $acl = Get-Acl -LiteralPath $Path
        $acl.SetAccessRuleProtection($true, $false)
        foreach ($ace in @($acl.Access)) { [void]$acl.RemoveAccessRule($ace) }
        $me = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
        $rule = New-Object System.Security.AccessControl.FileSystemAccessRule($me, "Modify", "Allow")
        $acl.AddAccessRule($rule)
        Set-Acl -LiteralPath $Path -AclObject $acl
    } catch {
        Write-Host "[cyclaw] WARNING: could not restrict the ACL on $Path." -ForegroundColor Yellow
    }
}

function Sync-CyclawPlaintextToCredentialManager {
    param(
        [string]$HomeDir = "",
        [string]$RepoDir = "",
        [switch]$WriteEnvFile
    )
    $files = @()
    if ($HomeDir) { $files += (Join-Path $HomeDir ".env") }
    if ($RepoDir) {
        $repoEnv = Join-Path $RepoDir ".env"
        if ($files -notcontains $repoEnv) { $files += $repoEnv }
    }
    foreach ($file in $files) {
        if (-not (Test-Path -LiteralPath $file)) { continue }
        $assignments = Get-CyclawDotenvAssignments $file
        $present = @()
        foreach ($name in $script:CyclawSecretTargets.Keys) {
            if ($assignments.ContainsKey($name)) { $present += $name }
        }
        if ($present.Count -eq 0) { continue }
        if ($WriteEnvFile) {
            Write-Host "[cyclaw] WARNING: PLAINTEXT OPT-IN: -WriteEnvFile leaves secrets in $file." -ForegroundColor Yellow
            Write-Host "[cyclaw] WARNING: Invoke-CyClaw.ps1 does not load those secret lines. Prefer Credential Manager." -ForegroundColor Yellow
            continue
        }
        if (-not (Test-CyclawWindowsHost)) {
            Write-Host "[cyclaw] WARNING: left plaintext secrets in $file (Credential Manager is unavailable on this host)." -ForegroundColor Yellow
            continue
        }
        if ($assignments.ContainsKey("GH_TOKEN") -and $assignments.ContainsKey("GITHUB_TOKEN")) {
            if ($assignments["GH_TOKEN"] -ne $assignments["GITHUB_TOKEN"]) {
                Write-Host "[cyclaw] WARNING: GH_TOKEN and GITHUB_TOKEN differ in $file; the Credential Manager copy follows GH_TOKEN. Values were not printed." -ForegroundColor Yellow
            }
        }
        $drop = New-Object System.Collections.Generic.List[string]
        foreach ($name in @("CYCLAW_API_KEY", "TELEGRAM_BOT_TOKEN", "GROK_API_KEY", "ANTHROPIC_API_KEY", "GH_TOKEN", "GITHUB_TOKEN")) {
            if (-not $assignments.ContainsKey($name)) { continue }
            $target = $script:CyclawSecretTargets[$name]
            $read = Read-CyclawCredential $target
            $secret = $null
            if ($read.Status -eq "readable") {
                $read.Secret = $null
                $drop.Add($name)
                continue
            }
            $read.Secret = $null
            if ($read.Status -eq "missing") {
                $secret = $assignments[$name]
                if ([string]::IsNullOrEmpty($secret)) {
                    Write-Host "[cyclaw] WARNING: left plaintext $name in $file (value empty; not stored)." -ForegroundColor Yellow
                    $secret = $null
                    continue
                }
                if (Write-CyclawCredential $target $secret) {
                    $drop.Add($name)
                    Write-Host "[cyclaw] moved $name from $file into Credential Manager ($target)."
                }
                $secret = $null
                continue
            }
            Write-Host "[cyclaw] WARNING: left plaintext $name in $file (Credential Manager target $target is $($read.Status); not deleting the only readable copy)." -ForegroundColor Yellow
        }
        if ($assignments.ContainsKey("CLAUDE_API_KEY")) {
            Write-Host "[cyclaw] WARNING: left CLAUDE_API_KEY in $file. llm/client.py reads ANTHROPIC_API_KEY; this unused name is not loaded and was not copied." -ForegroundColor Yellow
        }
        foreach ($name in @($assignments.Keys)) {
            if (-not (Test-CyclawSecretName $name)) { continue }
            if ($name -eq "CLAUDE_API_KEY") { continue }
            $mapped = ""
            if ($script:CyclawSecretTargets.ContainsKey($name)) { $mapped = $script:CyclawSecretTargets[$name] }
            if (-not [string]::IsNullOrEmpty($mapped)) { continue }
            Write-Host "[cyclaw] WARNING: left plaintext $name in $file (secret-classified, no Credential Manager target). Launchers do not load it. The value was not printed." -ForegroundColor Yellow
        }
        if ($drop.Count -gt 0) {
            Remove-CyclawSecretLines $file $drop.ToArray()
        }
        foreach ($key in @($assignments.Keys)) { $assignments[$key] = $null }
    }
}

function Write-CyclawPlaintextSecretWarning([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return }
    foreach ($raw in @(Get-Content -LiteralPath $Path)) {
        $line = $raw.Trim()
        if ($line.StartsWith('export ')) { $line = $line.Substring(7).Trim() }
        $eq = $line.IndexOf('=')
        if ($eq -lt 1) { continue }
        $name = $line.Substring(0, $eq).Trim()
        if ($script:CyclawSecretTargets.ContainsKey($name)) {
            Write-Host "[cyclaw] warn    : $name is in $Path but launchers do not load secrets from dotenv." -ForegroundColor Yellow
            Write-Host "[cyclaw] warn    : re-run Install-CyClaw.ps1 to copy it into Credential Manager and remove the plaintext line." -ForegroundColor Yellow
        }
    }
}
