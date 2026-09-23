"""Tests for the cross-encoder reranker behind the vault-hit gate's veto.

retrieval/rerank.py (settings, loading, fail-soft scoring) and the graph.py
wiring around it: retrieve_node scores the context window, and the audit
record carries the veto's inputs and outcome. The veto rule itself is pinned
by TestRerankVeto in tests/test_edge_cases.py. No test here loads the real
model: sentence_transformers is replaced, or the loader is.
"""

import sys
import types

import pytest
from torch import nn

import retrieval.rerank as rerank
from retrieval.hybrid_search import SearchResult
from tests.conftest import MockRetriever
from utils.errors import RerankerError

MODEL = "cross-encoder/ms-marco-MiniLM-L6-v2"
# Captured before any test patches it, so the autouse fixture can always clear
# the real lru_cache whatever monkeypatch has swapped in at teardown time.
_REAL_LOADER = rerank._load_cross_encoder


def _cfg(**reranker):
    block = {"enabled": True, "model": MODEL, "revision": None, **reranker}
    return {"models": {"embeddings": {"cache_dir": ".emb_cache", "offline_after_index": False}, "reranker": block}}


class _FakeModel:
    def __init__(self, scores):
        self.scores = scores
        self.calls = []

    def predict(self, pairs, **kwargs):
        self.calls.append((list(pairs), kwargs))
        return list(self.scores)


def _offline(*_args):
    raise OSError("offline and not cached")


@pytest.fixture(autouse=True)
def _fresh_reranker_state():
    rerank._failed_at.clear()
    _REAL_LOADER.cache_clear()
    yield
    rerank._failed_at.clear()
    _REAL_LOADER.cache_clear()


class TestRerankerSettings:
    def test_enabled_block_resolves_model_revision_and_cache(self, tmp_path):
        config_path = str(tmp_path / "config.yaml")
        settings = rerank.reranker_settings(_cfg(revision="abc123"), config_path)
        assert settings == (MODEL, "abc123", str((tmp_path / ".emb_cache").resolve()), False)

    @pytest.mark.parametrize("enabled", [False, None, "true", 1])
    def test_only_literal_true_enables(self, enabled):
        assert rerank.reranker_settings(_cfg(enabled=enabled), "config.yaml") is None

    def test_missing_block_is_off(self):
        assert rerank.reranker_settings({"models": {}}, "config.yaml") is None
        assert rerank.reranker_settings({}, "config.yaml") is None

    def test_empty_model_is_off(self):
        assert rerank.reranker_settings(_cfg(model=""), "config.yaml") is None

    def test_empty_revision_means_unpinned(self):
        assert rerank.reranker_settings(_cfg(revision=""), "config.yaml")[1] is None

    def test_offline_flag_follows_the_embedder(self):
        cfg = _cfg()
        cfg["models"]["embeddings"]["offline_after_index"] = True
        assert rerank.reranker_settings(cfg, "config.yaml")[3] is True


class TestRerankScores:
    def test_off_returns_none_without_loading(self, monkeypatch):
        monkeypatch.setattr(rerank, "_load_cross_encoder", lambda *a: pytest.fail("loaded while off"))
        assert rerank.rerank_scores("q", ["t"], _cfg(enabled=False), "config.yaml") is None

    def test_no_texts_returns_none_without_loading(self, monkeypatch):
        monkeypatch.setattr(rerank, "_load_cross_encoder", lambda *a: pytest.fail("loaded for nothing"))
        assert rerank.rerank_scores("q", [], _cfg(), "config.yaml") is None

    def test_scores_each_query_text_pair(self, monkeypatch):
        model = _FakeModel([2.5, -1.0])
        monkeypatch.setattr(rerank, "_load_cross_encoder", lambda *a: model)
        assert rerank.rerank_scores("q", ["a", "b"], _cfg(), "config.yaml") == [2.5, -1.0]
        pairs, kwargs = model.calls[0]
        assert pairs == [("q", "a"), ("q", "b")]
        assert kwargs["show_progress_bar"] is False

    def test_load_failure_raises_typed_error(self, monkeypatch):
        monkeypatch.setattr(rerank, "_load_cross_encoder", _offline)
        with pytest.raises(RerankerError) as err:
            rerank.rerank_scores("q", ["a"], _cfg(), "config.yaml")
        assert err.value.code == "RERANKER_UNAVAILABLE"

    def test_recent_failure_answers_without_retrying_the_load(self, monkeypatch):
        calls = []

        def counting_offline(*args):
            calls.append(args)
            _offline()
        monkeypatch.setattr(rerank, "_load_cross_encoder", counting_offline)
        for _ in range(3):
            with pytest.raises(RerankerError):
                rerank.rerank_scores("q", ["a"], _cfg(), "config.yaml")
        assert len(calls) == 1

    def test_failure_memo_expires(self, monkeypatch):
        now = [1000.0]
        monkeypatch.setattr(rerank.time, "monotonic", lambda: now[0])
        monkeypatch.setattr(rerank, "_load_cross_encoder", _offline)
        with pytest.raises(RerankerError):
            rerank.rerank_scores("q", ["a"], _cfg(), "config.yaml")
        now[0] += rerank._RETRY_AFTER_SEC + 1
        monkeypatch.setattr(rerank, "_load_cross_encoder", lambda *a: _FakeModel([1.0]))
        assert rerank.rerank_scores("q", ["a"], _cfg(), "config.yaml") == [1.0]
        assert not rerank._failed_at

    def test_score_count_mismatch_raises(self, monkeypatch):
        monkeypatch.setattr(rerank, "_load_cross_encoder", lambda *a: _FakeModel([1.0]))
        with pytest.raises(RerankerError):
            rerank.rerank_scores("q", ["a", "b"], _cfg(), "config.yaml")


