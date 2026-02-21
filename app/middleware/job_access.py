from __future__ import annotations

import os
from typing import Optional

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware

from app.security.job_tokens import JobTokenConfig, verify_job_token, TokenExpired, TokenInvalid


def _cfg() -> JobTokenConfig:
    secret = os.getenv("JOB_TOKEN_SECRET", "")
    ttl = int(os.getenv("JOB_TOKEN_TTL_SECONDS", str(7 * 24 * 3600)))
    return JobTokenConfig(secret=secret, ttl_seconds=ttl)


class JobAccessMiddleware(BaseHTTPMiddleware):
    """
    Requires token for:
      - GET /api/jobs/{job_id}  (status is OK public if you want; see below)
      - GET /api/jobs/{job_id}/(txt|docx|srt|vtt)
      - GET /api/jobs/{job_id}/page (if you add a page endpoint)
    Token can be passed:
      - query param: ?t=...
      - header: X-Job-Token: ...
    """

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Only protect these routes (keep /api/verify and upload untouched)
        protected_prefix = "/api/jobs/"
        if not path.startswith(protected_prefix):
            return await call_next(request)

        # If it’s exactly /api/jobs/{job_id} (status), you can decide:
        # - allow status public (no token) OR
        # - require token
        # For "Request Access Only" launch, I recommend requiring token for downloads only.
        # We'll require token for download endpoints; status can be public.
        parts = path.split("/")
        # /api/jobs/{job_id}/...
        if len(parts) < 4:
            return await call_next(request)

        job_id = parts[3]

        is_download = any(path.endswith(suf) for suf in ("/txt", "/docx", "/srt", "/vtt"))
        if not is_download:
            return await call_next(request)

        token = request.query_params.get("t") or request.headers.get("X-Job-Token")
        if not token:
            raise HTTPException(status_code=401, detail="Missing access token.")

        try:
            verify_job_token(_cfg(), token=token, job_id=job_id)
        except TokenExpired:
            raise HTTPException(status_code=410, detail="Access expired.")
        except TokenInvalid:
            raise HTTPException(status_code=401, detail="Invalid access token.")

        return await call_next(request)