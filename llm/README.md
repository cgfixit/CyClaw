# `llm/` — model clients

One module, `client.py`, holding the three HTTP clients the graph's answer
nodes use. No routing or policy lives here — which client gets called is
decided entirely by `graph.py`'s edges and `gate.py`'s construction gates
(invariants I2/I3); these classes only speak the wire protocols.

## Clients

| Class | Backend | Protocol |
|---|---|---|
| `LocalLLMClient` | Ollama (default) or LM Studio | OpenAI-compatible `/chat/completions` on loopback (or an operator-listed `models.local_llm.trusted_hosts` entry); ignores ambient `HTTP(S)_PROXY` (`trust_env=False`) so localhost traffic can't be redirected off-box |
| `GrokClient` | x.ai | OpenAI-compatible `/chat/completions`; ignores ambient `HTTP(S)_PROXY` (`trust_env=False`) so `GROK_API_KEY` cannot transit an operator proxy |
| `ClaudeClient` | Anthropic | Messages API; ignores ambient `HTTP(S)_PROXY` (`trust_env=False`) so `ANTHROPIC_API_KEY` cannot transit an operator proxy |

The two external clients are **constructed** only when `mode == "hybrid"` and
the provider's `enabled` flag is true, and **called** only after per-request
user confirmation — the triple gate (I3) lives in `gate.py` + `graph.py`, not
here. Read that against the shipped config: `app.mode` is `"hybrid"` and both
`models.grok.enabled` and `models.claude.enabled` are `true`, so on a fresh
clone both clients are constructed at boot and the only closed gate is the
per-request `user_confirmed_online`, which no config key can pre-set. Billed
calls land in `logs/spend.jsonl` ([`spend/README.md`](../spend/README.md)).

## Guarded generation

With the shipped `guardrails.enabled: true`, `graph.py` calls these clients
through the callable `utils/guardrail_bridge.py` injects: input checked before
generation and output after on all four answer routes, deterministic input and
soul-leak checks (audited `guardrail_degraded`) when NeMo is missing or fails,
grounding on retrieved local answers only, no added model calls. An unexpected
wrapper failure returns `GUARDRAIL_ERROR` without replaying generation; the
HTTP retry policy below is separate. Rail scope and limits:
[NeMo reference](../docs/NeMo/README.md).

## Shared behavior

- **Bounded retry** (`_post_with_retry`): transport errors, 5xx and 429 retry
  with exponential backoff; other 4xx fail fast (retrying a 400/401 wastes
  time and, for Grok, credits). Timeouts retry for `GrokClient`/`ClaudeClient`
  only — `LocalLLMClient` passes `retry_on_timeout=False`, so a stalled Ollama
  read fails fast rather than burning a second full `timeout_sec`.
  Config-driven via each model's `retry` block; absent block = single attempt
  (the shipped `config.yaml` sets `max_retries: 2` on all three models, i.e. up
  to three attempts). A `Retry-After` header on a 429/5xx is honored in place
  of the exponential delay, clamped to `backoff_max_sec`. Every sleep is also
  checked against the per-request graph deadline (`api.graph_timeout_sec`,
  set via `set_graph_deadline`): when the remaining budget cannot cover the
  pending backoff plus another POST, the retry is abandoned and the client
  raises its timeout error immediately instead of outliving the 504 (#1359).
- **Local failover** (`models.local_llm.fallback`): optional boot-time probe
  that prefers the primary backend (Ollama) and falls back to the secondary
  (LM Studio) if unreachable; selection cached per process. Ships disabled so
  single-backend installs stay fail-closed.
- Timeouts and model names come from `config.yaml` (`models.local_llm.*`,
  `models.grok.*`, `models.claude.*`) — see `CLAUDE.md` §2 "Load-bearing
  numbers" for the ones that interact (e.g. `api.graph_timeout_sec` (780) must
  exceed `models.local_llm.timeout_sec` (720)).

## Related

- Provider gating and per-query selection (`online_provider`): `graph.py`,
  repo-root `INVARIANTS.md`
- Ollama context-length footgun on "CyClaw hangs" reports:
  [`setup-guide.md`](../setup-guide.md#troubleshooting) (the `num_ctx`
  headroom formula lives in the same doc)
