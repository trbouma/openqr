# OpenQR

[User documentation](https://trbouma.github.io/openqr/) covers checking artifacts,
registration, GS1 links, and verification boundaries. To preview locally, run
`poetry install --with docs`, then `poetry run mkdocs serve --dev-addr 127.0.0.1:8001`.
Validate documentation with `poetry run mkdocs build --strict`.

OpenQR is a minimal public resolver for the
[OpenETR QR Resolver Profile 1.0](https://github.com/trbouma/openetr/blob/main/docs/specs/OPENETR_QR_RESOLVER_PROFILE_1_0.md).
It accepts the SHA-256 digest carried by a conforming OpenETR QR URL, queries
configured Nostr relays for kind `1415` Anchor Records carrying that digest in
the `o` tag, and verifies the returned event identifiers and signatures.

Nostr relay queries, keys, and event signing use
[Stroma](https://github.com/trbouma/stroma). Poetry locks the Git dependency to
a specific commit for reproducible installs and container builds. Stroma
discards events with invalid identifiers or signatures during relay retrieval;
OpenQR also checks the returned anchor's kind and artifact digest.

OpenQR uses the installable [OpenETR component](https://github.com/trbouma/openetr)
for relay-backed Control Desk identities and profile signer records. Registration
defaults to interactive mode: sign in with an existing Control Desk Key, select
an Acting Profile, then register an artifact. The profile signs the anchor and
authorizes any requested Blossom storage. QR lookup remains public.
OpenQR does not determine recognition, legal identity, or institutional effect.

The `/register` surface accepts a Digital Artifact, calculates its SHA-256
digest, publishes a signed kind `1415` Anchor Record, and creates a compact
resolver QR. Blossom storage is opt-in.
The result reports storage and relay acknowledgement separately. Unconfirmed
publication may still have reached a relay; check the resolver before retrying.

Opening a resolver link combines verified anchor Blossom hints, configured query
servers, and upload servers in one Stroma BlossomPool. Origins are normalized and
deduplicated; requests run concurrently and the first digest-verified copy wins.
This is not sequential fallback. Verified bytes can be downloaded through
`/artifact/{campaign_id}/{digest}`; the download rechecks the digest. Missing,
oversized, or mismatched artifacts are reported without hiding retrieved anchor
evidence. The JSON resolver includes artifact retrieval status.

New anchors include repeated `["blossom", "https://server.example.org"]` tags
only for servers confirmed by digest-verified readback before signing. Existing
anchors without hints remain resolvable through configured servers. Hints are
displayed with the anchor and do not guarantee current availability.

Uploads go only to `OPENQR_BLOSSOM_SERVERS`; query servers and anchor hints never
become upload destinations. All configured upload servers are attempted.
`OPENQR_BLOSSOM_REQUIRE` controls confirmation: `any` (one, default),
`half` (ceil(N/2)), `majority` (floor(N/2)+1), or `all` (N), counting unique
origins including failed targets. An unmet requirement stops anchor publication;
some copies may already exist. Retry checks existing bytes before uploading.
Each configured pool and the hint list is limited to 32 origins; the combined
retrieval pool supports up to 96 unique origins, four concurrent requests, and
an overall deadline. Public HTTPS is required; private destinations and redirects
are blocked by Stroma.

## Registration Identity

On `/register`, sign in with an existing OpenETR Control Desk nsec. Set
`OPENQR_HOME_RELAYS` to the relays holding that root's encrypted profile records.
Select an Acting Profile from the name-only dropdown; its public key and profile
details appear below. Create/manage profiles in the OpenETR Control Desk or CLI.
OpenQR checks membership and reloads the encrypted profile signer before each
registration. Anchor publication uses the profile's configured relays (home
relays when absent); public lookup uses `OPENQR_RELAYS`.
Registration results show publication targets, relays that acknowledged the
anchor, and the public QR lookup scope. A warning appears when no acknowledged
relay overlaps the lookup scope. An accepted event is not proof of later
retention or indexing. A timeout is unconfirmed, not proof of rejection.

If a QR link finds the artifact but not the anchor, compare those relay lists.
Blossom bytes can be retrieved independently of Nostr events. Include an
acknowledged publication relay in `OPENQR_RELAYS`, or configure the Acting
Profile to publish where the resolver queries. Changing `OPENQR_HOME_RELAYS`
alone does not expand public lookup. No automatic republishing is performed.

The app owns HTTP sessions and CSRF protection, while OpenETR owns identity
record conventions and decryption. `app/identity.py` isolates the component's
current internal async configuration APIs; it never imports the OpenETR web app
or reads/writes local user configuration. Those adapter imports should be checked
when updating OpenETR until a stable public identity facade is available.

The server handles the submitted nsec: this is a trusted-server key-custody model,
not a browser-only signer. Secrets are never rendered back into HTML. Sessions
are encrypted, HTTP-only cookies with SameSite protection and an eight-hour
expiry. Every state-changing form requires a CSRF token. Use HTTPS and a stable,
high-entropy `OPENQR_SESSION_SECRET` shared by all workers. Do not log request
bodies. Sign-out clears the browser cookie; it cannot revoke a previously stolen
cookie. Rotating the deployment session secret invalidates all sessions.

Service registration must be explicitly enabled using
`OPENQR_REGISTRATION_MODE=service`. Only that mode uses deployment signing keys;
there is no silent fallback in interactive mode. Protect service-mode registration
with your reverse proxy's authentication/access policy because visitors can
otherwise cause the deployment key to sign records.

Resolver pages render PDF documents with page controls using the same bundled
PDF.js viewer as OpenETR, and display PNG, JPEG, GIF, and WebP images inline.
Preview types are detected from verified bytes. Other formats remain available
as downloads. PDF.js and its fonts are served locally under `app/static/js`,
with their upstream license notices preserved.

## Run Locally With Poetry

```sh
poetry install
poetry run uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000>. The live example from the specification is:

```text
http://127.0.0.1:8000/etr/cvJo153DZBKiHQRswhJLnKAqqzxxLrI-Z_2W2Go4448
```

The same result is available as JSON:

```text
http://127.0.0.1:8000/api/etr/cvJo153DZBKiHQRswhJLnKAqqzxxLrI-Z_2W2Go4448
```

The first path segment is a campaign identifier. The resolver passes it to the
lookup handler as an extension point for later campaign-specific behavior. The
default `etr` path remains valid, and another campaign can use the same lookup
surface:

```text
http://127.0.0.1:8000/wine-2026/cvJo153DZBKiHQRswhJLnKAqqzxxLrI-Z_2W2Go4448
```

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `OPENQR_RELAYS` | `wss://relay.openetr.org` | Comma-separated relay query scope |
| `OPENQR_QUERY_TIMEOUT_SECONDS` | `10` | Relay connection and query timeout |
| `OPENQR_QUERY_LIMIT` | `20` | Maximum candidate Anchor Records |
| `OPENQR_PUBLIC_BASE_URL` | Request origin | Public origin encoded in generated QR links |
| `OPENQR_MAX_UPLOAD_BYTES` | `26214400` | Maximum registration upload size |
| `OPENQR_BLOSSOM_SERVER` | `https://blossom.getsafebox.app` | Default artifact storage server |
| `OPENQR_BLOSSOM_SERVERS` | Single-server setting | Comma/whitespace-separated upload origins |
| `OPENQR_BLOSSOM_QUERY_SERVERS` | Upload pool | Additional retrieval origins |
| `OPENQR_BLOSSOM_REQUIRE` | `any` | Upload confirmation requirement |
| `OPENQR_BLOSSOM_OPERATION_TIMEOUT_SECONDS` | `60` | Overall storage/retrieval deadline |
| `OPENQR_REGISTRATION_MODE` | `interactive` | Interactive profiles or explicit `service` mode |
| `OPENQR_HOME_RELAYS` | `OPENQR_RELAYS` | Relay-backed Control Desk configuration scope |
| `OPENQR_SESSION_SECRET` | Ephemeral development secret | Required stable encryption secret in Compose |
| `OPENQR_SESSION_SECURE` | HTTPS public URL detection | Secure cookies; Compose defaults to `true` |
| `OPENQR_REQUIRE_SESSION_SECRET` | `false` | Fail startup without secret; Compose sets `true` |
| `OPENQR_BLOSSOM_NSEC` | unset | Service-mode storage key and fallback anchor signer |
| `OPENQR_SIGNER_NSEC` | `OPENQR_BLOSSOM_NSEC` | Service-mode anchor signer |
| `OPENQR_BLOSSOM_TIMEOUT_SECONDS` | `20` | Blossom request timeout |
| `OPENQR_BIND_ADDRESS` | `127.0.0.1` | Docker host bind address |
| `OPENQR_PORT` | `8000` | Docker host port |

Copy `.env.example` to `.env` to customize Docker Compose settings.

Set `OPENQR_PUBLIC_BASE_URL` to the production HTTPS origin before generating
production QR codes. Generate the session secret with `openssl rand -hex 32`.
Existing deployment keys are ignored unless you explicitly choose service mode.
Interactive users sign in with their existing OpenETR root and select a profile.

For explicit service mode, generate a dedicated key locally with:

```sh
poetry run python -c "from stroma import Keys; print(Keys().private_key_bech32())"
```

Store the resulting secret as `OPENQR_BLOSSOM_NSEC` in `.env` and explicitly set
`OPENQR_REGISTRATION_MODE=service`. For local development, load the file with
`poetry run uvicorn app.main:app --reload --env-file .env`.
When testing on HTTP localhost, set `OPENQR_SESSION_SECURE=false`; retain
`true` behind your HTTPS reverse proxy.

## Docker Compose

```sh
docker compose up --build --detach
docker compose ps
```

For an existing deployment with a clean working tree:

```sh
./refresh-containers.sh
```

The refresh script pulls fast-forward changes, validates the Compose file,
rebuilds and recreates the service, and waits for `/health` to report success.

## Tests

```sh
poetry run pytest
```
## Check an original file

The home page accepts an original file as an alternative to a digest or URL.
OpenQR hashes the uploaded bytes in chunks, closes/discards the temporary upload,
and redirects to the normal digest lookup. No account or signing key is required;
no event is published and no copy is sent to Blossom. The upload is sent to the
OpenQR server, not hashed exclusively in the browser. Framework multipart handling
may spool it to temporary disk. `OPENQR_MAX_UPLOAD_BYTES` and proxy upload limits
apply. The resulting page independently retrieves signed evidence and, if available,
a verified artifact from Blossom; absence of a stored copy does not preclude evidence.

## MP4 playback

Artifact resolution previews recognized MP4 containers in a native browser video
player with playback, seeking, volume, and fullscreen controls. Playback does not
autostart. Browser codec support still applies; H.264 video with AAC audio is a
practical interoperability choice. OpenQR does not transcode or change the artifact.

The preview endpoint serves `video/mp4` and supports single byte-range requests.
The entire file is fetched and SHA-256 verified before any range is returned.
There is no persistent artifact cache, so preview and seeking requests can cause
repeat full retrievals. Large files require sufficient memory and retrieval time;
this is verified-file playback, not a streaming CDN.

Set `OPENQR_MAX_UPLOAD_BYTES` and the reverse proxy body limit to accommodate the
file. For slow servers, review `OPENQR_BLOSSOM_TIMEOUT_SECONDS` and
`OPENQR_BLOSSOM_OPERATION_TIMEOUT_SECONDS`. The same artifact size limit applies
to retrieval. Unsupported containers/codecs retain the download option.

## GS1 Digital Link integration

See the [GS1 Digital Link and campaign resolver implementation note](docs/GS1_DIGITAL_LINK_IMPLEMENTATION_NOTE.md)
for the FastAPI request flow, comparison of the two URL paths, signed tag
conventions, and specification boundaries.

Registration optionally accepts a GTIN, batch/lot (AI 10), and serial number
(AI 21). Leave these blank to retain the existing digest-only workflow. For a
demonstration, enter `09520123456788`, the documentation example GTIN; it is
explicitly labelled test data, not a production-assigned identifier.

OpenQR validates GTIN length and check digit, normalizes it to 14 digits, and
validates optional qualifiers (maximum 20 GS1 characters). This implementation
excludes slash and dot-only qualifiers for safe routing. It does not verify GS1
assignment or certify retail barcode print quality. Use HTTPS and a legitimately
assigned product GTIN for production; HTTP is supported for local development.

Registration generates both the existing `/{campaign}/{digest}` QR and a normal
QR encoding a GS1 Digital Link with an OpenQR extension:

```text
https://example.com/01/09520123456788?d=cvJo153DZBKiHQRswhJLnKAqqzxxLrI-Z_2W2Go4448
```

Generated GS1 links use `d` to save five bytes. The descriptive `digest` parameter
remains supported with identical meaning. Supply either name exactly once, not
both; both accept lowercase hex or canonical unpadded Base64URL digests.

Optional qualifiers appear in order `/10/{lot}/21/{serial}`. The full SHA-256
digest remains in the `d` (or `digest`) query parameter, not AI 21. Incoming digest values
may be lowercase hex or canonical unpadded Base64URL; generated links use the
latter. No serial-to-digest database is needed. GS1 links currently use the
default `etr` resolution handler, independently of the registration campaign.

Before signing the kind 1415 anchor, OpenQR adds these application-convention tags:

| Tag | Value |
| --- | --- |
| `gs1_gtin` | Normalized 14-digit GTIN |
| `gs1_lot` | Optional batch/lot |
| `gs1_serial` | Optional serial number, never the full digest |

The existing `o` tag retains the full hexadecimal artifact digest. These tags
are signed publisher assertions, not proof of GS1 allocation or bottle authenticity.
No new OpenETR event kind is introduced.

The `/01/{gtin}` route (with optional qualifiers) retrieves by digest and renders
the artifact, both QR options, and anchor details. It reports whether a verified
issue anchor with exactly matching digest and GS1 fields was found. A mismatch
does not suppress other evidence or prevent independent artifact verification.
The home-page lookup also accepts this Digital Link profile. `/gs1/qr/01/...`
renders its PNG. Both query entry points require exactly one `d` or `digest` parameter;
other GS1 keys, extensions and general resolver behaviours are not implemented.

This is a bounded Digital Link integration, **not a GS1-conformant resolver**.
Production use additionally requires appropriate GS1 identifier allocation,
retail symbol dimensions, quiet zone, placement, print verification and scanner
testing. A copied label remains copyable, and the same artifact can describe
multiple bottles; use genuine serialization where individual identity matters.

References: [GS1 Digital Link URI Syntax](https://ref.gs1.org/standards/digital-link/uri-syntax/1.7.0/),
[GS1 Resolver Standard](https://ref.gs1.org/standards/resolver/),
[Retail 2D implementation guidance](https://ref.gs1.org/guidelines/2d-in-retail/).
