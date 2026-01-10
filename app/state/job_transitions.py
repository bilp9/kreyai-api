from app.constants import JobStatus

ALLOWED_TRANSITIONS = {
    JobStatus.PENDING_VERIFICATION: {JobStatus.VERIFIED},

    JobStatus.VERIFIED: {JobStatus.UPLOADED},

    JobStatus.UPLOADED: {JobStatus.QUEUED},

    JobStatus.QUEUED: {JobStatus.PROCESSING},

    # Phase-2C: allow retry by sending PROCESSING back to QUEUED
    JobStatus.PROCESSING: {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.QUEUED},

    JobStatus.FAILED: set(),
    JobStatus.COMPLETED: set(),
    JobStatus.EXPIRED: set(),
}
