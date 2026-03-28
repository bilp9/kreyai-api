# Retention Enforcement

KreyAI currently enforces 7-day access expiry through:

- job access token TTL
- signed download URL expiry

To enforce actual blob deletion after 7 days, apply the GCS lifecycle policy in
`docs/ops/gcs-lifecycle-7-days.json` to the uploads bucket.

Example:

```bash
gcloud storage buckets update gs://$GCS_BUCKET \
  --lifecycle-file=docs/ops/gcs-lifecycle-7-days.json
```

Scope note:

- This deletes all objects under the `jobs/` prefix after 7 days.
- That includes uploaded source files and generated outputs.
- If you later need different retention for uploads vs outputs, split them into
  separate buckets or move them under separate prefixes with different rules.
