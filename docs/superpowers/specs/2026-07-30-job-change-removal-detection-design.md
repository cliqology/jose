# Design: Complete Job Change and Removal Detection (Issue 08)

## Goal

Accurately identify changed, removed, and reposted jobs, per
`docs/backlog/PHASE_0_1_BACKLOG.md` Issue 08:

- Job-source links track active and removed state.
- A job is globally removed only when no active source still lists it.
- Material field changes are identified separately from formatting changes.
- Reposts are linked to prior records when confident.
- Dashboard displays new, changed, removed, and reposted counts.
- A failed source run never marks jobs removed.

## Context and motivation

Today (`backend/jose/services/collection.py`, `backend/jose/models/core.py`) `Job.status`
only ever takes the values `"active"` and `"merged"` (introduced by Issue 07). `Job` has a
`removed_at` column but nothing ever sets it to a non-null value — it exists only as a
target for clearing back to `None` when a job reappears. `JobSource` has no active/inactive
concept at all: `_upsert_job` bumps `last_seen_at` on a link whenever a source's run finds
the job again, but nothing ever notices when a run *stops* finding it. There is no removal
detection, no material-vs-formatting change distinction (every content difference, however
trivial, is treated identically), and no repost linking. This design adds all three, reusing
the fuzzy-matching and audit patterns Issue 07 already established.

## Job-source active/removed tracking

**Schema:** `JobSource` gains `is_active: bool` (default `True`) and
`removed_at: datetime | None`.

**Per-run sweep**, added to `collect_source` (`backend/jose/services/collection.py`), success
path only:

1. `_upsert_job` already touches every `JobSource` link a run's items map to. Extend it so
   that touch also sets `is_active = True, removed_at = None` on that link. If the link had
   been inactive, this is a per-source revival: also flip the parent `Job` back to
   `status = "active", removed_at = None` if it had gone globally removed (see below).
2. After all of a run's items are processed (i.e. only when the run is about to be marked
   `"success"`), sweep: select this source's `JobSource` rows where `is_active = True` and
   `last_seen_at` is older than the run's `started_at` (i.e. not touched this run) → set
   `is_active = False, removed_at = now()`.
3. For every distinct `Job` touched in step 2, check whether it now has zero
   `is_active = True` links across *all* its `JobSource` rows (not just this source's). If
   so, set `Job.status = "removed", Job.removed_at = now()`.

Because the sweep only runs inside the `try` block that leads to `run.status = "success"`,
an exception anywhere in collection (caught by the existing `except Exception` in
`collect_source`, which already rolls back and marks the run `"failed"`) leaves all
`JobSource`/`Job` removal state untouched — satisfying "a failed source run never marks
jobs removed" for free from the existing success/failure branching, no new guard needed.

**Removal timing:** immediate — a job-source link goes inactive the first time a *successful*
run of that source omits it, no grace period across multiple runs. Issues 03/04 already
hardened collectors to fail loudly (raise, not return a truncated success) on malformed or
partial responses, so a clean successful run that omits a previously-seen job is trustworthy
signal, not noise.

**Disabled sources:** a disabled source simply never runs, so its `JobSource` links are never
swept — they freeze in whatever state they were last in. This is an intentional consequence
of the sweep only happening inside a run of that specific source, not a special case to code
for separately.

## Material vs. formatting change classification

**Schema:** `JobVersion` gains `is_material: bool` (default `True`; existing rows have no
prior version to diff against, so backfilling `True` is the conservative choice — it never
hides a change that already happened, it just may over-count history predating this
migration).

`content_hash` (the existing full-snapshot hash) is unchanged — it still governs whether a
new `JobVersion` row is written at all, preserving every raw change for debugging per
CLAUDE.md's payload-retention guidance.

A second hash, `material_hash`, is computed in `_upsert_job` over exactly:
`title`, `location`, `remote_type`, `employment_type`, `compensation_min`,
`compensation_max`, `currency`, `department`, `canonical_url`, and
`html_to_text(description_html) or normalize_whitespace(description_text)` (reusing the
existing `html_to_text`/`normalize_whitespace` helpers in `collectors/utils.py`, which already
strip tags and collapse whitespace — this is what makes a pure markup/whitespace edit to the
description hash identically before and after).

When `content_hash` changes and a new `JobVersion` is written, set
`JobVersion.is_material = (new material_hash != previous material_hash)`, where "previous"
is the material_hash of the job's immediately preceding version (recomputed from the prior
`Job` field values before they're overwritten, not a stored column on `Job` — keeping the
comparison a pure function of two snapshots rather than adding more mutable job state).

`SourceRun.jobs_updated` keeps its current meaning (any content change, material or not) —
it is a source-health signal, not a user-facing change feed. The dashboard's "changed" count
(below) is the only consumer of `is_material`.

## Repost linking

**Schema:** `Job` gains `reposted_from_job_id: UUID | None` (FK to `jobs.id`,
`ondelete=SET NULL`, matching the existing `merged_into_job_id` FK style).

In `_upsert_job`, when Tier 0 (fingerprint) and Tier 1 (ATS id) both miss and Tier 2's
active-job fuzzy search (existing, `_find_fuzzy_candidate`, unchanged) also misses — i.e. a
brand-new `Job` is about to be created — run one more fuzzy search, identical scoring
(`fuzzy_match_score`, same `COMPANY_ALIAS_THRESHOLD`/`TITLE_MATCH_THRESHOLD`/
`FUZZY_MATCH_THRESHOLD` constants) but scoped to `Job.status == "removed"` instead of
`"active"`. On a match clearing `FUZZY_MATCH_THRESHOLD`, set the new job's
`reposted_from_job_id` to the best-scoring removed job's id — no `JobMergeCandidate` row,
no review queue.

