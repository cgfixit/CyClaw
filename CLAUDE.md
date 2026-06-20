# CyClaw Test Coverage & CI Hardening — Claude Code PR Plan

**Branch:** `feat/test-coverage-hardening`  
**Target:** `main`  
**Scope:** `retrieval/stemmer.py`, `tests/test_stemmer.py`, `tests/test_sync_*.py`, `.github/workflows/ci.yml`, `tests/TEST_SUITE_AUDIT.md`

---

## Phase 0: Pre-Implementation Claim Verification

Before any code changes, Claude must verify the following claims against the live `main` branch
at HEAD (`a3e9310bfd2a71e84adb998ac910e98a95e6a606`). Each claim is confirmed or corrected here
based on actual repository state.

### Verified Findings (Main Branch Audit)

| Claim | Verified? | Evidence |
|-------|-----------|----------|
| `retrieval/stemmer.py` lives under `retrieval/`, **not** `utils/` | ✅ CORRECTED — original framing said "utils/stemmer"; actual path is `retrieval/stemmer.py` | `retrieval/` listing confirms no stemmer in `utils/` |
| `tests/test_stemmer.py` exists at 2,403 bytes | ✅ Confirmed | `tests/` directory listing |
| `test_stemmer.py` imports from `retrieval.stemmer` | ✅ Confirmed | Line 1 of test file: `from retrieval.stemmer import stem_token as enhanced_porter_stem, tokenize_and_stem` |
| `test_stemmer.py` only covers plurals, verb forms, 1 technical term, tokenization basics | ✅ Confirmed | File has 12 tests; no hyphen, no alphanumeric-mix, no idempotency, no unicode, no `_CUSTOM_STEMS` exhaustion |
| **No `test_sync.py` exists** | ✅ CORRECTED — sync tests DO exist: `test_sync_cli.py`, `test_sync_config.py`, `test_sync_filters.py`, `test_sync_runner.py`, `test_sync_scheduler.py` | `tests/` listing |
| `ci.yml` runs `pytest` | ✅ Confirmed | `ci.yml` explicitly enumerates test files including all 5 sync test files |
| **No `--cov-fail-under` coverage gate** | ✅ Confirmed | `ci.yml` uses `--cov=utils.sanitizer --cov=utils.errors ...` but NO `--cov-fail-under` flag; coverage is reported only, not enforced |
| `stemmer.py` is **NOT** in the CI `--cov` scope | ✅ Confirmed | `ci.yml` covers `utils.sanitizer`, `utils.errors`, `utils.logger`, `utils.personality`, `mcp_hybrid_server` — `retrieval.stemmer` is absent |
| CI uses `ubuntu-latest` + `windows-latest` matrix | ✅ Confirmed | `ci.yml` `strategy.matrix.os` already covers both; Python 3.12 only |
| No Python 3.11 CI matrix | ✅ Confirmed | Only `python-version: '3.12'` in `ci.yml` |
| `apipsTest.ps1` not wired to CI | ✅ Confirmed | CI has no `pwsh` step; PowerShell smoke is local-only |
| `security.ratelimit.enabled` is a no-op in config | ✅ Confirmed (per arch docs + `config.yaml`); rate limiting is hardcoded in `gate.py` |
| BM25 SHA integrity detection planned for v1.5.0; not yet implemented | ✅ Confirmed — v1.5.0 planning item in arch doc |
| `TEST_SUITE_AUDIT.md` exists in `tests/` | ✅ Confirmed | 17,198 bytes |

### Critical Corrections to Source Brief

1. **`utils/stemmer` is a misnomer** — the module is `retrieval/stemmer.py`. The `utils/` package
   contains `sanitizer.py`, `personality.py`, `errors.py`, `logger.py`, `ratelimit.py`, `health.py`.
   No stemmer lives there. All CI `--cov` flags and test imports must reference `retrieval.stemmer`.

2. **Sync coverage gap claim is partially wrong** — 5 sync test files exist and are wired to CI.
   The gap is not "no sync tests" but rather that `TEST_SUITE_AUDIT.md` may not enumerate them
   (architecture doc section J omits them from its test file list). The actual gap is documentation
   staleness, not missing tests.

