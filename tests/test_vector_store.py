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


def _build(cfg, rows, *, finalize=True):
    """Drive the real writer the way retrieval.indexer.build_index does."""
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


def _texts(reader):
    return [hit["text"] for hit in reader.query([1.0, 0.0], 5)]


class TestChromaWriterHotRebuild:
    """POST /index/build rebuilds inside the serving process, so the reader a
    live /query holds must keep answering until gate.py swaps in a new one."""

    def test_live_reader_keeps_serving_through_a_rebuild(self, tmp_path):
        from retrieval.vector_store import get_vector_reader

        cfg = _cfg(tmp_path / "chroma")
        _build(cfg, ["old"])
        live = get_vector_reader(cfg)

        # Before the fix, reset() deleted the live collection here and this
        # query raised chromadb NotFoundError for the rest of the build.
        _build(cfg, ["new"], finalize=False)
        assert _texts(live) == ["old"]

        # After the swap the old collection is gone; the serving reader
        # re-resolves by name and follows the build.
        _build(cfg, ["new"])
        assert _texts(live) == ["new"]
        assert _texts(get_vector_reader(cfg)) == ["new"]

    def test_reader_survives_builds_that_fail_after_finalize(self, tmp_path):
        """Codex P1 on #1450: a build can fail after finalize() (the BM25
        write), so gate.py never swaps readers and the serving one stays on
        the old collection. A later build must not strand it there."""
        from retrieval.vector_store import get_vector_reader

        cfg = _cfg(tmp_path / "chroma")
        _build(cfg, ["v1"])
        serving = get_vector_reader(cfg)
        _build(cfg, ["v2"])  # finalized, but the server never swapped
        _build(cfg, ["v3"])
        assert _texts(serving) == ["v3"]

    def test_swap_leaves_only_the_live_collection(self, tmp_path):
        import chromadb
        from chromadb.config import Settings

        cfg = _cfg(tmp_path / "chroma")
        _build(cfg, ["v1"])
        _build(cfg, ["v2"])
        client = chromadb.PersistentClient(
            path=str(tmp_path / "chroma"), settings=Settings(anonymized_telemetry=False)
        )
        assert [c.name for c in client.list_collections()] == ["cyclaw_kb"]

    def test_swap_carries_the_fingerprint_to_the_live_name(self, tmp_path):
        from retrieval.vector_store import get_vector_reader

        cfg = _cfg(tmp_path / "chroma")
        _build(cfg, ["only"])
        assert get_vector_reader(cfg).fingerprint() == {"model": "m", "dim": "2", "device": "cpu"}

    def test_failed_build_leaves_live_untouched_and_next_build_recovers(self, tmp_path):
        from retrieval.vector_store import get_vector_reader

        cfg = _cfg(tmp_path / "chroma")
        _build(cfg, ["v1"])
        _build(cfg, ["abandoned"], finalize=False)
        assert _texts(get_vector_reader(cfg)) == ["v1"]

        _build(cfg, ["v2"])
        _build(cfg, ["v3"])
        assert _texts(get_vector_reader(cfg)) == ["v3"]
