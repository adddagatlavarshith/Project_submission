Bulk Certificate Generator
A small FastAPI service for generating certificates in bulk. You send it a list of recipients in one request, and it creates a PDF certificate for each of them in the background. You can check how the job is going and download the certificates when they're ready.

Built with FastAPI, SQLAlchemy (SQLite by default) and ReportLab for the PDFs.

Sample certificate

Setup
You need Python 3.10 or newer.

git clone https://github.com/adddagatlavarshith/Project_submission.git
cd Project_submission
python -m venv .venv
source .venv/bin/activate      # on Windows: .venv\Scripts\activate
pip install -r requirements.txt
Run
uvicorn app.main:app --reload
The API runs at http://127.0.0.1:8000. Swagger docs are at http://127.0.0.1:8000/docs, which is the easiest way to try it out. The database tables get created automatically on startup.

Some settings can be changed with environment variables: DATABASE_URL, STORAGE_DIR, MAX_RECIPIENTS and WORKER_THREADS. See app/config.py for the defaults.

Tests
pytest
The tests cover creating jobs, validation, PDF generation, job status, handling a failed certificate, and downloading results.

Usage
1. Submit a job

curl -X POST http://127.0.0.1:8000/api/v1/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "course_name": "Introduction to Python",
    "issuer": "Acme Academy",
    "issue_date": "2026-10-01",
    "recipients": [
      {"name": "Ada Lovelace", "email": "ada@example.com"},
      {"name": "Alan Turing"},
      {"name": "", "email": "bad-email"}
    ]
  }'
You get back 202 Accepted with a job id. Generation then carries on in the background.

2. Check the status

curl http://127.0.0.1:8000/api/v1/jobs/<job_id>
This shows the job status (pending, processing, completed, completed_with_errors or failed), a count of certificates in each state, and a progress percentage.

3. See results per recipient

curl http://127.0.0.1:8000/api/v1/jobs/<job_id>/certificates
curl "http://127.0.0.1:8000/api/v1/jobs/<job_id>/certificates?status=failed"
Each recipient comes back with a status (generated, failed or invalid). Failed and invalid ones include an error message, and generated ones include a download link.

4. Download certificates

# a single certificate
curl -o cert.pdf http://127.0.0.1:8000/api/v1/certificates/<certificate_id>/download

# all certificates in a job, as a zip
curl -o certs.zip http://127.0.0.1:8000/api/v1/jobs/<job_id>/download
There's also POST /api/v1/jobs/<job_id>/retry, which retries only the certificates that failed.

Design decisions
Background processing. A request can have thousands of recipients, so the API doesn't generate the PDFs while the request is open. It saves the job and returns straight away, and a thread pool does the work. I picked a plain thread pool over Celery to avoid needing Redis. All job dispatching goes through app/worker.py, so switching to Celery later would be easy.
Validation happens at two levels. If the request itself is broken (missing course name, empty list, too many recipients), it's rejected with a 422. A bad individual recipient doesn't reject the whole batch. It's marked invalid with the reason, and everyone else still gets a certificate.
One failure doesn't stop the job. Each certificate is generated in its own try/except. If one fails, it's marked failed with the error and the loop moves on to the next.
Progress is stored in the database. Each recipient is a row with its own status, and progress is calculated from those rows. If the app restarts mid-job, it picks unfinished jobs back up on startup and only processes certificates still pending, so nothing gets generated twice.
Storage. PDFs are saved to disk under storage/<job_id>/. All file handling is in app/storage.py, so it could be swapped for S3 without touching the rest of the code.
What I'd improve next
Run a separate worker (e.g. Celery) instead of processing jobs inside the API process
Store the PDFs in S3 instead of on local disk
Add authentication
Add an endpoint to verify a certificate using its verification code