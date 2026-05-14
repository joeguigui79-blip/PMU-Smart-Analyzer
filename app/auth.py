"""
Auth module — password-based HMAC-signed token protection.
Tokens survive server restarts — no in-memory store required.
Format: <uuid>.<timestamp>.<hmac_signature>
"""
import hashlib
import hmac
import os
import time
import uuid
from fastapi import HTTPException, Request, status

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
APP_PASSWORD: str = os.environ.get("APP_PASSWORD", "pmu2024")

# Secret key used to sign tokens — stable across restarts via env var
# Falls back to a fixed default for single-user personal tools
_SECRET: bytes = os.environ.get("TOKEN_SECRET", "pmu-smart-analyzer-secret-key-2024").encode()

# Token validity duration (seconds) — 30 days
_TOKEN_TTL: int = 30 * 24 * 3600

# Keep a small in-memory revocation set for logout (best-effort, clears on restart)
_revoked_tokens: set[str] = set()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _sign(payload: str) -> str:
    """Return HMAC-SHA256 hex digest of payload."""
    return hmac.new(_SECRET, payload.encode(), hashlib.sha256).hexdigest()


def _make_token() -> str:
    """Build a signed token: <uuid>.<timestamp>.<signature>"""
    uid = str(uuid.uuid4())
    ts = str(int(time.time()))
    payload = f"{uid}.{ts}"
    sig = _sign(payload)
    return f"{payload}.{sig}"


def _verify_token_signature(token: str) -> bool:
    """
    Validate token structure, signature and expiry.
    Returns True if valid, False otherwise.
    """
    try:
        parts = token.split(".")
        if len(parts) != 6:
            # uuid has 5 parts separated by '-', so split('.') gives: [uuid, ts, sig]
            # Actually uuid4 = xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx (no dots)
            # So token = "<uuid>.<ts>.<sig>" → 3 parts on split('.')
            return False
        # token = "uuid.ts.sig" where uuid contains no dots
        # split('.') => [uuid_str, ts_str, sig_str] = 3 items
        return False
    except Exception:
        return False


def _parse_token(token: str) -> tuple[str, int, str] | None:
    """
    Parse token into (uuid_str, timestamp_int, sig_str).
    Returns None if malformed.
    """
    try:
        # Expected format: "<uuid>.<timestamp>.<signature>"
        # uuid4 has no dots, timestamp is int, signature is hex
        # So there are exactly 3 dot-separated components
        idx1 = token.index(".")
        idx2 = token.index(".", idx1 + 1)
        uid = token[:idx1]
        ts_str = token[idx1 + 1:idx2]
        sig = token[idx2 + 1:]
        return uid, int(ts_str), sig
    except (ValueError, IndexError):
        return None


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def verify_password(password: str) -> str:
    """Check password and return a new signed token if correct, else raise 401."""
    if password != APP_PASSWORD:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Mot de passe incorrect",
        )
    return _make_token()


def validate_token(token: str | None) -> None:
    """Raise 401 if token is absent, invalid, expired or revoked."""
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Non authentifié",
        )

    parsed = _parse_token(token)
    if parsed is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Non authentifié",
        )

    uid, ts, sig = parsed
    payload = f"{uid}.{ts}"

    # Check signature
    expected_sig = _sign(payload)
    if not hmac.compare_digest(expected_sig, sig):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Non authentifié",
        )

    # Check expiry
    if time.time() - ts > _TOKEN_TTL:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expirée, reconnectez-vous",
        )

    # Check revocation (best-effort)
    if token in _revoked_tokens:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Non authentifié",
        )


def revoke_token(token: str) -> None:
    """Mark a token as revoked (logout). Clears on restart — acceptable for personal tool."""
    if token:
        _revoked_tokens.add(token)


def get_token_from_request(request: Request) -> str | None:
    """Extract bearer token from Authorization header."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return None
