"""
Curated CyClaw Q&A dataset for LoRA fine-tuning.

Each entry is a hand-written instruction-response pair that teaches the model
to REASON about CyClaw's architecture, security decisions, and code patterns —
not to memorize file contents.

Categories:
  1. Architecture & Topology — graph flow, invariants, node responsibilities
  2. Security & Defense — injection filters, triple-gate, API key, soul write boundary
  3. Retrieval & RAG — hybrid search, RRF, BM25 caching, embedding fingerprints
  4. Soul Governance — identity layer, crash-safe writes, drift detection, evolution
  5. Telemetry & Offline — kill switches, transitive dep hardening, MPS risk
  6. Error Handling & Resilience — typed exceptions, retry logic, graceful degradation
  7. Extension Patterns — how to add nodes, tools, endpoints without breaking invariants
  8. Debugging Scenarios — diagnosing common failures from symptoms
  9. Code Pattern Q&A — implementing CyClaw-style code following established conventions

Sources: Actual CyClaw source (graph.py, gate.py, llm/client.py, utils/sanitizer.py,
utils/personality.py, retrieval/hybrid_search.py, mcp_hybrid_server.py,
guardrails/rails.py, utils/telemetry_kill.py, utils/errors.py, utils/logger.py)
read directly from github.com/CGFixIT/CyClaw main branch, August 2026.
"""

from __future__ import annotations

# ─── Curated Q&A Pairs ──────────────────────────────────────────────────────

