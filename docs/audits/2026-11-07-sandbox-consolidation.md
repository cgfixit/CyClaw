# Sandbox consolidation and issue #1797

Reviewed 2026-11-07 against `main@7c222959`. This record separates merged
runtime repairs from the remaining verification-helper maintenance in
[#1797](https://github.com/cgfixit/CyClaw/issues/1797).

## Remaining implementation and order

1. Merge useful behavior into `.claude/skills/CyClaw-Sandbox/`: loopback-only
   console probes, exact security-header values, configurable smoke report
   location, mock local inference, audit-integrity checks and portable reports.
   Preserve the canonical route inventory, retired-route refusals, redaction,
   fingerprint/source metadata and real LangGraph dependency requirement.
2. Replace the seven corresponding `.agents/skills/cyclaw-sandbox/` scripts
   with delegates. Keep caller arguments, environment, exit status and report
   defaults. Update tests that inspect the old implementation copies.
3. Verify each candidate independently and the ordered combination. Human
   review/merge and the resulting main revision remain separate from drafts.

The in-process runner is Tier 0: deterministic Chroma/embedding/local-client
doubles and selected node calls. Requiring LangGraph does not establish full
compiled-graph coverage. An unrelated Ollama listener cannot upgrade its
evidence tier. The Codex fake `StateGraph` and unconstrained installer using
the nonexistent `full` extra will be retired with the duplicate implementation;
prepared environments use the existing hashed installation profiles.

The console probe rejects non-loopback origins before sending a key, disables
ambient proxies and refuses redirects. Header-name lookup is case-insensitive;
header values must actually be `nosniff` and `DENY`.

The provider-specific mock under `cyclaw-sandbox-test/scripts` remains separate:
it advertises local/Grok/Claude IDs and implements Anthropic `/v1/messages`,
which its caller checks. The maintained Ollama mock has a different streaming
and protocol contract. Adding cloud fixture features only to remove that
small fixture would not improve this change.

## All twelve findings

| Item | Disposition |
| --- | --- |
| 1. Port-rule drift | Merged in #1812. Gateway, URL helper and service generators share strict port validation; valid explicit overrides keep precedence. A direct resolver probe on this base rejected bool/string/null/out-of-range config, retained 8787 when missing and accepted valid endpoints/override. |
| 2. Atomic scheduler writers | Merged in #1803: sibling temp, flush/fsync, replace, cleanup. Preserve already-correct independent writers. Native Windows ACLs and power-loss durability are not established by source review. |
| 3. Forwarding-header drift | Required AST parity guard merged in #1798. Shared auth/origin extraction is not planned without a separate defect; presence-only semantics remain. |
| 4. Sandbox forks | The two-step work above remains necessary before closure. |
| 5. Test-only bootout | Removed in #1798 with its obsolete marker/tests. |
| 6. Telegram retry clamp | Shared helper merged in #1799. |
| 7. Trash schedule preflight | Shared preflight merged in #1799, preserving OS-first checks and exit codes. |
| 8. Windows launcher formatting | Retain the separate formatter. Atomicity is already repaired; shared quoting/scrub helpers preserve `cyclaw_sync.bat` and working directory. No additional reachable defect was established. |
| 9. CLI preambles/print helpers | Not planned: small copies preserve distinct disabled/status/poll contracts and local redaction. No demonstrated maintenance defect warrants cross-subsystem churn. |
| 10. Historical metrics | Retain compatibility for old audit logs and `injection_findings`. Repository state cannot establish the operator's retention cutoff; removing the response key is outside this repair. |
| 11. Numbat keyword forwarding | Retain explicit signatures. Every `build_event` argument is forwarded; emitter-only `config_path` is intentional. No omitted field was found. |
| 12. Small cleanups | Unused arguments/usage corrected in #1799. Retain the scaffold's equal key sets with their existing contracts; no active-caller defect established. |

These are explicit dispositions, not claims that every optional refactor was
implemented. Closing the issue requires the Sandbox candidates to reach main
with relevant checks passing. Full local application suites, paid providers,
scheduler activation and native Windows qualification are separate evidence.

## Verification scope

The changes are verification tooling, not runtime graph/auth/config changes.
Focused helper execution covers success and deliberate failure; regression
checks cover refusal before transport, redirects, header values, report
preservation and missing dependencies. Static checks cover Python/shell syntax,
telemetry inventory and documentation consistency. Broad platform suites and
PowerShell analysis belong to the exact candidate's GitHub Actions results.

The complete in-process command passed 158 checks in a disposable checkout.
Two fault injections verified the failure exit: prior audit history cannot
satisfy the current run's RAG event count, and the Grok/Claude pause probes
require the confirmation node's own response.

The behavior candidate was exercised with Python 3.12.14: an owned loopback
HTTP server accepted the synthetic-key request and its redirect was refused
without a follow-up request; smoke report defaults and a path containing spaces
were checked. Focused regression files passed 11 console checks and 23 runner
checks, including wrong route, error-bearing/no-call/duplicate-call answers,
actual temporary audit/NDJSON writes, missing LangGraph and empty phases.
Ruff F/B/S, Python/Bash syntax, ShellCheck, the 46-check invariant guard,
telemetry inventory (zero failures/warnings) and doc-sync (zero drift) passed.
Strict mypy remains advisory: legacy skill typing is not clean (baseline 49
errors across the two checked scripts); no repository type policy was relaxed.
