"""Unit tests for retrieval/embeddings.py — the query-embedding cache layer.

embeddings.py had no dedicated test; it was only exercised indirectly via
test_indexer.py mocking ``get_embeddings_batch``. The memoization that the
module docstring calls out as the retrieval hot-path optimization
(``_cached_embedding`` lru_cache + ``reset_embedding_cache``) had no regression
test proving a repeat query is a cache hit. The heavy SentenceTransformer load
(``_load_model``) is mocked, so no model download is required.
"""

import os
import sys

import pytest
import yaml

from retrieval import embeddings


def _write_cfg(tmp_path, model="test-model", cache_dir="", offline_after_index=False):
    cfg = {
        "models": {"embeddings": {"model": model, "cache_dir": cache_dir, "offline_after_index": offline_after_index}},
        "indexing": {"chroma_path": "index/chroma_db", "bm25_path": "index/bm25.json"},
    }
    p = tmp_path / "config.yaml"
    with open(p, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f)
    return str(p)


class _Arr:
    """Minimal stand-in for the numpy array returned by SentenceTransformer.encode."""

    def __init__(self, data):
        self._data = data

    def tolist(self):
        return self._data


class _FakeModel:
    def __init__(self):
        self.calls = 0

    def encode(self, text, normalize_embeddings=True, show_progress_bar=False):
        self.calls += 1
        if isinstance(text, list):
            return _Arr([[float(len(t)), 0.5] for t in text])
        return _Arr([float(len(text)), 0.5])


@pytest.fixture(autouse=True)
def _reset_caches():
    embeddings._cached_embedding.cache_clear()
    embeddings._embeddings_cfg.cache_clear()
    yield
    embeddings._cached_embedding.cache_clear()
    embeddings._embeddings_cfg.cache_clear()


@pytest.fixture
def fake_model(monkeypatch):
    model = _FakeModel()
    monkeypatch.setattr(embeddings, "_load_model", lambda name, cache, offline_after_index, config_path: model)
    return model


class TestGetEmbedding:
    def test_returns_plain_list(self, tmp_path, fake_model):
        cfg_path = _write_cfg(tmp_path)
        out = embeddings.get_embedding("hello", cfg_path)
        assert isinstance(out, list)
        assert out == [5.0, 0.5]  # len("hello") == 5

    def test_repeat_query_is_a_cache_hit(self, tmp_path, fake_model):
        cfg_path = _write_cfg(tmp_path)
        embeddings.get_embedding("same query", cfg_path)
        embeddings.get_embedding("same query", cfg_path)
        # Second identical call served from the lru_cache -> model ran only once.
        assert fake_model.calls == 1

    def test_distinct_queries_each_encode(self, tmp_path, fake_model):
        cfg_path = _write_cfg(tmp_path)
        embeddings.get_embedding("query one", cfg_path)
        embeddings.get_embedding("query two", cfg_path)
        assert fake_model.calls == 2


class TestResetCache:
    def test_reset_forces_recompute(self, tmp_path, fake_model):
        cfg_path = _write_cfg(tmp_path)
        embeddings.get_embedding("q", cfg_path)
        assert fake_model.calls == 1
        embeddings.reset_embedding_cache()
        embeddings.get_embedding("q", cfg_path)
        # After a cache clear the same query must re-run the model.
        assert fake_model.calls == 2

    def test_reset_clears_config_and_query_caches(self, tmp_path, fake_model):
        # Populate both the query memo and the per-path config cache.
        cfg_path = _write_cfg(tmp_path)
        embeddings.get_embedding("hello", cfg_path)
        assert embeddings._cached_embedding.cache_info().currsize > 0
        assert embeddings._embeddings_cfg.cache_info().currsize > 0
        embeddings.reset_embedding_cache()
        # ALL caches must be empty — not just the query memo.
        assert embeddings._cached_embedding.cache_info().currsize == 0
        assert embeddings._embeddings_cfg.cache_info().currsize == 0

    def test_reset_picks_up_swapped_model(self, tmp_path):
        # A model swap rewrites models.embeddings in the SAME config path.
        cfg_path = _write_cfg(tmp_path, model="model-a")
        assert embeddings._embeddings_cfg(cfg_path)[0] == "model-a"
        _write_cfg(tmp_path, model="model-b")
        # Still stale until the caches are reset (the bug this fix closes:
        # clearing only _cached_embedding left _embeddings_cfg serving model-a).
        assert embeddings._embeddings_cfg(cfg_path)[0] == "model-a"
        embeddings.reset_embedding_cache()
        assert embeddings._embeddings_cfg(cfg_path)[0] == "model-b"


