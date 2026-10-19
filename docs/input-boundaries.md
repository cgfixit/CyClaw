# Corpus input boundaries

## Corpus ingestion

`corpus.max_file_bytes` is a positive integer, defaulting to 10485760 (10 MiB).
The indexer skips oversized files before reading and reads at most the cap plus
one byte to detect growth during the read. It rejects special files and UTF-8
decode failures. It never silently truncates a document. Empty resulting corpora
fail with `CorpusEmptyError`. This is a per-file bound, not a total corpus budget.
Symlinks resolving outside the corpus root are excluded.

Chunks use the [Unicode probe policy](../utils/unicode_data/README.md). A chunk
containing an instruction found only after normalization is replaced in full;
normalization never rewrites accepted benign corpus content.
