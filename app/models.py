from pydantic import BaseModel, EmailStr
from datetime import datetime
from typing import Optional

from app.constants import JobStatus


# =========================
# Job Creation Request
# =========================

class JobCreateRequest(BaseModel):
    email: EmailStr


# =========================
# Job Response (Public)
# =========================

class JobResponse(BaseModel):
    job_id: str
    status: JobStatus
    created_at: datetime


# =========================
# Internal Job Record
# =========================

class JobInternal(BaseModel):
    job_id: str
    email: EmailStr
    status: JobStatus
    created_at: datetime

    # verification
    verification_code: Optional[str] = None
    verified_at: Optional[datetime] = None

    # upload
    filename: Optional[str] = None
    uploaded_at: Optional[datetime] = None

    # processing
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    # retention
    expires_at: Optional[datetime] = None
