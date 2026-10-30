# CyClaw Agentic Package — User Guide (v0.2, experimental)

**Experimental, default-off:** scoped filesystem
(`python -m agentic.fsconnect.cli`) and passive LAN inventory
(`python -m agentic.netconnect.cli`). The package CLI, GitHub coding loop,
registry, verification executor, and SQL connector were removed (§8).

Core modules never import these connectors (I6). Neither calls an LLM;
both use direct I/O or argv-list subprocesses, audit operations, and require
write gates plus human `--reason` (`--confirm` for destructive operations).
[Package map](../../agentic/README.md).

## 1. Prerequisites

Base-installed connectors use repository `config.yaml` (`--config`
overrides). Package import applies telemetry suppression before submodules.

- **fsconnect:** stdlib reads/writes; optional indexing stages eligible
  files then invokes `python -m retrieval.indexer`, never imports retrieval.
- **netconnect:** reads existing neighbor caches using fixed OS commands
  (`ip neigh show` or `arp`). Missing commands exit 3; never probes instead.

## 2. Filesystem connector (`agentic.fsconnect`)

The filesystem connector reads files under operator-listed roots and, when
separately armed, writes under a different list of writable roots. It is
content-agnostic: it never calls a model, and write content comes only from
`--body`, `--body-file`, or stdin. Settings live in the `fsconnect:` block of
`config.yaml`, which is the source of truth for every default.

Enable reads:

```yaml
fsconnect:
  enabled: true
  allowed_roots: ["/path/you/allow/read"]   # required when enabled
```

Commands:

```bash
python -m agentic.fsconnect.cli status
python -m agentic.fsconnect.cli list    --root ... --path ...
python -m agentic.fsconnect.cli read    --root ... --path ...
python -m agentic.fsconnect.cli stat    --root ... --path ...
python -m agentic.fsconnect.cli grep    --root ... --path ... --pattern ...
python -m agentic.fsconnect.cli glob    --root ... --pattern '*.md'
python -m agentic.fsconnect.cli largest --root ... [--min-bytes N]
# Writes (gated; see the playbook below):
python -m agentic.fsconnect.cli write   --path ... --body-file f --reason ... [--confirm]
python -m agentic.fsconnect.cli append  --path ... --body-file f --reason ...
python -m agentic.fsconnect.cli mkdir   --path ... --reason ...
python -m agentic.fsconnect.cli move    --src ... --dst ... --reason ... --confirm
python -m agentic.fsconnect.cli delete  --path ... --reason ... --confirm   # to trash; --purge needs allow_hard_delete
python -m agentic.fsconnect.cli trash-empty | trash-restore | quota-status
python -m agentic.fsconnect.cli index   [--apply] [--reindex]               # stage a writable root into the corpus
python -m agentic.fsconnect.cli reveal
python -m agentic.fsconnect.cli trash-empty-plist   # macOS: writes the launchd plist, never loads it
python -m agentic.fsconnect.cli trash-empty-task    # Windows: writes the scheduled-task XML, never registers it
python -m agentic.fsconnect.cli test
```

**Write gates.** Writes are off by default (`writes_enabled: false` returns a
dry-run plan instead), are confined to `writable_roots`, and always need a
non-empty `--reason`; overwrite, move and delete also need `--confirm`. A
code-level `FS_WRITE_HARD_DISABLE` constant in `agentic/fsconnect/writer.py`
sits ahead of the config gates. Symlinks under a root are always denied
(`follow_symlinks` must be `false`). The staged enablement procedure is
[`FSCONNECT_WRITE_ENABLEMENT_PLAYBOOK.md`](FSCONNECT_WRITE_ENABLEMENT_PLAYBOOK.md);
the sign-off list is
[`FSCONNECT_SECURITY_REVIEW_CHECKLIST.md`](FSCONNECT_SECURITY_REVIEW_CHECKLIST.md).

**HTTP surface.** The terminal console's Filesystem panel reaches the
connector only through `POST /ops/fsconnect`, an API-key-gated, rate-limited,
audited route that runs the CLI as a subprocess via `utils/ops_runner.py`. It
accepts the read-only actions `status`, `test`, `list`, `read`, `stat`, `grep`
and `glob` (`OpsFsConnectRequest` in `schemas/api.py`); browser grep is
literal-only. Writes, trash, index and the scheduler generators stay CLI-only.

## 3. Passive network connector (`agentic.netconnect`)

