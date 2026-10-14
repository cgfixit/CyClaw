# fable-protocol knowledge base — §8.4 onward

Moved out of `SKILL.md` 2026-09-11 (issue #1351: SessionStart was injecting
this file's full body on every session start and every `/compact`; the
knowledge-base sections below are lookup/citation material, not per-turn
discipline, so they now load on demand via `/fable-protocol` or a direct
read instead of always sitting in context). `SKILL.md` §8.1-8.3 (identity,
communication contract, "the pattern") stay inline — those genuinely shape
tone every turn. Everything below is unchanged content, just relocated.

### 8.4 Flagship: CyClaw (github.com/cgfixit/CyClaw), package version 1.9.0

Lineage: OpenClaw skill research → SafeClaw (v1.1) → PsyClaw (v1.2) → CyClaw
(v1.4, "finally a claw name not already on GitHub"). Current train is "1.9.x"
under the same pyproject version; the changelog (`docs/changelog.txt`) is the
dated record.

What it is: an offline-first, trusted-operator (single by default, a small
trusted set once `auth.enabled`; see `docs/THREAT_MODEL.md`'s fifteenth
amendment), loopback-bound, single-tenant RAG server. FastAPI `gate.py` on
`127.0.0.1:8787`, a 12-node LangGraph security topology in `graph.py`, hybrid
ChromaDB + BM25 retrieval fused by RRF (k=60), local LLM via Ollama
(`qwen3.8:27b-mlx`), and triple-gated optional online fallback to Grok
(`grok-4.5`) or Claude (`claude-sonnet-5`) selected per query. A retrieval-only
MCP server (`mcp_hybrid_server.py`, `sampling: None`) exposes search with no LLM.

Everything about how to work in it is in `CLAUDE.md` (the operating manual),
`INVARIANTS.md`, `docs/THREAT_MODEL.md`, and `.claude/rules/PROJECT_RULES.md`.
Read CLAUDE.md fully before editing; this section is the part to know *cold*
without opening it.

**The six invariants and the load-bearing numbers** live in `CLAUDE.md` §3
and §2 ("Load-bearing numbers"), which `doc-sync` D3/D8 keep honest; this
file stopped carrying its own copy on 2026-10-13 after the copy drifted
(`max_context_tokens`, chunk sizes and the `num_ctx` floor were all a
generation stale). The two things to know cold without opening it: routing
is graph edges via four routers, never an LLM decision; and `min_score 0.028`
is RRF-scale (hybrid ceiling 2/60), do not "fix" it upward — the vault-hit
gate is `min_semantic_score`. Both providers are `enabled: true` since
2026-08-07 (armed), still triple-gated per request. Soul mutation is
governed (a human `reason`), not forbidden.

**The footgun to check first on any "CyClaw hangs" report** (carried forward,
still true): Ollama `num_ctx` must clear `max_context_tokens + max_tokens +
~1500` (`CLAUDE.md` §2 states the current floor; `macos/ollama-mlx.env` sets
`OLLAMA_CONTEXT_LENGTH`, and config-guard C12 fails when the env file is
below the floor) or RAG stalls at 0%.

**Integrity:** SHA-256 `soul.md` drift detection + SQLite shadow DB — this part
is shipped. **Proposed, NOT found in the current codebase** (verified by a
repo-wide grep for `DeBERTa`/`NLI entailment`/`semantic drift detection` at the
2026-09-06 merge that touched only these knowledge-handoff notes — apply §1.5/§3.1
here, re-verify before citing either as built): a 3-layer semantic drift
detector (structural diffing, NLI entailment via DeBERTa-v3-base-MNLI, embedding
distance via the existing MiniLM stack); and an "LLM Council" subgraph (5
personas, Send API fan-out, blind peer review, chairman synthesis — one earlier
note claimed "48/48 tests at design time," which this merge could not confirm
against `graph.py` or `docs/changelog.txt`). Treat both as open threads to ask
about, not shipped features to reference as fact.

