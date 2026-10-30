# CyClaw Sync — Rclone Dropbox Corpus Integration

Out-of-band Dropbox-to-corpus mirroring via `rclone`, with per-file audit
events in `logs/audit.jsonl` and no new Python dependencies. Run
`python -m sync.cli` manually or through cron, launchd, Windows Task Scheduler,
or an operator-written systemd timer. Authenticated loopback `POST /ops/sync`
uses `utils/ops_runner.py` argv-list subprocesses; core never imports sync.

---

## File layout

See the [module map](../sync/README.md) for config, filters, runner,
scheduler, CLI, and self-tests. `sync/scheduled.py` wraps scheduled execution
with credential-store loading. Focused tests live under `tests/test_sync_*.py`.

The Dropbox refresh token lives **only** in `rclone.conf`, owned by your user.
CyClaw's process never sees it; it is never written to `config.yaml`, the repo,
the audit log, or any argv.

---

## Security posture (read this before you sync anything)

| Default | Why |
|---|---|
| **`direction: pull`** | `rclone copy` never deletes at the destination. One-way pull is the safest default for an RAG corpus. Bidirectional `bisync` is a silent-rewrite path into governed state. |
| **`include_soul` deprecated** | `data/personality/` is governed via `POST /soul/apply` with a human reason string and an injection scan. Sync can never touch it: `local_path` must resolve inside `data/corpus`, and the soul filter rule is unconditional. The `include_soul` key remains only so old configs load; it has no effect. |
| **Hardened exclude list** | Model weights, indices, caches, venvs, logs, secrets, `.git`, and the soul DB (`*.db*`) are all excluded by default. See `sync/filters.py`. |
| **`max_delete: 20`** | rclone aborts the run if more than 20 deletions would occur (bisync only; pull never deletes). Tune up only when you understand exactly why. |
| **Per-file SHA-256 audit** | Added/modified file events include a SHA-256 hash when the local file resolves inside the corpus and can be read. Otherwise the audit row has an empty `sha256`. |
| **No in-process gateway import** | No graph node or edge. The six core modules never import `sync/`. Optional `POST /ops/sync` reaches it through the `require_api_key`-guarded subprocess shim in `utils/ops_runner.py`. The only outbound call is still `rclone` to Dropbox. |
| **Zero new deps** | stdlib + existing `pyyaml`/`utils.*` only. `rclone` is an external binary, installed out-of-band like Ollama. |

If an old config still sets `include_soul: true`, `python -m sync.cli setup` prints a
`[WARN]` noting the flag has no effect — soul data is never mirrored, because the
sync root is confined to `data/corpus` and the soul filter rule is unconditional.

### Why these invariants hold

Sync only changes files on disk that the indexer consumes later, so `retrieve`
stays the graph entry (I1) and no node or edge is added (I2). Dropbox is
contacted only by the `rclone` subprocess you invoke, never by a query (I3).
Events land in the same `audit.jsonl` with the same redaction (I4), and
`data/personality/**` plus `*.db*` are excluded so a synced file can never
reach `soul.md` or `cyclaw_soul.db` around the `POST /soul/apply` scan (I5).

---

## Step 1 — Install rclone (**≥ 1.68.2**)

A hard floor of **rclone ≥ 1.68.2** is enforced at runtime. This version fixes
**CVE-2024-52522** (insecure symlink handling with `--links`/`--metadata`).
CyClaw never passes `--links` or `--metadata`, but the floor is asserted anyway
as defense in depth. Older rclone → `RCLONE_VERSION_TOO_OLD` (exit 3).

### Linux / macOS / WSL
```bash
curl https://rclone.org/install.sh | sudo bash
```

### Windows
```powershell
winget install Rclone.Rclone
```

Verify:
```bash
rclone version   # must show v1.68.2 or higher
```

After install, restrict the config file once you've authenticated:
```bash
chmod 600 ~/.config/rclone/rclone.conf      # Linux/macOS; restrict ACLs on Windows
```

---

## Step 2 — Create an App-Folder-scoped Dropbox remote

Use an **App Folder**-scoped Dropbox app (least privilege), **not** Full
Dropbox. Run rclone's interactive config and complete the browser OAuth flow:

