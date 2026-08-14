# KreyAI — Phase 2 Technical Scope (Historical)

> Archived: this document describes an early development phase and is not current product or operational documentation.

Phase 2 builds on the stabilized Phase 1 API and introduces
job execution, resiliency, and processing orchestration.

This phase is focused on **control, observability, and safety** —
not performance or scale.

---

## Objectives

- Introduce background job execution
- Track progress and attempts
- Handle failures deterministically
- Prepare for real async workers
- Keep API contracts stable

---

## Job Lifecycle (Phase 2)

PENDING_VERIFICATION  
→ VERIFIED  
→ UPLOADED  
→ QUEUED  
→ PROCESSING  
→ COMPLETED | FAILED | EXPIRED

---

## New Capabilities

### 1. Dispatcher
- Accepts verified + uploaded jobs
- Moves jobs into QUEUED state
- Hands off execution to runner

### 2. Runner (Mock Processor)
- Simulates processing work
- Updates progress (0–100)
- Supports failure simulation
- Enforces timeout rules
- Increments attempt count

### 3. Progress Tracking
- `/jobs/{job_id}/progress`
- Read-only endpoint
- Frontend-safe polling

---

## Failure & Retry Policy

- Maximum attempts: configurable
- Timeout per attempt enforced
- Failed jobs are terminal unless retried manually
- All failures are recorded as events

---

## Constants & Guards

All limits, flags, and enums live in `constants.py`:
- JobStatus enum
- Upload size limits
- Retry limits
- Timeouts
- Feature flags

No magic values in route handlers.

---

## Out of Scope (Phase 2)

- Real AI transcription
- Cloud queues
- Billing / payments
- User accounts
- Authentication beyond email verification

---

## Exit Criteria

Phase 2 is complete when:
- Jobs reliably process or fail
- Progress is observable
- Retries and timeouts work
- API contract is frozen
- System is ready for async workers

---

## Next Phase Preview (Phase 3)

- Replace mock runner with real worker
- Introduce message queue (GCP / AWS)
- Persistent storage
- Production email provider
