"""Phase C spike for issue #1255 (chromadb -> sqlite-vec replacement).

Answers the one question the issue's deep-dive comment flagged as able to
kill the whole approach: does ``sqlite3.Connection.enable_load_extension`` +
``sqlite_vec.load()`` actually work on every CI-matrix OS? Apple's
system/framework Python builds ``sqlite3`` against a libsqlite3 compiled
WITHOUT extension-loading support, and this repo has zero prior use of
runtime extension loading to lean on (``memory/store.py``'s FTS5 is compiled
into stdlib SQLite, never runtime-loaded).

Deliberately standalone -- does NOT import retrieval/vector_store.py or wire
sqlite-vec into any production path. That is Phase D, gated on this file
passing across the full 3-OS matrix. No new CI job needed: sqlite-vec lives
in requirements-test.txt, so this runs wherever the existing test suite runs.
"""

from __future__ import annotations

import math
import sqlite3
import struct

import pytest

sqlite_vec = pytest.importorskip("sqlite_vec")


def _serialize(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


@pytest.fixture
def vec_conn():
    conn = sqlite3.connect(":memory:")
    # Confirmed 2026-09-21 on this PR's own macos-latest CI run: the
    # python.org/actions-setup-python arm64 3.12 build's _sqlite3 extension
    # module is compiled WITHOUT --enable-loadable-sqlite-extensions, so
    # enable_load_extension is not merely a no-op or a runtime OperationalError
    # -- the Connection object never gets the method at all
    # (AttributeError: 'sqlite3.Connection' object has no attribute
    # 'enable_load_extension'). This is exactly the risk this module's own
    # docstring named before CI ran; it is now an empirically confirmed
    # platform gap, not a hypothetical. Skip (not fail/error) here because
    # this is a capability the CURRENT stdlib sqlite3 build lacks, not a bug
    # in sqlite-vec or in this test -- see
    # docs/audits/2026-09-21-sqlite-vec-phase-c-spike.md's Disposition for
    # what this means for Phase D (a stdlib-sqlite3-only backend cannot ship
    # macOS support as-is; a different sqlite3 binding, e.g. pysqlite3-binary
    # or apsw, would need its own wheel-coverage/dependency-pin evaluation).
    if not hasattr(conn, "enable_load_extension"):
        conn.close()
        pytest.skip(
            "sqlite3 built without loadable-extension support on this platform "
            "(confirmed on GitHub Actions macos-latest, 2026-09-21) -- see "
            "docs/audits/2026-09-21-sqlite-vec-phase-c-spike.md"
        )
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    try:
        yield conn
    finally:
        conn.close()


def test_extension_loads_and_reports_version(vec_conn):
    """The load itself is the real risk -- confirm it didn't silently no-op."""
    (version,) = vec_conn.execute("SELECT vec_version()").fetchone()
    assert version == "v0.1.9"


def test_l2_knn_matches_hand_computed_distance(vec_conn):
    """Default vec0 metric is L2 -- confirm the extension computes real math,
    not a stub, by checking against a hand-computed Euclidean distance."""
    vec_conn.execute("CREATE VIRTUAL TABLE vec_items USING vec0(embedding float[4])")
    items = {1: [0.1, 0.1, 0.1, 0.1], 2: [0.2, 0.2, 0.2, 0.2], 3: [0.9, 0.9, 0.9, 0.9]}
    for rowid, vec in items.items():
        vec_conn.execute(
            "INSERT INTO vec_items(rowid, embedding) VALUES (?, ?)", [rowid, _serialize(vec)]
        )
    query = [0.15, 0.15, 0.15, 0.15]
    rows = vec_conn.execute(
        "SELECT rowid, distance FROM vec_items WHERE embedding MATCH ? ORDER BY distance LIMIT 3",
        [_serialize(query)],
    ).fetchall()
    got = dict(rows)
    for rowid, vec in items.items():
        expected = math.sqrt(sum((a - b) ** 2 for a, b in zip(vec, query, strict=True)))
        assert got[rowid] == pytest.approx(expected, abs=1e-5)
    # Nearest first: item 2 and item 1 straddle the query equally closely,
    # item 3 is far -- confirms real ranking, not insertion order.
    assert [rowid for rowid, _ in rows][-1] == 3


def test_cosine_distance_metric_reproduces_chroma_score_contract(vec_conn):
    """retrieval/vector_store.py's _ChromaReader.query computes
    score = 1 - distance and treats it as cosine similarity. vec0 supports
    distance_metric=cosine natively (v0.1.6+) -- confirm the same score
    contract holds here, so a sqlite-vec backend needs no pre-normalization
    trick to match Chroma's ranking semantics."""
    vec_conn.execute(
        "CREATE VIRTUAL TABLE vec_cos USING vec0(embedding float[4] distance_metric=cosine)"
    )
    items = {
        1: [1.0, 0.0, 0.0, 0.0],  # identical to query -> cosine sim 1.0
        2: [0.0, 1.0, 0.0, 0.0],  # orthogonal -> cosine sim 0.0
        3: [0.9, 0.1, 0.0, 0.0],  # near-identical -> cosine sim close to 1.0
    }
    for rowid, vec in items.items():
        vec_conn.execute(
            "INSERT INTO vec_cos(rowid, embedding) VALUES (?, ?)", [rowid, _serialize(vec)]
        )
    query = _serialize([1.0, 0.0, 0.0, 0.0])
    rows = vec_conn.execute(
        "SELECT rowid, distance FROM vec_cos WHERE embedding MATCH ? ORDER BY distance LIMIT 3",
        [query],
    ).fetchall()
    scores = {rowid: 1 - distance for rowid, distance in rows}
    assert scores[1] == pytest.approx(1.0, abs=1e-5)
    assert scores[2] == pytest.approx(0.0, abs=1e-5)
    assert 0.9 < scores[3] < 1.0
    # Ranking order: identical, then near-identical, then orthogonal.
    assert [rowid for rowid, _ in rows] == [1, 3, 2]
