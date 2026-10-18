# `macos/` — POSIX install and launchd glue

Installer / launcher / launchd **glue** for macOS (Apple Silicon) and Linux.
Not request-path code: `gate.py`, `graph.py`, and `mcp_hybrid_server.py` never
import anything here (I6). The Windows sibling is `powershell/`.

After install, `cyclaw` starts the RAG gateway (`127.0.0.1:8787`). Mutable
state lives under `~/.CyClaw`.


## Scripts

| Script | What it does |
|---|---|
| `setup-cyclaw.sh` | **One-command onboarding (#1053).** Clones when no checkout is found, runs `setup-from-clone.sh --no-start`, then optionally starts the gateway, opens the loopback console, and autofills the generated key into `#apiKeyInput` (browser memory only). Works standalone: download just this file. Own flags: `--repo PATH`, `--clone-dir PATH`, `--start`/`--no-start`, `--browser`/`--no-browser`, `--autofill-api-key`/`--no-autofill-api-key`, `--skip-prompts`, `--dry-run`; everything else is forwarded to `setup-from-clone.sh`. It adds no installer or secret store of its own; `--help` is authoritative. |
| `setup-from-clone.sh` | **One-shot after `git clone`** (Apple Silicon). Chains `install-cyclaw.sh` + `setup-cyclaw-keys.sh` (prompts for Telegram / Claude / Grok / GitHub), checks Ollama, builds the index, then starts the gateway. Common flags: `--dry-run`, `--skip-prompts` (implies no start; add `--start`), `--no-start`, `--small-model`, `--ollama-model TAG`; also `--skip-install`, `--skip-python-deps`, `--skip-keys`, `--skip-ollama`, `--skip-index`, `--skip-privacy`, `--no-browser`, `--no-fsconnect`, `--no-profile-edit`, `--no-path-edit`, `--grok-dummy`, `--rotate-key`, `--ollama-install-script`, `--yes`. Use it directly for scripted runs. |
| `install-cyclaw.sh` | Home layout, venv, `cyclaw` shim, optional PATH / rc function. `--repo-path`, `--replace-repo`, `--skip-python-deps`, `--no-profile-edit`, `--no-path-edit`, `--no-fsconnect`. `--replace-repo` is destructive only for an unusable directory at the default `~/.CyClaw/repo` target; it does not apply with `--repo-path`. |
| `uninstall-cyclaw.sh` | Removes the rc function, PATH entry, and the `cyclaw keys` source block; strips a secret-classified line from `~/.CyClaw/.env` or `~/.CyClaw/repo/.env` only when the Keychain value reads back byte-equal (skipped with `--remove-keychain`, so the purge never deletes the only copy). Does not follow `CYCLAW_REPO`. Keeps `~/.CyClaw` unless `--remove-home`; `--remove-fsconnect` optional. `--remove-keychain` (prompted y/N; `--yes`/`--assume-yes` confirms already-requested destructive flags only) removes the Linux libsecret item and key file, or on macOS every exact `com.cgfixit.cyclaw.*` service named in `utils/secret-policy.tsv` for `id -un` — never a wildcard or a secret value. Best-effort unschedules Dropbox sync, `launchctl bootout`s CyClaw LaunchAgent labels (telegram-poll/health, fsconnect-trash, gate, keys-rotate, opentweet, sync, the retired `harness`), then frees a leftover listener on `CYCLAW_GATE_PORT` (default 8787). |
| `invoke-cyclaw.sh` | Starts `python gate.py` from `~/.CyClaw/venv`, preserving the bind guard, `api.tls`, and `proxy_headers=False`. Loads non-secret settings from `~/.CyClaw/.env`, then secrets from the keystore into that process only. `--gate-port` / `CYCLAW_GATE_PORT` override `api.port` (default 8787); the console URL follows `api.host`, `api.tls.enabled`, and that port via `utils/gateway_url.py`. `--no-browser` / `--repo`. `--print-pairing-url` prints the one-time link for headless use (warns on redirected stdout). With no stored `CYCLAW_API_KEY` it runs `setup-cyclaw-keys.sh --skip-prompts` (no profile edit, no dotenv write) to generate one, then opens the console at a single-use `#pair=` link (`CYCLAW_CONSOLE_PAIRING_CODE`, `security.console_pairing_ttl_sec`) so operator tools arrive unlocked without the key reaching the page. |
| `cyclaw-linux-key.sh` | Sourced by `invoke-cyclaw.sh` on Linux: libsecret (`secret-tool`, service `com.cgfixit.cyclaw.api-key`) first, then `$XDG_CONFIG_HOME/cyclaw/api-key` (0700/0600; symlinked, foreign-owned, group-readable, or malformed files are refused). The key never becomes an argv token. Details: [Linux launcher credentials](#linux-launcher-credentials-and-headless-pairing). |
| `setup-cyclaw-keys.sh` | Apple Silicon key bootstrap. Autogenerates `CYCLAW_API_KEY`; prompts for Telegram / Claude (`ANTHROPIC_API_KEY`) / Grok / GitHub (skip allowed). Secrets go to the Keychain; `~/.CyClaw/.env` (chmod 600) keeps ordinary settings and receives secret-classified names only with `--write-env-file`. Re-running moves plaintext secret lines into the Keychain and removes them (no backup). `--rotate`, `--no-env-file`, `--fill-browser` (loopback `#apiKeyInput` only; the console trades the key for its signed HttpOnly cookie and clears the field), `--schedule-rotate monthly\|weekly\|never` (writes, never loads, a LaunchAgent), `--unschedule-rotate`, `--restart-servers` (frees the gate port after a write; does not start the server). Also `--no-keychain`, `--no-repo-env`, `--print-key`/`--no-print-key`, `--copy-key`/`--no-copy-key`, `--clipboard-ttl N`, `--open-consoles`, `--gate-port`, `--repo-path`, `--skip-prompts`, `--grok-dummy`. |
| `cyclaw-keychain-load.sh` | Shared sourced helper for onboarding and launchers. Filters dotenv settings, scrubs secret-classified dotenv values, and loads allowed Keychain items into the process. |
| `cyclaw-public-env.sh` | Sourced by the rc block. Exports non-secret dotenv settings. Reads the secret classification from `utils/secret-policy.tsv` (shared with Python and PowerShell) and refuses to run without it. |
| `setup-fsconnect.sh` | Creates confined `~/CyClaw-FS` (`chmod 700`). Unless `--prepare-only`, enables list/stat/read via `_enable_fsconnect_readlist.py`. |
| `_enable_fsconnect_readlist.py` | Writes the confined read/list `fsconnect:` profile into `config.yaml` (writes stay off). |
| `cyclaw-keychain-set.sh` | Interactive Keychain store. Bare `-w` (secret never in argv); `-T /usr/bin/security`. Requires a TTY. |
| `cyclaw-keychain-env.sh` | Fetch one Keychain item, export it, `exec` the wrapped command. Fail-closed if missing/empty. |
| `generate_service_plist.py` | Supervised LaunchAgent for `gate.py` (`--service gate`). Highest-risk generator: refuses to write without `--confirm` **and** a non-empty `--reason`. `KeepAlive: {SuccessfulExit: false}` (crash-only restart, never after a clean stop), `ThrottleInterval` 30s default, optional `--api-key-service` chains the Keychain wrapper. Never loads the agent itself. |
| `ollama-mlx.env` | KEY=value tunings sourced before `ollama serve` (context 32768, keep-alive 30m, one model, no parallel slots, flash-attn + KV q8_0). No secrets. `setup-from-clone.sh` sources it when *it* launches Ollama; an already-running .app ignores it until quit. |
| `Modelfile.cg` | Optional one-time derived tag `qwen3.8:27b-mlx-cg` (`PARAMETER num_ctx 32768`). Not created by any script. The shipped default stays `qwen3.8:27b-mlx`. See `docs/! How-To-Guides/OLLAMA_SETUP.md`. |

Target shells: bash (including macOS 3.2) and zsh. BSD userland on macOS —
no Homebrew required.

## One command (Apple Silicon)

`setup-cyclaw.sh` is the single entry point for a fresh machine — clone,
install, keys, index, start, browser, with the choices asked once up front:

```bash
bash macos/setup-cyclaw.sh          # inside a clone, or standalone (it offers to clone)
```

Interactive prompts need a real Terminal, not a piped stdin; pass
`--skip-prompts` for a non-interactive run. Onboarding, the launcher, and key
setup share one console URL resolver (`utils/gateway_url.py`) when the checkout
and Python dependencies are present: wildcard bind addresses become loopback
browser destinations, and standalone key setup falls back to
`http://127.0.0.1:<port>`.

## One-shot after clone (Apple Silicon)

`setup-from-clone.sh` is the path `setup-cyclaw.sh` calls. It chains the
scripts above to fill the four holes `setup-guide.md`'s Option A leaves open
(Ollama, the retrieval index, API keys, starting the server). Use it directly
for scripted runs that do not want clone detection or browser autofill:

```bash
git clone https://github.com/CGFixIT/CyClaw.git && cd CyClaw
bash macos/setup-from-clone.sh
```

Secrets are never logged, written to `config.yaml`, or placed on a child
argv; they persist in the Keychain via `setup-cyclaw-keys.sh`, ordinary
settings in `~/.CyClaw/.env` (chmod 600). fsconnect writes and indexing stay
off, and no LaunchAgent is generated or loaded (those need `--confirm --reason`).

## Key bootstrap

`setup-cyclaw-keys.sh` is the operator-facing path for the env vars
`setup-guide.md` otherwise tells you to `export` by hand. It is Darwin /
arm64 only (CyClaw's torch pin has no Intel macOS wheel).

`~/.CyClaw/.env` (mode 600) is the default home for ordinary settings:
ports, paths, mode flags, model names, and feature toggles. New shells
load that file through the `# >>> cyclaw keys >>>` block, which does not
export secret-classified names. If `CYCLAW_HOME` was set when the keys
script ran, the block follows that directory instead of `~/.CyClaw`.

`utils/secret-policy.tsv` (shared with the Python and PowerShell loaders)
defines secret classification: an `exact` name row, each mapped to its
Keychain service (`CYCLAW_API_KEY`, `TELEGRAM_BOT_TOKEN`, `GROK_API_KEY`,
`ANTHROPIC_API_KEY`, `GH_TOKEN`/`GITHUB_TOKEN`, `CYCLAW_SQL_DSN`, the
`CYCLAW_*_DB_URL` family, `RCLONE_CONFIG_PASS`, …), or a `suffix` row
(`API_KEY`, `CREDENTIALS`, `PASSWORD`, `SECRET`, `TOKEN`, `PAT`, `DSN`,
`DB_URL`, `KEY`). Those values live in the Keychain, and `cyclaw` and launchd
read them into the CyClaw process only. `--write-env-file` is the explicit
opt-in that also writes them into the dotenv; the rc block and the launchers
still never export those lines.

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
| `GH_TOKEN` (+ `GITHUB_TOKEN`) | Prompt (skip ok) | `com.cgfixit.cyclaw.gh-token` |

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

The plist's interpreter is `CYCLAW_PYTHON` when it names an existing file,
else `$CYCLAW_HOME/venv/bin/python` when it exists, else the Python running the
generator (`utils/launchd_plist.py`). A `CYCLAW_PYTHON` that names no file is
not an error: the generator falls back to `python3`/`python` on `PATH`, so check
the interpreter in the printed plist. Whichever is chosen must import `fastapi`
and `uvicorn`; if it cannot, the generator refuses with exit 3 and writes
nothing, because launchd would otherwise restart a broken agent forever.

Hand-editing a template: replace every `REPLACE_*` value, create
`~/Library/Logs/CyClaw`, test `ProgramArguments` by hand, then copy to
`~/Library/LaunchAgents/` and load **explicitly**.

## Related

- Dropbox sync scheduling: [`docs/SYNC_README.md`](../docs/SYNC_README.md)
- Telegram channel: [`docs/channels/TELEGRAM_DESIGN.md`](../docs/channels/TELEGRAM_DESIGN.md)
- OpenTweet X channel: [`docs/channels/OPENTWEET_DESIGN.md`](../docs/channels/OPENTWEET_DESIGN.md)
- Agentic / registry: [`agentic/README.md`](../agentic/README.md)
