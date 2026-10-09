import base64
import json

from stroma import Event, Keys

from app.registration import blossom_auth_header, render_qr_png


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