class TestEmbeddingsCfg:
    def test_reads_model_and_cache_dir(self, tmp_path):
        cfg_path = _write_cfg(tmp_path, model="my-model", cache_dir="/tmp/cache")
        assert embeddings._embeddings_cfg(cfg_path) == ("my-model", "/tmp/cache", False)

    def test_relative_cache_dir_resolves_from_config_dir(self, tmp_path):
        cfg_path = _write_cfg(tmp_path, model="my-model", cache_dir=".emb_cache")
        assert embeddings._embeddings_cfg(cfg_path) == (
            "my-model",
            str((tmp_path / ".emb_cache").resolve()),
            False,
        )

    def test_reads_offline_after_index_flag(self, tmp_path):
        cfg_path = _write_cfg(tmp_path, model="my-model", offline_after_index=True)
        assert embeddings._embeddings_cfg(cfg_path) == ("my-model", "", True)

    def test_quoted_string_false_does_not_enable_flag(self, tmp_path):
        # A quoted "false" is an easy typo and parses to the Python string
        # "false" -- bool("false") is True, which would enable the opt-in
        # exactly backwards (caught in review). Only the literal boolean
        # true may enable it.
        p = tmp_path / "config.yaml"
        with open(p, "w", encoding="utf-8") as f:
            f.write('models:\n  embeddings:\n    model: my-model\n    offline_after_index: "false"\n')
        assert embeddings._embeddings_cfg(str(p)) == ("my-model", "", False)

    def test_cfg_cached_per_path(self, tmp_path):
        cfg_path = _write_cfg(tmp_path)
        first = embeddings._embeddings_cfg(cfg_path)
        second = embeddings._embeddings_cfg(cfg_path)
        assert first is second  # served from the per-path cache


class TestBatch:
    def test_batch_encodes_all_texts(self, tmp_path, fake_model):
        cfg_path = _write_cfg(tmp_path)
        out = embeddings.get_embeddings_batch(["a", "bb", "ccc"], cfg_path)
        assert out == [[1.0, 0.5], [2.0, 0.5], [3.0, 0.5]]
        assert fake_model.calls == 1  # one batched encode call


class TestQueryCacheSize:
    def test_defaults_to_2048_when_unset(self, monkeypatch):
        monkeypatch.delenv("CYCLAW_EMBED_CACHE_SIZE", raising=False)
        assert embeddings._default_query_cache_size() == 2048

    def test_reads_positive_int_from_env(self, monkeypatch):
        monkeypatch.setenv("CYCLAW_EMBED_CACHE_SIZE", "512")
        assert embeddings._default_query_cache_size() == 512

    def test_falls_back_on_non_positive_value(self, monkeypatch):
        monkeypatch.setenv("CYCLAW_EMBED_CACHE_SIZE", "0")
        assert embeddings._default_query_cache_size() == 2048
        monkeypatch.setenv("CYCLAW_EMBED_CACHE_SIZE", "-5")
        assert embeddings._default_query_cache_size() == 2048

    def test_falls_back_on_non_numeric_value(self, monkeypatch):
        monkeypatch.setenv("CYCLAW_EMBED_CACHE_SIZE", "not-a-number")
        assert embeddings._default_query_cache_size() == 2048


