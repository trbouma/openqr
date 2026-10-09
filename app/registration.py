from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

import qrcode
from fastapi import UploadFile
from stroma import Event, Keys, RelayPool


async def publish_anchor(artifact: UploadedArtifact, *, signer_nsec: str, relays: list[str], timeout: float) -> dict:
    keys = Keys(priv_k=signer_nsec)
    event = Event(kind=1415, content=f"Registered Digital Artifact {artifact.filename}", tags=[
        ["o", artifact.digest], ["action", "issue"], ["name", artifact.filename],
        ["size_bytes", str(artifact.size_bytes)],
        ["digest_generated_at", datetime.now(timezone.utc).isoformat()],
    ])
    event.sign(keys)
    try:
        acknowledgements = await asyncio.wait_for(
            RelayPool(relays, timeout=timeout).publish(event), timeout=timeout + 1,
        )
    except Exception:
        return {"published": False, "event_id": event.id, "publisher": keys.public_key_bech32(),
                "message": "Publication was not confirmed. A relay may still have received the event; check the resolver before retrying."}
    return {"published": True, "event_id": event.id, "publisher": keys.public_key_bech32(),
            "message": "Anchor Record accepted by a relay.",
            "relays": [ack.relay for ack in acknowledgements if ack.accepted]}


def fetch_artifact(digest: str, *, server: str, timeout: float, max_bytes: int) -> bytes:
    request = urllib.request.Request(blossom_blob_url(digest, server))
    with urllib.request.urlopen(request, timeout=timeout) as response:
        content = response.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise ValueError("Artifact exceeds the download size limit.")
    if hashlib.sha256(content).hexdigest() != digest:
        raise ValueError("Artifact digest verification failed.")
    return content


async def retrieve_artifact(digest: str, *, server: str, timeout: float, max_bytes: int) -> dict:
    try:
        content = await asyncio.to_thread(fetch_artifact, digest, server=server, timeout=timeout, max_bytes=max_bytes)
    except ValueError as exc:
        return {"verified": False, "message": str(exc)}
    except Exception:
        return {"verified": False, "message": "The artifact could not be retrieved from the configured Blossom server."}
    return {"verified": True, "size_bytes": len(content), "media_type": preview_type(content),
            "message": "Artifact retrieved and SHA-256 verified."}


def preview_type(content: bytes) -> str | None:
    if content.startswith(b"%PDF-"):
        return "application/pdf"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    return None

BLOSSOM_AUTH_KIND = 24242
BLOSSOM_AUTH_TTL_SECONDS = 5 * 60
READ_CHUNK_BYTES = 64 * 1024


class ArtifactUploadTooLarge(ValueError):
    pass


@dataclass(frozen=True)
class UploadedArtifact:
    filename: str
    media_type: str
    size_bytes: int
    digest: str
    content: bytes


async def read_artifact(file: UploadFile, *, max_bytes: int) -> UploadedArtifact:
    digest = hashlib.sha256()
    chunks: list[bytes] = []
    size_bytes = 0
    try:
        while chunk := await file.read(READ_CHUNK_BYTES):
            size_bytes += len(chunk)
            if size_bytes > max_bytes:
                raise ArtifactUploadTooLarge(
                    f"The artifact exceeds the maximum upload size of {max_bytes} bytes."
                )
            digest.update(chunk)
            chunks.append(chunk)
    finally:
        await file.close()

    return UploadedArtifact(
        filename=file.filename or "digital-artifact",
        media_type=file.content_type or "application/octet-stream",
        size_bytes=size_bytes,
        digest=digest.hexdigest(),
        content=b"".join(chunks),
    )


def base64url_digest(digest: str) -> str:
    return base64.urlsafe_b64encode(bytes.fromhex(digest)).decode("ascii").rstrip("=")


def render_qr_png(payload: str) -> bytes:
    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    qr.add_data(payload)
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white")
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def blossom_blob_url(digest: str, server: str) -> str:
    return f"{server.rstrip('/')}/{digest}"


def blossom_auth_header(*, signer_nsec: str, digest: str) -> str:
    keys = Keys(priv_k=signer_nsec)
    event = Event(
        kind=BLOSSOM_AUTH_KIND,
        content="Authorize OpenQR artifact upload",
        pub_key=keys.public_key_hex(),
        tags=[
            ["t", "upload"],
            ["x", digest],
            ["expiration", str(int(time.time()) + BLOSSOM_AUTH_TTL_SECONDS)],
        ],
    )
    event.sign(keys.private_key_hex())
    encoded = base64.b64encode(
        json.dumps(event.data(), separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).decode("ascii")
    return f"Nostr {encoded}"


def blossom_exists(*, digest: str, server: str, timeout: float) -> bool:
    request = urllib.request.Request(blossom_blob_url(digest, server), method="HEAD")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return 200 <= response.status < 300
    except urllib.error.HTTPError as exc:
        if exc.code in {404, 405}:
            return False
        raise


def upload_to_blossom(
    artifact: UploadedArtifact,
    *,
    server: str,
    signer_nsec: str,
    timeout: float,
) -> dict[str, Any]:
    url = blossom_blob_url(artifact.digest, server)
    if blossom_exists(digest=artifact.digest, server=server, timeout=timeout):
        return {
            "stored": True,
            "already_present": True,
            "server": server,
            "url": url,
            "message": "The artifact was already available from the Blossom server.",
        }

    request = urllib.request.Request(
        f"{server.rstrip('/')}/upload",
        data=artifact.content,
        headers={
            "Authorization": blossom_auth_header(
                signer_nsec=signer_nsec,
                digest=artifact.digest,
            ),
            "Content-Type": artifact.media_type,
            "Content-Length": str(artifact.size_bytes),
            "X-SHA-256": artifact.digest,
            "X-Content-SHA256": artifact.digest,
            "X-Filename": quote(artifact.filename, safe="._-"),
        },
        method="PUT",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        response.read()
        if not 200 <= response.status < 300:
            raise RuntimeError(f"Blossom upload failed with HTTP {response.status}")

    if not blossom_exists(digest=artifact.digest, server=server, timeout=timeout):
        raise RuntimeError("Blossom accepted the upload but did not return the artifact by digest")

    return {
        "stored": True,
        "already_present": False,
        "server": server,
        "url": url,
        "message": "The artifact was stored on the Blossom server.",
    }


async def maybe_upload_to_blossom(
    artifact: UploadedArtifact,
    *,
    requested: bool,
    server: str,
    signer_nsec: str | None,
    timeout: float,
) -> dict[str, Any] | None:
    if not requested:
        return None
    if not signer_nsec:
        return {
            "stored": False,
            "server": server,
            "url": None,
            "message": "Blossom storage is not configured for this OpenQR deployment.",
        }
    try:
        return await asyncio.to_thread(
            upload_to_blossom,
            artifact,
            server=server,
            signer_nsec=signer_nsec,
            timeout=timeout,
        )
    except Exception as exc:
        return {
            "stored": False,
            "server": server,
            "url": None,
            "message": f"Blossom storage failed: {exc}",
        }
