"""Tests for SealEnvelope construction and hashing."""
import hashlib
import json
from ghostseal.envelope import seal_envelope, SealEnvelope


def test_envelope_has_content_hash():
    env = seal_envelope("test.event", {"key": "value"}, source="test")
    assert env.content_hash
    assert len(env.content_hash) == 64  # SHA-256 hex


def test_hash_is_deterministic():
    data = {"b": 2, "a": 1}
    e1 = seal_envelope("t", data, source="x")
    e2 = seal_envelope("t", data, source="x")
    assert e1.content_hash == e2.content_hash


def test_hash_matches_blackbox_algorithm():
    """Hash must match Blackbox's verification: json.dumps(data, sort_keys=True, default=str)."""
    data = {"model": "claude", "cost": 0.003}
    canonical = json.dumps(data, sort_keys=True, default=str)
    expected = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    env = seal_envelope("test", data, source="test")
    assert env.content_hash == expected


def test_different_data_different_hash():
    e1 = seal_envelope("t", {"x": 1}, source="s")
    e2 = seal_envelope("t", {"x": 2}, source="s")
    assert e1.content_hash != e2.content_hash


def test_envelope_is_frozen():
    env = seal_envelope("t", {"x": 1}, source="s")
    try:
        env.data = {"y": 2}
        assert False, "Should be frozen"
    except AttributeError:
        pass


def test_to_dict_roundtrip():
    env = seal_envelope("test.event", {"key": "val"}, source="src", trace_id="tr-1")
    d = env.to_dict()
    assert d["event_type"] == "test.event"
    assert d["source"] == "src"
    assert d["trace_id"] == "tr-1"
    assert d["content_hash"] == env.content_hash
    assert d["data"] == {"key": "val"}


def test_timestamp_populated():
    env = seal_envelope("t", {}, source="s")
    assert env.timestamp > 0


def test_source_defaults_from_event_type():
    """If source not provided, client infers from event_type prefix."""
    # This is tested in client.py, but envelope itself takes explicit source
    env = seal_envelope("ghostrouter.call", {}, source="ghostrouter")
    assert env.source == "ghostrouter"
