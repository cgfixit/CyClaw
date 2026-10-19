---
name: verification-specialist
description: "Independently challenge a supplied CyClaw change with executed checks and adversarial probes. Use for acceptance verification or regression validation; do not fix the implementation or publish."
---


# Verify a CyClaw Change

Try to falsify the acceptance claim. A green suite, polished UI, source reading,
or implementer summary is only one piece of evidence. Verify independently.

## Establish the candidate and boundaries

Read the original request/specification, exact base/head diff, applicable
`AGENTS.md`, relevant `CLAUDE.md` sections, and current workflow commands.
Record SHA, dirty state, OS, interpreter, selected configuration and scope.
Inspect available tools before deciding that a browser or checker is unavailable.

Do not edit the candidate, install dependencies, write Git history, or publish.
Keep probe scripts, caches and reports in an owned temporary directory outside
the project. Run mutating imports, servers or fixtures only against an isolated
disposable copy, with every storage path redirected and real credentials removed.
Never launch a manager that creates/restores soul or use the operator's live
data to test mutations. Stop only processes this verification owns.

For privileged PR review, obey the workflow's trusted-base/no-candidate-execution
boundary. Do not run candidate code because this skill asks for execution;
return static findings and state that runtime acceptance was not verified.

## Exercise the changed property

Use CyClaw's local verification order from `CLAUDE.md` section 5: direct
execution, relevant lint/static checks, hosted CI, then one focused test file
when the preceding evidence cannot exercise a concrete risk. Do not reproduce
the full local suite, coverage run or LoRA suite routinely. Read current-head
Actions results and skips for the broad/platform gates. No application build
step exists; use a build only for a changed artifact that actually has one.

| Change | Direct check and relevant negative case |
| --- | --- |
| Gateway/auth | Start an isolated owned gateway; request each changed endpoint and inspect status, headers, body and side effects. Probe malformed/oversized input, missing/wrong credentials, cross-site and proxy headers, CSRF/RBAC and disabled features as applicable. |
| CLI/helper | Execute representative arguments; inspect stdout, stderr and exit status. Probe unknown options, empty/malformed input, missing resources, refusal and cleanup after failure. |
| Retrieval/graph | Use synthetic data. Inspect scores, provenance, answer model, consent and audit. Exercise empty/stale index, keyword-only degradation, denied/unavailable providers and both local-node destination checks where relevant. |
| UI | Interact in a browser and request referenced JS/CSS. Check completed answers, error/confirmation controls, refresh/persistence, desktop/mobile overflow, uncaught errors and network destinations. HTML 200 or a visible result container alone is insufficient. |
| Config/install/workflow | Parse syntax and run maintained guards; dry-run the actual changed profile where supported. Native OS, keystore and confinement claims require matching native evidence. |
| Docs/skills | Parse frontmatter/UI metadata, follow links, run referenced checker/wrapper help, compare claims with source. Try a realistic task plus an adjacent task that should not trigger the skill. No unrelated server is needed. |
| Bugfix/refactor | Reproduce the original failure against the base when feasible, repeat against the candidate, and exercise adjacent callers. Preserve tests and public contracts; measure only claimed performance. |

Run at least one relevant adversarial probe before a scope-level PASS. Select
from boundary values, harmless near-misses, repeated/idempotent requests,
nonexistent IDs, timeout/partial failure, restart/recovery, or bounded concurrent
access. A docs-only negative control can be a broken-reference/metadata fixture
outside the checkout. Do not run every category without a changed risk.

Inspect what mocks replace and what assertions omit. A connection mock cannot
prove provider destination policy, real inference or native sandboxing. Verify
backend state after an apparent UI/API success. Trace retries, alternate routes
and cleanup if they affect the claim. Reject circular tests and hidden skips.

## Calibrate failures and limits

Before a finding, establish expected behavior, reachable trigger, actual impact,
and whether it predates the change. Check for handling in callers and intentional
refusal. Missing tooling, stopped Ollama, an unavailable native OS or a deliberately
disabled feature is a limit, not a product defect. Explain baseline failures.

Do not rationalize omitted checks as PASS. Use PARTIAL when required evidence
could not be obtained or remains inconclusive; use FAIL for a demonstrated
acceptance failure. PASS covers only the explicitly tested scope.

## Evidence report

For every executed check use:

```text
Check: <claim and expected result>
Command run: <exact command, with secret values redacted>
Output observed: <actual relevant stdout/stderr, verbatim; cite omitted log file>
Exit status: <actual code>
Result: PASS | FAIL
Expected vs actual: <required for FAIL>
```

Record unexecuted required checks as `NOT RUN` or `SKIP`, with the reason and
missing evidence. Never invent output or label source inspection a runtime pass.
Include file/symbol anchors for actionable findings, the adversarial probe,
SHA/environment, fixture/mock limits and current-head CI evidence when available.
Keep reports privacy-safe and remove owned temporary state when finished.
End with exactly one literal line:

```text
VERDICT: PASS
VERDICT: FAIL
VERDICT: PARTIAL
```
