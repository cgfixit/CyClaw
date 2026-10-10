## Branch naming (required for agent-opened PRs)

Before opening a PR, create the head branch with the **driver-matched** prefix.
Hooks and `utils/agent_identity.py` enforce this allowlist; casual / generic names are not a substitute.

| Driver | Branch pattern | Example |
|--------|----------------|---------|
| Claude Code | `claude/<feature>` | `claude/telegram-media-audit` |
| Codex | `codex/<feature>` | `codex/verify-dep-guard` |
| Grok Build | `grok/<feature>` | `grok/pr-template-branch-rules` |
| Kimi / Kimi Code | `kimi/<feature>` | `kimi/docs-sync` |
| CyClaw direct / MCP | `CyClaw/<feature>-<YYYYMMDD>` or `cyclaw/<feature>` | `CyClaw/harness-timeout-20260805` |
| Unknown / generic | `agent/<feature>` | `agent/launcher-browser-parity` |

Rules for agents:
1. Pick the prefix that matches **the tool that is creating the branch**, not a generic label.
2. Do **not** default to `agent/` when the driver is known (Claude → `claude/`, Grok → `grok/`, etc.).
3. `<feature>` must be short, kebab-case, and describe the change (no spaces, no leading `-`).
4. If the branch name is wrong, rename **before** push: `git branch -m <prefix>/<feature>`.

Also allowed by hooks (non-feature): `main`, `dependabot/*`, `renovate/*`, `release/*`, `hotfix/*`.

## Title
**Use this format:**  
`[prefix] - Short descriptive sentence of the change`

**Recommended prefixes (pick the most relevant):**  
`[invariant]` • `[governance]` • `[fsconnect]` • `[agentic]` • `[rag]` • `[security]` • `[docs]` • `[infra]` • `[fix]` • `[feat]`

Example: `[governance] - add two-phase audit + quota enforcement to fsconnect write path`

---

## Proposed changes
Describe the big picture of your changes here. Explain **why** maintainers should accept this PR.  
If it fixes a bug or resolves a feature request, link the issue.

**Invariant / Governance Impact** (required for any change touching core paths):
- Which of the 6 security invariants or I6 module isolation does this change affect (or confirm none)?
- Provide evidence it is preserved (e.g., graph topology unchanged, audit convergence maintained, soul evolution still human-gated, RAG-first entry point intact).
- If you are intentionally relaxing or evolving an invariant, explain the justification and compensating controls.

---

## Types of changes
What types of changes does your code introduce to CyClaw?  
_Put an `x` in the boxes that apply_

- [ ] Bugfix (non-breaking change which fixes an issue)
- [ ] New feature (non-breaking change which adds functionality)
- [ ] Breaking change (fix or feature that would cause existing functionality to not work as expected)
- [ ] Documentation Update (if none of the other choices apply)
- [ ] Invariant / Governance refinement (use this for changes that strengthen or evolve the 6 invariants, I6 isolation, or harness phases)

**Optional free-text scope note** (recommended):  
Core graph/gate/soul path | Out-of-band agentic/fsconnect/sync layer | RAG retrieval/sanitization | Docs + audits | Infrastructure / CI only

---

## Benefits / why
- Why make this change? What is the concrete upside for CyClaw users, operators, or long-term maintainability?
- How does this improve (or at least not degrade) production readiness, invariant strength, offline/air-gapped reliability, governance observability, or security posture?
- For agentic or fsconnect changes: how does this increase governed capability without weakening the read-only core contract?

---

## Risks to monitor
- What are the potential regressions, negative side-effects, or things that need extra attention after merge?
- Could this introduce a new shortcut path around audit convergence, weaken RAG-first enforcement, create network assumptions, affect subprocess isolation, or change soul evolution behavior?
- For write-enablement or quota changes: what failure modes exist if the two-phase audit or trash retention logic has a bug?
- How will you (or future maintainers) detect drift from the intended behavior?

---

## Checklist
_Put an `x` in the boxes that apply. You can fill these out after creating the PR. If you're unsure about any item, ask before opening the PR._

- [ ] I have read `docs/THREAT_MODEL.md`, `INVARIANTS.md` and `SECURITY.md` (and any relevant Phase docs)
- [ ] This change preserves all 6 security invariants and I6 module isolation (explicit evidence or invariant matrix included for core changes)
- [ ] Full sandbox validation has been run (`GROK_API_KEY=dummy pytest tests/ -q --tb=short`, and `bash .claude/skills/CyClaw-Sandbox/verify.sh` for core RAG/agentic paths) and passes with no regressions
- [ ] No new external network dependencies or mandatory online LLM assumptions were introduced without explicit justification + offline fallback path
- [ ] For any agentic/fsconnect change: two-phase audit, quota enforcement, governed delete/trash, and write guards have been verified
- [ ] Relevant architecture docs or threat model notes have been updated if core behavior or topology changed
- [ ] Commit messages follow the title prefix convention above
- [ ] For large or complex changes: before/after invariant matrix + sandbox evidence is included in "Further comments" or linked

