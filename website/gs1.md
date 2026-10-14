# GS1 Digital Links

A GS1 Digital Link carries a GTIN and optional lot and serial identifiers.
OpenQR adds an artifact digest using the compact `d` query parameter.

New anchors use the indexed `g` tag for the canonical 14-digit GTIN. Readers
also accept legacy `gs1_gtin`; if both appear they must agree. Repeated tags,
malformed values, or conflicting aliases do not establish a product association.
Lot and serial remain `gs1_lot` and `gs1_serial`. Product discovery can use
`{"kinds": [1415], "#g": ["09520123456788"]}`; digest lookup still uses `#o`.
Old anchors with only `gs1_gtin` cannot be found through a `#g` filter alone.

## Generate From A Result

After checking a link or original file, OpenQR automatically displays a GS1 link
and QR code when verified anchor tags supply a valid GTIN. Optional lot and serial
tags are included when present; absent fields are omitted. The digest comes from
the displayed result. The panel offers copy-link, copy-image, and download controls.
There is no manual-entry form. Missing, invalid, or conflicting product associations
do not produce a GS1 panel; values from different anchors are never combined.

!!! warning "Use authorized identifiers"
    Supply identifiers you are authorized to use in accordance with GS1
    standards. Formatting and check-digit validation do not establish assignment,
    authorization, or physical authenticity. Documentation examples are not
    product allocations.

```text
https://example.com/01/09520123456788/10/LOT1/21/ITEM1?d=cvJo153DZBKiHQRswhJLnKAqqzxxLrI-Z_2W2Go4448
```

New links use `d`, saving five bytes compared with `digest`. Both names are
accepted, with hexadecimal or Base64URL digest values. Use exactly one name and
one value; duplicates and both aliases together are rejected.

## Optional Campaign

Registration also accepts a separate campaign query identifier. Generated links
use `c`; readers accept `c` or `campaign`. For example:

```text
https://example.com/01/09520123456788/10/LOT1?d=cvJo153DZBKiHQRswhJLnKAqqzxxLrI-Z_2W2Go4448&c=wine-2027
```

Missing, empty, or whitespace-only campaign values are ignored and omitted from
generated links. A non-empty value must begin with a letter or digit and contain
only letters, digits, hyphens, or underscores, up to 64 characters. More than one
non-empty value is rejected, including repeated values or both aliases together.
An empty alias alongside one non-empty alias is accepted.

This parameter is preserved through link redirects, sharing, and QR generation
for both regular and GS1 links. It is independent of the existing resolver path,
does not change the digest, and is not added to the signed anchor. It is an
untrusted routing hint reserved for future campaign behavior, not proof of
campaign membership or authority. No campaign-specific lookup rules are applied.

## Association Is Not Publication

Generating a link from a result does not change or publish an anchor. OpenQR
uses verified anchor tags, not user-supplied URL values, to generate the panel.
Incoming links with unmatched identifiers retain an explicit warning.
Generation does not establish that
the identifiers occur inside the artifact itself.

Supplying GS1 fields during registration includes them in the signed anchor.
Neither flow proves that the label is attached to the genuine physical item.

OpenQR supports a bounded GS1 URI profile, not a complete GS1-conformant resolver
service. Checkout support depends on the retailer's equipment and application.
See the [implementation note and standards](references.md).
