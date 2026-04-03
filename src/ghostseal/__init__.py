"""ghostseal — Lightweight audit client for Ghost_Logic Blackbox."""
__version__ = "0.1.0"

from ghostseal.client import SealClient
from ghostseal.envelope import seal_envelope

__all__ = ["SealClient", "seal_envelope"]
