from fastapi.testclient import TestClient
import hashlib
import re
import pytest
from stroma import BlossomError, BlossomRetrievalResult

from app.main import app

client = TestClient(app)


def post_form(path, **kwargs):
    page = client.get("/register")
    token = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)
    data = kwargs.pop("data", {})
    return client.post(path, data={"csrf": token, **data}, **kwargs)


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    from app import main
    from app.resolver import ResolutionResult, normalize_digest
    client.cookies.clear()
    async def lookup(campaign, reference):
        digest, encoding = normalize_digest(reference)
        return ResolutionResult(digest, encoding, ["wss://example.com"], "2026-01-01T00:00:00Z", [])
    monkeypatch.setattr(main, "perform_lookup", lookup)


def mock_blob(monkeypatch, content):
    from app import registration
    async def retrieve(pool, digest):
        if hashlib.sha256(content).hexdigest() != digest:
            raise BlossomError("Digest mismatch")
        return BlossomRetrievalResult(digest, content, pool.servers[0], "application/octet-stream")
    monkeypatch.setattr(registration.BlossomPool, "retrieve", retrieve)


@pytest.fixture
def publisher(monkeypatch):
    from app import main
    monkeypatch.setattr(main, "SIGNER_NSEC", "test-key")
    monkeypatch.setattr(main, "REGISTRATION_MODE", "service")
    async def publish(artifact, **kwargs):
        return {"published": True, "event_id": "a" * 64, "publisher": "test-publisher", "message": "Anchor Record accepted by a relay."}
    monkeypatch.setattr(main, "publish_anchor", publish)


def test_home_page():
    response = client.get("/")
    assert response.status_code == 200
    assert "Check a digital artifact" in response.text


@pytest.mark.parametrize("lot,serial,suffix", [("", "", ""), ("LOT1", "", "/10/LOT1"),
                                               ("", "S1", "/21/S1"), ("LOT1", "S1", "/10/LOT1/21/S1")])
def test_generate_gs1_from_result(monkeypatch, lot, serial, suffix):
    from app import main
    from app.gs1 import TEST_GTIN
    from app.registration import base64url_digest
    content = b"original for GS1"
    digest = hashlib.sha256(content).hexdigest()
    mock_blob(monkeypatch, content)
    async def forbidden(*args, **kwargs):
        pytest.fail("Generating a link must not publish or upload")
    monkeypatch.setattr(main, "publish_anchor", forbidden)
    monkeypatch.setattr(main, "maybe_upload_to_blossom", forbidden)
    page = client.get("/etr/" + digest)
    assert f'name="digest" value="{digest}"' in page.text
    assert "authorized to use in accordance with GS1 standards" in page.text
    response = client.get("/gs1-link", params={"digest": digest, "gtin": TEST_GTIN,
                                               "lot": lot, "serial": serial}, follow_redirects=False)
    assert response.status_code == 303
    target = f"/01/{TEST_GTIN}{suffix}?d={base64url_digest(digest)}"
    assert response.headers["location"] == target
    result = client.get(target)
    assert result.status_code == 200
    assert "Download QR" in result.text
    assert "No verified anchor with matching GS1 values" in result.text


@pytest.mark.parametrize("values", [{}, {"digest": "no", "gtin": "09520123456788"},
                                    {"digest": "a" * 64, "gtin": "09520123456789"},
                                    {"digest": "a" * 64, "gtin": "09520123456788", "lot": "bad/lot"}])
def test_generate_gs1_invalid(values):
    assert client.get("/gs1-link", params=values).status_code == 400


@pytest.mark.parametrize("content", [b"original file", b"", b"x" * 150000])
def test_original_file_check_is_anonymous_and_read_only(monkeypatch, content):
    from app import main
    from app.registration import base64url_digest
    async def forbidden(*args, **kwargs):
        pytest.fail("Checking a file must not publish or store it")
    monkeypatch.setattr(main, "publish_anchor", forbidden)
    monkeypatch.setattr(main, "maybe_upload_to_blossom", forbidden)
    page = client.get("/")
    token = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)
    assert page.headers["cache-control"] == "no-store"
    response = client.post("/check-file", data={"csrf": token},
                           files={"file": ("original.bin", content)}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/etr/" + base64url_digest(hashlib.sha256(content).hexdigest())


def test_original_file_check_limits_and_csrf(monkeypatch):
    from app import main
    monkeypatch.setattr(main, "MAX_UPLOAD_BYTES", 2)
    assert client.post("/check-file", files={"file": ("x", b"abc")}).status_code == 403
    page = client.get("/")
    token = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)
    response = client.post("/check-file", data={"csrf": token}, files={"file": ("x", b"abc")})
    assert response.status_code == 400
    assert "exceeds the maximum upload size" in response.text
    assert 'data-progress="file-check-progress"' in response.text


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
    response = post_form(
        "/register",
        files={"file": ("artifact.txt", content, "text/plain")},
    )
    assert response.status_code == 200
    assert digest in response.text
    assert "http://testserver/etr/" in response.text
    assert "Anchor Record accepted by a relay" in response.text


