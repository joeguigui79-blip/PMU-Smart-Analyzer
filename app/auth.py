"""
Auth module — password-based single-token protection.
Token is a UUID stored in memory. On restart tokens are cleared
(forces re-login) which is acceptable for a personal tool.
"""
import os
import uuid
from fastapi import HTTPException, Request, status

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
APP_PASSWORD: str = os.environ.get("APP_PASSWORD", "pmu2024")

# In-memory token store  { token_str: True }
_valid_tokens: set[str] = set()


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def verify_password(password: str) -> str:
    """Check password and return a new token if correct, else raise 401."""
    if password != APP_PASSWORD:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Mot de passe incorrect",
        )
    token = str(uuid.uuid4())
    _valid_tokens.add(token)
    return token


def validate_token(token: str | None) -> None:
    """Raise 401 if token is absent or unknown."""
    if not token or token not in _valid_tokens:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Non authentifié",
        )


def revoke_token(token: str) -> None:
    """Remove a token (logout)."""
    _valid_tokens.discard(token)


def get_token_from_request(request: Request) -> str | None:
    """Extract bearer token from Authorization header."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return None
