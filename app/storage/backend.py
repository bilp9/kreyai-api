import os
import datetime
import google.auth
from google.auth.transport.requests import Request
from google.cloud import storage


class GCSStorage:
    """
    Production-grade Google Cloud Storage backend.

    - Uses Cloud Run service account
    - No JSON key files
    - IAM-based V4 signed URLs
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
        """
        Upload user file to:
        jobs/{job_id}/uploads/{filename}
        """
        blob_path = self.upload_blob_path(job_id, filename)
        blob = self.bucket.blob(blob_path)
        blob.upload_from_file(file_obj)
        return blob_path

    def upload_output_file(self, job_id: str, local_path: str, filename: str):
        """
        Upload worker output file to:
        jobs/{job_id}/outputs/{filename}
        """
        blob_path = self.output_blob_path(job_id, filename)
        blob = self.bucket.blob(blob_path)
        blob.upload_from_filename(local_path)
        return blob_path

    # -----------------------------
    # DOWNLOAD URL (IAM SIGNING)
    # -----------------------------

    def get_download_url(self, job_id: str, filename: str) -> str:
        """
        Create V4 signed download URL using IAM signing.
        Works in Cloud Run without private key files.
        """

        blob_path = self.output_blob_path(job_id, filename)
        blob = self.bucket.blob(blob_path)

        if not blob.exists():
            raise RuntimeError(f"GCS file not found: {blob_path}")

        # Get Cloud Run credentials
        credentials, _ = google.auth.default()
        credentials.refresh(Request())

        # IMPORTANT:
        # If credentials.service_account_email fails,
        # replace it with your actual service account email.
        service_account_email = getattr(
            credentials,
            "service_account_email",
            "98057750771-compute@developer.gserviceaccount.com",
        )

        url = blob.generate_signed_url(
            version="v4",
            expiration=datetime.timedelta(hours=1),
            method="GET",
            service_account_email=service_account_email,
            access_token=credentials.token,
        )

        return url
        

# Singleton storage instance
_storage_instance = None


def get_storage():
    global _storage_instance
    if _storage_instance is None:
        _storage_instance = GCSStorage()
    return _storage_instance