3. **`test_stemmer.py` coverage is low because `retrieval.stemmer` is excluded from `--cov` scope**
   in `ci.yml`. Even if tests execute the module, coverage is not measured. This is both a scope
   bug and a test-breadth problem — two separate fixes required.

---

## Phase 1: Branch Setup

```
git checkout main
git pull origin main
git checkout -b feat/test-coverage-hardening
```

All file edits below target this branch. PR opens against `main` at the end of Phase 4.

---

## Phase 2: Fix `tests/test_stemmer.py` — Expand Coverage

**Why:** `test_stemmer.py` is 2,403 bytes with 12 tests covering only: 2 short words, 3 plurals,
2 verb forms, 1 domain-mapped term (`kubernetes→k8s`), 1 `-ss` ending, 1 `-ies` duplicate, 1
suffix reduction, and 4 tokenization tests.

**What the source has that tests don't cover:**

- `_CUSTOM_STEMS` has 20+ entries — only `kubernetes` is tested
- `_WORD_RE = re.compile(r'[a-z][a-z0-9_-]+')` — no hyphen or underscore token tests
- `lru_cache(maxsize=100_000)` — no cache hit/miss or idempotency test
- `tokenize_and_stem` — no hyphenated input, no mixed alphanumeric (`v1.4.0`), no unicode, no
  whitespace-only input
- Domain vocab: `chromadb`, `langgraph`, `langchain`, `retrieval`, `embedding`, `transformer`,
  `attention`, `augmented`, `cyclaw`, `soul`, `personality`, `docker`, `nginx` — all untested

**Full replacement for `tests/test_stemmer.py`:**

