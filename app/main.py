from fastapi import FastAPI
from app.routes import jobs

app = FastAPI(
    title="Kreyai API",
    description="Secure transcription job service",
    version="0.1.0"
)

app.include_router(jobs.router, prefix="/api")


@app.get("/")
def root():
    return {"status": "Kreyai API running"}
