from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import unquote, urlparse

from stroma import Event, Keys, RelayPool

ANCHOR_KIND = 1415
HEX_DIGEST = re.compile(r"^[0-9a-f]{64}$")
BASE64URL_DIGEST = re.compile(r"^[A-Za-z0-9_-]{43}$")


class InvalidResolutionReference(ValueError):
    pass


class EvidenceRetrievalError(RuntimeError):
    pass


@dataclass(frozen=True)
class AnchorEvidence:
    event_id: str
    publisher_hex: str
    publisher_npub: str
    created_at: str
    kind: int
    content: str
    tags: list[list[str]]
    structure_valid: bool
    signature_valid: bool
    event_id_valid: bool

    @property
    def verified(self) -> bool:
        return self.structure_valid and self.signature_valid and self.event_id_valid

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "verified": self.verified}


@dataclass(frozen=True)
class ResolutionResult:
    digest: str
    supplied_encoding: str
    relays: list[str]
    retrieved_at: str
    anchors: list[AnchorEvidence]

    @property
    def status(self) -> str:
        if not self.anchors:
            return "not_found"
        if any(anchor.verified for anchor in self.anchors):
            return "evidence_found"
        return "unverified_evidence_found"

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile": "openetr:qr-resolver:https:1.0",
            "status": self.status,
            "digest": self.digest,
            "supplied_encoding": self.supplied_encoding,
            "relays": self.relays,
            "retrieved_at": self.retrieved_at,
            "anchor_count": len(self.anchors),
            "anchors": [anchor.to_dict() for anchor in self.anchors],
            "advisory": (
                "Retrieved evidence is not, by itself, proof of recognition, "
                "authority, or legal effect."
            ),
        }


def extract_resolution_target(value: str) -> tuple[str | None, str]:
    candidate = value.strip()
    if not candidate:
        raise InvalidResolutionReference("Enter an OpenETR digest or resolver URL.")

    campaign_id = None
    parsed = urlparse(candidate)
    if parsed.scheme or parsed.netloc:
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise InvalidResolutionReference("Resolver URLs must use HTTP or HTTPS.")
        if parsed.query or parsed.fragment:
            raise InvalidResolutionReference(
                "Standard OpenETR resolver URLs cannot contain a query or fragment."
            )
        segments = [unquote(segment) for segment in parsed.path.split("/") if segment]
        if len(segments) != 2:
            raise InvalidResolutionReference(
                "Resolver URLs must use /{campaign-id}/{resolution-reference}."
            )
        campaign_id = segments[-2]
        candidate = segments[-1]

    return campaign_id, candidate


def extract_resolution_reference(value: str) -> str:
    return extract_resolution_target(value)[1]


def normalize_lookup(
    value: str,
    *,
    default_campaign_id: str = "etr",
) -> tuple[str, str, str]:
    campaign_id, reference = extract_resolution_target(value)
    digest, encoding = normalize_digest(reference)
    return campaign_id or default_campaign_id, digest, encoding


def normalize_digest(value: str) -> tuple[str, str]:
    candidate = extract_resolution_reference(value)
    if HEX_DIGEST.fullmatch(candidate):
        return candidate, "hex"

    if not BASE64URL_DIGEST.fullmatch(candidate):
        raise InvalidResolutionReference(
            "The artifact digest must be 64 lowercase hexadecimal characters "
            "or 43 unpadded Base64URL characters."
        )

    try:
        digest_bytes = base64.b64decode(
            f"{candidate}=", altchars=b"-_", validate=True
        )
    except (ValueError, binascii.Error) as exc:
        raise InvalidResolutionReference(
            "The artifact digest is not valid unpadded Base64URL."
        ) from exc

    canonical = base64.urlsafe_b64encode(digest_bytes).decode("ascii").rstrip("=")
    if len(digest_bytes) != 32 or canonical != candidate:
        raise InvalidResolutionReference(
            "The artifact digest is not a canonical 32-byte Base64URL value."
        )
    return digest_bytes.hex(), "base64url"


def event_id_is_valid(event: Event) -> bool:
    try:
        data = event.data()
        serialized = json.dumps(
            [0, data["pubkey"], data["created_at"], data["kind"], data["tags"], data["content"]],
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest() == data["id"]
    except (KeyError, TypeError, ValueError):
        return False


def signature_is_valid(event: Event) -> bool:
    try:
        return bool(event.is_valid())
    except Exception:
        return False


def event_timestamp(event: Event) -> str:
    value = event.created_at
    if isinstance(value, datetime):
        timestamp = value
    else:
        timestamp = datetime.fromtimestamp(float(value), tz=timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def event_to_evidence(event: Event, digest: str) -> AnchorEvidence:
    data = event.data()
    o_values = event.tags.get_tags_value("o")
    return AnchorEvidence(
        event_id=event.id,
        publisher_hex=event.pub_key,
        publisher_npub=Keys.hex_to_bech32(event.pub_key),
        created_at=event_timestamp(event),
        kind=event.kind,
        content=event.content,
        tags=[list(tag) for tag in data["tags"]],
        structure_valid=event.kind == ANCHOR_KIND and digest in o_values,
        signature_valid=signature_is_valid(event),
        event_id_valid=event_id_is_valid(event),
    )


async def resolve_anchor_evidence(
    reference: str,
    *,
    relays: list[str],
    timeout: int = 10,
    limit: int = 20,
) -> ResolutionResult:
    digest, supplied_encoding = normalize_digest(reference)
    query_filter = {"kinds": [ANCHOR_KIND], "#o": [digest], "limit": limit}

    try:
        events = await RelayPool(relays, timeout=timeout).query(query_filter)
    except Exception as exc:
        raise EvidenceRetrievalError(
            "The configured relay scope could not be queried. Try again shortly."
        ) from exc

    unique_events = {event.id: event for event in events}
    ordered = sorted(
        unique_events.values(), key=lambda event: (int(event.created_at), event.id)
    )
    return ResolutionResult(
        digest=digest,
        supplied_encoding=supplied_encoding,
        relays=relays,
        retrieved_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        anchors=[event_to_evidence(event, digest) for event in ordered],
    )
