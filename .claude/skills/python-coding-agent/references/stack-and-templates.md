# python-coding-agent — stack table & output templates

Reference material for the `python-coding-agent` skill. Not injected by the
SessionStart hook (only `SKILL.md` is); read this file explicitly when the
task needs a library default, a scaffold, or the forward-looking notes below.

## CyClaw Stack (Override Only If Asked)

| Category | Default | Alt / Note |
|---|---|---|
| Linter/formatter | `ruff check` + `ruff format` (line 120, py312) | — |
| Types | `mypy --strict --python-version 3.12` | `pyright` (IDE) |
| HTTP | `httpx` 0.28+ (sync+async) | `requests` (legacy only) |
| Validation | `pydantic v2` 2.13+ | `dataclasses` (zero-dep scripts) |
| API | `FastAPI` 0.137+ + `uvicorn[standard]` 0.49+ | `starlette` (raw) |
| CLI | `typer` | `argparse` (stdlib; used in existing scripts) |
| Config | `pydantic-settings` + `PyYAML` 6.0 | `tomllib` (3.11+, stdlib) |
| AI orchestration | `langgraph` 1.2+ (`StateGraph`, `END`) | — no full LangChain — |
| Vector store | `chromadb` 1.5+ `PersistentClient` (embedded only, never HTTP) | — |
| Keyword retrieval | `rank_bm25` 0.2+ `BM25Okapi` | — |
| Embeddings | `sentence-transformers` 5.6+ | — |
| Retry | `tenacity` | — |
| Env mgmt | `venv` + `pip` | `uv` (forward-looking) |
| Logging | `logging` stdlib (audit JSONL via `utils/logger.py`) | `structlog` (dev) |
| MCP | `mcp` SDK (tools: retrieval only, no LLM sampling) | — |
| Tests | `pytest` 9.1+ + `coverage` ≥80% | — |

Install quirks (torch pin order, PyYAML flag, the macOS branch) are owned by
`CLAUDE.md` §8 — cite that section rather than repeating the commands here.

## Output Templates

### Script skeleton (CyClaw style)

```python
#!/usr/bin/env python3
"""script_name.py – one-line purpose.

Usage: python script_name.py --input <path> [--dry-run]
Requires: Python 3.12+ | see requirements.txt
"""
from __future__ import annotations
import argparse
import logging
import sys
from pathlib import Path

log = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)
    # core logic here
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sys.exit(main())
```

Always append: **Verify** — `python -m py_compile`, `mypy --strict`,
`ruff check`, `GROK_API_KEY=dummy pytest tests/ -q`. **Deps** — note any
addition to `requirements.txt`.

### LangGraph node skeleton

```python
from __future__ import annotations
from typing import Any
from langgraph.graph import StateGraph, END
from schemas.api import GraphState  # TypedDict

def my_node(state: GraphState) -> dict[str, Any]:
    # read from state, never mutate in place
    ...
    return {"field": value}

# Wire into graph:
# graph.add_node("my_node", my_node)
# graph.add_edge("my_node", END)
```

### Corpus entry skeleton

```markdown
---
title: ""
date: YYYY-MM-DD
tags: []
source: ""
---
## Summary
## Key Insights
## Action Items
- [ ] item (Priority: ?, Due: ?)
## Technical Details
## Version Notes
| Feature | Min Version | Fallback |
## References
```

## Forward-Looking Notes

Apply when they offer concrete benefit — not a mandate to chase every trend:

- **MCP:** prefer structured tool output (`TextContent` JSON) for
  agent-parseable results.
- **LangGraph multi-agent:** `StateGraph` with subgraph composition for
  complex topologies; avoid monolithic graphs beyond ~10 nodes.
- **Claude API / Agent SDK:** for harnesses calling Claude, use the
  `anthropic` SDK with tool use and streaming; respect token budgets and
  caching.
- **Local LLM:** Ollama keeps expanding its OpenAI-compatible surface — keep
  `llm/client.py` endpoint-agnostic rather than hardcoding Ollama-only
  assumptions.
- **`uv` adoption:** faster than `pip`; keep `pyproject.toml` primary and
  `requirements.txt` as the legacy CI path.
- **Python 3.13+:** annotate `# 3.13+` features (e.g. `locals()` semantics,
  PEP 696 defaults) when used.
