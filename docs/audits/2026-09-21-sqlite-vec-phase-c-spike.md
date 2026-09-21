# sqlite-vec Phase C spike findings (issue #1255)

Dated 2026-09-21. Verified against `origin/main` `f4f84d8`. Answers the four
checklist items the issue's phased-plan comment set as Phase C's acceptance
gate, plus one honest scope note on what this sandbox could not measure.

## 1. `enable_load_extension` + `sqlite_vec.load()` across the CI matrix

**Linux: confirmed working**, verified directly in this sandbox (not
assumed) and again on `ubuntu-latest` in this PR's own CI run:
`sqlite3.Connection.enable_load_extension(True)` succeeds,
`sqlite_vec.load(conn)` succeeds, `SELECT vec_version()` returns `v0.1.9`.

**Windows: confirmed working.** `windows-latest` passed all three tests in
this PR's own CI run (2026-09-21).

**macOS: CONFIRMED BROKEN — this is the kill signal.** `macos-latest` failed
this PR's own CI run (2026-09-21, run
[35595936487](https://github.com/cgfixit/CyClaw/actions/runs/35595936487),
job `macos-latest`) with:

```
AttributeError: 'sqlite3.Connection' object has no attribute 'enable_load_extension'
```

on all three tests, at `conn.enable_load_extension(True)` in the fixture. This
is *not* the softer failure mode the issue's deep-dive comment considered
(extension loading permitted but the specific `.dylib` rejected, or a
runtime `OperationalError`) — the arm64 macOS Python 3.12.10 build GitHub
Actions provisions (via `actions/setup-python`, a python.org framework
build) compiles its `_sqlite3` extension module *without*
`--enable-loadable-sqlite-extensions` at all, so `enable_load_extension`
never exists as a method on `sqlite3.Connection` in the first place. This
confirms, empirically rather than by inference, the exact risk this
repository's own `memory/store.py` comment already hinted at (FTS5 is
compiled into stdlib SQLite there specifically because it never needs
runtime extension loading).

**What this means for Phase D as originally scoped:** a `_SqliteVecWriter`/
`_SqliteVecReader` built on stdlib `sqlite3` cannot support macOS on the
CI-provisioned Python build, and macOS is one of CyClaw's three CI-matrix
release-gate legs (`CLAUDE.md` §8: "all three `test` legs are release
gates"). Phase D cannot ship as a straightforward stdlib-`sqlite3` backend
without either (a) accepting a macOS gap in a feature meant to be a
platform-parity default-backend candidate — a regression from ChromaDB's own
current macOS support — or (b) swapping the underlying sqlite3 binding for
one that carries its own loadable-extension-capable SQLite build, most
plausibly `pysqlite3-binary` (a drop-in `sqlite3`-API package that bundles a
statically-linked, extension-loading-enabled SQLite) or `apsw`. Either
option is a **new runtime dependency with its own wheel-coverage and
four-surface pin evaluation** (`CLAUDE.md` §4's dependency-pin discipline) —
out of scope for this spike, and a real added-scope item for whoever picks
up Phase D, not a detail to gloss over.

The fixture in `tests/test_sqlite_vec_extension_loading.py` now skips
(rather than errors) when `enable_load_extension` is absent, so this
platform gap is visible in the CI summary (a `SKIPPED` with this doc cited)
without failing the release-gate `test` leg on a capability the test itself
exists to characterize, not to require unconditionally.

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

All four Phase C checklist items are now answered, three from this sandbox
(pin, score-contract math, build mechanics) and the fourth — macOS extension
loading — from this PR's own CI run, which is the whole point of putting the
proof in `requirements-test.txt` rather than a written claim.

**Phase D (implement a production `_SqliteVecWriter`/`_SqliteVecReader`) is
NOT clear to start as originally scoped.** The empirical result is a hard
no on macOS via stdlib `sqlite3` on CyClaw's actual CI-provisioned Python
build — see §1 above. This is the kill signal the issue's own deep-dive
comment flagged as possible before this PR's CI ran; it did happen. Phase D
either needs an explicit, user-approved decision to ship without macOS
parity (a regression from ChromaDB's current three-OS support), or a
follow-up spike evaluating `pysqlite3-binary`/`apsw` as the sqlite3 binding
— itself a new-dependency decision requiring the same pin/wheel-coverage
diligence this spike applied to `sqlite-vec` itself, not a small addendum.
Linux and Windows both work today via stdlib `sqlite3`; only macOS is
blocked.

Nothing here changes `retrieval/vector_store.py`, `config.yaml`, or any
production code path. `sqlite-vec` is test-only; the default backend is
still ChromaDB.