**Traps a capable-but-new model falls into here** — the full, maintained list
is `CLAUDE.md` §4 (codebase traps) and the `cyclaw-gotchas` skill (session
traps: sandbox setup, PR-driving, review-bot handling, scheduled check-ins);
read those rather than a copy here. The three that bite first: the fresh
cloud sandbox has no CyClaw deps in any interpreter and its proxy denies the
PyTorch CPU index and `huggingface.co` (`driver.sh venv` handles the former;
the index cannot be built there); `import gate` at a test module's top level
boots the whole app; and `status: degraded`, `TELEMETRY KILL` on startup and
`503 INDEX_NOT_FOUND` are normal states, not defects.

**Git workflow he enforces** is `CLAUDE.md` §5 ("Commits, branches, PRs") and
§10: driver-matched branch prefixes, `[prefix] - sentence` subjects on every
commit (the tracked `commit-msg` hook refuses anything else), draft PRs with
the template body, never push to `main`, never force-push without his
explicit sign-off, commit as the session runtime's identity (never `CyClaw
Agent`, owner decision 2026-09-26), subscribe to every PR you open and drive
it to green with no polling beside a live subscription.

**Where the frontier is** (verify against `git log` and
`docs/changelog.txt` — this paragraph is a pointer, not a record): the live
agentic path is `agentic/real_repo_loop.py` (plan → patch → verify → human
decides → commit); the Python coding-harness console was removed 2026-09-11
and that role moved to the sibling CG-agent-harness repo; per-user auth
(RBAC, sessions, CSRF, device tokens, TLS), the default-off memory subsystem,
the default-off Telegram/OpenTweet channels, and the Numbat NDJSON plane all
shipped Aug–Sep 2026; the local model moved LM Studio → Ollama,
`qwen3.6:27b` → `qwen3.8:27b-mlx` on 2026-08-15; installs moved to hashed
`locks/` in 2026-10 (#1598). The 2026-09-11 skill-catalog cleanup (issue
#1351) is why this file exists as a reference and why `cyclaw-advisor` is
now `cyclaw-privacy`.

**Open threads he keeps returning to** (verify status before acting — see the
Integrity note above for two of these): 3-layer semantic drift detection for
`soul.md`; the LLM Council subgraph; seccomp/eBPF hardening
(`docs/SECCOMP_EBPF_HARDENING.md`); llama.cpp vs Ollama on the M5
(`docs/llamadotcpp-research.md`, `docs/m5-48gb-coding-expectations.md`).

### 8.5 Other projects

- vHC Simplifier (PowerShell; injection patched via `_ps_quote()`).
- scrape-n-email.
- Polymarket copy-trade bot (bounded [0,1] probability math).
- Pick-a-Politician ports (stored XSS patched in v1.2; the origin of the
  "security discipline travels to throwaway artifacts" rule, §5.1).
- cgfixit.com ecosystem, and the Claude Code skill suite in `.claude/skills/`
  (with Codex mirrors in `.agents/skills/`).

### 8.6 Hardware and environments (verified in config comments and CLAUDE.md)

- Primary inference box: Apple M5 Pro class, 48 GB unified memory, ~307 GB/s;
  the shipped 720s/4096-token budget is sized for it. Decode speed is measured
  with `scripts/measure_local_llm_throughput.py`, never assumed. Third-party
  reports put the shipped 4-bit MLX tag at roughly 29-34 tok/s.
- A Windows operator machine also exists (PowerShell launchers, `%USERPROFILE%\
  .CyClaw`, and the `gh` shim trap: bare `gh` is a py3dot12 shim, real CLI at
  `"/c/Program Files/GitHub CLI/gh.exe"`).
- Claude Code cloud sandbox (`sandbox-ccr-default`, Ubuntu 24.04): several
  Python minors on disk (3.11–3.13 on 2026-10-13; which one bare `python3`
  resolves to has changed between images), none preinstalled with CyClaw's
  deps (see `cyclaw-gotchas`; always use the venv's interpreter).
- Postgres is optional for soul, auth, and rate-limit stores; SQLite is default.

### 8.7 Decisions already made (do not re-litigate; cite, then move)

| Decision | Status | Where |
|---|---|---|
| Autonomous skill-write loops | rejected | `SKILL.md` §8.3 |
| DeepAgents subgraph | retired 2026-07-31, code kept | CLAUDE.md §2 key modules |
| chromadb CVE-2026-45829 | risk-accepted, embedded only | SECURITY.md (PROJECT_RULES.md restates it) |
| `min_score` 0.028 | intentional RRF scale | CLAUDE.md §2, §4 |
| `HF_HUB_OFFLINE` out of kill map | intentional | CLAUDE.md §4 |
| `/index/build` not API-key gated while `CYCLAW_API_KEY` is unset | intentional (first-run bricking); key-gated once the key is set | CLAUDE.md §2 route table |
| Grok and Claude `enabled: true` | armed 2026-08-07, triple gate unchanged | THREAT_MODEL 8th amendment |
| `api_key_optional` bypass | loopback-peer only, never Host header | CLAUDE.md §2 |
| Test mock `min_score` 0.75 vs prod 0.028 | both load-bearing, do not unify | CLAUDE.md §4 |
| `ci_rag_smoke.py` not `test_`-prefixed | intentional | CLAUDE.md §4 |
| Scope: single-operator → trusted-operator, single-tenant unchanged | 2026-09-06 | THREAT_MODEL 15th amendment |

### 8.8 Operational Constraints

- GitHub fetch: base repo pages and blob/main paths fetch fine; /tree/, /commits/,
  /pulls, PR pages are robots.txt-blocked. For blocked areas, request pasted
  content or use raw.githubusercontent.com. Don't pretend to have read what you
  couldn't fetch. (CWE-1022 / reverse tabnabbing is covered in `SKILL.md` §5.1.)

### 8.9 Sonnet-5 API notes and model-tier provenance

New tokenizer emits ~30% more tokens for the same text (per-token price
unchanged, per-request cost up; resize max_tokens tuned for 4.6 or output
truncates). Non-default temperature/top_p/top_k now return 400 (remove them).
Manual extended thinking removed (400); use adaptive thinking + effort. Prefill
still 400. Audit custom CyClaw wrappers/harnesses before swapping model ID to
claude-sonnet-5, or a stale param becomes a prod bug. 1M context is default and
max (no smaller variant). Cross-ref §5.5 for which tier to route a given task
to; those routing rules were last verified against Sonnet 5's system card on
2026-08-10 and never re-measured against Opus 5's own numbers — test his actual
prompts empirically before treating routing as fully settled.

This file was substantially authored 2026-09-02 by Claude Fable 5.1
(`claude-fable-5-1`, Mythos-class tier above Opus) as a knowledge-handoff
extraction, then merged into this skill 2026-09-06 (§11). If a future session
runs on Fable again, treat this file as a refresher, not a crutch — Fable can
hold CLAUDE.md, the route table, and a diff in one pass in a way most models
running this skill cannot; `SKILL.md` §9 is written for the latter case.

## History (consolidated 2026-10-13; the git log holds the full narrative)

- **v1.1** — recalibrated for Claude Sonnet 5 (launched 2026-06-30): some
  discipline is partly native on that model; apply anyway as cheap insurance.
- **v1.2 (2026-08-10)** — audited section by section against Anthropic's
  Sonnet 5 release notes and system card. Verdict: most of the protocol is
  reasoning structure, output format or project policy, which a
  better-calibrated model does not make obsolete; §2.3 (self-check) was
  compressed, §1.5/§3.1/§4.1 (verify stale-prone facts) kept at full strength
  because lower hallucination is not knowledge past a training cutoff. One
  opposite-direction finding: the Sonnet 5 card documents a regression on
  hostile-system-prompt/prefill resistance, a reason to keep this file lean
  beyond token cost.
- **v2.0 (2026-09-06)** — merged the companion `fable-5.1-cc` knowledge skill
  into this one at the owner's request; the two files had drifted on whether
  the "LLM Council" subgraph and 3-layer semantic drift detection were
  shipped (a repo-wide grep found neither; both are marked proposed in §8.4).
  `fable-5.1-cc`'s SKILL.md and wrapper are deleted; only dated audit docs and
  `docs/memories/zOld/` still name it.
- **v2.1 (2026-09-11, issue #1351)** — moved §8.4-8.9 here, out of the body the
  SessionStart hook injects on every start and `/compact`.
- **2026-10-04** — the version-history narrative moved out of `SKILL.md`'s
  header, and **2026-10-13** — §8.4's restated invariants, numbers, traps and
  git workflow were replaced by pointers to `CLAUDE.md` after they drifted.
