# `powershell/` — Windows install, Credential Manager, and Task Scheduler glue

Install/launch/scheduling glue for Windows 10/11, Server 2019/2022,
and PowerShell 5.1/7+.
Not request-path code: `gate.py`, `graph.py`, and `mcp_hybrid_server.py` never
import anything here (I6). The macOS sibling is `macos/`.

After install, `cyclaw` starts the RAG gateway (`gate.py`, `127.0.0.1:8787`
per `config.yaml`), the same thing the macOS `invoke-cyclaw.sh` does.
The venv and launcher live under `%USERPROFILE%\.CyClaw`. `-RepoPath` uses an
existing checkout in place; corpus, index, personality, and application logs
follow its `config.yaml`. The separate fsconnect jail defaults to
`%USERPROFILE%\CyClaw-FS`.

## Scripts

| Script | What it does |
|---|---|
| `Install-CyClaw.ps1` | Home layout, Python 3.12 venv, hashed Windows Torch/runtime locks, `cyclaw` shim, optional PATH / profile function. `-RepoPath`, `-SkipPythonDeps`, `-NoProfileEdit`, `-NoPathEdit`, `-ReplaceRepo` (required before deleting an unusable `%USERPROFILE%\.CyClaw\repo`; does not apply with `-RepoPath`). Ensures `%USERPROFILE%\.CyClaw\.env` exists for ordinary settings. `-WriteEnvFile` opts into **retaining existing** plaintext secret lines instead of migrating them; it does not collect or provision provider keys. |
| `Uninstall-CyClaw.ps1` | Removes the profile function and PATH entry. Keeps `~\.CyClaw` unless `-RemoveHome`. Optional `-RemoveFsConnect`. Best-effort unschedules Dropbox sync and deletes **known** CyClaw Task Scheduler names only (never a wildcard). Does not write Credential Manager. For the six bootstrap secret names described below, removes a plaintext line only when the stored value is ordinal-equal, and only in `%USERPROFILE%\.CyClaw\.env` and `%USERPROFILE%\.CyClaw\repo\.env` (it does not follow `CYCLAW_REPO`). `-RemoveCredentials` lists and counts every Credential Manager target named in `utils/secret-policy.tsv`, then prompts before deleting them (pass `-Yes` to skip the prompt) and leaves the plaintext lines. |
| `Invoke-CyClaw.ps1` | Starts the RAG gateway (`python gate.py`, so `gate.main()`'s bind guard and `api.tls` apply) from `~\.CyClaw\venv`. The console URL uses `utils/gateway_url.py`: host/TLS from `config.yaml`, port from `CYCLAW_GATE_PORT` when nonblank, otherwise `api.port`; wildcard binds become loopback browser destinations. `-NoBrowser`, `-Repo`. Loads non-secret settings from the home `.env`, falling back to the repo `.env` only if the home file cannot be loaded (every Allow ACE must resolve to the current user SID, with at least one Allow ACE; shared, unresolvable, and empty ACLs are refused). Secret-classified names in those files are not exported. Unset secrets are then read from Credential Manager into that process only. On first run with no inherited or stored `CYCLAW_API_KEY` it generates one (20 random bytes as hex, `Write-CyclawCredential`, never on argv). When a key is available and `-NoBrowser` is absent, it opens the console at a one-time `#pair=` link (`CYCLAW_CONSOLE_PAIRING_CODE`, single-use, `security.console_pairing_ttl_sec`), so operator tools arrive unlocked without the key reaching the page. |
| `CyClaw-SecretStore.ps1` | Shared classification and Credential Manager load/migrate helpers used by the launcher, installer, and uninstaller. `Test-CyclawSecretName` is the secret classifier. |
| `Setup-FsConnect.ps1` | Creates confined `%USERPROFILE%\CyClaw-FS` (current-user ACL). Unless `-PrepareOnly`, enables list/stat/read via `macos/_enable_fsconnect_readlist.py`. Writes stay off. |
| `CyClaw-CredMan-Set.ps1` | Interactive Credential Manager store. `Read-Host -AsSecureString` + `CredWriteW`. Secret never in argv. Requires a TTY. |
| `CyClaw-CredMan-Env.ps1` | Fetch one GENERIC credential, export it, run the wrapped command. Fail-closed if missing/empty. |

## Scheduled tasks

Dropbox sync can be scheduled with `python -m sync.cli schedule`
(live `schtasks /Create`, daily by default -- `sync.schedule_frequency` also
accepts `weekly` / `monthly`; task name `CyClaw Dropbox Sync`).

Uninstall deletes only known tasks: Dropbox Sync, fsconnect-trash,
telegram-poll/health, gate, opentweet, and retired harness. Query-before-delete
tolerates missing tasks on PowerShell 5.1; no wildcard names are used.
Credentials require `-RemoveCredentials` and y/N confirmation (`-Yes` skips
the prompt); plaintext copies remain. Default uninstall never writes a credential.
Generated jobs load tokens through `CyClaw-CredMan-Env.ps1`,
keeping them out of task XML.

## Secret classification

`%USERPROFILE%\.CyClaw\.env` holds ordinary settings.
`Test-CyclawSecretName` uses the shared `utils/secret-policy.tsv`: exact
names map to credential targets; suffixes classify additional secrets
(`API_KEY`, `CREDENTIALS`, `PASSWORD`, `SECRET`, `TOKEN`, `PAT`, `DSN`,
`DB_URL`, `KEY`).

Store classified secrets in Credential Manager. `-WriteEnvFile` keeps existing
plaintext lines; even then `Invoke-CyClaw.ps1` never exports those lines. Do
not persist provider keys with `setx` or
`[Environment]::SetEnvironmentVariable(..., "User")`. A suffix match with no
Credential Manager target (`DB_PASSWORD`) is neither loaded nor deleted;
`CLAUDE_API_KEY` is classified but never loaded or copied, because
`llm/client.py` reads `ANTHROPIC_API_KEY`.

Re-running install migrates the six bootstrap names `CYCLAW_API_KEY`,
`TELEGRAM_BOT_TOKEN`, `GROK_API_KEY`, `ANTHROPIC_API_KEY`, `GH_TOKEN`, and
`GITHUB_TOKEN` into Credential Manager when their items are missing, then
removes a plaintext line only when the value reads back ordinal-equal. A
mismatch, failed store, or unreadable/empty item keeps the line and warns.
Automatic migration and uninstall cleanup currently cover those six names,
even though launch-time loading and `-RemoveCredentials` use the full mapped
policy. Store other mapped secrets with `CyClaw-CredMan-Set.ps1` and verify
them before manually removing their plaintext copies. Other lines stay and
no backup is written. At launch a missing
optional credential stays unset and the gateway starts, but a present item
that cannot be read or is empty aborts. `Invoke-CyClaw.ps1` generates a missing
`CYCLAW_API_KEY` (20 random bytes) into Credential Manager first; if it cannot
store it, it warns and starts without one, so key-based operator access fails
closed while an enabled admin login and the constrained-loopback bypass keep
their own rules ([operator access](../README.md#api-key-setup-soul-mutations)).

## Related

- Dropbox sync scheduling: [`docs/SYNC_README.md`](../docs/SYNC_README.md)
- Telegram channel: [`docs/channels/TELEGRAM_DESIGN.md`](../docs/channels/TELEGRAM_DESIGN.md)
- Connectors (fsconnect, netconnect): [`agentic/README.md`](../agentic/README.md)
- macOS twin: [`macos/README.md`](../macos/README.md)
