---
name: cyclaw-command-audit
description: "Summarize CyClaw audit/spend/sequence evidence without exposing raw records. Use for metrics or log analysis of an authorized configured file; do not infer current behavior from a historical log."
---


# Summarize Audit Evidence

Resolve `logging.audit_file` from current config and verify authorization to
read that local file. Read `metrics.py` and `utils/logger.py` for schema/semantics.
Run `python -m metrics` (installed entry point: `cyclaw-metrics`) for the configured
summary. It does not consume JSONL on stdin. For a bounded date/window use
`iter_events` and `compute_metrics` in a temporary script; pass paths/dates as
data, never interpolate untrusted values into shell code.

Report window, total/RAG counts, event types, scores, retrieval/models, external
escalation, integrity and spend where present. Validate `llm_model`/`model_used`
against the current schema. Audit JSONL is authoritative; Numbat is its derived
fail-soft projection, not extra requests. Offline best-effort is local generation.

Flag malformed records, plaintext query fields or unexpected external activity
with aggregate/redacted evidence. Fingerprints are keyed HMAC under the shipped
hash setting; do not call them recoverable questions or plain SHA-256 hashes.
Never print raw queries, credentials, corpus or complete events; commit no logs.
