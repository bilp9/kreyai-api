# =====================================
# PUBLIC API
# =====================================

import os
import sys

from fastapi import FastAPI
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware
from app.config import build_openapi_yaml, get_public_api_version

# -------------------------------------------------
# Runtime guard
# -------------------------------------------------
if sys.version_info >= (3, 13):
    raise RuntimeError(
        "Python >=3.13 is not supported. Use Python 3.11 or 3.12."
    )

# -------------------------------------------------
# App (MUST be created early)
# -------------------------------------------------
app = FastAPI(
    title="KreyAI Transcription API",
    version=get_public_api_version(),
)

# =================================================
# ✅ CORS — MUST BE ADDED FIRST
# =================================================
# This ensures ALL responses (including 401/429/etc.)
# include proper CORS headers for the browser.

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://www.kreyai.com",
        "https://kreyai.com",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------------------------------
# Health check (Cloud Run required)
# -------------------------------------------------
@app.get("/health", include_in_schema=False)
def health():
    return {
        "status": "ok",
        "service": "kreyai-api",
        "version": get_public_api_version(),
    }

# -------------------------------------------------
# Custom Middleware
# -------------------------------------------------
from app.middleware.rate_limit import (
    RateLimitMiddleware,
    RateLimitHeadersMiddleware,
)
from app.middleware.auth import APIKeyAuthMiddleware
from app.middleware.job_access import JobAccessMiddleware

# Headers-only middleware
app.add_middleware(RateLimitHeadersMiddleware)

# Rate limiting
app.add_middleware(
    RateLimitMiddleware,
    rpm=120,
)

# API key auth
app.add_middleware(APIKeyAuthMiddleware)

# Job-level access control
app.add_middleware(JobAccessMiddleware)

# -------------------------------------------------
# Routes
# -------------------------------------------------
from app.routes import jobs, ops, upload

app.include_router(jobs.router)
app.include_router(ops.router)
app.include_router(upload.router)

# -------------------------------------------------
# Serve OpenAPI YAML
# -------------------------------------------------
@app.get("/openapi.yaml", include_in_schema=False)
def openapi_yaml():
    return Response(
        content=build_openapi_yaml(),
        media_type="application/yaml",
        headers={"Content-Disposition": 'attachment; filename="openapi.yaml"'},
    )

# -------------------------------------------------
# Background maintenance (disabled on Cloud Run)
# -------------------------------------------------
@app.on_event("startup")
def start_reaper():
    """
    IMPORTANT:
    Cloud Run MUST NOT run infinite background threads.
    """
    if os.getenv("KREYAI_ENV") == "cloudrun":
        print("⏭️ Reaper disabled on Cloud Run")
        return

    import threading
    import time
    from app.maintenance.reaper import reap_stuck_jobs

    def loop():
        while True:
            try:
                count = reap_stuck_jobs()
                if count:
                    print(f"🧹 Reaper recovered {count} stuck job(s)")
            except Exception as e:
                print(f"🔥 Reaper error: {e}")
            time.sleep(10)

    threading.Thread(target=loop, daemon=True).start()
