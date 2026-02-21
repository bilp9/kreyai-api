from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware

from app.models.user import get_user_by_api_key


class APIKeyAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):

        # ✅ Allow CORS preflight requests
        if request.method == "OPTIONS":
            return await call_next(request)

        path = request.url.path

        # ✅ Public endpoints (no API key required)
        if (
            path in ("/docs", "/openapi.yaml", "/health")
            or path.startswith("/api/jobs/")     # job access + downloads
            or path == "/api/"                   # create job
            or path == "/api/verify"             # verify job
        ):
            return await call_next(request)

        # 🔐 Everything else requires API key
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

        request.state.user = user
        return await call_next(request)