# app/middleware/rate_limit.py
# =====================================
# RATE LIMIT + QUOTA MIDDLEWARE
# API v1 — CLOUD RUN SAFE
# =====================================

from datetime import datetime, timedelta, timezone
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.services.quota import (
    get_quota,
    check_and_consume_quota,
)

# -------------------------------------
# Header helper
# -------------------------------------
def apply_quota_headers(response: Response, user) -> None:
    q = get_quota(user)

    response.headers["X-RateLimit-Limit"] = str(q.limit_seconds)
    response.headers["X-RateLimit-Remaining"] = str(q.remaining)

    reset_at = datetime.now(tz=timezone.utc) + timedelta(days=1)
    response.headers["X-RateLimit-Reset"] = reset_at.isoformat()


# -------------------------------------
# Enforcement middleware
# -------------------------------------
class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, rpm: int = 120):
        super().__init__(app)
        self.rpm = rpm

    async def dispatch(self, request: Request, call_next):
        if not request.url.path.startswith("/api"):
            return await call_next(request)

        user = getattr(request.state, "user", None)
        if user:
            check_and_consume_quota(user)

        response: Response = await call_next(request)

        if user:
            apply_quota_headers(response, user)

        return response


# -------------------------------------
# Header-only middleware (safe ordering)
# -------------------------------------
class RateLimitHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)

        user = getattr(request.state, "user", None)
        if user:
            apply_quota_headers(response, user)

        return response
