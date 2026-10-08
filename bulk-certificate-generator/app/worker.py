"""Dispatches jobs for processing.

The default is an in-process thread pool: the API returns immediately and generation happens
in the background. All callers go through `dispatch()`, so replacing this with a real task
queue (Celery, RQ, ...) only requires changing this module.
"""

import logging
from concurrent.futures import ThreadPoolExecutor

from app.config import get_settings
from app.processor import process_job

logger = logging.getLogger(__name__)

_executor: ThreadPoolExecutor | None = None


def _get_executor() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(
            max_workers=get_settings().worker_threads, thread_name_prefix="cert-worker"
        )
    return _executor


def dispatch(job_id: str) -> None:
    if get_settings().processing_mode == "sync":
        process_job(job_id)
    else:
        _get_executor().submit(process_job, job_id)


def shutdown(wait: bool = True) -> None:
    global _executor
    if _executor is not None:
        _executor.shutdown(wait=wait)
        _executor = None
