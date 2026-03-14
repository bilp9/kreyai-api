from fastapi import APIRouter
from app.queue.autoscaler import autoscale

router = APIRouter()

@router.get("/scale")
def scale_queue():

    autoscale()

    return {"status": "ok"}