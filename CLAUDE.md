# CLAUDE.md — JOSE Engineering Instructions

## Mission

Build JOSE, a selective and human-controlled executive job-search operating system. Read `docs/PRD.md` first. If it is missing, locate Scott's downloaded JOSE PRD in the repository root and use that file; copy a machine-readable version to `docs/PRD.md` when practical without deleting the original.

## Non-negotiable product rules

1. Never submit an application without explicit user approval.
2. Never send an external message without explicit user approval.
3. Never invent career facts, dates, metrics, titles, employers, compensation, work authorization, or personal information.
4. Unknown information remains unknown.
5. A failed collector is a failure, never a successful zero-result run.
6. Apply deterministic filters before paid AI calls.
7. Every user-owned record includes `user_id`.
8. Long-running work belongs in a worker task, not an HTTP request.
9. Every task must be idempotent and safely retryable.
10. The local and cloud versions must use the same code and containers.
11. Do not automate LinkedIn scraping, messaging, or connection requests.
12. Do not bypass CAPTCHA, MFA, rate limits, robots restrictions, or security controls.

## Architecture

- Python 3.12
- FastAPI API
- SQLAlchemy 2.x declarative models
- Alembic migrations
- PostgreSQL
- Database-backed task queue for MVP
- Next.js App Router frontend
- Separate worker process
- Future Playwright browser worker in its own container
- Environment-based configuration
- Docker Compose locally

## Working rules

- Make the smallest coherent vertical change.
- Add or update tests with every behavior change.
- Use typed Pydantic schemas at API boundaries.
- Use timezone-aware UTC datetimes.
- Use UUID primary keys.
- Do not put business logic in route handlers.
- Do not log secrets, résumés, email bodies, browser cookies, or OAuth tokens.
- Preserve source payloads only when needed for debugging and keep them user-scoped.
- Keep adapters isolated behind `BaseCollector`.
- Use fixtures for collector tests. Do not make live internet calls in unit tests.
- Add a migration whenever the persisted schema changes.
- Update relevant documentation and backlog acceptance criteria.

## Definition of done

A task is complete only when:

- Acceptance criteria are met.
- Unit tests pass.
- Relevant integration tests pass.
- Ruff passes for Python.
- Next.js lint/build passes when frontend code changes.
- Database changes include migrations.
- Error paths are handled.
- No unsupported claim or hidden automation is introduced.

## Initial commands

```bash
cp .env.example .env
make dev
make seed
make import-sources
make test
```

## Before changing architecture

Explain the proposed change, the problem it solves, cost impact, cloud impact, and migration path. Prefer boring, inexpensive infrastructure until actual load demonstrates a need for more.
