"""Pins CyClaw-Sandbox Phase 3 chunk construction vs the BM25 try.

Codex review on #1401: initializing `chunks = []` before the try still left
the list empty when `rank_bm25` was missing, so Chroma recorded a pass with
zero documents. Chunk text must be built before BM25-only imports.
"""

from __future__ import annotations

from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_CLAUDE = _REPO / ".claude" / "skills" / "CyClaw-Sandbox" / "run_full_verification.py"
_CODEX = _REPO / ".codex" / "skills" / "Cyclaw-Sandbox" / "run_full_verification.py"


def _phase3(text: str) -> str:
    start = text.index("def phase_build_corpus")
    end = text.index("def phase_execute_queries")
    return text[start:end]


def test_claude_swarm_builds_chunks_before_bm25_import() -> None:
    phase = _phase3(_CLAUDE.read_text(encoding="utf-8"))
    assert phase.index('chunks.append({"text": text') < phase.index("from rank_bm25 import BM25Okapi")
    assert 'raise ValueError("no chunks to index")' in phase


def test_codex_swarm_builds_chunks_before_stemmer_import() -> None:
    phase = _phase3(_CODEX.read_text(encoding="utf-8"))
    assert phase.index('chunks.append({"text": text') < phase.index("from retrieval.stemmer import tokenize_and_stem")
    assert 'raise ValueError("no chunks to index")' in phase
