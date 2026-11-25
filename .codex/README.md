# Codex guidance for CyClaw

Start with [AGENTS.md](../AGENTS.md) and use the [workflow overlay](Codex_instructions.md) for Git and PRs. Skills live in [`.agents/skills/`](../.agents/skills/). Invoke with `$name`. Codex can also select implicit skills when relevant. Explicit skills have `allow_implicit_invocation: false` in `agents/openai.yaml`. Invocation leaves task authority with the user and repository policy.

[Codex instruction discovery](https://developers.openai.com/codex/guides/agents-md) and [skills](https://learn.chatgpt.com/docs/build-skills) explain the runtime mechanisms. The overlay, routines and checklist are references reached by links. Command approvals use separate [Codex rules](https://developers.openai.com/codex/rules).

## Skill inventory

| Skill | Purpose | Selection |
| --- | --- | --- |
| `verification-specialist` | Independent executed acceptance and adversarial probes | Implicit |
| `refactor` | Scoped behavior-preserving structural cleanup | Implicit |
| `dep-guard` | Offline dependency/lock contract checks | Implicit |
| `doc-sync` | Mechanical drift plus manual source reconciliation | Implicit |
| `invariant-guard` | I1–I6 structural checks plus relevant behavior | Implicit |
| `injection-redteam` | Synthetic sanitizer regressions/false positives | Implicit |
| `otel-hardening` | Telemetry suppression/import/child-environment checks | Implicit |
| `cyclaw-command-status` | Read-only configured readiness | Implicit |
| `cyclaw-command-run` | Focused existing-environment smoke | Implicit |
| `cyclaw-command-audit` | Privacy-safe audit/spend evidence | Implicit |
| `cyclaw-command-check-soul` | Soul integrity without initialization/adoption | Implicit |
| `cyclaw-advisor` | Read-only architecture/platform/source navigation | Explicit |
| `verify-dep` | Selected install-profile and supply-chain acceptance | Explicit |
| `cyclaw-run-cyclaw` | Requested installation/indexing/startup | Explicit |
| `cyclaw-sandbox` | Requested full audit across separate evidence lanes | Explicit |
| `cyclaw-sandbox-test` | Legacy socket-mock runner in a disposable prepared copy | Explicit |
| `cyclaw-optimize` | Bounded improvement audit/implementation | Explicit |
| `add-comment` | Comment-only WHY pass | Explicit |
| `fable-protocol` | Optional consequential-decision evidence pass | Explicit |
| `chris-codex` | Public-safe continuity; no personal-copy synchronization | Explicit |

The legacy `cyclaw-sandbox-test` uses fixed ports. Shared `cyclaw-sandbox` helpers delegate to `.claude/skills/CyClaw-Sandbox/`. The browser helper and verification contract live with the Codex skill.

## Task references

Use the routines for [orientation](routines/first-pass-repo-review.md), [bug fixes](routines/bugfix.md), [features](routines/feature.md), [refactoring](routines/refactor.md), [verification](routines/test-and-verify.md), [PR review](routines/pr-review.md) and [security review](routines/security-review.md). Use the [handoff checklist](checklists/pre-pr.md) before a draft.

## Hosted PR prompts

| Workflow | Trusted input and result |
| --- | --- |
| [PR comment](../.github/workflows/codex.yml) | [Prompt](prompts/pr-agent.md) reads prepared diff data in the base checkout and returns Markdown. |
| [Structured PR review](../.github/workflows/pr-review.yml) | [Prompt](prompts/pr-review.md) inspects a sibling candidate read-only and returns schema-checked JSON. |
| [Apply approved fixes](../.github/workflows/codex-apply-fixes.yml) | [Default-branch prompt](prompts/pr-apply-fixes.md) scopes candidate edits to the owner/SHA-approved bot comment. A separate runner validates and publishes the patch. |

## Validation

```text
python scripts/check_codex_skills.py
python .claude/skills/doc-sync/doc_sync.py
git diff --check
```

The [Codex Skills workflow](../.github/workflows/codex-skills.yml) checks metadata, references and helper syntax. Review triggers with matching and adjacent tasks. Execute changed helper contracts separately where applicable.
