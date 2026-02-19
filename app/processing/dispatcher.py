# app/processing/dispatcher.py

from google.cloud import run_v2
import google.auth
import os


def _get_project_id() -> str:
    """
    Robust project resolution for Cloud Run production.
    Priority:
      1. GOOGLE_CLOUD_PROJECT
      2. GCP_PROJECT
      3. Auto-detect via ADC (google.auth.default)
    """

    project = (
        os.environ.get("GOOGLE_CLOUD_PROJECT")
        or os.environ.get("GCP_PROJECT")
    )

    if project:
        return project

    # Fallback to Application Default Credentials metadata
    credentials, detected_project = google.auth.default()

    if detected_project:
        return detected_project

    raise RuntimeError("Unable to determine GCP project ID.")


def dispatch_job(job_id: str):
    """
    Production-grade Cloud Run Job trigger.
    Executes kreyai-worker and passes JOB_ID as env var.
    """

    project = _get_project_id()
    region = os.environ.get("CLOUD_RUN_REGION", "us-central1")

    client = run_v2.JobsClient()

    job_name = f"projects/{project}/locations/{region}/jobs/kreyai-worker"

    request = run_v2.RunJobRequest(
        name=job_name,
        overrides=run_v2.RunJobRequest.Overrides(
            container_overrides=[
                run_v2.RunJobRequest.Overrides.ContainerOverride(
                    # MUST match container name in Cloud Run Job
                    name="kreyai-worker",
                    env=[
                        run_v2.EnvVar(
                            name="JOB_ID",
                            value=job_id,
                        )
                    ],
                )
            ]
        ),
    )

    operation = client.run_job(request=request)

    print(f"🚀 Triggered worker for job {job_id}")
    return operation
