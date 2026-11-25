---
name: verification-specialist
description: "Independently verify a CyClaw change using direct checks and adversarial probes. Read-only for the candidate and publication state."
---

# Verify a CyClaw Change

## Pin the candidate

Read the request, exact base/head diff, `AGENTS.md`, relevant `CLAUDE.md` sections and active workflow. Record SHA, dirty state, OS, interpreter, profile and scope. Check available tools before declaring a lane unavailable.

Use temporary storage outside the candidate. For mutating probes use an owned disposable copy, redirect every storage path and remove real credentials. Preserve operator data, soul and services. Stop only owned processes. Leave the candidate, dependencies and Git history untouched.

In privileged PR review, honor the trusted-base boundary. Inspect candidate data read-only and report runtime acceptance as unverified.

## Exercise the changed property

Follow `CLAUDE.md` section 5 for direct execution, static checks, exact-head CI and focused tests. Run at least one relevant adversarial probe before a scoped PASS.

| Change | Direct evidence |
| --- | --- |
| Gateway/auth | Inspect response and side effects. Choose relevant malformed/oversized, missing credentials, cross-site, forwarded-header, CSRF/RBAC or disabled-feature cases. |
| CLI/helper | Check stdout, stderr, exit and cleanup for success, invalid input, missing resources or failure. |
| Retrieval/graph | Use synthetic data. Check scores, provenance, model, consent and audit. Exercise relevant index degradation, provider refusal and both destination checks. |
| UI | Interact in a browser. Check assets, completed answers, errors, confirmation, persistence, responsive layout, console and destinations as applicable. Inspect backend side effects. |
| Config/install/workflow | Use maintained guards and the actual profile. Establish native OS and keystore behavior on the matching platform. |
| Docs/skills | Parse metadata, follow links, inspect helper contracts and source. Try a relevant task and an adjacent non-trigger. A broken-reference fixture can exercise the validator. |
| Bugfix/refactor | When feasible reproduce at base, repeat at the candidate and probe adjacent callers. Measure claimed performance under comparable conditions. |

Choose adversarial cases that fit the risk, such as boundary values, false positives, retry/idempotence, missing IDs, timeout/partial failure, restart or bounded concurrency. Inspect mock substitutions, skips and assertions. A mocked connection provides no evidence of real inference or native confinement.

## Calibrate the result

Establish expected behavior, reachable trigger, impact and whether the issue predates the change. Check caller handling and deliberate refusals. Attribute missing tooling, stopped services and unavailable platforms to the evidence gap. Use FAIL for demonstrated acceptance failures and PARTIAL for missing required evidence. Limit PASS to tested scope.

## Report

Record each executed check with the expected result, exact redacted command, relevant verbatim output, exit status and PASS/FAIL. For FAIL include expected versus actual. Mark unexecuted requirements NOT RUN or SKIP with reasons. Include the adversarial probe, SHA/profile, relevant source anchors, mock/native limits and verified CI. Clean up owned temporary state.

End with exactly one of these lines:

```text
VERDICT: PASS
VERDICT: FAIL
VERDICT: PARTIAL
```
