from pydantic import BaseModel, EmailStr
from datetime import datetime
from typing import Optional

class JobCreateRequest(BaseModel):
    email: EmailStr
    file_name: str
    file_size_mb: float
    diarization: bool = False

class JobResponse(BaseModel):
    job_id: str
    status: str
    created_at: datetime

class JobVerifyRequest(BaseModel):
    job_id: str
    code: str
