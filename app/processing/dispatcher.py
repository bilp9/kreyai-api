# app/processing/dispatcher.py

import os
import google.auth
from google.cloud import run_v2


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


def dispatch_job(
    job_id: str,
    *,
    worker_job_name: str = "kreyai-worker",
    worker_job_region: str | None = None,
    execution_lane: str | None = None,
    requires_diarization: bool | None = None,
):
    """
    Production-grade Cloud Run Job trigger.
    Executes the selected Cloud Run Job and passes routing env vars.
    """

    project = _get_project_id()
    region = worker_job_region or os.environ.get("CLOUD_RUN_REGION", "us-central1")

    client = run_v2.JobsClient()

    job_name = f"projects/{project}/locations/{region}/jobs/{worker_job_name}"

    env_vars = [
        run_v2.EnvVar(
            name="JOB_ID",
            value=job_id,
        )
    ]

    if execution_lane:
        env_vars.append(
            run_v2.EnvVar(
                name="EXECUTION_LANE",
                value=str(execution_lane),
            )
        )

    if requires_diarization is not None:
        env_vars.append(
            run_v2.EnvVar(
                name="REQUIRES_DIARIZATION",
                value="true" if requires_diarization else "false",
            )
        )

    request = run_v2.RunJobRequest(
        name=job_name,
        overrides=run_v2.RunJobRequest.Overrides(
            container_overrides=[
                run_v2.RunJobRequest.Overrides.ContainerOverride(
                    # MUST match container name in Cloud Run Job
                    name="kreyai-worker",
                    env=env_vars,
                )
            ]
        ),
    )

    operation = client.run_job(request=request)

    print(f"Triggered worker {worker_job_name} in {region} for job {job_id}")
    return operation
