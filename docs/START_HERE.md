# Start Here

This repository is the Phase 0/1 implementation scaffold for JOSE.

## Before opening Claude Code

1. Leave the downloaded PRD in the repository root or move it to `docs/PRD.md`.
2. Copy `.env.example` to `.env`.
3. Run `make doctor`.
4. Run `make setup`.
5. Run `make dev`.
6. In another Warp tab, run `make seed`, `make import-sources`, and `make collect-all`.

Then give Claude Code the contents of `docs/CLAUDE_CODE_MASTER_PROMPT.md`.

## What is implemented now

- Dockerized FastAPI API, worker, Next.js web application, and PostgreSQL
- Initial schema and migration
- Default development user
- Excel source import
- Source Registry endpoints
- Database-backed idempotent task queue
- Ashby, Greenhouse, Lever, and JSON-LD collectors
- Job normalization, deduplication, and version snapshots
- Dashboard, Sources, and Jobs pages
- CI workflow and cloud scheduler trigger

## What is deliberately not implemented yet

- Executive search profiles and relevance scoring
- Candidate Truth Bank
- Résumé tailoring
- Application CRM
- Playwright application assistant
- Gmail and Contacts integrations
- Production authentication
- Dedicated adapters for every VC portfolio aggregator

Those belong to the ordered backlog rather than being hidden behind pretend-complete buttons.
