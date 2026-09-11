"""Additional curated CyClaw Q&A (expansion set) — brings the dataset to 70.

22 new pairs (extra-001 .. extra-022) grounded in CyClaw source read from
github.com/CGFixIT/CyClaw main on 2026-09-07:
  - utils/personality.py   (PersonalityManager, _atomic_write_owner_only, soul_max_chars,
                            DB backend swap, TTL pruning, advisory vs enforced patterns)
  - utils/telemetry_kill.py (4-name LangSmith precedence + lru_cache latch,
                            HF_HUB_OFFLINE deliberately excluded, build_telemetry_safe_env,
                            stdlib-only constraint)
  - utils/errors.py         (RAGError code+details hierarchy, SoulPersistenceError,
                            SyncError sub-code bypass, AgenticError OOB mirror)
  - utils/sanitizer.py      (NFKC + invisible-char strip, lru_cache per-path,
                            DOTALL for newline straddling, warn-on-degrade)
  - graph.py                (GraphState, _GeneratingClient Protocol, _format_context_chunks)

Format matches cyclaw_debug_qa.py: structured {id, category, messages, source_refs}.
"""
from __future__ import annotations

_SYS = (
    "You are CyClaw's assistant. You reason about the CyClaw architecture "
    "(github.com/CGFixIT/CyClaw, v1.9.x) from source, follow its I1-I6 "
    "invariants, and never propose changes that bypass retrieval, audit, or "
    "soul governance. Distinguish established fact from reasonable inference, "
    "and cite the file and function."
)