```bash
rclone config
# n) New remote
# name>  dropbox_cyclaw         (must match config.yaml remote_name)
# Storage>  dropbox
# Use App Folder access (scoped), not Full Dropbox.
# Complete the browser OAuth — choose "offline access".
```

The resulting **refresh token lives only in `rclone.conf`**
(`~/.config/rclone/rclone.conf`, or `%APPDATA%\rclone\rclone.conf` on Windows),
owned by your user, managed entirely by rclone. CyClaw never holds it.

For unattended jobs, encrypt `rclone.conf` using `rclone config` →
`s) Set configuration password`; reversible `rclone obscure` is insufficient.
Store `RCLONE_CONFIG_PASS` in Keychain/Credential Manager and use generated
`sync.scheduled` jobs. Never put it in YAML, dotenv, scheduler arguments, or
plists. The child receives sync discovery variables and that password only.
Encryption protects storage; running rclone necessarily receives the password.

---

## Step 3 — Edit the `sync:` block in `config.yaml`

The `sync:` block contains metadata, not secrets. A missing or empty block is
a configuration error. Set `enabled: false` to disable syncing explicitly;
a valid block without an `enabled` key defaults to enabled.

```yaml
sync:
  enabled: false                 # off by default; `sync.cli sync` no-ops (exit 0) while false
  local_path: "data/corpus"      # validated: absolute, under repo data/corpus, a dir
  remote_name: "dropbox_cyclaw"  # must match `rclone listremotes`
  remote_path: "CyClaw/corpus"   # folder inside the Dropbox App Folder
  direction: "pull"              # "pull" (safe default) | "bisync" (opt-in, discouraged)
  include_soul: false            # deprecated no-op — soul is never mirrored (sync root confined to data/corpus)
  reindex_on_change: true        # exit 10 when data/corpus/** changed
  checksum: true                 # rclone --checksum (hash compare, not mtime)
  max_delete: 20                 # bisync fuse: abort if > N deletions (pull never deletes)
  max_transfer: "1G"             # fuse: rclone stops once this much has transferred
  schedule_hour: 2               # 24h local time (cron / Task Scheduler)
  schedule_min: 0
  conflict_resolve: "newer"      # bisync-only: newer modtime wins
  conflict_loser: "rename"       # bisync-only: loser saved as .conflict1 (never deleted)
  # extra_excludes:              # optional, appended AFTER the hardened block
  #   - "scratch/**"
```

---

## Step 4 — Validate

```bash
cd /path/to/CyClaw

# Pre-flight self-test (rclone present + version, config valid,
# filter file writable, remote reachability dry-run, soul-exclusion asserted)
python -m sync.cli test

# The pytest unit suite (mocked, no network)
pytest tests/test_sync_*.py
```

Without rclone, `setup` exits **3** (`RCLONE_NOT_INSTALLED`), `test` **2**,
and informational `status` **0** with an error message. Inspect status text.
Unreadable/malformed config exits **3** (`SYNC_CONFIG_INVALID`).

---

## Daily usage

```bash
python -m sync.cli setup             # validate config + write filter file + print OAuth steps
python -m sync.cli setup --schedule  # also register the daily job in one shot
python -m sync.cli sync --dry-run    # preview — no corpus or remote changes
python -m sync.cli sync              # live sync (pull by default)
python -m sync.cli status            # current state + last schedule
python -m sync.cli schedule          # (re-)register the daily job
python -m sync.cli unschedule        # remove the daily job
```

Sync is invoked **only** via `python -m sync.cli`; it is never imported by the
gateway or the graph.

A `--dry-run` leaves corpus/remote content unchanged but writes its filter,
log, and overlap-lock support files. It emits no audit rows.

### Exit codes

| Code | Meaning | Caller action |
|---|---|---|
| 0 | Successful operation, disabled sync, or successful automatic reindex | inspect the command output; restart the gateway after an automatic rebuild |
| **10** | Corpus changed and the caller must reindex; this can follow a partial failed sync | inspect the sync result, run `python -m retrieval.indexer`, then **restart the gateway** |
| 1 | Aborted by a safety fuse (`--max-delete` / `--max-transfer`) | investigate the remote; do **not** blindly raise the fuse |
| 2 | Sync failed (other) | inspect the audit log / rclone log |
| 3 | Config / environment problem (rclone missing or old, config invalid) | fix per the error details |

