import base64
import json
import asyncio
import hashlib
import io
import pytest
from types import SimpleNamespace

from stroma import Event, Keys

from app.registration import blossom_auth_header, render_qr_png


def test_anchor_publishing_requires_acknowledgement(monkeypatch):
    from app import registration as module
    artifact = module.UploadedArtifact("test.txt", "text/plain", 4, hashlib.sha256(b"test").hexdigest(), b"test")
    keys = Keys()
    class Pool:
        def __init__(self, relays, **kwargs):
            self.relays = relays
        async def publish(self, event):
            assert event.is_valid()
            assert event.kind == 1415
            assert event.tags.get_tags_value("o") == [artifact.digest]
            assert event.tags.get_tags_value("action") == ["issue"]
            return [SimpleNamespace(accepted=True, relay=self.relays[0])]
    monkeypatch.setattr(module, "RelayPool", Pool)
    result = asyncio.run(module.publish_anchor(artifact, signer_nsec=keys.private_key_bech32(), relays=["wss://example.com"], timeout=1))
    assert result["published"]
    async def failed(self, event):
        raise TimeoutError()
    monkeypatch.setattr(Pool, "publish", failed)
    result = asyncio.run(module.publish_anchor(artifact, signer_nsec=keys.private_key_bech32(), relays=["wss://example.com"], timeout=1))
    assert not result["published"]
    assert result["event_id"]


def test_artifact_retrieval_checks_bytes_and_size(monkeypatch):
    from app import registration as module
    content = b"test artifact"
    digest = hashlib.sha256(content).hexdigest()
    monkeypatch.setattr(module.urllib.request, "urlopen", lambda *args, **kwargs: io.BytesIO(content))
    kwargs = dict(server="https://example.com", timeout=1, max_bytes=100)
    assert module.fetch_artifact(digest, **kwargs) == content
    with pytest.raises(ValueError, match="verification failed"):
        module.fetch_artifact("0" * 64, **kwargs)
    with pytest.raises(ValueError, match="size limit"):
        module.fetch_artifact(digest, **{**kwargs, "max_bytes": 2})


def test_blossom_authorization_is_a_signed_nostr_event():
    keys = Keys()
    digest = "72f268d79dc36412a21d046cc2124b9ca02aab3c712eb23e67fd96d86a38e38f"
    header = blossom_auth_header(
        signer_nsec=keys.private_key_bech32(),
        digest=digest,
    )
    scheme, encoded = header.split(" ", 1)
    event = Event.load(json.loads(base64.b64decode(encoded)))

    assert scheme == "Nostr"
    assert event.kind == 24242
    assert digest in event.tags.get_tags_value("x")
    assert "upload" in event.tags.get_tags_value("t")
    assert event.is_valid()


def test_qr_renderer_uses_png_output():
    image = render_qr_png(
        "https://example.com/etr/cvJo153DZBKiHQRswhJLnKAqqzxxLrI-Z_2W2Go4448"
    )
    assert image.startswith(b"\x89PNG\r\n\x1a\n")


@pytest.mark.parametrize("failure", ["preflight", "upload", "confirmation", "missing", "unavailable", "wrong_bytes", "none"])
def test_blossom_upload_recovers_without_republishing(monkeypatch, failure):
    from app import registration as module

    content = b"test artifact"
    artifact = module.UploadedArtifact("test.txt", "text/plain", len(content), hashlib.sha256(content).hexdigest(), content)
    calls = []

    class Response(io.BytesIO):
        status = 200

        def read(self, *args):
            if calls[-1] == "PUT":
                raise AssertionError("Upload descriptor must not be read")
            return super().read(*args)

    def urlopen(request, **kwargs):
        method = request.get_method()
        calls.append(method)
        if method == "HEAD":
            if len(calls) == 1:
                if failure == "preflight":
                    raise TimeoutError("preflight timed out")
                raise module.urllib.error.HTTPError(request.full_url, 404, "Not found", {}, None)
            if failure in {"confirmation", "unavailable", "wrong_bytes"}:
                raise TimeoutError("confirmation timed out")
            if failure == "missing":
                raise module.urllib.error.HTTPError(request.full_url, 404, "Not found", {}, None)
        if method == "PUT" and failure == "upload":
            raise module.urllib.error.URLError(TimeoutError("upload timed out"))
        if method == "GET":
            assert kwargs["timeout"] <= 5
            if failure == "unavailable":
                raise TimeoutError("retrieval timed out")
            return Response(b"incorrect" if failure == "wrong_bytes" else content)
        return Response()

    monkeypatch.setattr(module.urllib.request, "urlopen", urlopen)
    result = module.upload_to_blossom(artifact, server="https://example.com", signer_nsec=Keys().private_key_bech32(), timeout=20)
    assert calls.count("PUT") == 1
    if failure in {"unavailable", "wrong_bytes"}:
        assert result["stored"] is None
        assert "could not be confirmed" in result["message"]
    else:
        assert result["stored"] is True
    assert result["url"].endswith(artifact.digest)
