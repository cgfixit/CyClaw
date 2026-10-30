# `sync/` — out-of-band Dropbox corpus sync

Optional Dropbox-to-`data/corpus/` rclone wrapper. Ships disabled
(`sync.enabled: false`); default `direction: pull` uses non-deleting
`rclone copy`. Bisync is opt-in and discouraged. Runs out-of-band via
`python -m sync.cli`; I6 forbids core imports in either direction.
`/ops/sync` uses the `utils/ops_runner.py` subprocess shim.

Design, setup, and threat model: [`docs/SYNC_README.md`](../docs/SYNC_README.md).

## Modules

| Module | Role |
|---|---|
| `cli.py` | Entry point: `setup` / `sync` / `test` / `schedule` / `unschedule` / `status`. `--dry-run` previews; `--resync` rebuilds the bisync baseline. |
| `config.py` | Loads the `sync:` block of `config.yaml`; validation and defaults. |
| `filters.py` | Generates the rclone filter file (what syncs, what never does). |
| `runner.py` | Drives `rclone copy` (pull, default) or `rclone bisync` (opt-in) as an argv-list subprocess with timeouts. |
| `scheduler.py` | Scheduled-job backends: cron (default), launchd (Darwin-only, opt-in via `sync.scheduler_backend`, writes a plist but never auto-loads it), Windows Task Scheduler. |
| `scheduled.py` | Scheduler entry (`python -m sync.scheduled`): loads only `RCLONE_CONFIG_PASS` through `utils.child_environment`, then invokes the CLI. Artifacts hold no password. `--check-credentials` tests decryption without transfers. |
| `selftest.py` | Pre-flight checks behind `sync test`. |

## Exit codes (an API — keep them)

`0` successful operation or disabled sync; `1` safety fuse tripped
(`--max-delete` / `--max-transfer` abort); `2` operation failed;
`3` env/config problem; `10` corpus changed and the caller must reindex
(`python -m retrieval.indexer`, then restart the gateway). Exit 10 can also
follow a partial failed sync; inspect the command output and audit log.

Exit `10` applies with shipped `sync.auto_reindex: false`. Enabling it runs
the indexer inside `sync.cli sync`; callers should no longer expect `10`.
The indexer subprocess does not reload an already-running gateway; restart
it to adopt that newly built index. A dry run never returns `10` or triggers
automatic reindexing. The overall `sync_timeout_sec` bounds rclone attempts,
retry backoff, and the post-sync check together; `0` explicitly removes that
deadline.

## Related

- Scheduling on macOS (plist generation, never auto-load):
  [`docs/work/MACOS_LAUNCHD_INTEGRATION_PLAN.md`](../docs/work/MACOS_LAUNCHD_INTEGRATION_PLAN.md)
- Corpus rules: [`data/README.md`](../data/README.md)
