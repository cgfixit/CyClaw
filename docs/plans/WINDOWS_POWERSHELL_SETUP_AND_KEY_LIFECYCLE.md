# Windows setup and credential lifecycle

Reviewed 2026-10-23 against main at 246e406. The
[original plan](https://github.com/cgfixit/CyClaw/blob/246e406d27beb097c3ecab3ba188a11c109b86db/docs/plans/WINDOWS_POWERSHELL_SETUP_AND_KEY_LIFECYCLE.md)
preserves the old parity proposals and cleanup rationale.
Use [the PowerShell guide](../../powershell/README.md) for current commands.

## Shipped

| Capability | Source of truth |
|---|---|
| Explicit checkout replacement | Install-CyClaw.ps1 -ReplaceRepo; no silent destructive replacement |
| Credential Manager migration and shared secret-store helpers | Install-CyClaw.ps1 and CyClaw-SecretStore.ps1 |
| Gateway launch and credential loading | Invoke-CyClaw.ps1; the old harness-only description is obsolete |
| Optional uninstall credential deletion | Uninstall-CyClaw.ps1 -RemoveCredentials, using policy-owned targets and Remove-CyclawCredential |
| Native error distinction in the maintained secret-store helper | CyClaw-SecretStore.ps1 separates missing credentials from other CredRead failures |
| Unmanaged secret cleanup and PowerShell 7 cancellation handling | CyClaw-CredMan-Set.ps1; retain the PowerShell 5.1-specific behavior |

The old proposed -RemoveCredMan name was not the shipped interface. A missing
Setup-CyClaw-Keys.ps1 filename is not evidence of missing bootstrap functionality:
the current launcher already handles bootstrap/loading through existing helpers.

## Remaining work

The older CyClaw-CredMan-Env.ps1 wrapper still treats every CredRead failure as
a missing credential. Bringing its classification into line with the maintained
secret-store helper is a deferred follow-up in
[#1745](https://github.com/cgfixit/CyClaw/issues/1745), not a docs-only fix.

Automatic installer invocation of Setup-FsConnect.ps1 -PrepareOnly and further
guided provider-key UX are optional proposals. Do not add a parallel bootstrap
path just to reproduce the old plan's filenames. No credentials, scheduled tasks
or installer behavior change in this cleanup.

## Credential-store boundary and verification

GENERIC Credential Manager credentials are scoped to the user/machine, not an
individual script. Do not port Keychain trusted-app concepts into a claim of
per-app isolation. Keep secret values out of task XML, argv and logs.

Preserve try/finally resource cleanup and the existing idempotent unmanaged-blob
wipe. The PowerShell 7 console handler is deliberately not applied identically
to Windows PowerShell 5.1. Native Windows acceptance remains distinct from
source checks or Linux/macOS fixtures.

See [the macOS plan](MACOS_BASH_SETUP_AND_KEY_LIFECYCLE.md) for the independent
scheduled-rotation lifecycle gap.
