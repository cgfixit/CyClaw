# `agentic/` — CyClaw out-of-band connectors

Experimental, **default-off** connectors:

- `python -m agentic.fsconnect.cli` — scoped local/SMB filesystem connector
- `python -m agentic.netconnect.cli` — passive LAN inventory, no active probes

User guide (enabling, commands, exit codes, auditing):
[`docs/agentic/AGENTIC_README.md`](../docs/agentic/AGENTIC_README.md).

Neither connector calls an LLM. I6 forbids imports in either direction
between this package and the six core modules;
`tests/test_agentic_isolation.py` pins that boundary.

## Package map

| Path | What it does |
|---|---|
| `agentic/__init__.py` | Applies `utils/telemetry_kill.py` before connector imports |
| `agentic/fsconnect/cli.py` | fsconnect CLI and its exit-code API (0 ok / 2 failed / 3 env-config / 4 write refused) |
| `agentic/fsconnect/config.py` | `fsconnect:` block schema and load-time validation |
| `agentic/fsconnect/pathsafe.py` | Root scoping: `ScopedRoots`, symlink/reparse-point denial, path checks for reads and writes |
| `agentic/fsconnect/client.py` | Read operations (`list`/`read`/`stat`/`grep`/`glob`/`largest`) with advisory injection flags |
| `agentic/fsconnect/context.py` | CLI read bundles: one short-lived client per op, JSON results |
| `agentic/fsconnect/writer.py` | Gated writes (`write`/`append`/`mkdir`/`move`/`delete`), `FS_WRITE_HARD_DISABLE`, reason/confirm gates, rate limit |
| `agentic/fsconnect/trash.py` / `quota.py` | Trash with retention and restore; per-root quota ledger |
| `agentic/fsconnect/indexer.py` | Optional staging of a writable root into the corpus, then `python -m retrieval.indexer` as a subprocess |
| `agentic/fsconnect/osutil.py` | `reveal`: opens a writable root in the OS file manager (argv-list, operator-run only) |
| `agentic/fsconnect/protected_paths.py` | Shared root and path-component policy used by the read and write scopes |
| `agentic/fsconnect/selftest.py` | `python -m agentic.fsconnect.cli test` |
| `agentic/netconnect/cli.py` | netconnect CLI (`status`/`self`/`arp`/`test`; exit 0 / 2 / 3) |
| `agentic/netconnect/config.py` / `scope.py` | `netconnect:` block validation; RFC1918/loopback CIDR scoping |
| `agentic/netconnect/client.py` / `context.py` | Host metadata and neighbor-cache reads filtered to `allowed_cidrs`; CLI bundles in `context.py` |
| `agentic/netconnect/selftest.py` | `python -m agentic.netconnect.cli test` |

## Where each connector is reachable

- **fsconnect:** CLI and console Filesystem panel via read-only
  `POST /ops/fsconnect` (operator auth, rate limit, audit).
  `utils/ops_runner.py` invokes the CLI as a subprocess. Browser/API grep is
  literal-only; writes, regex grep, `largest`, indexing, and trash maintenance
  are CLI-only.
- **netconnect:** CLI only; no HTTP route or scheduler.

The fsconnect writer refuses all writes on Windows until handle-based
containment is implemented. On supported platforms, `writes_enabled: false`
produces dry-run plans; actual writes still require the configured root,
reason/confirmation, hard-disable, quota, and rate-limit gates. Trash-job
generators emit launchd or Task Scheduler artifacts but never activate them;
their later execution does not bypass the write gates.

Write enablement for fsconnect follows
[`FSCONNECT_WRITE_ENABLEMENT_PLAYBOOK.md`](../docs/agentic/FSCONNECT_WRITE_ENABLEMENT_PLAYBOOK.md)
and [`FSCONNECT_SECURITY_REVIEW_CHECKLIST.md`](../docs/agentic/FSCONNECT_SECURITY_REVIEW_CHECKLIST.md).
Threat-model scope: [`docs/THREAT_MODEL.md`](../docs/THREAT_MODEL.md).

## Removed in October 2026

The main agentic CLI (`agentic/cli.py`: GitHub context, GitHub write gate,
skills registry), the real-repo coding loop, the verification executor, the DeepAgents
harness and harness optimizer, the UNSLOP rail, and the SQL connector
(`agentic.sqlconnect`) were removed from this package. What went and why:
[`docs/agentic/AGENTIC_README.md` §8](../docs/agentic/AGENTIC_README.md#8-removed-in-october-2026).
