# Pillow and NeMo: current status and the retired risk acceptance

**Updated 2026-11-01**, against main
`2a8ad88bbf55c84d05df32edd0920f2c2600289e`. The operator's confirmed use remains
**text/RAG with the shipped embedding and reranker models**.
[SECURITY.md](../../SECURITY.md#accepted-dependency-risks) owns the live advisory
register; this memo records the decision, evidence and operator next steps.

## Current decision: use the compatible update already on main

[PR #1784](https://github.com/cgfixit/CyClaw/pull/1784) merged on 2026-10-29 and
replaced the Pillow 12.3.0 acceptance with **Pillow 13.0.0 and FastEmbed 0.9.1**.
NeMo Guardrails remains **0.24.1**. These were the latest PyPI releases of all
three packages when checked on 2026-11-01.

[FastEmbed 0.9.1 metadata](https://pypi.org/pypi/fastembed/0.9.1/json) allows
`pillow>=10.3.0,<14.0` on Python 3.12; 0.9.0 required Pillow below 13.
[NeMo 0.24.1 metadata](https://pypi.org/pypi/nemoguardrails/0.24.1/json) accepts
`fastembed>=0.2.2`, so no NeMo version change is needed to unlock Pillow 13.
The compatible pins are in constraints, the three platform runtime locks and
the Conda profile. The pip-audit Pillow ignore list is removed.

The [Arrow disclosure advisory](https://github.com/python-pillow/Pillow/security/advisories/GHSA-654x-cwwv-5j9c)
now lists Pillow 13.0.0 as patched. This supersedes the earlier advisory metadata,
which included 13.0.0 as affected and listed no patched release. Fresh OSV
version queries on 2026-11-01 returned no advisories for Pillow 13.0.0,
FastEmbed 0.9.1 or NeMo 0.24.1. This is dated advisory evidence, not a guarantee
against undisclosed vulnerabilities.

## How CyClaw uses these dependencies

Pillow is installed for the dependency graph; that does not enable an image
processing feature. Guardrails remains enabled in
[config.yaml](../../config.yaml). Its active NeMo flows use Python checks, add
no LLM-based classifier calls, and retain the documented deterministic floor
when live checks are unavailable.

| Path | Behavior relevant to Pillow, checked 2026-11-01 |
| --- | --- |
| [Query and batch embeddings](../../retrieval/embeddings.py) | Pass strings to the shipped `all-MiniLM-L6-v2` SentenceTransformer. |
| [Reranker](../../retrieval/rerank.py) | Passes string pairs to `cross-encoder/ms-marco-MiniLM-L6-v2`, revision `233902d25c440f23af6f7d6e94d2946bac0bee0a`. |
| [Corpus loader](../../retrieval/indexer.py) | Reads bounded UTF-8 files; shipped extensions are `.md` and `.txt`. It has no PDF extraction, OCR or image decoder. |
| [fsconnect indexing](../../agentic/fsconnect/indexer.py) | Stages bytes and scans text patterns. `.pdf`/`.docx` in its extension list does not implement document extraction. |
| [Telegram media](../../telegram/media.py) | Ships disabled; optional staging stores bounded attachment bytes through fsconnect without decoding or indexing them. |
| [Sync](../../sync/cli.py) | Transfers corpus files and can invoke the existing indexer; it does not decode images. |
| [LLM transport](../../llm/client.py) | Sends prompt strings. Selecting a vision-capable Ollama model alone does not add image inputs or local Pillow decoding to this adapter. |
| [NeMo integration](../../guardrails/integration.py) | The installed FastEmbed provider uses `TextEmbedding`, not `ImageEmbedding`. |
| [LoRA kit](../../tools/lora_finetune/finetune_qwen38.py) | Renders local JSON examples into a text dataset. Arrow-backed text datasets are distinct from Pillow image-to-Arrow export. Training was inspected, not executed. |

No first-party production Python caller of `PIL`, `TarIO`, `ImageFont` or
Pillow Arrow export was found. Absence of a first-party import alone does not
prove dependency behavior. Configurable alternate embedding processors can
interpret URLs, paths or data URIs as images; model selection is trusted
configuration, **not an enforced text-only boundary**.

## Verification on 2026-11-01

A fresh disposable macOS arm64 environment used Python 3.12.14, pip 26.2.2,
the separate hashed Torch lock, then the full hashed macOS runtime lock.
Installed versions included Pillow 13.0.0, FastEmbed 0.9.1, NeMo 0.24.1,
SentenceTransformers 6.1.0, Transformers 5.20.2 and Torch 2.14.1.

- Installation and `pip check` passed. Strict dependency, pin and environment
  checks reported no failures/warnings; the generated lock contract passed.
- The real production NeMo engine, exercised through
  [`guardrails.verify_install`](../../guardrails/verify_install.py), allowed
  benign input and grounded output, and blocked injection input and ungrounded
  output. Socket/DNS operations were refused; no live provider was called.
- Query embeddings returned four 384-dimensional vectors; batch embeddings
  returned four vectors; the shipped reranker returned four scores. Inputs
  were ordinary text, an image URL, a synthetic local image path and a data URI.
  Refusing tripwires around `PIL.Image.open`,
  `transformers.image_utils.load_image`, `socket.connect` and
  `socket.getaddrinfo` recorded zero calls.
- The embedding snapshot was `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`;
  the reranker used the pinned revision above.
- The corpus probe excluded PDF filenames by default. Explicitly allowing
  `.pdf` read an ASCII placeholder as raw UTF-8 and rejected invalid UTF-8;
  this was not real PDF extraction.

The initial uv runtime-lock install rejected the split lock's unpinned
transitive Torch reference in hash mode. The documented pip install accepted
the already installed hashed Torch. No hash or constraint was weakened.

This evidence is separate from hosted CI: #1784's final head
`16166c2c1cc222afc721ede9cd091ebf099d8a15` had 69 successful checks,
four skips and one neutral result. Reviewed main had 48 successes and two
skips. Neither count turns skipped or neutral checks into passes.

No full local suite, malicious payload, alternate model, live provider, UI
flow, production service or native Linux/Windows artifact was exercised.
Static inspection covered the other paths in the table. Compatibility evidence
is bounded to these checks; it cannot guarantee every application path.

## Operator next steps

1. Check the versions in the interpreter that actually runs CyClaw, rather than
   assuming a Git update changed an existing environment:

   ```bash
   /path/to/cyclaw-venv/bin/python -c 'from importlib.metadata import version; print({p: version(p) for p in ("Pillow", "fastembed", "nemoguardrails")})'
   ```

2. If it still has Pillow 12.3.0/FastEmbed 0.9.0, update through the documented
   Python 3.12 [platform lock procedure](../../setup-guide.md), preserving
   operator configuration, corpus and credentials. Verify in a replacement
   environment before switching the service. Do not force one wheel past the
   dependency constraints or use an unconstrained upgrade.
3. Run `python -m pip check` and `python -m guardrails.verify_install`
   with that environment, then exercise the affected app query path before
   adopting it. If the current compatible trio is already installed and these
   checks pass, no further Pillow/NeMo bump is indicated by this review.

The old acceptance's November 23 review deadline is **retired with the
acceptance**, not a pending renewal. Continue normal advisory monitoring.
Reassess on a newly affected version, rollback below the fixed version,
a changed model/processor, or new image/PDF extraction, OCR, thumbnail, EXIF,
font, Pillow archive/PDF/Arrow or alignment behavior. Cached/offline model
loading and telemetry suppression do not make a vulnerable decoder safe.

The November 1 inspection did not locate a listener on port 8787 or identify
the operator's active installation. Repository state and this disposable
verification environment do not establish which versions are deployed.

## Historical decision: October 23–29

At the October 23 review, main was
`ae767ed9c6ecd64112993462370433c81e03707c`. The FastEmbed cap prevented a
compatible Pillow 13 install. Retaining a bounded, exact-advisory acceptance
for the confirmed text/RAG use was proportionate; forcing an unsupported
installation or removing NeMo was not justified. The earlier probe exercised
the same text models with Pillow 12.3.0/FastEmbed 0.9.0 and recorded no
image-loader or socket/DNS calls. It was an existing disposable environment,
not a fresh installation or proof of the deployed app.

Pillow exposure was broader than image attachments: font operations,
`PIL.TarIO`, PDF append/save and image-to-Arrow export required their own
reachability assessment. Relevant upstream examples are the
[font overflow](https://github.com/python-pillow/Pillow/security/advisories/GHSA-4rm8-3hmm-39fg),
[TarIO CPU loop](https://github.com/python-pillow/Pillow/security/advisories/GHSA-3j72-p6qg-6xp7)
and [FPX overflow](https://github.com/python-pillow/Pillow/security/advisories/GHSA-5x8w-8jj5-q52h).
FPX recognition is content-based, so a filename suffix allowlist would not have
been an adequate decoding boundary.

[PR #1768](https://github.com/cgfixit/CyClaw/pull/1768) preserved that reasoning.
The earlier Pillow-only attempts [#1742](https://github.com/cgfixit/CyClaw/pull/1742)
and [#1766](https://github.com/cgfixit/CyClaw/pull/1766) closed without merge.
FastEmbed 0.9.1 removed the compatibility block, and #1784 retired the acceptance.
The old rationale and deadlines must not be used to justify a downgrade or
new advisory ignore.
