"""OpenQR's bounded GS1 Digital Link profile, not a full GS1 resolver."""

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, quote, urlencode, urlsplit

from app.resolver import normalize_digest
from app.registration import base64url_digest

TEST_GTIN = "09520123456788"
XCHAR = re.compile(r"^[A-Za-z0-9!\"%&'()*+,\-./:;<=>?_]{1,20}$")


@dataclass(frozen=True)
class GS1Data:
    gtin: str
    lot: str = ""
    serial: str = ""

    @classmethod
    def validate(cls, gtin, lot="", serial=""):
        gtin, lot, serial = gtin.strip(), lot.strip(), serial.strip()
        if not re.fullmatch(r"[0-9]{8}|[0-9]{12,14}", gtin):
            raise ValueError("GTIN must contain 8, 12, 13, or 14 digits.")
        gtin = gtin.zfill(14)
        total = sum(int(value) * (3 if index % 2 == 0 else 1)
                    for index, value in enumerate(reversed(gtin[:-1])))
        if (10 - total % 10) % 10 != int(gtin[-1]):
            raise ValueError("GTIN check digit is invalid.")
        for name, value in [("Batch/lot", lot), ("Serial number", serial)]:
            if value and not XCHAR.fullmatch(value):
                raise ValueError(f"{name} must use 1-20 GS1 characters (no spaces).")
            if value in {".", ".."} or "/" in value:
                raise ValueError(f"{name} cannot contain slash or be a dot path segment in OpenQR.")
        return cls(gtin, lot, serial)

    @property
    def path(self):
        path = f"/01/{self.gtin}"
        for ai, value in [("10", self.lot), ("21", self.serial)]:
            if value:
                path += f"/{ai}/{quote(value, safe='')}"
        return path

    @property
    def tags(self):
        return [[name, value] for name, value in [
            ("gs1_gtin", self.gtin), ("gs1_lot", self.lot), ("gs1_serial", self.serial),
        ] if value]

    def url(self, base, digest):
        parsed = urlsplit(base)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.query or parsed.fragment or parsed.username:
            raise ValueError("GS1 links require an HTTP(S) public base URL without query, fragment, or credentials.")
        return base.rstrip("/") + self.path + "?" + urlencode({"d": base64url_digest(digest)})

    def matches(self, anchor, digest):
        if not anchor.verified or ["action", "issue"] not in anchor.tags:
            return False
        expected = {"o": digest, "gs1_gtin": self.gtin,
                    "gs1_lot": self.lot, "gs1_serial": self.serial}
        return all([tag[1] for tag in anchor.tags if len(tag) >= 2 and tag[0] == key]
                   == ([value] if value else []) for key, value in expected.items())

    @classmethod
    def from_anchor(cls, anchor, digest):
        values = {}
        for tag in anchor.tags:
            if tag and tag[0] in {"gs1_gtin", "gs1_lot", "gs1_serial"}:
                if len(tag) != 2 or tag[0] in values:
                    return None
                values[tag[0]] = tag[1]
        try:
            data = cls.validate(values.get("gs1_gtin", ""),
                                values.get("gs1_lot", ""), values.get("gs1_serial", ""))
        except (ValueError, TypeError, AttributeError):
            return None
        return data if data.matches(anchor, digest) else None


def gs1_from_anchors(anchors, digest):
    candidates = {data for anchor in anchors
                  if (data := GS1Data.from_anchor(anchor, digest)) is not None}
    # Do not silently choose between conflicting signed product associations.
    return next(iter(candidates)) if len(candidates) == 1 else None


def parse_link(path, query):
    parts = path.strip("/").split("/")
    if len(parts) not in {2, 4, 6} or parts[0] != "01":
        raise ValueError("Use /01/{GTIN}, optionally followed by /10/{lot} and /21/{serial}.")
    pairs = list(zip(parts[2::2], parts[3::2]))
    if any(not value for _, value in pairs):
        raise ValueError("GS1 qualifiers cannot be empty.")
    if [key for key, _ in pairs] not in [[], ["10"], ["21"], ["10", "21"]]:
        raise ValueError("Unsupported or out-of-order GS1 qualifiers.")
    values = dict(pairs)
    if len(parts[1]) != 14:
        raise ValueError("Digital Link GTIN must have 14 digits.")
    data = GS1Data.validate(parts[1], values.get("10", ""), values.get("21", ""))
    params = parse_qs(query, keep_blank_values=True)
    if set(params) not in ({"d"}, {"digest"}):
        raise ValueError("Use exactly one d or digest parameter and no other query parameters.")
    references = next(iter(params.values()))
    if len(references) != 1:
        raise ValueError("Use exactly one d or digest parameter; repeated values are not allowed.")
    reference = references[0]
    if not re.fullmatch(r"[0-9a-f]{64}|[A-Za-z0-9_-]{43}", reference):
        raise ValueError("Invalid artifact digest.")
    digest, _ = normalize_digest(reference)
    return data, digest