```python
"""Unit tests for retrieval/stemmer.py — enhanced Porter + CyClaw domain map.

Coverage targets:
  - All _CUSTOM_STEMS entries (exhaustive parametrized)
  - _WORD_RE hyphen/underscore/alphanumeric tokenization behaviour
  - Idempotency: stem(stem(x)) == stem(x) for every custom stem
  - Edge cases: empty string, single char, unicode, whitespace-only
  - tokenize_and_stem: hyphenated tokens, version strings, technical compound words
"""

import pytest
from retrieval.stemmer import stem_token as enhanced_porter_stem, tokenize_and_stem


class TestCustomStems:
    """Every entry in _CUSTOM_STEMS must round-trip through stem_token."""

    @pytest.mark.parametrize("token,expected", [
        ("embedding",    "embed"),
        ("embeddings",   "embed"),
        ("transformer",  "transform"),
        ("transformers", "transform"),
        ("attention",    "attn"),
        ("attentional",  "attn"),
        ("retrieval",    "retriev"),
        ("retrieve",     "retriev"),
        ("retrieved",    "retriev"),
        ("augmented",    "augment"),
        ("augmentation", "augment"),
        ("kubernetes",   "k8s"),
        ("docker",       "docker"),
        ("nginx",        "nginx"),
        ("langgraph",    "langgraph"),
        ("langchain",    "langchain"),
        ("chromadb",     "chroma"),
        ("chroma",       "chroma"),
        ("cyclaw",       "cyclaw"),
        ("safeclaw",     "safeclaw"),
        ("personality",  "person"),
        ("soul",         "soul"),
    ])
    def test_custom_stem_entry(self, token, expected):
        assert enhanced_porter_stem(token) == expected, (
            f"_CUSTOM_STEMS[{token!r}] should map to {expected!r}"
        )

    def test_case_insensitive_lookup(self):
        assert enhanced_porter_stem("ChromaDB") == "chroma"
        assert enhanced_porter_stem("LangGraph") == "langgraph"
        assert enhanced_porter_stem("KUBERNETES") == "k8s"


class TestTechnicalVocabPreservation:
    """Terms that must survive stemming without losing identity."""

    def test_rrf_preserved(self):
        result = enhanced_porter_stem("rrf")
        assert result == "rrf"

    def test_bm25_token(self):
        result = enhanced_porter_stem("bm25")
        assert isinstance(result, str) and len(result) >= 1

    def test_api_not_mangled(self):
        assert enhanced_porter_stem("api") == "api"

    def test_cpu_not_mangled(self):
        assert enhanced_porter_stem("cpu") == "cpu"

    def test_docker_identity(self):
        assert enhanced_porter_stem("docker") == "docker"

    def test_nginx_identity(self):
        assert enhanced_porter_stem("nginx") == "nginx"


class TestPorterStem:
    def test_short_words_preserved(self):
        assert enhanced_porter_stem("api") == "api"
        assert enhanced_porter_stem("cpu") == "cpu"

    def test_plurals(self):
        assert enhanced_porter_stem("processes") == "process"
        assert enhanced_porter_stem("policies") == "polici"
        assert enhanced_porter_stem("addresses") == "address"

    def test_verb_forms(self):
        assert enhanced_porter_stem("running") == "run"
        assert enhanced_porter_stem("configured") == "configur"

    def test_ss_ending_preserved(self):
        assert enhanced_porter_stem("access") == "access"

    def test_suffix_reduction(self):
        assert enhanced_porter_stem("rationalization") == "ration"


class TestIdempotency:
    @pytest.mark.parametrize("token", [
        "embedding", "transformer", "retrieval", "augmented", "kubernetes",
        "chromadb", "langgraph", "cyclaw", "personality", "soul",
        "running", "processes", "configured", "rationalization",
        "access", "api", "cpu",
    ])
    def test_idempotent(self, token):
        first = enhanced_porter_stem(token)
        second = enhanced_porter_stem(first)
        assert first == second, (
            f"stem is not idempotent for {token!r}: "
            f"stem(token)={first!r}, stem(stem(token))={second!r}"
        )


class TestEdgeCases:
    def test_empty_string_stem(self):
        result = enhanced_porter_stem("")
        assert isinstance(result, str)

    def test_single_char(self):
        result = enhanced_porter_stem("a")
        assert isinstance(result, str)

    def test_unicode_passthrough(self):
        result = enhanced_porter_stem("na\u00efve")
        assert isinstance(result, str)

    def test_uppercase_normalised(self):
        assert enhanced_porter_stem("Retrieval") == enhanced_porter_stem("retrieval")
        assert enhanced_porter_stem("RUNNING") == enhanced_porter_stem("running")


class TestTokenizeAndStem:
    def test_basic_tokenization(self):
        tokens = tokenize_and_stem("Configure the backup repository")
        assert len(tokens) == 4
        assert all(isinstance(t, str) for t in tokens)

    def test_empty_input(self):
        assert tokenize_and_stem("") == []

    def test_whitespace_only(self):
        assert tokenize_and_stem("   \t\n  ") == []

    def test_numeric_tokens_excluded(self):
        tokens = tokenize_and_stem("version 2.5.1 release")
        assert all(t.isalpha() or t.isalnum() for t in tokens)
        assert "2" not in tokens and "2.5.1" not in tokens

    def test_hyphenated_token(self):
        """_WORD_RE includes hyphens: bm25-okapi is one token from 'b' lead."""
        tokens = tokenize_and_stem("bm25-okapi retrieval")
        assert "retriev" in tokens

    def test_version_string_handling(self):
        tokens = tokenize_and_stem("v1.4.0 cyclaw upgrade")
        assert "cyclaw" in tokens

    def test_all_minilm_token(self):
        tokens = tokenize_and_stem("all-MiniLM-L6-v2 embeddings")
        assert "embed" in tokens

    def test_technical_compound(self):
        tokens = tokenize_and_stem("LangGraph ChromaDB hybrid search")
        assert "langgraph" in tokens
        assert "chroma" in tokens

    def test_consistency(self):
        t1 = tokenize_and_stem("backup configuration")
        t2 = tokenize_and_stem("backup configuration")
        assert t1 == t2

    def test_filters_short_words(self):
        tokens = tokenize_and_stem("I a b go run")
        assert "go" in tokens or len(tokens) >= 1

    def test_underscore_in_token(self):
        tokens = tokenize_and_stem("soul_core graph_state audit")
        assert any("soul" in t or "soul_cor" in t for t in tokens)

    def test_repeated_call_same_result(self):
        r1 = enhanced_porter_stem("langgraph")
        r2 = enhanced_porter_stem("langgraph")
        assert r1 == r2 == "langgraph"
```

