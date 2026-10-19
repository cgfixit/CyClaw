---
name: cyclaw-command-check-soul
description: "Check the configured CyClaw soul presence, UTF-8, hash and stored integrity reference without mutation. Use for soul drift or readiness checks; never instantiate a self-healing manager or adopt a new baseline."
---


# Check Soul Without Mutation

Resolve the effective personality file/backend from config/environment and
inspect `utils/personality.py` and `utils/personality_db.py` before reading a
stored reference. Default is `data/personality/soul.md`; do not hardcode it for
an operator deployment. Avoid imports/constructors that initialize or restore.

Read file bytes, compute SHA-256 and size, and validate nonempty UTF-8 without
printing content. Open an existing SQLite backend read-only; do not create a DB
or connect to a configured remote database unless that read is authorized.
Compare with its latest stored version only when available.

Report path, EXISTS/MISSING, size, hash and MATCH/DRIFT/NO BASELINE, plus observed
timestamp/reference metadata for drift. Missing soul can self-initialize at
boot; reporting it does not authorize starting the server to repair it.

Never edit, restore, delete, regenerate or change the stored baseline during
this check. Governed apply requires the separate human reason/scan/atomic path;
restore/reload/drift adoption are not equivalent injection-scanned writes.
Report the smallest investigation next step and expose no soul content by default.
