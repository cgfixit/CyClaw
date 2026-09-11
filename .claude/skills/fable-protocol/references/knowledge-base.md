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

**The six invariants** (wiring, not prompts; `python3
.claude/skills/invariant-guard/check_invariants.py` asserts them):
1. I1 RAG-first: `retrieve` is the unconditional entry node.
2. I2 Topology = policy: routing is graph edges via four routers only
   (`score_router`, `guardrail_router`, `user_gate_router`,
   `pre_action_hook_router`).
3. I3 Triple gate: Grok/Claude need `mode=="hybrid"` AND `<provider>.enabled`
   AND per-request `user_confirmed_online`. Both providers are `enabled: true`
   since 2026-08-07 (armed), still gated.
4. I4 Audit convergence: all eleven upstream paths reach `audit_logger` before END.
5. I5 Soul governance: `soul.md` mutation needs a human `reason` string, atomic
   write via `PersonalityManager`. Governed, not forbidden.
6. I6 Module isolation: the core six (`gate.py`, `gate_ops.py`, `gate_auth.py`,
   `gate_memory.py`, `graph.py`, `mcp_hybrid_server.py`) never import
   `agentic`/`sync`/`guardrails`/`harness`/`telegram`/`opentweet`, and vice versa.

**Load-bearing numbers** (source: `config.yaml`, `pyproject.toml`; never invent):
`min_score 0.028` is RRF-scale, not cosine, do not "fix" it upward; `rrf_k 60`;
`graph_timeout_sec 780` > `local_llm.timeout_sec 720`; `max_tokens 4096`;
`max_context_tokens 8000`; `soul_max_chars 8000`; chunk `512`/overlap `50`; rate
limit `60`/`60s` per IP; 40 `banned_patterns` (phrases are contractual, count is
documentary); coverage `fail_under 80`; Python `>=3.12,<3.13`.

**The footgun to check first on any "CyClaw hangs" report** (carried forward,
still true): Ollama `num_ctx` must clear `max_context_tokens + max_tokens + ~1500`
(floor 13,596; `macos/ollama-mlx.env` sets 16384) or RAG stalls at 0%.

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

**Traps a capable-but-new model falls into here** (full list CLAUDE.md §4):
- Fresh sandbox: bare `python3` is 3.11, and as of 2026-09-06 NO interpreter on
  the default cloud sandbox image ships CyClaw's deps preinstalled — build
  `/root/.venv-cyclaw-312` with `python3.12 -m venv`, torch `2.13.0+cpu` first
  (falling back to plain PyPI torch when the egress proxy denies
  `download.pytorch.org`), then requirements with `--ignore-installed PyYAML`.
  macOS needs plain torch (no `+cpu`). The `cyclaw-gotchas` skill's `driver.sh`
  does this end to end — load it for any sandbox setup/test/PR-driving task.
- `import gate` at test top level boots the whole app. Patch or subprocess.
- `status: degraded` without Ollama and `TELEMETRY KILL` at startup are normal.
- `security.require_env` is decorative. Tests need only `GROK_API_KEY=dummy`.
- The `_TELEMETRY_KILL` binding in `gate.py` must stay above heavy imports;
  invariant-guard G1 finds it by AST. `HF_HUB_OFFLINE` is excluded from the kill
  map on purpose. `ORT_TELEMETRY_OPT_OUT` is inert; `ORT_DISABLE_TELEMETRY=1`
  plus `disable_telemetry_events()` are the real controls.
- BM25 stays JSON (pickle = RCE). Audit log stores SHA-256 of queries, never text.
- No `print` in library code, no bare `except`, no `shell=True`, no TODO/FIXME
  comments, typed errors rooted at `RAGError`, exit codes are an API.
- Never docstrings as multi-line comments except at file top or function top.
- New POST routes must be added to `test_terminal_contract`'s `_POST_PATHS`.
- mypy is not a CI gate; ruff `--select F,B,S` is. Bare `pytest` runs no coverage.
- `pydantic`/`pydantic-core` lock-step; numpy `<2`; chromadb CVE is risk-accepted
  (embedded `PersistentClient` only). Do not file a "fix".
- Session-process traps (sandbox setup, PR-driving, review-bot handling,
  scheduled check-ins) are a separate, larger list — see the `cyclaw-gotchas`
  skill rather than duplicating it here.

**Git workflow he enforces:** driver-matched branch prefixes (`claude/`, `codex/`,
`grok/`, `kimi/`, `CyClaw/`, `agent/`), never push to `main`, never force-push
without his explicit sign-off, draft PRs only, one concern each, PR body follows
`.github/PULL_REQUEST_TEMPLATE.md` (title form `[prefix] - sentence`; the
squashed merge commit carries that title, which is why `git log` shows
`[security] - ...` rather than `feat:` despite CLAUDE.md §5 asking for
conventional commits on the branch itself). Subscribe to every PR you open and
drive it to green; no polling loops beside a live subscription. Identity for
commits: `CyClaw Agent <cyclaw-agent@users.noreply.github.com>` unless the host
stop-hook demands otherwise.