CURATED_QA: list[dict[str, str]] = [

# ═══ 1. ARCHITECTURE & TOPOLOGY ═════════════════════════════════════════════

{
    "instruction": "Describe the CyClaw LangGraph controller flow, including the guardrail nodes.",
    "input": "",
    "output": (
        "CyClaw uses a LangGraph StateGraph where topology IS the security policy.\n\n"
        "Full flow:\n"
        "  ENTRY → retrieve → route_by_score → guardrail_input → {local_llm | user_gate}\n"
        "  user_gate → {pre_action_hook_grok → grok_fallback | pre_action_hook_claude → claude_fallback | guardrail_input → offline_best_effort}\n"
        "  {local_llm | grok_fallback | claude_fallback | offline_best_effort} → guardrail_output\n"
        "  ALL paths → audit_logger → END\n\n"
        "Node responsibilities:\n"
        "1. retrieve: Hybrid search (ChromaDB vector + BM25 keyword + RRF fusion). Unconditional first node.\n"
        "2. route_by_score: Conditional edge. top_score >= min_score (0.028 RRF) → guardrail_input → local_llm. "
        "Otherwise → user_gate.\n"
        "3. guardrail_input: Sync, offline-only input rail (injection markers + soul-mutation regex, no LLM). "
        "Built by utils/guardrail_bridge.py. None default = pass-through.\n"
        "4. local_llm: Builds prompt from soul_core + retrieved docs, calls Ollama at 127.0.0.1:11434.\n"
        "5. user_gate: Sets needs_user_confirm flag. Client resubmits with user_confirmed_online.\n"
        "6. grok_fallback: Triple-gated external (xAI API). Soul preamble INTENTIONALLY omitted — "
        "identity must never leave the box.\n"
        "7. claude_fallback: Alternative external fallback (Anthropic Messages API). Same triple-gate.\n"
        "8. offline_best_effort: Best-effort local LLM when online is declined/unavailable. "
        "Soul preamble IS included here.\n"
        "9. guardrail_output: Sync, offline-only grounding (hallucination) check after response nodes, "
        "before audit. Scoped to local_llm path initially. Single unconditional edge to audit_logger.\n"
        "10. audit_logger: SHA-256 hashed, PII-redacted, append-only JSONL. ALL paths converge here.\n\n"
        "Key invariants enforced by graph edges (not prompts):\n"
        "- Every query passes through retrieval first (no bypass edge from ENTRY)\n"
        "- No LLM is called before the score gate\n"
        "- No external LLM without explicit user confirmation AND hybrid mode\n"
        "- Every response passes through audit logging before END\n"
        "- Soul evolution is NOT a graph node — it's an HTTP endpoint (POST /soul/apply)"
    ),
},

{
    "instruction": "What are the three CyClaw invariants and why are they enforced by graph topology rather than prompts?",
    "input": "",
    "output": (
        "Three invariants:\n"
        "1. RAG-first: retrieve is the unconditional first node from ENTRY. No bypass edge exists.\n"
        "2. Topology = enforcement: the LangGraph topology IS the security policy. "
        "Graph edges enforce safety, not prompts. Injected prompts cannot add graph edges.\n"
        "3. Identity ≠ memory ≠ topology: soul is governed independently from memory and control flow. "
        "soul.md is the source of truth, SQLite is the version log. "
        "Evolution requires explicit human reason via POST /soul/apply.\n\n"
        "Why topology over prompts:\n"
        "Prompt-based enforcement (e.g., 'CRITICAL: always call rag_query first') is probabilistic — "
        "LLM compliance ranges 85-95%. An injected prompt can override, ignore, or rephrase instructions. "
        "Graph topology is deterministic: if the edge from ENTRY to retrieve doesn't exist as a bypass, "
        "no prompt can create it. The StateGraph's add_edge() calls at build time are the enforcement mechanism. "
        "This is the core design insight — model control flow as a directed graph where safety properties "
        "become topology properties."
    ),
},

{
    "instruction": "What is the GraphState TypedDict in CyClaw and what fields does it carry?",
    "input": "",
    "output": (
        "GraphState is a TypedDict(total=False) that flows through every LangGraph node. "
        "Fields:\n\n"
        "Inputs:\n"
        "- query: str — the user's question\n"
        "- user_confirmed_online: bool | None — per-query client confirmation for external LLM\n"
        "- soul_core: str — current soul.md content (injected at prompt construction, not as a graph node)\n\n"
        "Set by retrieve:\n"
        "- retrieved_docs: list[RetrievedDoc] — search results with full RRF provenance\n"
        "- top_score: float — highest RRF fused score\n"
        "- retrieval_mode: str — 'hybrid' | 'vector' | 'bm25' | 'none'\n\n"
        "Set by route_by_score / user_gate:\n"
        "- needs_user_confirm: bool — flag for the client to show confirmation UI\n\n"
        "Set by responding nodes (local_llm / grok_fallback / claude_fallback / offline_best):\n"
        "- answer: str — the generated response\n"
        "- answer_model: str — 'local' | 'grok' | 'claude' | 'offline-best-effort'\n"
        "- answer_sources: list[RetrievedDoc] — docs cited in the answer\n\n"
        "Set by audit_logger:\n"
        "- audit_event: dict — SHA-256 hashed, PII-redacted audit record\n\n"
        "Set by any node on failure:\n"
        "- error: str | None — typed error message\n\n"
        "RetrievedDoc is also a TypedDict(total=False) carrying: text, score, source, chunk_id, "
        "source_sha256, stem_tags, mode, semantic_score, semantic_rank, keyword_score, keyword_rank, "
        "rrf_score, rrf_semantic_contrib, rrf_keyword_contrib."
    ),
},

{
    "instruction": "Why is soul evolution an HTTP endpoint rather than a LangGraph node? What was the model council consensus?",
    "input": "",
    "output": (
        "Soul evolution is NOT a graph node. It's an explicit HTTP endpoint: POST /soul/apply.\n\n"
        "The model council consensus was: no autonomous self-modification in the graph. If soul evolution "
        "were a graph node, a retrieved document or an LLM response could potentially route to it, "
        "creating a path where the agent modifies its own identity based on untrusted input.\n\n"
        "By making it an HTTP endpoint:\n"
        "1. It requires an explicit external HTTP call — no graph edge can reach it\n"
        "2. apply_evolution() requires a human-authored reason string — no anonymous mutations\n"
        "3. The endpoint is behind CYCLAW_API_KEY authentication (fail-closed if unset)\n"
        "4. The proposed soul is scanned with the SAME banned-pattern set as user queries, "
        "unioned with OWASP injection patterns, before any write\n"
        "5. threading.Lock serializes SQLite writes — concurrent evolution attempts are ordered\n\n"
        "Soul content IS injected at the prompt level inside local_llm and offline_best_effort nodes — "
        "but that's read-only injection, not evolution. The soul is prepended as a stable system preamble, "
        "and retrieved docs are explicitly separated with hard delimiters labeled 'untrusted context' "
        "to prevent retrieved content from overriding identity directives."
    ),
},

{
    "instruction": "How does the guardrail_input node work and what is its relationship to the NeMo Guardrails integration?",
    "input": "",
    "output": (
        "guardrail_input is a sync, offline-only input rail positioned between route_by_score and local_llm. "
        "It checks for injection markers and soul-mutation regex patterns — no LLM involved.\n\n"
        "Key design decisions:\n"
        "1. graph.py NEVER imports guardrails — the input_guard is an injected callable built by "
        "utils/guardrail_bridge.py. This preserves module isolation (invariant I6).\n"
        "2. build_graph() accepts an optional input_guard parameter. None (default) is a pure pass-through, "
        "so every existing caller is byte-identical to pre-guardrail behavior.\n"
        "3. The guardrail_router checks the guardrail's verdict: blocked → audit_logger, else → local_llm. "
        "Extended to also route to offline_best_effort as the offline branch's entry point.\n"
        "4. The actual check logic lives in guardrails/rails.py as plain, fully-typed, offline-testable Python — "
        "NOT in Colang flows. This means every check is unit-testable without a running LLM or nemoguardrails.\n\n"
        "Phase 4 added guardrail_output: a sync grounding (hallucination) check after response nodes, "
        "before audit_logger. It has exactly one unconditional outbound edge to audit_logger — "
        "scope/verdict branching happens inside the node and changes what gets logged, never which node runs next. "
        "This preserves invariant I2 by construction."
    ),
},

# ═══ 2. SECURITY & DEFENSE ═══════════════════════════════════════════════════

{
    "instruction": "How does the CyClaw prompt injection filter work? Describe the normalization, pattern matching, and two-level sanitization.",
    "input": "",
    "output": (
        "The sanitizer (utils/sanitizer.py) operates at two levels: user input (reject on match) and "
        "corpus chunks at ingestion time (strip + replace with [FILTERED]).\n\n"
        "Normalization pipeline (before pattern matching):\n"
        "1. NFKC Unicode normalization — folds fullwidth characters back to ASCII. "
        "e.g., 'ｉｇｎｏｒｅ ａｌｌ ｐｒｅｖｉｏｕｓ' collapses onto the plain form patterns already catch.\n"
        "2. Invisible character removal — zero-width space/non-joiner/joiner, LTR/RTL marks, "
        "word joiner, BOM, soft hyphen. These render as nothing but break regex matching when "
        "dropped inside a word: 'ig<ZWSP>nore all previous instructions' matches no pattern, "
        "yet tokenizes back to the instruction it spells.\n\n"
        "Both transforms only fold text TOWARD the ASCII the patterns are written in, so the normalized "
        "copy matches a superset of what the raw string would — this cannot silently stop catching "
        "something that used to be caught.\n\n"
        "Pattern compilation:\n"
        "- Patterns are loaded from config.yaml (policy.prompt_filter.banned_patterns)\n"
        "- 40 curated regex patterns (expanded from original 8→13→32→39→40)\n"
        "- Categories: Core Override, Role Reassignment, System/New Instructions, "
        "Memory/Persistence Manipulation, Authority/Urgency, Tool/Action Hijacking, Light Obfuscation/Jailbreak\n"
        "- All compiled with re.IGNORECASE | re.DOTALL (DOTALL so patterns spanning newlines still match)\n"
        "- Compiled once per config file and cached via @lru_cache(maxsize=8)\n"
        "- A malformed regex in config skips that entry with a warning rather than crashing all queries\n\n"
        "Max input length: 4000 chars (configurable via max_input_chars)"
    ),
},

{
    "instruction": "Explain the triple-gate pattern for external LLM fallback in CyClaw. What are the three gates, and where in the code does each one actually live?",
    "input": "",
    "output": (
        "Three gates must ALL be true simultaneously for external LLM access, and they live in two "
        "different places — not inside GrokClient/ClaudeClient:\n"
        "1. app.mode == 'hybrid' — checked in gate.py, at module load, before GrokClient/ClaudeClient "
        "are even constructed.\n"
        "2. models.grok.enabled == true (or models.claude.enabled) — checked in the SAME gate.py "
        "construction guard as gate 1. If either condition is false, the client object is never "
        "built at all: the module-level `grok`/`claude` name stays None.\n"
        "3. user_confirmed_online == true — a per-query, client-supplied boolean, checked by "
        "graph.py's user_gate_router, which also re-checks provider selection and availability "
        "(is_available(), i.e. an API key is present) before routing to pre_action_hook_grok/claude "
        "and then grok_fallback/claude_fallback.\n\n"
        "Graph topology enforces gate 3: route_by_score routes to user_gate (never directly to "
        "grok_fallback/claude_fallback), and user_gate_router only proceeds past the pre_action_hook "
        "node when user_confirmed_online is true. No graph edge bypasses this — it's structural, "
        "not a prompt instruction.\n\n"
        "GrokClient and ClaudeClient do NOT re-validate any of the three gates. Read their generate() "
        "methods: the only check either one performs is 'do I have an API key' (self.api_key), and "
        "only to raise GrokServiceError/ClaudeServiceError if it's missing — mode, enabled, and "
        "confirmation are never referenced inside either class. This is deliberate, not an oversight: "
        "CyClaw's own principle is topology-as-policy, not prompt- or object-level trust, so the "
        "enforcement lives exactly once, in gate.py's construction guard and graph.py's router. The "
        "practical consequence is important to know, not just reassuring to forget: there is no "
        "client-side backstop. If a future change ever altered gate.py's construction guard or "
        "graph.py's user_gate_router to skip a check, nothing inside GrokClient/ClaudeClient would "
        "catch it — which is exactly why those specific lines get extra scrutiny in review, not why "
        "they're safe to touch casually.\n\n"
        "Additional safety: soul_core is INTENTIONALLY omitted from the Grok/Claude prompt. "
        "The soul/identity layer must never be forwarded off-box (invariant I3 + privacy). "
        "When context forwarding is enabled, it uses data-trust framing (labeled 'untrusted context')."
    ),
},

{
    "instruction": "How does the CyClaw API key authentication work for soul mutation endpoints? What is the fail-closed design?",
    "input": "",
    "output": (
        "The require_api_key dependency guards soul mutation endpoints (/soul/apply, /soul/propose, etc.) "
        "and ops/memory routes.\n\n"
        "Fail-closed design:\n"
        "1. If CYCLAW_API_KEY is not set, the endpoint is REFUSED (401) — not open. "
        "No key is generated, logged, or stored. Previously, unset key meant 'open mode' with no auth.\n"
        "2. security.api_key_optional (default false) is the one escape hatch: an operator who explicitly "
        "opts in gets the dependency skipped entirely. BUT this bypass additionally requires a LOOPBACK PEER — "
        "the request must come from 127.0.0.1/localhost.\n"
        "3. The peer address check is load-bearing: a Host header is attacker-controlled, a peer address is not. "
        "TrustedHostMiddleware alone is insufficient.\n\n"
        "Constant-time comparison:\n"
        "- Uses hmac.compare_digest(credentials.encode('utf-8'), api_key.encode('utf-8'))\n"
        "- Plain != short-circuits on the first differing byte, leaking key length/prefix via response timing\n"
        "- Compares UTF-8 bytes, not str: hmac.compare_digest raises TypeError on str with non-ASCII chars, "
        "and Starlette decodes the Authorization header latin-1, so a token with any byte > 0x7F "
        "would escape as an unhandled 500 instead of the fail-closed 401"
    ),
},

{
    "instruction": "What patterns does the soul-write boundary enforce and why?",
    "input": "",
    "output": (
        "PersonalityManager.apply_evolution() scans proposed soul text with ENFORCED_SOUL_PATTERNS "
        "before any write. These are core injection patterns:\n"
        "- ignore previous/all/prior instructions\n"
        "- disregard previous/all/prior\n"
        "- forget previous/all/prior instructions\n"
        "- new instructions:\n"
        "- system prompt:\n"
        "- override instructions\n"
        "- jailbreak\n"
        "- DAN mode\n"
        "- developer mode\n\n"
        "Why this matters: soul.md is prepended to EVERY LLM system prompt. Anything that reaches it "
        "persists as a standing instruction to the LLM across all future queries. This is the most "
        "dangerous injection surface in the system — a successful soul poisoning is permanent.\n\n"
        "Additionally, propose_evolution uses OWASP_INJECTION_PATTERNS for advisory review — "
        "the core set plus softer patterns (you are now, pretend you are, act as, <script>) "
        "that are suspicious in arbitrary text but may be legitimate in author-controlled identity statements.\n\n"
        "These are surfaced for human review but are NOT enforced at the write boundary — "
        "only the core ENFORCED_SOUL_PATTERNS block the write."
    ),
},

{
    "instruction": "How does the guardrails soul-mutation detection work?",
    "input": "",
    "output": (
        "guardrails/rails.py contains detect_soul_mutation_intent() which checks whether a query "
        "tries to modify or override the soul/identity layer.\n\n"
        "The _SOUL_MUTATION_RE regex matches:\n"
        "- (re)?write your soul/personality/identity/system prompt\n"
        "- change your soul/personality/identity/persona/name\n"
        "- update your soul/personality/identity\n"
        "- forget who you are / your soul/identity/personality\n"
        "- you are now a/an/my\n"
        "- from now on you are/will be\n"
        "- ignore your soul/identity/personality/persona\n"
        "- overwrite your soul/identity\n\n"
        "This is the enforcement arm of CyClaw's Soul-Governance invariant at the guardrails layer. "
        "Soul mutation must always carry an explicit human reason via the gate.py endpoint; "
        "a query that tries to do it inline is refused outright.\n\n"
        "The module also has _INJECTION_MARKERS for defense-in-depth — these are a lightweight subset "
        "of the authoritative 40-pattern filter in utils/sanitizer.py + config.yaml. "
        "They exist so the guardrails CLI can flag obvious payloads offline without loading the full sanitizer config.\n\n"
        "Critically, guardrails/rails.py is NEVER imported by gate.py, graph.py, or mcp_hybrid_server.py. "
        "The NeMo action decorator is a no-op shim when nemoguardrails is not installed, so importing "
        "the module always succeeds offline."
    ),
},

# ═══ 3. RETRIEVAL & RAG ═════════════════════════════════════════════════════

{
    "instruction": "How does CyClaw's BM25 score caching work and why is it per-instance rather than class-level?",
    "input": "",
    "output": (
        "HybridRetriever caches BM25 scores using lru_cache(maxsize=256) wrapped around "
        "self.bm25.get_scores. This avoids re-running get_scores() — an O(corpus size) computation "
        "over the full BM25 term/document matrix — on repeated identical queries.\n\n"
        "Critical design detail: the cache is built as an lru_cache-wrapped closure stored as an "
        "INSTANCE attribute (self._bm25_scores), NOT a bare @lru_cache decorating the method.\n\n"
        "Why per-instance:\n"
        "A class-level @lru_cache would be one cache shared by the whole class, pinning every "
        "HybridRetriever instance ever passed to it alive for the life of the process — a real memory "
        "leak across the many short-lived instances that tests construct. The per-instance cache dies "
        "with the instance.\n\n"
        "What it caches:\n"
        "Only the raw, never-mutated scores array returned by BM25Okapi.get_scores() — NOT the "
        "SearchResult objects that keyword_search() builds from it. Downstream RRF fusion mutates "
        "those objects in place (hit.score / hit.rrf_score in _normalize_single_path and hybrid_search), "
        "so returning shared instances across calls would leak one query's fusion state into the next "
        "identical query."
    ),
},

{
    "instruction": "What is the embedding fingerprint check in HybridRetriever and why does it behave differently on Apple Silicon?",
    "input": "",
    "output": (
        "_check_embedding_fingerprint() guards against serving a semantic index built on a different "
        "embedding device/model/dimension than the one currently configured.\n\n"
        "Three cases:\n"
        "1. MISMATCHED fingerprint (present but different): Always fatal. The index was built with a "
        "different embedding space — comparing vectors from different spaces is meaningless. "
        "Raises IndexNotFoundError (gate boot handles as 503 INDEX_NOT_FOUND).\n\n"
        "2. ABSENT fingerprint (index built before this check existed): Only fatal when MPS is available "
        "on the current machine. CyClaw's Linux/Windows torch pin (torch==X+cpu) has never had MPS/CUDA "
        "kernels compiled in, so an absent fingerprint there provably means the old index was CPU-built. "
        "On Apple Silicon (which has no separate CPU torch build to pin), the old index could have "
        "auto-selected MPS — different embedding space, different results. Warn-and-continue on non-MPS.\n\n"
        "3. CHECK FAILURE (bad fingerprint_fn() call, torch import error): Degrades to warning. "
        "The check's own plumbing must never block retrieval; only a positive finding of staleness does.\n\n"
        "_mps_risk_present() does a deferred torch import (matching embeddings.py's pattern) to avoid "
        "pulling torch into every module that imports hybrid_search. Any failure resolves to False "
        "— the safer direction is to warn rather than refuse."
    ),
},

{
    "instruction": "Describe the RRF (Reciprocal Rank Fusion) implementation in CyClaw. What are the weights, k value, and how does graceful degradation work?",
    "input": "",
    "output": (
        "RRF fusion combines semantic (ChromaDB) and keyword (BM25) search results:\n\n"
        "score = Σ 1/(k + rank_i) * weight_i\n\n"
        "Parameters:\n"
        "- Semantic weight: 0.6 (cosine similarity via ChromaDB, all-MiniLM-L6-v2 384-dim CPU embeddings)\n"
        "- Keyword weight: 0.4 (BM25Okapi with Porter stemmer, ASCII-only tokenizer)\n"
        "- rrf_k: 60 (smoothing constant)\n"
        "- top_k_semantic: 5, top_k_keyword: 5 (max results per leg)\n"
        "- min_score: 0.028 (RRF fused-rank threshold — NOT cosine similarity, different scale)\n"
        "- max_context_tokens: 2400 (token budget for retrieved context in the prompt)\n\n"
        "Each SearchResult carries full provenance: semantic_score, semantic_rank, keyword_score, "
        "keyword_rank, rrf_score, rrf_semantic_contrib, rrf_keyword_contrib.\n\n"
        "Graceful degradation:\n"
        "- If semantic (vector) search fails → keyword-only mode. BM25 results are rebased to a "
        "0..1 scale and fused with the semantic weight applied to a synthetic rank.\n"
        "- If keyword (BM25) search fails → semantic-only mode.\n"
        "- The retrieval_mode field in GraphState records which mode was actually used.\n\n"
        "Why both: BM25 nails exact technical terms (CVE IDs, function names, product SKUs) where "
        "semantic struggles. Semantic captures meaning where exact match fails. RRF gives both worlds "
        "without requiring score calibration between the two systems."
    ),
},

{
    "instruction": "How does the CyClaw indexer handle chunking, and what validation does it perform on config values?",
    "input": "",
    "output": (
        "The indexer (retrieval/indexer.py) chunks documents by word count, not character count:\n"
        "- chunk_size: 512 words per chunk (sentence-snapped via split(' '))\n"
        "- chunk_overlap: 50 words\n"
        "- step = max(1, chunk_size - overlap) — always >= 1\n\n"
        "Validation (fail-fast at build time):\n"
        "1. chunk_size < 1 → ValueError (every window would be empty, collection.add() ingests blanks)\n"
        "2. overlap < 0 → ValueError (negative overlap makes step > chunk_size, silently drops content)\n"
        "3. overlap >= chunk_size → ValueError (stride would be 0 or negative, infinite loop / one-word stride)\n"
        "4. batch_size < 1 → ValueError (negative batch_size yields empty range, Chroma leg never written, "
        "every query silently falls back to BM25-only whose rebased scores top out below min_score)\n\n"
        "Corpus loading:\n"
        "- rglob('*') over corpus directory, filtering by configured extensions\n"
        "- Symlink escape check: rejects files that resolve outside the corpus directory\n"
        "- Extension matching is case-insensitive (.MD matches .md)\n"
        "- UnicodeDecodeError/OSError on a file → skip with warning, don't crash the whole build\n\n"
        "BM25 index format (JSON, not pickle):\n"
        "{\"tokenized_corpus\": [[tokens]], \"chunks\": [text], \"metadata\": [{source, chunk_id, source_sha256, stem_tags}]}\n"
        "Load-time validation: tokenized/chunks/metadata lengths must be equal and non-zero."
    ),
},

# ═══ 4. SOUL GOVERNANCE ═════════════════════════════════════════════════════

{
    "instruction": "Describe the crash-safe write ordering for soul evolution. What happens at each step and why is the order important?",
    "input": "",
    "output": (
        "PersonalityManager.apply_evolution() uses a strict 4-step write order so any crash leaves "
        "the system recoverable:\n\n"
        "1. BACKUP: soul.md → soul.md.bak (original preserved if subsequent steps fail)\n"
        "2. INSERT: new version row into SQLite soul_versions table (DB has record; file unchanged yet)\n"
        "3. WRITE: updated soul.md to disk via _atomic_write_owner_only() (file + DB consistent)\n"
        "4. UPDATE: in-memory soul_core (runtime matches persisted state)\n\n"
        "Why this order matters:\n"
        "- Crash after step 1: soul.md.bak exists, soul.md unchanged, DB unchanged. No inconsistency.\n"
        "- Crash after step 2: DB has a version row pointing to content that's not in soul.md yet. "
        "Startup drift detection catches this (SHA-256 mismatch) and inserts a recovery version.\n"
        "- Crash after step 3: File and DB are consistent. In-memory may be stale but startup reloads it.\n"
        "- Crash after step 4: Everything is consistent.\n\n"
        "_atomic_write_owner_only() uses tempfile.mkstemp + os.replace (atomic on POSIX) with chmod 0600 "
        "so the temp file is owner-only. The file handle is closed before os.replace, and the temp file "
        "is cleaned up in a finally block if the write fails.\n\n"
        "threading.Lock serializes all SQLite writes — concurrent evolution attempts are ordered, "
        "preventing race conditions in the version log."
    ),
},

{
    "instruction": "How does CyClaw's startup drift detection for soul.md work?",
    "input": "",
    "output": (
        "On startup, PersonalityManager computes SHA-256 of soul.md and compares it against the latest "
        "hash in the soul_versions SQLite table.\n\n"
        "Match: system is consistent, proceed normally.\n"
        "Mismatch (manual edit, tampering, crash corruption): insert a recovery version row into "
        "soul_versions and log a forensic event. The audit trail always reflects the true on-disk state — "
        "it never silently 'fixes' soul.md to match the DB.\n\n"
        "The mismatch could mean:\n"
        "1. Someone manually edited soul.md outside the /soul/apply flow\n"
        "2. A crash occurred between the INSERT step and the WRITE step of a previous evolution\n"
        "3. Deliberate tampering attempt\n\n"
        "In all cases, the system records what it found and continues with the actual on-disk content. "
        "This is why the write order is backup → INSERT → write → update: the DB record without the "
        "file write is the most likely crash state, and drift detection makes it observable."
    ),
},

{
    "instruction": "What is the soul injection pattern in local_llm_node? How is untrusted context separated from identity?",
    "input": "",
    "output": (
        "Soul injection happens at the prompt construction level inside local_llm_node and "
        "offline_best_effort_node — NOT as a graph node.\n\n"
        "Prompt structure:\n"
        "1. soul_core is prepended as a STABLE PREAMBLE (system-level)\n"
        "2. Retrieved docs are EXPLICITLY SEPARATED with hard delimiters (\\n\\n---\\n\\n) and labeled "
        "'untrusted context'\n"
        "3. The user query follows last\n\n"
        "Structural separation prevents retrieved content from overriding identity directives. "
        "Per OWASP LLM01: RAG does NOT remove prompt injection risk — it must be combined with "
        "structural separation.\n\n"
        "Key distinction between response paths:\n"
        "- local_llm_node and offline_best_effort_node: soul preamble IS included (local model, identity stays on-box)\n"
        "- grok_fallback_node and claude_fallback_node: soul preamble is INTENTIONALLY OMITTED — "
        "Grok/Claude are external models and the soul/identity layer must never be forwarded off-box "
        "(invariant 3 + privacy). When context forwarding is enabled for Grok, it uses the same "
        "data-trust framing (labeled 'untrusted context').\n\n"
        "The breakline + prompt-prepend formatting (consistent \\n\\n---\\n\\n separators, 'USER QUERY:' label) "
        "was replicated across all response paths for consistency."
    ),
},

# ═══ 5. TELEMETRY & OFFLINE ═════════════════════════════════════════════════

{
    "instruction": "Why does CyClaw have a separate utils/telemetry_kill.py module instead of just setting env vars in gate.py?",
    "input": "",
    "output": (
        "The telemetry kill block originally lived only in gate.py. But every process that reaches "
        "ChromaDB — python -m retrieval.indexer (cyclaw-index) and mcp_hybrid_server.py — never imports gate, "
        "so none of them applied it. They were relying entirely on upstream defaults staying benign.\n\n"
        "utils/telemetry_kill.py exists because:\n"
        "1. Any of these env var names present in the ambient environment (operator's shell profile, "
        "container base image, site-wide observability agent) would be honored by the libraries.\n"
        "2. Libraries latch their telemetry config at IMPORT or CONSTRUCTION time — setting vars afterwards is too late.\n"
        "3. Every entry point must apply the kill BEFORE any heavy import (langchain, chromadb, etc.)\n\n"
        "The module is deliberately stdlib-only (just os). It's imported at the very top of entry points, "
        "ahead of anything heavy, so it must never pull in a third-party package of its own.\n\n"
        "NOT included on purpose: HF_HUB_OFFLINE / TRANSFORMERS_OFFLINE. These would turn "
        "retrieval/embeddings.py's documented cache-miss bootstrap fetch into a guaranteed failure on "
        "any machine that has never run CyClaw before. huggingface_hub freezes HF_HUB_OFFLINE at its own "
        "import time — no retry past that once set. Instead, these are applied conditionally by "
        "retrieval/embeddings.py only once the embedding model is confirmed already on disk.\n\n"
        "HF_HUB_DISABLE_TELEMETRY and DO_NOT_TRACK ARE included unconditionally — they suppress only "
        "a background HEAD telemetry ping, not file downloads or cache lookups."
    ),
},

{
    "instruction": "Explain the four-name LangSmith tracing precedence and why all four must be pinned.",
    "input": "",
    "output": (
        "LangSmith tracing is controlled by four environment variables that are ONE switch with "
        "a namespace precedence order, not four independent mechanisms:\n\n"
        "Precedence (highest to lowest):\n"
        "  LANGSMITH_TRACING_V2 > LANGCHAIN_TRACING_V2 > LANGSMITH_TRACING > LANGCHAIN_TRACING\n\n"
        "The value must be exactly 'true' to enable, and a non-empty 'false' at a higher-precedence "
        "name shadows everything after it. A non-empty value at any single unpinned name would win "
        "over every pinned lower-precedence one.\n\n"
        "All four must be pinned because: if an ambient environment (shell profile, container image, "
        "observability agent) sets LANGSMITH_TRACING_V2=true and CyClaw only pins LANGCHAIN_TRACING_V2=false, "
        "the ambient value wins. Tracing is silently enabled and graph execution traces are sent to "
        "api.smith.langchain.com.\n\n"
        "Verified August 2026 against langsmith 0.10.15 (which langchain-core 1.5.0's "
        "_tracing_v2_is_enabled fully delegates to): tracing_is_enabled() calls "
        "get_env_var('TRACING_V2', default=get_env_var('TRACING')) at utils.py:141, and get_env_var "
        "tries the LANGSMITH_ prefix before LANGCHAIN_ and skips only EMPTY values.\n\n"
        "TELEMETRY_KILL dict pins all four to 'false'. tests/test_telemetry_kill.py asserts each one "
        "and treats a failure as P0 (live telemetry leakage)."
    ),
},

# ═══ 6. ERROR HANDLING & RESILIENCE ═════════════════════════════════════════

{
    "instruction": "Describe the CyClaw typed exception hierarchy. What is the base class and what are the key sub-errors?",
    "input": "",
    "output": (
        "RAGError is the base exception. All CyClaw errors carry message, code (str), and details (dict).\n\n"
        "Core retrieval/gateway errors:\n"
        "- EmbeddingServiceError (EMBEDDING_ERROR)\n"
        "- LLMServiceError (LLM_SERVICE_ERROR)\n"
        "- GrokServiceError (GROK_SERVICE_ERROR)\n"
        "- ClaudeServiceError (CLAUDE_SERVICE_ERROR)\n"
        "- IndexNotFoundError (INDEX_NOT_FOUND)\n"
        "- CorpusEmptyError (CORPUS_EMPTY)\n"
        "- PromptInjectionError (PROMPT_INJECTION_BLOCKED)\n"
        "- SoulPersistenceError (SOUL_PERSISTENCE_INCONSISTENT)\n"
        "- ConfigError (CONFIG_ERROR)\n\n"
        "Out-of-band feature hierarchies (never imported by gate.py/graph.py/mcp_hybrid_server.py):\n"
        "- SyncError → RcloneNotInstalledError, RcloneVersionError, RcloneTimeoutError, "
        "SyncConfigError, SchedulerError, SyncRuntimeError\n"
        "- AgenticError → GhNotInstalledError, GhVersionError, AgenticConfigError, "
        "AgenticWriteRefused, SkillRegistryError\n"
        "- FsConnectError → FsConnectConfigError, FsPathError → FsMacOSPermissionError, "
        "FsWriteRefused, FsConnectRuntimeError\n"
        "- SqlConnectError → SqlConnectConfigError, SqlDriverNotInstalledError, SqlConnectRuntimeError\n"
        "- TelegramError → TelegramConfigError, TelegramRefused, TelegramRuntimeError\n"
        "- AuthError → AuthConfigError, AuthLoginFailed, AuthAccountLocked, AuthUserExists, "
        "AuthUserNotFound, AuthPermissionDenied, AuthLastAdmin, AuthTokenLabelExists\n\n"
        "Design pattern: each out-of-band feature gets its own hierarchy mirroring SyncError's convention — "
        "a dedicated base so the gateway can stay oblivious to features it never imports."
    ),
},

{
    "instruction": "How does the LLM client handle retries, timeouts, and malformed responses?",
    "input": "",
    "output": (
        "llm/client.py implements bounded exponential backoff retry with careful classification:\n\n"
        "Retryable: 5xx server errors and 429 (rate limit). These are transient.\n"
        "Non-retryable: other 4xx (client errors) and unexpected exceptions. Retrying a 400/401 "
        "wastes time and, for Grok, external credits.\n"
        "Retry is config-driven via a 'retry' block under each model; max_retries defaults to 0 "
        "(preserving original single-attempt behavior).\n\n"
        "Timeout design:\n"
        "- _client_timeout() gives connect its own short ceiling (10s), capped at overall_timeout_sec.\n"
        "- Without this, httpx applies one number to connect/read/write/pool alike, so a stalled "
        "connect attempt burns the ENTIRE overall timeout before the caller sees an error.\n"
        "- Mirrors telegram/client.py's identical httpx.Timeout(N, connect=10.0) pattern.\n\n"
        "Response extraction (_extract_content):\n"
        "- Pulls choices[0].message.content from OpenAI-compatible /chat/completions response\n"
        "- A 2xx body that isn't valid JSON or lacks expected shape raises ValueError with a "
        "type-only message (no body fragments that could leak into answers/HTTP responses)\n"
        "- Empty/whitespace content is treated as malformed (non-retryable) — some backends return "
        "content=null alongside a refusal or tool-call\n"
        "- finish_reason=length logs a WARNING (truncated at max_tokens) but still returns the partial text\n\n"
        "Claude uses _extract_claude_content instead — pulls text blocks from Anthropic Messages API. "
        "Empty content names the specific stop_reason (refusal vs tool_use) rather than generic emptiness.\n\n"
        "Optional local failover: models.local_llm.fallback enables a short HTTP probe that prefers "
        "Ollama and falls back to LM Studio if unreachable. Selection is cached per-process; "
        "default is fallback disabled (single-backend installs stay fail-closed)."
    ),
},

{
    "instruction": "How does the audit logger work? Describe the file handle caching and thread safety.",
    "input": "",
    "output": (
        "utils/logger.py implements append-only JSONL audit logging with SHA-256 query hashing and "
        "PII redaction.\n\n"
        "File handle caching:\n"
        "- _AUDIT_HANDLES: dict[str, TextIO] caches one append-mode file handle per resolved audit path\n"
        "- _audit_handle() opens (or returns the cached) handle under _AUDIT_WRITE_LOCK\n"
        "- Previously opened, wrote, and closed on EVERY call — each event paid a fresh open() (path "
        "resolution, inode lookup, possible file creation) plus close(). Under sustained query volume "
        "that syscall overhead dominated the write itself.\n"
        "- Still flush() after every write so readers observe each event immediately.\n"
        "- Handles are closed via atexit.register at module level AND close_audit_handles() for tests.\n\n"
        "Thread safety:\n"
        "- _AUDIT_WRITE_LOCK (threading.Lock) serializes all writes and handle creation\n"
        "- Multiple threads writing audit events are ordered — no interleaved JSONL lines\n\n"
        "Query hashing:\n"
        "- When logging.audit_fields.include_query_hash is true (shipped default), query text is SHA-256 hashed\n"
        "- The audit log cannot become a data exfiltration vector — raw query text is never stored\n"
        "- Setting it false stores raw query text (PII redaction still applies) and is privacy-affecting\n"
        "- This invariant is tested in tests/test_due_diligence_invariants.py\n\n"
        "PII redaction patterns: emails, IPv4, AWS keys (AKIA...), Slack tokens (xoxb-...), API keys (sk-...)\n\n"
        "Path anchoring: _anchor() resolves relative paths against _REPO_ROOT (the module's parent.parent), "
        "so log_file/audit_file values from config.yaml don't depend on process CWD."
    ),
},

# ═══ 7. EXTENSION PATTERNS ═══════════════════════════════════════════════════

{
    "instruction": "How would you add a new tool to CyClaw? What invariants must be preserved?",
    "input": "",
    "output": (
        "Pattern for adding a new capability to CyClaw:\n\n"
        "1. Design as a NEW GRAPH NODE, not an MCP capability. The MCP server must stay retrieval-only "
        "with sampling=null — adding LLM access to it breaks the structural guarantee.\n\n"
        "2. Required properties:\n"
        "   - Behind a config flag (tools.<name>.enabled)\n"
        "   - Routed AFTER retrieval (never bypass the retrieve node)\n"
        "   - Requires user confirmation if it touches external systems (same triple-gate as Grok)\n"
        "   - Flows through guardrail_output and audit_logger before END (no bypass)\n\n"
        "3. Implementation steps:\n"
        "   - Add the node function in graph.py following the _GeneratingClient protocol pattern\n"
        "   - Add the conditional edge in build_graph() — the edge IS the policy\n"
        "   - Add tools.<name>.* section to config.yaml\n"
        "   - Add the client class in llm/client.py with retry/timeout/error handling matching "
        "LocalLLMClient/GrokClient patterns\n"
        "   - Add typed error in utils/errors.py (inherits from RAGError, carries code + details)\n"
        "   - Add tests under tests/test_<name>.py with mocked external deps\n\n"
        "4. Verify all 5 invariants hold:\n"
        "   - Does the new node bypass retrieve? NO — must be after ENTRY → retrieve\n"
        "   - Can it bypass audit? NO — must route through audit_logger before END\n"
        "   - Can it self-modify soul? NO — soul evolution is HTTP-only, not a graph node\n"
        "   - Does it need triple-gate for external access? YES if it calls any external API\n"
        "   - Does it add telemetry? Audit the dependency before merging — see telemetry kill switch docs"
    ),
},

{
    "instruction": "How would you add a new API endpoint to gate.py? What security patterns must be followed?",
    "input": "",
    "output": (
        "Pattern for adding a new endpoint to the CyClaw FastAPI gateway:\n\n"
        "1. Register the route in gate.py following existing patterns (see gate_ops.py, gate_auth.py, "
        "gate_memory.py for examples of how routes are organized into sub-modules).\n\n"
        "2. Security requirements:\n"
        "   - If the endpoint performs mutations (write, delete, modify), require CYCLAW_API_KEY via "
        "the require_api_key dependency. This is fail-closed: no key set = 401, not open.\n"
        "   - If the endpoint touches external systems, apply the same triple-gate as Grok fallback.\n"
        "   - All endpoints bind to loopback only (127.0.0.1:8787 by default).\n"
        "   - CORS is restricted to allowed_origins (default: http://127.0.0.1, http://localhost).\n"
        "   - Methods limited to GET/POST. Headers restricted to Content-Type. Credentials disallowed.\n"
        "   - Rate limiting applies (60 req/min default, configurable via security.rate_limit).\n\n"
        "3. Input validation:\n"
        "   - Run check_input() from utils/sanitizer.py on all user-supplied text (before any LLM call)\n"
        "   - Max input size: 4000 chars (gateway-enforced via sanitizer config)\n"
        "   - Use Pydantic models (schemas/api.py) for request/response validation\n\n"
        "4. Audit:\n"
        "   - Every endpoint that invokes the graph flows through audit_logger\n"
        "   - For non-graph endpoints, call audit_log() directly for forensic visibility\n\n"
        "5. Error handling:\n"
        "   - Catch typed RAGError subtypes and map to proper HTTP responses\n"
        "   - Use the QueryResponse uniform JSON schema (answer, sources, model_used, "
        "retrieval_mode, needs_confirm, error)\n\n"
        "6. Path anchoring: use _BASE_DIR (Path(__file__).resolve().parent) for file resolution, "
        "not CWD — prevents Windows double-click launch failures."
    ),
},

{
    "instruction": "How would you add a new retrieval backend (e.g., pgvector) to CyClaw?",
    "input": "",
    "output": (
        "CyClaw already has a pluggable vector backend system (retrieval/vector_store.py). "
        "The backend is selected via indexing.vector_backend in config.yaml.\n\n"
        "Existing backends:\n"
        "- ChromaDB (default, embedded, offline-first)\n"
        "- pgvector (when indexing.vector_backend=pgvector)\n\n"
        "Both implement the same writer/reader interface:\n"
        "- Writer: reset(fingerprint), add(ids, chunks, embeddings, metadata), finalize(), close()\n"
        "- Reader: search(query_embedding, top_k) → list[SearchResult], fingerprint() → str | None\n\n"
        "The reader's fingerprint() method is checked by _check_embedding_fingerprint() at startup. "
        "A None fingerprint (not implemented) is handled gracefully — only a MISMATCHED fingerprint is fatal.\n\n"
        "To add a new backend:\n"
        "1. Implement the writer and reader interfaces in retrieval/vector_store.py\n"
        "2. Register it in the get_vector_writer() and get_vector_reader() factory functions\n"
        "3. Add the backend name to config.yaml's indexing.vector_backend options\n"
        "4. Ensure cosine space / `1 - distance` scoring so RRF order and min_score gate are unaffected\n"
        "5. BM25 stays file-based regardless of the vector backend — it's JSON, not in the vector store\n\n"
        "The per-chunk metadata (source, chunk_id, source_sha256, stem_tags) is identical across backends, "
        "so SearchResult provenance is preserved. Only where the vectors live changes."
    ),
},

# ═══ 8. DEBUGGING SCENARIOS ═════════════════════════════════════════════════

{
    "instruction": "A CyClaw query returns 'needs_confirm: true' every time, even for simple questions. What could be wrong?",
    "input": "",
    "output": (
        "This means route_by_score is sending every query to user_gate instead of local_llm. "
        "The score gate threshold (min_score = 0.028 RRF) is not being met.\n\n"
        "Diagnostic steps:\n"
        "1. Check if the retrieval index exists:\n"
        "   curl -s http://127.0.0.1:8787/health\n"
        "   Look for INDEX_NOT_FOUND — if the BM25 index is missing, retrieval returns zero results.\n\n"
        "2. If index is missing, rebuild:\n"
        "   python -m retrieval.indexer\n"
        "   Verify data/corpus/ has documents with the configured extensions.\n\n"
        "3. Check the BM25 index integrity:\n"
        "   The JSON file at indexing.bm25_path must have tokenized_corpus, chunks, and metadata "
        "with equal non-zero lengths. A corrupt index raises IndexNotFoundError at HybridRetriever init.\n\n"
        "4. Check embedding fingerprint:\n"
        "   If the vector index was built with a different embedding model/dim/device, "
        "_check_embedding_fingerprint() raises IndexNotFoundError. Rebuild the index.\n"
        "   On Apple Silicon: an absent fingerprint is FATAL (MPS risk). On Linux/Windows: warn-and-continue.\n\n"
        "5. Check corpus content:\n"
        "   If the corpus was recently changed (e.g., new files added), the index may be stale.\n"
        "   Non-ASCII content produces zero BM25 tokens (the stemmer is ASCII-only) — keyword search "
        "won't see those chunks. Check build logs for 'produced no BM25 tokens' warnings.\n\n"
        "6. Check config.yaml retrieval.min_score — if it was raised above the typical RRF score range "
        "(~0.028), every query falls below threshold."
    ),
},

{
    "instruction": "CyClaw is showing a 'Soul drift forensic event on startup' message. What does this mean and how do you investigate?",
    "input": "",
    "output": (
        "This means PersonalityManager's startup integrity-hash check detected a mismatch between soul.md "
        "and the latest content digest in the soul_versions SQLite table.\n\n"
        "Possible causes:\n"
        "1. Someone manually edited soul.md outside the /soul/apply flow (e.g., vim data/personality/soul.md)\n"
        "2. A crash occurred between step 2 (INSERT into SQLite) and step 3 (write soul.md) of a "
        "previous evolution — the DB has a version row pointing to content that never made it to the file\n"
        "3. Deliberate tampering attempt\n\n"
        "Investigation:\n"
        "1. Check the audit log for recent soul events:\n"
        "   grep 'soul' logs/audit.jsonl | tail -20\n\n"
        "2. Check the SQLite version log (content digest / integrity hash of on-disk soul.md, plus the human reason):\n"
        "   sqlite3 data/personality/cyclaw_soul.db 'SELECT version, content_digest, reason FROM soul_versions ORDER BY version DESC LIMIT 5;'\n\n"
        "3. Compare soul.md with soul.md.bak (the backup from the last successful evolution):\n"
        "   diff data/personality/soul.md data/personality/soul.md.bak\n\n"
        "4. If the drift is from a manual edit that you WANT to keep:\n"
        "   POST /soul/reload to re-read soul.md and insert a recovery version row\n"
        "   The system records what it found and continues with the actual on-disk content.\n\n"
        "5. If the drift is unexpected/tampering: investigate who has filesystem access to "
        "data/personality/soul.md. The file should be owner-only (chmod 0600 via _atomic_write_owner_only).\n\n"
        "The system NEVER silently 'fixes' soul.md to match the DB. It records the true state and continues."
    ),
},

{
    "instruction": "A query to CyClaw returns a blank answer with model_used='local'. What could cause this?",
    "input": "",
    "output": (
        "A blank answer from local_llm means Ollama returned a response but _extract_content() "
        "received empty/whitespace content, OR the response was truncated.\n\n"
        "Diagnostic steps:\n\n"
        "1. Check Ollama is running and the model is loaded:\n"
        "   curl -s http://127.0.0.1:11434/api/tags\n"
        "   ollama run qwen3.8:27b-mlx 'Say hello'  # verify it responds\n\n"
        "2. Check the Ollama timeout:\n"
        "   config.yaml models.local_llm.timeout_sec (default 600s for qwen3.8:27b-mlx)\n"
        "   If the model is slow to generate, a timeout produces an LLMServiceError, not a blank answer.\n\n"
        "3. Check max_tokens vs context window:\n"
        "   Ollama allocates max_tokens up front. If (prompt_tokens + max_tokens) > loaded context length, "
        "   Ollama stalls at '0% processing'.\n"
        "   config.yaml: models.local_llm.max_tokens (RESERVED OUTPUT BUDGET)\n"
        "   graph.py bounds the prompt INPUT to retrieval.max_context_tokens\n"
        "   If soul_core + retrieved docs + query exceed the context budget, the LLM has no room to generate.\n\n"
        "4. Check if content was null/empty:\n"
        "   Some OpenAI-compatible backends return content=null alongside a refusal or tool-call. "
        "   _extract_content raises ValueError('empty LLM response: content missing or blank') in this case.\n"
        "   This would show as an error, not a blank answer — check if error is set in the response.\n\n"
        "5. Check finish_reason:\n"
        "   If finish_reason=length, the response was truncated at max_tokens. The partial text is returned "
        "   but a WARNING is logged. Increase max_tokens or reduce context budget.\n\n"
        "6. Check the audit log:\n"
        "   grep 'local' logs/audit.jsonl | tail -5\n"
        "   The audit event records answer_model and any error."
    ),
},

{
    "instruction": "CyClaw's network audit shows a connection to api.smith.langchain.com in offline mode. What happened and how do you fix it?",
    "input": "",
    "output": (
        "This is a telemetry leak — langsmith is attempting to send graph execution traces despite "
        "CyClaw's offline-first promise.\n\n"
        "Root cause analysis:\n"
        "1. One of the four LangSmith tracing env vars was not pinned. The precedence is:\n"
        "   LANGSMITH_TRACING_V2 > LANGCHAIN_TRACING_V2 > LANGSMITH_TRACING > LANGCHAIN_TRACING\n"
        "   If an ambient env var (shell profile, container image) sets a higher-precedence name to 'true', "
        "   it shadows CyClaw's pinned lower-precedence 'false'.\n\n"
        "2. Check which vars are set in the process environment:\n"
        "   The startup table prints [TELEMETRY KILL] status for each var. Look for 'MISSING' entries.\n\n"
        "3. Check if LANGCHAIN_API_KEY is set:\n"
        "   apply_telemetry_kill() unsets LANGCHAIN_API_KEY — no key means no auth attempt. "
        "   If it's still set in the environment, langsmith may still attempt connections.\n\n"
        "Fix:\n"
        "1. Ensure utils/telemetry_kill.apply_telemetry_kill() runs BEFORE any langchain/chromadb import. "
        "   It must be the first import in every entry point (gate.py, mcp_hybrid_server.py, indexer).\n\n"
        "2. If the leak persists after env vars are confirmed set, check if a new transitive dependency "
        "   has its own telemetry endpoint. Run the 4-phase network audit:\n"
        "   Phase 1: Index build — does sentence-transformers hit huggingface.co?\n"
        "   Phase 2: Live queries — any non-localhost connections?\n"
        "   Phase 3: Idle soak (5-10 min) — periodic heartbeat?\n"
        "   Phase 4: Online mode — only Grok endpoint expected\n\n"
        "3. If a dep won't behave with env vars: iptables DROP rule for the cyclaw user, "
        "then consider vendoring/forking the dependency to remove the telemetry code entirely.\n\n"
        "PASS criterion: zero non-localhost connections in phases 1-3."
    ),
},

# ═══ 9. CODE PATTERN Q&A ════════════════════════════════════════════════════

{
    "instruction": "Show the CyClaw pattern for a LangGraph node function. What does the _GeneratingClient protocol look like?",
    "input": "",
    "output": (
        "CyClaw graph nodes follow this pattern:\n\n"
        "```python\n"
        "from typing import Protocol, TypedDict\n"
        "from langgraph.graph import END, StateGraph\n\n"
        "class _GeneratingClient(Protocol):\n"
        "    \"\"\"Structural type for LocalLLMClient/GrokClient — both expose generate(prompt) -> str.\"\"\"\n"
        "    def generate(self, prompt: str) -> str:\n"
        "        pass  # Protocol stub — never executed, only implementations' bodies run\n"
        "\n"
        "def local_llm_node(state: GraphState, *, llm_client: _GeneratingClient, \n"
        "                   retriever: HybridRetriever, personality: PersonalityManager) -> dict:\n"
        "    \"\"\"Build prompt from soul_core + retrieved docs, call local LLM.\"\"\"\n"
        "    query = state[\"query\"]\n"
        "    soul_core = state.get(\"soul_core\", \"\")\n"
        "    retrieved = state.get(\"retrieved_docs\", [])\n"
        "\n"
        "    # Soul prepended as stable preamble (system-level)\n"
        "    # Retrieved docs explicitly separated with hard delimiters labeled 'untrusted context'\n"
        "    prompt_parts = []\n"
        "    if soul_core:\n"
        "        prompt_parts.append(soul_core)\n"
        "    prompt_parts.append(f\"USER QUERY:\\n{query}\")\n"
        "    if retrieved:\n"
        "        context = \"\\n\\n---\\n\\n\".join(doc[\"text\"] for doc in retrieved[:5])\n"
        "        prompt_parts.append(f\"---\\nuntrusted context:\\n{context}\")\n"
        "\n"
        "    prompt = \"\\n\\n\".join(prompt_parts)\n"
        "    answer = llm_client.generate(prompt)\n"
        "\n"
        "    return {\n"
        "        \"answer\": answer,\n"
        "        \"answer_model\": \"local\",\n"
        "        \"answer_sources\": retrieved[:5],\n"
        "    }\n"
        "```\n\n"
        "Key patterns:\n"
        "- Protocol for structural typing (duck typing with type checker support)\n"
        "- `pass` not `...` in protocol stubs (CodeQL's ineffectual-statement check doesn't flag it)\n"
        "- Node returns a dict (partial state update — LangGraph merges it)\n"
        "- Soul prepended, retrieved docs separated and labeled untrusted\n"
        "- GraphState is TypedDict(total=False) so all fields are optional"
    ),
},

{
    "instruction": "Show the CyClaw pattern for an atomic, owner-only file write. Why use tempfile + os.replace?",
    "input": "",
    "output": (
        "From utils/personality.py:\n\n"
        "```python\n"
        "import os, tempfile\n"
        "from pathlib import Path\n\n"
        "def _atomic_write_owner_only(path: Path, content: str) -> None:\n"
        "    \"\"\"Replace path atomically using an owner-only temporary file.\"\"\"\n"
        "    path.parent.mkdir(parents=True, exist_ok=True)\n"
        "    fd, tmp_name = tempfile.mkstemp(\n"
        "        prefix=f\".{path.name}.\",\n"
        "        suffix=\".tmp\",\n"
        "        dir=path.parent,  # same dir so os.replace is atomic (same filesystem)\n"
        "        text=True,\n"
        "    )\n"
        "    tmp_path = Path(tmp_name)\n"
        "    try:\n"
        "        os.chmod(tmp_path, 0o600)  # owner-only before content is written\n"
        "        with os.fdopen(fd, \"w\", encoding=\"utf-8\") as tmp_file:\n"
        "            fd = -1  # fd consumed by fdopen; prevent double-close in finally\n"
        "            tmp_file.write(content)\n"
        "        os.replace(tmp_path, path)  # atomic on POSIX\n"
        "    finally:\n"
        "        if fd >= 0:\n"
        "            os.close(fd)  # only if fdopen failed before consuming it\n"
        "        try:\n"
        "            tmp_path.unlink(missing_ok=True)  # cleanup if replace didn't happen\n"
        "        except OSError:\n"
        "            pass  # best-effort cleanup\n"
        "```\n\n"
        "Why this pattern:\n"
        "1. os.replace is atomic on POSIX — readers never see a partially-written file\n"
        "2. tempfile.mkstemp in the SAME directory as the target ensures same filesystem (required for atomic rename)\n"
        "3. chmod 0o600 before writing content — the temp file is owner-only even if the process is compromised\n"
        "4. fd = -1 after fdopen consumes it — prevents double-close in the finally block\n"
        "5. missing_ok=True on unlink — Python 3.8+ idiom for 'delete if exists, don't crash if not'\n"
        "6. The finally block handles both success (tmp already replaced, unlink is no-op) and failure (tmp cleaned up)"
    ),
},

{
    "instruction": "Show the CyClaw pattern for the MCP server's hybrid_search tool. How does it enforce the retrieval-only constraint?",
    "input": "",
    "output": (
        "From mcp_hybrid_server.py:\n\n"
        "```python\n"
        "CAPABILITIES = {\n"
        "    \"tools\": {},\n"
        "    \"sampling\": None  # CRITICAL: No LLM path at protocol level\n"
        "}\n\n"
        "TOOLS = [{\n"
        "    \"name\": \"hybrid_search\",\n"
        "    \"description\": \"Search local .md corpus using semantic + keyword retrieval with RRF fusion\",\n"
        "    \"inputSchema\": {\n"
        "        \"type\": \"object\",\n"
        "        \"properties\": {\n"
        "            \"query\": {\"type\": \"string\"},\n"
        "            \"top_k\": {\"type\": \"integer\", \"default\": 5, \"minimum\": 1, \"maximum\": 50},\n"
        "            \"mode\": {\"type\": \"string\", \"enum\": [\"hybrid\", \"semantic\", \"keyword\"], \"default\": \"hybrid\"}\n"
        "        },\n"
        "        \"required\": [\"query\"]\n"
        "    }\n"
        "}]\n"
        "```\n\n"
        "The retrieval-only constraint is STRUCTURAL, not policy:\n"
        "1. sampling: None in CAPABILITIES — at the JSON-RPC protocol level, the server declares it cannot invoke any LLM\n"
        "2. No write tools are exposed — only hybrid_search (read-only against existing indices)\n"
        "3. top_k is coerced via _coerce_top_k() — non-integer/negative values fall back to default 5, clamped to [1, 50]\n"
        "4. _MAX_QUERY_CHARS (65536) bounds request size — sanity bound, not a security filter\n"
        "5. The score scale is named in the response via _score_scale() because the three modes emit scores on incompatible scales (raw BM25 unbounded, cosine 0..1, RRF ~1/rrf_k)\n\n"
        "Any LLM processing must go through the gateway's LangGraph controller with full audit coverage. "
        "The MCP server cannot autonomously invoke an LLM — no prompt or config change can enable it."
    ),
},

{
    "instruction": "Show the CyClaw pattern for constant-time API key comparison. Why compare bytes not str?",
    "input": "",
    "output": (
        "From gate.py:\n\n"
        "```python\n"
        "import hmac\n"
        "from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials\n\n"
        "_bearer_scheme = HTTPBearer(auto_error=False)\n\n"
        "def require_api_key(\n"
        "    request: Request,\n"
        "    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),\n"
        "):\n"
        "    if _api_key_bypass_allowed(request):\n"
        "        return\n"
        "    api_key = os.environ.get(\"CYCLAW_API_KEY\", \"\")\n"
        "    if not api_key:\n"
        "        raise HTTPException(status_code=401,\n"
        "                            detail=\"Soul mutation disabled: CYCLAW_API_KEY not set\")\n"
        "    if not credentials or not hmac.compare_digest(\n"
        "        credentials.credentials.encode(\"utf-8\"),\n"
        "        api_key.encode(\"utf-8\")\n"
        "    ):\n"
        "        raise HTTPException(status_code=401, detail=\"Invalid or missing API key\")\n"
        "```\n\n"
        "Why bytes, not str:\n"
        "1. hmac.compare_digest raises TypeError on a str operand containing a non-ASCII character\n"
        "2. Starlette decodes the Authorization header as latin-1\n"
        "3. A token with any byte > 0x7F (curly quote, accented character) would escape as an unhandled 500 "
        "instead of the fail-closed 401 this endpoint promises\n"
        "4. The bytes overload never raises on content and preserves the constant-time property\n\n"
        "Why not plain `!=`:\n"
        "A plain != short-circuits on the first differing byte, leaking key length/prefix via response timing. "
        "compare_digest runs in time independent of how many leading characters match.\n\n"
        "The _api_key_bypass_allowed(request) check requires BOTH:\n"
        "- security.api_key_optional == True (explicit opt-in)\n"
        "- Loopback peer address (not just bind address — a Host header is attacker-controlled, a peer address is not)"
    ),
},

# ═══ 10. DESIGN PHILOSOPHY ══════════════════════════════════════════════════

{
    "instruction": "Why does CyClaw use LangGraph instead of a simpler chain or prompt-based routing? What does the StateGraph give you that a chain doesn't?",
    "input": "",
    "output": (
        "The core insight: safety properties should be topology properties, not behavioral instructions.\n\n"
        "A LangChain chain or prompt-based router relies on the LLM following instructions: 'always retrieve first', "
        "'never call Grok without user confirmation'. LLM compliance is probabilistic (85-95%) and vulnerable to "
        "prompt injection — an injected instruction can override, ignore, or rephrase the routing directive.\n\n"
        "LangGraph StateGraph makes invariants visible as code:\n"
        "1. ENTRY → retrieve is an add_edge() call at build time. No prompt can remove it. "
        "If the edge doesn't exist, the path doesn't exist.\n"
        "2. route_by_score is a conditional edge (add_conditional_edges), not an LLM decision. "
        "The routing function is deterministic Python code that checks top_score >= min_score.\n"
        "3. The user_gate → pre_action_hook_grok → grok_fallback edge only exists when user_confirmed_online is True. "
        "This is a graph condition, not a prompt instruction.\n"
        "4. ALL paths converge at audit_logger before END. There is no add_edge() call that bypasses it.\n\n"
        "What you get that a chain doesn't:\n"
        "- Visible security model: the graph IS the security policy. Reviewers can audit edges, not prompts.\n"
        "- Deterministic enforcement: topology is not probabilistic. No prompt compliance uncertainty.\n"
        "- Injection resistance: injected prompts cannot add graph edges. The graph structure is fixed at build time.\n"
        "- State typedness: GraphState TypedDict gives type checking across nodes. A chain passes opaque dicts.\n"
        "- Conditional routing: add_conditional_edges maps state values to next nodes deterministically.\n\n"
        "Trade-off: less flexibility. Adding a new path requires a code change (new edge), not a prompt edit. "
        "This is the intended friction — safety should require deliberate, reviewable changes."
    ),
},

{
    "instruction": "What is CyClaw's stance on RAG and prompt injection? Why doesn't RAG alone solve the injection problem?",
    "input": "",
    "output": (
        "Per OWASP LLM01: RAG does NOT remove prompt injection risk. It must be combined with structural separation.\n\n"
        "The problem: retrieved documents are untrusted input. A corpus chunk could contain 'ignore previous instructions' "
        "or a role reassignment attack. When this chunk is injected into the LLM prompt alongside the system prompt, "
        "the LLM may follow the injected instruction instead of the system prompt.\n\n"
        "CyClaw's defense-in-depth approach:\n"
        "1. Corpus sanitization at index time: sanitize_chunk() strips banned patterns from corpus chunks "
        "during indexing, replacing them with [FILTERED]. This catches injection patterns in the source documents.\n"
        "2. User input filtering: check_input() rejects queries containing banned patterns before any LLM call.\n"
        "3. Structural separation in the prompt: soul_core is prepended as a stable system preamble. "
        "Retrieved docs are explicitly separated with hard delimiters (\\n\\n---\\n\\n) and labeled 'untrusted context'. "
        "This makes it structurally clear to the model that retrieved content is not an instruction.\n"
        "4. Score gate: low-confidence retrieval (top_score < min_score) routes to user_gate instead of local_llm. "
        "This prevents the model from acting on poorly-matched, potentially injected content.\n"
        "5. Guardrail input rail: guardrail_input node checks for injection markers and soul-mutation regex "
        "before the LLM is called.\n"
        "6. Guardrail output rail: guardrail_output checks for hallucination/grounding issues after generation.\n"
        "7. Audit logging: every query is SHA-256 hashed and PII-redacted, providing forensic visibility.\n\n"
        "None of these alone is sufficient. The combination of structural separation + sanitization + score gating + "
        "guardrails + audit creates defense-in-depth where each layer catches what others miss."
    ),
},

{
    "instruction": "How does CyClaw handle the tension between offline-first and providing useful answers when local retrieval has no relevant results?",
    "input": "",
    "output": (
        "This is the core tension CyClaw was designed to resolve. The answer is the triple-gate fallback pattern.\n\n"
        "Offline-first means:\n"
        "- Default state: no external network access. All retrieval and LLM calls are local.\n"
        "- The system must work on a machine with no internet connection.\n"
        "- Telemetry is killed — no phone-home to posthog, langsmith, huggingface.\n\n"
        "But local retrieval may return low-confidence results (top_score < min_score = 0.028 RRF). "
        "In that case, route_by_score sends the query to user_gate instead of local_llm.\n\n"
        "user_gate sets needs_user_confirm=True in the response. The client (terminal.html or API caller) "
        "shows a confirmation prompt: 'No confident local results. Use online fallback?'\n\n"
        "If the user confirms (user_confirmed_online=True in the resubmitted request) AND app.mode=='hybrid' "
        "AND models.grok.enabled==True, the query routes to grok_fallback (external LLM via xAI API).\n\n"
        "If the user declines OR any gate fails, the query routes to offline_best_effort — the local LLM "
        "still generates a response, but without retrieved context confidence. The answer_model field is "
        "'offline-best-effort' so the consumer knows this is a low-confidence answer.\n\n"
        "Key design decisions:\n"
        "1. The default is NO. External access is opt-in per query, not opt-out.\n"
        "2. The triple-gate is structural (graph topology), not behavioral (prompt instruction).\n"
        "3. soul_core is NOT forwarded to the external LLM — identity stays on-box.\n"
        "4. send_local_context_to_grok defaults to false — even when online, local data doesn't leave.\n"
        "5. All paths (including grok_fallback) flow through audit_logger before END."
    ),
},

]


def get_curated_dataset() -> list[dict[str, str]]:
    """Return the curated Q&A dataset."""
    return CURATED_QA.copy()