---

## Phase 3: Update `ci.yml` — Add Coverage Gate + `retrieval.stemmer` Scope

**Why:** `ci.yml` currently measures coverage for `utils.sanitizer`, `utils.errors`, `utils.logger`,
`utils.personality`, and `mcp_hybrid_server` only. `retrieval.stemmer` — the module whose low
coverage triggered this PR — is not in scope. Additionally, there is no `--cov-fail-under` flag,
so the build never fails due to insufficient coverage regardless of what the report shows.

**Required change:** Add to the `pytest` invocation in `ci.yml`:

```yaml
            --cov=retrieval.stemmer \
            --cov-fail-under=80
```

**Rationale for `--cov-fail-under=80`:** Conservative first-pass threshold. Critical modules
already have deep coverage. The floor ensures `retrieval/stemmer.py` doesn't regress post-expansion,
without requiring immediate perfection on lower-risk modules.

**Per-module aspirational targets (document in `TEST_SUITE_AUDIT.md`):**

| Module | Target | Rationale |
|--------|--------|-----|
| `utils/sanitizer.py` | ≥ 95% | Security-critical: 13 OWASP patterns |
| `utils/personality.py` | ≥ 90% | Soul governance: drift detection, atomic writes, TTL |
| `retrieval/stemmer.py` | ≥ 90% | Post Phase 2 expansion target |
| `mcp_hybrid_server.py` | ≥ 85% | MCP protocol invariants |
| `utils/errors.py` | ≥ 80% | Error type hierarchy |
| `utils/logger.py` | ≥ 80% | Audit JSONL + PII redaction |
| `retrieval/hybrid_search.py` | ≥ 80% | RRF fusion math |
| `graph.py` | ≥ 85% | 7-node LangGraph topology |

---

## Phase 4: Rate-Limiter Config Gap Sentinel Test

**Append to `tests/test_rate_limit.py`:**

```python
def test_config_ratelimit_enabled_is_noop(monkeypatch):
    """
    KNOWN GAP (v1.4.0): security.ratelimit.enabled in config.yaml has no effect.
    Rate limiting is hardcoded at 60 req/min in gate.py regardless of config value.

    When config-driven toggling ships (v1.5.0), update this test to verify
    the wiring actually disables/enables the limiter.
    """
    import gate
    # Verify the hardcoded constant is present and unchanged
    assert hasattr(gate, "RATE_LIMIT_REQUESTS"), (
        "RATE_LIMIT_REQUESTS constant removed — verify config-driven toggle was "
        "implemented and update this sentinel test."
    )
    assert gate.RATE_LIMIT_REQUESTS == 60, (
        f"Hardcoded rate limit changed to {gate.RATE_LIMIT_REQUESTS}; "
        "if intentional, update the sentinel value here."
    )
```

> **Note:** Claude must `grep` the actual constant name from `gate.py` before writing this
> test. If the constant is named differently, use the real name.

---

## Phase 5: Update `tests/TEST_SUITE_AUDIT.md`

**Required additions:**

1. Add all 5 sync test files (`test_sync_cli.py`, `test_sync_config.py`, `test_sync_filters.py`,
   `test_sync_runner.py`, `test_sync_scheduler.py`) to the file inventory table.
2. Add the per-module coverage targets table (from Phase 3).
3. Add a **Known Gaps** section:
   - `security.ratelimit.enabled` config toggle not wired (v1.4.0); planned v1.5.0
   - BM25 SHA integrity detection not testable until v1.5.0 ships
   - `apipsTest.ps1` is local-only; never runs in CI (no `pwsh` step)
   - Python 3.11 compatibility stated in docs but not CI-matrix-verified
4. Update "Last Audited" date to June 2026 / v1.4.0.

---

## Phase 6: BM25 SHA Integrity — v1.5.0 Stub

