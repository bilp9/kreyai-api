# Retention Enforcement

KreyAI currently enforces 7-day access expiry through:

- job access token TTL
- signed download URL expiry

Production verification on August 13, 2026 confirmed that `gs://kreyai-uploads`
has a lifecycle rule that deletes objects under `jobs/` at age 7 days. The
bucket also has a 7-day GCS soft-delete retention period, so deleted objects are
removed from active customer access after 7 days and remain recoverable by
authorized operators for the following 7 days.

Apply `docs/ops/gcs-lifecycle-7-days.json` when provisioning or repairing the
uploads bucket.

Example:

```bash
gcloud storage buckets update gs://$GCS_BUCKET \
  --lifecycle-file=docs/ops/gcs-lifecycle-7-days.json
```

Scope note:

- This deletes all objects under the `jobs/` prefix after 7 days.
- That includes uploaded source files and generated outputs.
- GCS soft delete is a recovery safeguard; it does not extend customer access.
- If you later need different retention for uploads vs outputs, split them into
  separate buckets or move them under separate prefixes with different rules.
