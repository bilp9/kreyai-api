# app/storage/backend.py
from __future__ import annotations

import os
import datetime
from typing import Optional, Dict

from google.cloud import storage
import google.auth
from google.auth.transport.requests import Request

class GCSStorage:
    """
    Google Cloud Storage backend.
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
    # UPLOAD (legacy API upload)
    # -----------------------------
    def upload_file(self, job_id: str, file_obj, filename: str) -> str:
        blob_path = self.upload_blob_path(job_id, filename)
        blob = self.bucket.blob(blob_path)
        blob.upload_from_file(file_obj)
        return blob_path

    def save_upload(self, job_id: str, filename: str, file_obj) -> str:
        return self.upload_file(job_id, file_obj, filename)

    # -----------------------------
    # DOWNLOAD (worker)
    # -----------------------------
    def download_to_file(self, source: str, local_path: str) -> str:
        blob = self.bucket.blob(source)
        if not blob.exists():
            raise RuntimeError(f"GCS input file not found: {source}")
        blob.download_to_filename(local_path)
        return local_path

    # -----------------------------
    # SAVE OUTPUT
    # -----------------------------
    def save_output(self, job_id: str, filename: str, data: bytes, content_type: str) -> str:
        blob_path = self.output_blob_path(job_id, filename)
        blob = self.bucket.blob(blob_path)
        blob.upload_from_string(data, content_type=content_type)
        return blob_path

    # -----------------------------
    # Resumable upload (signed session start)
    # -----------------------------
    


    def create_resumable_start_url(self, object_path: str, content_type: str) -> str:
        """
        Creates a V4 signed URL using IAM-based signing (required on Cloud Run).
        """

        blob = self.bucket.blob(object_path)

        credentials, _ = google.auth.default()
        credentials.refresh(Request())

        signed_url = blob.generate_signed_url(
            version="v4",
            expiration=datetime.timedelta(minutes=10),
            method="POST",
            content_type=content_type,
            headers={"x-goog-resumable": "start"},
            service_account_email=credentials.service_account_email,
            access_token=credentials.token,
        )

        return signed_url

    # -----------------------------
    # SIGNED URL (download)
    # -----------------------------
    def get_download_url(self, job_id: str, filename: str, force_download: bool = False) -> str:
        blob_path = self.output_blob_path(job_id, filename)
        blob = self.bucket.blob(blob_path)

        if not blob.exists():
            raise RuntimeError(f"File not found: {blob_path}")

        response_disposition = None
        if force_download:
            response_disposition = f'attachment; filename="{filename}"'

        # ✅ 7 days (max practical for many systems)
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
_storage_instance: Optional[GCSStorage] = None


def get_storage() -> GCSStorage:
    global _storage_instance
    if _storage_instance is None:
        _storage_instance = GCSStorage()
    return _storage_instance