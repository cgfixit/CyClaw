# Unicode probe folding

`confusables-17.0.0.txt` is the unmodified Unicode 17.0.0 TR39 mapping from
[Unicode](https://unicode.org/Public/17.0.0/security/confusables.txt).
SHA-256: `091c7f82fc39ef208faf8f94d29c244de99254675e09de163160c810d13ef22a`.
Unicode License v3 is included in `LICENSE.txt`.

Run `python utils/unicode_data/generate.py` from the repository to reproduce
`utils/_unicode_confusables.py`. The generator checks the source digest. The
runtime imports the generated Python mapping, so installed packages require no
network fetch or external Unicode data file. Updates must deliberately change
the source version and digest, regenerate, and evaluate benign multilingual text.

This is a TR39-data-derived ASCII-preserving fold, **not** the full TR39 skeleton
algorithm. Full skeletons change ASCII `m` to `rn`, which would change the
meaning of existing operator regexes. ASCII input remains unchanged by this
mapping; non-ASCII characters map through the official table, restoring an
ASCII letter when its skeleton has exactly one ASCII-letter origin. Ambiguous
skeletons retain their official value. Python's Unicode database supplies
normalization and character categories; the confusables data version is pinned
independently.

The sanitizer decodes ASCII Tag characters, removes format characters, Tags and
variation selectors, applies NFKD, removes nonspacing marks, applies NFKC and case-folding, folds
confusables, and turns runs of `_`, `-`, `.`, and `·` into spaces. Only an
inspection copy is folded. Queries that pass remain unchanged. Corpus matches
in the raw text are replaced locally; if an obfuscated match remains after that
pass, the entire chunk becomes `[FILTERED]`. Benign chunks remain unchanged.
Soul and memory scanning import this same normalizer.

Accent removal and homoglyph folding can make distinct natural-language text
coincide. They do not detect every possible prompt injection. Operator regexes
still determine rejection, and the filter is not a substitute for capability
or authorization boundaries. Literal punctuation regexes still run against raw
query/chunk text before the folded pass.
