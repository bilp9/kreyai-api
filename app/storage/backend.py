# app/storage/backend.py

import os
import datetime
from google.cloud import storage


class GCSStorage:
    """
    Production-grade Google Cloud Storage backend.
    Uses Cloud Run service account with IAM signing.
    """

    def __init__(self):
        self.bucket_name = os.environ.get("GCS_BUCKET")
        if not self.bucket_name:
            raise RuntimeError("GCS_BUCKET environment variable not set")

        self.client = storage.Client()
        self.bucket = self.client.bucket(self.bucket_name)

    # -----------------------------
    # PATH HELPERS
    # -----------------------------

    def upload_blob_path(self, job_id: str, filename: str) -> str:
        return f"jobs/{job_id}/uploads/{filename}"

    def output_blob_path(self, job_id: str, filename: str) -> str:
        return f"jobs/{job_id}/outputs/{filename}"

    # -----------------------------
    # RESUMABLE START URL
    # -----------------------------

    def generate_resumable_start_url(
        self,
        blob_path: str,
        content_type: str,
    ) -> str:
        blob = self.bucket.blob(blob_path)

        url = blob.generate_signed_url(
            version="v4",
            expiration=datetime.timedelta(minutes=15),
            method="POST",
            headers={
                "x-goog-resumable": "start",
                "content-type": content_type,
            },
        )

        return url

    # -----------------------------
    # SIGNED DOWNLOAD URL (7 days)
    # -----------------------------

    def get_download_url(
        self,
        job_id: str,
        filename: str,
        force_download: bool = False,
    ) -> str:
        blob_path = self.output_blob_path(job_id, filename)
        blob = self.bucket.blob(blob_path)

        if not blob.exists():
            raise RuntimeError("File not found")

        response_disposition = None
        if force_download:
            response_disposition = f'attachment; filename="{filename}"'

        url = blob.generate_signed_url(
            version="v4",
            expiration=datetime.timedelta(days=7),
            method="GET",
            response_disposition=response_disposition,
        )

        return url


# -------------------------------------------------
# Singleton instance
# -------------------------------------------------

_storage_instance = None


def get_storage():
    global _storage_instance
    if _storage_instance is None:
        _storage_instance = GCSStorage()
    return _storage_instance