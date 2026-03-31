# app/storage/backend.py

import os
import datetime
import google.auth
from google.auth.transport.requests import Request
from google.cloud import storage


class GCSStorage:
    """
    Google Cloud Storage backend for KreyAI.

    - Uses Cloud Run service account
    - Uses IAM-based URL signing (no JSON key file)
    - Supports resumable uploads
    """

    def __init__(self):
        self.bucket_name = os.environ.get("GCS_BUCKET")
        if not self.bucket_name:
            raise RuntimeError("GCS_BUCKET environment variable not set")

        self.client = storage.Client()
        self.bucket = self.client.bucket(self.bucket_name)

        # Cloud Run default credentials
        self.credentials, self.project = google.auth.default()

    # -------------------------------------------------
    # PATH HELPERS
    # -------------------------------------------------

    def upload_blob_path(self, job_id: str, filename: str) -> str:
        return f"jobs/{job_id}/uploads/{filename}"

    def output_blob_path(self, job_id: str, filename: str) -> str:
        return f"jobs/{job_id}/outputs/{filename}"

    # -------------------------------------------------
    # RESUMABLE START URL (15 min)
    # -------------------------------------------------

    def generate_resumable_start_url(
        self,
        blob_path: str,
        content_type: str,
    ) -> str:
        """
        Creates a signed URL to START a resumable upload session.
        Frontend must send:
            x-goog-resumable: start
        """

        blob = self.bucket.blob(blob_path)

        # Ensure fresh token
        self.credentials.refresh(Request())

        service_account_email = getattr(
            self.credentials,
            "service_account_email",
            None,
        )

        if not service_account_email:
            raise RuntimeError("Service account email not available")

        url = blob.generate_signed_url(
            version="v4",
            expiration=datetime.timedelta(minutes=15),
            method="POST",
            headers={
                "x-goog-resumable": "start",
                "content-type": content_type,
            },
            service_account_email=service_account_email,
            access_token=self.credentials.token,
        )

        return url

    # -------------------------------------------------
    # LEGACY DIRECT UPLOAD (small files)
    # -------------------------------------------------

    def upload_file(self, job_id: str, file_obj, filename: str):
        blob_path = self.upload_blob_path(job_id, filename)
        blob = self.bucket.blob(blob_path)
        blob.upload_from_file(file_obj)
        return blob_path

    # -------------------------------------------------
    # WORKER DOWNLOAD
    # -------------------------------------------------

    def download_to_file(self, source_blob_path: str, local_path: str):
        blob = self.bucket.blob(source_blob_path)

        if not blob.exists():
            raise RuntimeError(
                f"GCS input file not found: {source_blob_path}"
            )

        blob.download_to_filename(local_path)
        return local_path

    def blob_exists(self, blob_path: str) -> bool:
        return self.bucket.blob(blob_path).exists()

    def delete_prefix(self, prefix: str) -> int:
        deleted = 0
        for blob in self.client.list_blobs(self.bucket_name, prefix=prefix):
            blob.delete()
            deleted += 1
        return deleted

    # -------------------------------------------------
    # SAVE OUTPUT
    # -------------------------------------------------

    def save_output(
        self,
        job_id: str,
        filename: str,
        data: bytes,
        content_type: str,
    ):
        blob_path = self.output_blob_path(job_id, filename)
        blob = self.bucket.blob(blob_path)

        blob.upload_from_string(
            data,
            content_type=content_type,
        )

        return blob_path

    # -------------------------------------------------
    # SIGNED DOWNLOAD URL (7 days)
    # -------------------------------------------------

    def get_download_url(self, job_id: str, filename: str) -> str:
        blob_path = self.output_blob_path(job_id, filename)
        blob = self.bucket.blob(blob_path)

        if not blob.exists():
            raise RuntimeError(
                f"GCS output file not found: {blob_path}"
            )

        self.credentials.refresh(Request())

        service_account_email = getattr(
            self.credentials,
            "service_account_email",
            None,
        )

        if not service_account_email:
            raise RuntimeError("Service account email not available")

        url = blob.generate_signed_url(
            version="v4",
            expiration=datetime.timedelta(days=7),
            method="GET",
            service_account_email=service_account_email,
            access_token=self.credentials.token,
        )

        return url

    def delete_job_files(self, job_id: str) -> int:
        deleted_uploads = self.delete_prefix(f"jobs/{job_id}/uploads/")
        deleted_outputs = self.delete_prefix(f"jobs/{job_id}/outputs/")
        return deleted_uploads + deleted_outputs


# -------------------------------------------------
# Singleton Instance (IMPORTANT — DO NOT INDENT)
# -------------------------------------------------

_storage_instance = None


def get_storage():
    global _storage_instance
    if _storage_instance is None:
        _storage_instance = GCSStorage()
    return _storage_instance
