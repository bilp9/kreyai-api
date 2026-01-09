# app/state/job_transitions.py
from app.constants import JobStatus

ALLOWED_TRANSITIONS = {
    JobStatus.PENDING_VERIFICATION: {JobStatus.VERIFIED},
    JobStatus.VERIFIED: {JobStatus.UPLOADED},
    JobStatus.UPLOADED: {JobStatus.QUEUED},
    JobStatus.QUEUED: {JobStatus.PROCESSING},
    JobStatus.PROCESSING: {JobStatus.COMPLETED, JobStatus.FAILED},
    JobStatus.FAILED: set(),
    JobStatus.COMPLETED: set(),
}
