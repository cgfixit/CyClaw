# cyclaw-privacy ("Legal")

Advisory-only privacy & compliance reviewer persona: DPA reviews, data subject
requests (DSR/DSAR), breach analysis, cross-border transfers (SCCs), regulatory
monitoring, and the privacy impact of CyClaw changes. Never a substitute for
licensed counsel. See `SKILL.md` for the full protocol; `verify.sh` and
`bootstrap.sh` ship alongside it. This is not a troubleshooting skill.

Invoke `/cyclaw-privacy` explicitly in Claude Code; its manifest disables
model invocation. For local configuration checks, run from the repository root:

```bash
bash .claude/skills/cyclaw-privacy/verify.sh
```

The verifier checks selected shipped privacy defaults in `config.yaml`,
including query fingerprints, redaction, external-context forwarding, memory,
auth, and third-party logging. It does not inspect deployed data stores or
establish legal compliance. Missing PyYAML prints `SKIP` and exits zero, so read
the output before calling it a pass. A posture mismatch exits 2.
`bootstrap.sh` additionally fetches `origin/main` and prints both base and
checkout revisions; a failed fetch leaves a potentially stale local ref.

Renamed from `cyclaw-advisor` 2026-09-11 (issue #1351) to resolve an
in-repo name collision with the unrelated `.agents/skills/cyclaw-advisor`
(architecture/PR advice, not privacy/DPA — see
[the Codex inventory](../../../.codex/README.md)).
