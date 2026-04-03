"""Standardized audit envelope — the packet every ghost* package emits."""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class SealEnvelope:
    """Immutable audit event ready for Blackbox ingest."""

    event_type: str          # e.g. "ghostrouter.call.complete"
    source: str              # e.g. "ghostrouter"
    source_version: str      # e.g. "0.1.0"
    timestamp: float         # Unix epoch
    data: dict[str, Any]     # Arbitrary payload
    content_hash: str        # SHA-256 of canonical JSON(data)
    trace_id: str = ""       # Optional correlation ID

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def seal_envelope(
    event_type: str,
    data: dict[str, Any],
    *,
    source: str = "",
    source_version: str = "",
    trace_id: str = "",
) -> SealEnvelope:
    """Build a SealEnvelope with computed content_hash.

    The hash is SHA-256 of the data dict serialized as sorted-key JSON
    (matching Blackbox's verification algorithm).
    """
    canonical = json.dumps(data, sort_keys=True, default=str)
    content_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    return SealEnvelope(
        event_type=event_type,
        source=source,
        source_version=source_version,
        timestamp=time.time(),
        data=data,
        content_hash=content_hash,
        trace_id=trace_id,
    )
