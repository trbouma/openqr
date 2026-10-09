from __future__ import annotations

import base64
import os
import re
import secrets
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from stroma import BlossomPool, storage_threshold

from app import identity
from app.session import EncryptedSessionMiddleware, check_csrf, csrf_token

from app.resolver import (
    EvidenceRetrievalError,
    InvalidResolutionReference,
    ResolutionResult,
    normalize_lookup,
    resolve_anchor_evidence,
)
from app.registration import (
    ArtifactUploadTooLarge,
    base64url_digest,
    maybe_upload_to_blossom,
    read_artifact,
    render_qr_png,
    publish_anchor,
    retrieve_artifact,
    fetch_artifact,
    preview_type,
)

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_RELAYS = [
    relay.strip()
    for relay in os.getenv("OPENQR_RELAYS", "wss://relay.openetr.org").split(",")
    if relay.strip()
]
QUERY_TIMEOUT = int(os.getenv("OPENQR_QUERY_TIMEOUT_SECONDS", "10"))
QUERY_LIMIT = int(os.getenv("OPENQR_QUERY_LIMIT", "20"))
GIT_COMMIT = os.getenv("OPENQR_GIT_COMMIT", "unknown")
PUBLIC_BASE_URL = os.getenv("OPENQR_PUBLIC_BASE_URL", "").rstrip("/")
MAX_UPLOAD_BYTES = int(os.getenv("OPENQR_MAX_UPLOAD_BYTES", str(25 * 1024 * 1024)))
BLOSSOM_SERVER = os.getenv(
    "OPENQR_BLOSSOM_SERVER", "https://blossom.getsafebox.app"
).rstrip("/")
BLOSSOM_NSEC = os.getenv("OPENQR_BLOSSOM_NSEC") or None
SIGNER_NSEC = os.getenv("OPENQR_SIGNER_NSEC") or BLOSSOM_NSEC
BLOSSOM_TIMEOUT = float(os.getenv("OPENQR_BLOSSOM_TIMEOUT_SECONDS", "20"))
BLOSSOM_OPERATION_TIMEOUT = float(os.getenv("OPENQR_BLOSSOM_OPERATION_TIMEOUT_SECONDS", "60"))
BLOSSOM_SERVERS = list(BlossomPool(re.split(r"[,\s]+", (os.getenv("OPENQR_BLOSSOM_SERVERS") or BLOSSOM_SERVER).strip())).servers)
BLOSSOM_QUERY_SERVERS = list(BlossomPool(re.split(r"[,\s]+", (os.getenv("OPENQR_BLOSSOM_QUERY_SERVERS") or ",".join(BLOSSOM_SERVERS)).strip())).servers)
BLOSSOM_REQUIRE = os.getenv("OPENQR_BLOSSOM_REQUIRE", "any")
storage_threshold(len(BLOSSOM_SERVERS), BLOSSOM_REQUIRE)
HOME_RELAYS = [value for value in re.split(r"[,\s]+", os.getenv("OPENQR_HOME_RELAYS", ",".join(DEFAULT_RELAYS)).strip()) if value]
REGISTRATION_MODE = os.getenv("OPENQR_REGISTRATION_MODE", "interactive")
if REGISTRATION_MODE not in {"interactive", "service"}:
    raise ValueError("OPENQR_REGISTRATION_MODE must be interactive or service")
SESSION_SECRET = os.getenv("OPENQR_SESSION_SECRET")
if not SESSION_SECRET:
    if os.getenv("OPENQR_REQUIRE_SESSION_SECRET", "false").lower() == "true":
        raise RuntimeError("OPENQR_SESSION_SECRET is required.")
    SESSION_SECRET = secrets.token_urlsafe(32)
SESSION_SECURE = os.getenv("OPENQR_SESSION_SECURE", str(PUBLIC_BASE_URL.startswith("https://"))).lower() == "true"
CAMPAIGN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")

