<#
.SYNOPSIS
  Credential Manager access and dotenv handling for the Windows launcher.

.DESCRIPTION
  Dot-sourced by Invoke-CyClaw.ps1, Install-CyClaw.ps1, and Uninstall-CyClaw.ps1.
  ~/.CyClaw/.env stays the home for ordinary settings (ports, paths, mode
  flags, model names, feature toggles). Secret-classified names are not
  imported. A name is secret when it is on the allowlist below, or when it
  ends in _API_KEY, _TOKEN, _SECRET, or _PASSWORD (PowerShell -like is
  case-insensitive, so grok_api_key is secret too). Allowlisted secrets are
  read from Credential Manager into the CyClaw process only. A plaintext
  line is removed only when the value read back from Credential Manager is
  ordinal-equal to the file. A mismatch keeps the line and warns. No backup
  is written. Values are never printed. Install may copy a missing item.
  Uninstall never writes to Credential Manager. A pattern match with no
  Credential Manager target is left in the file.

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
    foreach ($raw in @(Get-Content -LiteralPath $Path)) {
        foreach ($row in @(Get-CyclawEnvLineAssignments $raw)) {
            # Secret-classified names stay out of this process. Credential Manager is the source.
            if (Test-CyclawSecretName $row.Name) { continue }
            if ($row.Op -eq "+=") {
                $cur = [Environment]::GetEnvironmentVariable($row.Name)
                if ($null -eq $cur) { $cur = "" }
                Set-Item -Path ("Env:" + $row.Name) -Value ($cur + [string]$row.Value)
            } else {
                Set-Item -Path ("Env:" + $row.Name) -Value ([string]$row.Value)
            }
        }
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

    [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern bool CredDelete(string target, int type, int flags);
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

function Remove-CyclawCredential([string]$Target) {
    # True when the item is gone (deleted or already absent). False off
    # Windows, on an empty target, or when CredDelete fails for another reason.
    # Never prints a secret. Uninstall's -RemoveCredentials is the only caller.
    if ([string]::IsNullOrEmpty($Target)) { return $false }
    if (-not (Test-CyclawWindowsHost)) { return $false }
    Initialize-CyclawSecretStoreNative
    if ([CyClawSecretStoreNative]::CredDelete($Target, [CyClawSecretStoreNative]::CRED_TYPE_GENERIC, 0)) {
        return $true
    }
    $err = [Runtime.InteropServices.Marshal]::GetLastWin32Error()  # DevSkim: ignore DS104456 — CredDelete last-error; not a secret
    # 1168 ERROR_NOT_FOUND, 2 ERROR_FILE_NOT_FOUND: already absent.
    if ($err -eq 1168 -or $err -eq 2) { return $true }
    Write-Host "[cyclaw] WARNING: CredDelete failed for target $Target (win32=$err)." -ForegroundColor Yellow
    return $false
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

function Get-CyclawEnvLineAssignments([string]$Line) {
    # One env-line parser for the Windows loaders. Same cases as
    # cyclaw_dotenv_line_assignments in macos/cyclaw-public-env.sh:
    # every NAME= / NAME+= token, lowercase names, a leading UTF-8 BOM,
    # and export / declare -x / typeset / readonly (optional flag words).
    # Returns objects with Name, Op ("=" or "+="), and Value. A command
    # word stops the scan. An unquoted semicolon starts another command.
    $rows = New-Object System.Collections.Generic.List[object]
    if ($null -eq $Line) { return @() }
    $s = $Line
    if ($s.Length -gt 0 -and [int][char]$s[0] -eq 0xFEFF) { $s = $s.Substring(1) }
    $n = $s.Length
    $i = 0
    while ($i -lt $n -and [char]::IsWhiteSpace($s[$i])) { $i++ }
    while ($i -lt $n) {
        while ($i -lt $n -and [char]::IsWhiteSpace($s[$i])) { $i++ }
        if ($i -ge $n) { break }
        $c = $s[$i]
        if ($c -eq '#') { break }
        if ($c -eq ';' -or $c -eq '|' -or $c -eq '&') { $i++; continue }
        $start = $i
        $word = ""
        $scanning = $true
        while ($scanning -and $i -lt $n) {
            $c = $s[$i]
            if ([char]::IsWhiteSpace($c) -or $c -eq ';' -or $c -eq '|' -or $c -eq '&') { $scanning = $false; continue }
            if ($c -eq '\') {
                $i++
                if ($i -lt $n) { $word += $s[$i]; $i++ }
                continue
            }
            if ($c -eq "'") {
                $i++
                while ($i -lt $n -and $s[$i] -ne "'") { $word += $s[$i]; $i++ }
                if ($i -lt $n) { $i++ }
                continue
            }
            if ($c -eq '"') {
                $i++
                while ($i -lt $n -and $s[$i] -ne '"') {
                    if ($s[$i] -eq '\' -and ($i + 1) -lt $n) { $i++; $word += $s[$i]; $i++; continue }
                    $word += $s[$i]
                    $i++
                }
                if ($i -lt $n) { $i++ }
                continue
            }
            $word += $c
            $i++
        }
        if ($word -eq 'export' -or $word -eq 'declare' -or $word -eq 'typeset' -or $word -eq 'readonly') {
            while ($i -lt $n -and [char]::IsWhiteSpace($s[$i])) { $i++ }
            while ($i -lt $n -and $s[$i] -eq '-') {
                $flagStart = $i
                $flag = ""
                while ($i -lt $n -and -not [char]::IsWhiteSpace($s[$i]) -and $s[$i] -ne ';' -and $s[$i] -ne '|' -and $s[$i] -ne '&') {
                    $flag += $s[$i]
                    $i++
                }
                if (-not $flag.StartsWith('-')) { $i = $flagStart; break }
                while ($i -lt $n -and [char]::IsWhiteSpace($s[$i])) { $i++ }
            }
            continue
        }
        $i = $start
        if ($i -ge $n -or -not ($s[$i] -match '[A-Za-z_]')) { break }
        $name = ""
        while ($i -lt $n -and ($s[$i] -match '[A-Za-z0-9_]')) { $name += $s[$i]; $i++ }
        $op = ""
        if (($i + 1) -lt $n -and $s[$i] -eq '+' -and $s[$i + 1] -eq '=') { $op = "+="; $i += 2 }
        elseif ($i -lt $n -and $s[$i] -eq '=') { $op = "="; $i++ }
        else { break }
        $val = ""
        $reading = $true
        while ($reading -and $i -lt $n) {
            $c = $s[$i]
            if ([char]::IsWhiteSpace($c) -or $c -eq ';' -or $c -eq '|' -or $c -eq '&') { $reading = $false; continue }
            if ($c -eq '\') {
                $i++
                if ($i -lt $n) { $val += $s[$i]; $i++ }
                continue
            }
            if ($c -eq "'") {
                $i++
                while ($i -lt $n -and $s[$i] -ne "'") { $val += $s[$i]; $i++ }
                if ($i -lt $n) { $i++ }
                continue
            }
            if ($c -eq '"') {
                $i++
                while ($i -lt $n -and $s[$i] -ne '"') {
                    if ($s[$i] -eq '\' -and ($i + 1) -lt $n) { $i++; $val += $s[$i]; $i++; continue }
                    $val += $s[$i]
                    $i++
                }
                if ($i -lt $n) { $i++ }
                continue
            }
            $val += $c
            $i++
        }
        $rows.Add((New-Object psobject -Property @{ Name = $name; Op = $op; Value = $val }))
    }
    return @($rows.ToArray())
}

function Get-CyclawDotenvAssignments([string]$Path) {
    # Name -> value (last assignment wins). Caller must not print values.
    $map = @{}
    if (-not (Test-Path -LiteralPath $Path)) { return $map }
    foreach ($raw in @(Get-Content -LiteralPath $Path)) {
        foreach ($row in @(Get-CyclawEnvLineAssignments $raw)) {
            $map[$row.Name] = $row.Value
        }
    }
    return $map
}

function Remove-CyclawSecretLines([string]$Path, [hashtable]$Expected) {
    # Expected maps a name to the unquoted value that must match ordinally.
    # Other assignments on the same line are rewritten. Comments stay.
    # A file that would become blank keeps the public header.
    if (-not (Test-Path -LiteralPath $Path)) { return }
    if (-not $Expected -or $Expected.Count -eq 0) { return }
    $kept = New-Object System.Collections.Generic.List[string]
    $removed = New-Object System.Collections.Generic.List[string]
    $assignLeft = $false
    foreach ($raw in @(Get-Content -LiteralPath $Path)) {
        $rows = @(Get-CyclawEnvLineAssignments $raw)
        if ($rows.Count -eq 0) {
            $kept.Add($raw)
            continue
        }
        $rebuilt = New-Object System.Collections.Generic.List[string]
        $droppedHere = $false
        foreach ($row in $rows) {
            $match = $false
            if ($Expected.ContainsKey($row.Name)) {
                $want = [string]$Expected[$row.Name]
                if ([string]::Equals([string]$row.Value, $want, [StringComparison]::Ordinal)) {
                    $match = $true
                }
            }
            if ($match) {
                $droppedHere = $true
                if (-not $removed.Contains($row.Name)) { $removed.Add($row.Name) }
                continue
            }
            # Shell-style single quotes so a later macOS read of a copied file
            # round-trips an apostrophe the same way setup writes it.
            $escaped = ([string]$row.Value).Replace("'", "'\''")
            if ($row.Op -eq "+=") {
                $rebuilt.Add("$($row.Name)+='$escaped'")
            } else {
                $rebuilt.Add("$($row.Name)='$escaped'")
            }
        }
        if (-not $droppedHere) {
            $assignLeft = $true
            $kept.Add($raw)
            continue
        }
        if ($rebuilt.Count -gt 0) {
            $assignLeft = $true
            $kept.Add(($rebuilt -join " "))
        }
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
        $drop = @{}
        foreach ($name in @("CYCLAW_API_KEY", "TELEGRAM_BOT_TOKEN", "GROK_API_KEY", "ANTHROPIC_API_KEY", "GH_TOKEN", "GITHUB_TOKEN")) {
            if (-not $assignments.ContainsKey($name)) { continue }
            $target = $script:CyclawSecretTargets[$name]
            $fileVal = [string]$assignments[$name]
            $read = Read-CyclawCredential $target
            $secret = $null
            if ($read.Status -eq "readable") {
                $stored = [string]$read.Secret
                $read.Secret = $null
                # GITHUB_TOKEN shares com.cgfixit.cyclaw.gh-token with GH_TOKEN.
                # A different file value is kept; the stored bytes are not overwritten.
                if ([string]::Equals($stored, $fileVal, [StringComparison]::Ordinal)) {
                    $drop[$name] = $fileVal
                } else {
                    Write-Host "[cyclaw] WARNING: left plaintext $name in $file (Credential Manager $target value differs from the file). The line was kept. Values were not printed." -ForegroundColor Yellow
                }
                $stored = $null
                continue
            }
            $read.Secret = $null
            if ($read.Status -eq "missing") {
                $secret = $fileVal
                if ([string]::IsNullOrEmpty($secret)) {
                    Write-Host "[cyclaw] WARNING: left plaintext $name in $file (value empty; not stored)." -ForegroundColor Yellow
                    $secret = $null
                    continue
                }
                if (Write-CyclawCredential $target $secret) {
                    $readBack = Read-CyclawCredential $target
                    $readBackVal = $null
                    if ($readBack.Status -eq "readable") { $readBackVal = [string]$readBack.Secret }
                    $readBack.Secret = $null
                    if ([string]::Equals($readBackVal, $secret, [StringComparison]::Ordinal)) {
                        $drop[$name] = $secret
                        Write-Host "[cyclaw] moved $name from $file into Credential Manager ($target)."
                    } else {
                        Write-Host "[cyclaw] WARNING: left plaintext $name in $file (Credential Manager $target could not be read back). The line was kept. Values were not printed." -ForegroundColor Yellow
                    }
                    $readBackVal = $null
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
            Remove-CyclawSecretLines $file $drop
        }
        foreach ($key in @($assignments.Keys)) { $assignments[$key] = $null }
    }
}

function Remove-CyclawPlaintextIfCredentialMatches {
    # Read-only. Never calls Write-CyclawCredential. Uninstall uses this so
    # tearing the integration down cannot create Credential Manager items.
    param(
        [string]$HomeDir = "",
        [string]$RepoDir = ""
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
        $expected = @{}
        foreach ($name in @("CYCLAW_API_KEY", "TELEGRAM_BOT_TOKEN", "GROK_API_KEY", "ANTHROPIC_API_KEY", "GH_TOKEN", "GITHUB_TOKEN")) {
            if (-not $assignments.ContainsKey($name)) { continue }
            $target = $script:CyclawSecretTargets[$name]
            $fileVal = [string]$assignments[$name]
            if (-not (Test-CyclawWindowsHost)) {
                Write-Host "[cyclaw] WARNING: left plaintext $name in $file (Credential Manager is unavailable on this host)." -ForegroundColor Yellow
                continue
            }
            $read = Read-CyclawCredential $target
            if ($read.Status -ne "readable") {
                $read.Secret = $null
                Write-Host "[cyclaw] WARNING: left plaintext $name in $file (Credential Manager target $target is $($read.Status); not deleting the only readable copy)." -ForegroundColor Yellow
                continue
            }
            $stored = [string]$read.Secret
            $read.Secret = $null
            if (-not [string]::Equals($stored, $fileVal, [StringComparison]::Ordinal)) {
                Write-Host "[cyclaw] WARNING: left plaintext $name in $file (Credential Manager $target value differs from the file). The line was kept. Values were not printed." -ForegroundColor Yellow
                $stored = $null
                continue
            }
            $expected[$name] = $fileVal
            $stored = $null
        }
        if ($expected.Count -gt 0) {
            Remove-CyclawSecretLines $file $expected
        }
        foreach ($key in @($assignments.Keys)) { $assignments[$key] = $null }
    }
}

function Write-CyclawPlaintextSecretWarning([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return }
    foreach ($raw in @(Get-Content -LiteralPath $Path)) {
        foreach ($row in @(Get-CyclawEnvLineAssignments $raw)) {
            if ($script:CyclawSecretTargets.ContainsKey($row.Name)) {
                Write-Host "[cyclaw] warn    : $($row.Name) is in $Path but launchers do not load secrets from dotenv." -ForegroundColor Yellow
                Write-Host "[cyclaw] warn    : re-run Install-CyClaw.ps1 to copy it into Credential Manager and remove the plaintext line." -ForegroundColor Yellow
            }
        }
    }
}
