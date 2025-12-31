from fastapi import APIRouter, UploadFile, File, HTTPException
from pydantic import BaseModel, EmailStr
from datetime import datetime
import random
import string
import os

router = APIRouter(prefix="/api", tags=["jobs"])

# -----------------------------
# In-memory job store (Phase 1)
# -----------------------------
JOBS = {}

# -----------------------------
# Models
# -----------------------------

class JobCreateRequest(BaseModel):
    email: EmailStr


class JobResponse(BaseModel):
    job_id: str
    status: str
    created_at: datetime


class VerifyResponse(BaseModel):
    job_id: str
    status: str
    verified_at: datetime


class UploadResponse(BaseModel):
    job_id: str
    status: str
    filename: str


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    created_at: datetime
    verified_at: datetime | None = None
    uploaded_at: datetime | None = None


# -----------------------------
# Helpers
# -----------------------------

def generate_job_id() -> str:
    return "KR-" + "".join(random.choices(string.digits, k=6))


def generate_code() -> str:
    return "".join(random.choices(string.digits, k=6))


# -----------------------------
# Create Job
# -----------------------------

@router.post("/", response_model=JobResponse)
def create_job(payload: JobCreateRequest):
    job_id = generate_job_id()
    code = generate_code()

    JOBS[job_id] = {
        "email": payload.email,
        "code": code,
        "status": "pending_verification",
        "created_at": datetime.utcnow(),
        "verified_at": None,
        "uploaded_at": None,
        "filename": None,
    }

    # DEV email simulation
    print(
        f"""
        =========================
        EMAIL VERIFICATION (DEV)
        =========================
        To: {payload.email}
        Job ID: {job_id}
        Verification Code: {code}
        =========================
        """
    )

    return {
        "job_id": job_id,
        "status": "pending_verification",
        "created_at": JOBS[job_id]["created_at"],
    }


# -----------------------------
# Verify Email
# -----------------------------

@router.post("/verify", response_model=VerifyResponse)
def verify_job(job_id: str, code: str):
    job = JOBS.get(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job["status"] != "pending_verification":
        raise HTTPException(status_code=400, detail="Job already verified")

    if job["code"] != code:
        raise HTTPException(status_code=400, detail="Invalid verification code")

    job["status"] = "verified"
    job["verified_at"] = datetime.utcnow()

    return {
        "job_id": job_id,
        "status": job["status"],
        "verified_at": job["verified_at"],
    }


# -----------------------------
# Upload File
# -----------------------------

@router.post("/upload", response_model=UploadResponse)
def upload_file(job_id: str, file: UploadFile = File(...)):
    job = JOBS.get(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job["status"] != "verified":
        raise HTTPException(status_code=400, detail="Job not verified")

    os.makedirs("app/storage", exist_ok=True)
    file_path = f"app/storage/{job_id}_{file.filename}"

    with open(file_path, "wb") as f:
        f.write(file.file.read())

    job["status"] = "uploaded"
    job["uploaded_at"] = datetime.utcnow()
    job["filename"] = file.filename

    return {
        "job_id": job_id,
        "status": job["status"],
        "filename": file.filename,
    }


# -----------------------------
# Get Job Status (READ ONLY)
# -----------------------------

@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
def get_job_status(job_id: str):
    job = JOBS.get(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return {
        "job_id": job_id,
        "status": job["status"],
        "created_at": job["created_at"],
        "verified_at": job["verified_at"],
        "uploaded_at": job["uploaded_at"],
    }