app = FastAPI(
    title="OpenQR",
    description="Minimal resolver for the OpenETR QR Resolver Profile 1.0",
    version="0.1.0",
)
app.add_middleware(EncryptedSessionMiddleware, secret=SESSION_SECRET, secure=SESSION_SECURE)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


def template_context(request: Request, **values):
    return {
        "request": request,
        "relays": DEFAULT_RELAYS,
        "git_commit": GIT_COMMIT,
        "blossom_server": BLOSSOM_SERVER,
        "blossom_servers": BLOSSOM_SERVERS,
        "registration_mode": REGISTRATION_MODE,
        "signed_in": bool(request.session.get("root_nsec")),
        "acting_profile": request.session.get("profile"),
        "acting_npub": request.session.get("profile_npub"),
        "csrf_token": csrf_token(request) if request.url.path in {"/register", "/login", "/profiles/use"} else "",
        "max_upload_bytes": MAX_UPLOAD_BYTES,
        **values,
    }


async def registration_page(request: Request, *, status_code=200, **values):
    profiles, details = [], {}
    if request.session.get("root_nsec"):
        try:
            profiles = await identity.list_profiles(request.session["root_nsec"], HOME_RELAYS)
            if request.session.get("profile") in profiles:
                profile = await identity.acting_profile(request.session["root_nsec"], request.session["profile"], HOME_RELAYS)
                details = await identity.profile_details(profile)
                request.session["profile_npub"] = profile["npub"]
            elif request.session.get("profile"):
                request.session.pop("profile", None)
                request.session.pop("profile_npub", None)
        except Exception:
            values.setdefault("error_message", "Profile information could not be retrieved. Check the configured home relays.")
    return templates.TemplateResponse(request, "register.html", template_context(
        request, profiles=profiles, profile_details=details, **values,
    ), status_code=status_code)


def artifact_options(result: ResolutionResult | None = None) -> dict:
    hints = []
    for anchor in result.anchors if result else []:
        if [tag[1] for tag in anchor.tags if len(tag) >= 2 and tag[0] == "o"] != [result.digest]:
            continue
        for server in anchor.blossom_servers:
            if server not in hints and len(hints) < 32:
                hints.append(server)
    return dict(servers=[*hints, *BLOSSOM_QUERY_SERVERS, *BLOSSOM_SERVERS],
                timeout=BLOSSOM_TIMEOUT, operation_timeout=BLOSSOM_OPERATION_TIMEOUT,
                max_bytes=MAX_UPLOAD_BYTES)


@app.post("/login")
async def login(request: Request, nsec: str = Form(...), csrf: str = Form("")):
    check_csrf(request, csrf)
    if REGISTRATION_MODE != "interactive":
        raise HTTPException(403, "Interactive sign-in is disabled in service mode.")
    try:
        root = identity.normalize_root(nsec)
        await identity.list_profiles(root, HOME_RELAYS)
    except ValueError as exc:
        return await registration_page(request, error_message=str(exc), status_code=400)
    except Exception:
        return await registration_page(request, error_message="Unable to load this Control Desk from the configured home relays.", status_code=502)
    request.session.clear()
    request.session.update(root_nsec=root, csrf=secrets.token_urlsafe(32))
    return RedirectResponse("/register", status_code=303)


@app.post("/profiles/use")
async def use_profile(request: Request, profile: str = Form(...), csrf: str = Form("")):
    check_csrf(request, csrf)
    root = request.session.get("root_nsec")
    if not root or REGISTRATION_MODE != "interactive":
        raise HTTPException(401, "Sign in before selecting an Acting Profile.")
    try:
        selected = await identity.acting_profile(root, profile, HOME_RELAYS)
    except ValueError as exc:
        return await registration_page(request, error_message=str(exc), status_code=400)
    except Exception:
        return await registration_page(request, error_message="Unable to retrieve this profile.", status_code=502)
    request.session.update(profile=selected["name"], profile_npub=selected["npub"])
    return RedirectResponse("/register", status_code=303)


