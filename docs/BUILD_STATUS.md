# Build Status

**Package date:** July 28, 2026
**First boot validated:** July 28, 2026, on Scott's Mac (Issue 00)

## Verified on Scott's Mac

- Docker installed and running (Colima-managed Docker Engine, since Docker Desktop's
  Homebrew cask install requires an interactive `sudo` prompt this environment could
  not satisfy).
- `make doctor` reports all prerequisites clearly, including a clean warning when
  `.env` is absent.
- `make setup` creates `.env` from `.env.example` and builds the `api`, `worker`, and
  `web` images from a clean checkout.
- `make dev` starts PostgreSQL, the API, the worker, and the web app from zero
  volumes. Alembic runs automatically on API startup. All four containers reach a
  healthy/running state.
- `GET /health` returns `{"status":"ok","service":"jose-api"}`.
- The dashboard (`/`), Sources page, and Jobs page all render with real data
  (HTTP 200), including a working "Source health" panel that surfaces failed
  collector runs instead of hiding them.
- `make test` passes (9 backend unit tests: Ashby, Greenhouse, Lever, and JSON-LD
  fixtures; URL canonicalization; adapter detection; title normalization; fingerprint
  stability).
- `make lint` passes for both the API (`ruff`) and the web app (`eslint`).
- `make build` (Next.js production build) passes, including while `make dev` is
  running concurrently in another terminal.
- `make seed`, `make import-sources`, and `make collect-all` run end to end. The
  Excel importer correctly creates 31 sources from the workbook (969 of 1000 sheet
  rows are blank/header padding, not real sources). The worker claims and processes
  queued tasks; sources without a dedicated adapter yet fail visibly (403/406/no
  JSON-LD) rather than reporting a false zero-result success, per the PRD's
  collector-failure rule.

## Fixes applied during first-boot validation (Issue 00)

- `docs/PRD.md` created from the downloaded PRD PDF (source file preserved in place,
  one directory above the repository root).
- Nine `ruff` findings auto-fixed (import ordering, `datetime.UTC` alias) across the
  API package.
- `web/package.json`: `next` bumped `15.3.3` → `15.5.22` to resolve a critical Next.js
  CVE (CVE-2025-66478) and a long list of related advisories flagged by `npm audit`;
  `eslint-config-next` bumped to match.
- `web/eslint.config.mjs`: fixed an anonymous-default-export lint warning and added
  `next-env.d.ts` to the ignore list (Next.js's own auto-generated file was failing
  `--max-warnings=0`).
- `docker-compose.yml` / `Makefile`: `make build` was silently corrupting a
  concurrently running `make dev` web container by writing a production build into
  the same `.next` cache the dev server was using, producing a cryptic 500
  ("Cannot find module './102.js'") until the container was restarted. Fixed by
  giving the one-off build invocation its own throwaway `.next` mount
  (`docker compose run --rm -v /app/.next web npm run build`) instead of sharing the
  dev server's named volume.

## Issue 01 — Source Registry CRUD (completed July 28, 2026)

- Added `jose/services/sources.py`: `list_sources`, `get_source`, `create_source`,
  `update_source`, `delete_source`, all scoped by `user_id`. Duplicate source URLs are
  rejected per user (not globally), and deleting a source requires an explicit
  `confirm=True` flag. Jobs are never deleted when their discovering source is
  deleted — `Job` has no foreign key to `Source` (only `JobSource` link rows do, and
  those cascade), so a canonical job discovered through multiple sources survives the
  deletion of any one of them. Verified directly with a dedicated test.
- Added `SourceCategory`, `SourceAdapter`, and `CollectionFrequency` enums in
  `jose/schemas.py`, plus a `SourceUpdate` schema for partial updates. Priority is
  bounded 1–1000.
- New API routes: `GET/PATCH/DELETE /api/v1/sources/{id}` (existing `GET`/`POST
  /api/v1/sources` now delegate to the service layer instead of embedding queries in
  the route handlers).
- 23 new backend tests (15 service-level incl. two-user isolation and the
  jobs-survive-source-deletion case; 8 API-level incl. validation, duplicate, and
  confirmation-required status codes). Full suite: 32 passed.
- Web: `/sources` now supports adding a source, inline editing, enable/disable
  toggling, and delete-with-confirmation, via a new client component
  (`components/source-manager.tsx`). Verified via `tsc --noEmit`, `eslint`, and a
  full manual CRUD pass against the live API matching the exact request shapes the
  UI sends. The Chrome browser extension was not connected this session, so the
  click-through UI itself was not visually exercised — only its underlying API calls
  and static server-rendered markup were verified.
