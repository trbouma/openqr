"""Encrypted, expiring browser sessions and form CSRF protection."""

import base64
import hashlib
import json
import secrets

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException
from starlette.datastructures import MutableHeaders
from starlette.requests import HTTPConnection


class EncryptedSessionMiddleware:
    def __init__(self, app, secret: str, secure: bool, max_age: int = 28800):
        self.app, self.secure, self.max_age = app, secure, max_age
        self.cipher = Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest()))
        self.cookie = "openqr_session"

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        token = HTTPConnection(scope).cookies.get(self.cookie)
        session = {}
        if token:
            try:
                session = json.loads(self.cipher.decrypt(token.encode(), ttl=self.max_age))
                if not isinstance(session, dict):
                    session = {}
            except (InvalidToken, ValueError, UnicodeError):
                session = {}
        initial = dict(session)
        scope["session"] = session

        async def send_session(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                if scope["path"] in {"/register", "/login", "/logout", "/profiles/use"}:
                    headers["Cache-Control"] = "no-store"
                    headers["Referrer-Policy"] = "same-origin"
                if session != initial:
                    value = self.cipher.encrypt(json.dumps(session).encode()).decode() if session else ""
                    age = self.max_age if session else 0
                    headers.append("Set-Cookie", f"{self.cookie}={value}; Path=/; Max-Age={age}; HttpOnly; SameSite=Lax" + ("; Secure" if self.secure else ""))
                    headers.add_vary_header("Cookie")
            await send(message)

        await self.app(scope, receive, send_session)


def csrf_token(request):
    if "csrf" not in request.session:
        request.session["csrf"] = secrets.token_urlsafe(32)
    return request.session["csrf"]


def check_csrf(request, supplied: str):
    expected = request.session.get("csrf")
    if not expected or not secrets.compare_digest(expected, supplied):
        raise HTTPException(403, "The form session expired. Reload the page and try again.")