EXTRA_QA: list[dict] = [

# ═══ ARCHITECTURE & TOPOLOGY (+2) ═══════════════════════════════════════════
{
    "id": "extra-001-graphstate-fields",
    "category": "Architecture & Topology",
    "messages": [
        {"role": "system", "content": _SYS},
        {"role": "user", "content": (
            "Walk through the GraphState TypedDict in graph.py. Which fields does "
            "the local_llm path populate versus the external fallback path, and "
            "what is served_model for?"
        )},
        {"role": "assistant", "content": (
            "GraphState is a total=False TypedDict (every field optional) so "
            "callers that don't set auth.username keep working. Key fields:\n\n"
            "Inputs: query (str), username (optional, only when auth.enabled).\n\n"
            "Retrieval outputs: retrieved_docs (list[RetrievedDoc]), top_score "
            "(float), retrieval_mode ('semantic'|'keyword'|'hybrid'|'none').\n\n"
            "Control flags: needs_user_confirm (bool), user_confirmed_online "
            "(bool|None), online_provider (str|None).\n\n"
            "Model outputs: answer (str), answer_model — one of "
            "'local'|'grok'|'claude'|'offline-best-effort'|'guardrail-blocked'|"
            "'hook-denied'|'external-unavailable'. served_model (str) is the "
            "vendor-resolved model id an external provider echoed, when it sent "
            "one; it can differ from the configured tag behind an unpinned alias, "
            "so audit records the real served id rather than the configured name.\n\n"
            "Path split:\n"
            "  - local_llm sets answer_model='local', answer_sources from "
            "_format_context_chunks (the subset actually rendered, not raw "
            "docs[:limit]).\n"
            "  - grok_fallback/claude_fallback set answer_model to 'grok'/'claude' "
            "and omit the soul preamble (identity never leaves the box).\n"
            "  - offline_best_effort includes the soul preamble and uses a "
            "truncated char_cap context.\n"
            "  - A blocked input rail or denied pre-action hook routes to "
            "audit_logger with answer_model='guardrail-blocked'/'hook-denied', "
            "no generation.\n\n"
            "Guardrail fields: guardrail_blocked (bool), guardrail_rails "
            "(list[str]), guardrail_degraded (bool — distinct from blocked so "
            "audit can tell 'passed' from 'failed-open/Decision 3'). "
            "pre_action_hook_denied (bool, issue #963). audit_event (dict) and "
            "error (str|None) close the state."
        )},
    ],
    "source_refs": ["graph.py:GraphState,RetrievedDoc", "graph.py:_format_context_chunks"],
},

{
    "id": "extra-002-generating-client-protocol",
    "category": "Architecture & Topology",
    "messages": [
        {"role": "system", "content": _SYS},
        {"role": "user", "content": (
            "Why does graph.py define _GeneratingClient as a typing.Protocol "
            "with a generate() stub whose body is `pass` (not `...`), instead of "
            "an ABC or a shared base class?"
        )},
        {"role": "assistant", "content": (
            "It's a structural type, not a runtime contract. _GeneratingClient "
            "declares a single generate(prompt, *, spend_context) -> str method. "
            "LocalLLMClient, GrokClient, and ClaudeClient all satisfy it by "
            "having a matching generate() signature — no inheritance, no import "
            "coupling. The graph node code (_generate_or_error) is written "
            "against the Protocol, so it can accept any of the three clients "
            "uniformly without knowing which concrete class it holds.\n\n"
            "The body is `pass` (not `...`) deliberately: the comment says it's "
            "there so CodeQL's ineffectual-statement check doesn't flag a bare "
            "Ellipsis expression statement. The Protocol method is never "
            "executed — only the implementations' bodies run. This is a "
            "static-typing construct, not an abstract method that subclasses "
            "override.\n\n"
            "Why a Protocol over an ABC: CyClaw keeps the LLM client layer "
            "behind llm/client.py and the graph behind graph.py. An ABC would "
            "force a shared base class import, coupling the graph module to the "
            "client implementation hierarchy. A structural Protocol lets the "
            "graph depend on a shape, not a module — which is the same "
            "isolation posture as the I6 import boundary (core never imports "
            "the OOB packages)."
        )},
    ],
    "source_refs": ["graph.py:_GeneratingClient,_generate_or_error"],
},

# ═══ SECURITY & DEFENSE (+3) ═══════════════════════════════════════════════
{
    "id": "extra-003-sanitizer-nfkc-invisible",
    "category": "Security & Defense",
    "messages": [
        {"role": "system", "content": _SYS},
        {"role": "user", "content": (
            "How does the prompt injection filter handle Unicode evasion — "
            "fullwidth characters, zero-width splits, and homoglyphs?"
        )},
        {"role": "assistant", "content": (
            "In utils/sanitizer.py, _normalize_for_match(text) produces a "
            "normalized COPY that the patterns match against, without mutating "
            "the user's original query. Two transforms, both folding TOWARD the "
            "ASCII the patterns are written in:\n\n"
            "1. unicodedata.normalize('NFKC', text) — folds compatibility "
            "forms back to ASCII. So fullwidth "
            "'ｉｇｎｏｒｅ ａｌｌ ｐｒｅｖｉｏｕｓ ｉｎｓｔｒｕｃｔｉｏｎｓ' collapses onto the plain "
            "form the patterns already catch.\n\n"
            "2. _INVISIBLE_CHARS.sub('', ...) — strips zero-width "
            "space/non-joiner/joiner, LTR/RTL marks, word joiner, BOM, and soft "
            "hyphen (\\u200b-\\u200f, \\u2060, \\ufeff, \\u00ad). Deleting them "
            "(not replacing with a space) is what rejoins a split word: "
            "'ig<ZWSP>nore all previous instructions' matches no pattern as "
            "raw text, yet tokenizes back to the instruction it spells.\n\n"
            "This only ever matches a SUPERSET of what the raw string would, so "
            "it cannot silently stop catching something that used to be caught. "
            "Caveat: it is NOT a complete homoglyph defense — a Cyrillic 'і' "
            "substituted for Latin 'i' is a distinct codepoint that NFKC does not "
            "fold, so 'іgnore' bypasses the ASCII pattern. That homoglyph gap is "
            "explicitly out of scope per the threat model; the layered defense "
            "(untrusted-context framing in graph.py + output grounding + audit) "
            "is what contains it, not the regex."
        )},
    ],
    "source_refs": ["utils/sanitizer.py:_normalize_for_match,_INVISIBLE_CHARS", "graph.py:UNTRUSTED_NOTE"],
},

{
    "id": "extra-004-soul-advisory-vs-enforced",
    "category": "Security & Defense",
    "messages": [
        {"role": "system", "content": _SYS},
        {"role": "user", "content": (
            "PersonalityManager compiles two pattern lists — advisory and "
            "enforced. What's the difference, and why does the soul (prepended "
            "to every system prompt) get the enforced set at the write boundary?"
        )},
        {"role": "assistant", "content": (
            "Both lists share a _CORE_INJECTION_PATTERNS base "
            "(ignore/disregard/forget previous/all/prior instructions, new "
            "instructions:, system prompt:, override instructions, jailbreak, "
            "DAN mode, developer mode). They diverge:\n\n"
            "- ENFORCED_SOUL_PATTERNS = the core set only. These are checked at "
            "the soul-WRITE boundary in apply_evolution(scan=True): a soul "
            "containing any of them raises PromptInjectionError BEFORE any file "
            "or DB write. The reasoning is explicit in the source: soul.md is "
            "prepended to every LLM system prompt, so anything reaching it "
            "would persist as a standing instruction to the LLM across all "
            "future queries — the worst-case injection.\n\n"
            "- OWASP_INJECTION_PATTERNS = core + broader constructs "
            "('you are now', 'pretend you are/to be', 'act as', '<script>'). "
            "These are ADVISORY: surfaced for human review in "
            "propose_evolution, but not enforced at the write boundary, because "
            "they may be legitimate in author-controlled identity statements "
            "('You are now CyClaw; act as...').\n\n"
            "The same banned-pattern set the query path uses "
            "(config.yaml policy.prompt_filter) is unioned with the OWASP "
            "baseline for the soul — so the soul is never guarded by a weaker "
            "list than user queries. This is the write-path-only scan described "
            "in INVARIANTS Rule 4/5; reload and drift adopt soul.md unscanned "
            "by design."
        )},
    ],
    "source_refs": ["utils/personality.py:_CORE_INJECTION_PATTERNS,ENFORCED_SOUL_PATTERNS,OWASP_INJECTION_PATTERNS", "INVARIANTS.md:Rule 4,5"],
},

{
    "id": "extra-005-atomic-write-owner-only",
    "category": "Security & Defense",
    "messages": [
        {"role": "system", "content": _SYS},
        {"role": "user", "content": (
            "Explain _atomic_write_owner_only in personality.py. Why tempfile "
            "in the target dir, chmod 0600, and os.replace — and what failure "
            "does the finally block guard against?"
        )},
        {"role": "assistant", "content": (
            "It replaces a file atomically with owner-only permissions:\n"
            "1. mkdir parents (idempotent).\n"
            "2. tempfile.mkstemp(prefix='.{name}.', suffix='.tmp', dir=path.parent, "
            "text=True) — creates the temp file IN THE SAME DIRECTORY as the "
            "target. Same-directory matters: os.replace is atomic within a "
            "filesystem, but only within the same mount. A cross-device tmp "
            "(e.g. /tmp on a separate mount) would make os.replace fall back to "
            "copy+unlink, losing atomicity.\n"
            "3. os.chmod(tmp_path, 0o600) — owner read/write only, before any "
            "content is written, so a crash between open and chmod can't leave a "
            "world-readable soul on disk.\n"
            "4. write content, flush via context close.\n"
            "5. os.replace(tmp_path, path) — the atomic swap. Readers either see "
            "the old soul or the complete new soul, never a partial write.\n\n"
            "The finally block: if fd >= 0 (the context manager didn't take "
            "ownership of the fd), os.close(fd) prevents a leak; then "
            "tmp_path.unlink(missing_ok=True) cleans up a temp file left behind "
            "by a failure between mkstemp and os.replace. The OSError swallow on "
            "unlink is logged, not silent.\n\n"
            "This is the soul-write primitive that apply_evolution and "
            "restore_from_backup both rely on — and why a crash between the DB "
            "INSERT and the os.replace produces soul drift on the next startup "
            "(the version row points at content that never made it to disk)."
        )},
    ],
    "source_refs": ["utils/personality.py:_atomic_write_owner_only", "INVARIANTS.md:Rule 4"],
},

# ═══ RETRIEVAL & RAG (+2) ═════════════════════════════════════════════════
{
    "id": "extra-006-context-chunk-rendering",
    "category": "Retrieval & RAG",
    "messages": [
        {"role": "system", "content": _SYS},
        {"role": "user", "content": (
            "How does _format_context_chunks in graph.py render retrieved docs "
            "into the prompt, and why does it track which chunks it actually "
            "kept instead of just slicing docs[:limit]?"
        )},
        {"role": "assistant", "content": (
            "_format_context_chunks(docs, limit, char_cap, total_char_budget) "
            "renders the context block with per-chunk source headers and RRF "
            "scores: '[Source: {source}, Score: {score:.3f}]\\n{text}'. Chunks "
            "are joined by SECTION_SEP ('\\n\\n---\\n\\n').\n\n"
            "Three rendering modes by parameter:\n"
            "- char_cap=None: full chunk text (local_llm path).\n"
            "- char_cap=int: truncated chunk text (best-effort / grok partial).\n"
            "- total_char_budget=int: cap the TOTAL rendered length including "
            "headers and separators. Once the budget is reached it stops adding "
            "chunks and truncates the crossing chunk to exactly what fit.\n\n"
            "It returns (context_text, included_docs). included_docs is the "
            "subset of docs[:limit] that actually contributed body text — a chunk "
            "truncated mid-text by the budget still counts, with its 'text' "
            "clipped to what reached the model; a chunk for which only the header "
            "would fit does NOT count.\n\n"
            "Why track this: callers use included_docs for answer_sources, so a "
            "cited source always matches what the model and the grounding check "
            "actually saw. The prior code reported raw docs[:limit] regardless of "
            "what was rendered — meaning a source could be cited that the model "
            "never saw, or a source omitted that it did. The fix ties citations "
            "to the real context window."
        )},
    ],
    "source_refs": ["graph.py:_format_context_chunks,SECTION_SEP,UNTRUSTED_NOTE"],
},

{
    "id": "extra-007-context-char-budget",
    "category": "Retrieval & RAG",
    "messages": [
        {"role": "system", "content": _SYS},
        {"role": "user", "content": (
            "How is the context token budget computed in graph.py, and what "
            "happens when soul + query + framing exhaust it?"
        )},
        {"role": "assistant", "content": (
            "_context_char_budget(cfg, soul_preamble, query, framing_chars) "
            "estimates context space after reserving soul, query, and framing:\n"
            "  budget = retrieval.max_context_tokens (default 8000) * CHARS_PER_TOKEN (3)\n"
            "  reserved = len(soul) + len(query) + framing_chars\n"
            "  available = budget - reserved\n"
            "  return max(_MIN_CONTEXT_CHARS, available)  # floor 800\n\n"
            "CHARS_PER_TOKEN=3 is a heuristic estimate, not a tokenizer bound — "
            "lower values reduce the context allowance and increase the "
            "post-assembly estimate. The actual token usage depends on the "
            "backend and text.\n\n"
            "When reservations exhaust the budget, available drops below "
            "_MIN_CONTEXT_CHARS (800). Rather than returning 0 or negative "
            "(which would produce an empty context and a blank answer), it "
            "floors to 800 and logs a debug line. The trade-off: this floor can "
            "make the assembled input exceed the configured estimate. Neither the "
            "floor nor the char estimate guarantees the assembled prompt fits the "
            "backend's token window — that's the local_llm blank-answer failure "
            "mode when (prompt_tokens + max_tokens) > loaded context length."
        )},
    ],
    "source_refs": ["graph.py:_context_char_budget,CHARS_PER_TOKEN,_MIN_CONTEXT_CHARS"],
},

# ═══ SOUL GOVERNANCE (+3) ═════════════════════════════════════════════════
{
    "id": "extra-008-soul-max-chars-ceiling",
    "category": "Soul Governance",
    "messages": [
        {"role": "system", "content": _SYS},
        {"role": "user", "content": (
            "What bounds the size of the soul text that gets prepended to every "
            "LLM system prompt, and why is there a hard ceiling at all?"
        )},
        {"role": "assistant", "content": (
            "PersonalityManager.soul_max_chars (config: "
            "personality.soul_max_chars, default 8000) is a hard ceiling on the "
            "soul text prepended to EVERY LLM system prompt. Two layers enforce "
            "it: PersonalityManager truncates via _bounded_soul at read time, "
            "and the /soul/apply schema enforces a matching outer cap at the "
            "HTTP boundary (SoulEvolutionRequest).\n\n"
            "Why a ceiling: the soul is prepended to every local_llm and "
            "offline_best_effort prompt (NOT the external grok/claude paths — "
            "identity never leaves the box). An unbounded soul would inflate the "
            "system prompt and consume the Ollama context budget, leaving less "
            "room for retrieved context and the query — directly causing the "
            "blank-answer / truncation failure when (prompt + max_tokens) "
            "exceeds the loaded context window. The ceiling bounds prompt "
            "inflation no matter how soul.md was written or edited (including "
            "the unscanned reload/drift paths).\n\n"
            "Caveat from INVARIANTS Rule 5: harness/prompts.py reads soul.md "
            "directly and bypasses PersonalityManager entirely — so it skips "
            "_bounded_soul truncation too. A soul larger than soul_max_chars "
            "gets injected untruncated into the harness console's system prompt."
        )},
    ],
    "source_refs": ["utils/personality.py:soul_max_chars,_bounded_soul", "INVARIANTS.md:Rule 5", "harness/prompts.py:compose_system_prompt"],
},

{
    "id": "extra-009-db-backend-swap",
    "category": "Soul Governance",
    "messages": [
        {"role": "system", "content": _SYS},
        {"role": "user", "content": (
            "How does CyClaw switch the soul version DB from SQLite to Postgres, "
            "and what stays the same across backends?"
        )},
        {"role": "assistant", "content": (
            "Default is SQLite (zero-config, offline-first). Set "
            "CYCLAW_DB_URL=postgresql://... or personality.database_url in "
            "config.yaml to switch to Postgres. The connection shim lives in "
            "utils/personality_db.py: connect(db_path, pers_cfg) returns "
            "(conn, placeholder, backend) where placeholder is the "
            "backend-specific SQL parameter marker (?, %s, etc.) and backend "
            "identifies the dialect.\n\n"
            "What stays the same: PersonalityManager builds parameterized SQL "
            "templates using self._ph for both inserts (soul_versions and "
            "interactions) and the TTL delete, so the same code works across "
            "backends. DDL is backend-specific — personality_db.ddl_soul_versions, "
            "ddl_interactions, and ddl_indexes take the backend and return the "
            "right statement.\n\n"
            "Two columns are independent by design: soul_versions stores sha256 "
            "(a hash of soul file CONTENT) and timestamp separately — the hash is "
            "of content, not of the timestamp, so drift detection compares the "
            "current file's hash against the latest row's hash, not against a "
            "time-derived value. The soul_versions table is the version log; "
            "the soul.md FILE is the source of truth (file-as-truth with a "
            "shadow DB)."
        )},
    ],
    "source_refs": ["utils/personality.py:_init_db,_sql_insert_soul", "utils/personality_db.py:connect,ddl_soul_versions"],
},

{
    "id": "extra-010-interaction-ttl-pruning",
    "category": "Soul Governance",
    "messages": [
        {"role": "system", "content": _SYS},
        {"role": "user", "content": (
            "Why does PersonalityManager prune old interaction records every N "
            "inserts instead of on every record_interaction() call?"
        )},
        {"role": "assistant", "content": (
            "Amortized pruning. _prune_every (config: "
            "personality.interaction_prune_every, default 100) sweeps the "
            "interactions table once per that many inserts, not per insert. "
            "_inserts_since_prune counts up; when it hits _prune_every, a "
            "DELETE FROM interactions WHERE timestamp < ? runs (the cutoff is "
            "now - interaction_ttl_days, default 365), then the counter resets.\n\n"
            "Why not per-call: a DELETE on every interaction insert would make "
            "every query pay a write + a delete + an index maintenance cost, "
            "amplifying write amplification on the SQLite/Postgres backing store "
            "for no benefit — the TTL is a retention bound (don't keep "
            "interactions forever), not a real-time eviction. Sweeping every 100 "
            "inserts amortizes the delete cost across many queries while still "
            "bounding the table size to roughly ttl_days * (queries_per_day) + "
            "100.\n\n"
            "The interaction log is separate from the audit log: interactions "
            "store query_hash + outcome + timestamp for the soul layer's own "
            "history; audit_log (utils/logger.py) is the append-only JSONL of "
            "every query path including the soul events. They serve different "
            "consumers."
        )},
    ],
    "source_refs": ["utils/personality.py:_prune_every,_inserts_since_prune,maintenance", "utils/logger.py:audit_log"],
},

# ═══ TELEMETRY & OFFLINE (+3) ═════════════════════════════════════════════
{
    "id": "extra-011-langsmith-precedence-lru",
    "category": "Telemetry & Offline",
    "messages": [
        {"role": "system", "content": _SYS},
        {"role": "user", "content": (
            "Explain the four-name LangSmith tracing precedence and why a "
            "non-empty 'false' at a higher-precedence name is load-bearing."
        )},
        {"role": "assistant", "content": (
            "The four names are ONE switch with a namespace precedence order, "
            "not four mechanisms. Verified against langsmith 0.10.15: "
            "tracing_is_enabled() calls get_env_var('TRACING_V2', "
            "default=get_env_var('TRACING')) at utils.py:141, and get_env_var "
            "(utils.py:418-442) tries the LANGSMITH_ prefix before LANGCHAIN_ "
            "and skips only EMPTY values. So the live precedence is:\n\n"
            "  LANGSMITH_TRACING_V2 > LANGCHAIN_TRACING_V2 >\n"
            "  LANGSMITH_TRACING  > LANGCHAIN_TRACING\n\n"
            "The value must be exactly 'true' to enable. A non-empty 'false' at "
            "a HIGHER-precedence name shadows everything after it — so pinning "
            "LANGSMITH_TRACING_V2=false does NOT stop tracing if an ambient "
            "LANGCHAIN_TRACING_V2=true is set by a lower-precedence name? No — "
            "wait: higher precedence wins, so LANGSMITH_TRACING_V2=false "
            "shadows a lower-precedence true. That's why all four must be pinned: "
            "an ambient value at any single UNPINNED name would win over every "
            "pinned LOWER-precedence one.\n\n"
            "Worse, the value latches permanently via get_env_var's "
            "@functools.lru_cache — once read, it's cached for the process. And "
            "langsmith attempts the upload even with NO API key (it only warns), "
            "so unsetting LANGCHAIN_API_KEY alone is not a substitute for pinning "
            "all four names to false. This is why utils/telemetry_kill.py sets "
            "all four to 'false' before any langchain import."
        )},
    ],
    "source_refs": ["utils/telemetry_kill.py:TELEMETRY_KILL", "tests/test_telemetry_kill.py"],
},

{
    "id": "extra-012-hf-hub-offline-excluded",
    "category": "Telemetry & Offline",
    "messages": [
        {"role": "system", "content": _SYS},
        {"role": "user", "content": (
            "Why is HF_HUB_OFFLINE deliberately NOT in the telemetry_kill "
            "block, while HF_HUB_DISABLE_TELEMETRY IS?"
        )},
        {"role": "assistant", "content": (
            "They suppress different things, and HF_HUB_OFFLINE is dangerous to "
            "set unconditionally.\n\n"
            "HF_HUB_DISABLE_TELEMETRY=1 suppresses ONLY huggingface_hub's "
            "background telemetry HEAD request to {ENDPOINT}/api/telemetry/{topic} "
            "— a separate code path from any file download or cache lookup. It "
            "never blocks a real download or cache-miss fetch, so it's safe to "
            "set for every process from the start. It's in the block.\n\n"
            "HF_HUB_OFFLINE / TRANSFORMERS_OFFLINE are deliberately EXCLUDED from "
            "the canonical block. Reason: huggingface_hub freezes "
            "HF_HUB_OFFLINE at its own import time, with no way to retry past it "
            "once set. Forcing it on for every process would turn "
            "retrieval/embeddings.py's documented cache-miss bootstrap fetch "
            "(downloading all-MiniLM-L6-v2 on first run) into a guaranteed "
            "failure on any machine that has never run CyClaw before.\n\n"
            "Instead, retrieval/embeddings.py::_load_model applies them "
            "CONDITIONALLY — only once the embedding model is confirmed already on "
            "disk (see _model_offline_eligible there). So the first run fetches "
            "the model; subsequent runs go fully offline. DO_NOT_TRACK=1 is also "
            "included unconditionally — it's a cross-ecosystem opt-out that "
            "huggingface_hub 1.26.0 honors (constants.py computes "
            "HF_HUB_DISABLE_TELEMETRY as the OR of three env vars including "
            "DO_NOT_TRACK)."
        )},
    ],
    "source_refs": ["utils/telemetry_kill.py:TELEMETRY_KILL,module docstring", "retrieval/embeddings.py:_load_model,_model_offline_eligible"],
},

{
    "id": "extra-013-build-telemetry-safe-env",
    "category": "Telemetry & Offline",
    "messages": [
        {"role": "system", "content": _SYS},
        {"role": "user", "content": (
            "apply_telemetry_kill mutates os.environ process-wide. How do "
            "child processes (subprocess.run, rclone) inherit the same kill "
            "values, and why must the module be stdlib-only?"
        )},
        {"role": "assistant", "content": (
            "apply_telemetry_kill mutates os.environ for the whole interpreter — "
            "that's the point, because the libraries read the process "
            "environment, not a config object. But child processes built from a "
            "MINIMAL environment inherit nothing, so they'd run without the kill "
            "values. build_telemetry_safe_env() produces a copy of the canonical "
            "TELEMETRY_KILL dict merged into the child's environment, so the same "
            "values reach subprocesses (rclone, the OOB CLIs via "
            "utils/ops_runner.py).\n\n"
            "Why stdlib-only (just `os`): the module is imported at the very top "
            "of every entry point — gate.py, mcp_hybrid_server.py, "
            "retrieval/indexer.py — AHEAD of anything heavy (langchain, chromadb, "
            "sentence-transformers). If it imported a third-party package of its "
            "own, that import would pull in a transitive dependency before the "
            "kill is applied, and the transitive might read its own telemetry "
            "config at import time. So telemetry_kill.py imports only `os`, `ast`, "
            "`hashlib`, `json`, `pathlib` — nothing that drags a heavy tree.\n\n"
            "The same reasoning is why the real ONNX Runtime API suppression "
            "(onnxruntime.disable_telemetry_events()) does NOT live in this "
            "module — importing onnxruntime here would drag its transitive into "
            "every entry point. That call lives at the optional ONNX load seams in "
            "utils/onnx_telemetry.py, called by retrieval/vector_store.py and "
            "guardrails/integration.py."
        )},
    ],
    "source_refs": ["utils/telemetry_kill.py:apply_telemetry_kill,build_telemetry_safe_env", "utils/onnx_telemetry.py", "utils/ops_runner.py"],
},

# ═══ ERROR HANDLING (+3) ═══════════════════════════════════════════════════
{
    "id": "extra-014-rag-error-code-details",
    "category": "Error Handling",
    "messages": [
        {"role": "system", "content": _SYS},
        {"role": "user", "content": (
            "Describe the RAGError exception hierarchy in utils/errors.py and "
            "how the gateway maps it to HTTP responses."
        )},
        {"role": "assistant", "content": (
            "RAGError is the base, a dataclass-style Exception carrying message, "
            "code (str), and details (dict|None). Every subclass sets a stable "
            "code string the gateway catches and maps to an HTTP response:\n\n"
            "  RAGError          -> RAG_ERROR\n"
            "  EmbeddingServiceError -> EMBEDDING_ERROR\n"
            "  LLMServiceError   -> LLM_SERVICE_ERROR\n"
            "  GrokServiceError  -> GROK_SERVICE_ERROR\n"
            "  ClaudeServiceError -> CLAUDE_SERVICE_ERROR\n"
            "  IndexNotFoundError -> INDEX_NOT_FOUND\n"
            "  CorpusEmptyError  -> CORPUS_EMPTY\n"
            "  PromptInjectionError -> PROMPT_INJECTION_BLOCKED\n"
            "  SoulPersistenceError -> SOUL_PERSISTENCE_INCONSISTENT\n"
            "  ConfigError       -> CONFIG_ERROR\n\n"
            "The OOB layer has its own parallel hierarchies that the gateway "
            "stays oblivious to (I6 isolation): SyncError (and its sub-errors "
            "RcloneNotInstalledError, RcloneVersionError, RcloneTimeoutError, "
            "SyncConfigError, SchedulerError, SyncRuntimeError) for Dropbox/rclone "
            "sync; AgenticError for the GitHub-context / skills layer. The gateway "
            "never imports agentic or sync, so those error types can't surface "
            "through the core request path — they're handled in their own OOB "
            "consoles.\n\n"
            "The code field is the stable contract: the gateway switches on code, "
            "not on exception type, so a new sub-error that reuses an existing "
            "code doesn't need a gateway change. The details dict carries "
            "machine-readable context (e.g. which provider, which chunk index) "
            "for audit without being in the user-facing message."
        )},
    ],
    "source_refs": ["utils/errors.py:RAGError,hierarchy", "gate.py:exception mapping"],
},

{
    "id": "extra-015-soul-persistence-error",
    "category": "Error Handling",
    "messages": [
        {"role": "system", "content": _SYS},
        {"role": "user", "content": (
            "What is SoulPersistenceError and when is it raised — what "
            "inconsistency does it signal?"
        )},
        {"role": "assistant", "content": (
            "SoulPersistenceError (code SOUL_PERSISTENCE_INCONSISTENT) signals that "
            "a soul update failed AND its filesystem compensation was incomplete. "
            "It's raised when apply_evolution cannot guarantee the soul.md file "
            "and the soul_versions DB row agree.\n\n"
            "The normal write ordering (INVARIANTS Rule 4) is: scan for injection "
            "(raise PromptInjectionError before any write) -> atomic file write "
            "(_atomic_write_owner_only: tmp + os.replace) -> DB INSERT of the "
            "version row with the new content's sha256. If the process crashes "
            "between the file write and the DB insert, the file has the new soul "
            "but the DB has no row for it — that's soul DRIFT (detected on next "
            "startup by the SHA-256 mismatch, adopted unscanned as a "
            "DRIFT_RECOVERY row). If the crash happens the other way — DB row "
            "written but file write failed — the DB points at content that never "
            "reached disk.\n\n"
            "SoulPersistenceError is raised when the compensation logic itself "
            "can't restore consistency — e.g. the atomic replace succeeded but "
            "the DB insert raised, and the rollback (delete the new file / "
            "restore the prior) also failed. It tells the caller the soul store "
            "is in a state that needs human attention, not a silent retry. This "
            "is distinct from drift (a detectable, recoverable state) — "
            "SoulPersistenceError means the recovery path itself failed."
        )},
    ],
    "source_refs": ["utils/errors.py:SoulPersistenceError", "utils/personality.py:apply_evolution", "INVARIANTS.md:Rule 4"],
},

{
    "id": "extra-016-rclone-timeout-bypass",
    "category": "Error Handling",
    "messages": [
        {"role": "system", "content": _SYS},
        {"role": "user", "content": (
            "In utils/errors.py, RcloneTimeoutError calls "
            "RAGError.__init__ directly instead of super().__init__. Why the "
            "deliberate bypass?"
        )},
        {"role": "assistant", "content": (
            "It's a workaround for a real inheritance bug. The comment is explicit: "
            "SyncError.__init__ hardcodes code='SYNC_ERROR' and provides no way to "
            "pass a sub-code through. If RcloneTimeoutError called "
            "super().__init__ (SyncError), it would get code='SYNC_ERROR' — losing "
            "the distinction between a timeout, a version-too-old, a "
            "not-installed, a config-invalid, a scheduler-failed, and a "
            "runtime-failed sync error.\n\n"
            "So RcloneTimeoutError bypasses SyncError.__init__ and calls "
            "RAGError.__init__(self, message, code='RCLONE_TIMEOUT', details) "
            "directly. This sets the right code without triggering "
            "SyncError.__init__'s hardcoded overwrite. The same pattern is used by "
            "RcloneNotInstalledError, RcloneVersionError, SyncConfigError, "
            "SchedulerError, and SyncRuntimeError — each sets self.code AFTER "
            "super().__init__ to overwrite the hardcoded 'SYNC_ERROR'.\n\n"
            "RcloneTimeoutError can't use that pattern because it needs to set "
            "the code DURING construction, not after — and SyncError.__init__ "
            "would overwrite any code set before super() returns. The direct "
            "RAGError.__init__ call is the only way to get the right code through. "
            "It's ugly but correct; the alternative would be refactoring "
            "SyncError to accept a code parameter, which would touch every sub-error."
        )},
    ],
    "source_refs": ["utils/errors.py:RcloneTimeoutError,SyncError,RAGError"],
},

# ═══ EXTENSION PATTERNS (+1) ═══════════════════════════════════════════════
{
    "id": "extra-017-add-telemetry-dependency",
    "category": "Extension Patterns",
    "messages": [
        {"role": "system", "content": _SYS},
        {"role": "user", "content": (
            "I want to add a new dependency to CyClaw that has its own "
            "analytics/telemetry. What's the safe path?"
        )},
        {"role": "assistant", "content": (
            "Three gates, in order:\n\n"
            "1. Audit the dependency's egress BEFORE merge. Identify every "
            "endpoint it contacts (telemetry, update-check, model-download). "
            "Classify each against SECURITY.md 'Egress classification': is it "
            "intentional policy-gated traffic (allowed, behind its own gate), "
            "or unsolicited secondary telemetry (forbidden)?\n\n"
            "2. If it latches config at import time, add its env var to "
            "utils/telemetry_kill.py TELEMETRY_KILL — BEFORE the heavy import, "
            "same as the four LangSmith names. The block is stdlib-only, so "
            "don't import the dep there; just set the env var. Add a test to "
            "tests/test_telemetry_kill.py asserting the new name against the "
            "expected map (P0 on failure = live telemetry leak).\n\n"
            "3. If it has a runtime API suppression (like onnxruntime's "
            "disable_telemetry_events()), put that call at the optional load seam, "
            "NOT in telemetry_kill.py — importing the dep in the kill module "
            "would drag its transitive into every entry point. Mirror the "
            "utils/onnx_telemetry.py pattern.\n\n"
            "If the dep won't behave with env vars: a network DROP rule for "
            "the cyclaw user (iptables/eBPF), then consider vendoring/forking to "
            "remove the telemetry code. PASS criterion: zero non-localhost "
            "connections in the 4-phase network audit (index build, live query, "
            "idle soak, online mode) — only the policy-gated Grok/Claude "
            "endpoint is expected, and only in hybrid mode."
        )},
    ],
    "source_refs": ["utils/telemetry_kill.py:TELEMETRY_KILL", "SECURITY.md:Egress classification", "tests/test_telemetry_kill.py"],
},

# ═══ DEBUGGING SCENARIOS (+3) ═════════════════════════════════════════════
{
    "id": "extra-018-bad-banned-regex-warn",
    "category": "Debugging Scenarios",
    "messages": [
        {"role": "system", "content": _SYS},
        {"role": "user", "content": (
            "I have a typo in a banned_patterns regex in config.yaml. Will it "
            "crash every /query, and how do I know which pattern is bad?"
        )},
        {"role": "assistant", "content": (
            "It will NOT crash — it degrades with a warning, by design. In "
            "utils/sanitizer.py _load_filter, each banned pattern is compiled "
            "INDIVIDUALLY inside a try/except re.error. A single malformed regex "
            "(an unbalanced paren typo) would otherwise raise on the FIRST /query, "
            "and since check_input's only caller-side handler catches "
            "PromptInjectionError (not re.error), it would escape as an unhandled "
            "500 on EVERY query, benign ones included.\n\n"
            "Instead, the bad entry is SKIPPED with a warning, and the filter "
            "keeps enforcing its remaining patterns. The warning logs the entry "
            "INDEX and the compile error (which carries the fault position), NOT "
            "the pattern text — so the log tells you 'banned_patterns entry #7 "
            "failed to compile (missing ) at position 42)' without dumping the "
            "pattern.\n\n"
            "Find it: the warning is at logger 'cyclaw.sanitizer'. Grep the server "
            "logs for 'failed to compile' or 'non-string type' to find the bad "
            "entry index, then fix that line in config.yaml policy.prompt_filter. "
            "Note: a non-string entry (a YAML number or null) is also skipped "
            "with a warning, not a crash — same warn-on-degrade posture."
        )},
    ],
    "source_refs": ["utils/sanitizer.py:_load_filter,check_input"],
},

{
    "id": "extra-019-no-banned-patterns-noop",
    "category": "Debugging Scenarios",
    "messages": [
        {"role": "system", "content": _SYS},
        {"role": "user", "content": (
            "policy.prompt_filter.enabled is true but banned_patterns is an "
            "empty list. Is injection filtering doing anything?"
        )},
        {"role": "assistant", "content": (
            "No — it has silently degraded to a length-only check, and the code "
            "explicitly warns about it. In _load_filter, after compiling all "
            "patterns, if enabled AND not patterns (enabled=True but zero "
            "patterns compiled), it logs: 'prompt_filter is enabled but no "
            "banned_patterns are configured in {path}; injection filtering is "
            "disabled (length check only).'\n\n"
            "This is the warn-on-degrade posture: the filter refuses to become a "
            "silent no-op. The length check (max_input_chars, default 4000) still "
            "runs — so overly long input is still rejected — but no injection "
            "patterns are matched. Under the threat model this is a "
            "misconfiguration, not a crash.\n\n"
            "Fix: populate policy.prompt_filter.banned_patterns in config.yaml "
            "with the shipped pattern set (or your own). The patterns are "
            "compiled once per config file path and cached via @lru_cache, so "
            "the hot path (every /query and every chunk at index time) does not "
            "recompile regexes on each call. After editing config.yaml, restart "
            "the server — the cache is per-process."
        )},
    ],
    "source_refs": ["utils/sanitizer.py:_load_filter,lru_cache"],
},

{
    "id": "extra-020-ambient-langsmith-shadow",
    "category": "Debugging Scenarios",
    "messages": [
        {"role": "system", "content": _SYS},
        {"role": "user", "content": (
            "I set LANGSMITH_TRACING_V2=false in the CyClaw .env, but the network "
            "audit still shows api.smith.langchain.com traffic. The kill block "
            "sets all four names — what's shadowing it?"
        )},
        {"role": "assistant", "content": (
            "An ambient value at a lower-precedence name that you DIDN'T pin, OR "
            "the kill block ran too late. Per the precedence "
            "(LANGSMITH_TRACING_V2 > LANGCHAIN_TRACING_V2 > LANGSMITH_TRACING > "
            "LANGCHAIN_TRACING), a higher-precedence 'false' shadows a "
            "lower-precedence value — but only if the higher-precedence name is "
            "non-empty. If LANGSMITH_TRACING_V2 is unset (empty) in the ambient "
            "environment, get_env_var skips it and reads the NEXT name. So an "
            "ambient LANGCHAIN_TRACING=true in a shell profile, container base "
            "image, or site-wide observability agent would win — and you only "
            "pinned the LANGSMITH_ names.\n\n"
            "The kill block sets all four to 'false' to prevent exactly this — "
            "so if traffic persists, the block didn't apply. Check:\n"
            "1. Did apply_telemetry_kill() run BEFORE the langchain import? It "
            "must be the first import in gate.py, mcp_hybrid_server.py, and "
            "retrieval/indexer.py. A heavy import that fires first reads the "
            "ambient env and latches it via @functools.lru_cache — after that, "
            "setting the env var is too late.\n"
            "2. Is a new entry point missing the kill call? Every process that "
            "reaches ChromaDB or langchain must apply it. If you added a new CLI "
            "or script that imports langchain without the kill, that process "
            "traces.\n"
            "3. Did a transitive dep start its own telemetry on a new endpoint? "
            "Run the 4-phase network audit to isolate which phase leaks.\n\n"
            "PASS: zero non-localhost connections in phases 1-3 (index, query, "
            "idle). Only the Grok endpoint is expected, and only in phase 4 "
            "(hybrid mode, user-confirmed)."
        )},
    ],
    "source_refs": ["utils/telemetry_kill.py:TELEMETRY_KILL,apply_telemetry_kill", "INVARIANTS.md:telemetry"],
},

# ═══ CODE PATTERNS (+1) ═══════════════════════════════════════════════════
{
    "id": "extra-021-lru-cache-compiled-patterns",
    "category": "Code Patterns",
    "messages": [
        {"role": "system", "content": _SYS},
        {"role": "user", "content": (
            "Show the CyClaw pattern for compiling config-driven regexes once "
            "and caching them. Why @lru_cache on the loader, not on the match "
            "function?"
        )},
        {"role": "assistant", "content": (
            "utils/sanitizer.py _load_filter is decorated with "
            "@lru_cache(maxsize=8), keyed by config_path (a str). It returns "
            "(enabled, max_input_chars, compiled_patterns) — a tuple of a bool, "
            "an int, and a tuple of compiled re.Pattern objects. The cache key is "
            "the config file PATH, not the query.\n\n"
            "Why cache the loader, not the match: check_input(query) runs on "
            "EVERY /query and EVERY chunk at index time. If it recompiled the "
            "banned_patterns regexes on each call, the hot path would pay O(n) "
            "regex compilation per query — and regex compilation is expensive "
            "(re.error handling, AST building). Caching the COMPILED patterns "
            "once per config path means the hot path does O(1) dict lookup + "
            "O(n) pattern MATCH (cheap) per query.\n\n"
            "maxsize=8: the cache holds up to 8 distinct config paths. In "
            "practice there's one (config.yaml), but the cache tolerates test "
            "fixtures and alternate configs without eviction. The cache is "
            "per-process — editing config.yaml requires a server restart, because "
            "the compiled patterns are already in memory.\n\n"
            "This is the same pattern BM25 uses (per-instance lru_cache on the "
            "tokenizer) and the same reasoning: compile-once, match-many. The "
            "trade-off is staleness — a config edit isn't picked up until restart. "
            "For the prompt filter that's acceptable; for the soul it's not, which "
            "is why /soul/reload exists to re-read without a full restart."
        )},
    ],
    "source_refs": ["utils/sanitizer.py:_load_filter,lru_cache", "retrieval/hybrid_search.py:BM25"],
},

# ═══ DESIGN PHILOSOPHY (+1) ═══════════════════════════════════════════════
{
    "id": "extra-022-stdlib-only-kill-before-imports",
    "category": "Design Philosophy",
    "messages": [
        {"role": "system", "content": _SYS},
        {"role": "user", "content": (
            "Why is utils/telemetry_kill.py stdlib-only and imported at the very "
            "top of every entry point, ahead of anything heavy? What's the "
            "philosophy?"
        )},
        {"role": "assistant", "content": (
            "The philosophy: kill switches must be in place BEFORE the libraries "
            "that read them are imported, because those libraries latch their "
            "config at import or construction time. LangChain/LangSmith, "
            "LangGraph, NeMo Guardrails, ChromaDB's PostHog client, ONNX Runtime, "
            "and the OpenTelemetry SDK all read their env vars once — setting "
            "them afterwards is too late. apply_telemetry_kill() mutates "
            "os.environ at the top of the entry point, before the heavy imports "
            "below it.\n\n"
            "Why stdlib-only (just os, ast, hashlib, json, pathlib): the kill "
            "module is imported at the very top of entry points, ahead of "
            "anything heavy. If it imported a third-party package of its own, "
            "that import would pull a transitive dependency before the kill is "
            "applied — and the transitive might read its OWN telemetry config at "
            "import time, defeating the kill. So telemetry_kill.py imports nothing "
            "that drags a heavy tree.\n\n"
            "This is also why the module exists as a separate file at all: the "
            "block used to live only in gate.py. But python -m retrieval.indexer "
            "(cyclaw-index) and mcp_hybrid_server.py never import gate, so none of "
            "them applied it — they relied on upstream defaults staying benign, "
            "which CyClaw doesn't control. An ambient env var in an operator's "
            "shell profile or container base image would be honored. The "
            "canonical module fixes that: every entry point that reaches "
            "ChromaDB or langchain applies the same kill, first.\n\n"
            "The deeper principle: offline-first is a property of the PROCESS, "
            "not a config flag. You can't bolt it on after the libraries are "
            "loaded; you have to establish it before they're born."
        )},
    ],
    "source_refs": ["utils/telemetry_kill.py:module docstring,apply_telemetry_kill", "retrieval/indexer.py:apply_telemetry_kill() call"],
},

]
