# app/storage/backend.py

import os
import datetime
import google.auth
from google.auth.transport.requests import Request
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
    # UPLOAD
    # -----------------------------

    def upload_file(self, job_id: str, file_obj, filename: str):
        blob_path = self.upload_blob_path(job_id, filename)
        blob = self.bucket.blob(blob_path)
        blob.upload_from_file(file_obj)
        return blob_path

    # -----------------------------
    # Backward compatibility wrapper
    # -----------------------------

    def save_upload(self, job_id: str, filename: str, file_obj):
        """
        Compatibility wrapper for existing upload route.
        """
        return self.upload_file(job_id, file_obj, filename)

    # -----------------------------
    # DOWNLOAD (Worker)
    # -----------------------------

    def download_to_file(self, source: str, local_path: str):
        blob = self.bucket.blob(source)

        if not blob.exists():
            raise RuntimeError(f"GCS input file not found: {source}")

        blob.download_to_filename(local_path)
        return local_path

    # -----------------------------
    # SAVE OUTPUT
    # -----------------------------

    def save_output(self, job_id: str, filename: str, data: bytes, content_type: str):
        blob_path = self.output_blob_path(job_id, filename)
        blob = self.bucket.blob(blob_path)
        blob.upload_from_string(data, content_type=content_type)
        return blob_path

    # -----------------------------
    # SIGNED URL (7-day expiration)
    # -----------------------------

    def get_download_url(self, job_id: str, filename: str) -> str:
        blob_path = self.output_blob_path(job_id, filename)
        blob = self.bucket.blob(blob_path)

        if not blob.exists():
            raise RuntimeError(f"GCS output file not found: {blob_path}")

        credentials, _ = google.auth.default()
        credentials.refresh(Request())

        service_account_email = getattr(credentials, "service_account_email", None)
        if not service_account_email:
            raise RuntimeError("Service account email not available")

        url = blob.generate_signed_url(
            version="v4",
            expiration=datetime.timedelta(days=7),
            method="GET",
            service_account_email=service_account_email,
            access_token=credentials.token,
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