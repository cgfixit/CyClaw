"""Unit tests for retrieval.vector_store's ChromaDB reader (_ChromaReader).

Uses a real ChromaDB PersistentClient in a tmp_path (no mocking of chromadb
itself) so these tests exercise the actual exception types the library raises,
not an assumed shape.
"""

from __future__ import annotations

import pytest

from utils.errors import IndexNotFoundError


def _cfg(chroma_path, collection_name="cyclaw_kb"):
    return {"indexing": {"chroma_path": str(chroma_path), "collection_name": collection_name}}


class TestChromaReaderMissingCollection:
    def test_missing_collection_raises_index_not_found(self, tmp_path):
        import chromadb
        from chromadb.config import Settings

        from retrieval.vector_store import get_vector_reader

        chroma_path = tmp_path / "chroma"
        # A real PersistentClient must have touched the path (chromadb creates
        # its sqlite file lazily) so _ChromaReader's Path(...).exists() check
        # passes and execution reaches the get_collection() call this test
        # targets, rather than failing earlier on a missing directory.
        chromadb.PersistentClient(path=str(chroma_path), settings=Settings(anonymized_telemetry=False))

        with pytest.raises(IndexNotFoundError, match="not found in ChromaDB"):
            get_vector_reader(_cfg(chroma_path))

    def test_unrelated_construction_error_is_not_reported_as_index_not_found(self, tmp_path, monkeypatch):
        """Narrowing the except clause to chromadb.errors.NotFoundError must not
        mask a genuinely different failure (e.g. a corrupted client) as though
        it were an ordinary missing-collection case."""
        import chromadb
        from chromadb.config import Settings

        from retrieval.vector_store import get_vector_reader

        chroma_path = tmp_path / "chroma"
        chromadb.PersistentClient(path=str(chroma_path), settings=Settings(anonymized_telemetry=False))

        def _boom(self, name):
            raise RuntimeError("simulated corrupt client state")

        # chromadb.PersistentClient is a factory function, not a class -- patch
        # the actual client class it returns.
        import chromadb.api.client

        monkeypatch.setattr(chromadb.api.client.Client, "get_collection", _boom)

        with pytest.raises(RuntimeError, match="simulated corrupt client state"):
            get_vector_reader(_cfg(chroma_path))


def _gen_cfg(tmp_path, collection_name="cyclaw_kb"):
    """A config whose bm25.json (the generation pointer) lives in tmp_path."""
    cfg = _cfg(tmp_path / "chroma", collection_name)
    cfg["indexing"]["bm25_path"] = str(tmp_path / "bm25.json")
    return cfg


def _build(cfg, rows, *, finalize=True):
    """Drive the real writer the way retrieval.indexer.build_index does; return
    the generation it wrote."""
    from retrieval.vector_store import get_vector_writer

    writer = get_vector_writer(cfg)
    writer.reset({"model": "m", "dim": "2", "device": "cpu"})
    writer.add(
        [f"chunk_{i}" for i in range(len(rows))],
        list(rows),
        [[1.0, 0.0]] * len(rows),
        [{"source": "s.md", "chunk_id": i} for i in range(len(rows))],
    )
    if finalize:
        writer.finalize()
    writer.close()
    return writer.generation


def _publish(cfg, generation):
    """What build_index's atomic bm25.json replace does for the vector leg."""
    import json
    from pathlib import Path

    Path(cfg["indexing"]["bm25_path"]).write_text(json.dumps({"vector_collection": generation}), encoding="utf-8")


def _texts(reader):
    return [hit["text"] for hit in reader.query([1.0, 0.0], 5)]


def _collections(cfg):
    import chromadb
    from chromadb.config import Settings

    client = chromadb.PersistentClient(
        path=cfg["indexing"]["chroma_path"], settings=Settings(anonymized_telemetry=False)
    )
    return {c.name for c in client.list_collections()}


