# Handoff checklist

Use when preparing a commit/authorized draft or review handoff; this is an
optional reminder, not a second policy or automatically loaded Codex file.

- Requested outcome and scope match the final diff; unrelated edits are preserved.
- Exact base/head and relevant open-PR overlap/integration order are recorded.
- I1–I6, destinations/consent, auth/CSRF, audit, telemetry and protected state
  were considered where the changed path reaches them.
- Direct evidence and relevant static checks were inspected; skips, mocks,
  platform limits and current-head CI state are stated accurately.
- Skill metadata/references/callers and documentation match the resulting tree.
- No private corpus, raw queries, credentials, indexes, logs or local DBs are staged.
- Git/publication follows `.codex/Codex_instructions.md`; no hook bypasses,
  implicit merges or unauthorized history rewrites.
- The PR uses the full repository template, with agent-instruction/workflow
  review note, merge order, ELI5 and current final timestamp.
