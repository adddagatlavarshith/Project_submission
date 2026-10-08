from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, overridable through environment variables or a .env file."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./certificates.db"
    storage_dir: str = "./storage"
    # Upper bound on recipients per request; protects the API from unbounded payloads.
    max_recipients: int = 5000
    # Number of jobs processed concurrently by the in-process worker pool.
    worker_threads: int = 2
    # "background": jobs run in a thread pool after the request returns.
    # "sync": jobs run inline before the response is sent (used by tests / debugging).
    processing_mode: str = "background"
    # Certificates are committed in batches so progress is visible while a job runs.
    commit_batch_size: int = 20


@lru_cache
def get_settings() -> Settings:
    return Settings()
