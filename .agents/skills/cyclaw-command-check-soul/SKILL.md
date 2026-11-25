---
name: cyclaw-command-check-soul
description: "Check CyClaw soul presence, UTF-8, SHA-256 and stored integrity without writes. Use for readiness or drift. Avoid self-healing managers."
---

# Check Soul Without Mutation

Resolve the effective file and backend from config and environment. Read `utils/personality.py` and `utils/personality_db.py` for reference semantics. Avoid imports or constructors that initialize or restore state.

Read bytes, verify nonempty UTF-8, and calculate size and SHA-256 without printing content. Open an existing SQLite backend read-only. Use a remote reference only when authorized, and compare with the latest stored version when available.

Report path, EXISTS/MISSING, size, digest, MATCH/DRIFT/NO BASELINE and relevant reference timestamps. A missing file can self-initialize at boot. Keep services, file bytes and the stored baseline untouched. For repair contracts, consult I5 in `INVARIANTS.md`.