def test_register_artifact_accepts_campaign_id(publisher):
    response = post_form(
        "/register",
        data={"campaign_id": "wine-2026"},
        files={"file": ("artifact.txt", b"wine", "text/plain")},
    )
    assert response.status_code == 200
    assert "http://testserver/wine-2026/" in response.text


@pytest.mark.parametrize("overlap", [True, False])
def test_registration_displays_publication_and_query_scope(monkeypatch, publisher, overlap):
    from app import main
    target = "wss://publisher.example.org"
    query = target if overlap else "wss://query.example.org"
    monkeypatch.setattr(main, "DEFAULT_RELAYS", [query])
    async def publish(artifact, **kwargs):
        return {"published": True, "event_id": "a" * 64, "publisher": "test-publisher",
                "message": "Accepted", "target_relays": [target, "wss://unconfirmed.example.org"],
                "relays": [target]}
    monkeypatch.setattr(main, "publish_anchor", publish)
    response = post_form("/register", files={"file": ("test.txt", b"test", "text/plain")})
    assert response.status_code == 200
    assert "Publication targets" in response.text
    assert "Confirmed relay acceptance" in response.text
    assert "QR lookup relays" in response.text
    assert target in response.text and query in response.text
    assert "wss://unconfirmed.example.org" in response.text
    assert ("None of the relays that acknowledged" in response.text) is not overlap


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
    mock_blob(monkeypatch, content)
    response = client.get(f"/campaign/{digest}")
    assert response.status_code == 200
    assert "Download verified artifact" in response.text
    assert client.get(f"/api/campaign/{digest}").json()["artifact"]["verified"]
    response = client.get(f"/artifact/campaign/{digest}")
    assert response.content == content
    assert response.headers["content-disposition"].startswith("attachment;")
    mock_blob(monkeypatch, b"wrong bytes")
    assert client.get(f"/artifact/campaign/{digest}").status_code == 502
    assert "Download verified artifact" not in client.get(f"/campaign/{digest}").text


def test_registration_requires_signing_configuration(monkeypatch):
    from app import main
    monkeypatch.setattr(main, "SIGNER_NSEC", None)
    monkeypatch.setattr(main, "REGISTRATION_MODE", "service")
    response = post_form("/register", files={"file": ("test.txt", b"test", "text/plain")})
    assert response.status_code == 503


@pytest.mark.parametrize("content, media_type", [(b"%PDF-1.7\npreview", "application/pdf"), (b"\x89PNG\r\n\x1a\npreview", "image/png")])
def test_verified_preview_response(monkeypatch, content, media_type):
    import io
    from app import registration
    digest = hashlib.sha256(content).hexdigest()
    mock_blob(monkeypatch, content)
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
    mock_blob(monkeypatch, content)
    assert client.get(f"/artifact/etr/{digest}?preview=true").status_code == 415
    assert client.get(f"/artifact/etr/{digest}").status_code == 200