- **Found and fixed a real local-dev bug while testing this**: `uvicorn --reload`
  was not picking up backend file edits at all inside the Colima-backed container —
  WatchFiles' default OS file-event watcher doesn't fire reliably across Colima's
  virtualized bind mount. Fixed by setting `WATCHFILES_FORCE_POLLING=true` on the
  `api` service in `docker-compose.yml`; confirmed a live file touch now triggers an
  automatic reload.
- **Found and fixed a second gap**: `make test` did not run Alembic migrations first
  (unlike the GitHub Actions CI job, which does), so it only worked because a prior
  `make dev` had already migrated the shared database. Fixed by changing the `test`
  target to run `alembic upgrade head && pytest`; confirmed against a fully fresh
  `docker compose down -v` state.

## Issue 02 — Make Excel import reviewable (completed July 28, 2026)

- Rewrote `jose/services/source_import.py` around a classify → apply split:
  `classify_workbook` (pure, read-only against the DB — checks for existing sources
  by URL but never writes) returns one `ImportRowOutcome` per row with an action of
  `create`, `update`, `skip`, or `flag`. `commit_import` runs classification, applies
  the create/update writes, and persists a report. Rows are flagged (not silently
  defaulted) when the same URL repeats within one workbook, or when a URL appears
  before any recognized section header — the pre-existing code silently assigned
  `user_added` in that second case.
- Added `SourceImportRun` model + migration `0002_source_import_runs` (report
  retention): filename, created/updated/skipped/flagged counts, and the flagged rows'
  detail, scoped by `user_id`.
- **Fixed a real idempotency gap while writing the update path**: the previous
  importer reset a source's `enabled` flag to the category default on every
  re-import, which would have silently undone any manual enable/disable toggle made
  through the Issue 01 UI. `enabled` is now set only at creation; re-imports never
  touch it again. Covered by a dedicated test.
- New API routes: `POST /api/v1/sources/import/preview` (multipart upload, dry-run,
  zero DB writes — verified with a dedicated test), `POST
  /api/v1/sources/import/commit` (multipart upload, commits and returns the
  retained report), `GET /api/v1/sources/import/runs` (list retained reports).
- CLI: `jose.cli import-sources` gained a `--preview` flag for the same dry-run
  behavior from the command line; the committing path now goes through
  `commit_import` and retains a report like the UI does.
- Web: new `/sources/import` page (`components/import-manager.tsx`) — file upload,
  a preview table (counts + per-row action/reason for every non-skip row), a
  "Confirm import" step, and a "Past imports" table backed by the retained reports.
  Linked from `/sources`.
- 12 new backend tests (10 service-level, 2 API-level). Full suite: 44 passed.
  Manually verified end to end against the real `VC_Job_Search_Resources.xlsx`
  workbook via CLI and via direct multipart upload to the API (same request shape
  the UI sends): preview writes nothing, commit is idempotent on rerun (0 created,
  31 updated), and the workbook's SHA-256/mtime are unchanged throughout.
- **Found and fixed a second file-watching gap**: the same class of bug from Issue
  01 (Colima's virtualized bind mount not firing filesystem events) also affected
  the Next.js dev server — new files under `web/app/` were not detected at all
  (confirmed: a new page 404'd until the container was manually recreated). Fixed
  by setting `WATCHPACK_POLLING=true` on the `web` service in `docker-compose.yml`;
  confirmed a live file touch now triggers an automatic recompile.
- Verified via `tsc --noEmit`, `eslint`, `next build` (including while `make dev`
  runs concurrently), and a full fresh-boot pass (`docker compose down -v` → `make
  dev` → `make seed` → `make import-sources`) exercising both new migrations in
  order. The Chrome extension was not connected this session, so the click-through
  UI itself was not visually exercised — only its underlying API calls and
  server-rendered markup were verified.

## Known residual items (not boot blockers)

- `npm audit` still reports high-severity advisories in `eslint`'s own transitive
  dependencies (`brace-expansion`/`minimatch`) and in `postcss`/`sharp` versions
  bundled by the current Next.js release line. These are dev-tooling/build-time only;
  the only fix `npm audit fix --force` offers is downgrading `next` to `9.3.3`, which
  would be a regression. Revisit when upstream ships a clean fix.
- Docker on this machine runs via Colima rather than Docker Desktop, because the
  Homebrew cask install requires an interactive `sudo` prompt that a non-interactive
  session cannot satisfy. Functionally equivalent for `docker`/`docker compose`.