@app.post("/logout")
async def logout(request: Request, csrf: str = Form("")):
    check_csrf(request, csrf)
    request.session.clear()
    return RedirectResponse("/register", status_code=303)

def public_base_url(request: Request) -> str:
    return PUBLIC_BASE_URL or str(request.base_url).rstrip("/")


def resolver_url(request: Request, campaign_id: str, reference: str) -> str:
    return f"{public_base_url(request)}/{quote(campaign_id, safe='')}/{quote(reference, safe='')}"


def normalize_campaign_id(value: str | None) -> str:
    candidate = (value or "").strip() or "etr"
    if not CAMPAIGN_ID.fullmatch(candidate):
        raise ValueError(
            "Campaign ID must begin with a letter or digit and contain only letters, digits, hyphens, or underscores."
        )
    return candidate


async def perform_lookup(campaign_id: str, reference: str) -> ResolutionResult:
    # Reserved for campaign-specific resolution behavior.
    _ = campaign_id
    return await resolve_anchor_evidence(
        reference,
        relays=DEFAULT_RELAYS,
        timeout=QUERY_TIMEOUT,
        limit=QUERY_LIMIT,
    )


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(request, "index.html", template_context(request))


@app.get("/register", response_class=HTMLResponse)
async def register_form(request: Request):
    return await registration_page(request)


@app.post("/register", response_class=HTMLResponse)
async def register_artifact(
    request: Request,
    file: UploadFile = File(...),
    campaign_id: str = Form(""),
    store_on_blossom: str | None = Form(None),
    csrf: str = Form(""),
):
    check_csrf(request, csrf)
    if REGISTRATION_MODE == "interactive":
        if not request.session.get("root_nsec") or not request.session.get("profile"):
            await file.close()
            return await registration_page(request, error_message="Sign in and select an Acting Profile before registering.", status_code=401)
        try:
            selected = await identity.acting_profile(request.session["root_nsec"], request.session["profile"], HOME_RELAYS)
        except Exception:
            await file.close()
            return await registration_page(request, error_message="The Acting Profile could not be authorized. No artifact was published.", status_code=403)
        signer_nsec = selected["nsec"]
        upload_signer = signer_nsec
        publication_relays = [value for value in re.split(r"[,\s]+", selected["relays"]) if value]
    else:
        signer_nsec, upload_signer, publication_relays = SIGNER_NSEC, BLOSSOM_NSEC or SIGNER_NSEC, DEFAULT_RELAYS
    if not signer_nsec:
        await file.close()
        return await registration_page(
            request, error_message="Registration signing is not configured on this deployment.",
            campaign_id=campaign_id, status_code=503,
        )
    try:
        resolved_campaign_id = normalize_campaign_id(campaign_id)
        artifact = await read_artifact(file, max_bytes=MAX_UPLOAD_BYTES)
    except (ValueError, ArtifactUploadTooLarge) as exc:
        await file.close()
        return await registration_page(request, error_message=str(exc), campaign_id=campaign_id, status_code=400)

    encoded_digest = base64url_digest(artifact.digest)
    public_url = resolver_url(request, resolved_campaign_id, encoded_digest)
    blossom = await maybe_upload_to_blossom(
        artifact,
        requested=(store_on_blossom or "").lower() in {"1", "true", "yes", "on"},
        servers=BLOSSOM_SERVERS,
        signer_nsec=upload_signer,
        timeout=BLOSSOM_TIMEOUT,
        operation_timeout=BLOSSOM_OPERATION_TIMEOUT,
        max_bytes=MAX_UPLOAD_BYTES, require=BLOSSOM_REQUIRE,
    )
    if blossom and not blossom["stored"]:
        anchor = {"published": False, "message": "Requested storage was not confirmed; no Anchor Record was published."}
    else:
        anchor = await publish_anchor(
            artifact, signer_nsec=signer_nsec, relays=publication_relays, timeout=QUERY_TIMEOUT,
            blossom_servers=(blossom or {}).get("confirmed_servers", []),
        )
    return templates.TemplateResponse(
        request,
        "register_result.html",
        template_context(
            request,
            artifact=artifact,
            campaign_id=resolved_campaign_id,
            encoded_digest=encoded_digest,
            resolver_url=public_url,
            qr_image_url=(
                f"/qr/{quote(resolved_campaign_id, safe='')}/"
                f"{quote(encoded_digest, safe='')}"
            ),
            blossom=blossom,
            anchor=anchor,
        ),
        status_code=200 if anchor["published"] else 502,
    )


