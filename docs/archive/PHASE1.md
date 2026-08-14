# KreyAI — Phase 1 Specification (Historical)

> Archived: this document describes an early development phase and is not current product or operational documentation.

## Overview

Phase 1 establishes the foundational workflow for Kreyai’s transcription platform.
The goal of this phase is **stability, correctness, and trust**, not scale or feature breadth.

Kreyai Phase 1 supports secure job creation, email verification, file upload, and
basic job lifecycle management for audio and video transcription workloads.

This phase is intentionally limited.

---

## Core Principles

- **Accuracy over speed**
- **Security before convenience**
- **Minimal retention**
- **Explicit user consent**
- **Human-review–friendly outputs**
- **No silent reuse of customer data**

---

## Scope (Phase 1)

### Included
- Job creation
- Email verification (one-time code)
- File upload (audio/video)
- Job lifecycle tracking
- Limited retention for support
- Manual or internal processing
- API-first design

### Explicitly Excluded
- Payments
- User accounts
- Background queues
- Automatic transcription execution
- Cloud deployment
- Diarization configuration UI
- Language selection UI
- Marketing or analytics tracking

---

## Job Lifecycle

Each transcription request is represented by a **Job**.

### Job States

| State | Description |
|-----|-------------|
| `pending_verification` | Job created, email not yet verified |
| `verified` | Email verified, upload allowed |
| `uploaded` | File successfully uploaded |
| `processing` | Internal transcription processing (manual or automated) |
| `completed` | Transcription completed |
| `failed` | Processing error or invalid input |
| `expired` | Retention window exceeded |

---

## Email Verification

- Email verification is **mandatory**
- A one-time numeric code is issued per job
- Verification must occur **before upload**
- Incorrect codes do not reveal job existence
- Codes expire after a short time window (configurable)

**Phase 1 behavior:**
- Emails are logged to console (development)
- No external email provider is required yet

---

## File Upload Constraints

- Supported formats: audio and video
- Maximum file size: **1–2 GB**
- One file per job
- Upload allowed only after verification
- Multiple upload attempts are blocked after success

---

## Retention Policy

Retention exists **solely for support purposes**.

- Default retention: **7 days**
- Files and transcripts are automatically deleted after expiration
- No long-term storage
- No reuse for training or analytics

Retention is **not configurable by the user** in Phase 1.

---

## Reprocessing Policy

- One-time reprocessing allowed **if user made a mistake**
- Unlimited reprocessing **only if Kreyai caused the error**
- Reprocessing always requires explicit request
- No silent retries

This protects both:
- Customer trust
- Infrastructure cost

---

## Privacy & Data Handling

- Customer data is never sold or shared
- Email addresses are used **only** for job communication
- Files are not used for model training
- Logs avoid storing raw content
- Access is strictly scoped per job

---

## Supported Languages (Phase 1)

- Haitian Creole (primary focus)
- Mixed-language speech (Creole, French, English)
- Other languages may work but are **not guaranteed**

Language expansion is planned for Phase 2.

---

## Known Limitations

- No real-time status updates
- No frontend authentication
- No payment enforcement
- No automatic diarization toggle
- No subtitle exports (SRT/VTT) yet
- No cloud-scale processing

These are **intentional**.

---

## API Stability

- Phase 1 API is considered **stable**
- Breaking changes require a new version
- Endpoint contracts should not change silently

---

## Phase 1 Success Criteria

Phase 1 is considered complete when:
- Jobs can be created, verified, uploaded reliably
- Errors are predictable and recoverable
- Support can diagnose issues via job ID alone
- No data leaks or retention violations occur

---

## Next Phases (Preview)

### Phase 2 (Planned)
- Payments
- Background processing
- Subtitles export (SRT/VTT)
- Language selection
- Diarization options
- Cloud deployment

---

**Phase 1 intentionally prioritizes trust, correctness, and restraint.**
