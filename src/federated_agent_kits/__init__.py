"""Subscribe to kits from wherever they live, and write them where each harness looks.

The public surface of this package is the `akit` entry point, not these modules.
DESIGN.md section 9 makes that explicit: the command name is the contract other
repositories pin in a pre-commit hook, and importing from here is not supported.
"""

from __future__ import annotations

from federated_agent_kits.cli import main, version

__all__ = ["main", "version"]
