# app/processing/payloads.py
from pydantic import BaseModel, Field


class JobTaskPayload(BaseModel):
    job_id: str = Field(..., min_length=3)
