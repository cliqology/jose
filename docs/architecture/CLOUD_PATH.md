# Cloud Deployment Path

JOSE is designed to move from a laptop to the cloud without changing application code.

## Local topology

- `web`: Next.js container
- `api`: FastAPI container
- `worker`: the same Python image running the worker command
- `db`: PostgreSQL container
- Local bind mounts for source files and development code

## Initial cloud topology

- Managed PostgreSQL database
- One web service/container
- One API service/container
- One worker service/container
- One scheduled trigger that calls the queue endpoint
- S3-compatible object storage when document handling begins

The scheduler only queues work. The worker executes it. This prevents scheduler time limits from truncating collection runs.

## Environment boundaries

Use separate environment variables and databases for:

- Development
- Staging
- Production

Never connect local development directly to the production database.

## Deployment order

1. Provision managed PostgreSQL.
2. Create staging environment.
3. Store secrets in the host's secret manager.
4. Run Alembic migrations as a release task.
5. Deploy API.
6. Deploy worker.
7. Deploy web.
8. Verify health checks.
9. Add scheduler.
10. Validate one manual source run.
11. Enable daily collection.

## Production changes required before public exposure

- Replace development-user fixture with real authentication.
- Restrict CORS to the production web origin.
- Rotate scheduler token.
- Add request rate limiting.
- Encrypt OAuth and browser credentials.
- Configure HTTPS.
- Configure database backups.
- Add error monitoring with content redaction.
- Remove source-code bind mounts.
- Use production container commands without hot reload.

## Scale path

Do not introduce extra infrastructure prematurely.

- One worker can process Phase 1 volume.
- Add worker replicas when queue latency demonstrates a need.
- Add Redis or a managed queue only if database polling becomes a measured bottleneck.
- Split browser workers from collection workers when Playwright is introduced.
