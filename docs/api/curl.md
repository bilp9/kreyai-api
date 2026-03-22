# KreyAI API Examples

The public API contract is served dynamically at:

```text
https://api.kreyai.com/openapi.yaml
```

The current production app also exposes the customer job flow used by the web experience:

1. `POST /api/` to create a job
2. `POST /api/verify` to verify the email code
3. `POST /api/jobs/{job_id}/upload-url` to begin upload
4. `POST /api/jobs/{job_id}/finalize-upload` to queue processing
5. `GET /api/jobs/{job_id}` to track completion

This file is intentionally light until the direct public transcription endpoint examples are refreshed for the current deployment.
