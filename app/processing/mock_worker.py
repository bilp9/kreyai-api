# app/processing/mock_worker.py
import asyncio
from app.state.state_manager import update_progress

async def process_job(job):
    for pct in range(0, 101, 20):
        await asyncio.sleep(1)
        update_progress(job, pct)
