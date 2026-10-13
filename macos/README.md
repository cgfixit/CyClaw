# `macos/` — POSIX install and launchd glue

Installer / launcher / launchd **glue** for macOS (Apple Silicon) and Linux.
Not request-path code: `gate.py`, `graph.py`, and `mcp_hybrid_server.py` never
import anything here (I6). The Windows sibling is `powershell/`.

After install, `cyclaw` starts the RAG gateway (`127.0.0.1:8787`). Mutable
state lives under `~/.CyClaw`.


## Scripts

| Script | What it does |
|---|---|
| `setup-cyclaw.sh` | **The one-command onboarding entry point (#1053).** Wraps everything below into a single operator decision: clone (if no checkout is found), run `setup-from-clone.sh --no-start`, then optionally start the gateway, open the loopback console, and autofill the generated key into `#apiKeyInput` in browser memory only. Works standalone too — download just this file and it offers to clone. `--repo PATH`, `--clone-dir PATH`, `--start`/`--no-start`, `--browser`/`--no-browser`, `--autofill-api-key`/`--no-autofill-api-key`, `--skip-prompts`, `--dry-run`; forwards its remaining flags (`--skip-install`, `--skip-keys`, `--small-model`, `--ollama-model TAG`, etc.) straight to `setup-from-clone.sh`. It does not reimplement installation or key persistence — every write still goes through the scripts below. Run it with `--help` for the authoritative flag list. |
| `setup-from-clone.sh` | **One-shot after `git clone`** on Apple Silicon. Chains `install-cyclaw.sh` + `setup-cyclaw-keys.sh` (prompts for Telegram / Claude / Grok / GitHub), checks Ollama, builds the retrieval index, then starts the gateway. `--dry-run`, `--skip-prompts`, `--no-start`, `--small-model`, `--ollama-model TAG`. Note `--skip-prompts` implies no server start; pass `--start` to launch anyway. The script accepts a wider flag set than the common ones listed here — including `--skip-install`, `--skip-python-deps`, `--skip-keys`, `--skip-ollama`, `--skip-index`, `--skip-privacy`, `--no-browser`, `--no-fsconnect`, `--no-profile-edit`, `--no-path-edit`, `--grok-dummy`, `--rotate-key`, `--ollama-install-script`, and `--yes`; run it with `--help` for the authoritative list. Called directly, it is the multi-question path `setup-cyclaw.sh` exists to front. |
| `install-cyclaw.sh` | Home layout, venv, `cyclaw` shim, optional PATH / rc function. `--repo-path`, `--replace-repo`, `--skip-python-deps`, `--no-profile-edit`, `--no-path-edit`, `--no-fsconnect`. `--replace-repo` is intentionally destructive only for an unusable directory at the default `~/.CyClaw/repo` clone target; it does not apply with `--repo-path`. |
| `uninstall-cyclaw.sh` | Removes the rc function, PATH entry, and the `cyclaw keys` source block. Strips an allowlisted secret line from `~/.CyClaw/.env` or `~/.CyClaw/repo/.env` only when the Keychain value read back is byte-equal, and leaves ordinary settings. Does not follow `CYCLAW_REPO`. `--remove-keychain` skips that strip so the purge is not also the only copy. Keeps `~/.CyClaw` unless `--remove-home`. Optional `--remove-fsconnect`. Optional `--remove-keychain` (prompted y/N) removes the Linux API-key libsecret item and selected key file; on macOS it lists, counts, then deletes every exact `com.cgfixit.cyclaw.*` Keychain service named in `utils/secret-policy.tsv` for `id -un` — never a wildcard, never a secret value. `--yes` / `--assume-yes` confirms already-requested destructive flags only. Best-effort unschedules Dropbox sync, `launchctl bootout`s CyClaw LaunchAgent labels (telegram-poll/health, fsconnect-trash, gate, keys-rotate, opentweet, sync, plus the retired console's `harness` label), then frees a leftover loopback listener on `CYCLAW_GATE_PORT` (default 8787). |
| `invoke-cyclaw.sh` | Starts `python gate.py` from `~/.CyClaw/venv`, preserving the bind guard, `api.tls`, and `proxy_headers=False`. Loads non-secret settings from `~/.CyClaw/.env`, then secrets from the Keychain into that process only. `--gate-port` / `CYCLAW_GATE_PORT` select the port (default 8787, overriding `api.port`); the console URL follows `api.host`, `api.tls.enabled`, and that effective port via `utils/gateway_url.py`. `--no-browser` / `--repo` select browser behavior and checkout. `--print-pairing-url` explicitly prints the one-time link for headless use; redirected stdout triggers a secret-link warning. On first run with no `CYCLAW_API_KEY` in the Keychain it runs `setup-cyclaw-keys.sh --skip-prompts` (no profile edit, no dotenv write) to generate one. It opens the console at a one-time `#pair=` link (`CYCLAW_CONSOLE_PAIRING_CODE`, single-use, `security.console_pairing_ttl_sec`), so operator tools arrive unlocked without the key reaching the page. |
| `setup-cyclaw-keys.sh` | Apple Silicon key bootstrap. Autogenerates `CYCLAW_API_KEY`; prompts for Telegram / Claude (`ANTHROPIC_API_KEY`) / Grok / GitHub (skip allowed). Secrets go to the Keychain. `~/.CyClaw/.env` (chmod 600) stays the home for ordinary settings and does not receive secret-classified names unless `--write-env-file` is set. Re-running moves allowlisted plaintext lines into the Keychain and removes those lines (no backup). `--rotate`, `--no-env-file`, `--fill-browser` (loopback `#apiKeyInput` only; the console trades the key for its own signed HttpOnly cookie and clears the field, so the key never reaches localStorage), `--schedule-rotate monthly\|weekly\|never` (writes, never loads, a LaunchAgent), `--unschedule-rotate` (removes that LaunchAgent again), `--restart-servers` (best-effort free the configured gate loopback port after a write; does not start the server). Further flags exist — `--no-keychain`, `--no-repo-env`, `--print-key`/`--no-print-key`, `--copy-key`/`--no-copy-key`, `--clipboard-ttl N`, `--open-consoles`, `--gate-port`, `--repo-path`, `--skip-prompts`, `--grok-dummy`; run it with `--help` for the authoritative list. |
| `cyclaw-keychain-load.sh` | Shared sourced helper for onboarding and launchers. Filters dotenv settings, scrubs secret-classified dotenv values, and loads allowed Keychain items into the process. |
| `cyclaw-public-env.sh` | Sourced by the rc block. Exports non-secret dotenv settings. Defines the secret classification (allowlist plus `*_API_KEY` / `*_TOKEN` / `*_SECRET` / `*_PASSWORD`). |
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

`setup-cyclaw.sh` is (arguably) the single entry point for a fresh machine — clone,
install, keys, index, start, browser, in that order, with the choices asked
once up front instead of scattered across several scripts' worth of prompts:

```bash
bash macos/setup-cyclaw.sh          # inside a clone
```

It offers to clone when no checkout is found, so the same file also works
standalone: download `macos/setup-cyclaw.sh` by itself and run
`bash setup-cyclaw.sh` (interactive prompts need a real Terminal, not a
piped stdin — pass `--skip-prompts` for a non-interactive run instead). It
delegates to `setup-from-clone.sh` for the actual install/keys/index work
below — it adds no second secret store or installer of its own.

Onboarding, the launcher, and key setup use the same console URL resolver
when the checkout and Python dependencies are available. Wildcard bind
addresses become loopback browser destinations. Standalone key setup still
works without a checkout, using its default `http://127.0.0.1:<port>` URL.

## One-shot after clone (Apple Silicon)

`setup-from-clone.sh` is the operator-facing "I just cloned this, make it
run" path that `setup-cyclaw.sh` calls. It does **not** reimplement the
scripts above — it chains them and fills the four holes `setup-guide.md`
documents that Option A leaves open (Ollama, the retrieval index, API keys,
and starting the server). Use it directly for scripted/CI-style runs where the
extra clone-detection and browser-autofill layer isn't wanted.

```bash
git clone https://github.com/CGFixIT/CyClaw.git && cd CyClaw
bash macos/setup-from-clone.sh
```

Privacy matches `cyclaw-privacy`: secrets are never logged, never written
to `config.yaml`, never placed on a child process argv. Secrets persist in
the Keychain via `setup-cyclaw-keys.sh`. Ordinary settings persist in
`~/.CyClaw/.env` (chmod 600).
fsconnect writes and indexing stay off. LaunchAgents are **not** generated
or loaded (those still need `--confirm --reason`).

## Key bootstrap

`setup-cyclaw-keys.sh` is the operator-facing path for the env vars
`setup-guide.md` otherwise tells you to `export` by hand. It is Darwin /
arm64 only (CyClaw's torch pin has no Intel macOS wheel).

`~/.CyClaw/.env` (mode 600) is the default home for ordinary settings:
ports, paths, mode flags, model names, and feature toggles. New shells
load that file through the `# >>> cyclaw keys >>>` block, which does not
export secret-classified names. If `CYCLAW_HOME` was set when the keys
script ran, the block follows that directory instead of `~/.CyClaw`.

A name is secret-classified when it is on the allowlist in
`macos/cyclaw-public-env.sh` (`CYCLAW_API_KEY`, `TELEGRAM_BOT_TOKEN`,
`GROK_API_KEY`, `ANTHROPIC_API_KEY`, `GH_TOKEN`, `GITHUB_TOKEN`,
`CLAUDE_API_KEY`) or when it ends in `_API_KEY`, `_TOKEN`, `_SECRET`, or
`_PASSWORD`. Those values live in the Keychain. `cyclaw` and launchd read
them into the CyClaw process only. `--write-env-file` is the explicit
opt-in that also writes them into the dotenv; the rc block and the
launchers still do not export those lines.

Re-running the keys script copies each allowlisted secret into the Keychain
when that item is missing, then removes the plaintext line only when the
value read back is byte-equal. A mismatch keeps the line and warns. Other
lines stay. No backup file is written. A pattern match that has no Keychain
service is left in place and is not loaded. If the Keychain store fails,
the plaintext line stays, because it is still the only copy.

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
process environment, and the browser's console cookie disagree. This usually
follows `--rotate`, a reinstall, an expired cookie, or a leftover listener that
still holds the old key. CyClaw never stores the operator key in `localStorage`
and does not read that secret from `~/.CyClaw/.env`.

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

`uninstall-cyclaw.sh --remove-keychain` prompts before clearing the exact
libsecret service/account and deleting the selected key file. Add `--yes` for
an intentional noninteractive purge. Ordinary uninstall and `--remove-home`
alone keep those credentials. Use the same `XDG_CONFIG_HOME` as at launch;
unrelated files are retained. If `secret-tool` is unavailable or clearing it
fails, the uninstaller reports that the keyring still needs manual verification.

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

Hand-editing a template: replace every `REPLACE_*` value, create
`~/Library/Logs/CyClaw`, test `ProgramArguments` by hand, then copy to
`~/Library/LaunchAgents/` and load **explicitly**.

## Related

- Dropbox sync scheduling: [`docs/SYNC_README.md`](../docs/SYNC_README.md)
- Telegram channel: [`docs/channels/TELEGRAM_DESIGN.md`](../docs/channels/TELEGRAM_DESIGN.md)
- OpenTweet X channel: [`docs/channels/OPENTWEET_DESIGN.md`](../docs/channels/OPENTWEET_DESIGN.md)
- Agentic / registry: [`agentic/README.md`](../agentic/README.md)
