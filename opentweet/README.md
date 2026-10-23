# `opentweet/` — out-of-band X posting channel

Optional OpenTweet adapter, shipped `enabled: false`. Runs strictly as a
separate process (`python -m opentweet.cli`). The six core modules never
import it (invariant I6). Generation only
ever happens through HTTP `POST /query` on loopback with
`user_confirmed_online: false`. Default write is an OpenTweet **draft**;
`scheduled_date` is opt-in via `opentweet.schedule_enabled`. Schedulers
never send `publish_now`.

Architecture and threat notes: [`docs/channels/OPENTWEET_DESIGN.md`](../docs/channels/OPENTWEET_DESIGN.md).

## Modules

| Module | Role |
|---|---|
| `cli.py` | `status` / `test` / `post` / `schedule-plist` (Darwin) / `schedule-task` (Windows). Generators never load or register. |
| `config.py` | Loads the `opentweet:` block. The `ot_` key is named by `api_key_env`, never stored in YAML. |
| `client.py` | Loopback `/query` + OpenTweet REST. `trust_env=False`. |
| `runner.py` | Topic → query → validate → draft/schedule. |
| `selftest.py` | Pre-flight checks behind `opentweet test`. |

## Consent boundaries

- Topic comes from `--topic`, `--topic-file`, or `opentweet.topic_file`.
- Fail-closed on query errors, empty retrieval, `needs_confirm`, online `model_used`, empty or rail-prefixed answers, oversize answers, and missing credentials. The size limits are `opentweet.max_post_chars` and `opentweet.max_topic_chars` in `config.yaml`.
- Automatic scheduling requires the injection filter and screens both topic and answer. Answers containing URL/domain/email shapes, mentions, or hashtags are refused because this path cannot establish their provenance. Draft creation remains the review path.
- Logs/audit carry keyed `query_fingerprint(text)` + length + OpenTweet id — never the post body or Bearer token. `post --dry-run` still calls the local `/query` endpoint and validates the answer, but does not call OpenTweet to create a post.
- Exit codes: `0` ok · `2` refused/HTTP · `3` env/config.

When `auth.enabled` protects `/query`, supply a named CyClaw device token
through the environment variable selected by `opentweet.query.api_key_env`.
The ops `CYCLAW_API_KEY` does not satisfy `/query`'s session/device-token
authentication. OpenTweet's own `api_key_env` is a separate credential.

## Related

- Keychain wrapper: [`macos/README.md`](../macos/README.md)
- CredMan wrapper: [`powershell/README.md`](../powershell/README.md)
