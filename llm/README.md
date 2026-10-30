# `llm/` — model clients

`client.py` implements three HTTP clients, bounded retries, local recovery,
and persistent external attempt limits. `graph.py` routing and `gate.py`
construction gates select the client (I2/I3).

## Clients

| Class | Backend | Protocol |
|---|---|---|
| `LocalLLMClient` | Ollama (default) or LM Studio | OpenAI-compatible `/chat/completions` on loopback (or an operator-listed `models.local_llm.trusted_hosts` entry); ignores ambient `HTTP(S)_PROXY` (`trust_env=False`) so localhost traffic can't be redirected off-box |
| `GrokClient` | x.ai | OpenAI-compatible `/chat/completions`; ignores ambient `HTTP(S)_PROXY` (`trust_env=False`) so `GROK_API_KEY` cannot transit an operator proxy |
| `ClaudeClient` | Anthropic | Messages API; ignores ambient `HTTP(S)_PROXY` (`trust_env=False`) so `ANTHROPIC_API_KEY` cannot transit an operator proxy |

I3 lives in `gate.py` and `graph.py`: external clients are constructed only
in hybrid mode with the provider enabled, then called only after per-request
confirmation. Mode and both providers ship enabled; missing keys leave clients
unavailable. Config cannot pre-set `user_confirmed_online`. Destination checks, the optional pre-action hook,
and external attempt budgets can still refuse a confirmed call. Reported
usage lands in `logs/spend.jsonl` ([`spend/README.md`](../spend/README.md)).

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
  with exponential backoff; other 4xx fail fast. Only external clients retry
  timeouts; `LocalLLMClient.retry_on_timeout=False` avoids another full
  `timeout_sec` after a stalled read.
  Each model's `retry` block controls retries: absent means one attempt;
  shipped `max_retries: 2` permits three. A `Retry-After` header on a 429/5xx is honored in place
  of the exponential delay, clamped to `backoff_max_sec`. Every sleep is also
  checked against the per-request graph deadline (`api.graph_timeout_sec`,
  set via `set_graph_deadline`): when the remaining budget cannot cover the
  pending backoff plus another POST, the retry is abandoned and the client
  raises its timeout error immediately instead of outliving the 504 (#1359).
- **Local failover** (`models.local_llm.fallback`): optional short probes
  prefer the primary backend (Ollama), then the loopback secondary (LM
  Studio). Successful selection is cached while it works. If neither backend
  answers at startup, later generation re-probes; after a selected backend
  fails, the next generation re-probes rather than replaying that failed
  request on another backend. Ships disabled. Configure the secondary's
  actual loaded model id before enabling it; the shipped id is an example.
- **Credentials and reasoning:** primary and fallback local credentials use
  separate `api_key_env` names; gateway boot validation refuses non-empty
  literal `api_key` values in either block, even with fallback disabled.
  The resolved local backend receives `reasoning_effort` only when its
  provider is `ollama`. Grok resolves its own reasoning effort and sends it
  with `max_completion_tokens`; Claude uses the Messages API's `max_tokens`.
- **External attempt budgets:** `utils/external_budget.py` reserves a slot
  before every Grok/Claude POST, retries included, using the shared
  `policy.external_call_limits` ledger. UTC daily/monthly ceilings persist
  across restarts; exhausted budgets or unavailable storage refuse the POST.
  Failed attempts count; provider-reported token usage remains separate.
- Timeouts and model names come from `config.yaml` (`models.local_llm.*`,
  `models.grok.*`, `models.claude.*`) — see `CLAUDE.md` §2 "Load-bearing
  numbers" for the ones that interact. Boot requires
  `api.graph_timeout_sec >= models.local_llm.timeout_sec + 30`; increasing
  the model timeout alone can therefore prevent startup.

## Related

- Provider gating and per-query selection (`online_provider`): `graph.py`,
  repo-root `INVARIANTS.md`
- Ollama context-length footgun on "CyClaw hangs" reports:
  [`setup-guide.md`](../setup-guide.md#troubleshooting) (the `num_ctx`
  headroom formula lives in the same doc)