def test_gs1_registration_and_routes(publisher, monkeypatch):
    from app import main
    from app.gs1 import TEST_GTIN
    from app.registration import base64url_digest
    monkeypatch.setattr(main, "PUBLIC_BASE_URL", "https://example.com")
    content = b"GS1 artifact"
    digest = hashlib.sha256(content).hexdigest()
    encoded = base64url_digest(digest)
    seen = {}
    async def publish(artifact, **kwargs):
        seen.update(kwargs)
        return {"published": True, "message": "Accepted"}
    monkeypatch.setattr(main, "publish_anchor", publish)
    response = post_form("/register", data={"gs1_gtin": TEST_GTIN, "gs1_lot": "LOT1"},
                         files={"file": ("test.txt", content, "text/plain")})
    assert response.status_code == 200
    assert seen["gs1"].tags == [["gs1_gtin", TEST_GTIN], ["gs1_lot", "LOT1"]]
    path = f"/01/{TEST_GTIN}/10/LOT1?d={encoded}"
    assert "https://example.com" + path in response.text
    assert "https://example.com/etr/" in response.text
    assert "Documentation test GTIN" in response.text
    payloads = []
    def render(url):
        payloads.append(url)
        return b"png"
    monkeypatch.setattr(main, "render_qr_png", render)
    assert client.get("/gs1/qr" + path).status_code == 200
    assert payloads == ["https://example.com" + path]
    mock_blob(monkeypatch, content)
    response = client.get(path)
    assert response.status_code == 200
    assert "No verified anchor with matching GS1 values" in response.text
    assert "Download verified artifact" in response.text
    from app.resolver import ResolutionResult, event_to_evidence
    from stroma import Event, Keys
    event = Event(kind=1415, content="", tags=[["o", digest], ["action", "issue"], *seen["gs1"].tags])
    event.sign(Keys())
    async def matched(*args):
        return ResolutionResult(digest, "hex", [], "now", [event_to_evidence(event, digest)])
    monkeypatch.setattr(main, "perform_lookup", matched)
    assert "A cryptographically verified anchor contains matching GS1 values" in client.get(path).text
    assert "No verified anchor with matching GS1 values" in client.get(path.replace("LOT1", "LOT2")).text
    response = client.get("/resolve", params={"reference": "https://example.com" + path}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == path
    legacy = path.replace("?d=", "?digest=")
    assert client.get(legacy).status_code == 200
    assert client.get("/gs1/qr" + legacy).status_code == 200
    response = client.get("/resolve", params={"reference": "https://example.com" + legacy}, follow_redirects=False)
    assert response.headers["location"] == path


@pytest.mark.parametrize("fields", [{"gs1_gtin": "123"}, {"gs1_lot": "LOT"},
                                   {"gs1_gtin": "09520123456788", "gs1_serial": "x" * 43}])
def test_invalid_gs1_does_not_publish(publisher, monkeypatch, fields):
    from app import main
    async def forbidden(*args, **kwargs):
        pytest.fail("Invalid GS1 data must not cause storage or publication")
    monkeypatch.setattr(main, "publish_anchor", forbidden)
    monkeypatch.setattr(main, "maybe_upload_to_blossom", forbidden)
    response = post_form("/register", data=fields, files={"file": ("x.txt", b"x", "text/plain")})
    assert response.status_code == 400


@pytest.mark.parametrize("path", ["/01/123?digest=no", "/01/09520123456788",
                                 "/gs1/qr/01/09520123456788?digest=no"])
def test_invalid_gs1_routes(path):
    assert client.get(path).status_code == 400


def test_mp4_preview_and_verified_ranges(monkeypatch):
    content = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 4 + b"isommp42" + b"video test data"
    digest = hashlib.sha256(content).hexdigest()
    mock_blob(monkeypatch, content)
    path = f"/artifact/etr/{digest}?preview=true"
    response = client.get(path)
    assert response.status_code == 200
    assert response.content == content
    assert response.headers["content-type"] == "video/mp4"
    assert response.headers["accept-ranges"] == "bytes"
    page = client.get(f"/etr/{digest}")
    assert 'data-media-type="video/mp4"' in page.text
    assert 'controls playsinline preload="metadata"' in page.text
    for header, start, end in [("bytes=0-1", 0, 1), ("bytes=10-", 10, len(content)-1),
                                ("bytes=-8", len(content)-8, len(content)-1),
                                ("bytes=0-999", 0, len(content)-1)]:
        response = client.get(path, headers={"Range": header})
        assert response.status_code == 206
        assert response.content == content[start:end+1]
        assert response.headers["content-range"] == f"bytes {start}-{end}/{len(content)}"
    for header in ["bytes=999-", "bytes=10-1", "bytes=-0", "bytes=-", "bytes=0-1,4-5", "nonsense"]:
        response = client.get(path, headers={"Range": header})
        assert response.status_code == 416
        assert response.headers["content-range"] == f"bytes */{len(content)}"
    mock_blob(monkeypatch, b"wrong bytes")
    assert client.get(path, headers={"Range": "bytes=0-1"}).status_code == 502
