# Why CyClaw temporarily accepts Pillow exposure

Decision reviewed **2026-10-23**, against main
`ae767ed9c6ecd64112993462370433c81e03707c`. The operator confirmed the intended
use: **text/RAG with the shipped embedding and reranker models**.

For that use, keeping the compatible dependency set and a bounded Pillow risk
acceptance is proportionate. Pillow remains affected; this is a deployment
decision, not a patched dependency or a claim that every supported configuration
is safe. [SECURITY.md](../../SECURITY.md#accepted-dependency-risks) owns the exact
accepted advisories and review dates; this memo explains the reasoning.

## Why keep the dependency set

At review time, Pillow was 12.3.0 and the latest FastEmbed release was 0.9.0.
[FastEmbed's Python 3.12 metadata](https://pypi.org/pypi/fastembed/0.9.0/json)
requires `pillow>=10.3.0,<13.0`. NeMo brings FastEmbed into the base runtime.
The Pillow 13 attempts in [#1742](https://github.com/cgfixit/CyClaw/pull/1742)
and [#1766](https://github.com/cgfixit/CyClaw/pull/1766) were closed without merge.

Forcing Pillow 13 past that constraint would leave an unsupported installation.
Removing NeMo to eliminate an unused Pillow surface would trade an existing
protection for a dependency change without an established reachable operation.
Neither is justified for the confirmed text/RAG setup. Prefer a supported
compatible upgrade when available, then reassess each advisory separately.

## What the current paths do

| Path | Behavior relevant to Pillow |
| --- | --- |
| [Query and batch embeddings](../../retrieval/embeddings.py) | Pass strings to the shipped `all-MiniLM-L6-v2` SentenceTransformer. |
| [Reranker](../../retrieval/rerank.py) | Passes string pairs to `cross-encoder/ms-marco-MiniLM-L6-v2`, revision `233902d25c440f23af6f7d6e94d2946bac0bee0a`. |
| [Corpus loader](../../retrieval/indexer.py) | Reads bounded regular files and decodes UTF-8; shipped extensions are `.md` and `.txt`. It has no PDF parser, OCR or image decoder. |
| [fsconnect indexing](../../agentic/fsconnect/indexer.py) | Stages bytes and scans text patterns. `.pdf`/`.docx` in its extension list does not implement document extraction. |
| [Telegram media](../../telegram/media.py) | Ships disabled; when explicitly enabled, stages bounded attachment bytes through fsconnect without decoding or indexing them. |
| [Sync](../../sync/cli.py) | Transfers corpus files and can invoke the existing indexer; it does not decode images. |
| [LLM transport](../../llm/client.py) | Sends prompt strings. Selecting a vision-capable Ollama model alone does not add image inputs or local Pillow decoding to this adapter. |
| [NeMo integration](../../guardrails/integration.py) | Uses text rails; its installed FastEmbed provider uses `TextEmbedding`, not `ImageEmbedding`. |
| [LoRA kit](../../tools/lora_finetune/finetune_qwen38.py) | Renders local JSON examples into a text dataset. Arrow-backed text datasets are distinct from Pillow image-to-Arrow export. Training was inspected, not executed. |

No first-party production Python caller of `PIL`, `TarIO`, `ImageFont`, or Pillow
Arrow export was found. The inspected dependency environment had no `olefile`
and no `PILLOW_ALIGNMENT` setting. These observations support the specific
deployment; absence of a first-party import alone is not proof about dependency
behavior.

## Pillow exposure extends beyond image attachments

The affected API families include image decoding/encoding, font operations,
Pillow's archive reader, PDF append/save operations, and image-to-Arrow export:

- [Font integer overflow](https://github.com/python-pillow/Pillow/security/advisories/GHSA-4rm8-3hmm-39fg)
  requires Pillow font operations, not ordinary model tokenization.
- [TarIO CPU loop](https://github.com/python-pillow/Pillow/security/advisories/GHSA-3j72-p6qg-6xp7)
  requires Pillow's tar-member reader, not generic file sync or Python `tarfile`.
- [Arrow disclosure](https://github.com/python-pillow/Pillow/security/advisories/GHSA-654x-cwwv-5j9c)
  requires Pillow image export with `PILLOW_ALIGNMENT > 1`. At review time,
  upstream included **13.0.0 as affected** and listed **no patched release**.
- [FPX heap overflow](https://github.com/python-pillow/Pillow/security/advisories/GHSA-5x8w-8jj5-q52h)
  requires image decoding with optional `olefile`. Recognition is content-based;
  a filename extension allowlist is not an adequate decoding boundary.

Do not describe these as reachable only through image attachments, or assume
Pillow 13 fixes every accepted advisory. [#1762](https://github.com/cgfixit/CyClaw/pull/1762)
at `3cc6c8288ba918bd591e01843923472e3a0d17c5` improves the documented model
boundary, but retains those overbroad summary statements. Its proposed Arrow/FPX
exceptions are separate from main's original 35-ID list. This memo adds no
exception and changes no scanner suppression.

## When to reopen the decision

Review at the **next FastEmbed release or 2026-11-23, whichever comes first**.
The deadline is manual; the pip-audit ignores do not automatically expire.
Remove an exception only after checking that advisory's fixed versions or
recording fresh evidence supporting its disposition.

Reassess sooner when adding image/PDF extraction, OCR, thumbnails, EXIF handling,
font rendering, Pillow archive/PDF/Arrow operations, `olefile`, or a non-default
Pillow alignment. A new corpus extension is a reason to inspect the path; it
does not itself add a parser.

Changing the embedding/reranker model or processor also requires reassessment.
The shared adapters pass strings to configurable models. An image-capable
processor can interpret a URL, path or data URI as an image. Model selection is
trusted configuration, **not an enforced text-only boundary**. Cached/offline
model loading and telemetry suppression do not make a vulnerable decoder safe.

For the confirmed deployment, a dependency fork, new isolation service or model
allowlist is not justified by the evidence found. A small regression probe of
image-looking text through both embedding APIs and reranking would protect the
actual assumption during future dependency/model changes; this memo does not
add such a CI gate.

## Evidence and limits

On 2026-10-23, the current retrieval source was exercised in an existing
disposable PR dependency environment on macOS 27.0.1 arm64 / Python 3.12.14:
Pillow 12.3.0, FastEmbed 0.9.0, SentenceTransformers 6.1.0, Transformers 5.20.2,
Torch 2.14.1 and NeMo 0.24.1. This was neither a fresh installation nor the
operator's running service. The dependency PR changes no exercised retrieval
behavior; its only retrieval diff is a Torch-version docstring.

The embedding snapshot was `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`; the
reranker used the pinned revision above. Ordinary text, an image URL, a synthetic
local image path and a data URI produced four 384-dimensional query vectors,
four batch vectors and four reranker scores. Refusing tripwires around
`PIL.Image.open`, `transformers.image_utils.load_image`, `socket.connect` and
`socket.getaddrinfo` recorded **zero calls** during those operations.

The corpus probe confirmed that defaults exclude PDF filenames. Explicitly
allowing `.pdf` read an ASCII placeholder as raw UTF-8 and rejected invalid
UTF-8; this did not test real PDF extraction. Static inspection covered the
other paths in the table.

No malicious payloads, alternate models, live providers, full suites, production
service, or native Linux/Windows artifacts were exercised. This is bounded
evidence for the confirmed text/RAG use, not exhaustive security clearance.
