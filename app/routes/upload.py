# app/routes/upload.py

from fastapi import APIRouter, UploadFile, File, Depends
from app.auth.auth import get_current_user
from app.services.quota import check_and_consume_quota
from app.transcription.engine import transcribe_audio

router = APIRouter(prefix="/api", tags=["upload"])


@router.post("/upload")
async def upload_audio(
    file: UploadFile = File(...),
    user=Depends(get_current_user),
):
    # ----------------------------------
    # Quota enforcement (v1)
    # ----------------------------------
    # Conservative default: 60 seconds per request
    #check_and_consume_quota(user, seconds=60)
    check_and_consume_quota(user, seconds=estimated_seconds)


    # ----------------------------------
    # Save temp file
    # ----------------------------------
    import tempfile

    suffix = file.filename[file.filename.rfind(".") :]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    # ----------------------------------
    # Transcribe
    # ----------------------------------
    text = transcribe_audio(tmp_path)

    return {
        "id": f"kr_{user.id}",
        "text": text,
    }
