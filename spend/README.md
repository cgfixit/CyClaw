# Spend Tracking — Online LLM Token Ledger

`utils/spend.py` records billed Grok/Claude usage after human-confirmed
fallback. Compare matching windows with vendor statements: built-in metrics
cover today and seven UTC days, not months.

**Tokens are ground truth; prices are derived on read**, allowing rate-card
corrections to reprice history. xAI `cost_in_usd_ticks` converts by dividing
by 10,000,000,000. Claude uses billed input/output/cache counts and the
`claude-sonnet-5` `_RATES` entry; do not substitute tiktoken estimates.

## What the ledger is not

The append-only spend stream is separate from authoritative `audit.jsonl`.
It records completed billed calls and feeds CLI spend/sequence reports;
request authorization never reads it. Gateway `metrics.summarize_audit`
reads audit only. Sequence detection loads lazily in the CLI.

## What is recorded

Each successful HTTP response that reaches the external client's extraction
step attempts one JSON-line append, even if answer extraction then fails.
Transport failures without a response cannot establish or record vendor usage,
and a failed best-effort write can leave no row. The writer is
`record_external_usage()` in `utils/spend.py`, serialized by a module-level
threading lock so concurrent calls cannot interleave a partial line.

| Field | Meaning |
|---|---|
| `timestamp` | UTC ISO-8601, set at write time |
| `provider` | Lowercased provider tag (`grok`, `claude`); unparseable input becomes `unknown` |
| `model` | The configured model tag sent in the request, e.g. `grok-4.5` |
| `served_model` | The vendor-resolved id echoed back in the response -- what actually served and billed; kept alongside `model` because an unpinned alias can be re-pointed upstream |
| `input_tokens` / `output_tokens` | Prompt and visible completion counts |
| `cached_input_tokens` | Grok prompt tokens served from cache |
| `cache_creation_input_tokens` / `cache_read_input_tokens` | Claude cache write and read counts |
| `cache_creation_5m_tokens` / `cache_creation_1h_tokens` | Claude cache writes split by TTL, when the vendor reports the split |
| `reasoning_tokens` | Grok reasoning tokens, billed at the output rate |
| `vendor_cost_ticks` | xAI's own `cost_in_usd_ticks`, when the response carries it |
| `usage_missing` | `true` when the vendor returned a billed response CyClaw could not parse usage from |
| `source` | One of `query`, `agentic`, `eval`; anything else normalizes to `unknown`. `agentic` appears only on rows written before the agentic planner was removed in October 2026 |
| `query_hash` | Optional. The same persistent HMAC-SHA256 query fingerprint the audit log uses, accepted only as 64 lowercase hex characters |
| `route_path` | Optional. Up to 16 graph hops, each matching `^[a-z][a-z0-9_]{0,63}$` |
| `outcome` | Optional. `failed_after_billing` on a row the (since-removed) agentic proposer wrote when Grok returned a billed 2xx and the SDK raised afterwards (usage captured from the wire, so the tokens are real); absent on every ordinary row |

### What is never recorded

`utils/spend.py` never persists query text, prompt text, message content,
response bodies, API keys, or authorization headers. `query_hash` is a
pseudonymous correlation key — the only field joinable to an audit record —
and both it and `route_path` are pattern-validated before writing, so a
malformed or oversized value is dropped rather than stored.

## API keys

The ledger records billed usage. It does not hold credentials. Keys live in the
environment (or, on Darwin, in Keychain items that a wrapper exports into the
environment). `config.yaml` names the provider and model; it never contains the
secret.

| Provider | Env var `llm/client.py` actually reads | Dummy / missing |
|---|---|---|
| Grok (xAI) | `GROK_API_KEY` | Client reports unavailable; no spend row |
| Claude (Anthropic) | `ANTHROPIC_API_KEY` (not `CLAUDE_API_KEY`) | Same: unavailable, no spend row |

