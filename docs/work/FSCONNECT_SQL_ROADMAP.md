# Filesystem connector: shipped behavior and deferred proposals

Reviewed 2026-10-23 against main at 246e406 for [#1745](https://github.com/cgfixit/CyClaw/issues/1745).
The filename is retained for existing references. SQL connector planning is
retired: sqlconnect was removed on 2026-10-18. The
[previous roadmap](https://github.com/cgfixit/CyClaw/blob/246e406d27beb097c3ecab3ba188a11c109b86db/docs/work/FSCONNECT_SQL_ROADMAP.md)
preserves the old SQL and connector research.

## Shipped behavior

- [fsconnect](../../agentic/README.md) provides scoped reads and gated
  POSIX writes, trash/quota controls, rate limits and audited operations.
- [Incremental staging](../../agentic/fsconnect/indexer.py) compares file metadata,
  hashes changed content and prunes its own stale staged copies. It is not an
  OS watch service or cross-source content-deduplication system.
- Windows read/list/stat use native handle-based containment. Native adversarial
  coverage lives in tests/test_fsconnect_pathsafe_windows.py. Windows writes
  remain hard-refused.
- The CLI reveal operation opens an approved root in the OS file manager.
- [netconnect](../../agentic/README.md) is the other remaining
  connector; it supplies passive network inventory, not general OS inventory.

The [write playbook](../agentic/FSCONNECT_WRITE_ENABLEMENT_PLAYBOOK.md) and
[security checklist](../agentic/FSCONNECT_SECURITY_REVIEW_CHECKLIST.md) remain
the maintained write-enablement documentation.

## Deferred proposals

None is implemented by the documentation cleanup.

| Proposal | Current limit and requirement before implementation |
|---|---|
| Watch-triggered reindex | No FSEvents/inotify/ReadDirectoryChangesW service. Events must be advisory triggers; every read re-enters scoped authority. Overflow, coalescing and root changes require rescan. |
| Cross-source content deduplication | Hashing changed files does not eliminate identical content at different paths. Preserve provenance if deduplication is pursued. |
| Offline OCR | No local OCR integration. Needs a real corpus need and dependency review. |
| Quarantine and human release | Indexing flags suspicious content advisory-only; flagged content is not routed to a maintained release queue. |
| Windows write authority | Keep writes refused until equivalent handle-relative mutation containment is implemented and verified natively. |
| NTFS ACL advisory output | Not part of the current fs_stat result. Optional least-privilege reporting, not a replacement for containment. |
| Terminal file-share reveal | CLI reveal exists; a browser-triggered action needs a separately reviewed request/authorization boundary. |
| Audit reconciliation | No audit-verify command. A small intent/applied/failed checker would be separate from cryptographic integrity. |
| Tamper-evident audit | No live record hash chain with a trusted external anchor. Export-time hashes do not establish original-log history. |
| Read-only OS inventory, governed OS actions, IMAP/EWS, SIEM or direct SMB | New connector proposals only; no automatic commitment or shared-base extraction. |

## Boundaries to preserve

I6 keeps connectors out of the core graph. A connector must not become an LLM
caller or graph node. Filesystem access uses the maintained pathsafe authority,
not string-prefix checks. Mutations retain enablement, explicit confirmation,
human reason and audit controls. Advisory scan enforcement remains an explicit
operator policy decision; this roadmap changes no defaults.

Track dispositions in [remaining work](../plans/remaining_work.md). SQL-specific
live-DB tests, NL-to-SQL, new dialects, MSSQL EXPLAIN, cost limits and row redaction
are retired with the removed connector, not remaining fsconnect work.
