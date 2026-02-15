from pathlib import Path
from typing import BinaryIO
import os

from google.cloud import storage

# --------------------------------------
# ENV Detection
# --------------------------------------

ENV = os.getenv("KREYAI_ENV", "local")

# If using GCS
GCS_BUCKET_NAME = os.getenv("KREYAI_GCS_BUCKET", "kreyai-jobs-prod")


class StorageBackend:
    def save_upload(self, job_id: str, filename: str, file_obj: BinaryIO) -> str:
        raise NotImplementedError

    def save_output(self, job_id: str, filename: str, data: bytes) -> str:
        raise NotImplementedError

    def get_download_url(self, job_id: str, filename: str) -> str:
        raise NotImplementedError


# --------------------------------------
# LOCAL STORAGE
# --------------------------------------

class LocalStorage(StorageBackend):
    BASE_DIR = Path("app/storage")

    def save_upload(self, job_id: str, filename: str, file_obj: BinaryIO) -> str:
        upload_dir = self.BASE_DIR / "uploads" / job_id
        upload_dir.mkdir(parents=True, exist_ok=True)

        path = upload_dir / filename
        with open(path, "wb") as f:
            f.write(file_obj.read())

        return str(path)

    def save_output(self, job_id: str, filename: str, data: bytes) -> str:
        output_dir = self.BASE_DIR / "outputs" / job_id
        output_dir.mkdir(parents=True, exist_ok=True)

        path = output_dir / filename
        path.write_bytes(data)

        return str(path)

    def get_download_url(self, job_id: str, filename: str) -> str:
        return f"/api/jobs/{job_id}/{filename}"


# --------------------------------------
# GCS STORAGE
# --------------------------------------

class GCSStorage(StorageBackend):
    def __init__(self):
        self.client = storage.Client()
        self.bucket = self.client.bucket(GCS_BUCKET_NAME)

    def save_upload(self, job_id: str, filename: str, file_obj: BinaryIO) -> str:
        blob_path = f"jobs/{job_id}/uploads/{filename}"
        blob = self.bucket.blob(blob_path)
        blob.upload_from_file(file_obj)
        return blob_path

    def save_output(self, job_id: str, filename: str, data: bytes) -> str:
        blob_path = f"jobs/{job_id}/outputs/{filename}"
        blob = self.bucket.blob(blob_path)
        blob.upload_from_string(data)
        return blob_path

    def get_download_url(self, job_id: str, filename: str) -> str:
        blob_path = f"jobs/{job_id}/outputs/{filename}"
        blob = self.bucket.blob(blob_path)
        return blob.generate_signed_url(expiration=3600)


# --------------------------------------
# Factory
# --------------------------------------

def get_storage() -> StorageBackend:
    if ENV == "cloudrun":
        return GCSStorage()
    return LocalStorage()