Do not paste a live key into chat, a PR, or `config.yaml`. On Darwin the
documented store is `macos/cyclaw-keychain-set.sh` plus
`macos/cyclaw-keychain-env.sh <service> <ENV_VAR> -- <command>`:

| Env var | Keychain service |
|---|---|
| `GROK_API_KEY` | `com.cgfixit.cyclaw.grok-api-key` |
| `ANTHROPIC_API_KEY` | `com.cgfixit.cyclaw.anthropic-api-key` |

The Keychain account must match `id -un` (typically the login user). An item
stored under another account (`root` from a sudo run) is invisible to the
wrapper and will 401 if you force-read the wrong secret.

A billed call still needs the same confirmation gates as the rest of CyClaw.
`/query` is I3 (hybrid mode, provider enabled, `user_confirmed_online`). The
ledger cannot grant a call those gates refused.

## Where the ledger lives

The path comes from `config.yaml`, which is the single source of truth:

```yaml
logging:
  audit_file: "logs/audit.jsonl"
  spend_file: "logs/spend.jsonl"
```

Relative paths anchor to the repo root, so `cyclaw-metrics` reports the same
file wherever it is invoked. Without `logging.spend_file` the ledger falls back
to `logs/spend.jsonl` and `cyclaw-metrics` omits its Spend section. Writes are
best-effort: a failure logs a WARNING and returns, never raising into the
request path, because a full disk must not turn a paid answer into a failed one.

## Who writes to the ledger

Production `llm/client.py` writes confirmed fallback as `source: "query"`.
Historical `agentic` rows remain readable after the October 2026 planner
removal. Opt-in judge/calibration calls use `source: "eval"` in the separate
`logs/evals/spend.jsonl`; local judges incur no provider bill.
`utils/sequence_detect.py` considers only `query` rows.

A billed non-JSON response is still recorded, with `usage_missing: true`:
quota was consumed either way, and a missing line would understate the bill.

## How dollars are derived

Pricing happens only at read time, in `estimate_usd()`. The resolution order is:

1. **Vendor ticks.** When a row carries `vendor_cost_ticks`, that wins. xAI
   reports cost in ticks at 10,000,000,000 ticks per USD, so this is the
   vendor's own arithmetic rather than CyClaw's approximation. Such a row is
   reported with `usd_source: "vendor_ticks"`.
2. **The dated rate table.** Otherwise CyClaw prices from the hardcoded
   per-million-token rates in `utils/spend.py`, reported as
   `usd_source: "rate_table"`.
3. **No price.** An unknown model yields `usd: None` with `rate_unknown: true`.
   A row whose every token count is absent (as opposed to zero) yields
   `usd: None` with `usd_source: "incomplete"`.

Two provider-specific billing rules are implemented rather than approximated.
Grok's long-context band applies to **all** tokens in a request once the prompt
reaches its long-prompt threshold, not just the tokens past it. Claude's cache
writes are priced by TTL when the vendor reports the 5-minute and 1-hour split,
and an unsplit write is priced at the 5-minute rate.

Output billing also differs by provider, which is why `billed_output_tokens()`
exists: Grok reasoning tokens sit outside `completion_tokens` and must be added,
while Claude's `output_tokens` is already the inclusive billing total.

### Rate staleness

`PRICED_AS_OF` is the oldest date in `_RATE_VERIFIED` (one per `_RATES` row)
and the table counts as stale after `STALE_AFTER_DAYS` (30); `rates_are_stale()`
and `warn_if_priced_as_of_stale()` surface that so a long-running deployment
says "old rate card" instead of reporting confident, wrong totals. Token counts
stay correct regardless — only derived dollars go stale, which is why dollars
are not persisted. To re-price, update the `_RATES` row and its
`_RATE_VERIFIED` date in `utils/spend.py` (never hand-edit `PRICED_AS_OF`;
`tests/test_spend.py` asserts every row has a date). History re-prices on the
next `cyclaw-metrics` run with no migration.

## Reading the ledger

The Spend section is part of the standard metrics output:

```bash
python -m metrics
```

