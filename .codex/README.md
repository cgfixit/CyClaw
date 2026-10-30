# Codex guidance for CyClaw

Start with root [AGENTS.md](../AGENTS.md). Use the
[workflow overlay](Codex_instructions.md) for Git/PRs and relevant
[CLAUDE.md](../CLAUDE.md) sections for operating/verification contracts.
This folder holds explicitly referenced operating material, not another runtime
policy engine. Instructions and skills cannot enforce CyClaw's security topology.

## Discovery and folder roles

Repository skills live in [`.agents/skills/`](../.agents/skills/), one manifest
each. Restart if updates are missing. Personal/global skills are not installed
here; discovery varies by hosted surface.

| Material | How it is used |
| --- | --- |
| Root `AGENTS.md` | Automatically discovered repository instructions in Codex's documented instruction chain |
| `.agents/skills/` | Discoverable skill metadata; invoke `$name` explicitly or allow relevance-based selection |
| `Codex_instructions.md` | Reference linked by root guidance; its arbitrary filename is not automatically loaded |
| `routines/` | Optional Markdown playbooks, read when relevant; not automatically run |
| `checklists/pre-pr.md` | Optional handoff reminder |
| `prompts/` | The three trusted prompt files consumed by GitHub Actions; preserve their security/output contracts |

Keep Markdown workflows in `routines/`. Codex `.rules` files are a separate
Starlark command-approval format under an active trusted config layer's `rules/`
directory. No such command rules ship here; renaming a Markdown playbook to a
rule does not enforce it. Do not add permissive command rules for convenience.

Official references: [skills](https://learn.chatgpt.com/docs/build-skills),
[AGENTS discovery](https://developers.openai.com/codex/guides/agents-md),
[command rules](https://developers.openai.com/codex/rules).

## Skill inventory

Implicit means Codex may select the skill when relevant. Explicit means
`agents/openai.yaml` sets `allow_implicit_invocation: false`; `$name` still works.
Neither setting grants permission to install, mutate operator state, publish,
merge or spend tokens. Root instructions may explicitly direct a skill read.

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

`refactor` absorbs `architecture-refactor`; `AGENTS.md` and the advisor's
source map absorb `cyclaw-project-guidance`. Generic prompt copies and
duplicate checklists were removed; task routines and one handoff checklist remain.

`cyclaw-sandbox-test` remains explicit-only until its legacy install, ports,
readiness, inherited environment, and caller tests are replaced. The larger
sandbox's lifecycle scripts are also explicit legacy tools. Reports live in
`docs/audits/`; socket-mock/terminal probes forward to maintained Claude
scripts, while driver-specific verification remains local.

## Routines, prompts and validation

Use routines for [orientation](routines/first-pass-repo-review.md),
[bugfixes](routines/bugfix.md), [features](routines/feature.md),
[refactoring](routines/refactor.md), [verification](routines/test-and-verify.md),
[PR review](routines/pr-review.md) and [security](routines/security-review.md).

The active [advisory PR agent](prompts/pr-agent.md),
[structured reviewer](prompts/pr-review.md) and
[owner-approved apply-fixes agent](prompts/pr-apply-fixes.md) differ in candidate
access, privilege and output. They are necessary workflow inputs; do not merge
them into a generic prompt or allow a privileged reviewer to execute candidates.

After guidance/resource changes run:

```text
python scripts/check_codex_skills.py
python .claude/skills/doc-sync/doc_sync.py
git diff --check
```

Inspect references/callers and execute changed helper contracts; validate shell
syntax and Python syntax. Use realistic positive, adjacent negative and explicit
invocation scenarios for complex skills. Metadata validation cannot prove an
LLM will choose or follow a workflow. The Codex Skills workflow validates metadata
and helper syntax without repeating the product's full suite/bootstrap; existing
product/checker workflows retain their acceptance gates.
