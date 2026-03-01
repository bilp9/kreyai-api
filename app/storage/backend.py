def generate_resumable_start_url(
    self,
    blob_path: str,
    content_type: str,
) -> str:
    """
    Creates signed URL to START a resumable upload session.
    Frontend must send:
        PUT
        x-goog-resumable: start
    """

    blob = self.bucket.blob(blob_path)

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
        method="PUT",  # ✅ FIXED
        content_type=content_type,
        headers={
            "x-goog-resumable": "start",
        },
        service_account_email=service_account_email,
        access_token=self.credentials.token,
    )

    return url