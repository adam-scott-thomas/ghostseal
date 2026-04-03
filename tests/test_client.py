"""Tests for SealClient — batching, flushing, spilling."""
import json
import pytest
import respx
import httpx
from ghostseal.client import SealClient


@pytest.fixture
def client(tmp_path):
    return SealClient(
        blackbox_url="https://blackbox.test:8443",
        api_key="test-key",
        source="test",
        source_version="0.0.1",
        batch_size=5,
        spill_path=str(tmp_path / "spill.jsonl"),
        auto_flush=False,  # manual flush for deterministic tests
    )


def test_emit_returns_envelope(client):
    env = client.emit("test.event", {"x": 1})
    assert env.event_type == "test.event"
    assert env.content_hash
    assert env.source == "test"


def test_emit_buffers(client):
    client.emit("a", {"x": 1})
    client.emit("b", {"x": 2})
    assert client.stats["buffered"] == 2
    assert client.stats["emitted"] == 2
    assert client.stats["flushed"] == 0


@respx.mock
def test_flush_sends_to_blackbox(client):
    route = respx.post("https://blackbox.test:8443/api/v1/ingest").mock(
        return_value=httpx.Response(200, json={"status": "ingested", "accepted": 2})
    )
    client.emit("a", {"x": 1})
    client.emit("b", {"x": 2})
    sent = client.flush()
    assert sent == 2
    assert client.stats["flushed"] == 2
    assert client.stats["buffered"] == 0

    # Verify request shape
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["source_id"] == "test"
    assert len(body["events"]) == 2
    assert req.headers["X-API-Key"] == "test-key"


@respx.mock
def test_auto_flush_on_batch_size(client):
    respx.post("https://blackbox.test:8443/api/v1/ingest").mock(
        return_value=httpx.Response(200, json={"status": "ingested", "accepted": 5})
    )
    # batch_size is 5 — should auto-flush when 5th event is emitted
    for i in range(5):
        client.emit("e", {"i": i})
    assert client.stats["flushed"] == 5
    assert client.stats["buffered"] == 0


@respx.mock
def test_flush_empty_returns_zero(client):
    sent = client.flush()
    assert sent == 0


@respx.mock
def test_blackbox_down_spills_to_disk(client, tmp_path):
    respx.post("https://blackbox.test:8443/api/v1/ingest").mock(
        side_effect=httpx.ConnectError("refused")
    )
    client.emit("a", {"x": 1})
    client.emit("b", {"x": 2})
    sent = client.flush()
    assert sent == 0
    assert client.stats["spilled"] == 2
    assert client.stats["flush_errors"] == 1

    # Verify spill file
    spill = tmp_path / "spill.jsonl"
    assert spill.exists()
    lines = spill.read_text().strip().split("\n")
    assert len(lines) == 2
    assert json.loads(lines[0])["event_type"] == "a"


@respx.mock
def test_drain_spill_resends(client, tmp_path):
    # Write a spill file manually
    spill = tmp_path / "spill.jsonl"
    spill.write_text(json.dumps({"event_type": "old", "data": {}}) + "\n")

    respx.post("https://blackbox.test:8443/api/v1/ingest").mock(
        return_value=httpx.Response(200, json={"status": "ingested", "accepted": 1})
    )
    count = client.drain_spill()
    assert count == 1
    assert not spill.exists()  # cleaned up after successful drain


def test_drain_spill_no_file(client):
    count = client.drain_spill()
    assert count == 0


@respx.mock
def test_close_flushes_remaining(client):
    respx.post("https://blackbox.test:8443/api/v1/ingest").mock(
        return_value=httpx.Response(200, json={"status": "ingested", "accepted": 3})
    )
    client.emit("a", {})
    client.emit("b", {})
    client.emit("c", {})
    client.close()
    assert client.stats["flushed"] == 3
    assert client.stats["buffered"] == 0


def test_stats_tracking(client):
    s = client.stats
    assert s["emitted"] == 0
    assert s["flushed"] == 0
    assert s["spilled"] == 0
    assert s["flush_errors"] == 0
    assert s["buffered"] == 0


@respx.mock
def test_no_api_key_omits_header(tmp_path):
    c = SealClient(
        blackbox_url="https://bb:8443",
        api_key="",
        spill_path=str(tmp_path / "spill.jsonl"),
        auto_flush=False,
    )
    route = respx.post("https://bb:8443/api/v1/ingest").mock(
        return_value=httpx.Response(200, json={"status": "ingested", "accepted": 1})
    )
    c.emit("t", {"x": 1})
    c.flush()
    req = route.calls[0].request
    assert "X-API-Key" not in req.headers


def test_spine_integration(tmp_path):
    """SealClient can be registered as a spine capability."""
    try:
        from spine import Core
        Core._reset_instance()

        c = SealClient(
            blackbox_url="https://bb:8443",
            api_key="k",
            spill_path=str(tmp_path / "spill.jsonl"),
            auto_flush=False,
        )

        def setup(core):
            core.register("audit", c)
            core.boot(env="test")

        Core.boot_once(setup)
        audit = Core.instance().get("audit")
        assert audit is c
        env = audit.emit("test.spine", {"works": True})
        assert env.event_type == "test.spine"

        Core._reset_instance()
    except ImportError:
        pytest.skip("spine not installed")