class TestEmbeddingFailureWrapping:
    """A model failure on the query path must surface as EmbeddingServiceError.

    hybrid_search.hybrid_search() catches exactly EmbeddingServiceError around
    the semantic leg to degrade to keyword-only; before the wrap in
    _cached_embedding, raw ImportError/OSError/RuntimeError escaped that catch
    and crashed the request instead of degrading.
    """

    def test_model_failure_raises_embedding_service_error(self, tmp_path, monkeypatch):
        from utils.errors import EmbeddingServiceError

        cfg_path = _write_cfg(tmp_path)

        def _boom(name, cache, offline_after_index, config_path):
            raise RuntimeError("model exploded")

        monkeypatch.setattr(embeddings, "_load_model", _boom)
        with pytest.raises(EmbeddingServiceError) as exc_info:
            embeddings.get_embedding("query text", cfg_path)
        assert exc_info.value.code == "EMBEDDING_ERROR"
        assert exc_info.value.details["error_type"] == "RuntimeError"

    def test_failure_is_not_cached(self, tmp_path, monkeypatch):
        # lru_cache does not memoize exceptions -- a transient failure must be
        # retried, not poison the cache for that query text forever.
        from utils.errors import EmbeddingServiceError

        cfg_path = _write_cfg(tmp_path)

        def _boom(name, cache, offline_after_index, config_path):
            raise OSError("cache_dir unreadable")

        monkeypatch.setattr(embeddings, "_load_model", _boom)
        with pytest.raises(EmbeddingServiceError):
            embeddings.get_embedding("same query", cfg_path)

        model = _FakeModel()
        monkeypatch.setattr(embeddings, "_load_model", lambda name, cache, offline_after_index, config_path: model)
        result = embeddings.get_embedding("same query", cfg_path)
        assert result == [float(len("same query")), 0.5]
        assert model.calls == 1