class TestLoadCrossEncoder:
    @pytest.fixture
    def fake_st(self, monkeypatch):
        captured = {}

        class FakeCrossEncoder:
            attempts = 0

            def __init__(self, model, **kwargs):
                FakeCrossEncoder.attempts += 1
                if captured.get("fail_first") and FakeCrossEncoder.attempts == 1:
                    raise OSError("transient")
                captured.update(model=model, **kwargs)

        monkeypatch.setitem(sys.modules, "sentence_transformers", types.SimpleNamespace(CrossEncoder=FakeCrossEncoder))
        monkeypatch.setattr(rerank.time, "sleep", lambda _s: None)
        return captured

    def test_loads_pinned_revision_on_cpu_with_raw_logits(self, fake_st, monkeypatch):
        monkeypatch.setattr(rerank, "_model_offline_eligible", lambda *a: False)
        rerank._load_cross_encoder(MODEL, "abc123", "/cache", False, "config.yaml")
        assert fake_st["model"] == MODEL
        assert fake_st["revision"] == "abc123"
        assert fake_st["cache_folder"] == "/cache"
        assert fake_st["device"] == "cpu"
        assert fake_st["local_files_only"] is False
        assert isinstance(fake_st["activation_fn"], nn.Identity)

    def test_cached_snapshot_loads_local_only(self, fake_st, monkeypatch):
        probed = []
        monkeypatch.setattr(rerank, "_model_offline_eligible", lambda *a: probed.append(a) or True)
        rerank._load_cross_encoder(MODEL, "abc123", "/cache", False, "config.yaml")
        assert probed == [(MODEL, "/cache", "abc123")]
        assert fake_st["local_files_only"] is True

    def test_offline_after_index_refuses_a_fresh_fetch(self, fake_st, monkeypatch):
        monkeypatch.setattr(rerank, "_model_offline_eligible", lambda *a: False)
        monkeypatch.setattr(rerank, "_index_or_bm25_present", lambda _p: True)
        rerank._load_cross_encoder(MODEL, None, "", True, "config.yaml")
        assert fake_st["local_files_only"] is True
        assert fake_st["cache_folder"] is None

    def test_transient_network_failure_is_retried(self, fake_st, monkeypatch):
        fake_st["fail_first"] = True
        monkeypatch.setattr(rerank, "_model_offline_eligible", lambda *a: False)
        rerank._load_cross_encoder(MODEL, None, "/cache", False, "config.yaml")
        assert fake_st["model"] == MODEL

    def test_local_only_failure_is_not_retried(self, fake_st, monkeypatch):
        fake_st["fail_first"] = True
        monkeypatch.setattr(rerank, "_model_offline_eligible", lambda *a: True)
        with pytest.raises(OSError):
            rerank._load_cross_encoder(MODEL, None, "/cache", False, "config.yaml")


