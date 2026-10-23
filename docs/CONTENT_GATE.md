# Local gate for exact consumed text

CyClaw can hold untrusted corpus and returned retrieval content with an
operator-installed [yara-gate](https://github.com/cgfixit/yara-gate) CLI.
This is optional and absent from shipped configuration. It adds no Python
dependency, network download, vendor update, or model call to CyClaw.

## Enable the local gate

Add this block under the existing `policy` mapping in your configuration.
Use absolute paths to a trusted local executable and reviewed rules tree.
Replace both identity placeholders with values you independently approve;
the placeholders intentionally fail closed.

```yaml
policy:
  content_gate:
    enabled: true
    executable: /absolute/path/to/yara-gate
    rules: /absolute/path/to/reviewed-rules
    engine_version: REPLACE_WITH_APPROVED_ENGINE_VERSION
    ruleset_sha256: REPLACE_WITH_APPROVED_64_CHARACTER_SHA256
```

The scanner must implement `scan <directory> --json --policy agent-ingest
--home <temporary-home> --rules <rules>`, with one JSON Lines receipt for
each file. Review its version, provenance, rule coverage and benign controls
before approving the receipt's `engine_version` and `ruleset_sha256` values.
An unexpected identity is an error; CyClaw never learns or approves a new
identity from the scan it is deciding whether to trust. Review and repin
after an intentional rule or engine update. Zero skipped rule files is required.

Restart the gateway and MCP process after editing configuration. Rebuild to
apply ingress checks to the complete corpus. Already loaded indexes receive
fresh result checks on every search even before a rebuild. Explicit
`enabled: false` or an absent block disables the gate; quoted booleans,
null enablement and malformed enabled settings are incomplete scans.

## What is approved

1. **Ingestion:** `load_corpus` retains strictly decoded UTF-8 strings from
   its bounded reads. Before chunking, CyClaw scans their exact UTF-8 encoding
   and source fields. After chunking and sanitization, it checks the exact
   chunk strings and generated tag strings before resetting the vector writer
   or publishing BM25. A refusal preserves the prior generation. Existing
   sanitizer replacements still apply, including inside benign quotations.
2. **Public searches:** semantic and keyword results are checked before return.
   Hybrid results are checked again after optional memory fusion. Text, source,
   tags, source hash and mode are scanned as individual strings, plus their
   JSON representation. One rejected field holds the whole batch, preserving
   score/order/source consistency. A source hash is provenance, not approval.
3. **Graph consumers:** results are checked before reranking. Local, offline
   and both provider nodes also check clipped bodies, sources and the final
   rendered external-data context block. Trusted query, soul and instruction
   framing are outside this content scan. Context forwarded to a provider
   retains the existing consent, destination and context-forwarding gates.
4. **MCP:** all three modes check decoded result fields and the serialized
   returned chunk array, using the stdio writer's JSON serialization defaults.
   The query echo and protocol envelope are outside the external-content
   check. There is still no MCP generation or sampling capability.

Each check snapshots retained strings into an owner-private temporary directory
as `.txt` files and consumes those same strings afterward. Source paths are not
reopened after approval. Each field has its own file so a documentary prefix in
one field cannot exempt an override in another. Checks repeat after a consumer
transformation; there is no persistent approval cache or raw-file approval token
that can authorize a different view. This integration covers CyClaw's current
UTF-8 text corpus and RAG MCP server, not arbitrary binary extraction or an
outbound MCP client.

## Refusal and resource limits

Only complete `clean` receipts under `agent-ingest`, with no findings or advisory,
permit delivery. Every digest must match the retained bytes exactly once, every
rule/engine identity must match configuration, and individual and aggregate
process exits must agree. Advisory findings are held by `agent-ingest` without
changing their finding severity.

`CONTENT_GATE_BLOCKED` denotes a verified block. `CONTENT_GATE_INCOMPLETE` covers
timeout, missing executable/rules, malformed/partial/duplicate output, changed
identity, skipped rules, digest mismatch and other scanner failures. Search
methods raise a typed `RAGError` subclass; hybrid's normal retrieval degradation
does not catch it. MCP returns JSON-RPC `-32000` and audits the failure. Graph
refusals reach the existing audit node with empty answer/sources and no rerank,
generation, provider hook or external fallback. Errors contain fixed messages,
without sample bytes, scanner output or source paths.

Each string is limited to 10 MiB of UTF-8. Scans batch at most 512 distinct
strings or 64 MiB, with a 30-second process timeout and a 4 MiB accepted report
limit per batch. Larger corpora use successive batches. Temporary homes, reports
and cache directories are removed afterward; the rules tree is read-only to
the scanning path. Temporary storage and process creation must be available.

Repeated boundary checks add local subprocess/compilation cost. There is no
production throughput measurement or cross-request caching in this change.
YARA signatures are a supplementary detection layer: a clean result does not
prove that text is safe, true or free of semantic prompt injection. Keep the
graph, consent, endpoint, isolation and tool-authority controls in place.

## Verification

See the dated [implementation evidence](audits/2026-10-23-exact-consumed-text-gate.md)
for baseline, pinned scanner identity, inert positives, benign controls, failure
paths and the distinction between real scanner and mocked model/storage evidence.
