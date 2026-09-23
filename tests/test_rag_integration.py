"""Real retriever-through-graph integration test.

CI already runs tests.ci_rag_smoke against the committed corpus. This test keeps
the distinct signal: a real ChromaDB + BM25 index flowing through graph.py.
"""

from pathlib import Path

import yaml

from graph import build_graph
from retrieval.indexer import build_index
from retrieval.hybrid_search import HybridRetriever
from tests.conftest import MockLocalLLM
from utils.logger import close_audit_handles, reset_config_cache


# Repo root, for cwd-independent reads of the shipped config.yaml. A bare
# Path("config.yaml") breaks when pytest is invoked from outside the repo root.
_REPO_ROOT = Path(__file__).resolve().parent.parent


def _fake_embedding(_text: str, _config_path: str = "config.yaml") -> list[float]:
    return [1.0, 0.0, 0.0]


def _write_isolated_config(tmp_path: Path) -> tuple[Path, dict]:
    cfg = yaml.safe_load((_REPO_ROOT / "config.yaml").read_text(encoding="utf-8"))

    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "overview.md").write_text(
        "# CyClaw Retrieval\n\n"
        "CyClaw blends semantic embeddings with BM25 keyword search using "
        "Reciprocal Rank Fusion before the graph routes to the local LLM.\n",
        encoding="utf-8",
    )

    cfg["corpus"] = {"path": str(corpus), "extensions": [".md"]}
    cfg["indexing"] = {
        **cfg["indexing"],
        "chroma_path": str(tmp_path / "chroma_db"),
        "bm25_path": str(tmp_path / "bm25.json"),
        "collection_name": "rag_integration_test",
    }
    cfg["models"]["embeddings"] = {
        **cfg["models"]["embeddings"],
        "cache_dir": str(tmp_path / ".emb_cache"),
    }
    cfg["retrieval"] = {
        **cfg["retrieval"],
        "top_k_semantic": 2,
        "top_k_keyword": 2,
        "min_score": 0.028,
    }
    cfg["logging"] = {
        **cfg["logging"],
        "audit_file": str(tmp_path / "audit.jsonl"),
    }

    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return config_path, cfg


class _FakeCrossEncoder:
    """Returns one fixed logit per pair, standing in for the real cross-encoder."""

    def __init__(self, logit: float) -> None:
        self.logit = logit
        self.pairs: list[tuple[str, str]] = []

    def predict(self, pairs, **_kwargs):
        self.pairs.extend(pairs)
        return [self.logit for _ in pairs]


def _run_graph_on_real_index(tmp_path, monkeypatch, cross_encoder: _FakeCrossEncoder) -> tuple[dict, dict]:
    """Build the isolated index and invoke the real graph once; return (result, cfg)."""
    config_path, cfg = _write_isolated_config(tmp_path)
    reset_config_cache()
    monkeypatch.setattr(
        "retrieval.indexer.get_embeddings_batch",
        lambda texts, config_path="config.yaml": [_fake_embedding(text) for text in texts],
    )
    monkeypatch.setattr(
        "retrieval.indexer.get_token_counter",
        lambda config_path="config.yaml": (lambda texts: [len(t.split()) for t in texts], 256, 2),
    )
    monkeypatch.setattr("retrieval.hybrid_search.get_embedding", _fake_embedding)
    monkeypatch.setattr("utils.logger._get_config", lambda config_path="config.yaml": cfg)
    # The shipped config enables the reranker; no unit test may download it.
    monkeypatch.setattr("retrieval.rerank._load_cross_encoder", lambda *_args: cross_encoder)

    build_index(str(config_path))
    retriever = HybridRetriever(str(config_path))
    try:
        graph = build_graph(retriever=retriever, llm=MockLocalLLM(response="local answer"), grok=None, cfg=cfg)
        result = graph.invoke({"query": "How does CyClaw blend semantic embeddings with BM25 keyword search?"})
    finally:
        retriever.close()
        close_audit_handles()
        reset_config_cache()
    return result, cfg


def test_reranker_veto_turns_a_cosine_hit_into_a_miss_end_to_end(tmp_path, monkeypatch) -> None:
    """The fake index is a cosine hit; a cross-encoder logit below the floor vetoes it."""
    cross_encoder = _FakeCrossEncoder(logit=-5.0)
    result, cfg = _run_graph_on_real_index(tmp_path, monkeypatch, cross_encoder)

    assert cfg["models"]["reranker"]["enabled"] is True
    assert cross_encoder.pairs, "retrieve_node never asked the reranker"
    assert result["rerank_vetoed"] is True
    assert result["needs_user_confirm"] is True
    assert result["answer_model"] != "local"
    assert all(d["rerank_score"] == -5.0 for d in result["retrieved_docs"])


def test_reranker_above_the_floor_keeps_the_vault_hit(tmp_path, monkeypatch) -> None:
    result, _cfg = _run_graph_on_real_index(tmp_path, monkeypatch, _FakeCrossEncoder(logit=5.0))

    assert result["answer_model"] == "local"
    assert not result.get("rerank_vetoed")


def test_real_retriever_result_flows_through_graph(tmp_path, monkeypatch) -> None:
    """Real index -> HybridRetriever -> LangGraph -> local answer + audit."""
    config_path, cfg = _write_isolated_config(tmp_path)
    # The shipped config enables the reranker; this test is about the cosine
    # path, so it runs with the reranker off (and so never loads the model).
    cfg["models"]["reranker"] = {**cfg["models"]["reranker"], "enabled": False}
    config_path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    reset_config_cache()
    monkeypatch.setattr(
        "retrieval.indexer.get_embeddings_batch",
        lambda texts, config_path="config.yaml": [_fake_embedding(text) for text in texts],
    )
    # The shipped config chunks by embedder tokens; one token per word stands
    # in for the real tokenizer so no model is loaded.
    monkeypatch.setattr(
        "retrieval.indexer.get_token_counter",
        lambda config_path="config.yaml": (lambda texts: [len(t.split()) for t in texts], 256, 2),
    )
    monkeypatch.setattr("retrieval.hybrid_search.get_embedding", _fake_embedding)
    monkeypatch.setattr("utils.logger._get_config", lambda config_path="config.yaml": cfg)

    build_index(str(config_path))
    retriever = HybridRetriever(str(config_path))
    llm = MockLocalLLM(response="local answer")

    try:
        graph = build_graph(retriever=retriever, llm=llm, grok=None, cfg=cfg)
        result = graph.invoke({
            "query": "How does CyClaw blend semantic embeddings with BM25 keyword search?"
        })
    finally:
        retriever.close()
        close_audit_handles()
        reset_config_cache()

    assert result["answer_model"] == "local"
    assert result["top_score"] >= cfg["retrieval"]["min_score"]
    assert result["answer_sources"]
    assert "overview.md" in result["answer_sources"][0]["source"]
    assert result["audit_event"]["event"] == "rag_query"
    assert result["audit_event"]["model_used"] == "local"
    assert llm.last_prompt is not None
    assert "Reciprocal Rank Fusion" in llm.last_prompt
