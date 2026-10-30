# Unicode probe folding

`confusables-17.0.0.txt` is the unmodified Unicode 17.0.0 TR39 mapping from
[Unicode](https://unicode.org/Public/17.0.0/security/confusables.txt).
SHA-256: `091c7f82fc39ef208faf8f94d29c244de99254675e09de163160c810d13ef22a`.
Unicode License v3 is included in `LICENSE.txt`.

Regenerate with `python utils/unicode_data/generate.py`; it verifies the
source digest and writes `utils/_unicode_confusables.py`. Runtime uses that
mapping without network/data-file access. Updates require explicit version
and digest changes, regeneration, and benign multilingual evaluation.

This ASCII-preserving fold uses TR39 data, not the full skeleton algorithm
(which changes ASCII `m` to `rn`). Non-ASCII skeletons with exactly one
ASCII-letter origin restore that letter; ambiguous skeletons retain their
official value. Python supplies normalization/categories independently of
the pinned confusables version.

The sanitizer decodes ASCII Tag characters, removes format characters, Tags and
variation selectors, applies NFKD, removes nonspacing marks, applies NFKC and
case-folding, then folds confusables. It checks both that normalized copy with
punctuation retained and a second probe that turns runs of `_`, `-`, `.`, and
`·` into spaces, alongside the original text. Only inspection copies are
folded. Queries that pass remain unchanged. Corpus matches
in the raw text are replaced locally; if an obfuscated match remains after that
pass, the entire chunk becomes `[FILTERED]`. Benign chunks remain unchanged.
Soul and memory scanning import this same normalizer. Scheduled OpenTweet
screening also uses it with separator folding disabled so URL punctuation
remains visible.

Accent removal and homoglyph folding can make distinct natural-language text
coincide. They do not detect every possible prompt injection. Operator regexes
still determine rejection, and the filter is not a substitute for capability
or authorization boundaries. Literal punctuation regexes still run against raw
query/chunk text before the folded pass.
