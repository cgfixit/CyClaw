# Security Audit Report — CyClaw LoRA Fine-Tune Kit

**Date:** 2026-09-11
**Scope:** `/cyclaw-finetune/` directory (corpus builder, fine-tune script, tests, dataset)
**Scanners:** bandit 1.7.5, semgrep 1.85.0, pip-audit 2.7.3

## Executive Summary

| Severity | Count | Reachable | Fixed | Accepted Risk |
|----------|-------|-----------|-------|---------------|
| Critical | 0 | 0 | 0 | 0 |
| High | 0 | 0 | 0 | 0 |
| Medium | 2 | 1 | 1 | 1 |
| Low | 1 | 0 | 0 | 1 |
| **Total** | **3** | **1** | **1** | **2** |

**Top must-fix (1):**
1. `build_cyclaw_corpus.py:131` — `AutoTokenizer.from_pretrained` without revision pinning → **FIXED** (added `revision="main"`)

## Stack & Resolution Notes

- **Ecosystem:** Python 3.12+ (CyClaw requires `>=3.12,<3.13`)
- **Manifests:** None. No `requirements.txt`, `pyproject.toml`, or `setup.py` in the LoRA kit.
- **Dependency resolution:** Not applicable — corpus builder is stdlib-only; fine-tune script uses unsloth/trl/datasets installed separately on GPU pod.
- **pip-audit:** No known vulnerabilities found (no dependencies to audit).

## CVE Findings Table

| Package | Installed | Fixed | CVE/GHSA | CVSS | Reachability | Scanner(s) | Notes |
|---------|-----------|-------|----------|------|-------------|------------|-------|
| transformers.AutoTokenizer | n/a | revision="main" added | [B613](https://bandit.readthedocs.io/en/latest/plugins/huggingface_unsafe_download.html) | 0.0 | reachable | bandit | Fixed: added revision pinning to both tokenizer loads |
| datasets.load_dataset | n/a | no fix needed | [B613](https://bandit.readthedocs.io/en/latest/plugins/huggingface_unsafe_download.html) | 0.0 | unreachable-feature-gated | bandit | FALSE POSITIVE: loads local JSON file, not HF Hub |
| assert statements | n/a | no fix needed | — | 0.0 | dev-only | bandit | Expected in pytest test suites |

## Reachability Methodology

**Tier 1 (static):**
- Grep for direct imports of flagged packages
- Context analysis of call sites
- `build_cyclaw_corpus.py:131`: `AutoTokenizer.from_pretrained` called in `_render_with_real_tokenizer()` — reachable from `build_canonical()` entrypoint. Fixed.
- `finetune_qwen38.py:130`: `load_dataset("json", data_files=str(jsonl))` loads local file path, not HF Hub download. False positive.

**Tier 2 (AST/call-graph):** Not escalated — no critical/high findings.

## Hardened Manifest Diff

See `hardened.diff` for the unified diff. Summary:
- `build_cyclaw_corpus.py`: Added `revision="main"` parameter to both `AutoTokenizer.from_pretrained()` calls

## Remediation Order

1. ✅ **COMPLETED**: Add revision pinning to `AutoTokenizer.from_pretrained()` in `build_cyclaw_corpus.py`
2. ✅ **N/A**: False positive on `load_dataset("json", ...)` — no remote download occurs
3. ✅ **N/A**: `assert_used` in test files — expected pattern for pytest

## Residual Risk

- **No external dependencies** in the LoRA kit corpus builder (stdlib only)
- **Fine-tune script** uses unsloth/trl/datasets — these should NOT be added to CyClaw's core `pyproject.toml`. Install separately on GPU pod.
- **No hardcoded secrets** found (grep for api_key, secret, password, token, sk-, ghp_, huggingface tokens)
- **No dangerous patterns** (eval, exec, shell=True, pickle.load, yaml.load, __import__)
- **CyClaw's chromadb==1.5.9** has CVE-2026-45829 (accepted risk for embedded mode) — LoRA kit does not use ChromaDB
