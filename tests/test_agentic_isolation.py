"""Invariant guard: the agentic layer must stay out of the request path.

The whole security argument for the agentic layer is that it is out-of-band --
exactly like sync/. If gate.py, graph.py, or mcp_hybrid_server.py ever imported
``agentic``, the layer would be coupled into the request path and could (in
principle) influence retrieval, routing, or the MCP surface. This test fails
loudly if that coupling is ever introduced.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
REQUEST_PATH_MODULES = ["gate.py", "graph.py", "mcp_hybrid_server.py"]


def _imports(source: str) -> set[str]:
    """Top-level module names imported by ``source`` (import X / from X import ...)."""
    names: set[str] = set()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:
                names.add(node.module.split(".")[0])
    return names


@pytest.mark.parametrize("module_file", REQUEST_PATH_MODULES)
def test_request_path_does_not_import_agentic(module_file):
    source = (REPO_ROOT / module_file).read_text(encoding="utf-8")
    assert "agentic" not in _imports(source), (
        f"{module_file} must not import the agentic package "
        "(it would couple the out-of-band layer into the request path)"
    )


def test_agentic_does_not_import_request_path():
    # Symmetric guard: agentic must not pull in gate/graph/mcp either.
    forbidden = {"gate", "graph", "mcp_hybrid_server"}
    for py in (REPO_ROOT / "agentic").glob("*.py"):
        imported = _imports(py.read_text(encoding="utf-8"))
        leaked = forbidden & imported
        assert not leaked, f"agentic/{py.name} imports request-path module(s): {leaked}"
