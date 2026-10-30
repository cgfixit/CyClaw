# `opentweet/` — out-of-band X posting channel

Default-off OpenTweet adapter (`python -m opentweet.cli`), outside core
imports (I6). Generation uses loopback `POST /query` with
`user_confirmed_online: false`. Writes default to **drafts**; scheduling needs
`opentweet.schedule_enabled`. Schedulers never send `publish_now`.

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

With auth enabled, `opentweet.query.api_key_env` must name a CyClaw device
token; the ops `CYCLAW_API_KEY` cannot authorize `/query`. OpenTweet's
`api_key_env` names a separate credential.

## Related

- Keychain wrapper: [`macos/README.md`](../macos/README.md)
- CredMan wrapper: [`powershell/README.md`](../powershell/README.md)
