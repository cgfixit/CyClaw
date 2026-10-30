# `macos/` — POSIX install and launchd glue

Installer / launcher / launchd **glue** for macOS (Apple Silicon) and Linux.
Not request-path code: `gate.py`, `graph.py`, and `mcp_hybrid_server.py` never
import anything here (I6). The Windows sibling is `powershell/`.

After install, `cyclaw` starts the RAG gateway (default `127.0.0.1:8787`).
The installer puts its venv and launcher under `~/.CyClaw`; `--repo-path`
keeps an existing checkout in place. Corpus, index, personality, and application
log paths follow that checkout's `config.yaml`, so they need not live under
`~/.CyClaw`. The separate fsconnect jail defaults to `~/CyClaw-FS`.


## Scripts

| Script | What it does |
|---|---|
| `setup-cyclaw.sh` | One-command onboarding: finds/clones checkout, runs `setup-from-clone.sh --no-start`, optionally starts gateway, opens console, and autofills the key in browser memory. Can run standalone. Owns repo/clone, start/browser/autofill, prompt and dry-run options; forwards remaining flags. `--help` is authoritative. |
| `setup-from-clone.sh` | Apple Silicon onboarding: installer, key prompts (Telegram/Claude/Grok/GitHub), Ollama, index, gateway. `--skip-prompts` implies no start unless `--start`. Supports dry-run, model selection and selective skip flags; consult `--help`. |
| `install-cyclaw.sh` | Home layout, venv, `cyclaw` shim, optional PATH / rc function. `--repo-path`, `--replace-repo`, `--skip-python-deps`, `--no-profile-edit`, `--no-path-edit`, `--no-fsconnect`. `--replace-repo` is destructive only for an unusable directory at the default `~/.CyClaw/repo` target; it does not apply with `--repo-path`. |
| `uninstall-cyclaw.sh` | Removes the rc function, PATH entry, and the `cyclaw keys` source block; strips a secret-classified line from `~/.CyClaw/.env` or `~/.CyClaw/repo/.env` only when the Keychain value reads back byte-equal (skipped with `--remove-keychain`, so the purge never deletes the only copy). Does not follow `CYCLAW_REPO`. Keeps `~/.CyClaw` unless `--remove-home`; `--remove-fsconnect` optional. `--remove-keychain` (prompted y/N; `--yes`/`--assume-yes` confirms already-requested destructive flags only) removes the Linux libsecret item and key file, or on macOS every exact `com.cgfixit.cyclaw.*` service named in `utils/secret-policy.tsv` for `id -un` — never a wildcard or a secret value. Best-effort unschedules Dropbox sync, `launchctl bootout`s CyClaw LaunchAgent labels (telegram-poll/health, fsconnect-trash, gate, keys-rotate, opentweet, sync, the retired `harness`), then frees a leftover listener on `CYCLAW_GATE_PORT` (default 8787). |
| `invoke-cyclaw.sh` | Starts `python gate.py` from `~/.CyClaw/venv`, preserving the bind guard, `api.tls`, and `proxy_headers=False`. Loads non-secret settings from the home `.env` or, if that fails, the repo `.env`, then secrets from the keystore into that process only. Port precedence is `--gate-port`, inherited `CYCLAW_GATE_PORT`, then **8787**; it exports that choice even when `api.port` differs. The console URL follows `api.host`, `api.tls.enabled`, and that port via `utils/gateway_url.py`. `--no-browser` / `--repo`. `--print-pairing-url` prints the one-time link for headless use (warns on redirected stdout). On macOS, with no inherited or stored `CYCLAW_API_KEY`, it runs `setup-cyclaw-keys.sh --skip-prompts` (no profile edit, no dotenv write) to generate one, then opens the console at a single-use `#pair=` link (`CYCLAW_CONSOLE_PAIRING_CODE`, `security.console_pairing_ttl_sec`) so operator tools arrive unlocked without the key reaching the page. |
| `cyclaw-linux-key.sh` | Sourced by `invoke-cyclaw.sh` on Linux: libsecret (`secret-tool`, service `com.cgfixit.cyclaw.api-key`) first, then `$XDG_CONFIG_HOME/cyclaw/api-key` (0700/0600; symlinked, foreign-owned, group-readable, or malformed files are refused). The key never becomes an argv token. Details: [Linux launcher credentials](#linux-launcher-credentials-and-headless-pairing). |
| `setup-cyclaw-keys.sh` | Apple Silicon key bootstrap; generates gateway key and optionally prompts for provider/channel keys. Keychain is default; `--write-env-file` opts into plaintext. Migration verifies equality before removal. Supports rotation, clipboard TTL, browser fill, and generate-only rotation schedules. `--restart-servers` frees the port but does not start the server. See Key bootstrap below and `--help`. |
| `cyclaw-keychain-load.sh` | Shared sourced helper for onboarding and launchers. Filters dotenv settings, scrubs secret-classified dotenv values, and loads allowed Keychain items into the process. |
| `cyclaw-public-env.sh` | Sourced by the rc block. Exports non-secret dotenv settings. Reads the secret classification from The shared `utils/secret-policy.tsv` maps exact secret names to Keychain
services and classifies suffixes (`API_KEY`, `CREDENTIALS`, `PASSWORD`,
`SECRET`, `TOKEN`, `PAT`, `DSN`, `DB_URL`, `KEY`). Launchers load mapped
secrets into the process only. `--write-env-file` additionally persists
plaintext; neither rc blocks nor launchers export those dotenv lines.

Re-running the keys script copies each classified secret into the Keychain
when its item is missing, then removes the plaintext line only when the value
read back is byte-equal; a mismatch or failed store keeps the line (it is
still the only copy) and warns. Other lines stay and no backup is written. A
suffix match with no Keychain service is left in place and not loaded.

```bash
bash macos/setup-cyclaw-keys.sh
# new tabs inherit non-secret settings; cyclaw reads the Keychain
```

LaunchAgents still read Keychain through `cyclaw-keychain-env.sh`. They do
not read `.env`, and this script never writes a token into a plist or the
`cyclaw` shim.

The terminal console never stores the operator key in `localStorage`.
Onboarding autofill passes the key through a temporary mode-0600 file in a
mode-0700 directory for AppleScript, then removes it. If autofill fails, its
clipboard fallback clears the copied key after the configured TTL when the
clipboard still contains that value. Disable autofill with
`--no-autofill-api-key` when that extra handling is unwanted.
`--fill-browser` puts the key into `#apiKeyInput` on a matching-port HTTP tab
at literal `127.0.0.1` or `[::1]`. The page exchanges it once through
`POST /console/session`, receives a signed HttpOnly `cyclaw_console` cookie,
and clears the field. HTTPS and hostname URLs, including `localhost`, require
manual entry. The launcher path normally avoids the key field by redeeming a
single-use `#pair=` fragment for the same cookie.

A scheduled rotate updates the Keychain. It exits nonzero before removing a
plaintext line if the Keychain write fails. A manual or scheduled rotate does
not change an already-running server environment. Restart `gate.py`, then
redeem a new pairing code or enter the current key once.

```bash
# first run (prompts; skip any; fill the consoles if they are up)
bash macos/setup-cyclaw-keys.sh --grok-dummy --fill-browser

# rotate now, then open a new console session
bash ~/.CyClaw/bin/setup-cyclaw-keys.sh --rotate --skip-prompts --fill-browser

# write (do not load) a monthly rotator
bash ~/.CyClaw/bin/setup-cyclaw-keys.sh --schedule-rotate monthly
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.cgfixit.cyclaw.keys-rotate.plist
```

The rotate LaunchAgent runs a frozen copy at
`$CYCLAW_HOME/bin/setup-cyclaw-keys.sh`. Re-run `--schedule-rotate` after
updating CyClaw so an existing schedule receives script fixes.

| Env var | How | Keychain service |
|---|---|---|
| `CYCLAW_API_KEY` | Autogenerated | `com.cgfixit.cyclaw.api-key` |
| `TELEGRAM_BOT_TOKEN` | Prompt (skip ok) | `com.cgfixit.cyclaw.telegram-bot-token` |
| `ANTHROPIC_API_KEY` | Prompt (skip ok) | `com.cgfixit.cyclaw.anthropic-api-key` |
| `GROK_API_KEY` | Prompt (skip ok) or `--grok-dummy` | `com.cgfixit.cyclaw.grok-api-key` |
| `GH_TOKEN` (+ `GITHUB_TOKEN`) | Prompt (skip ok); only used for the optional `gh auth login` in `setup-from-clone.sh`, the gateway never reads it | `com.cgfixit.cyclaw.gh-token` |

Claude is `ANTHROPIC_API_KEY` because that is the only name `llm/client.py`
reads.

## 401 / key drift recovery

Soul routes return `401 bad_credentials` when the Keychain item, the live gate
process environment, and the browser's console cookie disagree — usually after
`--rotate`, a reinstall, an expired cookie, or a leftover listener holding the
old key.

1. Stop stragglers on the configured loopback port (default 8787).
   `uninstall-cyclaw.sh` does this best-effort before teardown. After a
   rotate, `setup-cyclaw-keys.sh --restart-servers` frees the same port
   without starting the server and without a process-name sweep.
2. Re-run `bash macos/setup-cyclaw-keys.sh --skip-prompts` so the Keychain
   item exists. A new terminal does not need `CYCLAW_API_KEY` in its
   environment. `cyclaw` loads the Keychain item into that process.
3. Start with `cyclaw`. The startup log must not warn that `CYCLAW_API_KEY`
   is unset.
4. Start a new console session. Let `cyclaw` open its one-time `#pair=` URL, or
   enter the current key once. The page clears the key after it mints the
   HttpOnly cookie.

To **purge** stored credentials for this account (macOS: exact services in
`utils/secret-policy.tsv`; Linux: the API-key libsecret item and key file):

```bash
bash macos/uninstall-cyclaw.sh --remove-keychain          # prompts y/N
bash macos/uninstall-cyclaw.sh --remove-keychain --yes    # non-interactive
```

`--remove-home` deletes `~/.CyClaw` (including `.env`) and still leaves
Keychain items and Linux credentials unless `--remove-keychain` is also passed. A later
`setup-cyclaw-keys.sh` without `--rotate` will keep an existing Keychain
`CYCLAW_API_KEY` rather than mint a replacement.

## Linux launcher credentials and headless pairing

On Linux, `cyclaw` reuses an inherited `CYCLAW_API_KEY`, otherwise loads
libsecret (`secret-tool`) or `$XDG_CONFIG_HOME/cyclaw/api-key` (default
`~/.config/cyclaw/api-key`). First launch generates a key if neither store
has one. The file is owner-only (0600); malformed files are refused, including
extra records. Concurrent launchers serialize creation and reuse the winner.
An abandoned `.api-key.lock` causes a bounded failure: remove that empty lock
directory only after confirming no launcher or credential purge is running.

For a headless session, use `cyclaw --no-browser --print-pairing-url` and open
the printed URL from a browser that can reach the configured gateway. Normal
redirected output does not contain a pairing link. The explicit flag warns on
non-TTY stdout because the single-use, short-lived link is a credential: keep
it private and delete any saved copy after pairing. It contains no API key.

`uninstall-cyclaw.sh --remove-keychain` (see [401 recovery](#401--key-drift-recovery))
clears the exact libsecret service/account and the selected key file; run it
with the same `XDG_CONFIG_HOME` as at launch. If `secret-tool` is unavailable
or clearing fails, the uninstaller says the keyring still needs manual verification.

## `LaunchAgents/` — templates only

These plists are **not** installed or loaded by the installer.

| File | Prefer generating with |
|---|---|
| `com.cgfixit.cyclaw.fsconnect-trash.plist` | `python -m agentic.fsconnect.cli trash-empty-plist` |
| `com.cgfixit.cyclaw.telegram-poll.plist` | `python -m telegram.cli poll-plist` |
| `com.cgfixit.cyclaw.telegram-health.plist` | `python -m telegram.cli health-plist` |
| `com.cgfixit.cyclaw.opentweet.plist` | `python -m opentweet.cli schedule-plist` |

Generators write resolved paths and (for Telegram) chain the Keychain
wrapper so tokens never appear in the plist. They print a `launchctl
bootstrap` command; they never load the agent themselves.

The plist's interpreter is `CYCLAW_PYTHON` when set, else
`$CYCLAW_HOME/venv/bin/python` when it exists, else the Python running the
generator (`utils/launchd_plist.py`). `CYCLAW_PYTHON` may be a path or a command
name on `PATH` (the plist records the absolute path); a value that is neither
makes the generator refuse with exit 3 rather than pick another interpreter.
Whichever is chosen must import `fastapi` and `uvicorn`; if it cannot, the
generator refuses with exit 3 and writes nothing, because launchd would
otherwise restart a broken agent forever.

Hand-editing a template: replace every `REPLACE_*` value, create
`~/Library/Logs/CyClaw`, test `ProgramArguments` by hand, then copy to
`~/Library/LaunchAgents/` and load **explicitly**.

The separate gate generator writes
`~/Library/LaunchAgents/com.cgfixit.cyclaw.gate.plist` with output in
`~/Library/Logs/CyClaw/gate.log`. It runs `gate.py` directly, so it does not
perform the interactive launcher's secret bootstrap, dotenv loading, or
browser pairing. Pass `--api-key-service com.cgfixit.cyclaw.api-key` to load
that key at process start. Its `--config` option only changes the port reported
during generation; the generated process still reads the checkout's
`config.yaml`. LaunchAgents run in the user's login session; this is not a
system LaunchDaemon.

## Related

- Dropbox sync scheduling: [`docs/SYNC_README.md`](../docs/SYNC_README.md)
- Telegram channel: [`docs/channels/TELEGRAM_DESIGN.md`](../docs/channels/TELEGRAM_DESIGN.md)
- OpenTweet X channel: [`docs/channels/OPENTWEET_DESIGN.md`](../docs/channels/OPENTWEET_DESIGN.md)
- Connectors (fsconnect, netconnect): [`agentic/README.md`](../agentic/README.md)