Exit 10 signals a reindex obligation, not proof of a successful sync. Inspect
the rclone log and `sync_failed` audit events for a partial failure. With
`auto_reindex: true`, the CLI runs the indexer instead of returning 10; a
caught sync error still returns failure even if that rebuild succeeds.

A failed `--dry-run` returns the same 1, 2 or 3 as a real run. A dry run never
returns 10: it previews changes only, so there is nothing to reindex.

A standalone reindex needs a gateway restart to load the new retriever. The
separate `POST /index/build` route rebuilds in the gateway and replaces its
retriever after a successful build.

### Cron-friendly reindex chain

```bash
python -m sync.cli sync; rc=$?
if [ "$rc" -eq 10 ]; then
    python -m retrieval.indexer       # full rebuild: Chroma + BM25
    # then restart the gateway so it loads the new index
fi
```

`retrieval.indexer` runs as a **separate process** — never inline, never in the
gateway event loop.

---

## Scheduling

`python -m sync.cli schedule` registers a single tagged job and is idempotent
(re-running replaces our own entry, never touches yours). Which mechanism it
uses is `sync.scheduler_backend` in `config.yaml` (default `"cron"`); how
often it fires is `sync.schedule_frequency` (default `"daily"`; `"weekly"`
uses `sync.schedule_weekday`, `"monthly"` uses `sync.schedule_day`).

| Platform | Backend | Mechanism | Tag / identity |
|---|---|---|---|
| Linux / macOS / WSL | `cron` (default) | `crontab` via `crontab -l` / `crontab -` (never `crontab -e`). Maps `daily` to `MIN HOUR * * *`, `weekly` to `MIN HOUR * * WEEKDAY`, and `monthly` to `MIN HOUR DAY * *`. | comment `CYCLAW_DROPBOX_SYNC` |
| macOS only | `launchd` (opt-in: `scheduler_backend: "launchd"`) | Generates `~/Library/LaunchAgents/com.cgfixit.cyclaw.sync.plist` via `plistlib` from real, resolved install paths — no `REPLACE_*` placeholders to hand-edit. Supports `daily`/`weekly`/`monthly` via `StartCalendarInterval`. **`install()` never calls `launchctl load`/`bootstrap`** — it prints the exact `launchctl bootstrap gui/<uid> <path>` command; loading a persistent background agent is always an explicit operator step. `remove()` best-effort `launchctl bootout`s before deleting the file. No secret/token is embedded; `sync.scheduled` retrieves the config password at execution time, and rclone owns its OAuth state. | `Label` `com.cgfixit.cyclaw.sync` |
| Windows | (only option) | `schtasks /Create` with `/SC DAILY`, `/SC WEEKLY /D <weekday>`, or `/SC MONTHLY /D <day>`, plus `/ST HH:MM /RL LIMITED /F`. | task name `CyClaw Dropbox Sync` |

Schedules use the repository working directory and `python -m sync.scheduled`,
which loads the encrypted-config password before invoking sync. Nondefault
config paths propagate. Cron quotes tokens; Windows uses a quoted `.bat`
with doubled `%`; launchd executes an argument array without a shell.
Paths containing spaces or shell metacharacters remain literal.

> **Overlap protection:** `run_sync` holds a single-instance OS-backed lock on
> `sync.lock` under the rclone log dir (PID + start timestamp while held), so a
> scheduled and a manual run cannot drive rclone concurrently; the second exits
> `SYNC_RUNTIME_ERROR`. The OS releases the lock on clean exit or crash; the
> empty file remains for reuse and does not mean a sync is active, so never
> delete it mid-run. The lock lives in `run_sync`, so every backend shares it.
>
> A systemd `--user` `Type=oneshot` service plus timer adds journald logging
> and `Persistent=true` catch-up on Linux; cron stays the implemented portable
> baseline and `sync/scheduler.py` generates no systemd unit. launchd design
> and validation limits: `docs/work/MACOS_LAUNCHD_INTEGRATION_PLAN.md` (CI does
> not prove a live `launchctl` load); the fsconnect and Telegram CLIs ship the
> same generate-only plist pattern ([`macos/README.md`](../macos/README.md)).

