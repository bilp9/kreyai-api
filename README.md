Kreyai API — Phase 1

Kreyai is a secure, email-verified transcription job system designed for high-fidelity language processing workflows.

Phase-1 establishes a stable job intake and verification layer.
Audio processing is intentionally out of scope at this stage.

🔐 Phase-1 Scope (Frozen)
Implemented

Job creation with unique job ID

Email-based verification (code + job ID)

Explicit job lifecycle states

OpenAPI documentation via Swagger

No authentication accounts required

No persistent storage (in-memory, dev)

Out of Scope (Phase-2+)

Audio uploads

Transcription processing

Payments

User accounts

Long-term storage

Webhooks / notifications

🔁 Job Lifecycle
pending_verification → verified


Only verified jobs may proceed to processing in Phase-2.

🌐 API Endpoints
Create Job
POST /api/


Response

{
  "job_id": "KR-123456",
  "status": "pending_verification",
  "created_at": "ISO-8601 timestamp"
}

Verify Job
POST /api/verify?job_id=KR-123456&code=123456


Response

{
  "job_id": "KR-123456",
  "status": "verified",
  "verified_at": "ISO-8601 timestamp"
}

📄 API Docs

Swagger UI available at:

/docs

🧪 Development Notes

Email delivery is mocked (console output)

Job storage is in-memory

API contract is frozen for Phase-1

Changes require versioning in Phase-2+

🧭 Roadmap

Phase-2: file uploads, processing pipeline, retention rules

Phase-3: accounts, billing, advanced workflows

License

Private / internal — not open source (for now).
