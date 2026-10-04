"""Test-only ArgvListSandbox injector.

Production verification requires native confinement and refuses Windows. CI tests that
need to exercise argv/cwd/timeout/numbat/env plumbing inject this double via
monkeypatch -- never an env flag. The hard-sandbox and real-repo smoke files must NOT use this helper.
"""

from __future__ import annotations

from agentic.executor.hard_sandbox import ArgvListSandbox

PRODUCTION_SANDBOX_TARGET = "agentic.executor.runner.production_sandbox"


def inject_argv_list_sandbox(monkeypatch) -> None:
    """Replace production_sandbox with the ArgvListSandbox class (zero-arg factory)."""
    monkeypatch.setattr(PRODUCTION_SANDBOX_TARGET, ArgvListSandbox)
