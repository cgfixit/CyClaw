# `agentic/` — CyClaw out-of-band connectors

**Status:** Experimental, **disabled by default**, and out-of-band.
Two connectors, each with its own CLI:

- `python -m agentic.fsconnect.cli` — scoped local/SMB filesystem connector
- `python -m agentic.netconnect.cli` — passive LAN inventory, no active probes

User guide (enabling, commands, exit codes, auditing):
[`docs/agentic/AGENTIC_README.md`](../docs/agentic/AGENTIC_README.md).

The six core modules (`gate.py`, `gate_ops.py`, `gate_auth.py`,
`gate_memory.py`, `graph.py`, and `mcp_hybrid_server.py`) never import this
package, and it never imports them (I6, pinned by
`tests/test_agentic_isolation.py`). Neither connector calls an LLM.

## Package map

| Path | What it does |
|---|---|
| `agentic/__init__.py` | Applies the shared telemetry kill (`utils/telemetry_kill.py`) at package import, before any connector submodule loads |
| `agentic/fsconnect/cli.py` | fsconnect CLI and its exit-code API (0 ok / 2 failed / 3 env-config / 4 write refused) |
| `agentic/fsconnect/config.py` | `fsconnect:` block schema and load-time validation |
| `agentic/fsconnect/pathsafe.py` | Root scoping: `ScopedRoots`, symlink/reparse-point denial, path checks for reads and writes |
| `agentic/fsconnect/client.py` | Read operations (`list`/`read`/`stat`/`grep`/`glob`/`largest`) with advisory injection flags |
| `agentic/fsconnect/context.py` | Read bundlers the CLI dispatches through: one short-lived client per op, JSON-serializable result |
| `agentic/fsconnect/writer.py` | Gated writes (`write`/`append`/`mkdir`/`move`/`delete`), `FS_WRITE_HARD_DISABLE`, reason/confirm gates, rate limit |
| `agentic/fsconnect/trash.py` / `quota.py` | Trash with retention and restore; per-root quota ledger |
| `agentic/fsconnect/indexer.py` | Optional staging of a writable root into the corpus, then `python -m retrieval.indexer` as a subprocess |
| `agentic/fsconnect/osutil.py` | `reveal`: opens a writable root in the OS file manager (argv-list, operator-run only) |
| `agentic/fsconnect/protected_paths.py` | Shared root and path-component policy used by the read and write scopes |
| `agentic/fsconnect/selftest.py` | `python -m agentic.fsconnect.cli test` |
| `agentic/netconnect/cli.py` | netconnect CLI (`status`/`self`/`arp`/`test`; exit 0 / 2 / 3) |
| `agentic/netconnect/config.py` / `scope.py` | `netconnect:` block validation; RFC1918/loopback CIDR scoping |
| `agentic/netconnect/client.py` / `context.py` | Local host metadata and neighbor-cache reads, filtered to `allowed_cidrs`; `context.py` bundles one op per call for the CLI |
| `agentic/netconnect/selftest.py` | `python -m agentic.netconnect.cli test` |

## Where each connector is reachable

- **fsconnect:** the CLI, plus the read-only `POST /ops/fsconnect` route
  (API key, rate limit, audit) behind the console's Filesystem panel. The route
  runs the CLI as a subprocess through `utils/ops_runner.py`; it never imports
  this package. Writes are CLI-only.
- **netconnect:** the CLI only. No HTTP route, scheduler or request-path import.

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
