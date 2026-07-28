# JOSE Phase 0/1 Backlog

Issues are ordered. Complete acceptance criteria before starting the next issue unless a dependency requires otherwise.

## Issue 00 — Validate first boot

**Goal:** Prove a new checkout starts predictably.

**Acceptance criteria:**

- `make doctor` reports prerequisites clearly.
- `make setup` creates `.env` when missing and builds all images.
- `make dev` starts PostgreSQL, API, worker, and web.
- API health endpoint succeeds.
- Dashboard renders without a build error.
- README commands match actual behavior.
- No secrets are committed.

**Scaffold status:** Partially implemented; validate on Scott's Mac.

---

## Issue 01 — Finish Source Registry CRUD

**Goal:** Manage sources without editing code or the database.

**Acceptance criteria:**

- Create, read, update, enable, disable, and delete a source.
- Validate URL, category, adapter, frequency, and priority.
- Prevent duplicate source URLs per user.
- Deleting a source requires confirmation and does not delete canonical jobs discovered elsewhere.
- UI supports editing and toggling.
- API and service tests cover user isolation.

---

## Issue 02 — Make Excel import reviewable

**Goal:** Import the supplied workbook safely and visibly.

**Acceptance criteria:**

- Import can run from CLI and UI upload.
- Preview shows records to create, update, skip, or flag.
- Section headers map to correct categories.
- Newsletters and talent networks default to disabled.
- Re-import is idempotent.
- Import report is retained.
- The original workbook is not modified.

---

## Issue 03 — Harden the collector contract

**Goal:** Give every adapter one tested, predictable interface.

**Acceptance criteria:**

- Collector results validate through a Pydantic schema.
- HTTP requests use bounded timeouts, a JOSE user agent, redirect limits, and response-size limits.
- Unsafe/private-network URLs are rejected to reduce SSRF risk.
- Rate-limit and access-denied errors are distinguishable.
- Unknown fields remain null.
- Live network calls are absent from unit tests.

---

## Issue 04 — Productionize ATS collectors

**Goal:** Reliably collect direct Ashby, Greenhouse, and Lever boards.

**Acceptance criteria:**

- Fixture tests cover empty, paginated, malformed, and changed responses.
- Collector identifies actual company rather than relying solely on source label when data permits.
- Compensation parsing is normalized without guessing.
- Publication timestamps are timezone aware.
- Jobs lacking application URLs are rejected and logged.
- Raw payload retention can be disabled by configuration.

---

## Issue 05 — Discover portfolio-board platform types

**Goal:** Determine the platform behind every VC source in the spreadsheet.

**Acceptance criteria:**

- Each VC source has a configured adapter or an explicit `unsupported` status.
- Platform detection results are stored and reviewable.
- Redirected ATS links are captured as canonical application URLs.
- Findings are documented in `docs/source-catalog.md`.
- No source is silently assigned JSON-LD when platform detection is uncertain.

---

## Issue 06 — Build the first portfolio aggregator adapter

**Goal:** Collect one high-value VC board end to end.

**Acceptance criteria:**

- Adapter supports pagination.
- Portfolio company name is captured correctly.
- Final employer application URL is stored.
- VC source relationship is retained in `job_sources`.
- Fixture tests cover duplicates and page changes.
- Access rules and terms are documented.

**Selection rule:** Choose the source with the clearest permitted structured interface and highest likely value to Scott.

---

## Issue 07 — Improve canonicalization and deduplication

**Goal:** Merge the same job found through different sources.

**Acceptance criteria:**

- Tracking parameters and benign URL differences are removed.
- ATS job IDs take precedence when available.
- Cross-source duplicates merge without losing source lineage.
- Potential fuzzy duplicates enter a review queue rather than auto-merging at low confidence.
- Merge and unmerge actions are audited.
- Tests cover company aliases and location wording differences.

---

## Issue 08 — Complete job change and removal detection

**Goal:** Accurately identify changed, removed, and reposted jobs.

**Acceptance criteria:**

- Job-source links track active and removed state.
- A job is globally removed only when no active source still lists it.
- Material field changes are identified separately from formatting changes.
- Reposts are linked to prior records when confident.
- Dashboard displays new, changed, removed, and reposted counts.
- A failed source run never marks jobs removed.

---

## Issue 09 — Harden the database-backed task queue

**Goal:** Make background work cloud-safe without adding Redis.

**Acceptance criteria:**

- Concurrent workers cannot claim the same task.
- Retries use exponential backoff with jitter.
- Stale running tasks can be recovered.
- Failed tasks enter a visible terminal state.
- Task payloads are versioned.
- Daily collection idempotency respects the user's timezone.
- Worker shutdown is graceful.

---

## Issue 10 — Source Health dashboard

**Goal:** Make failures actionable.

**Acceptance criteria:**

- Source page shows last attempt, last success, duration, counts, adapter, and error.
- User can rerun one source.
- User can inspect recent run history.
- Repeated failures are highlighted.
- A zero-result successful run is distinguishable from failure.
- Error text is sanitized for secrets.

---

## Issue 11 — Jobs review foundation

**Goal:** Provide a useful pre-scoring job workspace.

**Acceptance criteria:**

- Search and filters for company, title, source, date, location, ATS, and status.
- Job detail page shows description, source lineage, and version history.
- User can mark already applied, irrelevant, watch, or archived.
- Decisions are user-scoped and audited.
- No AI is required for this issue.

---

## Issue 12 — Cloud deployment baseline

**Goal:** Run JOSE without Scott's Mac.

**Acceptance criteria:**

- API, web, and worker images build in CI.
- Managed PostgreSQL connection works through environment configuration.
- HTTPS and production authentication protect the application.
- Scheduler queues daily collection using a secret token or platform-native identity.
- Database migrations run as a release step, not from every web replica.
- Logs and health checks are available.
- Deployment and rollback instructions are documented.
- Monthly infrastructure cost is recorded before launch.

---

## Issue 13 — Backups and recovery

**Goal:** Ensure the system can be restored.

**Acceptance criteria:**

- Automated database backups are enabled.
- Résumé/file storage backup strategy is documented.
- Restore procedure is tested in a non-production environment.
- Export command creates a user-readable data archive.
- Recovery objectives are stated.

---

## Issue 14 — Phase 1 release gate

**Goal:** Decide whether discovery is reliable enough to begin scoring.

**Acceptance criteria:**

- At least five high-value sources operate reliably.
- Scheduled cloud collection runs for seven consecutive days.
- Failed sources are visible and actionable.
- Duplicate rate and false merge rate are measured.
- New and changed jobs are correctly surfaced.
- Cost and runtime are documented.
- Scott signs off that the discovery dashboard is useful.
