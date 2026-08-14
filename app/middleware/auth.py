from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.auth.auth import authenticate_api_key, extract_api_key


PUBLIC_EXACT_PATHS = {
    "/",
    "/health",
    "/openapi.json",
    "/openapi.yaml",
    "/api/public-config",
    "/api/verify",
    "/api/billing/config",
    "/api/billing/balance",
    "/api/billing/checkout-session",
    "/api/stripe/webhook",
    "/api/atelier/config",
    "/api/atelier/checkout-session",
    "/api/atelier/activate",
    "/api/atelier/deactivate",
    "/api/dekk/config",
    "/api/dekk/checkout-session",
    "/api/dekk/download-event",
}


def _is_public_path(path: str) -> bool:
    """Return only routes that implement their own customer access controls."""
    return (
        path in PUBLIC_EXACT_PATHS
        or path.startswith("/docs")
        or path == "/api/"
        or path.startswith("/api/jobs/")
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
        # Everything not explicitly public requires an API key. Customer job
        # routes enforce their scoped job token inside the route handler.
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
