from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.auth.auth import authenticate_api_key, extract_api_key


def _is_public_path(path: str) -> bool:
    return (
        path == "/"
        or path.startswith("/health")
        or path.startswith("/docs")
        or path.startswith("/openapi")
        or path.startswith("/api")
    )


class APIKeyAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):

        # ----------------------------------------
        # ✅ Allow CORS preflight
        # ----------------------------------------
        if request.method == "OPTIONS":
            return await call_next(request)

        path = request.url.path

        if _is_public_path(path):
            return await call_next(request)

        # ----------------------------------------
        # 🔐 EVERYTHING ELSE REQUIRES API KEY
        # ----------------------------------------
        try:
            user = authenticate_api_key(
                extract_api_key(
                    authorization=request.headers.get("Authorization"),
                    x_api_key=request.headers.get("X-API-Key"),
                )
            )
        except HTTPException as exc:
            return JSONResponse(
                status_code=exc.status_code,
                content={"detail": exc.detail},
            )

        # Attach user to request state
        request.state.user = user

        return await call_next(request)
