# app/main.py
# =====================================
# PUBLIC API v1 — FROZEN
# =====================================

import os
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

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
    version="1.0.0",
)

# -------------------------------------------------
# Health check (REQUIRED for Cloud Run)
# -------------------------------------------------
@app.get("/health", include_in_schema=False)
def health():
    return {"status": "ok"}

# -------------------------------------------------
# Middleware
# -------------------------------------------------
from app.middleware.rate_limit import (
    RateLimitMiddleware,
    RateLimitHeadersMiddleware,
)
from app.middleware.auth import APIKeyAuthMiddleware

# Headers-only middleware (safe)
app.add_middleware(RateLimitHeadersMiddleware)

# Rate limiting (API routes only)
app.add_middleware(
    RateLimitMiddleware,
    rpm=120,
)

# API key auth
app.add_middleware(APIKeyAuthMiddleware)

# -------------------------------------------------
# Routes
# -------------------------------------------------
from app.routes import jobs, upload

app.include_router(jobs.router)
app.include_router(upload.router)

# -------------------------------------------------
# Serve frozen OpenAPI YAML (v1)
# -------------------------------------------------
@app.get("/openapi.yaml", include_in_schema=False)
def openapi_yaml():
    path = Path("docs/openapi.yaml")
    if not path.exists():
        raise RuntimeError("docs/openapi.yaml not found")
    return FileResponse(
        path,
        media_type="application/yaml",
        filename="openapi.yaml",
    )

# -------------------------------------------------
# Background maintenance
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