**Recent trajectory (Aug-Sep 2026, from `git log` and changelog)** so you know
where the frontier is: doc-sync + verify-deps skill hardening and a full
38-README reconciliation pass (#1319); the `cyclaw-gotchas` session-lessons
skill (#1320); a fifteenth threat-model amendment widening scope from
single-operator to trusted-operator while keeping single-tenant (#1319);
hash-pinned telemetry kill maps at boot (#1268); harness Origin check with port
and scheme (#1267); Grok proposer spend ledgering (#1266); nltk 3.10.3 pin and
256-char Porter token cap for the PorterStemmer DoS cluster (#1258); Numbat
NDJSON mainline plane (every audit record projected, fail-soft); default-off
Unslop slop-detection probe for the agentic loop; per-user auth with RBAC,
sessions, CSRF, device tokens, TLS via `cyclaw-gen-cert`; default-off memory
subsystem (facts + episodes, SQLite FTS5, propose/apply governance); out-of-band
Telegram and OpenTweet channels (disabled by default); `real_repo_loop` plan →
patch → verify → human decides → commit. The Python coding-harness console was
removed on 2026-09-11; that role moved to the sibling CG-agent-harness repo. Local model moved LM Studio → Ollama, `qwen3.6:27b` →
`qwen3.8:27b-mlx` on 2026-08-15. Skill-catalog context-tax cleanup landed
2026-09-11 (issue #1351): `general-purpose` deleted, `python-coding-agent` and
this knowledge-base section both moved their bulk into `references/`,
`cyclaw-advisor` renamed `cyclaw-privacy`, `CyClaw-Sandbox`'s frontmatter/folder
mismatch fixed, several chore/loop skills gained `disable-model-invocation`,
and the fat `CyClaw-Optimize`/`*-refactor` command-wrapper duplicates were
trimmed to thin pointers.

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
  (with Codex mirrors in `.codex/skills/`).

### 8.6 Hardware and environments (verified in config comments and CLAUDE.md)

- Primary inference box: Apple M5 Pro class, 48 GB unified memory, ~307 GB/s;
  the shipped 720s/4096-token budget is sized for it. Decode speed is measured
  with `scripts/measure_local_llm_throughput.py`, never assumed. Third-party
  reports put the shipped 4-bit MLX tag at roughly 29-34 tok/s.
- A Windows operator machine also exists (PowerShell launchers, `%USERPROFILE%\
  .CyClaw`, and the `gh` shim trap: bare `gh` is a py3dot12 shim, real CLI at
  `"/c/Program Files/GitHub CLI/gh.exe"`).
- Claude Code cloud sandbox (`sandbox-ccr-default`, Ubuntu 24.04): Python 3.10
  through 3.13 all on disk, none preinstalled with CyClaw's deps as of
  2026-09-06 (see the trap list above and `cyclaw-gotchas`).
- Postgres is optional for soul, auth, and rate-limit stores; SQLite is default.

### 8.7 Decisions already made (do not re-litigate; cite, then move)

| Decision | Status | Where |
|---|---|---|
| Autonomous skill-write loops | rejected | `SKILL.md` §8.3 |
| DeepAgents subgraph | retired 2026-07-31, code kept | CLAUDE.md §2 key modules |
| chromadb CVE-2026-45829 | risk-accepted, embedded only | PROJECT_RULES.md |
| `min_score` 0.028 | intentional RRF scale | CLAUDE.md §2, §4 |
| `HF_HUB_OFFLINE` out of kill map | intentional | CLAUDE.md §4 |
| `/index/build` not API-key gated | intentional (first-run bricking) | CLAUDE.md §2 route table |
| Grok and Claude `enabled: true` | armed 2026-08-07, triple gate unchanged | THREAT_MODEL 8th amendment |
| `api_key_optional` bypass | loopback-peer only, never Host header | CLAUDE.md §2 |
| Test mock `min_score` 0.75 vs prod 0.028 | both load-bearing, do not unify | CLAUDE.md §4 |
| `ci_rag_smoke.py` not `test_`-prefixed | intentional | CLAUDE.md §4 |
| Scope: single-operator → trusted-operator, single-tenant unchanged | 2026-09-06 | THREAT_MODEL 15th amendment |

### 8.8 Operational Constraints

- GitHub fetch: base repo pages and blob/main paths fetch fine; /tree/, /commits/,
  /pulls, PR pages are robots.txt-blocked. For blocked areas, request pasted
  content or use raw.githubusercontent.com. Don't pretend to have read what you
  couldn't fetch.
- CWE-1022: "Use of Web Link to Untrusted Target with window.opener Access" —
  reverse tabnabbing. Fix: rel="noopener noreferrer" on target=_blank, or
  window.opener=null on programmatic window.open(). Apply per §5.1.

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

## Consolidation history (full detail)

This skill previously shipped as two files — `fable-protocol` (the discipline
layer, `SKILL.md` §1-7, plus its checklist and meta sections) and a companion
`fable-5.1-cc` (the knowledge layer, now this file's §8-9, folded into
`SKILL.md`'s META section originally). They were merged on the owner's
explicit request once both had shipped long enough to show the split cost
more than it bought: two files to keep in sync, and genuine drift between
them where they overlapped — the two files' "CyClaw knows cold" sections
disagreed on whether the LLM Council subgraph and 3-layer semantic drift
detection were shipped-and-tested or still open proposals (§8.4's Integrity
paragraph resolves this the honest way: neither was found in the actual
codebase at merge time). Every real session needed both loaded anyway.
`fable-5.1-cc`'s SKILL.md and command wrapper are deleted; nothing else in
this repo should reference them going forward except as historical record
(dated audit docs under `docs/audits/` and the legacy snapshot under
`docs/memories/zOld/` are left as they were — dated docs stay dated).
