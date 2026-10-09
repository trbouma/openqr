import base64
import asyncio

import pytest
from stroma import Event, Keys

from app.resolver import (
    InvalidResolutionReference, event_to_evidence, normalize_digest,
    normalize_lookup, resolve_anchor_evidence,
)

DIGEST = "72f268d79dc36412a21d046cc2124b9ca02aab3c712eb23e67fd96d86a38e38f"
BASE64URL = "cvJo153DZBKiHQRswhJLnKAqqzxxLrI-Z_2W2Go4448"


def test_hex_digest_is_accepted():
    assert normalize_digest(DIGEST) == (DIGEST, "hex")


def test_base64url_digest_is_normalized():
    assert normalize_digest(BASE64URL) == (DIGEST, "base64url")
    assert base64.urlsafe_b64encode(bytes.fromhex(DIGEST)).decode().rstrip("=") == BASE64URL


def test_standard_resolver_url_is_accepted():
    assert normalize_digest(f"https://example.com/etr/{BASE64URL}") == (
        DIGEST,
        "base64url",
    )


def test_campaign_path_is_extracted_from_resolver_url():
    assert normalize_lookup(f"https://example.com/wine-2026/{BASE64URL}") == (
        "wine-2026",
        DIGEST,
        "base64url",
    )


def test_plain_digest_uses_default_campaign_path():
    assert normalize_lookup(BASE64URL) == ("etr", DIGEST, "base64url")


@pytest.mark.parametrize(
    "value",
    [
        "",
        DIGEST.upper(),
        f"{BASE64URL}=",
        "https://example.com/too/many/segments/" + BASE64URL,
        "https://example.com/etr/" + BASE64URL + "?source=label",
    ],
)
def test_invalid_references_are_rejected(value):
    with pytest.raises(InvalidResolutionReference):
        normalize_digest(value)


def signed_anchor(timestamp=1700000000):
    event = Event(kind=1415, created_at=timestamp, tags=[["o", DIGEST]], content="Test anchor")
    event.sign(Keys())
    return event


def test_stroma_anchor_verification_and_timestamp():
    evidence = event_to_evidence(signed_anchor(), DIGEST)
    assert evidence.verified
    assert evidence.created_at == "2023-11-14T22:13:20Z"


def test_modified_anchor_and_wrong_digest_fail_verification():
    event = signed_anchor()
    assert not event_to_evidence(event, "0" * 64).structure_valid
    event.content = "Modified after signing"
    evidence = event_to_evidence(event, DIGEST)
    assert not evidence.event_id_valid
    assert not evidence.verified


def test_stroma_query_normalizes_filters_and_orders_candidates(monkeypatch):
    from app import resolver

    older, newer = signed_anchor(), signed_anchor(1700000001)

    class Pool:
        def __init__(self, relays, *, timeout):
            assert relays == ["wss://example.com"]
            assert timeout == 5

        async def query(self, filters):
            assert filters == {"kinds": [1415], "#o": [DIGEST], "limit": 20}
            return [newer, older, newer]

    monkeypatch.setattr(resolver, "RelayPool", Pool)
    result = asyncio.run(resolve_anchor_evidence(
        BASE64URL, relays=["wss://example.com"], timeout=5,
    ))
    assert [anchor.event_id for anchor in result.anchors] == [older.id, newer.id]
    assert all(anchor.verified for anchor in result.anchors)
