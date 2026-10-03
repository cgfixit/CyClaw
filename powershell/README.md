# `powershell/` — Windows install, Credential Manager, and Task Scheduler glue

Installer / launcher / scheduled-task **glue** for Windows 10/11.
Not request-path code: `gate.py`, `graph.py`, and `mcp_hybrid_server.py` never
import anything here (I6). The macOS sibling is `macos/`.

After install, `cyclaw` starts the RAG gateway (`gate.py`, `127.0.0.1:8787`
per `config.yaml`), the same thing the macOS `invoke-cyclaw.sh` does.
Mutable state lives under `%USERPROFILE%\.CyClaw`.

## Scripts

| Script | What it does |
|---|---|
| `Install-CyClaw.ps1` | Home layout, venv, `cyclaw` shim, optional PATH / profile function. `-RepoPath`, `-SkipPythonDeps`, `-NoProfileEdit`, `-NoPathEdit`, `-ReplaceRepo` (required before deleting a stale `%USERPROFILE%\.CyClaw\repo`; does not apply with `-RepoPath`). Ensures `%USERPROFILE%\.CyClaw\.env` exists for ordinary settings. `-WriteEnvFile` is the loud opt-in that also writes secret lines into that file. |
| `Uninstall-CyClaw.ps1` | Removes the profile function and PATH entry. Keeps `~\.CyClaw` unless `-RemoveHome`. Optional `-RemoveFsConnect`. Best-effort unschedules Dropbox sync and deletes **known** CyClaw Task Scheduler names only (never a wildcard). Does not write Credential Manager. Removes a plaintext line only when the stored value is ordinal-equal, and only in `%USERPROFILE%\.CyClaw\.env` and `%USERPROFILE%\.CyClaw\repo\.env` (it does not follow `CYCLAW_REPO`). `-RemoveCredentials` deletes the five documented targets and leaves the plaintext lines. |
| `Invoke-CyClaw.ps1` | Starts the RAG gateway (`python gate.py`, so `gate.main()`'s bind guard and `api.tls` apply) from `~\.CyClaw\venv`. The console URL uses `utils/gateway_url.py`: host/TLS from `config.yaml`, port from `CYCLAW_GATE_PORT` when nonblank, otherwise `api.port`; wildcard binds become loopback browser destinations. `-NoBrowser`, `-Repo`. Loads non-secret settings from `%USERPROFILE%\.CyClaw\.env` then the repo `.env` (every Allow ACE must resolve to the current user SID, with at least one Allow ACE; shared, unresolvable, and empty ACLs are refused; refused HOME does not shadow repo). Secret-classified names in those files are not exported. Unset secrets are then read from Credential Manager into that process only. |
| `CyClaw-SecretStore.ps1` | Shared classification and Credential Manager load/migrate helpers used by the launcher, installer, and uninstaller. `Test-CyclawSecretName` is the secret classifier. |
| `Setup-FsConnect.ps1` | Creates confined `%USERPROFILE%\CyClaw-FS` (current-user ACL). Unless `-PrepareOnly`, enables list/stat/read via `macos/_enable_fsconnect_readlist.py`. Writes stay off. |
| `CyClaw-CredMan-Set.ps1` | Interactive Credential Manager store. `Read-Host -AsSecureString` + `CredWriteW`. Secret never in argv. Requires a TTY. |
| `CyClaw-CredMan-Env.ps1` | Fetch one GENERIC credential, export it, run the wrapped command. Fail-closed if missing/empty. |

## Scheduled tasks

Dropbox sync is already scheduled with `python -m sync.cli schedule`
(live `schtasks /Create`, daily by default -- `sync.schedule_frequency` also
accepts `weekly` / `monthly`; task name `CyClaw Dropbox Sync`).

`Uninstall-CyClaw.ps1` best-effort deletes a **fixed** list of CyClaw task
names (`CyClaw Dropbox Sync`, `CyClaw fsconnect-trash`,
`CyClaw telegram-poll`, `CyClaw telegram-health`, `CyClaw gate`,
`CyClaw harness` (the retired console's name, kept for older installs), `CyClaw opentweet`) so a later generator cannot outlive uninstall. It never
uses a wildcard `/TN`. A missing task is a no-op (query-then-delete;
Windows PowerShell 5.1 must not abort uninstall on `schtasks` stderr).
Credential Manager items are **not** deleted unless `-RemoveCredentials` is
passed (the macOS twin is `--remove-keychain`). That switch leaves plaintext
lines in place. The default uninstall never writes a credential.

Telegram / API-key injection for those later generators goes through
`CyClaw-CredMan-Env.ps1` so tokens never appear in task XML.

## Secret classification

`%USERPROFILE%\.CyClaw\.env` stays the default home for ordinary settings
(ports, paths, mode flags, model names, feature toggles). `cyclaw` still
loads those lines. A name is secret-classified when `Test-CyclawSecretName`
in `CyClaw-SecretStore.ps1` says so: the allowlist (`CYCLAW_API_KEY`,
`TELEGRAM_BOT_TOKEN`, `GROK_API_KEY`, `ANTHROPIC_API_KEY`, `GH_TOKEN`,
`GITHUB_TOKEN`, `CLAUDE_API_KEY`) or a name ending in `_API_KEY`, `_TOKEN`,
`_SECRET`, or `_PASSWORD`.

Allowlisted secrets are stored in Credential Manager and are not written
into `.env` unless `-WriteEnvFile` is passed. Even then, `Invoke-CyClaw.ps1`
does not export secret-classified lines. Do not persist provider keys with
`setx` or `[Environment]::SetEnvironmentVariable(..., "User")`. A name that
matches the suffix pattern but has no Credential Manager target (for example
`DB_PASSWORD`) is not loaded and is not deleted. `CLAUDE_API_KEY` is not
loaded and is not copied; `llm/client.py` reads `ANTHROPIC_API_KEY`.

Re-running install copies each allowlisted secret into Credential Manager
when that item is missing, then removes the plaintext line only when the
value read back is ordinal-equal. A mismatch keeps the line and warns.
Uninstall never writes a credential; it only removes a matching line.
Other lines stay. No backup file is written. If the store fails or the
item is unreadable or empty, the plaintext line stays, because it is
still the only copy. A missing optional credential stays unset and the
gateway still starts. A present item that cannot be read, or is empty,
aborts that launch. `CYCLAW_API_KEY` missing warns and still starts the
server; soul and ops routes then fail closed with 401.

## Related

- Dropbox sync scheduling: [`docs/SYNC_README.md`](../docs/SYNC_README.md)
- Telegram channel: [`docs/channels/TELEGRAM_DESIGN.md`](../docs/channels/TELEGRAM_DESIGN.md)
- Agentic / registry: [`agentic/README.md`](../agentic/README.md)
- macOS twin: [`macos/README.md`](../macos/README.md)
