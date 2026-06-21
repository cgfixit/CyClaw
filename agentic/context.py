"""Higher-level read-only GitHub *context* fetchers for human/agent consumption.

Thin, audit-friendly wrappers over ``agentic.gh_client.run_read`` that assemble
structured context bundles (a PR plus its diff, an issue, a repo overview). These
are pure reads -- nothing here mutates GitHub state, and the module is never
imported by the request path.

Each underlying ``run_read`` call already emits its own audit event, so these
wrappers do not double-log; they only shape the returned data.
"""

from __future__ import annotations

from agentic.config import AgenticConfig
from agentic.gh_client import DEFAULT_MIN_GH, run_read
from utils.errors import AgenticError


def _guard_read_op(cfg: AgenticConfig, op: str) -> None:
    """Reject ops the operator has not allow-listed in config.allowed_read_ops."""
    if op not in cfg.allowed_read_ops:
        raise AgenticError(
            f"read op {op!r} is not in agentic.allowed_read_ops",
            details={"op": op, "allowed": list(cfg.allowed_read_ops)},
        )


def fetch_pr_context(cfg: AgenticConfig, number: int, *, include_diff: bool = True) -> dict:
    """Return a PR's metadata and (optionally) its diff as one bundle."""
    _guard_read_op(cfg, "pr_view")
    bundle: dict = {"repo": cfg.repo, "number": number}
    bundle["pr"] = run_read(
        "pr_view", cfg.repo, number=number, min_version=cfg.gh_min_tuple
    )["data"]
    if include_diff:
        _guard_read_op(cfg, "pr_diff")
        bundle["diff"] = run_read(
            "pr_diff", cfg.repo, number=number, min_version=cfg.gh_min_tuple
        )["diff"]
    return bundle


def fetch_issue_context(cfg: AgenticConfig, number: int) -> dict:
    """Return an issue's metadata bundle."""
    _guard_read_op(cfg, "issue_view")
    return {
        "repo": cfg.repo,
        "number": number,
        "issue": run_read(
            "issue_view", cfg.repo, number=number, min_version=cfg.gh_min_tuple
        )["data"],
    }


def fetch_repo_context(cfg: AgenticConfig) -> dict:
    """Return a repo overview plus a shortlist of open PRs and issues."""
    _guard_read_op(cfg, "repo_view")
    bundle: dict = {"repo": cfg.repo}
    bundle["overview"] = run_read("repo_view", cfg.repo, min_version=cfg.gh_min_tuple)["data"]
    if "pr_list" in cfg.allowed_read_ops:
        bundle["open_prs"] = run_read(
            "pr_list", cfg.repo, limit=10, min_version=cfg.gh_min_tuple
        )["data"]
    if "issue_list" in cfg.allowed_read_ops:
        bundle["open_issues"] = run_read(
            "issue_list", cfg.repo, limit=10, min_version=cfg.gh_min_tuple
        )["data"]
    return bundle


__all__ = [
    "DEFAULT_MIN_GH",
    "fetch_pr_context",
    "fetch_issue_context",
    "fetch_repo_context",
]
