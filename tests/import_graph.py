"""Shared AST helper for the six ``test_*_isolation.py`` I6 guards.

Each guard used to carry its own byte-identical copy of this walker; one copy
means a fix to what counts as an import reaches every guard at once.
"""

from __future__ import annotations

import ast


def all_imports(source: str) -> set[str]:
    """Top-level package names imported anywhere in ``source`` (absolute imports only)."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names