This is deliberately auto-linked rather than routed through manual review: unlike an
active-duplicate merge (which collapses two currently-visible records and risks hiding a
real distinct posting), a repost link is purely additive lineage between two records that
both remain independently visible. A wrong link is a cosmetic mislabel, not a data-loss risk,
so it doesn't need the same human gate Issue 07 put in front of active-duplicate merges.

An active job is never a repost-link source (that path is Issue 07's existing merge-candidate
queue) — the two fuzzy searches are mutually exclusive by construction (`status == "active"`
vs `status == "removed"`), so a given upsert can trigger at most one of them.

## Dashboard

`DashboardSummary` (`schemas.py`) and `get_dashboard_summary`
(`services/dashboard.py`) gain four fields, all using the same rolling-24h `since` window
already used by the existing `jobs_seen_last_24h`:

- `jobs_new_last_24h` — `Job.first_seen_at >= since` (same query `jobs_seen_last_24h`
  already runs; `jobs_seen_last_24h` is kept as-is for API stability and `jobs_new_last_24h`
  is added as the more clearly-named field for this issue's UI).
- `jobs_changed_last_24h` — count of distinct `Job.id` with a `JobVersion` where
  `is_material = True` and `seen_at >= since`.
- `jobs_removed_last_24h` — `Job.status == "removed"` and `Job.removed_at >= since`.
- `jobs_reposted_last_24h` — `Job.reposted_from_job_id is not null` and
  `Job.first_seen_at >= since`.

## API surface

`list_jobs` (`api/routes/jobs.py`) currently filters out only `status == "merged"`. Removed
jobs stay in the default listing (a user should see a job just disappeared, not have it
silently vanish from the page) — no filter change needed, just widening what `status` values
mean. The per-job response dict gains `reposted_from_job_id`. No new schema-level enum change
beyond documenting `"removed"` as a third valid `Job.status` value alongside `"active"`/
`"merged"`.

No new page or route is added. The existing Jobs page and dashboard are sufficient surfaces
for this issue; a richer review workspace (filtering by removed/changed/reposted, lineage
drill-down) is Issue 11's scope.

## Data model changes (migration `0006_job_change_removal_detection`)

- `job_sources.is_active` — `Boolean`, default `True`, not null.
- `job_sources.removed_at` — `DateTime(timezone=True)`, nullable.
- `jobs.reposted_from_job_id` — `UUID`, nullable, FK `jobs.id` `ondelete=SET NULL`, indexed.
- `job_versions.is_material` — `Boolean`, default `True`, not null.

No changes to existing unique constraints or indexes.

## Testing plan

Fixture/unit tests only, no live network calls, extending
`backend/tests/test_collection_service.py` and a new
`backend/tests/test_job_change_removal.py` (service-level, constructing `CollectedJob`
instances directly, matching `test_job_dedup.py`'s existing pattern):

- **Link goes inactive:** a job present in run 1 of a source is absent from run 2 (same
  source, both successful) → that `JobSource` link's `is_active` flips `False` with
  `removed_at` set; the `Job` stays `"active"` if a second source still lists it.
- **Job goes globally removed:** a job with exactly one source link, absent from that
  source's next successful run → `Job.status == "removed"`, `Job.removed_at` set.
- **Failed run changes nothing:** a source run that raises leaves every `JobSource.is_active`
  and every `Job.status` exactly as before the run.
- **Revival:** a removed job's fingerprint reappears in a later successful run (same or a
  different source that previously listed it) → `Job.status` back to `"active"`,
  `Job.removed_at` cleared, and the specific `JobSource` link reactivated.
- **Material change:** a compensation or title change between two runs produces a new
  `JobVersion` with `is_material = True`.
- **Formatting-only change:** a description edit that only changes HTML markup/whitespace
  (same visible text) produces a new `JobVersion` (different `content_hash`) but
  `is_material = False`.
- **Repost linked:** a removed job's company/title/location fuzzy-matches a new job posted
  under a new `external_job_id` at/above `FUZZY_MATCH_THRESHOLD` → new job's
  `reposted_from_job_id` set to the removed job's id.
- **Repost below threshold:** same setup but similarity below threshold → new job created
  with `reposted_from_job_id = None`, same as any unrelated new job.
- **Active jobs never repost-source:** a fuzzy match against a still-`"active"` job never
  sets `reposted_from_job_id` (falls through to the existing Issue 07 merge-candidate path
  instead, unchanged).
- **Dashboard counts:** each of the four new `DashboardSummary` fields computed correctly
  against seeded fixtures spanning the 24h window boundary.
- **User isolation:** removal, repost-linking, and dashboard counts are all scoped by
  `user_id`, matching the existing two-user isolation test pattern
  (`test_sources_service.py`, `test_job_dedup.py`).

## Out of scope

- A dedicated removed/changed/reposted review UI beyond the existing Jobs page and
  dashboard counts — Issue 11's broader jobs-review workspace.
- AI/embedding-based description-change classification — CLAUDE.md rule 6 requires
  deterministic filters before paid AI calls; normalized-text hash comparison is sufficient
  and keeps this fully unit-testable with fixtures.
- A grace period / multi-run confirmation before marking a link removed — immediate removal
  on one successful run's omission is accurate enough given Issues 03/04's collector
  hardening, and adds no new failure mode to reason about.
- Notifications (email/etc.) on removal or repost — not requested by the backlog acceptance
  criteria for this issue.
