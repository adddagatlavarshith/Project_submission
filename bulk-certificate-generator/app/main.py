import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import worker
from app.api.routes import router
from app.database import SessionLocal, init_db
from app.services import unfinished_job_ids

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    # Resume jobs interrupted by a restart. Only pending certificates are processed,
    # so re-running a job never regenerates certificates that already exist.
    with SessionLocal() as db:
        job_ids = unfinished_job_ids(db)
    for job_id in job_ids:
        logger.info("Resuming unfinished job %s", job_id)
        worker.dispatch(job_id)
    yield
    worker.shutdown(wait=True)


app = FastAPI(
    title="Bulk Certificate Generator",
    version="1.0.0",
    description="Submit a list of recipients and generate a PDF certificate for each of them.",
    lifespan=lifespan,
)
app.include_router(router)


@app.get("/health", tags=["health"])
def health():
    return {"status": "ok"}