---

## Conflict resolution (bisync mode only)

`direction: bisync` is **opt-in and discouraged.** If you enable it:

| Scenario | Behavior |
|---|---|
| Both sides changed the same file | rclone detects via its `.lst` baseline |
| Winner | Newer `modtime` wins (`conflict_resolve: newer`) |
| Loser | Renamed `.conflict1` — **never silently deleted** |
| Your job | Review `.conflict*` files, delete the unwanted version |
| Next sync | Your choice propagates to both sides |

---

## What is NOT synced (filter exclusions)

| Pattern | Reason |
|---|---|
| `data/personality/**` | Soul layer — governed via `POST /soul/apply`, never via file replication |
| `*.gguf`, `*.bin`, `*.safetensors`, `*.onnx`, `*.pt`, `*.pth` | AI model weights — managed locally |
| `index/**`, `.chroma/**` | ChromaDB + BM25 — rebuildable via `python -m retrieval.indexer` |
| `.emb_cache/**` | embeddings cache — auto-downloads |
| `venv/**`, `.venv/**`, `env/**` | virtualenvs — rebuild with the hashed-lock install in `setup-guide.md` (torch first) |
| `__pycache__/**`, `*.pyc`, `*.pyo` | bytecode |
| `logs/**`, `*.log`, `*.jsonl` | local forensic data incl. `audit.jsonl` — never share across machines |
| `.env`, `*.pem`, `*.key`, `*_secret*`, `credentials*` | secrets |
| `*.db`, `*.db-wal`, `*.db-shm` | governed soul DB state (`cyclaw_soul.db`) |
| `.git/**`, `.gitignore` | use `git push/pull` separately |
| `.DS_Store`, `Thumbs.db`, `desktop.ini`, `.idea/**`, `.vscode/**` | OS/editor noise |
| `.rclone-state/**`, `*.rclone.lst*` | rclone's own state |

`extra_excludes:` in the `sync:` block is appended **after** the hardened block.
First-match-wins, most-restrictive-first — you can tighten further but cannot
accidentally re-include something the hardened rules already excluded.

---

## Audit events

Every real (non-dry-run) sync run emits these into `logs/audit.jsonl` via
`utils.logger.audit_log()` — the same path the gateway uses, with the same PII
redaction. Only metadata is logged; never a token and never raw rclone stderr
that could echo a secret. A `--dry-run` preview emits none of these rows (its
events describe what rclone *would* copy, not what changed).

