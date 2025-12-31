# app/processing/dispatcher.py

from app.processing.mock_processor import process_job

def dispatch_job(job_id: str):
    process_job(job_id)

