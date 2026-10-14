# Preserve behavior while simplifying

Use `$refactor`. Record the structural defect and a direct comparable baseline;
trace callers/public contracts before a narrow cleanup. Prefer deletion/reuse to
speculative interfaces. Keep formatting/dependencies/behavior changes separate.
Repeat baseline probes, inspect adjacent paths and invariants, and use current
verification policy. Reclassify an intentional behavior change. Report evidence
of preservation, measured performance when claimed, and limits.
