# JOSE — Job Opportunity Search Engine

JOSE is a cloud-ready, human-approved executive job-search operating system. This starter repository implements the Phase 0/1 foundation: PostgreSQL, FastAPI, a database-backed worker, source import, initial ATS collectors, a Next.js dashboard, Docker Compose, migrations, tests, and CI.

## What works in this scaffold

- Local development through Docker Compose
- Cloud-portable containers
- PostgreSQL schema and Alembic migration
- Default-user seeding
- Import of `VC_Job_Search_Resources.xlsx`
- Source Registry API
- Database-backed task queue
- Ashby public job-board collector
- Greenhouse public job-board collector
- Lever public postings collector
- JSON-LD `JobPosting` collector
- Job normalization, fingerprinting, deduplication, and version history
- Source-run health records
- Minimal Next.js dashboard
- GitHub Actions CI and scheduled collection trigger

Portfolio aggregators such as a16z, Index, General Catalyst, and similar boards are imported as sources but intentionally marked for dedicated adapters. A source failure is stored as a failure; it is never treated as “zero jobs.”

## Install into Scott's folder

Your target folder contains a space, so keep the quotes:

```bash
cd "$HOME/Desktop/Jose desktop/jose"
unzip -n "$HOME/Downloads/JOSE-starter.zip"
cp .env.example .env
```

The `-n` flag prevents the archive from overwriting a PRD file you already placed in the directory.

The recommended PRD location is:

```text
docs/PRD.md
```

You may leave the downloaded PRD in the repository root initially. Claude Code is instructed to locate it there when `docs/PRD.md` is absent.

## Start JOSE

Prerequisites:

- Docker Desktop
- Git
- Warp, Terminal, or another shell

```bash
cd "$HOME/Desktop/Jose desktop/jose"
make setup
make dev
```

Then open:

- Dashboard: http://localhost:3000
- API documentation: http://localhost:8000/docs
- Health check: http://localhost:8000/health

In a second Warp tab:

```bash
cd "$HOME/Desktop/Jose desktop/jose"
make seed
make import-sources
make collect-all
```

The worker will process queued collection tasks. Sources requiring a dedicated portfolio-board adapter will fail visibly on the Source Health screen instead of silently disappearing. Several VC aggregators are expected to remain unsupported until the dedicated Phase 1 adapter issues are completed.

## Useful commands

```bash
make dev
make down
make logs
make test
make lint
make migrate
make seed
make import-sources
make collect-all
```

The Python CLI is also available directly inside the API container:

```bash
docker compose run --rm api python -m jose.cli --help
```

## Cloud path

The same images can run on any container host. The lowest-friction early deployment is:

1. Managed PostgreSQL
2. One web container
3. One API container
4. One worker container
5. A scheduler that calls `POST /api/v1/admin/collect-all`

The repository includes a GitHub Actions scheduled workflow. Set these repository secrets after deployment:

- `JOSE_API_URL`
- `JOSE_SCHEDULER_TOKEN`

The workflow calls the cloud API and merely queues work; the worker performs the collection.

## Development workflow with Claude Code and Codex

1. Read `docs/PRD.md`.
2. Read `CLAUDE.md` or `AGENTS.md`.
3. Read `docs/CLAUDE_CODE_MASTER_PROMPT.md`.
4. Pick the next issue from `docs/backlog/PHASE_0_1_BACKLOG.md`.
5. Make one vertical, tested change.
6. Run `make test` and `make lint` before committing.

## Security note

This scaffold is a development foundation. Before exposing it publicly, complete the authentication, secret management, HTTPS, token encryption, rate limiting, and production hardening issues in the backlog.


## Initialize version control

After the first successful boot:

```bash
cd "$HOME/Desktop/Jose desktop/jose"
git init
git add .
git commit -m "Initialize JOSE Phase 0/1 scaffold"
```

## Validation status

Read `docs/BUILD_STATUS.md`. Backend unit tests were executed successfully. Docker and the Next.js dependency build must be validated on your Mac because the artifact environment did not provide those runtimes.
