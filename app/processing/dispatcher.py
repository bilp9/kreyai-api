# app/processing/dispatcher.py

import os
from google.auth.transport.requests import AuthorizedSession
from google.auth import default as google_auth_default

from app.state.firestore_jobs import update_job
from app.constants import JobStatus
from app.events.recorder import record_event

PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT")
REGION = os.environ.get("GCP_REGION", "us-central1")
WORKER_JOB_NAME = os.environ.get("WORKER_JOB_NAME", "kreyai-worker")


def dispatch_job(job_id: str):
    """
    1) Mark job as queued in Firestore
    2) Automatically trigger Cloud Run Job execution
    """

    # Update Firestore
    update_job(job_id, {
        "status": JobStatus.QUEUED,
        "progress": 0,
    })

    record_event(
        job_id,
        "queued",
        "Job queued (auto-trigger)",
        JobStatus.QUEUED,
    )

    # Authenticate inside Cloud Run
    credentials, _ = google_auth_default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    authed_session = AuthorizedSession(credentials)

    url = (
        f"https://run.googleapis.com/v2/projects/{PROJECT_ID}"
        f"/locations/{REGION}/jobs/{WORKER_JOB_NAME}:run"
    )

    response = authed_session.post(url, json={}, timeout=30)

    if response.status_code >= 300:
        record_event(
            job_id,
            "dispatch_error",
            f"Worker start failed: {response.text}",
            JobStatus.QUEUED,
        )
        raise RuntimeError(
            f"Failed to start worker job: {response.status_code} {response.text}"
        )