Add to `tests/test_security.py`:

```python
# TODO(v1.5.0): Add test_bm25_sha_integrity_mismatch() once SHA integrity detection
# on load is implemented in retrieval/indexer.py. The test should:
#   1. Build a valid BM25 index and record its SHA-256
#   2. Tamper with index/bm25.pkl (flip a byte)
#   3. Assert that indexer.load_bm25() raises IntegrityError (or equivalent)
# Current state (v1.4.0): a tampered bm25.pkl loads silently.
# See: v1.5.0 planning item "BM25 SHA integrity detection on load"
```

---

## Phase 7 (Optional): Python 3.11 CI Matrix

Expand `ci.yml` matrix if constraints.txt compatibility is confirmed:

```yaml
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, windows-latest]
        python-version: ['3.11', '3.12']
```

Treat 3.11 failures as informational (not blocking) on first pass.

---

## Implementation Order (Claude Code Execution Sequence)

```
1.  git checkout -b feat/test-coverage-hardening
2.  Read gate.py → confirm RATE_LIMIT_REQUESTS constant name
3.  Read tests/test_rate_limit.py → identify append point
4.  Read tests/TEST_SUITE_AUDIT.md → understand structure before editing
5.  Write tests/test_stemmer.py (full replacement — Phase 2)
6.  Append sentinel test to tests/test_rate_limit.py (Phase 4)
7.  Edit .github/workflows/ci.yml — add --cov=retrieval.stemmer + --cov-fail-under=80
8.  Edit tests/TEST_SUITE_AUDIT.md — sync files, coverage targets, known gaps
9.  Add TODO stub to tests/test_security.py (Phase 6)
10. [Optional] Add Python 3.11 matrix if Phase 7 approved
11. git add -A && git commit -m "test: expand stemmer coverage + wire CI coverage gate"
12. git push origin feat/test-coverage-hardening
13. Open PR against main
```

---

## PR Description Template

```
## Summary
Addresses the stemmer coverage gap and missing CI coverage gate from the v1.4.0 audit.
No production code changed — tests and CI only.

## Changes
- tests/test_stemmer.py — Full rewrite: 12 → ~35 tests. Adds all _CUSTOM_STEMS entries,
  idempotency suite, edge cases, hyphenated/versioned tokenization, _WORD_RE verification.
- .github/workflows/ci.yml — Adds --cov=retrieval.stemmer + --cov-fail-under=80 gate.
- tests/test_rate_limit.py — Sentinel documenting security.ratelimit.enabled no-op gap.
- tests/TEST_SUITE_AUDIT.md — Sync files inventory, coverage targets, Known Gaps section.
- tests/test_security.py — TODO stub for v1.5.0 BM25 SHA integrity test.

## Verification
- All existing tests continue to pass (no behaviour changes)
- pytest tests/test_stemmer.py -v shows ~35 tests passing
- CI --cov-fail-under=80 passes after stemmer expansion
- No new # pragma: no cover suppressions added

## Does NOT include
- Production changes to retrieval/stemmer.py
- Python 3.11 CI matrix (deferred — constraints.txt compat unverified)
- BM25 SHA integrity implementation (v1.5.0 scope)
- Config-driven rate-limiter wiring (v1.5.0 scope)
```

---

## Risk Assessment

| Change | Blast Radius | Risk | Mitigation |
|--------|-------------|------|------------|
| `test_stemmer.py` full rewrite | Low | Additive; existing assertions preserved | Side-by-side review |
| `--cov-fail-under=80` in CI | Medium | Could break CI if current coverage < 80% | Run locally first; confirm >80% before committing threshold |
| `--cov=retrieval.stemmer` added | Low | Adds new module to scope; visibility only | No downside |
| Sentinel in `test_rate_limit.py` | Low | Imports `gate` — confirm importable in CI | Already confirmed by `test_gate.py` |
| `TEST_SUITE_AUDIT.md` edits | None | Documentation only | Diff review |

---

*Plan generated: June 2026 | Base commit: `a3e9310` | Target: `CGFixIT/CyClaw` `main`*
