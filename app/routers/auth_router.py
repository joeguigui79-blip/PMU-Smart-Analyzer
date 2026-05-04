"""Auth router — /api/login and /api/logout endpoints."""
from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.auth import verify_password, revoke_token, get_token_from_request

router = APIRouter(prefix="/api", tags=["auth"])


class LoginRequest(BaseModel):
    password: str


class LoginResponse(BaseModel):
    token: str


@router.post("/login", response_model=LoginResponse)
async def login(payload: LoginRequest):
    """Verify password and return a bearer token."""
    token = verify_password(payload.password)
    return LoginResponse(token=token)


@router.post("/logout")
async def logout(request: Request):
    """Invalidate the current token."""
    token = get_token_from_request(request)
    if token:
        revoke_token(token)
    return {"ok": True}