class TestChromaGenerations:
    """POST /index/build rebuilds inside the serving process. Each build writes
    its own generation and bm25.json names the one it was built with, so a
    reader always queries the vectors that match its BM25 leg."""

    def test_live_reader_stays_on_its_generation_through_a_rebuild(self, tmp_path):
        from retrieval.vector_store import get_vector_reader

        cfg = _gen_cfg(tmp_path)
        old = _build(cfg, ["old"])
        _publish(cfg, old)
        live = get_vector_reader(cfg, old)

        new = _build(cfg, ["new"])
        assert new != old
        # Codex P1 on #1450: the staging swap re-pointed this reader at the new
        # vectors while its retriever still held the old BM25 leg.
        assert _texts(live) == ["old"]
        _publish(cfg, new)
        assert _texts(live) == ["old"]
        assert _texts(get_vector_reader(cfg, new)) == ["new"]

    def test_unpublished_build_never_goes_live(self, tmp_path):
        """A build that fails after its vectors are written (the BM25 write)
        leaves the previous pair live, and the next build retires the orphan."""
        from retrieval.vector_store import get_vector_reader

        cfg = _gen_cfg(tmp_path)
        live = _build(cfg, ["v1"])
        _publish(cfg, live)
        orphan = _build(cfg, ["v2"])
        assert _texts(get_vector_reader(cfg, live)) == ["v1"]

        building = _build(cfg, ["v3"], finalize=False)
        assert _collections(cfg) == {live, building}
        assert orphan not in _collections(cfg)

    def test_next_build_keeps_only_the_published_generation(self, tmp_path):
        import chromadb

        from retrieval.vector_store import get_vector_reader

        cfg = _gen_cfg(tmp_path)
        first = _build(cfg, ["v1"])
        _publish(cfg, first)
        stale_reader = get_vector_reader(cfg, first)
        second = _build(cfg, ["v2"])
        _publish(cfg, second)
        third = _build(cfg, ["v3"])
        assert _collections(cfg) == {second, third}
        # A reader on a retired generation fails loudly (hybrid_search degrades
        # it) instead of silently following another build's vectors.
        with pytest.raises(chromadb.errors.NotFoundError):
            stale_reader.query([1.0, 0.0], 5)

    def test_unreadable_bm25_keeps_every_generation(self, tmp_path):
        cfg = _gen_cfg(tmp_path)
        first = _build(cfg, ["v1"])
        _publish(cfg, first)
        (tmp_path / "bm25.json").write_text("{not json", encoding="utf-8")
        second = _build(cfg, ["v2"])
        assert _collections(cfg) == {first, second}

    def test_legacy_collections_stay_live_until_a_generation_is_published(self, tmp_path):
        import json

        import chromadb
        from chromadb.config import Settings

        from retrieval.vector_store import get_vector_reader

        cfg = _gen_cfg(tmp_path)
        client = chromadb.PersistentClient(
            path=cfg["indexing"]["chroma_path"], settings=Settings(anonymized_telemetry=False)
        )
        client.create_collection("cyclaw_kb").add(
            ids=["a"], documents=["legacy"], embeddings=[[1.0, 0.0]],
            metadatas=[{"source": "s.md", "chunk_id": 0}],
        )
        client.create_collection("cyclaw_kb_staging")
        (tmp_path / "bm25.json").write_text(json.dumps({"chunks": []}), encoding="utf-8")

        first = _build(cfg, ["v1"])
        # A bm25.json without the key was built with the fixed name, so that
        # collection is live and a reader with no name still opens it.
        assert _collections(cfg) == {"cyclaw_kb", first}
        assert _texts(get_vector_reader(cfg)) == ["legacy"]

        _publish(cfg, first)
        second = _build(cfg, ["v2"])
        assert _collections(cfg) == {first, second}

    def test_generation_carries_the_fingerprint(self, tmp_path):
        from retrieval.vector_store import get_vector_reader

        cfg = _gen_cfg(tmp_path)
        generation = _build(cfg, ["only"])
        assert get_vector_reader(cfg, generation).fingerprint() == {"model": "m", "dim": "2", "device": "cpu"}

    def test_longest_valid_collection_name_still_builds(self, tmp_path):
        """Codex P2 on #1450: a 505-512 char name is valid, and a fixed suffix
        pushed the build collection past Chroma's 512-char limit."""
        from retrieval.vector_store import get_vector_reader

        cfg = _gen_cfg(tmp_path, collection_name="k" * 512)
        first = _build(cfg, ["v1"])
        assert len(first) <= 512
        _publish(cfg, first)
        second = _build(cfg, ["v2"])
        assert _collections(cfg) == {first, second}
        assert _texts(get_vector_reader(cfg, second)) == ["v2"]


def test_failed_bm25_write_keeps_both_legs_on_one_build(test_config, tmp_path):
    """Codex P1 on #1450, end to end: a rebuild that fails after its vectors
    are written (the BM25 write) must not leave a retriever, serving or fresh,
    fusing the new vectors with the old BM25 leg."""
    import json
    from pathlib import Path
    from unittest.mock import patch

    from retrieval.hybrid_search import HybridRetriever
    from retrieval.indexer import build_index

    cfg, config_path = test_config
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    cfg["corpus"]["path"] = str(corpus)
    Path(config_path).write_text(json.dumps(cfg), encoding="utf-8")
    doc = corpus / "a.md"

    embed = patch("retrieval.indexer.get_embeddings_batch", side_effect=lambda chunks, _p: [[1.0, 0.0]] * len(chunks))
    query = patch("retrieval.hybrid_search.get_embedding", return_value=[1.0, 0.0])
    with embed, query:
        doc.write_text("alpha old", encoding="utf-8")
        build_index(config_path)
        serving = HybridRetriever(config_path)

        doc.write_text("alpha new", encoding="utf-8")
        with (
            patch("retrieval.indexer.os.replace", side_effect=OSError("disk full")),
            pytest.raises(OSError, match="disk full"),
        ):
            build_index(config_path)

        assert [h.text for h in serving.semantic_search("alpha")] == ["alpha old"]
        assert [h.text for h in HybridRetriever(config_path).semantic_search("alpha")] == ["alpha old"]