The passive network connector reports best-effort local host metadata and the
operating system's existing neighbor (ARP) cache, filtered to operator-listed
networks. It sends no packets: there is no ping, port probe, subnet sweep,
scheduler, or HTTP route. Settings live in the `netconnect:` block of
`config.yaml`.

```yaml
netconnect:
  enabled: true
  allowed_cidrs: ["192.168.1.0/24"]   # required; IPv4 RFC1918 or loopback subnets only
```

```bash
python -m agentic.netconnect.cli status
python -m agentic.netconnect.cli self     # local host inventory, no probing
python -m agentic.netconnect.cli arp      # scope-filtered neighbor cache
python -m agentic.netconnect.cli test     # offline pre-flight self-test
```

Public, link-local, carrier-grade NAT, IPv6 and over-broad networks fail at
config load. Every returned address is filtered against `allowed_cidrs` again
at the client boundary. Results are cache-derived hints: stale entries are
possible and absence proves nothing about reachability.

## 4. Exit codes

The connector CLIs share one exit-code API; `utils/ops_runner.py` maps the
fsconnect codes into the `/ops/fsconnect` JSON envelope, and anything outside
this table is reported as `"unknown"`.

| Code | fsconnect | netconnect |
|---|---|---|
| 0 | success, including the clean no-op while `enabled: false` | same |
| 2 | operation failed | same |
| 3 | config or environment problem | same (also: neighbor-cache command missing) |
| 4 | a write was refused by a gate (missing `--reason`/`--confirm`, rate limit, quota) | not used |

## 5. Auditing

Both connectors write JSONL through the same `utils.logger.audit_log` path as
the gateway (secrets, emails and IPs redacted). fsconnect emits
`fsconnect_read`, `fsconnect_write_intent`, `fsconnect_write_dryrun`,
`fsconnect_write_applied`, `fsconnect_write_refused`, `fsconnect_write_failed`
and the `fsconnect_index_*` family; each read also emits a Numbat
`file.read` event. netconnect emits `netconnect_scan` with scope hashes
and counts, never the returned IP or MAC values. Inspect with
`python -m metrics` or by reading `logs/audit.jsonl`.

## 6. Troubleshooting

- **"Filesystem connector disabled" / "Network connector disabled"** → set
  `enabled: true` in the matching `config.yaml` block; exit 0 is the intended
  no-op.
- **fsconnect DRY-RUN**: on supported platforms, `writes_enabled` is false.
- **fsconnect refusal (exit 4)**: Windows writes are always refused; elsewhere
  check `--reason`, destructive `--confirm`, quotas, and write rate limits.
- **netconnect config error at load** → an `allowed_cidrs` entry is not an IPv4
  RFC1918/loopback subnet, or the list is empty while `enabled: true`.

## 7. Tests

Agents follow the verification policy in `CLAUDE.md` §5 (run the code, lint,
then let CI run the suites); these commands are for the owner and CI.

```bash
GROK_API_KEY=dummy pytest tests/test_fsconnect_*.py tests/test_netconnect_*.py -q
GROK_API_KEY=dummy pytest tests/test_agentic_isolation.py -q   # I6, both directions
python -m agentic.fsconnect.cli test
python -m agentic.netconnect.cli test
```

## 8. Removed in October 2026

Until October 2026 the agentic package also carried a GitHub-facing coding
layer and a SQL connector. All of it was deleted, together with its config
blocks, tests, console panels and routes:

- the main CLI (`agentic/cli.py`) and its config loader (`agentic/config.py`);
- read-only GitHub PR/issue context via `gh`, and the GitHub write gate that
  could open a draft PR;
- the governed skills registry (`data/agentic/skills_registry.json`);
- the plan → patch → verify → human-decides → commit coding loop
  (`real-repo-run*`), its jailed clone tools, the retired DeepAgents harness
  and the harness optimizer;
- the Seatbelt/bubblewrap verification executor and its AppArmor profile;
- the UNSLOP prose-quality rail;
- the read-only Postgres/MSSQL connector (`agentic.sqlconnect`);
- the `POST /ops/agentic` and `POST /ops/sqlconnect` routes with the Agentic
  and SQL console panels.

Why: the layer shipped disabled and, after the coding console moved to the
sibling CG-agent-harness project (`docs/THREAT_MODEL.md`, sixteenth
amendment), was reachable only from the command line. It was also the only
part of CyClaw that executed repository code or wrote to GitHub; removing it
retires that surface. The dated record is the `docs/changelog.txt` entry and
the threat model's nineteenth amendment. The `agentic-deepagents`,
`agentic-deepagents-cloud` and `mssql` dependency extras and their locks were
dropped in a follow-up change.