@app.get("/qr/{campaign_id}/{reference}")
async def qr_image(request: Request, campaign_id: str, reference: str):
    try:
        resolved_campaign_id = normalize_campaign_id(campaign_id)
        _, digest, _ = normalize_lookup(reference)
    except (InvalidResolutionReference, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    canonical_reference = base64url_digest(digest)
    image = render_qr_png(
        resolver_url(request, resolved_campaign_id, canonical_reference)
    )
    return Response(content=image, media_type="image/png")


@app.get("/resolve", include_in_schema=False)
async def resolve_input(reference: str = Query(..., min_length=1)):
    try:
        campaign_id, digest, supplied_encoding = normalize_lookup(reference)
    except InvalidResolutionReference as exc:
        return RedirectResponse(
            url=f"/?error={quote(str(exc))}&reference={quote(reference)}",
            status_code=303,
        )
    canonical = digest
    if supplied_encoding == "base64url":
        canonical = base64.urlsafe_b64encode(bytes.fromhex(digest)).decode("ascii").rstrip("=")
    return RedirectResponse(url=f"/{quote(campaign_id)}/{canonical}", status_code=303)


@app.get("/artifact/{campaign_id}/{reference}")
async def download_artifact(campaign_id: str, reference: str, preview: bool = False):
    try:
        _, digest, _ = normalize_lookup(reference)
    except InvalidResolutionReference as exc:
        raise HTTPException(400, str(exc)) from exc
    try:
        try:
            result = await perform_lookup(campaign_id, digest)
        except EvidenceRetrievalError:
            result = None
        content = await fetch_artifact(digest, **artifact_options(result))
    except ValueError as exc:
        raise HTTPException(502, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, "Artifact retrieval unavailable.") from exc
    media_type = preview_type(content) if preview else None
    if preview and not media_type:
        raise HTTPException(415, "No preview is available for this file type.")
    return Response(content, media_type=media_type or "application/octet-stream", headers={
        "Content-Disposition": f'{"inline" if preview else "attachment"}; filename="{digest}"',
        "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store",
    })


@app.get("/{campaign_id}/{reference}", response_class=HTMLResponse)
async def resolve_html(request: Request, campaign_id: str, reference: str):
    try:
        result = await perform_lookup(campaign_id, reference)
    except InvalidResolutionReference as exc:
        return templates.TemplateResponse(
            request,
            "error.html",
            template_context(request, title="Invalid QR reference", message=str(exc)),
            status_code=400,
        )
    except EvidenceRetrievalError as exc:
        return templates.TemplateResponse(
            request,
            "error.html",
            template_context(request, title="Relay query unavailable", message=str(exc)),
            status_code=502,
        )

    artifact_status = await retrieve_artifact(result.digest, **artifact_options(result))
    return templates.TemplateResponse(
        request,
        "result.html",
        template_context(request, result=result, campaign_id=campaign_id, artifact_status=artifact_status,
                         share_url=resolver_url(request, campaign_id, base64url_digest(result.digest))),
    )


@app.get("/api/{campaign_id}/{reference}")
async def resolve_json(campaign_id: str, reference: str):
    try:
        result = await perform_lookup(campaign_id, reference)
    except InvalidResolutionReference as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except EvidenceRetrievalError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    artifact_status = await retrieve_artifact(result.digest, **artifact_options(result))
    return {**result.to_dict(), "artifact": artifact_status}


@app.get("/health")
async def health():
    return {"status": "ok", "service": "openqr", "git_commit": GIT_COMMIT}
