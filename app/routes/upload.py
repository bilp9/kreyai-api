# app/routes/upload.py

import math
import os

from fastapi import APIRouter, UploadFile, File, Depends
from app.auth.auth import get_current_user
from app.services.quota import check_and_consume_quota
from app.transcription.engine import transcribe_audio

router = APIRouter(prefix="/api", tags=["upload"])


def _estimate_upload_seconds(file_path: str) -> int:
    try:
        from app.processing.runner import get_audio_duration_seconds

        return max(1, math.ceil(float(get_audio_duration_seconds(file_path))))
    except Exception:
        return 60


@router.post("/upload")
async def upload_audio(
    file: UploadFile = File(...),
    user=Depends(get_current_user),
):
    # ----------------------------------
    # Save temp file
    # ----------------------------------
    import tempfile

    suffix = ""
    if file.filename and "." in file.filename:
        suffix = file.filename[file.filename.rfind(".") :]

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    try:
        estimated_seconds = _estimate_upload_seconds(tmp_path)

        # ----------------------------------
        # Quota enforcement (v1)
        # ----------------------------------
        check_and_consume_quota(user, seconds=estimated_seconds)

        # ----------------------------------
        # Transcribe
        # ----------------------------------
        result = transcribe_audio(tmp_path)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    return {
        "id": f"kr_{user.id}",
        "text": result["text"] if isinstance(result, dict) else result,
    }
