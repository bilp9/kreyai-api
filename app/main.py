from fastapi import FastAPI


from app.routes import jobs

app = FastAPI(title="Kreyai API")
app.include_router(jobs.router)

