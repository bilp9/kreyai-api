# KreyAI API

Backend services for KreyAI Transcription, Adwaz operations, and desktop-product checkout and licensing.

## Responsibilities

- Create and verify transcription jobs
- Issue signed upload and download access
- Dispatch transcription processing and recover interrupted jobs
- Manage transcription credits and Stripe webhooks
- Activate aTelier licenses and sell aTelier and Dekk licenses
- Expose authenticated operational reporting and Haitian Creole review workflows

The public website lives in the separate `kreyai-web` repository. aTelier and Dekk desktop source code are maintained separately.

## Runtime

- Python 3.11 or 3.12
- FastAPI
- Google Cloud Run, Cloud Storage, and Firestore
- Stripe for checkout
- Optional GPU worker jobs for diarization and heavier transcription work

## Local Setup

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Copy `.env.example` to `.env` when local credentials are needed. Never commit secrets or production service-account material.

## Route Ownership

- `/health`: service health
- `/api/*`: customer job, checkout, credit, and desktop-license workflows
- `/ops/*`: API-key-protected operational tools
- `/docs` and `/openapi.json`: generated FastAPI contract for implemented routes

Customer job routes use scoped job tokens. Operational routes require an API key. New routes should be private by default and added to the explicit public allowlist only when they implement their own access control.

## Tests

```bash
pytest
```

Run focused tests while developing, then run the full suite before deployment.

## Deployment

Cloud Run deployment definitions and operational documentation live under `cloudbuild*.yaml` and `docs/`. Production configuration is supplied through environment variables and Google Secret Manager.

Important production checks:

- Confirm the Cloud Storage seven-day lifecycle policy is active.
- Confirm scheduled reaper execution and alerts.
- Confirm Stripe webhook signatures and desktop-license signing keys.
- Smoke-test job creation, upload, processing, downloads, and immediate deletion.

See `docs/ops/retention.md` for storage-retention enforcement.

## Internal Programs

The operational runbook for complimentary Linguist Partner licenses is in [`docs/linguist-partner-program.md`](docs/linguist-partner-program.md). Keep participant lists, application exports, API keys, and license keys outside the repository.
