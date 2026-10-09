# OpenQR

OpenQR is a minimal public resolver for the
[OpenETR QR Resolver Profile 1.0](https://github.com/trbouma/openetr/blob/main/docs/specs/OPENETR_QR_RESOLVER_PROFILE_1_0.md).
It accepts the SHA-256 digest carried by a conforming OpenETR QR URL, queries
configured Nostr relays for kind `1415` Anchor Records carrying that digest in
the `o` tag, and verifies the returned event identifiers and signatures.

OpenQR is deliberately read-only with respect to OpenETR evidence. It does not
issue records, hold OpenETR issuer keys, manage visitor accounts, or determine
whether evidence has legal or institutional effect. A separately configured
deployment key may authorize optional Blossom storage only.

The `/register` surface accepts a Digital Artifact, calculates its SHA-256
digest, and creates a compact resolver QR. Registration does not publish an
OpenETR Anchor Record. A deployment can optionally authorize storage of the
uploaded bytes on its configured Blossom server.

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
| `OPENQR_BLOSSOM_NSEC` | unset | Deployment key used only to authorize Blossom uploads |
| `OPENQR_BLOSSOM_TIMEOUT_SECONDS` | `20` | Blossom request timeout |
| `OPENQR_BIND_ADDRESS` | `127.0.0.1` | Docker host bind address |
| `OPENQR_PORT` | `8000` | Docker host port |

Copy `.env.example` to `.env` to customize Docker Compose settings.

Set `OPENQR_PUBLIC_BASE_URL` to the production HTTPS origin before generating
production QR codes. To enable the optional Blossom checkbox, provide a
dedicated `OPENQR_BLOSSOM_NSEC`; OpenQR never displays this secret or asks a
visitor to provide one.

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
