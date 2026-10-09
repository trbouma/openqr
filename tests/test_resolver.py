import base64

import pytest

from app.resolver import InvalidResolutionReference, normalize_digest, normalize_lookup

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
