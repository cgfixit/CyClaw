"""Additional curated debugging Q&A for CyClaw LoRA fine-tuning (Deliverable 2).

Extends the original curated_qa.py (4 debugging scenarios) with 12 new debugging
pairs grounded in the ACTUAL CyClaw source read from github.com/CGFixIT/CyClaw
main on 2026-09-07. Each pair targets a "sharp edge" — a place where the
behavior differs from what the name/docstring implies — because those are the
failures that waste real debugging time.

Canonical format (per advisor): structured {id, category, messages, source_refs}
where messages is a system/user/assistant turn list. The build script renders
this to a chat-template `text` column for Unsloth SFTTrainer.

Sources verified this session:
  - graph.py            (10-node LangGraph, GraphState, _GeneratingClient, routers)
  - INVARIANTS.md       (Rules 1-9, sharp edges, decorative signals)
  - retrieval/indexer.py (chunk_document guards, load_corpus symlink rejection)
  - llm/client.py       (retry/timeout, _extract_content, graph deadline contextvar)
"""

from __future__ import annotations

# System prompt baked into every debugging example. Keeps the model in
# "CyClaw architect" frame and forbids the two worst failure modes for a
# debugging assistant: inventing file paths, and weakening an invariant to
# "fix" a symptom.
_DEBUG_SYSTEM = (
    "You are CyClaw's debugging assistant. You diagnose failures by reading the "
    "real source, not by guessing. Distinguish established fact (the code does X) "
    "from reasonable inference (a config probably caused it). Never propose a "
    "fix that weakens an I1-I6 invariant. If a signal is decorative "
    "(require_env, /health embeddings_local, sampling=None), say so explicitly "
    "rather than treating it as enforcement. Cite the file and function."
)

