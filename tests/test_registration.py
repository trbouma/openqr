import asyncio
import hashlib
from types import SimpleNamespace

import pytest
from stroma import BlossomError, BlossomPool, BlossomOutcome, BlossomStoreResult, Keys

from app import registration as module


def artifact():
    content = b"test artifact"
    return module.UploadedArtifact("test.txt", "text/plain", len(content), hashlib.sha256(content).hexdigest(), content)


def test_anchor_publishing_requires_acknowledgement_and_signs_hints(monkeypatch):
    item = artifact()
    keys = Keys()
    class Pool:
        def __init__(self, relays, **kwargs):
            self.relays = relays
        async def publish(self, event):
            assert event.is_valid()
            assert event.kind == 1415
            assert event.tags.get_tags_value("o") == [item.digest]
            assert event.tags.get_tags_value("action") == ["issue"]
            assert event.tags.get_tags_value("blossom") == ["https://example.com"]
            return [SimpleNamespace(accepted=True, relay=self.relays[0])]
    monkeypatch.setattr(module, "RelayPool", Pool)
    options = dict(signer_nsec=keys.private_key_bech32(), relays=["wss://example.com"], timeout=1,
                   blossom_servers=["https://example.com/", "https://EXAMPLE.com:443"])
    assert asyncio.run(module.publish_anchor(item, **options))["published"]
    async def rejected(self, event):
        return []
    monkeypatch.setattr(Pool, "publish", rejected)
    assert not asyncio.run(module.publish_anchor(item, **options))["published"]
    async def failed(self, event):
        raise TimeoutError()
    monkeypatch.setattr(Pool, "publish", failed)
    result = asyncio.run(module.publish_anchor(item, **options))
    assert not result["published"] and result["event_id"]


@pytest.mark.parametrize("require,required", [("any", 1), ("half", 1), ("majority", 2), ("all", 2)])
def test_storage_thresholds_and_confirmed_locations(monkeypatch, require, required):
    item = artifact()
    seen = {}
    async def store(pool, content, **kwargs):
        seen.update(kwargs)
        assert pool.servers == ("https://one.example.org", "https://two.example.org")
        assert content == item.content
        return BlossomStoreResult(item.digest, require, required, (
            BlossomOutcome(pool.servers[0], "confirmed"),
            BlossomOutcome(pool.servers[1], "unconfirmed", "Timeout"),
        ))
    monkeypatch.setattr(BlossomPool, "store", store)
    result = asyncio.run(module.maybe_upload_to_blossom(
        item, requested=True, servers=["https://one.example.org", "https://two.example.org"],
        signer_nsec=Keys().private_key_bech32(), timeout=1, max_bytes=100, require=require,
    ))
    assert result["stored"] is (required == 1)
    assert result["confirmed_servers"] == ["https://one.example.org"]
    assert seen["require"] == require
    assert seen["signer"].private_key_hex()


def test_optional_storage_and_failure(monkeypatch):
    async def fail(*args, **kwargs):
        raise BlossomError("timeout")
    monkeypatch.setattr(BlossomPool, "store", fail)
    options = dict(servers=["https://example.com"], signer_nsec=Keys().private_key_bech32(), timeout=1, max_bytes=100)
    assert asyncio.run(module.maybe_upload_to_blossom(artifact(), requested=False, **options)) is None
    assert not asyncio.run(module.maybe_upload_to_blossom(artifact(), requested=True, **options))["stored"]


def test_retrieval_passes_limits_and_deduplicates(monkeypatch):
    async def retrieve(pool, digest):
        assert pool.servers == ("https://example.com",)
        assert pool.max_bytes == 100
        assert pool.operation_timeout == 2
        raise BlossomError("No verified copy")
    monkeypatch.setattr(BlossomPool, "retrieve", retrieve)
    result = asyncio.run(module.retrieve_artifact(artifact().digest, servers=["https://example.com/", "https://EXAMPLE.com:443"], timeout=1, operation_timeout=2, max_bytes=100))
    assert not result["verified"]


def test_qr_renderer_uses_png_output():
    assert module.render_qr_png("https://example.com/etr/" + artifact().digest).startswith(b"\x89PNG\r\n\x1a\n")
