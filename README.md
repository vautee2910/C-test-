# Open-source Research Platform (Scaffold)

This repository bootstraps the open-source, low-cost stack described in `open_source_stack_plan.md`.

## What's included
- **FastAPI** service with health/version endpoints.
- **Celery** worker and beat scheduler with stub tasks for ingestion and reporting jobs.
- **Postgres**, **Redis**, and **MinIO** services wired through Docker Compose.

## Quick start

```bash
docker compose up --build
```

Then visit:
- `http://localhost:8000/health`
- `http://localhost:8000/version`

## Service layout
- `backend/app/main.py`: FastAPI app entrypoint.
- `backend/app/tasks.py`: Celery app and scheduled task placeholders.
- `docker-compose.yml`: local dev stack.

## Next steps
- Implement data models and persistence.
- Add ingestion connectors, chunking, and vectorization modules.
- Wire report generation, alert rules, and approvals.
