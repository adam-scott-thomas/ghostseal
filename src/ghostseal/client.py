"""SealClient — batched, fire-and-forget audit emitter to Blackbox.

Usage:
    client = SealClient(blackbox_url="https://blackbox:8443", api_key="...")
    client.emit("ghostrouter.call.complete", {"model": "claude", "cost": 0.003})

    # Or register in spine:
    core.register("audit", client)
    # Then anywhere:
    Core.instance().get("audit").emit("event_type", {...})

Events are batched in memory and flushed to Blackbox /api/v1/ingest
either when the batch is full or when flush() is called explicitly.
If Blackbox is unreachable, events are saved to a local spill file.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Optional

import httpx

from ghostseal.envelope import SealEnvelope, seal_envelope

logger = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 50
DEFAULT_FLUSH_INTERVAL = 30.0  # seconds
DEFAULT_SPILL_PATH = "~/.ghostseal/spill.jsonl"


class SealClient:
    """Batched audit emitter targeting Blackbox /api/v1/ingest."""

    def __init__(
        self,
        blackbox_url: str = "http://localhost:8443",
        api_key: str = "",
        *,
        source: str = "",
        source_version: str = "",
        batch_size: int = DEFAULT_BATCH_SIZE,
        flush_interval: float = DEFAULT_FLUSH_INTERVAL,
        spill_path: str = DEFAULT_SPILL_PATH,
        auto_flush: bool = True,
    ) -> None:
        self._url = blackbox_url.rstrip("/")
        self._api_key = api_key
        self._source = source
        self._source_version = source_version
        self._batch_size = batch_size
        self._flush_interval = flush_interval
        self._spill_path = Path(spill_path).expanduser()

        self._buffer: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._total_emitted = 0
        self._total_flushed = 0
        self._total_spilled = 0
        self._flush_errors = 0

        self._timer: Optional[threading.Timer] = None
        if auto_flush and flush_interval > 0:
            self._schedule_flush()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def emit(
        self,
        event_type: str,
        data: dict[str, Any],
        *,
        trace_id: str = "",
    ) -> SealEnvelope:
        """Create an envelope, buffer it, and return it.

        Never raises — failures are logged and events spilled to disk.
        """
        envelope = seal_envelope(
            event_type=event_type,
            data=data,
            source=self._source or event_type.split(".")[0],
            source_version=self._source_version,
            trace_id=trace_id,
        )

        with self._lock:
            self._buffer.append(envelope.to_dict())
            self._total_emitted += 1

            if len(self._buffer) >= self._batch_size:
                self._flush_locked()

        return envelope

    def flush(self) -> int:
        """Flush the buffer to Blackbox. Returns number of events sent."""
        with self._lock:
            return self._flush_locked()

    def close(self) -> None:
        """Stop auto-flush timer and flush remaining events."""
        if self._timer:
            self._timer.cancel()
            self._timer = None
        self.flush()

    @property
    def stats(self) -> dict[str, int]:
        return {
            "emitted": self._total_emitted,
            "flushed": self._total_flushed,
            "spilled": self._total_spilled,
            "flush_errors": self._flush_errors,
            "buffered": len(self._buffer),
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _flush_locked(self) -> int:
        """Flush buffer while lock is held. Returns events sent."""
        if not self._buffer:
            return 0

        batch = self._buffer[:]
        self._buffer.clear()

        try:
            self._send_to_blackbox(batch)
            self._total_flushed += len(batch)
            return len(batch)
        except Exception as exc:
            logger.warning("Blackbox flush failed (%s), spilling %d events", exc, len(batch))
            self._flush_errors += 1
            self._spill_to_disk(batch)
            return 0

    def _send_to_blackbox(self, events: list[dict]) -> None:
        """POST events to Blackbox /api/v1/ingest."""
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._api_key:
            headers["X-API-Key"] = self._api_key

        payload = {
            "events": events,
            "source_id": self._source,
            "agent_id": f"ghostseal/{self._source_version or '0.0.0'}",
        }

        resp = httpx.post(
            f"{self._url}/api/v1/ingest",
            json=payload,
            headers=headers,
            timeout=10.0,
        )
        resp.raise_for_status()

    def _spill_to_disk(self, events: list[dict]) -> None:
        """Append events to local spill file for later recovery."""
        try:
            self._spill_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._spill_path, "a") as f:
                for event in events:
                    f.write(json.dumps(event, default=str) + "\n")
            self._total_spilled += len(events)
        except Exception as exc:
            logger.error("Spill to disk failed: %s", exc)

    def _schedule_flush(self) -> None:
        """Schedule next auto-flush."""
        def _tick():
            self.flush()
            self._schedule_flush()

        self._timer = threading.Timer(self._flush_interval, _tick)
        self._timer.daemon = True
        self._timer.start()

    def drain_spill(self) -> int:
        """Re-emit spilled events from disk. Returns count re-emitted."""
        if not self._spill_path.exists():
            return 0

        events = []
        with open(self._spill_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    events.append(json.loads(line))

        if not events:
            return 0

        try:
            self._send_to_blackbox(events)
            self._spill_path.unlink()
            self._total_flushed += len(events)
            return len(events)
        except Exception as exc:
            logger.warning("Drain spill failed: %s", exc)
            return 0
