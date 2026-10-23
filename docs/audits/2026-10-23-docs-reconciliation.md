# Documentation reconciliation, 2026-10-23

## Scope and provenance

Documentation-only cleanup for [#1745](https://github.com/cgfixit/CyClaw/issues/1745).
The initial review covered 176 tracked docs files at
[cb0a58e](https://github.com/cgfixit/CyClaw/commit/cb0a58e9204a0a3f25bd28903d095e9ddf05feda).
The cleanup starts from
[246e406](https://github.com/cgfixit/CyClaw/commit/246e406d27beb097c3ecab3ba188a11c109b86db),
after the Git-hook and platform-script lint changes. README-only PR #1747 was
open during preparation; its overlapping docs index and NeMo overview edits
must be preserved when merging.

No runtime feature, configuration default, dependency, workflow, provider call,
credential, installed service or security policy is changed. The removed Python
files are an unsupported docs prototype and obsolete verifier copies under the
old memory folder; maintained skills and product entrypoints remain untouched.

## Dispositions and historical evidence

[Remaining work](../plans/remaining_work.md) records every reviewed area as
existing tracking, unverified acceptance, a deferred proposal, completed work or
retired architecture. It also preserves independent ideas from the older archive
such as corpus-source eligibility, cross-file deduplication, OS inventory,
connector research and evidence-retention hypotheses. No new feature is approved.

[The history index](../ARCHIVE_AND_ROADMAP.md#retired-plans) links every removed
source file to its complete text at the cleanup base. Full old versions of the
rewritten archive and platform plans are likewise linked. These Git references
preserve research and rationale without leaving obsolete instructions in the
active docs tree. Offline readers need the base commit to inspect removed files.

The unique July 9 swarm PDF moved to the audit collection without changing its
bytes. The legacy SandboxWss PDF was byte-identical to the retained audit copy.
The three removed harness how-to PDFs remain accessible through the history
index; they describe removed endpoints, not current operator commands.

The remaining dated audits are preserved. Changes within them are limited to
historical-status clarification or links to retired sources. The June 30 tracked
memory audit, session-note destination, small setup redirects and maintained
connector/authentication/memory/NeMo contracts remain.

All 35 screenshots/images and both videos remain byte-identical. Their
[index](../screenshots/README.md) separates current references from historical
captures. Lack of an in-repository reference is not proof of no external use.
The older unreferenced video was not replayed; retention avoids inventing a
content-based deletion conclusion.

## Audit-export prototype

The initial review exercised the former docs script using disposable synthetic
files. The observations are preserved here after removing the unsupported script:

| Probe / inspection | Result |
|---|---|
| Documented flag-only invocation | Usage error; implementation required an export subcommand. |
| Ordinary synthetic export and verify | Succeeded. |
| Empty file manifest, bogus manifest digest, audit log without chain file | Warned that the chain was missing, then reported Bundle integrity: VERIFIED and returned zero. |
| Negative retention days, dry-run only | Accepted. |
| Purge implementation, static inspection | Read/rewrite without atomic replacement or writer coordination; no destructive purge was run. |

The manifest's own digest was not validated. An export-time chain stored in the
same bundle does not prove the original log history was not rewritten. This
prototype was not an integrated product entrypoint and does not establish that
the live logger has tamper-evident auditing. Future reconciliation, retention and
trusted anchoring require separate design and authorization.

## Completed console work

[Console UX notes](../console-ux.md) preserve the completed first-run, advanced
mode, error vocabulary, health disclosure, elapsed-time and route/model work,
including the hidden-attribute/CSS finding and original PR provenance. No new
browser acceptance or complete cross-browser matrix is claimed.

## Evaluation-corpus change

The optional docs report in tests/ci_rag_smoke.py and the reranker bakeoff can
copy Markdown from docs/ into their temporary corpus. This cleanup removes
obsolete Markdown, condenses plans and adds status/evidence indexes, so that
corpus changes even though retrieval code and the default data/corpus content
do not. Compare results only with the source revision and chosen roots recorded;
prior docs-derived scores are not directly interchangeable with this candidate.
No model-quality improvement is claimed and no model evaluation is rerun here.

## Verification limits

The initial review used source tracing, issue state, reference scans, PDF text,
screenshot inspection and the synthetic prototype probes above. Its documentation
checker had zero drift despite the semantic contradictions being corrected.

The cleanup uses documentation consistency, link/reference checks, artifact hash
comparison and diff review. Exact commands, candidate commit and hosted CI state
are recorded in the draft PR. No broad local application suite, native acceptance,
live provider, bot posting or video playback is implied by those checks. Runtime
findings remain deferred in #1745 and #1657; this record does not close them.