(`cyclaw-metrics` is the same report once the project is installed following
the editable-install instructions in [`setup-guide.md`](../setup-guide.md).)
The Spend section prints `today` and `last_7d` windows, using UTC dates
(`today - 6` through `today`, inclusive):
input/output tokens, derived USD, and per-provider and per-source row counts.
When any row carried vendor ticks it also shows `table_usd`,
`ticked_table_usd`, `vendor_usd`, and `delta_usd` side by side so rate-table
drift is visible. Two data-quality counters: `usage_missing` (billed calls with
unparseable usage) and `rate_unknown` (models absent from the rate table).
Those two top-level counters cover all parsed ledger rows, not just the two
displayed date windows. Pricing uses the configured `model` field; the optional
`served_model` remains provenance and does not select a separate rate row.

### Verifying the rate table against the vendor

`compare_vendor_cost()` prices a row both ways — rate table versus vendor ticks
— and reports the delta. `ticks_mismatch()` decides when that delta is worth
acting on: sub-tick dust is ignored, a relative disagreement beyond 5% of a
nonzero vendor figure trips, and a large absolute delta trips regardless. This
is how a silently wrong rate entry gets caught instead of accumulating.

Claude rows have no ticks. For those, `usd_source` is `rate_table` (or
`incomplete` / `rate_unknown`). The operator check is the Anthropic console
total for the same window, not a tick delta.

### Matching a vendor console

`cyclaw-metrics` is the local reader. The vendor console is the independent
check. Compare the same window:

1. Sum CyClaw dollars for that provider (`python -m metrics`, Spend section).
2. Open the vendor console and select the same UTC dates. A month-to-date
   console total is not comparable to the CLI's `today` or `last_7d` total.
3. Ignore Grok Build / Claude Code / this coding-agent session's own token
   counter — those are different bills.
4. Cent rounding on the vendor UI is expected. A two-cent gap on a five-dollar
   Grok window, or a sub-cent gap on a six-dollar Claude window, is a match.
   A mid-run screenshot that is missing the last rows is not a rate-table bug;
   refresh after the process exits.

The checked-in `grok-4.5` rate row switches the **whole request** at
`input_tokens >= 200000` to its long-context rates. These are dated local
estimates, not a live price lookup; use vendor ticks when present and verify
the current vendor rate before treating a table-only estimate as a bill.

### Live probes (they spend real money)

**`/query` plane** (`llm/client.py`, `source: "query"`). Opt-in, not collected
by pytest, fails closed unless the live flag is set:

```bash
# Grok only when GROK_API_KEY is set; omit ANTHROPIC_API_KEY to skip Claude.
CYCLAW_SPEND_LIVE=1 python tests/spend_live_probe.py
```

The probe writes a **temp** ledger and deletes it — it does not append
`logs/spend.jsonl`. Capture stdout (`model`, `ticks`, `table_usd`,
`vendor_usd`, `delta_usd`). It asserts that no forbidden field (query, prompt,
content, messages, api_key, authorization) reached the ledger.

## Joining spend to the audit trail

`utils/sequence_detect.py` joins `logs/audit.jsonl` to `logs/spend.jsonl` on the
shared `query_hash` to surface offline forensic patterns — for example, a
blocked injection attempt followed by an online escalation inside a 15-minute
window. Its output is printed as a Sequences section by `cyclaw-metrics`.

The detector is forensic and CLI-only: it keeps `source == "query"` rows
(counting and dropping agentic ones), and its findings carry only hashes, event
names, timestamps, and provider/model tags — never query text, IPs, soul
content, or secrets. The window assumes the shipped threat model (one operator
on a loopback host): it is a correlation aid, not an actor identifier.

## Related documentation

- `docs/online-llm/readme.md` — Grok/Claude gating and per-query provider selection.
- `docs/THREAT_MODEL.md` — the scope the ledger's redaction rules are written against.
- `CLAUDE.md` — the audit-log privacy rules the ledger parallels.