def _results(n):
    return [
        SearchResult(
            text=f"chunk {i}", score=1 / (60 + i), source=f"doc{i}.md", chunk_id=i,
            stem_tags=[], retrieval_mode="hybrid", semantic_score=0.4,
        )
        for i in range(n)
    ]


class TestRetrieveNodeReranking:
    def test_scores_only_the_context_window(self):
        from graph import LOCAL_CONTEXT_CHUNKS, retrieve_node
        retriever = MockRetriever(_results(LOCAL_CONTEXT_CHUNKS + 2), rerank=[float(i) for i in range(20)])
        out = retrieve_node({"query": "q"}, retriever, cfg={})
        (query, texts), = retriever.rerank_calls
        assert query == "q"
        assert texts == [f"chunk {i}" for i in range(LOCAL_CONTEXT_CHUNKS)]
        docs = out["retrieved_docs"]
        assert [d["rerank_score"] for d in docs[:LOCAL_CONTEXT_CHUNKS]] == [float(i) for i in range(LOCAL_CONTEXT_CHUNKS)]
        assert all("rerank_score" not in d for d in docs[LOCAL_CONTEXT_CHUNKS:])
        assert "rerank_degraded" not in out

    def test_reranker_off_attaches_nothing(self):
        from graph import retrieve_node
        out = retrieve_node({"query": "q"}, MockRetriever(_results(3)), cfg={})
        assert all("rerank_score" not in d for d in out["retrieved_docs"])
        assert "rerank_degraded" not in out

    def test_degraded_reranker_is_flagged_not_an_error(self):
        from graph import retrieve_node
        retriever = MockRetriever(_results(3), rerank=RerankerError("cross-encoder unavailable"))
        out = retrieve_node({"query": "q"}, retriever, cfg={})
        assert out["rerank_degraded"] is True
        assert "error" not in out
        assert len(out["retrieved_docs"]) == 3
        assert all("rerank_score" not in d for d in out["retrieved_docs"])

    def test_no_results_never_asks_the_reranker(self):
        from graph import retrieve_node
        retriever = MockRetriever([], rerank=[1.0])
        retrieve_node({"query": "q"}, retriever, cfg={})
        assert retriever.rerank_calls == []


class TestAuditRecordsTheVeto:
    def test_vetoed_query_records_flag_and_best_logit(self, monkeypatch):
        from graph import audit_logger_node
        monkeypatch.setattr("graph.audit_log", lambda _event: None)
        state = {
            "query": "What is the plot of the horror film The Medium?",
            "retrieved_docs": [
                {"source": "a.md", "semantic_score": 0.46, "rerank_score": -6.5},
                {"source": "b.md", "semantic_score": 0.31, "rerank_score": -2.25},
            ],
            "needs_user_confirm": True,
            "rerank_vetoed": True,
        }
        event = audit_logger_node(state, cfg={})["audit_event"]
        assert event["rerank_vetoed"] is True
        assert event["rerank_degraded"] is False
        assert event["rerank_best"] == -2.25

    def test_no_reranker_records_null_best(self, monkeypatch):
        from graph import audit_logger_node
        monkeypatch.setattr("graph.audit_log", lambda _event: None)
        event = audit_logger_node({"query": "q", "retrieved_docs": [{"source": "a.md"}]}, cfg={})["audit_event"]
        assert event["rerank_vetoed"] is False
        assert event["rerank_best"] is None

    def test_answer_sources_carry_their_logit(self, monkeypatch):
        from graph import audit_logger_node
        monkeypatch.setattr("graph.audit_log", lambda _event: None)
        state = {"query": "q", "answer_model": "local", "answer_sources": [{"source": "a.md", "rerank_score": 4.0}]}
        event = audit_logger_node(state, cfg={})["audit_event"]
        assert event["sources"][0]["rerank_score"] == 4.0


def test_hybrid_retriever_delegates_with_its_own_config(monkeypatch):
    from retrieval.hybrid_search import HybridRetriever
    seen = []
    monkeypatch.setattr(
        "retrieval.hybrid_search.rerank_scores",
        lambda query, texts, cfg, config_path: seen.append((query, list(texts), cfg, config_path)) or [0.5],
    )
    retriever = HybridRetriever.__new__(HybridRetriever)
    retriever.cfg = {"models": {}}
    retriever.config_path = "/abs/config.yaml"
    assert retriever.rerank_scores("q", ["t"]) == [0.5]
    assert seen == [("q", ["t"], {"models": {}}, "/abs/config.yaml")]
