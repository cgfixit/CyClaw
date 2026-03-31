================================================================================
                          SafeClaw (Current Vision)
                    Offline‑First, RAG‑First, MCP‑Exposed Stack
================================================================================

                          ┌────────────────────────────┐
                          │   Chris / Client Devices   │
                          │  - LM Studio UI (MCP)      │
                          │  - CLI / Web UI (HTTP)     │
                          └─────────────┬──────────────┘
                                        │  User query
                                        ▼
================================================================================
A. SafeClaw Gateway Layer (DL360p Gen8) – FastAPI + MCP + LangGraph Controller
================================================================================

                      (DL360p Gen8 – 24/7, localhost‑only bindings)

                         ┌────────────────────────────┐
                         │    FastAPI HTTP Gateway    │
                         │  - /query (JSON API)       │
                         │  - /mcp/tools (RPC)        │
                         │  - Binds 127.0.0.1:8787    │
                         └─────────────┬──────────────┘
                                       │
                      Builds initial GraphState: { query, ... }
                                       │
                                       ▼
                         ┌────────────────────────────┐
                         │   LangGraph Controller     │
                         │   ("SafeClaw Clawbot")     │
                         │  Topology = Enforcement    │
                         └─────────────┬──────────────┘
                                       │
             ┌─────────────────────────┴─────────────────────────┐
             │                                                   │
             ▼                                                   ▼

   [Node 1: retrieve]                                  (Config + libs wired in)
   ──────────────────
   • Reads state.query
   • Calls Hybrid Retrieval Service (see section B)
   • Writes:
       - retrieved_docs[ ] (chunks + scores)
       - top_score (float)
       - retrieval_mode = "hybrid" | "vector" | "bm25" | "none"

             │
             ▼

   [Node 2: route_by_score]
   ───────────────────────
   • Compares top_score to cfg.retrieval.min_score (e.g. 0.75)
   • If top_score ≥ threshold:
   │     state.needs_user_confirm = False
   │     ──► route to local_llm
   • Else:
         state.needs_user_confirm = True
         ──► route to user_gate

             │                                      
   ┌─────────┴───────────┐
   │                     │
   ▼                     ▼

[Node 3: local_llm]                    [Node 4: user_gate]
────────────────────                    ───────────────────
• Builds prompt from                    • If user_confirmed_online is None:
  retrieved_docs + query                  - Return to client with:
• Calls LM Studio chat                      needs_confirm = true
  (localhost:1234) with                     message: "Vault miss (score X < 0.75).
  configured model                          Go online to Grok? (y/n)"
• Writes:                                 • Client re‑calls /query with
    - answer                                 user_confirmed_online = true/false
    - answer_model = "local"              • State passes through unchanged for
    - answer_sources (top N docs)           LangGraph routing

   │                                         │
   │                                         ▼

   │                         [Conditional routing from user_gate]
   │                         ────────────────────────────────────
   │                         • If:
   │                             - cfg.app.mode = "hybrid" AND
   │                             - cfg.models.grok.enabled AND
   │                             - state.user_confirmed_online is True
   │                           ──► grok_fallback
   │                         • Else
   │                           ──► offline_best_effort
   │
   ▼

[Node 5: grok_fallback]             [Node 6: offline_best_effort]
────────────────────────             ─────────────────────────────
• Only reachable when:              • Used when:
    - hybrid mode enabled              - user said "no", OR
    - user_confirmed_online = True     - hybrid/online disabled by config
• Builds prompt:                    • Returns:
    - query alone (or                  - best‑effort answer from local LLM
      optional sanitized context)      - answer_model = "offline-best-effort"
• Calls Grok via xAI API              - answer_sources = retrieved_docs (top N)
  using GROK_API_KEY (env)
• Writes:
    - answer
    - answer_model = "grok"
    - answer_sources = [ { source: "Grok Fallback" } ]

             │
             └──────────────┬─────────────────────────────┐
                            ▼                             ▼

                   [Node 7: audit_logger]
                   ──────────────────────
                   • Runs for ALL paths (local, grok, offline)
                   • Computes query_hash = SHA256(query)
                   • Writes JSONL line to cfg.logging.audit_file:
                       {
                         event: "rag_query",
                         timestamp: ...,
                         query_hash: ...,
                         top_score: ...,
                         retrieval_mode: ...,
                         online_escalated: (answer_model == "grok"),
                         model_used: answer_model
                       }
                   • Attaches audit event into state.audit
                   • Graph terminates here (END)

                                       │
                                       ▼
                         ┌────────────────────────────┐
                         │   Gateway HTTP / MCP Resp  │
                         │  - answer                  │
                         │  - sources (chunks/meta)   │
                         │  - needs_confirm flag      │
                         └────────────────────────────┘


