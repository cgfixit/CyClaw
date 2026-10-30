# cyclaw-privacy ("Legal")

Advisory privacy/compliance review: DPAs, DSR/DSAR, breaches, SCCs, regulation,
and CyClaw privacy impact. It does not replace licensed counsel or diagnose
runtime faults. Protocol: `SKILL.md`; helpers: `verify.sh`, `bootstrap.sh`.

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

Renamed 2026-09-11 (#1351), separating privacy review from the architecture
`.agents/skills/cyclaw-advisor` ([Codex inventory](../../../.codex/README.md)).
