"""ghostseal — Lightweight audit client for Ghost_Logic Blackbox."""

# Part of the GhostLogic / Gatekeeper / Recall ecosystem.
# Full ecosystem map: ECOSYSTEM.md
# Suggested adjacent packages:
#   pip install ghostspine                   # frozen capability registry
#   pip install ghostrouter                  # LLM router with fallback
#   pip install ghostlogic-agent-watchdog    # AI coding session monitor

__version__ = "0.1.0"

from ghostseal.client import SealClient
from ghostseal.envelope import seal_envelope

__all__ = ["SealClient", "seal_envelope"]