| Event | When | Key fields |
|---|---|---|
| `sync_started` | run begins | `direction`, `dry_run`, `remote`, `local_path` |
| `sync_file_added` | per file | `file`, `sha256` |
| `sync_file_modified` | per file | `file`, `sha256` |
| `sync_file_deleted` | per file | `file` (no hash — bytes gone) |
| `sync_completed` | success | `direction`, `duration_sec`, `rclone_exit_code`, `counts`, `errors_n`, `aborted_for_safety`, `dry_run`, `corpus_changed` |
| `sync_failed` | failure (rclone ran, exit ≠ 0) | same field set as `sync_completed` |
| `sync_failed` | **exceptional** exit (timeout, retry-budget exhaustion, subprocess error) | same field set as above, **plus `error_type`** (the exception's type name only — never its message); `rclone_exit_code` is the last observed code or `null` if rclone never returned one. Any change evidence harvested before the exception fired is preserved (e.g. a file copied just before a timeout still counts toward `corpus_changed`/`counts`). |
| `sync_check_subprocess_failed` | optional post-sync check could not launch (including permission or executable-format errors) | `ok: false`, `missing_local`, `missing_remote`, `differences`, `errors_n` |

Per-file events preserve the complete relative filename, including colons in
macOS/POSIX names, so SHA-256 lookup and the corpus-change signal use the copied
file's actual path. If the copy succeeds but the optional integrity check cannot
launch, its failed check result is returned alongside the successful copy result;
per-file audits and exit 10 for a changed corpus are still emitted. This does not
certify integrity: inspect `check_ok: false` and the check audit event.

No event field is named `query`; the logger treats it as protected query content.

---

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `RCLONE_NOT_INSTALLED` (exit 3) | Install rclone (Step 1) |
| `RCLONE_VERSION_TOO_OLD` (exit 3) | Upgrade to **v1.68.2** or higher (CVE-2024-52522 fix) |
| `SYNC_CONFIG_INVALID` (exit 3) | Check the `sync:` block in `config.yaml` — error details name the failing field |
| `aborted_for_safety: true` (exit 1) | A safety fuse tripped (`--max-delete`/`--max-transfer`). Either many files were genuinely changed upstream (raise the fuse only if intentional) or the remote is wrong — investigate, don't blindly raise it. |
| `SYNC_CONFIG_INVALID` naming an unknown `sync:` key (exit 3) | A typo such as `max_delte` is now **fatal** (fail closed): a misspelled safety fuse would otherwise silently keep its default while the operator believes it is set. Correct the key name — the error details list the offending keys. (`enabled` is exempt: it is CyClaw's own on/off toggle, not an rclone parameter.) |
| `SYNC_SCHEDULER_ERROR` | `crontab`/`schtasks` not on PATH (e.g. running schtasks under WSL), or the scheduler write failed — see the error details |
| Soul changed on a second machine | Never via sync — the sync root is confined to `data/corpus` and `include_soul` is a no-op. If the soul changed, it was edited out-of-band; rebuild it from the canonical machine's `data/personality/` via `POST /soul/apply`. |
| Stale answers after a sync | The gateway caches the index at import time. After exit 10 + reindex, **restart the gateway**. |

---

## Why rclone (and not Maestral or the Dropbox SDK)

rclone provides separate-process transport, native Windows support, and
OAuth storage outside CyClaw. Maestral adds a persistent daemon without
native Windows support; direct SDK integration would make CyClaw manage OAuth.

## Encrypted rclone configuration in scheduled jobs

Re-run `python -m sync.cli schedule` after upgrading to regenerate existing jobs.
On macOS, launchd keeps a loaded job's old definition until it is reloaded:
run `launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.cgfixit.cyclaw.sync.plist`,
then the `launchctl bootstrap` command that `schedule` prints.
Cron, launchd and Task Scheduler launch `python -m sync.scheduled`, which reads
only `RCLONE_CONFIG_PASS` at execution time and then invokes the normal sync CLI.
Generated scripts, task arguments and plists never contain the password. The
selected interpreter and `--config` identity remain unchanged.

On macOS store the password with
`macos/cyclaw-keychain-set.sh com.cgfixit.cyclaw.rclone-config-pass` (hidden prompt).
On Windows use the existing Credential Manager setup for `RCLONE_CONFIG_PASS`;
the shared secret policy maps it to the same service name. The scheduled user must
have access to that keystore. A locked/inaccessible or empty item fails with exit
3, without echoing credential output. An absent item permits plaintext rclone
configuration; encrypted configuration without a password fails without prompting.
Linux automatic keystore retrieval is unsupported: use an operator-managed
service that securely injects `RCLONE_CONFIG_PASS`, or an unencrypted configuration
with appropriately restricted filesystem permissions. Do not store this secret in
a dotenv file, crontab, plist or task command.

Run `python -m sync.scheduled [--config PATH] --check-credentials` under the scheduled account to
check whether rclone can read its configuration without transferring data or
printing remote names. This verifies config decryption, not remote authorization
or unattended OS-keystore access after logout/reboot. Existing environment-supplied
passwords take precedence; unrelated gateway/provider secrets are discarded.
The sync subprocess always has `RCLONE_ASK_PASSWORD=false`.

Windows directory capabilities such as `%CYCLAW_FS_ROOT%` use the same explicit
name allowlist as `$CYCLAW_FS_ROOT`. Unset, nonsecret percent names remain literal;
already retained discovery variables such as `%USERPROFILE%` keep their meaning.
Other populated percent variables are rejected before filtering can change the
sync directory or overlap lock. The percent syntax does not permit arbitrary
secret or loader variables through child environments.
