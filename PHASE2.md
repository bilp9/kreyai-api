# Kreyai — Phase 2 Specification

## Overview

Phase 2 transitions Kreyai from a **validated, supportable workflow** into a
**production-ready transcription platform**.

The focus of this phase is **automation, user autonomy, and paid usage** —
while preserving the trust, accuracy, and restraint established in Phase 1.

Phase 2 does **not** aim for mass scale yet. It aims for *reliable real-world use*.

---

## Core Objectives

- Introduce paid usage
- Automate transcription processing
- Improve user experience without forcing accounts
- Expand language and output support
- Maintain strict privacy guarantees
- Control infrastructure costs

---

## Scope (Phase 2)

### Included

#### 1. Payments
- Pay-per-job pricing
- Clear cost preview before processing
- Payment required **after verification, before processing**
- Stripe or equivalent provider
- No subscription requirement

#### 2. Background Processing
- Asynchronous job processing
- FIFO queue by default
- Concurrent processing with guardrails
- Automatic retry on recoverable errors

#### 3. Output Formats
- Plain text transcript (default)
- Subtitle exports:
  - SRT
  - VTT
- Time-aligned transcripts (best effort)

#### 4. Diarization (Optional)
- User-selectable diarization at job creation
- Clear disclaimer on diarization accuracy
- No retroactive diarization without reprocessing
- One reprocessing allowed if user forgot to enable it

#### 5. Language Handling
- Explicit language selection (optional)
- Auto-detection remains default
- Improved handling of:
  - Code-switching
  - Mixed Creole / French / English speech
- Language list exposed in UI (non-exclusive)

#### 6. Notifications
- Email notification when job completes
- Secure download link with expiration
- Optional one-time access code for downloads

---

## Job Lifecycle (Phase 2 Extension)

Additional states introduced:

| State | Description |
|-----|-------------|
| `awaiting_payment` | Verified but not yet paid |
| `queued` | Awaiting processing |
| `processing` | Actively transcribing |
| `ready_for_download` | Output available |
| `downloaded` | User retrieved output |

All Phase 1 states remain valid.

---

## Retention Policy (Phase 2)

- Default retention remains **7 days**
- Optional paid extensions (e.g. 30 days)
- Automatic deletion enforced
- Clear retention countdown visible to users

Retention continues to serve **support and user access only**.

---

## User Accounts (Optional)

Phase 2 introduces **optional accounts**, not mandatory ones.

### Guest Users
- Upload, pay, download without account
- Email-based access only
- Limited job history

### Account Users
- Job history dashboard
- Faster checkout
- Saved preferences
- Extended retention options

No dark patterns forcing account creation.

---

## Privacy & Compliance

- Same privacy guarantees as Phase 1
- Explicit confirmation that:
  - Content is not sold
  - Content is not used for training
- GDPR-friendly deletion flow
- Clear data ownership language

---

## Infrastructure (Target)

- Cloud-based processing (GCP preferred)
- Object storage for files
- Stateless API services
- Secure secrets management
- Cost ceilings and alerts

No premature multi-region deployment.

---

## Known Non-Goals (Phase 2)

Phase 2 will **not** include:
- Real-time transcription
- Live streaming
- Mobile apps
- Team collaboration features
- Advanced analytics dashboards
- Marketplace or API resale

These are candidates for later phases.

---

## Phase 2 Success Criteria

Phase 2 is successful when:
- Users can complete end-to-end paid jobs autonomously
- Jobs process reliably without manual intervention
- Support load is manageable
- Costs remain predictable
- Trust is preserved

---

## Phase 3 (Preview)

Potential future directions:
- Enterprise plans
- Team workspaces
- API access for partners
- Custom language models
- Advanced quality review tools
- Integration with media platforms

---

**Phase 2 builds capability — not chaos.**
