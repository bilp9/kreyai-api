# app/auth/auth.py
# =====================================
# AUTH MIDDLEWARE
# API key → User resolution
# =====================================

from __future__ import annotations

from fastapi import Header, HTTPException, status
from typing import Optional

from app.models.user import User, get_user_by_api_key


def _normalize_header_value(value: Optional[str]) -> Optional[str]:
    if not isinstance(value, str):
        return None

    normalized = value.strip()
    return normalized or None


def extract_api_key(
    authorization: Optional[str] = None,
    x_api_key: Optional[str] = None,
) -> str:
    authorization = _normalize_header_value(authorization)
    x_api_key = _normalize_header_value(x_api_key)

    if authorization:
        if not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid Authorization header format",
            )

        api_key = authorization.removeprefix("Bearer ").strip()
        if not api_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Empty API key",
            )
        return api_key

    if x_api_key:
        return x_api_key

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Missing API key",
    )


def authenticate_api_key(api_key: str) -> User:
    normalized_api_key = _normalize_header_value(api_key)
    if not normalized_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Empty API key",
        )

    user = get_user_by_api_key(normalized_api_key)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )

    if not user.active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is disabled",
        )

    return user


# -------------------------------------------------
# Dependency: get current user from API key
# -------------------------------------------------
def get_current_user(
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> User:
    """
    Resolve API key → User.

    Expected header:
        Authorization: Bearer sk_xxx

    This function is:
    - synchronous
    - deterministic
    - side-effect free
    """

    return authenticate_api_key(
        extract_api_key(
            authorization=authorization,
            x_api_key=x_api_key,
        )
    )
