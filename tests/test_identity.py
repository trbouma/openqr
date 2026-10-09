import asyncio
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
from stroma import Keys

from app import main, identity
from app.resolver import ResolutionResult, event_to_evidence
from stroma import Event


def token(client):
    page = client.get("/register")
    assert page.headers["cache-control"] == "no-store"
    return re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)


def setup_identity(monkeypatch):
    root, signer = Keys(), Keys()
    monkeypatch.setattr(main, "REGISTRATION_MODE", "interactive")
    monkeypatch.setattr(main, "SIGNER_NSEC", Keys().private_key_bech32())
    monkeypatch.setattr(identity, "list_profiles", AsyncMock(return_value=["warehouse"]))
    selected = {"name": "warehouse", "npub": signer.public_key_bech32(),
                "nsec": signer.private_key_bech32(), "relays": "wss://profile.example.org"}
    async def acting(root_nsec, name, relays):
        if name != "warehouse":
            raise ValueError("Not a managed profile")
        return selected
    monkeypatch.setattr(identity, "acting_profile", acting)
    monkeypatch.setattr(identity, "profile_details", AsyncMock(return_value={"name": "Test Warehouse"}))
    return root, signer


def login_select(client, root):
    response = client.post("/login", data={"csrf": token(client), "nsec": root.private_key_bech32()})
    assert response.status_code == 200
    response = client.post("/profiles/use", data={"csrf": token(client), "profile": "warehouse"})
    assert response.status_code == 200
    assert "Test Warehouse" in response.text


def test_login_selection_signing_logout_and_isolation(monkeypatch):
    root, signer = setup_identity(monkeypatch)
    publish = AsyncMock(return_value={"published": True, "event_id": "a" * 64, "publisher": signer.public_key_bech32(), "message": "Published"})
    store = AsyncMock(return_value={"stored": True, "confirmed_servers": ["https://blob.example.org"], "outcomes": [], "urls": [], "message": "Stored"})
    monkeypatch.setattr(main, "publish_anchor", publish)
    monkeypatch.setattr(main, "maybe_upload_to_blossom", store)
    with TestClient(main.app) as client, TestClient(main.app) as other:
        login_select(client, root)
        cookie = client.cookies.get("openqr_session")
        assert root.private_key_bech32() not in cookie
        assert signer.private_key_bech32() not in cookie
        assert "Test Warehouse" not in other.get("/register").text
        response = client.post("/register", data={"csrf": token(client), "store_on_blossom": "true"},
                               files={"file": ("test.txt", b"test", "text/plain")})
        assert response.status_code == 200
        assert publish.call_args.kwargs["signer_nsec"] == signer.private_key_bech32()
        assert publish.call_args.kwargs["relays"] == ["wss://profile.example.org"]
        assert publish.call_args.kwargs["blossom_servers"] == ["https://blob.example.org"]
        assert store.call_args.kwargs["signer_nsec"] == signer.private_key_bech32()
        assert root.private_key_bech32() not in response.text
        assert client.post("/logout", data={"csrf": token(client)}).status_code == 200
        response = client.post("/register", data={"csrf": token(client)}, files={"file": ("x", b"x")})
        assert response.status_code == 401
        assert publish.await_count == 1


def test_csrf_and_forged_profile_are_rejected(monkeypatch):
    root, _ = setup_identity(monkeypatch)
    with TestClient(main.app) as client:
        assert client.post("/login", data={"nsec": root.private_key_bech32()}).status_code == 403
        assert client.post("/logout").status_code == 403
        client.post("/login", data={"csrf": token(client), "nsec": root.private_key_bech32()})
        assert client.post("/profiles/use", data={"csrf": token(client), "profile": "someone-else"}).status_code == 400
        assert client.post("/register", data={"csrf": token(client)}, files={"file": ("x", b"x")}).status_code == 401


def test_invalid_campaign_retains_registration_identity_panel(monkeypatch):
    root, _ = setup_identity(monkeypatch)
    with TestClient(main.app) as client:
        login_select(client, root)
        response = client.post("/register", data={"csrf": token(client), "campaign_id": "../bad"}, files={"file": ("x", b"x")})
        assert response.status_code == 400
        assert "Test Warehouse" in response.text
        assert root.private_key_bech32() not in response.text


def test_revoked_profile_and_storage_failure_block_publication(monkeypatch):
    root, _ = setup_identity(monkeypatch)
    publish = AsyncMock()
    monkeypatch.setattr(main, "publish_anchor", publish)
    with TestClient(main.app) as client:
        login_select(client, root)
        monkeypatch.setattr(main, "maybe_upload_to_blossom", AsyncMock(return_value={
            "stored": False, "confirmed_servers": [], "outcomes": [], "urls": [], "message": "Unconfirmed",
        }))
        assert client.post("/register", data={"csrf": token(client), "store_on_blossom": "true"}, files={"file": ("x", b"x")}).status_code == 502
        csrf = token(client)
        monkeypatch.setattr(identity, "acting_profile", AsyncMock(side_effect=ValueError("Removed")))
        assert client.post("/register", data={"csrf": csrf}, files={"file": ("x", b"x")}).status_code == 403
        publish.assert_not_called()


def test_component_context_is_reset_and_no_local_config_is_loaded(monkeypatch):
    from openetr.config import _REQUEST_RUNTIME_BOOTSTRAP
    root = Keys().private_key_bech32()
    async def load(config):
        assert _REQUEST_RUNTIME_BOOTSTRAP.get()
        assert config["root_nsec"] == root
        return SimpleNamespace(profiles=["warehouse"])
    monkeypatch.setattr(identity, "_async_load_profiles_index", load)
    before = dict(_REQUEST_RUNTIME_BOOTSTRAP.get())
    assert asyncio.run(identity.list_profiles(root, ["wss://home.example.org"])) == ["warehouse"]
    assert _REQUEST_RUNTIME_BOOTSTRAP.get() == before


def test_combined_retrieval_uses_only_verified_hints(monkeypatch):
    digest = "a" * 64
    event = Event(kind=1415, tags=[["o", digest], ["action", "issue"],
        ["blossom", "https://hint.example.org"], ["blossom", "javascript:alert(1)"]])
    event.sign(Keys())
    evidence = event_to_evidence(event, digest)
    result = ResolutionResult(digest, "hex", [], "", [evidence])
    monkeypatch.setattr(main, "BLOSSOM_QUERY_SERVERS", ["https://query.example.org"])
    monkeypatch.setattr(main, "BLOSSOM_SERVERS", ["https://upload.example.org"])
    assert main.artifact_options(result)["servers"] == [
        "https://hint.example.org", "https://query.example.org", "https://upload.example.org"]
    event.content = "tampered"
    bad = ResolutionResult(digest, "hex", [], "", [event_to_evidence(event, digest)])
    assert "https://hint.example.org" not in main.artifact_options(bad)["servers"]
