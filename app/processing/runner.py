import asyncio
from app.state.jobs_store import JOBS
from app.constants import JobStatus, MAX_JOB_ATTEMPTS, JOB_ATTEMPT_TIMEOUT_SECONDS, PROGRESS_STEPS
from app.state.state_manager import transition_job
from app.events.recorder import record_event

async def _process(job):
    for p in PROGRESS_STEPS:
        await asyncio.sleep(2)
        job["progress"] = p

async def run_job(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        return

    while job["attempts"] < MAX_JOB_ATTEMPTS:
        try:
            job["attempts"] += 1
            transition_job(job, JobStatus.PROCESSING)
            record_event(job, "processing", f"Attempt {job['attempts']}")

            await asyncio.wait_for(
                _process(job),
                timeout=JOB_ATTEMPT_TIMEOUT_SECONDS
            )

            transition_job(job, JobStatus.COMPLETED)
            record_event(job, "completed", "Job completed successfully")
            return

        except asyncio.TimeoutError:
            record_event(job, "timeout", "Processing timed out")

        except Exception as e:
            record_event(job, "error", str(e))

    transition_job(job, JobStatus.FAILED)
    record_event(job, "failed", "Max retries exceeded")
