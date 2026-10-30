# `schemas/` — Pydantic API models

`api.py` defines gateway request/response models for query, sources, health,
soul evolution, `/ops/*`, `/auth/*`, `/memory/*`, and `/console/session`.
Every model uses `extra='forbid', strict=True`: unexpected fields and loose
type coercion receive HTTP 422 before retrieval or generation.

`QueryRequest.max_length` adds a DoS backstop independent of the configurable
injection-filter length cap in `utils/sanitizer.py`.

## Response and operator contracts

- `QueryResponse.model_used` identifies the answer route; `llm_model` supplies
  its model tag when available. On the confirmation pause,
  `available_providers` names only usable online choices. Generation failures
  can return an empty `answer` with `error`; callers must inspect both rather
  than displaying an error as an answer.
- `HealthResponse` includes index/graph readiness, mode, corpus path, version,
  and server-side query/sync deadlines used by the console's longer fetch
  timeouts.
- Ops actions are closed `Literal` sets. `/ops/fsconnect` exposes read-only
  operations, and its `regex` field accepts only `false`; regex grep and
  writes remain local CLI operations.
- Memory proposals use closed actions (`add_fact`, `update_fact`,
  `deactivate_fact`) and bounded content/tags/reasons. Schema validation is
  followed by the store's policy checks and enforced apply-time scan.

Changing a field name, a bound, or an error shape here is an API-contract
change: `tests/test_gate.py` and the console contract test
(`tests/test_terminal_contract.py`) assert against these models' behavior.

## Related

- Route table these models serve: `CLAUDE.md` §2 "All HTTP routes"
- Sanitizer (the other half of input validation): `utils/sanitizer.py`