class TestOfflineEligibility:
    """_model_offline_eligible + _load_model's conditional HF_HUB_OFFLINE set.

    Real _load_model is exercised here (not mocked wholesale like the tests
    above), with `sentence_transformers` itself replaced via sys.modules so no
    heavy/network-dependent import is required. _load_model is lru_cache'd, so
    each test clears it to avoid a stale hit from a previous test's args.
    """

    @pytest.fixture(autouse=True)
    def _clear_load_model_cache(self):
        embeddings._load_model.cache_clear()
        yield
        embeddings._load_model.cache_clear()

    @pytest.fixture(autouse=True)
    def _clean_offline_env(self, monkeypatch):
        # Isolate from any ambient/leftover HF_HUB_OFFLINE / TRANSFORMERS_OFFLINE
        # so assertions on "was it set" are never polluted by outside state.
        monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
        monkeypatch.delenv("TRANSFORMERS_OFFLINE", raising=False)

    def test_not_cached_when_probe_returns_none(self, monkeypatch):
        monkeypatch.setattr(
            "huggingface_hub.try_to_load_from_cache", lambda **kw: None
        )
        assert embeddings._model_offline_eligible("some/model", "") is False

    def test_cached_when_probe_returns_a_path(self, monkeypatch):
        monkeypatch.setattr(
            "huggingface_hub.try_to_load_from_cache", lambda **kw: "/cache/config.json"
        )
        assert embeddings._model_offline_eligible("some/model", "") is True

    def test_not_cached_when_probe_returns_the_negative_cache_sentinel(self, monkeypatch):
        # huggingface_hub's own "we already asked and it doesn't exist" marker --
        # a non-None, non-str return that must NOT be treated as a real hit.
        sentinel = object()
        monkeypatch.setattr(
            "huggingface_hub.try_to_load_from_cache", lambda **kw: sentinel
        )
        assert embeddings._model_offline_eligible("some/model", "") is False

    def test_not_cached_when_probe_raises(self, monkeypatch):
        def _boom(**kw):
            raise OSError("cache index unreadable")

        monkeypatch.setattr("huggingface_hub.try_to_load_from_cache", _boom)
        assert embeddings._model_offline_eligible("some/model", "") is False

    def test_not_cached_when_huggingface_hub_unimportable(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "huggingface_hub", None)
        assert embeddings._model_offline_eligible("some/model", "") is False

    def test_load_model_sets_offline_env_when_cached(self, monkeypatch):
        monkeypatch.setattr(embeddings, "_model_offline_eligible", lambda name, cache: True)
        monkeypatch.setitem(
            sys.modules, "sentence_transformers",
            type("_Mod", (), {"SentenceTransformer": lambda *a, **kw: _FakeModel()})(),
        )
        embeddings._load_model("cached-model", "", False, "")
        assert os.environ.get("HF_HUB_OFFLINE") == "1"
        assert os.environ.get("TRANSFORMERS_OFFLINE") == "1"

    def test_load_model_leaves_offline_env_untouched_when_not_cached(self, monkeypatch):
        monkeypatch.setattr(embeddings, "_model_offline_eligible", lambda name, cache: False)
        monkeypatch.setitem(
            sys.modules, "sentence_transformers",
            type("_Mod", (), {"SentenceTransformer": lambda *a, **kw: _FakeModel()})(),
        )
        embeddings._load_model("fresh-model", "", False, "")
        assert "HF_HUB_OFFLINE" not in os.environ
        assert "TRANSFORMERS_OFFLINE" not in os.environ

    def test_load_model_never_clears_an_operators_own_stricter_choice(self, monkeypatch):
        # An operator who already sourced cyclaw_telemetry_kill.env by hand has
        # made an explicit, stricter choice. A cold-cache probe result must not
        # override it.
        monkeypatch.setenv("HF_HUB_OFFLINE", "1")
        monkeypatch.setattr(embeddings, "_model_offline_eligible", lambda name, cache: False)
        monkeypatch.setitem(
            sys.modules, "sentence_transformers",
            type("_Mod", (), {"SentenceTransformer": lambda *a, **kw: _FakeModel()})(),
        )
        embeddings._load_model("some-model", "", False, "")
        assert os.environ.get("HF_HUB_OFFLINE") == "1"

    def test_load_model_passes_local_files_only_true_when_cached(self, monkeypatch):
        # This is what actually enforces offline behavior IN this process --
        # the env vars alone do not, because _model_offline_eligible's own
        # `from huggingface_hub import try_to_load_from_cache` has already
        # forced huggingface_hub's import (latching its HF_HUB_OFFLINE
        # constant to whatever the environment said BEFORE this call), so
        # setting os.environ two lines later is too late for that constant.
        # local_files_only is passed straight through to huggingface_hub's
        # download path, which gates independently of that already-latched
        # global. Regression test for the bug this fixes: asserting the env
        # var is set (the tests above) is not enough -- it must be asserted
        # that the thing which actually takes effect receives the right value.
        captured = {}

        def _fake_ctor(*args, **kwargs):
            captured.update(kwargs)
            return _FakeModel()

        monkeypatch.setattr(embeddings, "_model_offline_eligible", lambda name, cache: True)
        monkeypatch.setitem(
            sys.modules, "sentence_transformers",
            type("_Mod", (), {"SentenceTransformer": _fake_ctor})(),
        )
        embeddings._load_model("cached-model", "", False, "")
        assert captured.get("local_files_only") is True

    def test_load_model_passes_local_files_only_false_when_not_cached(self, monkeypatch):
        # A cold cache must still be allowed to fetch -- local_files_only=True
        # here would turn the documented first-run bootstrap fetch into a
        # guaranteed LocalEntryNotFoundError.
        captured = {}

        def _fake_ctor(*args, **kwargs):
            captured.update(kwargs)
            return _FakeModel()

        monkeypatch.setattr(embeddings, "_model_offline_eligible", lambda name, cache: False)
        monkeypatch.setitem(
            sys.modules, "sentence_transformers",
            type("_Mod", (), {"SentenceTransformer": _fake_ctor})(),
        )
        embeddings._load_model("fresh-model", "", False, "")
        assert captured.get("local_files_only") is False

    def test_load_model_passes_embed_device(self, monkeypatch):
        # This is the actual fix: sentence-transformers auto-selects a device
        # (cuda -> mps -> ... -> cpu) whenever device= is omitted, which is what
        # made macOS/Apple-Silicon retrieval rank differently than Linux/Windows
        # (PR #734). Asserting the constructor kwarg -- not just that EMBED_DEVICE
        # == "cpu" -- is what would have caught a call site that forgot to pass it.
        captured = {}

        def _fake_ctor(*args, **kwargs):
            captured.update(kwargs)
            return _FakeModel()

        monkeypatch.setattr(embeddings, "_model_offline_eligible", lambda name, cache: False)
        monkeypatch.setitem(
            sys.modules, "sentence_transformers",
            type("_Mod", (), {"SentenceTransformer": _fake_ctor})(),
        )
        embeddings._load_model("some-model", "", False, "")
        assert captured.get("device") == embeddings.EMBED_DEVICE == "cpu"