================================================================================
B. SafeClaw Retrieval Layer – Hybrid RAG on CPU (DL360p)
================================================================================

   ┌────────────────────────────────────────────────────────────────────────┐
   │                         Hybrid Retrieval Service                       │
   │                  (used by LangGraph retrieve node)                    │
   └────────────────────────────────────────────────────────────────────────┘

                           ┌──────────────────────┐
                           │  Corpus (.md/.txt)  │
                           │  data/corpus/       │
                           └─────────┬────────────┘
                                     │  (indexer.py batch job)
                                     ▼
                     ┌──────────────────────────────────┐
                     │       Index Builder (CPU)        │
                     │   retrieval/indexer.py           │
                     │   - load_corpus()                │
                     │   - chunk_document()             │
                     │   - tokenize_and_stem()          │
                     │   - build embeddings (ST CPU)    │
                     └─────────┬─────────────┬──────────┘
                               │             │
                      semantic index   keyword index
                         (Chroma)        (BM25)
                               │             │
                  ┌────────────┘             └────────────┐
                  ▼                                       ▼
      ┌───────────────────────┐                ┌─────────────────────┐
      │   ChromaDB Embedded   │                │   BM25 (rank_bm25)  │
      │   index/chroma_db/    │                │   index/bm25.pkl    │
      └───────────┬───────────┘                └───────────┬─────────┘
                  │  query(text)                           │  query(tokens)
                  └──────────┬──────────────────────────────┘
                             ▼
                  ┌────────────────────────────┐
                  │ hybrid_search.py           │
                  │ - compute embedding(text)  │
                  │   via sentence-transformers│
                  │   (CPU on DL360p)          │
                  │ - semantic search (top_k)  │
                  │ - BM25 search (top_k)      │
                  │ - RRF fuse w/ weights      │
                  └────────────────────────────┘
                             │
                             ▼
                  top fused results -> LangGraph.retrieve


================================================================================
C. Local Models on DL360p – Option C (No Ollama)
================================================================================

            ┌───────────────────────────────────────────────┐
            │     sentence-transformers (embeddings)        │
            │     - all-MiniLM-L6-v2 (or similar)           │
            │     - CPU-only, uses DL360p cores + RAM       │
            └──────────────────────────────┬────────────────┘
                                           │ used by indexer & hybrid_search
                                           ▼

            ┌───────────────────────────────────────────────┐
            │          LM Studio (local LLM)               │
            │  - GGUF model: Llama 3.1 8B / Qwen 7B        │
            │  - HTTP: http://127.0.0.1:1234/v1            │
            │  - Chat only (no embeddings required)        │
            └──────────────────────────────┬────────────────┘
                                           │ used by local_llm & offline_best_effort
                                           ▼

            ┌───────────────────────────────────────────────┐
            │                Grok API (online)              │
            │  - base_url: https://api.x.ai/v1             │
            │  - model: grok-beta                           │
            │  - Only callable when:                       │
            │      app.mode == "hybrid" AND                │
            │      user_confirmed_online == True           │
            └───────────────────────────────────────────────┘


================================================================================
D. Config & Security Constraints (High-Level)
================================================================================

• YAML config:
  - app.mode: "offline" | "hybrid" (hybrid enables Grok path)
  - retrieval.min_score: 0.75
  - retrieval.hybrid.enabled: true
  - policy.fallback.require_user_confirm: true
  - policy.prompt_filter.enabled: true (sanitizes chunks at ingestion)
  - logging.audit_file: ./logs/audit.jsonl
  - security.require_env: ["GROK_API_KEY"]

• Bindings:
  - FastAPI gateway: 127.0.0.1:8787 only
  - LM Studio: 127.0.0.1:1234 only
  - No Ollama in final design

• Invariants enforced by topology + code:
  1. Every query passes through retrieval first.
  2. No LLM (local or Grok) is called before RAG & score gate.
  3. No Grok call is possible without explicit user confirmation AND hybrid mode.
  4. Every response passes through audit logging.
