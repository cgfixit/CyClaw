# sqlite-vec Phase C spike findings (issue #1255)

Dated 2026-09-21. Verified against `origin/main` `f4f84d8`. Answers the four
checklist items the issue's phased-plan comment set as Phase C's acceptance
gate, plus one honest scope note on what this sandbox could not measure.

## 1. `enable_load_extension` + `sqlite_vec.load()` across the CI matrix

**Linux: confirmed working**, verified directly in this sandbox (not
assumed): `sqlite3.Connection.enable_load_extension(True)` succeeds,
`sqlite_vec.load(conn)` succeeds, `SELECT vec_version()` returns `v0.1.9`.

**macOS / Windows: not yet confirmed from this sandbox** (no such runners
here). `tests/test_sqlite_vec_extension_loading.py` (added by this PR) proves
exactly this capability and runs on all three CI-matrix OSes for free —
`sqlite-vec==0.1.9` is a `requirements-test.txt` entry, so it installs
wherever `pip install -r requirements.txt -r requirements-test.txt -c
constraints.txt` already runs, no new CI job needed. **The real answer to
the macOS question is this PR's own CI run** — check that before treating
Phase D as viable. If `macos-latest` fails here, that is the kill signal the
issue's deep-dive comment flagged as possible.

## 2. Pin `sqlite-vec==0.1.9` (latest stable, not the 0.1.10 alpha)

Done — confirmed `0.1.9` is still PyPI's newest stable release as of
2026-09-21 (the `0.1.10-alpha.4` DiskANN work remains in flight). Pinned in
`constraints.txt`, `requirements-test.txt`, and `pyproject.toml`'s `test`
extra (all three, matching the `tzdata`/`pygments` precedent for a
test-only dependency). No conda-forge package exists (checked both
`noarch` and `linux-64` repodata — zero matches), so `environment.yml`
carries it in the `pip:` sublist, same as `langgraph`/`rank-bm25`/
`websockets`/`onnxruntime` above it.

## 3. `scripts/compare_vector_backends.py` — built, and partially run

Built per the issue's own request (builds two isolated indices from the same
corpus + embeddings, runs index-doctor's fixed `PROBES` set through both,
reports top-1 agreement / overlap@k / build+query wall-clock).

**What it proved, verified in this sandbox:**

- **Score-contract equivalence.** Ran the script end-to-end against the real
  corpus with deterministic synthetic (non-semantic) embeddings standing in
  for the real model — chosen specifically to isolate "does the *math*
  match" from "does the *model* agree with itself," since the two backends
  must produce identical scores for identical input vectors regardless of
  what those vectors mean. Result: **byte-identical cosine scores** between
  Chroma and the sqlite-vec prototype on all 5 probes (e.g. `0.1027` vs
  `0.1027`, `0.1426` vs `0.1426`), 5/5 top-1 agreement, 1.0 mean overlap@5.
  This directly confirms the issue's own claim — `vec0`'s native
  `distance_metric=cosine` (v0.1.6+) reproduces `_ChromaReader.query`'s
  `score = 1 - distance` contract exactly, with **no pre-normalization
  trick needed** (the issue's proposal assumed only L2 was available and
  relied on pre-normalized embeddings; that assumption is now moot —
  cosine is native).
- **Rough perf signal** (67-chunk corpus, synthetic embeddings, single
  sandbox run — not a benchmark claim): build wall-clock 5.358s (Chroma) vs
  0.014s (sqlite-vec prototype); query p50 2.39ms (Chroma) vs 0.55ms
  (sqlite-vec). Directionally consistent with the issue's own framing
  ("vec0 does a fast brute-force scan... fine, maybe better, at CyClaw's
  corpus scale") but **not a real measurement** — Chroma's number likely
  includes one-time client/collection construction overhead this tiny
  corpus doesn't amortize away, and neither number reflects the real
  embedding model's actual vector distribution.

**What it could NOT prove in this sandbox:** real semantic-content ranking
agreement using the actual `all-MiniLM-L6-v2` embeddings. This sandbox's
egress proxy denies `huggingface.co` (`403` on every `CONNECT`, confirmed
via `curl $HTTPS_PROXY/__agentproxy/status`'s `recentRelayFailures`), so the
model this script needs (`retrieval/embeddings.py`'s cold-start fetch) has
no path to download. `ci.yml`'s own `test` jobs *do* reach `huggingface.co`
(the "Cache embeddings model" step, `ci_rag_smoke.py`'s real-index run) — a
follow-up run of this script belongs in that environment or on a dev
machine with the model already cached, not this sandbox. **This is a real
gap, not a blocker**: the score-contract equivalence proven above is the
stronger, more fundamental claim (it holds for any embedding, not just this
one model's output on this one corpus), and the real-corpus run is a
confirmation, not a new risk.

## 4. Wheel availability for the actual CI-matrix archs

Not independently re-verified beyond what the deep-dive comment already
found (manylinux x86_64/arm64 + macOS arm64 prebuilt; upstream issue #211
leaves Windows x86_64 / macOS Intel coverage ambiguous). **This PR's own CI
run settles it empirically**: if `pip install -c constraints.txt sqlite-vec`
succeeds on all three matrix legs (it must, for
`test_sqlite_vec_extension_loading.py` to even collect), wheel coverage for
this repo's actual runners is proven, not assumed.

## Disposition

Three of four Phase C checklist items are answered from this sandbox alone
(pin, score-contract math, build mechanics); the fourth (macOS extension
loading + wheel coverage) is answered by this PR's own CI run, which is the
whole point of putting the proof in `requirements-test.txt` rather than a
written claim. **Do not treat Phase D as clear to start until this PR's
`macos-latest` and `windows-latest` legs are confirmed green** — that is
the actual gate, not this document.

Nothing here changes `retrieval/vector_store.py`, `config.yaml`, or any
production code path. `sqlite-vec` is test-only; the default backend is
still ChromaDB.