class TestIndexOrBm25Present:
    """_index_or_bm25_present -- backs offline_after_index (#1255 Phase B).

    Checks the BM25 sidecar file only, not the Chroma directory -- see the
    function's own docstring for why a bare Chroma directory is NOT a valid
    "index present" signal (retrieval.indexer.build_index()'s
    _ChromaWriter.reset() mkdir()s it before any embedding is ever fetched,
    which was a real bug: an empty, just-created directory used to read as
    "present").
    """

    def test_false_when_neither_present(self, tmp_path):
        cfg_path = _write_cfg(tmp_path)
        assert embeddings._index_or_bm25_present(cfg_path) is False

    def test_false_when_only_chroma_dir_present(self, tmp_path):
        # Reproduces the exact ordering bug (caught in review): build_index()
        # calls writer.reset() -- which mkdir()s chroma_path -- BEFORE the
        # batch loop that fetches any embedding. A bare, empty chroma_db
        # directory must NOT read as "an index already exists," or a
        # machine's first-ever build would be wrongly forced offline the
        # moment reset() ran, before the embedding model was ever cached.
        cfg_path = _write_cfg(tmp_path)
        (tmp_path / "index" / "chroma_db").mkdir(parents=True)
        assert embeddings._index_or_bm25_present(cfg_path) is False

    def test_true_when_bm25_file_present(self, tmp_path):
        # The BM25 file is written LAST in build_index() (atomic os.replace,
        # after every embedding batch has already been fetched/generated),
        # so its presence is the one artifact that reliably means "a full
        # index build already completed."
        cfg_path = _write_cfg(tmp_path)
        (tmp_path / "index").mkdir()
        (tmp_path / "index" / "bm25.json").write_text("{}", encoding="utf-8")
        assert embeddings._index_or_bm25_present(cfg_path) is True

    def test_false_on_unreadable_config(self, tmp_path):
        # Ambiguity (missing/unparseable config) must resolve to False, the
        # same fail-safe direction _model_offline_eligible takes.
        assert embeddings._index_or_bm25_present(str(tmp_path / "does-not-exist.yaml")) is False

    def test_false_when_indexing_section_missing(self, tmp_path):
        p = tmp_path / "config.yaml"
        with open(p, "w", encoding="utf-8") as f:
            yaml.dump({"models": {"embeddings": {"model": "m"}}}, f)
        assert embeddings._index_or_bm25_present(str(p)) is False


