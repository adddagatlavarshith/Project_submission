"""Local filesystem storage for generated certificates.

Files live at <STORAGE_DIR>/<job_id>/<certificate_id>.pdf. Only this module knows about the
layout, so swapping it for object storage (e.g. S3) would not touch the rest of the app.
"""

from pathlib import Path

from app.config import get_settings


def _root() -> Path:
    return Path(get_settings().storage_dir)


def save_certificate(job_id: str, certificate_id: str, content: bytes) -> str:
    directory = _root() / job_id
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{certificate_id}.pdf"
    # Write to a temp file first so a crash never leaves a half-written PDF behind.
    tmp_path = path.with_suffix(".pdf.tmp")
    tmp_path.write_bytes(content)
    tmp_path.replace(path)
    return str(path)


def resolve(file_path: str) -> Path | None:
    path = Path(file_path)
    return path if path.is_file() else None
