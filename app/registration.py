from __future__ import annotations

import asyncio
import base64
import hashlib
import io
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

import qrcode
from fastapi import UploadFile
from stroma import BlossomPool, Event, Keys, RelayPool


async def publish_anchor(artifact: UploadedArtifact, *, signer_nsec: str, relays: list[str], timeout: float, blossom_servers: list[str] = (), gs1=None) -> dict:
    keys = Keys(priv_k=signer_nsec)
    tags = [
        ["o", artifact.digest], ["action", "issue"], ["name", artifact.filename],
        ["size_bytes", str(artifact.size_bytes)],
        ["digest_generated_at", datetime.now(timezone.utc).isoformat()],
    ]
    if gs1:
        tags.extend(gs1.tags)
    if blossom_servers:
        tags.extend([["blossom", server] for server in BlossomPool(blossom_servers).servers])
    event = Event(kind=1415, content=f"Registered Digital Artifact {artifact.filename}", tags=tags)
    event.sign(keys)
    result = {"event_id": event.id, "publisher": keys.public_key_bech32(),
              "target_relays": list(dict.fromkeys(relays)), "relays": []}
    try:
        acknowledgements = await asyncio.wait_for(
            RelayPool(relays, timeout=timeout).publish(event), timeout=timeout + 1,
        )
    except Exception:
        return {**result, "published": False,
                "message": "Publication was not confirmed. A relay may still have received the event; check the resolver before retrying."}
    if not any(ack.accepted for ack in acknowledgements):
        return {**result, "published": False,
                "message": "No relay acceptance was confirmed for the Anchor Record."}
    return {**result, "published": True,
            "message": "Anchor Record accepted by a relay.",
            "relays": [ack.relay for ack in acknowledgements if ack.accepted]}


async def fetch_artifact(digest: str, *, servers: list[str], timeout: float,
                         max_bytes: int, operation_timeout: float = 60) -> bytes:
    result = await BlossomPool(
        servers, timeout=timeout, max_bytes=max_bytes,
        operation_timeout=operation_timeout, max_servers=96,
    ).retrieve(digest)
    return result.content


async def retrieve_artifact(digest: str, **options) -> dict:
    try:
        content = await fetch_artifact(digest, **options)
    except Exception:
        return {"verified": False, "message": "The artifact could not be retrieved and verified from the Blossom servers."}
    return {"verified": True, "size_bytes": len(content), "media_type": preview_type(content),
            "message": "Artifact retrieved and SHA-256 verified."}


def preview_type(content: bytes) -> str | None:
    # Recognize MP4's file-type box, not just the untrusted filename/MIME hint.
    if len(content) >= 16 and content[4:8] == b"ftyp":
        box_size = int.from_bytes(content[:4], "big")
        if (16 <= box_size <= len(content) and box_size % 4 == 0
                and content[8:12] in {b"isom", b"iso2", b"iso3", b"iso4", b"iso5", b"iso6",
                                      b"mp41", b"mp42", b"avc1", b"M4V ", b"dash"}):
            return "video/mp4"
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

READ_CHUNK_BYTES = 64 * 1024


class ArtifactUploadTooLarge(ValueError):
    pass


async def hash_artifact(file: UploadFile, *, max_bytes: int) -> str:
    """Hash an uploaded original without retaining another in-memory copy."""
    digest = hashlib.sha256()
    size = 0
    try:
        while chunk := await file.read(READ_CHUNK_BYTES):
            size += len(chunk)
            if size > max_bytes:
                raise ArtifactUploadTooLarge(
                    f"The artifact exceeds the maximum upload size of {max_bytes} bytes."
                )
            digest.update(chunk)
    finally:
        await file.close()
    return digest.hexdigest()


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


async def maybe_upload_to_blossom(
    artifact: UploadedArtifact, *, requested: bool, servers: list[str],
    signer_nsec: str | None, timeout: float, max_bytes: int,
    require: str = "any", operation_timeout: float = 60,
) -> dict[str, Any] | None:
    if not requested:
        return None
    try:
        if not signer_nsec:
            raise ValueError("No storage signer is configured.")
        if hashlib.sha256(artifact.content).hexdigest() != artifact.digest:
            raise ValueError("Artifact digest mismatch.")
        result = await BlossomPool(
            servers, timeout=timeout, operation_timeout=operation_timeout, max_bytes=max_bytes,
        ).store(artifact.content, signer=Keys(priv_k=signer_nsec),
                require=require, media_type=artifact.media_type)
    except Exception:
        return {"stored": False, "confirmed_servers": [], "outcomes": [], "urls": [],
                "message": "Storage could not be confirmed. No anchor was published; copies may already exist."}
    return {
        "stored": result.ok, "confirmed_servers": list(result.confirmed_servers),
        "required": result.required, "require": result.require,
        "outcomes": [asdict(item) for item in result.outcomes],
        "urls": [f"{server}/{artifact.digest}" for server in result.confirmed_servers],
        "message": f"Verified storage on {len(result.confirmed_servers)} server(s); {result.required} required ({result.require})."
                   + ("" if result.ok else " No anchor was published; some copies may already exist."),
    }
