# Documentation history and roadmap index

Reconciled 2026-10-23 for [#1745](https://github.com/cgfixit/CyClaw/issues/1745).
This is an index, not a second implementation backlog.

- [Remaining work and proposal dispositions](plans/remaining_work.md) owns the
  distinction between shipped behavior, acceptance gaps, deferred proposals and
  retired work.
- [Documentation map](README.md) points to maintained operating contracts.
- [Reconciliation record](audits/2026-10-23-docs-reconciliation.md) records the
  cleanup, evidence preserved and changed evaluation-corpus scope.
- [Previous full archive/roadmap](https://github.com/cgfixit/CyClaw/blob/246e406d27beb097c3ecab3ba188a11c109b86db/docs/ARCHIVE_AND_ROADMAP.md)
  preserves the detailed historical phase decisions and original research.

## Retirement decisions

The Python coding console and port 8790 endpoints were removed on 2026-09-11.
The GitHub coding layer, verification executor and SQL connector were removed
on 2026-10-18. Filesystem and passive network connectors remain. See
[changelog](changelog.txt) and [threat-model amendments](THREAT_MODEL.md).

Plans for the removed paths are historical records, not instructions to rebuild
them. In particular, old missing harness memory tunables, proposal fingerprints,
registry views, SQL dialects and harness-side scanners no longer describe a
reachable CyClaw implementation gap.

## Durable rationale

- Keep retrieval-only MCP separate from agentic tools. The old proposal to add
  an MCP adapter did not override I6.
- Prefer existing ownership and simple pipelines over optional frameworks and
  parallel approval abstractions. The historical LangGraph-native alternative
  required fewer dependencies; it is research, not a new architecture mandate.
- A future governed write surface must use the current confinement and audit
  boundaries, preserve human confirmation/reason, and deny on validation failure.
  Old shell or unrestricted filesystem backends are not approved alternatives.
- Pattern-based redaction cannot prove free text contains no confidential
  meaning. A corpus-source allowlist is retained as an independent, deferred
  cloud-context proposal; existing forwarding defaults remain false.
- Keep risk matching specific enough to avoid benign substring false positives,
  use the maintained audit API, and obtain the running event loop inside async
  approval code. Historical examples are not current callable APIs.
- Preserve source/artifact identity and distinguish fixtures, runtime probes,
  native checks and live-provider acceptance. A successful mock does not prove
  an end-to-end provider or filesystem boundary.

## Retired plans

The links below pin the complete pre-cleanup text. Their useful surviving ideas
are in [remaining work](plans/remaining_work.md); they are removed from the active
tree to avoid conflicting instructions.

| Historical file | Disposition |
|---|---|
| [UNSLOP_INTEGRATION_PLAN.md](https://github.com/cgfixit/CyClaw/blob/246e406d27beb097c3ecab3ba188a11c109b86db/docs/UNSLOP_INTEGRATION_PLAN.md) | Retired architecture or obsolete operational instructions; full historical text retained at this revision. |
| [work/CyClaw_Safe_Agentic_Enhancement_Plan.md](https://github.com/cgfixit/CyClaw/blob/246e406d27beb097c3ecab3ba188a11c109b86db/docs/work/CyClaw_Safe_Agentic_Enhancement_Plan.md) | Retired architecture or obsolete operational instructions; full historical text retained at this revision. |
| [work/DEEP_AGENT_HARNESS_PHASES_6_9.md](https://github.com/cgfixit/CyClaw/blob/246e406d27beb097c3ecab3ba188a11c109b86db/docs/work/DEEP_AGENT_HARNESS_PHASES_6_9.md) | Retired architecture or obsolete operational instructions; full historical text retained at this revision. |
| [work/GITHUB_DEEP_AGENT_HARNESS_OPTIMIZER_PLAN.md](https://github.com/cgfixit/CyClaw/blob/246e406d27beb097c3ecab3ba188a11c109b86db/docs/work/GITHUB_DEEP_AGENT_HARNESS_OPTIMIZER_PLAN.md) | Retired architecture or obsolete operational instructions; full historical text retained at this revision. |
| [work/cyclaw_codebase_notes.md](https://github.com/cgfixit/CyClaw/blob/246e406d27beb097c3ecab3ba188a11c109b86db/docs/work/cyclaw_codebase_notes.md) | Retired architecture or obsolete operational instructions; full historical text retained at this revision. |
| [NeMo/phase3_implementation_plan.md](https://github.com/cgfixit/CyClaw/blob/246e406d27beb097c3ecab3ba188a11c109b86db/docs/NeMo/phase3_implementation_plan.md) | Retired architecture or obsolete operational instructions; full historical text retained at this revision. |
| [NeMo/phase5_agent_run_broker.md](https://github.com/cgfixit/CyClaw/blob/246e406d27beb097c3ecab3ba188a11c109b86db/docs/NeMo/phase5_agent_run_broker.md) | Retired architecture or obsolete operational instructions; full historical text retained at this revision. |
| [plans/WAKU_HARNESS_TOOLS_PLAN.md](https://github.com/cgfixit/CyClaw/blob/246e406d27beb097c3ecab3ba188a11c109b86db/docs/plans/WAKU_HARNESS_TOOLS_PLAN.md) | Retired Python harness; independent corpus-report idea retained in remaining work. |
| [work/CONSOLE_NORMIE_UX_PLAN.md](https://github.com/cgfixit/CyClaw/blob/246e406d27beb097c3ecab3ba188a11c109b86db/docs/work/CONSOLE_NORMIE_UX_PLAN.md) | Completed work summarized in console-ux.md; original acceptance log retained here. |
| [work/DEPENDENCY_CURRENCY_PLAN.md](https://github.com/cgfixit/CyClaw/blob/246e406d27beb097c3ecab3ba188a11c109b86db/docs/work/DEPENDENCY_CURRENCY_PLAN.md) | Historical versions superseded by maintained locks and current dependency tracking. |
| [work/console-review-bundle/cyclaw-dep-cve-scan-claude-code.md](https://github.com/cgfixit/CyClaw/blob/246e406d27beb097c3ecab3ba188a11c109b86db/docs/work/console-review-bundle/cyclaw-dep-cve-scan-claude-code.md) | Obsolete scan baseline; optional image/license/second-scanner ideas retained. |
| [CyClaw Audit Bundle Export Script.py](https://github.com/cgfixit/CyClaw/blob/246e406d27beb097c3ecab3ba188a11c109b86db/docs/CyClaw%20Audit%20Bundle%20Export%20Script.py) | Unsupported prototype; findings retained in the reconciliation record. |
| [! How-To-Guides/CyClaw-Agentic-Harness-HowTo.pdf](https://github.com/cgfixit/CyClaw/blob/246e406d27beb097c3ecab3ba188a11c109b86db/docs/%21%20How-To-Guides/CyClaw-Agentic-Harness-HowTo.pdf) | Retired architecture or obsolete operational instructions; full historical text retained at this revision. |
| [! How-To-Guides/CyClaw-harness-html-User-Guide.pdf](https://github.com/cgfixit/CyClaw/blob/246e406d27beb097c3ecab3ba188a11c109b86db/docs/%21%20How-To-Guides/CyClaw-harness-html-User-Guide.pdf) | Retired architecture or obsolete operational instructions; full historical text retained at this revision. |
| [CyClaw-Auth-Gate-vs-Harness-curl.pdf](https://github.com/cgfixit/CyClaw/blob/246e406d27beb097c3ecab3ba188a11c109b86db/docs/CyClaw-Auth-Gate-vs-Harness-curl.pdf) | Retired architecture or obsolete operational instructions; full historical text retained at this revision. |
| [memories/zOld/CyClaw_SandboxWss_v1.8.0_Validation_Report_Combined.pdf](https://github.com/cgfixit/CyClaw/blob/246e406d27beb097c3ecab3ba188a11c109b86db/docs/memories/zOld/CyClaw_SandboxWss_v1.8.0_Validation_Report_Combined.pdf) | Byte-identical duplicate removed; audit copy retained. |
| [memories/zOld/CyClaw_Swarm_Verification_Report_2026-07-09_v2.pdf](https://github.com/cgfixit/CyClaw/blob/246e406d27beb097c3ecab3ba188a11c109b86db/docs/memories/zOld/CyClaw_Swarm_Verification_Report_2026-07-09_v2.pdf) | Unique dated report moved unchanged to audits/. |
| [memories/zOld/Efficient-computer.md](https://github.com/cgfixit/CyClaw/blob/246e406d27beb097c3ecab3ba188a11c109b86db/docs/memories/zOld/Efficient-computer.md) | Legacy verifier/skill/research copy; maintained verification lives in active skill directories. |
| [memories/zOld/LangChainFix.md](https://github.com/cgfixit/CyClaw/blob/246e406d27beb097c3ecab3ba188a11c109b86db/docs/memories/zOld/LangChainFix.md) | Legacy verifier/skill/research copy; maintained verification lives in active skill directories. |
| [memories/zOld/LangchainIntegrationPlan.md](https://github.com/cgfixit/CyClaw/blob/246e406d27beb097c3ecab3ba188a11c109b86db/docs/memories/zOld/LangchainIntegrationPlan.md) | Legacy verifier/skill/research copy; maintained verification lives in active skill directories. |
| [memories/zOld/Ponytail-Research.md.md](https://github.com/cgfixit/CyClaw/blob/246e406d27beb097c3ecab3ba188a11c109b86db/docs/memories/zOld/Ponytail-Research.md.md) | Legacy verifier/skill/research copy; maintained verification lives in active skill directories. |
| [memories/zOld/SKILL.md](https://github.com/cgfixit/CyClaw/blob/246e406d27beb097c3ecab3ba188a11c109b86db/docs/memories/zOld/SKILL.md) | Legacy verifier/skill/research copy; maintained verification lives in active skill directories. |
| [memories/zOld/_test_terminal_consoles.py](https://github.com/cgfixit/CyClaw/blob/246e406d27beb097c3ecab3ba188a11c109b86db/docs/memories/zOld/_test_terminal_consoles.py) | Legacy verifier/skill/research copy; maintained verification lives in active skill directories. |
| [memories/zOld/cyclaw_implementation_action_plan.md](https://github.com/cgfixit/CyClaw/blob/246e406d27beb097c3ecab3ba188a11c109b86db/docs/memories/zOld/cyclaw_implementation_action_plan.md) | Legacy verifier/skill/research copy; maintained verification lives in active skill directories. |
| [memories/zOld/fable-protocol-SKILL.md](https://github.com/cgfixit/CyClaw/blob/246e406d27beb097c3ecab3ba188a11c109b86db/docs/memories/zOld/fable-protocol-SKILL.md) | Legacy verifier/skill/research copy; maintained verification lives in active skill directories. |
| [memories/zOld/run_full_verification.py](https://github.com/cgfixit/CyClaw/blob/246e406d27beb097c3ecab3ba188a11c109b86db/docs/memories/zOld/run_full_verification.py) | Legacy verifier/skill/research copy; maintained verification lives in active skill directories. |
| [memories/zOld/test-specifications.md](https://github.com/cgfixit/CyClaw/blob/246e406d27beb097c3ecab3ba188a11c109b86db/docs/memories/zOld/test-specifications.md) | Legacy verifier/skill/research copy; maintained verification lives in active skill directories. |

## Historical evidence retained

Dated audits remain in [audits](audits/). The unique July 9 swarm report moved
from the old memory folder to
[the audit collection](audits/CyClaw_Swarm_Verification_Report_2026-07-09_v2.pdf)
without changing bytes. The duplicate SandboxWss PDF was removed only from the
old memory folder; [the audit copy](audits/CyClaw_SandboxWss_v1.8.0_Validation_Report_Combined.pdf)
remains.

The tracked [June 30 sandbox record](memories/Local_Sandbox_Complete_Audit_2026-06-30.md)
is retained as dated evidence. New local memory stays ignored under memories/;
ignore rules do not retroactively untrack that historical record.

[Screenshots and videos](screenshots/README.md) retain their original bytes.
Unlinked media are not assumed valueless. Current README assets and dated
acceptance evidence remain available.

## Maintained documents that are not retired

- [Session notes](work/SESSION_NOTES.md) remains the blocker-log destination named
  by CLAUDE.md and project rules.
- [Sync guard notes](work/LOCAL_REMOTE_SYNC_GUARD.md) retain their operating context.
- [NeMo overview](NeMo/README.md), phases 2/4/4b and dated runtime audits preserve
  live guardrail contracts and historical acceptance.
- [Memory design](memory/IMPLEMENTATION_PLAN.md), [authentication](AUTHENTICATION_DESIGN.md),
  connector playbooks and channel designs retain their useful contracts.
- Setup redirects remain valid entry points. They are not deleted merely for
  being short.
