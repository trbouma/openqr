# GS1 Digital Link and Campaign Resolver Implementation

Status: implementation note describing the current OpenQR application.

OpenQR supports two URL entry points into the same artifact lookup: a campaign
path carrying an artifact digest, and a GS1 Digital Link carrying a product GTIN
plus the digest. Neither requires a database mapping a serial number to a digest.
Both preserve the full SHA-256 identity of the artifact and use the same relay
and Blossom retrieval services.

This note supports the
[OpenETR QR Resolver Profile 1.0](https://github.com/trbouma/openetr/blob/main/docs/specs/OPENETR_QR_RESOLVER_PROFILE_1_0.md).
It documents application behaviour, not a new OpenETR core protocol or a claim
of complete GS1 resolver conformance.

## Relationship to the Specification

The OpenETR specification separates the Resolver Profile from the Resolution
Reference. Its Standard Web Resolver Profile disallows query strings and
fragments; custom profiles can document query syntax needed for dispatch.

The GS1 entry point is therefore a **custom direct-resolution extension**, not
the query-free Standard Web Resolver Profile. Its `d` (alias `digest`) parameter is the
artifact's Resolution Reference. The GTIN and optional qualifiers identify the
associated product or item; they are not substitutes for the artifact digest or
additional OpenETR record identifiers.

This implementation note defines the supported URL shape. A separately versioned
GS1/OpenETR profile identifier and broader interoperability contract have not yet
been standardized. Existing generic API metadata must not be interpreted as a
claim of a standardized GS1-specific profile.

## Two Entry Points

These illustrative links identify the same artifact:

```text
https://example.com/wine2026/cvJo153DZBKiHQRswhJLnKAqqzxxLrI-Z_2W2Go4448

https://example.com/01/09520123456788?d=cvJo153DZBKiHQRswhJLnKAqqzxxLrI-Z_2W2Go4448
```

The example GTIN is documentation test data, not a production allocation.

| Aspect | Campaign and digest route | GS1 Digital Link route |
| --- | --- | --- |
| URL shape | `/{campaign_id}/{reference}` | `/01/{gtin}?d={reference}` |
| Optional path fields | None after the reference | `/10/{lot}`, then `/21/{serial}` |
| Artifact identity | SHA-256 digest in the path | SHA-256 digest in the query |
| Accepted digest encodings | Lowercase hex or canonical unpadded Base64URL | Same |
| Generated encoding | Base64URL | Base64URL |
| Campaign dispatch | Passed to `perform_lookup`; presently unused | Uses default `etr` context |
| Product information | Not asserted by the URL | GTIN and optional batch/serial |
| Relay search key | Hex digest in `#o`, kind 1415 | Same; GTIN is not the relay search key |
| Database mapping | None | None |
| Additional verification | Event ID and signature | Also checks signed product association |
| QR image route | `/qr/{campaign_id}/{reference}` | `/gs1/qr/01/{gs1_path}` with `d` or `digest` query |

Although the first path includes a campaign name, it is **not** the specification's
indirect campaign-reference model: its reference is already a digest. It does not
currently select campaign policy, enforce redemption, or map an opaque label ID.

## FastAPI Request Flow

The GS1 handler is registered before the generic campaign route in
[`app/main.py`](../app/main.py):

```python
@app.get("/01/{gs1_path:path}", response_class=HTMLResponse)
async def resolve_gs1(request: Request, gs1_path: str):
    try:
        data, digest = parse_link("/01/" + gs1_path, request.url.query)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return await render_resolution(request, "etr", digest, gs1=data)
```

The `:path` converter captures optional qualifier segments as well as the GTIN.
Declaring it first prevents `/01/{gtin}` from being interpreted as campaign `01`
and an artifact reference. Consequently, `01` is effectively reserved for GS1
at this route boundary.

The ordinary handler instead calls
`render_resolution(request, campaign_id, reference)`. Both paths converge on:

1. Query configured `OPENQR_RELAYS` for kind 1415 anchors with the hexadecimal
   digest in `#o`.
2. Check event structure, event ID, and cryptographic signature.
3. Collect usable Blossom hints from verified issue anchors matching the digest.
4. Retrieve the artifact using the combined hint, query-server, and upload-server
   pool. This is a pooled retrieval, not a strict sequential fallback.
5. Verify the retrieved bytes against the requested digest.
6. Render the artifact preview or download option, QR information, and evidence.

The handler does not resolve the incoming URL's domain through GS1, contact a
GS1 allocation registry, or establish physical product authenticity. Anchor-only
discovery is also not a complete evaluation of later OpenETR evidence or a
transferable-record ruleset.

## Parsing and Validation

[`app/gs1.py`](../app/gs1.py) implements a deliberately bounded subset:

- Incoming Digital Links require a 14-digit GTIN with a valid check digit.
- Registration accepts GTIN-8, GTIN-12, GTIN-13, or GTIN-14 and pads to 14 digits.
- Batch/lot and serial are optional, limited to 20 supported GS1 characters,
  and ordered as AI 10 before AI 21 when both occur.
- Slash-containing and dot-only qualifiers are excluded for safe application routing.
- Exactly one `d` or `digest` parameter is required. Both names together, duplicate values, other query
  parameters, unsupported AIs, invalid qualifiers, and invalid digests are rejected.
- Base64URL values must decode canonically to exactly 32 bytes.

This is not a general-purpose parser for every valid GS1 Digital Link. For
example, AI 22 and expiry attributes are not implemented. Valid GS1 links outside
this supported subset may receive HTTP 400.

The home-page `/resolve` endpoint also recognizes pasted GS1 URLs, validates them,
and redirects to the equivalent local GS1 route. It does not fetch the pasted
external URL. It rejects fragments in pasted URLs; fragments in browser navigation
are not transmitted to FastAPI. Generated links contain no fragment.

## Registration and Signed Tags

Registration validates optional GS1 inputs before storage or publication.
[`publish_anchor()`](../app/registration.py) adds these tags before signing:

```json
[
  ["o", "72f268d79dc36412a21d046cc2124b9ca02aab3c712eb23e67fd96d86a38e38f"],
  ["action", "issue"],
  ["gs1_gtin", "09520123456788"],
  ["gs1_lot", "LOT1"],
  ["gs1_serial", "BOTTLE000001"]
]
```

Absent optional values are omitted. The `gs1_*` names are OpenQR application
conventions for structured event data, not newly allocated GS1 Application
Identifiers. The normal anchor metadata and confirmed Blossom hints remain.
See the [OpenETR wire-format specification](https://github.com/trbouma/openetr/blob/main/docs/specs/OPENETR_NOSTR_WIRE_FORMAT_SPEC.md)
for the underlying event model.

The full digest never occupies AI 21: 43-character Base64URL or 64-character hex
does not fit the 20-character serial field. It stays in `o` in the event and
`d` in generated Digital Links, saving five ASCII bytes compared with `digest`.
The descriptive `digest` alias remains supported, with the same validation and
meaning. Generation and redirects canonicalize to `d`; previously printed links
remain usable. The registration campaign is carried by the regular
link, not the GS1 link or these GS1 tags.

Supplying a GTIN generates both QR options on the registration result. Leaving
all GS1 fields blank preserves ordinary registration. The same `qrcode` renderer
is used for both; no FNC1 mode is required for the URL-based Digital Link.

## Product Association and Recognition

The result page calls `GS1Data.matches()` against the returned anchors. A match
requires a cryptographically verified issue anchor, exactly one matching `o` and
GTIN value, and matching optional lot/serial values. Omitted URL qualifiers must
also be absent from the matching anchor; this is exact matching, not GS1
hierarchical resolver fallback.

If at least one anchor matches, the page reports a matching signed assertion.
Otherwise it warns that the association is unconfirmed. Other anchors are still
shown, and independent artifact retrieval is not suppressed. Multiple or
conflicting publisher assertions are not globally settled by this check.

A valid signature establishes that a signing key asserted the association. It
does not establish that the signer controls the GTIN, that a bottle is genuine,
or that the assertion has legal effect. Recognition and authority remain matters
for the integrating application and its ruleset. Identical files share a digest,
even when associated with multiple products or bottles.

## Boundaries and Verification

Production deployments need HTTPS, appropriately assigned identifiers, and
applicable barcode size, quiet-zone, placement, and print-quality checks. HTTP
is supported for local development. The displayed test GTIN warning and check-digit
validation are not allocation verification or certification.

OpenQR does not implement the full GS1-Conformant Resolver Standard, including
general linksets, link-type selection, or resolver discovery. Existing digest
URLs and APIs remain available; the GS1 route is an additional HTML entry point.

Tests in [`tests/test_gs1.py`](../tests/test_gs1.py) and
[`tests/test_app.py`](../tests/test_app.py) cover normalization, qualifier order,
invalid inputs, signed tags, product-association matches and mismatches,
registration output, QR payload construction, and pasted-link dispatch.
They do not certify scanner interoperability or printed labels.

## Related Specifications

- [OpenETR QR Resolver Profile 1.0](https://github.com/trbouma/openetr/blob/main/docs/specs/OPENETR_QR_RESOLVER_PROFILE_1_0.md)
- [OpenETR QR production and scratch-off considerations](https://github.com/trbouma/openetr/blob/main/docs/specs/OPENETR_QR_PRODUCTION_AND_SCRATCH_OFF_DESIGN_NOTE.md)
- [GS1 Digital Link URI Syntax](https://ref.gs1.org/standards/digital-link/uri-syntax/1.7.0/)
- [GS1-Conformant Resolver Standard](https://ref.gs1.org/standards/resolver/)
- [GS1 retail 2D barcode guidance](https://ref.gs1.org/guidelines/2d-in-retail/)
