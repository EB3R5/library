"""Single-user session login (ADR 0003). One credential row lives in the `users` table:
    username, pw_hash (bcrypt), totp_secret
Bootstrap it with `./run.sh create-user`. Login (app.py) verifies the password then a TOTP
code and stamps request.session[SESSION_USER_KEY]. The auth gate (app.py) blocks every
request without a session, except EXEMPT_PREFIXES and any request carrying the trusted
API_TOKEN bearer header (the agent API, ADR 0005)."""

import hmac

import bcrypt
import pyotp
from fastapi import Request

from config import API_TOKEN  # noqa: F401 — module-level so tests can monkeypatch auth.API_TOKEN

SESSION_USER_KEY = "user"

# Paths reachable without a session. Prefix match. /healthz stays open for probes;
# /login + /logout must be reachable to log in and out.
EXEMPT_PREFIXES = ("/login", "/logout", "/healthz")


def _pw_bytes(raw: str) -> bytes:
    # bcrypt rejects secrets > 72 bytes; truncate (standard bcrypt behaviour).
    return raw.encode("utf-8")[:72]


def hash_password(raw: str) -> str:
    return bcrypt.hashpw(_pw_bytes(raw), bcrypt.gensalt()).decode("ascii")


def verify_password(raw: str, hashed: str) -> bool:
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(_pw_bytes(raw), hashed.encode("ascii"))
    except ValueError:
        return False


def verify_totp(secret: str, code: str) -> bool:
    # valid_window=1 tolerates ±30s clock skew.
    if not secret:
        return False
    return pyotp.TOTP(secret).verify((code or "").strip(), valid_window=1)


def is_exempt(path: str) -> bool:
    return any(path == p or path.startswith(p + "/") for p in EXEMPT_PREFIXES)


def has_valid_api_token(auth_header: str | None) -> bool:
    """True if the Authorization header carries the configured static bearer token.
    Disabled (always False) while API_TOKEN is unset."""
    if not API_TOKEN or not auth_header:
        return False
    scheme, _, token = auth_header.partition(" ")
    if scheme.lower() != "bearer":
        return False
    return hmac.compare_digest(token.strip(), API_TOKEN)


class TokenRequired(Exception):
    """Raised by require_token; app.py turns it into a 401 {ok: false, error} JSON."""


def require_token(request: Request) -> None:
    """FastAPI dependency for the agent API (ADR 0005): the bearer token, not a session."""
    if not API_TOKEN:
        raise TokenRequired("agent API disabled: set API_TOKEN")
    if not has_valid_api_token(request.headers.get("authorization")):
        raise TokenRequired("Not authenticated")
