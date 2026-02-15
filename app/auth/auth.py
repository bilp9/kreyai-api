# app/auth/auth.py
# =====================================
# AUTH MIDDLEWARE — API v1 (STABLE)
# API key → User resolution
# =====================================

from __future__ import annotations

from fastapi import Depends, Header, HTTPException, status
from typing import Optional

from app.models.user import User, get_user_by_api_key


# -------------------------------------------------
# Dependency: get current user from API key
# -------------------------------------------------
def get_current_user(
    authorization: Optional[str] = Header(None),
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

    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
        )

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

    user = get_user_by_api_key(api_key)

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
