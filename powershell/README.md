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
| `Uninstall-CyClaw.ps1` | Removes the profile function and PATH entry. Keeps `~\.CyClaw` unless `-RemoveHome`. Optional `-RemoveFsConnect`. Best-effort unschedules Dropbox sync and deletes **known** CyClaw Task Scheduler names only (never a wildcard). Does not write Credential Manager. Removes a plaintext line only when the stored value is ordinal-equal, and only in `%USERPROFILE%\.CyClaw\.env` and `%USERPROFILE%\.CyClaw\repo\.env` (it does not follow `CYCLAW_REPO`). `-RemoveCredentials` lists and counts every Credential Manager target named in `utils/secret-policy.tsv`, then prompts before deleting them (pass `-Yes` to skip the prompt) and leaves the plaintext lines. |
| `Invoke-CyClaw.ps1` | Starts the RAG gateway (`python gate.py`, so `gate.main()`'s bind guard and `api.tls` apply) from `~\.CyClaw\venv`. The console URL uses `utils/gateway_url.py`: host/TLS from `config.yaml`, port from `CYCLAW_GATE_PORT` when nonblank, otherwise `api.port`; wildcard binds become loopback browser destinations. `-NoBrowser`, `-Repo`. Loads non-secret settings from `%USERPROFILE%\.CyClaw\.env` then the repo `.env` (every Allow ACE must resolve to the current user SID, with at least one Allow ACE; shared, unresolvable, and empty ACLs are refused; refused HOME does not shadow repo). Secret-classified names in those files are not exported. Unset secrets are then read from Credential Manager into that process only. On first run with no `CYCLAW_API_KEY` in Credential Manager it generates one (20 random bytes as hex, `Write-CyclawCredential`, never on argv). It opens the console at a one-time `#pair=` link (`CYCLAW_CONSOLE_PAIRING_CODE`, single-use, `security.console_pairing_ttl_sec`), so operator tools arrive unlocked without the key reaching the page. |
| `CyClaw-SecretStore.ps1` | Shared classification and Credential Manager load/migrate helpers used by the launcher, installer, and uninstaller. `Test-CyclawSecretName` is the secret classifier. |
| `Setup-FsConnect.ps1` | Creates confined `%USERPROFILE%\CyClaw-FS` (current-user ACL). Unless `-PrepareOnly`, enables list/stat/read via `macos/_enable_fsconnect_readlist.py`. Writes stay off. |
| `CyClaw-CredMan-Set.ps1` | Interactive Credential Manager store. `Read-Host -AsSecureString` + `CredWriteW`. Secret never in argv. Requires a TTY. |
| `CyClaw-CredMan-Env.ps1` | Fetch one GENERIC credential, export it, run the wrapped command. Fail-closed if missing/empty. |

## Scheduled tasks

Dropbox sync is already scheduled with `python -m sync.cli schedule`
(live `schtasks /Create`, daily by default -- `sync.schedule_frequency` also
accepts `weekly` / `monthly`; task name `CyClaw Dropbox Sync`).

`Uninstall-CyClaw.ps1` best-effort deletes a **fixed** list of task names
(`CyClaw Dropbox Sync`, `CyClaw fsconnect-trash`, `CyClaw telegram-poll`,
`CyClaw telegram-health`, `CyClaw gate`, `CyClaw opentweet`, and the retired
`CyClaw harness`) so a later generator cannot outlive uninstall; never a
wildcard `/TN`, and a missing task is a no-op (query-then-delete, so Windows
PowerShell 5.1 does not abort on `schtasks` stderr). Credential Manager items
go only with `-RemoveCredentials` (the macOS twin is `--remove-keychain`),
which prompts y/N unless `-Yes` is passed and leaves plaintext lines in place;
the default uninstall never writes a credential. Generators inject tokens
through `CyClaw-CredMan-Env.ps1`, so none appears in task XML.

## Secret classification

`%USERPROFILE%\.CyClaw\.env` stays the default home for ordinary settings
(ports, paths, mode flags, model names, feature toggles), and `cyclaw` loads
those lines. `Test-CyclawSecretName` in `CyClaw-SecretStore.ps1` classifies a
name as secret from `utils/secret-policy.tsv` (shared with the bash and Python
loaders): an `exact` row mapped to its Credential Manager target
(`CYCLAW_API_KEY`, `TELEGRAM_BOT_TOKEN`, `GROK_API_KEY`, `ANTHROPIC_API_KEY`,
`GH_TOKEN`/`GITHUB_TOKEN`, the `CYCLAW_*_DB_URL` family,
`RCLONE_CONFIG_PASS`, …) or a `suffix` row (`API_KEY`, `CREDENTIALS`,
`PASSWORD`, `SECRET`, `TOKEN`, `PAT`, `DSN`, `DB_URL`, `KEY`).

Classified secrets live in Credential Manager and reach `.env` only with
`-WriteEnvFile`; even then `Invoke-CyClaw.ps1` never exports those lines. Do
not persist provider keys with `setx` or
`[Environment]::SetEnvironmentVariable(..., "User")`. A suffix match with no
Credential Manager target (`DB_PASSWORD`) is neither loaded nor deleted;
`CLAUDE_API_KEY` is classified but never loaded or copied, because
`llm/client.py` reads `ANTHROPIC_API_KEY`.

Re-running install copies each classified secret into Credential Manager when
its item is missing, then removes the plaintext line only when the value reads
back ordinal-equal; a mismatch, failed store, or unreadable/empty item keeps
the line (still the only copy) and warns. Other lines stay and no backup is
written; uninstall only ever removes a matching line. At launch a missing
optional credential stays unset and the gateway starts, but a present item
that cannot be read or is empty aborts. `Invoke-CyClaw.ps1` generates a missing
`CYCLAW_API_KEY` (20 random bytes) into Credential Manager first; if it cannot
store it, it warns and starts without one, so key-based operator access fails
closed while an enabled admin login and the constrained-loopback bypass keep
their own rules ([operator access](../README.md#api-key-setup-soul-mutations)).

## Related

- Dropbox sync scheduling: [`docs/SYNC_README.md`](../docs/SYNC_README.md)
- Telegram channel: [`docs/channels/TELEGRAM_DESIGN.md`](../docs/channels/TELEGRAM_DESIGN.md)
- Agentic / registry: [`agentic/README.md`](../agentic/README.md)
- macOS twin: [`macos/README.md`](../macos/README.md)
