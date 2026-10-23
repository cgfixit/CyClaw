# Remaining work and proposal dispositions

Reviewed 2026-10-23 against main at 246e406. This is a documentation status
index for [#1745](https://github.com/cgfixit/CyClaw/issues/1745), not approval
to implement new features. Code and configuration determine shipped behavior.
The cleanup changes no runtime code, defaults, credentials, or provider policy.

## Existing work

| Area | Current state | Disposition and evidence |
|---|---|---|
| Retrieval quality and backend | Chroma and pgvector ship. sqlite-vec remains a spike, not a production adapter. pgvector fingerprint handling, indexing metadata and backend-selected evaluation remain incomplete. | Continue [#1657](https://github.com/cgfixit/CyClaw/issues/1657): retrieval acceptance before an opt-in backend. Keep [SQLite platform evidence](../audits/2026-09-21-sqlite-vec-phase-c-spike.md) and [reranker measurements](../audits/2026-09-26-reranker-bakeoff.md). No threshold/default-backend change is approved here. |
| Published answer quality | Evaluators exist, but the judge/calibration and full-fixture live-model evidence listed in [EVALS](../EVALS.md#what-has-not-been-measured) is not published. | Acceptance remains unverified; defer live runs to separately authorized work. Do not build another evaluator. |
| Local-model comparison | The [October 10 report](../bakeoff/local-model-bakeoff-2026-10-10.md) has no committed runner, temporary result references, conflated injection/completion scores, and nominal long prompts measured at 88 tokens in one lane. | Retain as preliminary, no winner. A future run needs reproducible code, safe raw artifacts, separate safety/completion scoring and actual prompt lengths. |
| Audit reconciliation | No maintained audit-verify command or live log hash-chain/external anchor. The docs export prototype did not establish its advertised integrity guarantees. | Prototype retired; [observations preserved](../audits/2026-10-23-docs-reconciliation.md#audit-export-prototype). Reconciliation and tamper-evident logging are separate deferred designs; no implementation in this cleanup. |
| Telegram | T0–T3 and partial T4 ship; T4 needs a platform refusal before download and a durable receipt/re-ack recovery policy. | Keep default-off media and [T4 limitations](../channels/TELEGRAM_DESIGN.md#t4--media--fsconnect-optional-high-risk--partial). Live operator acceptance remains unverified. |
| OpenTweet | Implementation exists; live posting acceptance is not recorded as complete. | Preserve [design and limits](../channels/OPENTWEET_DESIGN.md); do not send posts to complete documentation. |
| Filesystem connector | Incremental staging, guarded writes, native Windows reads and CLI reveal ship. Watch-triggered indexing, OCR, real quarantine, Windows writes, ACL reporting and terminal reveal remain proposals. | Deferred; see [fsconnect roadmap](../work/FSCONNECT_SQL_ROADMAP.md). Keep Windows writes refused. |
| Credential lifecycle | Key-store setup/loading and explicit uninstall deletion ship on both platforms. | [macOS scheduled rotation](MACOS_BASH_SETUP_AND_KEY_LIFECYCLE.md#remaining-work) and [legacy Windows error classification](WINDOWS_POWERSHELL_SETUP_AND_KEY_LIFECYCLE.md#remaining-work) remain deferred. |
| Numbat | Projection ships on; hook/CEL code exists and ships off. Rolling-stream scoring is not built. | Keep the [layer matrix and evidence](NUMBAT_AND_ALWAYS_ON_ROADMAP.md). Defer stream observation/alerts; on-path sequence enforcement still needs session/checkpointer design. |
| Dependencies and CI | Historical version lists are not current upgrade instructions. | Use maintained locks, [#1702](https://github.com/cgfixit/CyClaw/issues/1702) and [#1709](https://github.com/cgfixit/CyClaw/issues/1709); refresh their state before acting. |

## Optional proposals: retained, not approved

All rows below are deferred. Retention preserves an idea, not a promise to build
it. Recheck the implementation and user need before opening focused work.

| Proposal | Preserved rationale / constraint |
|---|---|
| [Mailtag](../mailtag/IMPLEMENTATION_PLAN.md) | No package, gateway module, config or adapters exist. Provider authentication and explicit propose/review/apply mutation semantics need a fresh design review. |
| [Guided Markdown corpus authoring](../zIdeas/Features_and_Security_notes.md) | A small operator-facing authoring flow may help; no new UI is approved. |
| Read-only corpus layout report | Independent surviving idea from the [retired Waku plan](../ARCHIVE_AND_ROADMAP.md#retired-plans). Compare with existing index diagnostics before adding a module. |
| [CVE-triage / release-cut skills](../work/PROPOSED_SKILLS.md) | Check overlap with maintained dependency and verification skills first. |
| [Audited runtime provider controls](../work/online-llm-grok-claude.md) | Configuration authority differs from per-request online consent; preserve I3. |
| [OpenAI cloud fallback](../analysis/2026-08-02_cyclaw-current-codebase-openai-integration-deep-dive.md) | Core fallback is Local/Grok/Claude. Old harness-specific proposals are retired; a new cloud provider needs separate approval. |
| Corpus-source allowlist for cloud context | Pattern redaction cannot certify absence of confidential meaning. Source eligibility is a separate possible control if context forwarding is enabled. Current provider context-forwarding defaults remain false. |
| Cross-file content deduplication | Incremental staging hashes changed files; eliminating duplicate content across different source paths is a separate proposal. |
| Read-only OS inventory / governed OS actions | Distinct from passive netconnect. New authority and platform behavior require a concrete need; no osconnect package is promised. |
| IMAP/EWS, SIEM and direct-SMB connectors | Research only; not obligations to expand the connector set. |
| Shared connector abstraction | No automatic extraction threshold. Reuse existing boundaries until a real caller demonstrates the need. |
| [Portable audit evidence, retention and matter/client tags](../work/PSYCLAW_FEATURE_IDEAS.md) | Product hypotheses, not supported compliance guarantees. Existing memory/personality retention does not implement audit-log erasure. |
| Published-image/license scanning or a second scanner | Salvaged from the retired CVE runbook. Reassess current CI and overlap before adding tools. |
| Full cross-browser console acceptance | Preserve [completed UX evidence](../console-ux.md); no complete Edge/Firefox/Brave matrix is claimed. |
| MFA, automatic memory consolidation and microVM isolation | Intentional optional designs, not missing mandatory capabilities. Preserve human governance and the trusted-operator deployment scope. |

## Completed or retired: do not reopen from old checkboxes

- [#1013](https://github.com/cgfixit/CyClaw/issues/1013) is closed completed.
  Its removed agentic acceptance leg is not a reason to rebuild that subsystem.
- [#1128](https://github.com/cgfixit/CyClaw/issues/1128) is closed not planned.
  Hook and CEL implementation status is in the Numbat matrix above.
- [#1255](https://github.com/cgfixit/CyClaw/issues/1255) is superseded by #1657.
- SQL-specific live-DB CI, NL-to-SQL, dialect/EXPLAIN expansion, cost limits and
  redaction tasks retired with sqlconnect on 2026-10-18.
- Harness executor, approval decorators, proposal fingerprints, live Deep Agents
  smoke tests, persistent harness checkpointers, registry skill surfacing,
  cloud harness provider parity and its memory-size tunable retired with their
  execution paths. They are not current CyClaw fixes.
- The old harness instruction-scanner proposal retired with its API. The
  offline-best-effort guardrail routing gap was already closed.
- Changing fsconnect advisory scanning into enforcement is an explicit operator
  policy decision, not a documentation fix.
- Session-start sync checking is already wired; do not rebuild it.
- Console first-run, health disclosure, elapsed indexing time, route/model copy
  and error vocabulary are implemented; see [current UX notes](../console-ux.md).

## Cleanup boundary

Use [the archive index](../ARCHIVE_AND_ROADMAP.md) for exact historical versions
and [the reconciliation record](../audits/2026-10-23-docs-reconciliation.md) for
preservation and verification scope. Issue #1745 remains the follow-up ledger;
this documentation cleanup does not claim the deferred runtime work is done.
