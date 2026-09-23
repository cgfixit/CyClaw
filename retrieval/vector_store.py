"""Pluggable vector-store backends for CyClaw semantic retrieval.

Default backend is **ChromaDB** (``PersistentClient``, embedded, zero-config,
offline-first) — unchanged behavior. Set ``indexing.vector_backend: "pgvector"``
(plus a Postgres DSN via ``indexing.database_url`` / ``CYCLAW_VECTOR_DB_URL`` /
``CYCLAW_DB_URL``) to store and query the 384-dim embeddings in PostgreSQL via the
``pgvector`` extension instead.

This module isolates the *only* part of retrieval that differs between backends:
the semantic add (indexer) and the semantic query (hybrid_search). The RRF fusion
and the BM25 keyword leg in ``hybrid_search.py`` are backend-agnostic and untouched
— a pgvector deployment fuses and ranks identically to a ChromaDB one.

Trade-off: ChromaDB is a local file needing no server (keeps CyClaw offline-first);
pgvector requires a running Postgres. Only choose pgvector as a deliberate
"consolidate on Postgres" move. ``psycopg`` / ``pgvector`` are lazy-imported, so a
default (ChromaDB) install never loads them.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import uuid
from pathlib import Path
from typing import Any

from utils.errors import IndexNotFoundError
from utils.onnx_telemetry import suppress_onnx_telemetry
from utils.telemetry_kill import apply_telemetry_kill

# Applied at import, not at client construction, because this module is the ONLY
# production path that reaches ChromaDB -- both `import chromadb` statements below
# are lazy (inside _ChromaWriter.reset and _ChromaReader.__init__), so a module-level
# apply is guaranteed to run first. That covers every entry point in one place:
# gate.py (which also applies it directly), mcp_hybrid_server.py, and
# `python -m retrieval.indexer`, which reaches ChromaDB only through here.
#
# ChromaDB reads its OTel settings from the process environment via
# pydantic-settings, so an ambient CHROMA_OTEL_GRANULARITY would otherwise be
# honored on the two paths that never import gate. Settings(anonymized_telemetry=
# False) at the call sites below does not cover this -- that flag governs the
# separate PostHog product-telemetry path.
apply_telemetry_kill()

logger = logging.getLogger(__name__)


def parse_stem_tags(raw: object) -> list[str]:
    """Safely parse stem_tags from index metadata.

    Metadata may store stem_tags as a JSON string (indexer default), a list
    (pgvector JSONB columns), or a corrupted/truncated value after a partial
    write. A bare ``json.loads`` would crash the entire retrieval path on
    malformed data; returning ``[]`` lets the query complete with degraded
    stem metadata rather than an HTTP 500.
    """
    if isinstance(raw, list):
        return list(raw)
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else []
    except (json.JSONDecodeError, TypeError):
        logger.warning("Malformed stem_tags metadata, falling back to []: %r", raw)
        return []


# all-MiniLM-L6-v2 embedding width (config: models.embeddings.dim).
_DEFAULT_EMBED_DIM = 384
# Every build writes a fresh vector generation (a Chroma collection or a pgvector
# table) and bm25.json records its name, so a HybridRetriever always queries the
# vectors that were built with its BM25 leg. _PG_TABLE is the legacy fixed name
# (and _staging the #1450-era build table); generations are kb_chunks_g<12 hex>.
# Any table name is checked against _PG_NAME_RE before it reaches SQL, so an
# identifier can only ever be one of these code-generated shapes.
_PG_TABLE = "kb_chunks"
_PG_NAME_RE = re.compile(r"kb_chunks(?:_staging|_g[0-9a-f]{12})?")
# Chroma collection names are 3-512 chars of [a-zA-Z0-9._-] (chromadb 1.5.9).
_CHROMA_NAME_MAX = 512
_GEN_TAG = "__gen_"
_GEN_TOKEN_LEN = 12

# The keys retrieval.embeddings.embedding_fingerprint() stamps into a freshly
# built index's metadata, and _ChromaReader.fingerprint() reads back. Shared
# here (not re-derived) so writer and reader agree on the exact key set.
_FINGERPRINT_KEYS = ("model", "dim", "device")


def vector_backend(cfg: dict) -> str:
    """Return the configured vector backend ("chroma" default, or "pgvector")."""
    return ((cfg.get("indexing") or {}).get("vector_backend") or "chroma").lower()


def _generation_token() -> str:
    return uuid.uuid4().hex[:_GEN_TOKEN_LEN]


def _chroma_generation_prefix(name: str) -> str:
    """The configured collection name, shortened only if a generation suffix
    would push it past Chroma's limit. A shortened name keeps its head plus a
    hash of the whole, so two long names sharing a head stay distinct."""
    room = _CHROMA_NAME_MAX - len(_GEN_TAG) - _GEN_TOKEN_LEN
    if len(name) <= room:
        return name
    digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:8]
    return f"{name[:room - len(digest) - 1]}-{digest}"


def _live_names(cfg: dict, legacy_name: str) -> set[str] | None:
    """Vector generations a new build must not delete, or None if unknown.

    The live generation is the one the on-disk bm25.json was built with: its
    ``vector_collection`` key, or the legacy fixed name for a bm25.json from
    before generations existed. No bm25.json means nothing is live. A file
    that exists but cannot be parsed returns None, and the caller then deletes
    nothing rather than guess which generation a running server still uses.
    """
    path = Path((cfg.get("indexing") or {}).get("bm25_path") or "")
    if not path.is_file():
        return set()
    try:
        with open(path, encoding="utf-8") as f:  # DevSkim: ignore DS161085 - project-generated index
            data = json.load(f)
    except (OSError, ValueError):
        return None
    name = data.get("vector_collection") if isinstance(data, dict) else None
    return {name if isinstance(name, str) and name else legacy_name}


def _pg_dsn(cfg: dict) -> str:
    """Resolve the pgvector DSN: dedicated env → indexing.database_url → CYCLAW_DB_URL."""
    return (
        os.environ.get("CYCLAW_VECTOR_DB_URL")
        or (cfg.get("indexing") or {}).get("database_url")
        or os.environ.get("CYCLAW_DB_URL")
        or ""
    )


def _embed_dim(cfg: dict) -> int:
    return int(((cfg.get("models") or {}).get("embeddings") or {}).get("dim") or _DEFAULT_EMBED_DIM)


# ============================================================ ChromaDB (default)
class _ChromaWriter:
    """Wraps the ChromaDB build path (PersistentClient + collection.add).

    Each build writes a new ``<name>__gen_<12 hex>`` collection and never
    renames or deletes the one being served. The indexer records the new name
    in bm25.json (an atomic replace), and a HybridRetriever opens the
    generation its bm25.json names, so its two legs always come from the same
    build. POST /index/build runs this inside the serving process, where the
    #1450 staging swap re-pointed a live reader at the new vectors while it
    still held the old BM25, fusing unrelated chunks that happened to share a
    (source, chunk_id). Stale generations are deleted when the next build
    starts, except the one bm25.json names.
    """

    def __init__(self, cfg: dict):
        self._cfg = cfg
        self._chroma_path = cfg["indexing"]["chroma_path"]
        self._collection_name = cfg["indexing"]["collection_name"]
        self._prefix = _chroma_generation_prefix(self._collection_name)
        self._client = None
        self._collection = None
        self.generation: str | None = None

    def reset(self, fingerprint: dict[str, str] | None = None) -> None:
        import chromadb
        from chromadb.config import Settings

        # If chromadb's import pulled onnxruntime in (its default embedding
        # function is ONNX-backed), disable the post-import event stream before
        # any collection work. No force_import: CyClaw always passes
        # precomputed vectors, so ONNX may legitimately never load here -- the
        # ORT_DISABLE_TELEMETRY env var from the kill block above covers a
        # later lazy import.
        suppress_onnx_telemetry()
        Path(self._chroma_path).mkdir(parents=True, exist_ok=True)
        # Pin checked at gate boot by utils.telemetry_kill.verify_telemetry_contract.
        self._client = chromadb.PersistentClient(
            path=self._chroma_path, settings=Settings(anonymized_telemetry=False)
        )
        self._discard_stale(_live_names(self._cfg, self._collection_name))
        # Cosine space: embeddings are L2-normalized, so `1 - distance` is genuine
        # cosine similarity (matches hybrid_search's score). See indexer comment.
        # `fingerprint` (model/dim/device, from embeddings.embedding_fingerprint())
        # rides in the same flat metadata dict -- ChromaDB collection metadata has
        # no separate slot, and HybridRetriever reads it back via .fingerprint()
        # to detect a stale/mismatched index at query time.
        metadata = {"hnsw:space": "cosine", **(fingerprint or {})}
        self.generation = f"{self._prefix}{_GEN_TAG}{_generation_token()}"
        self._collection = self._client.create_collection(self.generation, metadata=metadata)

    def add(self, ids: list[str], documents: list[str], embeddings: Any, metadatas: list[dict]) -> None:
        self._collection.add(documents=documents, embeddings=embeddings, metadatas=metadatas, ids=ids)

    def finalize(self) -> None:
        # Nothing to swap: the generation already has its final name, and it
        # goes live only when the indexer's atomic bm25.json replace names it.
        # A crash anywhere before that leaves the previous pair intact.
        pass

    def _discard_stale(self, live: set[str] | None) -> None:
        import chromadb

        if live is None:
            logger.warning("bm25.json unreadable; keeping every vector generation this build")
            return
        generation = re.compile(re.escape(self._prefix) + _GEN_TAG + f"[0-9a-f]{{{_GEN_TOKEN_LEN}}}")
        legacy = {self._collection_name, f"{self._collection_name}_staging"}
        for collection in self._client.list_collections():
            name = getattr(collection, "name", collection)
            if name in live or not (name in legacy or generation.fullmatch(name)):
                continue
            try:
                self._client.delete_collection(name)
            except chromadb.errors.NotFoundError:
                pass  # already absent is exactly the state a delete-if-exists wants

    def close(self) -> None:
        pass


class _ChromaReader:
    """Wraps the ChromaDB query path; returns normalized semantic hits.

    ``name`` is the generation bm25.json was built with; None (a bm25.json
    from before generations) opens the configured collection name.
    """

    def __init__(self, cfg: dict, name: str | None = None):
        import chromadb
        from chromadb.config import Settings

        # Same post-import ONNX suppression as _ChromaWriter.reset; see the
        # comment there for why force_import stays off on this seam.
        suppress_onnx_telemetry()
        chroma_path = cfg["indexing"]["chroma_path"]
        collection_name = name or cfg["indexing"]["collection_name"]
        if not Path(chroma_path).exists():
            raise IndexNotFoundError(
                f"ChromaDB index not found at {chroma_path}. Run: python -m retrieval.indexer"
            )
        client = chromadb.PersistentClient(
            path=chroma_path, settings=Settings(anonymized_telemetry=False)
        )
        try:
            self._collection = client.get_collection(collection_name)
        except chromadb.errors.NotFoundError as e:
            raise IndexNotFoundError(
                f"Collection '{collection_name}' not found in ChromaDB: {e}"
            ) from e

    def fingerprint(self) -> dict[str, str] | None:
        """Return the {model, dim, device} stamp recorded at index-build time.

        None when the collection predates fingerprinting entirely (built before
        this feature existed) -- distinct from a present-but-mismatched
        fingerprint, which HybridRetriever warns about differently.
        """
        metadata = self._collection.metadata or {}
        if not any(key in metadata for key in _FINGERPRINT_KEYS):
            return None
        return {key: str(metadata.get(key, "")) for key in _FINGERPRINT_KEYS}

    def query(self, embedding: Any, k: int) -> list[dict]:
        # Bound to one generation for this reader's life. If a later build has
        # deleted it, the NotFoundError reaches hybrid_search's designed
        # degrade: re-resolving to another generation here would pair these
        # vectors with a different build's BM25 leg.
        results = self._collection.query(query_embeddings=[embedding], n_results=k)
        out: list[dict] = []
        if results["documents"] and results["documents"][0]:
            for i, doc in enumerate(results["documents"][0]):
                # cosine space: distance = 1 - cos, so score = 1 - distance = cos.
                score = 1 - results["distances"][0][i]
                meta = results["metadatas"][0][i]
                out.append({
                    "text": doc, "score": score, "source": meta["source"],
                    "chunk_id": meta["chunk_id"],
                    "source_sha256": meta.get("source_sha256", ""),
                    "stem_tags": parse_stem_tags(meta.get("stem_tags", "[]")),
                })
        return out

    def close(self) -> None:
        pass


# ================================================================ pgvector (opt-in)
class _PgVectorBase:
    def __init__(self, cfg: dict):
        self._dsn = _pg_dsn(cfg)
        if not self._dsn:
            raise IndexNotFoundError(
                "vector_backend=pgvector but no DSN — set indexing.database_url, "
                "CYCLAW_VECTOR_DB_URL, or CYCLAW_DB_URL."
            )
        self._dim = _embed_dim(cfg)
        self._conn = None

    def _connection(self):
        if self._conn is None:
            import psycopg  # noqa: PLC0415 -- lazy: ChromaDB installs need no driver
            from pgvector.psycopg import register_vector  # noqa: PLC0415

            from utils.personality_db import _harden_pg_conninfo

            self._conn = psycopg.connect(_harden_pg_conninfo(self._dsn), autocommit=True)
            self._conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            register_vector(self._conn)
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            finally:
                self._conn = None


class _PgVectorWriter(_PgVectorBase):
    """Stores embeddings in a per-build ``kb_chunks_g<12 hex>`` table with an HNSW index.

    Same generation model as _ChromaWriter: the indexer records the table name
    in bm25.json, and nothing is renamed, so each generation's primary-key,
    sequence and index names are its own.
    """

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self._cfg = cfg
        self.generation: str | None = None

    def reset(self, fingerprint: dict[str, str] | None = None) -> None:
        # pgvector has no analogous per-collection metadata slot to stamp a
        # fingerprint into, so it is accepted (matching _ChromaWriter's signature)
        # and deliberately ignored -- fingerprint mismatch detection is scoped to
        # the ChromaDB backend only. HybridRetriever only calls .fingerprint() when
        # the reader exposes it (getattr), and _PgVectorReader deliberately does not.
        conn = self._connection()
        self._discard_stale(conn, _live_names(self._cfg, _PG_TABLE))
        # A fresh generation table, for the same reason as _ChromaWriter: the
        # served table is never truncated, renamed or dropped by this build.
        # The table name is code-generated and the dimension an int. Build the
        # HNSW index AFTER the bulk load (finalize) — far faster than
        # maintaining it row-by-row during insert.
        table = f"{_PG_TABLE}_g{_generation_token()}"
        conn.execute(
            f"CREATE TABLE {table} ("
            "  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,"
            "  source TEXT NOT NULL,"
            "  chunk_id INT NOT NULL,"
            "  source_sha256 TEXT NOT NULL DEFAULT '',"
            "  content TEXT NOT NULL,"
            "  stem_tags TEXT NOT NULL DEFAULT '[]',"
            f"  embedding vector({self._dim}) NOT NULL"
            ")"
        )
        conn.execute(f"CREATE INDEX {table}_src ON {table} (source, chunk_id)")
        self.generation = table

    def add(self, ids: list[str], documents: list[str], embeddings: Any, metadatas: list[dict]) -> None:
        conn = self._connection()
        rows = []
        for doc, emb, meta in zip(documents, embeddings, metadatas, strict=True):
            stem = meta.get("stem_tags", "[]")
            if not isinstance(stem, str):
                stem = json.dumps(stem)
            rows.append((
                meta["source"],
                int(meta["chunk_id"]),
                meta.get("source_sha256", ""),
                doc,
                stem,
                _as_list(emb),
            ))
        with conn.cursor() as cur:
            cur.executemany(
                f"INSERT INTO {self.generation} (source, chunk_id, source_sha256, content, stem_tags, embedding) "  # noqa: S608  # nosec B608 -- code-generated table name (_PG_NAME_RE shape)
                "VALUES (%s, %s, %s, %s, %s, %s)",
                rows,
            )

    def finalize(self) -> None:
        # Cosine ops mirror Chroma's cosine space; built once over the full set.
        # No swap: bm25.json naming this table is what makes it live.
        self._connection().execute(
            f"CREATE INDEX {self.generation}_hnsw "
            f"ON {self.generation} USING hnsw (embedding vector_cosine_ops)"
        )

    def _discard_stale(self, conn: Any, live: set[str] | None) -> None:
        if live is None:
            logger.warning("bm25.json unreadable; keeping every vector generation this build")
            return
        # DROP waits out in-flight queries on a table (ACCESS EXCLUSIVE lock).
        tables = conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = current_schema()"
        ).fetchall()
        for (name,) in tables:
            if name not in live and _PG_NAME_RE.fullmatch(name):
                conn.execute(f"DROP TABLE IF EXISTS {name}")


class _PgVectorReader(_PgVectorBase):
    """Queries one pgvector generation table; returns normalized semantic hits.

    ``name`` is the table bm25.json was built with; None (a bm25.json from
    before generations) opens the legacy ``kb_chunks`` table.
    """

    def __init__(self, cfg: dict, name: str | None = None):
        super().__init__(cfg)
        table = name or _PG_TABLE
        if not _PG_NAME_RE.fullmatch(table):
            raise IndexNotFoundError(
                f"pgvector table name {table!r} in bm25.json is not one this indexer writes. "
                "Run: python -m retrieval.indexer"
            )
        self._table = table
        conn = self._connection()
        exists = conn.execute("SELECT to_regclass(%s)", (table,)).fetchone()[0]
        if exists is None:
            # __init__ never returns to the caller on this path, so nothing
            # else can reach self.close() to release the connection just
            # opened by self._connection() above -- close it here before
            # raising, matching _ChromaReader's fail-clean-on-construction
            # behavior (that reader never opens a resource it doesn't return).
            self.close()
            raise IndexNotFoundError(
                f"pgvector table '{table}' not found. Run: python -m retrieval.indexer"
            )
        self._has_source_sha256 = conn.execute(
            "SELECT EXISTS ("
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = current_schema() "
            "AND table_name = %s AND column_name = %s"
            ")",
            (table, "source_sha256"),
        ).fetchone()[0]

    def query(self, embedding: Any, k: int) -> list[dict]:
        conn = self._connection()
        source_sha256_sql = "source_sha256" if self._has_source_sha256 else "'' AS source_sha256"
        # `<=>` is cosine distance; `1 - distance` reproduces Chroma's cosine score.
        # Same ordering expression in SELECT and ORDER BY so the HNSW index is used.
        rows = conn.execute(
            f"SELECT content, source, chunk_id, {source_sha256_sql}, stem_tags, "  # noqa: S608
            f"1 - (embedding <=> %(q)s::vector) AS score FROM {self._table} "
            "ORDER BY embedding <=> %(q)s::vector LIMIT %(k)s",
            {"q": _as_list(embedding), "k": k},
        ).fetchall()
        out: list[dict] = []
        for content, source, chunk_id, source_sha256, stem_tags, score in rows:
            out.append({
                "text": content, "score": float(score), "source": source,
                "chunk_id": chunk_id, "source_sha256": source_sha256,
                "stem_tags": parse_stem_tags(stem_tags),
            })
        return out


def _as_list(emb: Any) -> list[float]:
    """Coerce an embedding (list or numpy array) to a plain list for pgvector binding."""
    tolist = getattr(emb, "tolist", None)
    return tolist() if callable(tolist) else list(emb)


# ===================================================================== factories
def get_vector_writer(cfg: dict):
    """Return a write-side store (``reset`` / ``add`` / ``finalize`` / ``close``)."""
    if vector_backend(cfg) == "pgvector":
        return _PgVectorWriter(cfg)
    return _ChromaWriter(cfg)


def get_vector_reader(cfg: dict, name: str | None = None):
    """Return a read-side store exposing ``query(embedding, k) -> list[dict]``.

    ``name`` is the vector generation bm25.json records (its
    ``vector_collection`` key); None opens the legacy fixed name.
    """
    if vector_backend(cfg) == "pgvector":
        return _PgVectorReader(cfg, name)
    return _ChromaReader(cfg, name)
