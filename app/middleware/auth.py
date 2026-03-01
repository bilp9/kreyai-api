from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware

from app.models.user import get_user_by_api_key


class APIKeyAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):

        # ----------------------------------------
        # ✅ Allow CORS preflight
        # ----------------------------------------
        if request.method == "OPTIONS":
            return await call_next(request)

        path = request.url.path

        # ----------------------------------------
        # ✅ PUBLIC ROUTES (NO API KEY REQUIRED)
        # ----------------------------------------
        if (
            path == "/"                              # Allow base URL
            or path.startswith("/health")
            or path.startswith("/docs")
            or path.startswith("/openapi")
            or path.startswith("/api")               # Allow ALL public SaaS API
        ):
            return await call_next(request)

        # ----------------------------------------
        # 🔐 EVERYTHING ELSE REQUIRES API KEY
        # ----------------------------------------
        api_key = request.headers.get("X-API-Key")

        if not api_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing API key",
            )

        user = get_user_by_api_key(api_key)

        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API key",
            )

        # Attach user to request state
        request.state.user = user

        return await call_next(request)