# Local Qwen dogfood (issue #1395)

Opt-in recipe. Not required CI. Does not grant network or write authority.
Does not use `CYCLAW_EVAL_LIVE` / Anthropic. Isolated corpus is this
directory — never `data/corpus/` or a production index.

## Named environment

Record these before claiming a live run:

- commit SHA (`git rev-parse HEAD`)
- Python 3.12.x
- `models.local_llm.model` (shipped default `qwen3.8:27b-mlx`)
- hardware (M5 Pro 48GB is the intended box)
- Ollama/LM Studio loopback only (`127.0.0.1` / `localhost` / `::1`)

## Run

```bash
CYCLAW_EVAL_DOGFOOD=1 python scripts/cyclaw-eval-dogfood.py
```

Writes `logs/evals/dogfood_matrix.md` (gitignored). Exit 2 if the env var is
not exactly `1`. Sanitizer probe does not call an LLM. Generation rows are
`unverified` if the local model is down — do not invent a green matrix.

Compact set: one fixture case per category (`direct_factual`, `paraphrase`,
`two_source_synthesis`, `false_premise`, `out_of_corpus`) plus
`check_input` on an injected query.

## Recovery (manual)

Do not automate a second policy engine. After a live generate() row:

1. Stop the local model process; rerun — generation should be `unverified`.
2. Start it again; rerun — generation should return.
3. Interrupt a long generate (Ctrl-C); process must exit; no extra writes.
4. Confirm `user_confirmed_online` is still required for Grok/Claude.

## Matrix columns

`id | category | status | detail` with `PASS` / `FAIL` / `generated` /
`retrieval_only` / `unverified`. Publish automated vs real-local vs unverified
explicitly.
