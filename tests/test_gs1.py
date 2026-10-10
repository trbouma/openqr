import asyncio
from types import SimpleNamespace
from urllib.parse import urlsplit, unquote

import pytest
from stroma import Keys

from app.gs1 import GS1Data, TEST_GTIN, parse_link
from app.registration import base64url_digest, publish_anchor, UploadedArtifact
from app.resolver import event_to_evidence

DIGEST = "72f268d79dc36412a21d046cc2124b9ca02aab3c712eb23e67fd96d86a38e38f"


def test_round_trip_and_padding():
    data = GS1Data.validate(TEST_GTIN[1:], "BATCH%1", "BOTTLE001")
    url = urlsplit(data.url("https://example.com", DIGEST))
    assert url.path == f"/01/{TEST_GTIN}/10/BATCH%251/21/BOTTLE001"
    assert url.query == "d=" + base64url_digest(DIGEST)
    assert parse_link(unquote(url.path), url.query) == (data, DIGEST)
    assert parse_link(f"/01/{TEST_GTIN}", "digest=" + DIGEST)[1] == DIGEST


@pytest.mark.parametrize("name", ["d", "digest"])
@pytest.mark.parametrize("reference", [DIGEST, base64url_digest(DIGEST)])
def test_digest_parameter_aliases(name, reference):
    assert parse_link(f"/01/{TEST_GTIN}", name + "=" + reference)[1] == DIGEST


@pytest.mark.parametrize("gtin,lot,serial", [
    ("09520123456789", "", ""), ("abc", "", ""),
    (TEST_GTIN, "", "a" * 21), (TEST_GTIN, "a b", ""),
    (TEST_GTIN, "a/b", ""), (TEST_GTIN, "..", ""),
])
def test_bad_fields(gtin, lot, serial):
    with pytest.raises(ValueError):
        GS1Data.validate(gtin, lot, serial)


@pytest.mark.parametrize("suffix,query", [
    ("/21/one/10/two", "digest=" + DIGEST),
    ("/99/one", "digest=" + DIGEST),
    ("", ""), ("", "digest=no"),
    ("", "digest=" + DIGEST + "&digest=" + DIGEST),
    ("", "digest=" + DIGEST + "&unexpected=x"),
    ("", "d="), ("", "d=no"),
    ("", "d=" + DIGEST + "&d=" + DIGEST),
    ("", "d=" + DIGEST + "&digest=" + DIGEST),
    ("", "digest=" + DIGEST + "&d=" + "0" * 64),
    ("", "d=" + DIGEST + "&unexpected=x"),
])
def test_bad_links(suffix, query):
    with pytest.raises(ValueError):
        parse_link(f"/01/{TEST_GTIN}" + suffix, query)


def test_gs1_tags_are_signed_and_matched(monkeypatch):
    from app import registration
    data = GS1Data.validate(TEST_GTIN, "LOT1", "BOTTLE1")
    captured = []
    class Pool:
        def __init__(self, *args, **kwargs):
            pass
        async def publish(self, event):
            captured.append(event)
            return [SimpleNamespace(accepted=True, relay="wss://example.com")]
    monkeypatch.setattr(registration, "RelayPool", Pool)
    item = UploadedArtifact("test.txt", "text/plain", 1, DIGEST, b"x")
    asyncio.run(publish_anchor(item, signer_nsec=Keys().private_key_bech32(),
                              relays=["wss://example.com"], timeout=1, gs1=data))
    anchor = event_to_evidence(captured[0], DIGEST)
    assert anchor.verified
    assert all(tag in anchor.tags for tag in data.tags)
    assert data.matches(anchor, DIGEST)
    assert not GS1Data.validate(TEST_GTIN, "LOT2", "BOTTLE1").matches(anchor, DIGEST)
    assert not GS1Data.validate(TEST_GTIN).matches(anchor, DIGEST)
    assert not data.matches(anchor, "0" * 64)
    anchor.tags.append(["gs1_gtin", TEST_GTIN])
    assert not data.matches(anchor, DIGEST)
