# Exact consumed text: implementation evidence

Verified on October 23, 2026, on macOS ARM64 with Python 3.12.12. CyClaw base:
`ae767ed9c6ecd64112993462370433c81e03707c`, branch `codex/exact-consumed-text-gate`.
The operator's existing checkouts had unrelated changes and were preserved;
implementation and probes used a fresh clone and disposable storage.

## Baseline and changed boundary

A separate export of the base reproduced three ungated paths with inert text:
MCP returned an override phrase in a search hit, the local answer node included
it in a mock model's prompt, and indexing published an override introduced by
a controlled sanitizer replacement. The unsupported `content_gate` settings
were ignored on that base. These are consumer-boundary observations, not a
claim that the legacy sanitizer failed to recognize that literal phrase.

The optional [content gate](../CONTENT_GATE.md) now approves retained corpus
strings and post-sanitizer chunks, public semantic/keyword/hybrid results after
memory fusion, and final graph/MCP external-data views. Only complete clean
receipts with the configured engine/rule identity and matching byte digests
permit consumption. Refusals cannot become a degradable empty retrieval and
then invoke a model. No graph nodes or edges changed.

## Real scanner identity and isolation

The real CLI came from yara-gate commit
`6502979e6fd8007bd5b159cf432feec7d9c95b6c`, the unmerged quotation-suppression
[draft PR #47](https://github.com/cgfixit/yara-gate/pull/47). Its locked YARA-X
engine was `1.22.0`; the complete copied local pack had 32 rules and zero skips.
Approved ruleset fingerprint:
`cd7577ff627ef3e32a42b190c2516fe7a48e713703c711be17df83ebbc43efce`.

Each adapter call used private UTF-8 snapshots, a fresh gate home and cache,
and the disposable copied rules tree. No vendor download, target execution,
referenced URL fetch, provider transport or operator gate home was used.
An initial copy containing only `.yar` files omitted four `.yara` files: it
produced a different fingerprint, and the adapter refused even benign controls
as incomplete. Copying the complete pack restored the approved fingerprint.
The expected identity was never changed to accept the incomplete copy.

## Direct runtime results

The maintained `tests/test_content_gate.py` executed 50 focused cases: 27 used
the real CLI and 23 exercised forged receipts/configuration and malformed
results. All passed on the final Python source. The final real-scanner run
took 9.89 seconds; this is test duration, not a production throughput estimate.

| Boundary | Observed result |
| --- | --- |
| Literal override and quotation followed by a separate override | Held under `agent-ingest`; advisory finding promoted to overall block |
| Orchard prose and documentary quotation | Allowed by the real gate |
| Semantic, keyword and hybrid result bodies, source names and tags | Inert positives held in all nine combinations; MCP returns typed error without the positive text |
| Memory-fusion hit, including already-confirmed provider selection | Blocked and wrong-identity scans both reach one graph audit with empty answer/sources; no rerank, model call or provider hook |
| Raw retained corpus and controlled post-sanitizer override | Held before obtaining/resetting the vector writer; previous BM25 generation unchanged |
| Benign ingestion and path mutation after approval | Actual build succeeds with stub embeddings/vector writer; BM25 and vector-add use retained approved content even after on-disk replacement |
| Local, offline, Grok and Claude consumer nodes | Benign prose and quotation reach mock clients; override reaches none; approved rendered context is present verbatim in the generated prompt |
| Extracted view of a source-approved quotation | Bare override is independently held at final context consumption |
| MCP benign controls in all three modes | Exact decoded text returned; sampling remains absent |
| Receipt/process failures | Missing/duplicate records, altered digest/identity, skipped rules, incomplete/advisory/nonempty findings, malformed output, wrong exit and timeout all refuse |

The real legacy sanitizer runs in the benign-ingestion cases: it may replace
quoted phrases with `[FILTERED]`. The adapter approves the resulting strings
separately; the gate's quotation control is also exercised directly and at
all four model consumers without relying on that replacement.

## Commands and static evidence

Use a Python 3.12 environment with the affected runtime/test tools installed
under `constraints.txt`. The focused environment did not install or download
Torch, ChromaDB models, sentence-transformers models or provider credentials.
Set the four identity variables to the independently reviewed local installation:

```sh
export CYCLAW_YARA_GATE=/absolute/path/to/yara-gate
export CYCLAW_YARA_RULES=/absolute/path/to/complete-disposable-rules-copy
export CYCLAW_YARA_SHA256=cd7577ff627ef3e32a42b190c2516fe7a48e713703c711be17df83ebbc43efce
export CYCLAW_YARA_ENGINE=1.22.0
python -m pytest tests/test_content_gate.py -v --tb=short
GROK_API_KEY=dummy python -m pytest tests/test_due_diligence_invariants.py tests/test_mcp_server.py -v --tb=short
python .claude/skills/invariant-guard/check_invariants.py
ruff check --select E,F,I,B,C4,UP,S --ignore E501 retrieval/content_gate.py tests/test_content_gate.py graph.py mcp_hybrid_server.py retrieval/indexer.py retrieval/hybrid_search.py tests/test_mcp_server.py
mypy --explicit-package-bases --follow-imports=silent --strict retrieval/content_gate.py
git diff --check
```

The existing focused invariant/MCP files passed 80 cases. Static invariant
guard passed all 46 checks. Ruff 0.17.1 passed the changed Python files;
mypy 2.4.0 strict passed the new adapter. Strict checking all four older
affected modules plus the adapter reports 51 errors, the same count and
normalized messages as the separate base export (existing annotations and
missing heavy dependencies/stubs). This is not a whole-project type-check pass.

The 27 real-scanner cases explicitly skip without the four identity variables;
default CI does not install or approve the optional external scanner. The
receipt/configuration cases and ordinary regression suites remain available
without it. Broad suites and platform coverage are left to hosted Actions.

The tested Python source digest is `111c6e22da8d4c5545e3f6dae4480020f2dbc43b200612a03bf8357f7fa592ef`:
SHA-256 of each sorted repository-relative filename, NUL, file bytes, NUL for
`graph.py`, `mcp_hybrid_server.py`, `retrieval/content_gate.py`,
`retrieval/hybrid_search.py`, `retrieval/indexer.py`, `tests/test_content_gate.py`
and `tests/test_mcp_server.py`. Documentation is excluded from that digest.

## Invariant and verification limits

| Contract | Before and after |
| --- | --- |
| I1: RAG first | Unconditional `retrieve` entry retained |
| I2: topology is policy | Same 12 nodes, routers and edges; refusal uses the existing input-rail path |
| I3: external consent | Provider construction, per-request consent, destination checks and context-forwarding flags unchanged |
| I4: audit convergence | Refusals converge on existing graph audit; MCP audits an error before returning it |
| I5: soul governance | Soul writes, adoption and off-box exclusion unchanged |
| I6: module isolation | No core import of out-of-band packages; telemetry ordering retained |

Model clients, embeddings and the vector writer were stubs; the real CLI,
YARA-X rules, chunk/sanitizer boundaries, BM25 publication, search methods,
compiled graph routing and MCP handler ran. No live inference, authenticated
HTTP/browser/native acceptance, full embedding/vector integration, Windows or
Linux execution was performed locally. The gate is off by default and requires
operator installation and approval of scanner identities. Synthetic positives
and benign controls do not establish a production false-positive rate or
comprehensive prompt-injection prevention. Both draft PRs remain unmerged.
