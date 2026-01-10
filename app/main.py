# app/main.py
from fastapi import FastAPI
import asyncio

from app.routes import jobs
from app.processing.worker import worker_loop

app = FastAPI()
app.include_router(jobs.router)

@app.on_event("startup")
async def startup_event():
    # Worker lives inside FastAPI's event loop.
    asyncio.create_task(worker_loop())