class TestOfflineAfterIndex:
    """offline_after_index (#1255 Phase B) -- acceptance criteria:

    - a fresh machine with neither an index nor a cached model still
      bootstraps normally (local_files_only=False) regardless of the flag
    - with an existing (COMPLETED) index AND the flag on, a cold HF-cache
      probe still forces local_files_only=True (no HF egress)
    - a build in progress -- writer.reset() has run (mkdir'd chroma_path)
      but no embedding batch has completed yet -- must NOT be mistaken for
      a completed index (the ordering bug caught in review; see
      test_index_build_in_progress_does_not_force_offline below)
    """

    @pytest.fixture(autouse=True)
    def _clear_load_model_cache(self):
        embeddings._load_model.cache_clear()
        yield
        embeddings._load_model.cache_clear()

    @pytest.fixture(autouse=True)
    def _clean_offline_env(self, monkeypatch):
        # _load_model sets these directly via os.environ[...] = "1" (not via
        # monkeypatch), so without this, a real assignment during one test
        # leaks into every later test/subprocess in the same session (caught
        # in review) -- mirrors TestOfflineEligibility's identical fixture.
        # monkeypatch.delenv restores both back to their pre-test state
        # (unset) at teardown regardless of what _load_model set them to.
        monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
        monkeypatch.delenv("TRANSFORMERS_OFFLINE", raising=False)

    def _install_fake_sentence_transformers(self, monkeypatch):
        captured = {}

        def _fake_ctor(*args, **kwargs):
            captured.update(kwargs)
            return _FakeModel()

        monkeypatch.setitem(
            sys.modules, "sentence_transformers",
            type("_Mod", (), {"SentenceTransformer": _fake_ctor})(),
        )
        return captured

    def _write_completed_index(self, tmp_path):
        # The one filesystem state that actually means "a full index build
        # already completed" -- see _index_or_bm25_present's docstring.
        (tmp_path / "index").mkdir(parents=True, exist_ok=True)
        (tmp_path / "index" / "bm25.json").write_text("{}", encoding="utf-8")

    def test_fresh_machine_no_index_flag_off_still_bootstraps(self, monkeypatch, tmp_path):
        cfg_path = _write_cfg(tmp_path, offline_after_index=False)
        monkeypatch.setattr(embeddings, "_model_offline_eligible", lambda name, cache: False)
        captured = self._install_fake_sentence_transformers(monkeypatch)
        embeddings._load_model("some-model", "", False, cfg_path)
        assert captured.get("local_files_only") is False

    def test_fresh_machine_no_index_flag_on_still_bootstraps(self, monkeypatch, tmp_path):
        # The flag alone is not enough -- an index must actually exist, or a
        # genuinely fresh machine would be wrongly forced offline.
        cfg_path = _write_cfg(tmp_path, offline_after_index=True)
        monkeypatch.setattr(embeddings, "_model_offline_eligible", lambda name, cache: False)
        captured = self._install_fake_sentence_transformers(monkeypatch)
        embeddings._load_model("some-model", "", True, cfg_path)
        assert captured.get("local_files_only") is False

    def test_index_build_in_progress_does_not_force_offline(self, monkeypatch, tmp_path):
        # Reproduces the exact ordering bug (caught in review):
        # retrieval.indexer.build_index() calls _ChromaWriter.reset() -- which
        # mkdir()s chroma_path -- BEFORE the batch loop that calls
        # get_embeddings_batch() (and therefore _load_model) even once. A
        # bare, freshly-created chroma_db directory with no bm25.json yet
        # must NOT read as "an index exists," or a machine's first-ever
        # build would be wrongly forced offline mid-build, before the
        # embedding model was ever cached.
        cfg_path = _write_cfg(tmp_path, offline_after_index=True)
        (tmp_path / "index" / "chroma_db").mkdir(parents=True)  # writer.reset()'s side effect
        monkeypatch.setattr(embeddings, "_model_offline_eligible", lambda name, cache: False)
        captured = self._install_fake_sentence_transformers(monkeypatch)
        embeddings._load_model("some-model", "", True, cfg_path)
        assert captured.get("local_files_only") is False

    def test_index_present_flag_on_cold_probe_forces_offline(self, monkeypatch, tmp_path):
        cfg_path = _write_cfg(tmp_path, offline_after_index=True)
        self._write_completed_index(tmp_path)
        # Cold HF-cache probe (model not yet fetched) must still be overridden
        # by the on-disk index -- this is the whole point of the flag.
        monkeypatch.setattr(embeddings, "_model_offline_eligible", lambda name, cache: False)
        captured = self._install_fake_sentence_transformers(monkeypatch)
        embeddings._load_model("some-model", "", True, cfg_path)
        assert captured.get("local_files_only") is True

    def test_index_present_flag_off_cold_probe_stays_online(self, monkeypatch, tmp_path):
        # The flag itself is opt-in (ships false) -- an index on disk must not
        # silently change behavior when the operator never enabled it.
        cfg_path = _write_cfg(tmp_path, offline_after_index=False)
        self._write_completed_index(tmp_path)
        monkeypatch.setattr(embeddings, "_model_offline_eligible", lambda name, cache: False)
        captured = self._install_fake_sentence_transformers(monkeypatch)
        embeddings._load_model("some-model", "", False, cfg_path)
        assert captured.get("local_files_only") is False


class TestEmbeddingFingerprint:
    """embedding_fingerprint() stamps a freshly built index so a stale/mismatched
    index (e.g. one built before EMBED_DEVICE existed) can be detected at query
    time -- see retrieval/hybrid_search.py's HybridRetriever._check_embedding_fingerprint.
    """

    def test_stamps_model_dim_and_device_as_strings(self):
        fp = embeddings.embedding_fingerprint({"model": "all-MiniLM-L6-v2", "dim": 384})
        assert fp == {"model": "all-MiniLM-L6-v2", "dim": "384", "device": "cpu"}

    def test_missing_keys_default_to_empty_string(self):
        fp = embeddings.embedding_fingerprint({})
        assert fp == {"model": "", "dim": "", "device": "cpu"}
