---
name: cyclaw-command-audit
description: "Summarize CyClaw audit, spend or sequence evidence from an authorized configured file. Report aggregates without exposing raw records."
---

# Summarize Audit Evidence

Resolve `logging.audit_file` from effective config. Read `metrics.py` and `utils/logger.py` for field semantics. Run `python -m metrics` or installed `cyclaw-metrics` for the configured summary. For a date range, pass filtered `iter_events` to `compute_metrics` in a temporary script. Pass paths and dates as data.

Report window, event and retrieval counts, scores, models, external escalation, integrity and spend as available. Check `llm_model` and `model_used` against source. Offline best-effort uses local generation. Count audit JSONL once and treat Numbat as its projection.

Flag malformed records, plaintext queries and unexpected external activity with aggregates. Under the shipped hash setting, query fingerprints use keyed HMAC. Keep raw queries, credentials, corpus, complete events and logs out of reports and commits.
