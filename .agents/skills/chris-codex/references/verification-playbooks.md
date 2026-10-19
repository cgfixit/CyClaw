# Verification references

Use `CLAUDE.md` section 5 for direct execution → static checks → Actions → one
targeted file when needed. Use `$verification-specialist` for independent
failure-path acceptance. Each result belongs to a SHA, environment and scope.

Confirm mock fidelity, native platform requirements, skipped dependencies and
adjacent side effects. Ruff F/B/S blocks; broader Ruff is advisory; mypy is
best-effort with `--explicit-package-bases`. Bare pytest proves no coverage.
After publication inspect the actual remote head/current-head checks and
distinguish inherited baseline failures from introduced regressions.
