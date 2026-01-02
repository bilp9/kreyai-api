# app/state/job_transitions.py

ALLOWED_TRANSITIONS = {
    "pending_verification": {"verified"},
    "verified": {"uploaded"},
    "uploaded": {"queued"},
    "queued": {"processing"},
    "processing": {"completed", "failed"},
    "failed": set(),
    "completed": set(),
}
