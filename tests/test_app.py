from fastapi.testclient import TestClient
import hashlib
import pytest

from app.main import app

client = TestClient(app)


@pytest.fixture
def publisher(monkeypatch):
    from app import main
    monkeypatch.setattr(main, "SIGNER_NSEC", "test-key")
    async def publish(artifact, **kwargs):
        return {"published": True, "event_id": "a" * 64, "publisher": "test-publisher", "message": "Anchor Record accepted by a relay."}
    monkeypatch.setattr(main, "publish_anchor", publish)


def test_home_page():
    response = client.get("/")
    assert response.status_code == 200
    assert "Check a digital artifact" in response.text


@pytest.mark.parametrize("path, status_id", [("/", "lookup-progress"), ("/register", "register-progress")])
def test_forms_include_progress_feedback(path, status_id):
    response = client.get(path)
    assert response.status_code == 200
    assert f'data-progress="{status_id}"' in response.text
    assert f'id="{status_id}"' in response.text
    assert 'role="status"' in response.text
    assert "Please wait." in response.text
    assert 'src="/static/progress.js" defer' in response.text
    assert client.get("/static/progress.js").status_code == 200


def test_assets_use_relative_urls_behind_https_proxy():
    response = client.get("/", headers={"host": "example.com", "x-forwarded-proto": "https"})
    assert 'href="/static/styles.css"' in response.text
    assert 'src="/static/openetr-logo.png"' in response.text
    assert 'http://example.com/static/' not in response.text
    assert client.get("/static/styles.css").status_code == 200


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_invalid_api_reference():
    response = client.get("/api/etr/not-a-digest")
    assert response.status_code == 400


def test_form_preserves_campaign_path_from_url():
    response = client.get(
        "/resolve",
        params={
            "reference": (
                "https://example.com/wine-2026/"
                "cvJo153DZBKiHQRswhJLnKAqqzxxLrI-Z_2W2Go4448"
            )
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"].startswith("/wine-2026/")


def test_register_artifact_uses_default_campaign(publisher):
    content = b"OpenQR registration test"
    digest = hashlib.sha256(content).hexdigest()
    response = client.post(
        "/register",
        files={"file": ("artifact.txt", content, "text/plain")},
    )
    assert response.status_code == 200
    assert digest in response.text
    assert "http://testserver/etr/" in response.text
    assert "Anchor Record accepted by a relay" in response.text


def test_register_artifact_accepts_campaign_id(publisher):
    response = client.post(
        "/register",
        data={"campaign_id": "wine-2026"},
        files={"file": ("artifact.txt", b"wine", "text/plain")},
    )
    assert response.status_code == 200
    assert "http://testserver/wine-2026/" in response.text


def test_qr_image_is_png():
    response = client.get(
        "/qr/wine-2026/cvJo153DZBKiHQRswhJLnKAqqzxxLrI-Z_2W2Go4448"
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content.startswith(b"\x89PNG\r\n\x1a\n")


def test_resolver_retrieves_artifact_and_downloads_verified_bytes(monkeypatch):
    import io
    from app import main, registration
    from app.resolver import ResolutionResult
    content = b"retrievable artifact"
    digest = hashlib.sha256(content).hexdigest()
    async def lookup(*args):
        return ResolutionResult(digest, "hex", ["wss://example.com"], "2026-01-01T00:00:00Z", [])
    monkeypatch.setattr(main, "perform_lookup", lookup)
    monkeypatch.setattr(registration.urllib.request, "urlopen", lambda *args, **kwargs: io.BytesIO(content))
    response = client.get(f"/campaign/{digest}")
    assert response.status_code == 200
    assert "Download verified artifact" in response.text
    assert client.get(f"/api/campaign/{digest}").json()["artifact"]["verified"]
    response = client.get(f"/artifact/campaign/{digest}")
    assert response.content == content
    assert response.headers["content-disposition"].startswith("attachment;")
    monkeypatch.setattr(registration.urllib.request, "urlopen", lambda *args, **kwargs: io.BytesIO(b"wrong bytes"))
    assert client.get(f"/artifact/campaign/{digest}").status_code == 502
    assert "Download verified artifact" not in client.get(f"/campaign/{digest}").text


def test_registration_requires_signing_configuration(monkeypatch):
    from app import main
    monkeypatch.setattr(main, "SIGNER_NSEC", None)
    response = client.post("/register", files={"file": ("test.txt", b"test", "text/plain")})
    assert response.status_code == 503


@pytest.mark.parametrize("content, media_type", [(b"%PDF-1.7\npreview", "application/pdf"), (b"\x89PNG\r\n\x1a\npreview", "image/png")])
def test_verified_preview_response(monkeypatch, content, media_type):
    import io
    from app import registration
    digest = hashlib.sha256(content).hexdigest()
    monkeypatch.setattr(registration.urllib.request, "urlopen", lambda *args, **kwargs: io.BytesIO(content))
    response = client.get(f"/artifact/etr/{digest}?preview=true")
    assert response.status_code == 200
    assert response.headers["content-type"] == media_type
    assert response.headers["content-disposition"].startswith("inline;")
    assert response.content == content
    assert client.get(f"/artifact/etr/{'0' * 64}?preview=true").status_code == 502


def test_active_content_is_download_only(monkeypatch):
    import io
    from app import registration
    content = b"<svg onload='alert(1)'></svg>"
    digest = hashlib.sha256(content).hexdigest()
    monkeypatch.setattr(registration.urllib.request, "urlopen", lambda *args, **kwargs: io.BytesIO(content))
    assert client.get(f"/artifact/etr/{digest}?preview=true").status_code == 415
    assert client.get(f"/artifact/etr/{digest}").status_code == 200
