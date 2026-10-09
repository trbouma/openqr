from fastapi.testclient import TestClient
import hashlib

from app.main import app

client = TestClient(app)


def test_home_page():
    response = client.get("/")
    assert response.status_code == 200
    assert "Check a digital artifact" in response.text


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


def test_register_artifact_uses_default_campaign():
    content = b"OpenQR registration test"
    digest = hashlib.sha256(content).hexdigest()
    response = client.post(
        "/register",
        files={"file": ("artifact.txt", content, "text/plain")},
    )
    assert response.status_code == 200
    assert digest in response.text
    assert "http://testserver/etr/" in response.text
    assert "No Anchor Record was published" in response.text


def test_register_artifact_accepts_campaign_id():
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