# Each entry: id, category, messages=[{role,content}], source_refs (file:area).
# source_refs is for audit/provenance only — the trainer ignores it.
DEBUG_QA: list[dict] = [

# ── I3 sharp edge: two of three gates live in gate.py, not the router ───────
{
    "id": "debug-005-external-never-fires",
    "category": "Debugging Scenarios",
    "messages": [
        {"role": "system", "content": _DEBUG_SYSTEM},
        {"role": "user", "content": (
            "I set app.mode: hybrid and models.grok.enabled: true, and the user "
            "confirmed online, but grok_fallback never runs — every low-score "
            "query still falls through to offline_best_effort. The router must be "
            "bugged. Where do I look?"
        )},
        {"role": "assistant", "content": (
            "The router is not the bug, and 'topology = policy' does not cover "
            "all three gates. Per INVARIANTS.md Rule 2, the external call is "
            "triple-gated, but the gates are split across two locations:\n\n"
            "1. graph.py `user_gate_router` enforces ONLY: the user confirmed, "
            "the selected `state.online_provider` matches, and that provider's "
            "client is not None and `is_available()`. It deliberately does NOT "
            "read `app.mode` or `models.<provider>.enabled` — there is a "
            "tripwire test (test_graph_gate_does_not_consult_app_mode_by_design) "
            "asserting it never will.\n\n"
            "2. `app.mode == 'hybrid'` and `models.<provider>.enabled` are "
            "enforced EXCLUSIVELY by gate.py's client construction: each of "
            "grok/claude stays None unless BOTH hold. A None client makes the "
            "router fall back to offline_best_effort.\n\n"
            "So if grok_fallback never fires despite hybrid + enabled + confirm, "
            "the client is None at construction time. Check, in order:\n"
            "  - Is the provider's API key actually present? `is_available()` "
            "returns False (not None) when the key is missing, and the router "
            "treats that the same as 'no client'.\n"
            "  - Did someone construct GrokClient/ClaudeClient OUTSIDE its "
            "double-gated `if` in gate.py (a new entry point, a test harness "
            "wired into prod, an 'always build the client' refactor)? That is "
            "the only way to bypass mode/enabled — and it sends confirmed "
            "low-score queries to a paid API in offline mode.\n\n"
            "Do not 'fix' this by adding an app.mode check to the router. That "
            "would violate the deliberate construction/runtime split and delete "
            "the tripwire. The fix is in gate.py's client construction block."
        )},
    ],
    "source_refs": ["INVARIANTS.md:Rule 2", "graph.py:user_gate_router", "gate.py:client construction"],
},

# ── Rule 5 sharp edge: reload/drift adopt soul unscanned ───────────────────
{
    "id": "debug-006-soul-reload-unscanned",
    "category": "Debugging Scenarios",
    "messages": [
        {"role": "system", "content": _DEBUG_SYSTEM},
        {"role": "user", "content": (
            "I edited data/personality/soul.md directly with vim to add a new "
            "persona line, then hit POST /soul/reload. The audit log shows the "
            "new soul is live but there's no injection-scan event. Isn't the "
            "soul supposed to be scanned on every change?"
        )},
        {"role": "assistant", "content": (
            "No — and describing the soul as 'always scanned' is the most common "
            "wrong mental model. Per INVARIANTS.md Rule 5, the injection scan "
            "is WRITE-PATH-ONLY. Only `PersonalityManager.apply_evolution` "
            "(POST /soul/apply) scans, and only with scan=True (the default).\n\n"
            "Two paths change the live soul with NO scan:\n"
            "  - POST /soul/reload — re-reads and adopts soul.md verbatim.\n"
            "  - Startup drift recovery (_load_soul) — if soul.md differs from "
            "the newest soul_versions row, the on-disk content is adopted "
            "verbatim (a DRIFT_RECOVERY row + soul_drift_detected audit event "
            "are recorded, but the content is not scanned).\n\n"
            "Your vim edit + /soul/reload is exactly the unscanned reload path. "
            "This is a documented sharp edge, not a bug. Under the single-operator "
            "threat model it is acceptable because only the operator can write "
            "soul.md. If you want it scanned, route the edit through "
            "POST /soul/apply with a non-empty human reason instead — that path "
            "rejects injection patterns (PromptInjectionError) BEFORE any file "
            "or DB write, and writes atomically (tmp + os.replace).\n\n"
            "If you intend to harden the reload/drift path (legitimate), you must "
            "update test_reload_adopts_soul_without_scanning__scan_is_write_path_only "
            "and Rule 5 deliberately — do not silently delete the tripwire."
        )},
    ],
    "source_refs": ["INVARIANTS.md:Rule 4,5", "utils/personality.py:apply_evolution,_load_soul,reload"],
},

# ── Decorative /health signal ────────────────────────────────────────────────
{
    "id": "debug-007-health-embeddings-static",
    "category": "Debugging Scenarios",
    "messages": [
        {"role": "system", "content": _DEBUG_SYSTEM},
        {"role": "user", "content": (
            "GET /health returns {\"embeddings_local\": \"healthy\"} but retrieval "
            "is returning zero results. The health check says the embedding model "
            "is fine — is the retriever broken?"
        )},
        {"role": "assistant", "content": (
            "The health check is lying, by design. Per INVARIANTS.md "
            "('Signals that are weaker than their name suggests'), "
            "`/health` `embeddings_local: healthy` is a hardcoded literal, not "
            "a probe — a broken embedding model still reports healthy. The "
            "test TestHealthEmbeddingsSignalIsStatic pins this.\n\n"
            "Do not trust it for retrieval readiness. Use the actual readiness "
            "fields: `index_ready` and `graph_ready`. For the real retrieval "
            "state, check whether the indices exist:\n"
            "  - ChromaDB persistent path (indexing.chroma_path) populated?\n"
            "  - BM25 JSON (indexing.bm25_path) has tokenized_corpus, chunks, "
            "and metadata with equal non-zero lengths? A corrupt/empty BM25 "
            "index raises IndexNotFoundError at HybridRetriever init.\n"
            "  - Embedding fingerprint matches? If the vector index was built "
            "with a different embedding model/dim/device, "
            "_check_embedding_fingerprint() raises IndexNotFoundError. On Apple "
            "Silicon an absent fingerprint is FATAL (MPS risk); on Linux/Windows "
            "it is warn-and-continue.\n\n"
            "If the indices are missing or stale, rebuild: "
            "`python -m retrieval.indexer`. Verify data/corpus/ has documents "
            "with the configured extensions."
        )},
    ],
    "source_refs": ["INVARIANTS.md:decorative signals", "retrieval/hybrid_search.py:_check_embedding_fingerprint", "retrieval/indexer.py"],
},

# ── Rule 8: sampling=None is decorative, no LLM import is the real guard ───
{
    "id": "debug-008-mcp-sampling-decorative",
    "category": "Debugging Scenarios",
    "messages": [
        {"role": "system", "content": _DEBUG_SYSTEM},
        {"role": "user", "content": (
            "An external MCP client connected to mcp_hybrid_server.py and is "
            "trying to use sampling/tool-calling to make the model generate "
            "text. The server declares sampling: null in capabilities. Is that "
            "what's blocking it, and can I set sampling to enable it?"
        )},
        {"role": "assistant", "content": (
            "No — `sampling` is a red herring and toggling it changes nothing. "
            "Per INVARIANTS.md Rule 8, the MCP server is retrieval-only "
            "STRUCTURALLY, not by capability flag: mcp_hybrid_server.py imports "
            "no LLM client (LocalLLMClient/GrokClient/anything under llm/) and "
            "never calls .generate(). That — not the decorative "
            "CAPABILITIES['sampling'] = None — is what makes it retrieval-only.\n\n"
            "`sampling` is a CLIENT capability in MCP; a server declaring it "
            "None enforces nothing. The tests "
            "TestMcpNoLlmPath.test_mcp_server_imports_no_llm_client and "
            "test_mcp_capabilities_declare_no_sampling pin both the import "
            "absence and the declared value. Do not add an LLM import 'because "
            "the capability is already declared' — the flag is not a guard.\n\n"
            "If you genuinely need generation over the MCP surface, the correct "
            "path is to add a new graph entry point that goes through retrieve → "
            "routing → audit (preserving I1/I4), not to wire an LLM into the MCP "
            "server. That would break I6 isolation and the retrieval-only "
            "contract the server exists to enforce."
        )},
    ],
    "source_refs": ["INVARIANTS.md:Rule 8", "mcp_hybrid_server.py", "tests/test_due_diligence_invariants.py:TestMcpNoLlmPath"],
},

# ── Rule 9 / I6: core imports OOB ───────────────────────────────────────────
{
    "id": "debug-009-i6-isolation-break",
    "category": "Debugging Scenarios",
    "messages": [
        {"role": "system", "content": _DEBUG_SYSTEM},
        {"role": "user", "content": (
            "CI is failing on TestCoreModuleIsolation with 'core module imports "
            "out-of-band package'. I only added `from guardrails.integration "
            "import apply_guard` to graph.py. What's wrong?"
        )},
        {"role": "assistant", "content": (
            "That import is the violation. Per INVARIANTS.md Rule 9 / I6, the "
            "core request-path modules — gate.py, gate_ops.py, gate_auth.py, "
            "gate_memory.py, graph.py, mcp_hybrid_server.py — must NEVER import "
            "agentic, sync, guardrails, harness, telegram, or opentweet (and "
            "those packages must never import the core six). The /ops/* routes "
            "reach the OOB CLIs only through utils/ops_runner.py, a "
            "subprocess.run([...]) shim — never an import.\n\n"
            "This isolation is what keeps the OOB subsystems from becoming a "
            "path around the security invariants. guardrails is OOB precisely "
            "so a bug or override in the rails layer cannot reach into the core "
            "request path.\n\n"
            "The graph touches guardrails ONLY through the injected bridge: "
            "utils/guardrail_bridge.py builds the guard functions and passes "
            "them in, so graph.py never imports guardrails. If you need a "
            "guardrail in the graph, add it as an injected callable (the "
            "generate_guard parameter on _generate_or_error is the existing "
            "pattern), do not import the guardrails package directly.\n\n"
            "Note: memory/ is NOT in the OOB set — it is default-off and "
            "lazy-imported from gate_memory.py, graph.py, and "
            "retrieval/hybrid_search.py, with its own isolation contract in "
            "tests/test_memory_isolation.py."
        )},
    ],
    "source_refs": ["INVARIANTS.md:Rule 9 / I6", "graph.py:guardrail_bridge injection", "utils/ops_runner.py", "tests/test_due_diligence_invariants.py:I6"],
},

# ── Rule 7: include_query_hash flipped ──────────────────────────────────────
{
    "id": "debug-010-audit-raw-query-leak",
    "category": "Debugging Scenarios",
    "messages": [
        {"role": "system", "content": _DEBUG_SYSTEM},
        {"role": "user", "content": (
            "I turned logging.audit_fields.include_query_hash to false to make "
            "the audit log easier to read, and now audit.jsonl contains the raw "
            "query text. Is that expected?"
        )},
        {"role": "assistant", "content": (
            "Yes, and it is a privacy regression, not a verbosity change. Per "
            "INVARIANTS.md Rule 7, with include_query_hash: true (the shipped "
            "default), audit_log() replaces the query field with its SHA-256 "
            "hash and never persists raw query text. Setting it false makes the "
            "audit log persist the raw query string — subject only to "
            "email/IP/secret redaction — turning audit.jsonl into a plaintext "
            "query log.\n\n"
            "The tests TestAuditQueryPrivacy.test_query_is_hashed_and_raw_text_never_persisted, "
            "test_shipped_config_enables_query_hashing, and "
            "test_disabling_hashing_persists_raw_text__documented_leak pin this "
            "behavior explicitly. The last one is a tripwire: it documents that "
            "disabling hashing is a known leak, so no one 'fixes' it by making "
            "raw text the default.\n\n"
            "Revert to true. If you need queryable audit content for debugging, "
            "grep the hashed query and correlate via hash_query() in "
            "utils/logger.py — do not persist raw queries on the query path."
        )},
    ],
    "source_refs": ["INVARIANTS.md:Rule 7", "utils/logger.py:audit_log,hash_query", "tests/test_due_diligence_invariants.py"],
},

# ── indexer chunk_document validation ───────────────────────────────────────
{
    "id": "debug-011-indexer-chunk-validation",
    "category": "Debugging Scenarios",
    "messages": [
        {"role": "system", "content": _DEBUG_SYSTEM},
        {"role": "user", "content": (
            "python -m retrieval.indexer crashes with 'overlap (60) must be < "
            "chunk_size (50)' during index build. My corpus is fine — what's "
            "wrong with my config?"
        )},
        {"role": "assistant", "content": (
            "The corpus is not the problem; the chunking config is. In "
            "retrieval/indexer.py, chunk_document validates its parameters "
            "explicitly and fails loud rather than silently degrading:\n"
            "  - chunk_size < 1 → ValueError('chunk_size must be >= 1')\n"
            "  - overlap < 0 → ValueError('overlap must be >= 0')\n"
            "  - overlap >= chunk_size → ValueError('overlap must be < chunk_size')\n\n"
            "The last one is your crash. With overlap >= chunk_size, the step "
            "(chunk_size - overlap) would be <= 0; a negative overlap makes step "
            "exceed chunk_size so each window jumps FORWARD past its own end and "
            "silently drops the words in the gap — a corpus indexed with a "
            "sign-typo'd overlap loses content from both retrieval legs with no "
            "error. The guard turns that silent data loss into a hard failure.\n\n"
            "Fix config.yaml: set indexing.chunk_overlap to a value strictly less "
            "than indexing.chunk_size (e.g. chunk_size: 512, chunk_overlap: 50). "
            "Then rebuild. Note build_index() also validates config values, but "
            "chunk_document() is called directly by tests and ad-hoc tooling, so "
            "the per-call guard is what caught your typo."
        )},
    ],
    "source_refs": ["retrieval/indexer.py:chunk_document,build_index"],
},

# ── llm/client retry: 4xx fail-fast ─────────────────────────────────────────
{
    "id": "debug-012-llm-retry-4xx",
    "category": "Debugging Scenarios",
    "messages": [
        {"role": "system", "content": _DEBUG_SYSTEM},
        {"role": "user", "content": (
            "Grok fallback is burning credits — it retries a 401 Unauthorized "
            "three times before giving up. Shouldn't a bad key fail immediately?"
        )},
        {"role": "assistant", "content": (
            "It should, and the shipped client does — so if you are seeing 401 "
            "retries, you are running a modified retry policy. In llm/client.py, "
            "_is_retryable_status returns True ONLY for status >= 500 "
            "(_RETRYABLE_STATUS_FLOOR) or status == 429 "
            "(_RETRYABLE_EXTRA_STATUS). All other 4xx — including 401 and 400 — "
            "fail fast. The docstring states this directly: 'Client errors "
            "(other 4xx) and unexpected exceptions fail fast — retrying a "
            "400/401 only wastes time and, for Grok, external credits.'\n\n"
            "Retry is config-driven via a retry block under each model; when "
            "absent, max_retries defaults to 0, preserving single-attempt "
            "behavior. So check:\n"
            "  - Did someone add 401 to _RETRYABLE_EXTRA_STATUS or lower "
            "_RETRYABLE_STATUS_FLOOR? That is the regression.\n"
            "  - Is the retry block on models.grok setting max_retries > 0? That "
            "is correct for 5xx/429 but must not widen the retryable set.\n\n"
            "Also note _extract_content: a 2xx body that is malformed (non-JSON, "
            "missing choices[0].message.content, or content=null/empty) raises "
            "ValueError('malformed LLM response (...)') — and this is NOT "
            "retried, because a retry would re-fetch the same malformed body."
        )},
    ],
    "source_refs": ["llm/client.py:_is_retryable_status,_extract_content,_client_timeout"],
},

# ── load_corpus symlink escape ──────────────────────────────────────────────
{
    "id": "debug-013-corpus-symlink-rejected",
    "category": "Debugging Scenarios",
    "messages": [
        {"role": "system", "content": _DEBUG_SYSTEM},
        {"role": "user", "content": (
            "I symlinked a file into data/corpus/ from outside the repo and the "
            "indexer logged 'Skipping <path>: resolves outside corpus "
            "directory' and never indexed it. Why is it rejecting my file?"
        )},
        {"role": "assistant", "content": (
            "That is a path-traversal guard, not a bug. In "
            "retrieval/indexer.py load_corpus, rglob follows symlinks by "
            "default, so a link pointing outside data/corpus could pull "
            "arbitrary filesystem content into the index. The function checks "
            "file_path.resolve().is_relative_to(corpus_resolved) and skips any "
            "file whose resolved path escapes the corpus directory, logging the "
            "skip. This is why your symlinked file is rejected.\n\n"
            "To include the content legitimately, copy the actual file bytes "
            "into data/corpus/ (or a subdirectory) rather than symlinking across "
            "a trust boundary. If the target lives outside the corpus for a "
            "good reason (e.g. a shared corpus on another volume), point "
            "corpus.path at that directory directly in config.yaml — the "
            "anchor resolves the path, and everything under it is in-bounds.\n\n"
            "Also note load_corpus matches extensions case-insensitively "
            "(.MD matches a .md config entry) and skips files that fail "
            "UnicodeDecodeError/OSError on read with a warning. If no documents "
            "match at all, it raises CorpusEmptyError."
        )},
    ],
    "source_refs": ["retrieval/indexer.py:load_corpus"],
},

# ── /soul 401 fail-closed + hmac.compare_digest ─────────────────────────────
{
    "id": "debug-014-soul-401-fail-closed",
    "category": "Debugging Scenarios",
    "messages": [
        {"role": "system", "content": _DEBUG_SYSTEM},
        {"role": "user", "content": (
            "POST /soul/apply returns 401 even though I'm on localhost. There's "
            "no 'open mode' for local dev? And the docs mention "
            "security.require_env — do I set that?"
        )},
        {"role": "assistant", "content": (
            "There is no open mode, by design. Per INVARIANTS.md Rule 6, with "
            "CYCLAW_API_KEY unset, every /soul/*, /ops/*, and /audit/summary "
            "route returns 401 — never 'open mode.' Key comparison uses "
            "hmac.compare_digest (constant-time), so do not try to shortcut it "
            "with ==. Reintroducing an unauthenticated fallback is explicitly "
            "forbidden.\n\n"
            "security.require_env is decorative — no code reads it, and the "
            "server boots fine without GROK_API_KEY (Grok just reports "
            "unavailable). Setting it does nothing for auth. Set "
            "CYCLAW_API_KEY in the environment to a strong secret and send it as "
            "the API key header on /soul/* and /ops/* requests.\n\n"
            "Separately, the scanner path resolution is CWD-independent: "
            "utils/sanitizer.check_input resolves a non-absolute config_path "
            "against the repo root (_REPO_ROOT), so the injection filter works "
            "from any working directory. Do not revert to a bare "
            "open('config.yaml') — that reintroduces the CWD-relative crash that "
            "took down the entire /query path when launched from outside the "
            "repo root (finding F4)."
        )},
    ],
    "source_refs": ["INVARIANTS.md:Rule 6", "utils/sanitizer.py:check_input,_REPO_ROOT", "gate.py:auth"],
},

# ── httpx connect timeout burns whole request budget ────────────────────────
{
    "id": "debug-015-connect-timeout-burns-budget",
    "category": "Debugging Scenarios",
    "messages": [
        {"role": "system", "content": _DEBUG_SYSTEM},
        {"role": "user", "content": (
            "A local_llm call to Ollama is taking the full 600s timeout and then "
            "failing, even though Ollama is up. The connect step seems to hang."
        )},
        {"role": "assistant", "content": (
            "This is the httpx single-timeout failure mode that "
            "llm/client.py was specifically hardened against. Without a separate "
            "connect ceiling, httpx applies one number to connect/read/write/pool "
            "alike, so a stalled connect attempt (a black-holed TCP handshake — "
            "firewall/proxy drop, not a fast ECONNREFUSED) burns the ENTIRE "
            "overall timeout on a worker thread before the caller sees an error. "
            "For GrokClient/ClaudeClient that repeats on every retry attempt.\n\n"
            "The fix in llm/client.py: _CONNECT_TIMEOUT_SEC = 10.0, and "
            "_client_timeout(overall) returns httpx.Timeout(overall, "
            "connect=min(overall, 10.0)) — connect gets its own short ceiling "
            "capped at the overall timeout. So a black-holed connect fails in "
            "~10s, not 600s.\n\n"
            "If you are seeing the full 600s burn, either:\n"
            "  - You are on an older client.py without the connect cap "
            "(mirrors telegram/client.py's identical pattern), or\n"
            "  - The hang is in read/write, not connect — in which case check "
            "the graph deadline. gate.py sets _graph_deadline (a ContextVar) to "
            "monotonic() + graph_timeout_sec before to_thread(invoke). "
            "_call_timeout(cap) shrinks the per-POST timeout to the remaining "
            "graph budget; if remaining <= 0 it raises "
            "httpx.TimeoutException('graph deadline elapsed') immediately.\n\n"
            "So a 600s wall-clock hang with Ollama up almost always means either "
            "the connect cap is missing or the model is generating into a "
            "context window that leaves no room (see the blank-answer "
            "diagnostic: max_tokens reserved output budget vs context window)."
        )},
    ],
    "source_refs": ["llm/client.py:_CONNECT_TIMEOUT_SEC,_client_timeout,_call_timeout,_graph_deadline"],
},

# ── banned_patterns best-effort, homoglyph evasion ──────────────────────────
{
    "id": "debug-016-banned-patterns-homoglyph",
    "category": "Debugging Scenarios",
    "messages": [
        {"role": "system", "content": _DEBUG_SYSTEM},
        {"role": "user", "content": (
            "A prompt-injection red-team probe spelled 'іgnore' (with a "
            "Cyrillic і) past the input filter, but the ASCII 'ignore previous "
            "instructions' variant was caught. Is the filter broken?"
        )},
        {"role": "assistant", "content": (
            "The filter is working as designed — it is defense-in-depth, not a "
            "completeness guarantee. Per INVARIANTS.md, banned_patterns is "
            "best-effort regex over raw text (~40 patterns in the shipped "
            "config). Homoglyph and zero-width evasion is explicitly out of "
            "scope per the threat model. The probe that spelled 'іgnore' with a "
            "Cyrillic і does not byte-match the ASCII 'ignore' pattern, so the "
            "regex does not fire — that is the expected gap, not a bug.\n\n"
            "Do not try to 'fix' this by expanding the regex to every Unicode "
            "lookalike; that is an unbounded arms race. The layered defense is "
            "what actually contains it:\n"
            "  - The NFKC normalization in the injection filter folds some "
            "lookalikes before matching, but not all.\n"
            "  - The untrusted-context framing in graph.py (UNTRUSTED_NOTE + "
            "delimiters) tells the model retrieved content is not an "
            "instruction, so even if a probe reaches the LLM, the model is "
            "structurally told to disregard instruction-like text in the "
            "retrieved block.\n"
            "  - The output grounding rail (guardrail_output) checks the local "
            "answer for grounding.\n"
            "  - Every path audits, so a probe that succeeds is still logged.\n\n"
            "If a homoglyph probe reaches generation and the model follows it, "
            "treat it as a soul/identity boundary issue (is the probe in "
            "retrieved docs or in the soul?) and route the soul edit through "
            "POST /soul/apply, which scans at the write boundary."
        )},
    ],
    "source_refs": ["INVARIANTS.md:decorative signals, banned_patterns", "graph.py:UNTRUSTED_NOTE", "utils/sanitizer.py"],
},

]
