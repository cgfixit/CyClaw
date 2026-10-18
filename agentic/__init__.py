"""CyClaw out-of-band connectors -- opt-in, human-governed, shipped off.

Two connectors, each with its own CLI, NEVER imported by gate.py, gate_ops.py,
gate_auth.py, gate_memory.py, graph.py, or mcp_hybrid_server.py (I6):

  1. ``agentic.fsconnect`` -- scoped local/SMB filesystem connector
     (``python -m agentic.fsconnect.cli``).
  2. ``agentic.netconnect`` -- passive LAN inventory, no active probes
     (``python -m agentic.netconnect.cli``).

The GitHub context layer, skills registry, real-repo coding loop, verification
executor, harness optimizer and SQL connector that used to live here were
removed in October 2026; docs/changelog.txt records the removal.
"""

# This process never imports gate.py, so without this it inherits whatever
# telemetry env the operator's shell/container/observability agent happens to
# carry. Applying the kill at package-import time puts it in place before any
# connector submodule loads. Same rationale as mcp_hybrid_server.py.
from utils.telemetry_kill import apply_telemetry_kill

apply_telemetry_kill()

__version__ = "0.2.0"