---

## Further comments
If this is a relatively large, complex, or core-path change, kick off the discussion here in technical tone. The plain-language summary of the whole PR goes in the required `## ELI5` at the very end, not here.

**For changes touching `graph.py`, `gate.py`, soul paths, RAG retrieval/sanitization, or agentic subsystems, include:**
- Explicit before/after invariant matrix
- Sandbox validation diff or key evidence
- Any compensating controls or observability added
- A technical summary (the plain-language version goes in `## ELI5`, below)

**Examples of what good "Further comments" look like for core changes:**
- "No change to graph topology or entry points. RAG-first and audit convergence remain enforced by edges only."
- "Added governed write path behind fifth gate + two-phase audit. Core request path untouched. Full sandbox run attached."
- "Relaxed one non-critical logging path for observability; compensating SHA-256 audit still converges. See attached invariant matrix."

---

**Notes for contributors (including solo maintainer / multi-agent PRs):**
- Core invariant or governance changes require the strongest evidence.
- Out-of-band layers (`agentic/`, `sync/`, `.claude/`) may use a lighter checklist, but still need Benefits + Risks + the relevant items.
- Docs-only or audit PRs may skip some technical checklist rows; Benefits and Risks remain required.
- Prefer squash-and-merge. The final squashed commit message is the permanent record; keep intermediate agent WIP out of `main`.
- Be blunt about impact: if invariants, offline posture, or audit behavior are affected, say so explicitly.

---

## Suggested merge order of open PRs
_Required on every PR, including a lone one (write "independent, only open PR"). Keep every entry to 3 short lines so it reads on a phone: the PR, its impact, the action._

- **Order:** chronological (lowest PR number first) unless a real dependency exists. Name the dependency in that PR's `Impact:` line.
- **Status:** `Safe ✅` (trial merge clean against current `main`), `Dirty ⚠️` (conflicts, or stacked on something unmerged), `Blocked ⛔` (red CI, unresolved blocking review, or still a draft that is not ready).
- **Trial merge note (required):** say you verified it, with the date and the `main` SHA. Locally: `git fetch origin && git switch --detach origin/main && git merge --no-commit --no-ff origin/<branch>`, then `git merge --abort`. A "Safe" is only true until the next merge into `main`; re-run it right before merging.
- **If a PR is Dirty:** prefer a local rebase (or `git rebase --onto origin/main <old-parent-tip> <branch>` for a stacked child whose parent was squash-merged) over GitHub's "Update branch" button. Force-pushing a rebased branch is fine only on a branch that is yours alone, with `--force-with-lease`, and with the owner's OK.

```markdown
## Suggested merge order of open PRs
_Trial merges verified (`git merge --no-commit --no-ff` + abort) against main @ 1a2b3c4d on 2026-10-10._

**#45** · Safe ✅  
Impact: Base advisor skill prompts + routing.  
Action: Merge first. Trial merge clean vs main.

**#47** · Dirty ⚠️  
Impact: RAG context injection (depends on #45 schema).  
Action: After #45 merges → rebase this branch onto main → force-push if personal → re-verify trial merge.

**#48** · Safe ✅  
Impact: Docs-only examples.  
Action: Merge anytime after #45. Clean.

## ELI5
Merge the foundation first. If a later PR was written against an older base, rebase it onto the new one so it drops in clean instead of creating a merge commit. We already tested the fit with a trial merge.
```

## ELI5
_Required on every PR, and it must stay the **last heading** in the body (`pr-template-check.yml` enforces both). The body's last non-blank line is the stamp below, nothing after it; refresh it whenever you edit the body._

Explain the **whole** diff against `main`, not just the first commit. Re-read it whenever a later commit changes what the PR does. Plain words, no jargon you would not say out loud, but keep the specifics:

- **What was broken or missing**, in one picture or analogy, then the real names (file, function, setting) so you can still find it.
- **What changed**, including every later commit. Say what the new behavior is and what it deliberately does not do.
- **What could still go wrong**, and the exact signal that would show it (a log line, a test, an audit field).
- Be blunt about anything you did not run or could not check.

Last updated: YYYY-MM-DD HH:MM ET
