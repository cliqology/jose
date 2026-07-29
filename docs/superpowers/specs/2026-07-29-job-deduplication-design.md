# Design: Improve Canonicalization and Deduplication (Issue 07)

## Goal

Merge the same job found through different sources, per `docs/backlog/PHASE_0_1_BACKLOG.md` Issue 07:

- Tracking parameters and benign URL differences are removed.
- ATS job IDs take precedence when available.
- Cross-source duplicates merge without losing source lineage.
- Potential fuzzy duplicates enter a review queue rather than auto-merging at low confidence.
- Merge and unmerge actions are audited.
- Tests cover company aliases and location wording differences.

## Context and motivation

This is forward-looking hardening, not a response to an observed bug. Today only two
sources exist (OpenAI via Ashby, Anthropic via Greenhouse) with no company overlap, so no
real duplicate jobs exist yet. The goal is to have solid dedup in place before Issue 06
adds more hand-picked companies and before any future VC-aggregator source risks
overlapping with a direct-company source for the same underlying job.

Current behavior (`backend/jose/services/collection.py::_upsert_job`,
`backend/jose/collectors/utils.py::job_fingerprint`): every collected job is reduced to a
single SHA-256 fingerprint over `(normalized company, normalized title, normalized
location, canonicalized application URL, external ATS job id)`. `canonicalize_url`
already lowercases scheme/host, strips `utm_*` query params, and drops the fragment — this
covers "tracking parameters and benign URL differences" and is not changed by this design.
A job matches an existing row only on an **exact** fingerprint match; any difference in any
one field (e.g. title casing after normalization still differs, or a company name is
written two different ways by two different collectors) silently creates a second `Job`
row with no signal that anything went wrong. There is no fuzzy matching, no review queue,
and no merge/unmerge concept anywhere in the codebase today.

## Matching algorithm

`_upsert_job` gains two new tiers, each attempted only if the previous misses. Tier 0 is
today's existing behavior, unchanged.

### Tier 0 — exact fingerprint (existing, unchanged)

Exact fingerprint match on `(company, title, location, url, external_id)` → update the
existing `Job` in place, as today.

### Tier 1 — ATS job ID match (new, deterministic, auto-merge)

If the incoming item has both `ats_type` and `external_job_id`, look up an existing active
`Job` for the same `user_id` with the same `ats_type` and `external_job_id`, regardless of
whether title/location/company text differs. An ATS-issued ID is stronger evidence of
"same posting" than any text field — this is what "ATS job IDs take precedence" means. On a
hit, treat it exactly like a Tier 0 update: overwrite all fields including recomputing
`fingerprint` and `content_hash` from the new data, add a new `JobVersion` if the content
changed, and update/insert the `JobSource` link as today.

Edge case: recomputing `fingerprint` on a Tier 1 hit could theoretically collide with an
unrelated job's existing fingerprint (extremely unlikely — would require two different ATS
postings to normalize to an identical company+title+location+url+external_id tuple, which
by construction is a different `external_job_id` than the one that got us into Tier 1 in
the first place, so a collision is only possible via a hash collision, not a logical one).
No special handling needed beyond letting the unique constraint raise if it ever happens;
this is not a realistic case to design around (YAGNI).

### Tier 2 — fuzzy match (new, review queue, no auto-merge)

Only reached when Tier 0 and Tier 1 both miss and we are about to create a brand-new `Job`.

**Candidate search:** among existing active jobs for the same `user_id`, find those whose
`Company.name` has a `difflib.SequenceMatcher(None, a, b).ratio()` similarity to the
incoming `company_name` at or above `COMPANY_ALIAS_THRESHOLD`. This is deliberately a
string-similarity match on the *name*, not a requirement that `company_id` be identical —
it is what catches "OpenAI" vs "OpenAI, Inc." even though `Company` de-aliasing (merging
those into one `Company` row) is a separate concern this design does not touch. Using
`difflib` from the standard library avoids adding a new dependency (e.g. `rapidfuzz`) for a
need this simple, consistent with CLAUDE.md's preference for boring, inexpensive
infrastructure.

**Scoring:** for each candidate in that set, compute a weighted composite:

```
score = 0.5 * company_similarity + 0.4 * title_similarity + 0.1 * location_similarity
```

using `difflib` ratios on the normalized (`normalize_name`/`normalize_title`) forms of each
field. Title is weighted heavily because two postings at the same company with genuinely
different titles are usually genuinely different roles — the wording noise we need to
absorb there is small (e.g. punctuation, stray whitespace already handled by
`normalize_title`). Location is weighted lightly because it varies the most for the same
underlying job ("San Francisco, CA" vs "SF, CA, US" vs "San Francisco, California") and
should not gate a match on its own, but also should not be strong enough by itself to
force a match between two otherwise-unrelated jobs.

**Decision:** if `score >= FUZZY_MATCH_THRESHOLD`:
1. Create the new `Job` normally (Tier 0's create path, unchanged) — a fuzzy match never
   blocks or hides a newly collected job. Per CLAUDE.md rule 5, we always record what a
   collector actually saw.
2. Additionally insert a `JobMergeCandidate` row (`job_id` = the new job, `candidate_job_id`
   = the best-scoring existing match, `similarity_score`, `matched_signals` = the three
   component scores as JSON) with `status = "pending"`.

If multiple existing jobs clear the threshold, only the single highest-scoring one becomes
the candidate pair (one candidate row per new job, not one per match) — keeps the review
queue to one decision per new job rather than a combinatorial fan-out.

`COMPANY_ALIAS_THRESHOLD` and `FUZZY_MATCH_THRESHOLD` are named constants in
`collectors/utils.py`, tuned against the alias/wording fixtures in the testing plan below
(starting points: `COMPANY_ALIAS_THRESHOLD = 0.82`, `FUZZY_MATCH_THRESHOLD = 0.85` — exact
values finalized against real test cases during implementation, not treated as load-bearing
now).

**Avoiding repeat proposals:** before creating a new `JobMergeCandidate`, check whether a
`JobMergeCandidate` already exists for this exact `(job_id, candidate_job_id)` pair
(in either order) with `status != "pending"` (i.e. already `dismissed` or `merged`) — if so,
skip creating a new one. A dismissed pair should not resurface on the next collection run
just because the same two jobs are still around and still similar.

## Data model changes

Migration adds:

- **`jobs.merged_into_job_id`** — nullable `UUID` FK to `jobs.id`, `ondelete=SET NULL`.
  When a job is merged away it keeps its row (nothing is deleted, preserving history) but
  gains `status = "merged"` and this column points at the surviving job.
- **New table `job_merge_candidates`** (`UUIDPrimaryKeyMixin`, `TimestampMixin`,
  `UserOwnedMixin`, matching the existing model conventions in `models/core.py`):
  - `job_id`, `candidate_job_id` — FKs to `jobs.id`, `ondelete=CASCADE`.
  - `similarity_score: float`
  - `matched_signals: JSONB` — `{"company": 0.9, "title": 0.95, "location": 0.4}`
  - `status: str` — `"pending" | "merged" | "dismissed"`, indexed with `user_id` for the
    queue listing query.
  - `resolved_at: datetime | None`
  - `kept_job_id: uuid | None`, `merged_job_id: uuid | None` — set at resolution; which of
    the pair survived vs. got merged away (the reviewer picks either job as primary, it is
    not always `job_id`).
  - `moved_job_source_ids: JSONB` (list of UUIDs), `moved_job_version_ids: JSONB` (list of
    UUIDs) — recorded at merge time, listing exactly which `JobSource`/`JobVersion` rows had
    their `job_id` reassigned. This is what makes unmerge exact: it only reverses what this
    specific merge moved, not anything collected against the surviving job afterward.

`Job.status` is currently a free-text `String(50)` column (no DB-level enum). This design
adds a `JobStatus` `StrEnum` in `schemas.py` (`ACTIVE = "active"`, `MERGED = "merged"`) for
API-layer validation, without constraining the column itself — consistent with how
`SourceCategory`/`SourceAdapter` are handled today (enum at the Pydantic boundary, plain
string in the DB).

`SystemEvent` (defined in `models/core.py`, currently unused anywhere in the codebase) gets
its first real use here: one row per merge (`event_type="job_merged"`) and per unmerge
(`event_type="job_unmerged"`), each with `entity_type="job"`, `entity_id` = the kept job's
id, and `data` capturing the merge candidate id, both job ids, and who/when. This satisfies
"merge and unmerge actions are audited" using the existing audit-log model rather than
inventing a new one.

## Merge / unmerge mechanics

Implemented as `backend/jose/services/job_merge.py` (new module, mirroring the
`services/sources.py` pattern — service layer holds the logic, routes stay thin per
CLAUDE.md's "no business logic in route handlers"):

**`resolve_merge_candidate(session, user_id, candidate_id, action, keep)`**

- `action = "dismiss"`: set `status = "dismissed"`, `resolved_at = now`. No job data
  changes.
- `action = "merge"`: `keep` (`"job"` or `"candidate"`) picks which of `job_id`/
  `candidate_job_id` survives. For the other one (the "merged-away" job):
  1. Reassign its `JobSource` rows to the surviving job — except any that would collide
     with the unique constraint `(user_id, job_id, source_id)` because the survivor already
     has a link to that same `Source`; in that case keep whichever of the two links has the
     more recent `last_seen_at` and drop the other (its lineage is not lost — the survivor
     already recorded that source).
  2. Reassign its `JobVersion` rows to the surviving job — except any colliding with
     `(job_id, content_hash)` for the same reason (identical content already recorded).
  3. Record the ids actually moved into `moved_job_source_ids`/`moved_job_version_ids`.
  4. Set the merged-away job's `status = "merged"`, `merged_into_job_id` = survivor's id.
  5. Write the `SystemEvent`.
  - Both jobs must belong to `user_id`; enforced the same way every other service function
    in this codebase scopes queries (`Job.user_id == user_id`).

**`unmerge_candidate(session, user_id, candidate_id)`**

- Only valid when `status == "merged"`. Reassigns exactly the `JobSource`/`JobVersion` rows
  listed in `moved_job_source_ids`/`moved_job_version_ids` back to the merged-away job (not
  a blanket "everything currently on the survivor with a matching timestamp" — the recorded
  id lists are the source of truth). Sets the merged-away job's `status` back to `"active"`,
  `merged_into_job_id = None`.

  The candidate's own `status` goes to `"dismissed"` (not back to `"pending"`) —  to keep
  the state machine simple and avoid the pair silently re-entering the active review queue.
  The reviewer already made a call once; unmerging is them overriding their own prior
  decision, not asking to be asked again. `resolved_at` is updated to the unmerge time, and
  a `SystemEvent("job_unmerged")` is written.

## API

New router `backend/jose/api/routes/job_merge.py`, `/api/v1/job-merge-candidates` prefix,
following the existing route-file-per-resource convention (`sources.py`, `jobs.py`):

- `GET /api/v1/job-merge-candidates?status=pending` — list, default filter `pending`,
  scoped to the current user. Returns both jobs' summary fields (title, company, location,
  URL) plus `similarity_score`/`matched_signals` so the UI can show why they were paired.
- `POST /api/v1/job-merge-candidates/{id}/resolve` — body `{"action": "merge", "keep":
  "job"|"candidate"}` or `{"action": "dismiss"}`.
- `POST /api/v1/job-merge-candidates/{id}/unmerge` — no body.

New Pydantic schemas in `schemas.py`: `JobMergeCandidateRead`, `JobMergeResolveRequest`.

## Web UI

New page `/jobs/review` (`web/app/jobs/review/page.tsx` + a client component
`components/job-merge-review.tsx`, mirroring `source-manager.tsx`'s structure): lists
pending candidate pairs side by side (title/company/location/URL for each, plus the
similarity breakdown), with "Merge" (choose which side to keep) and "Not a duplicate"
buttons. This is intentionally minimal — no filtering, sorting, or history view. The
broader jobs-review workspace (search, filters, applied/irrelevant/watch decisions) is
Issue 11's scope; this page only handles the merge queue this issue introduces. Linked from
the existing `/jobs` page nav alongside the current links.

## Testing plan

Fixture/unit tests only, no live network calls, extending
`backend/tests/test_collectors.py` or a new `backend/tests/test_job_dedup.py` (service-level,
constructing `CollectedJob` instances directly rather than going through a real collector):

- **Tier 1 (ATS ID match):** two `CollectedJob`s with the same `ats_type`/
  `external_job_id` but different title text (e.g. a re-titled role) → second upsert
  updates the same `Job` row, not a new one; `fingerprint` reflects the new title.
- **Tier 2 company alias:** "OpenAI" vs "OpenAI, Inc." at the same normalized title/location
  → new job created, plus a `JobMergeCandidate` with `status="pending"` and a `company`
  component score at/above `COMPANY_ALIAS_THRESHOLD`.
- **Tier 2 location wording:** identical company/title, "San Francisco, CA" vs "SF, CA, US"
  → same outcome as above, `location` component score below what title/company alone would
  need, but composite still clears `FUZZY_MATCH_THRESHOLD`.
- **Below threshold:** same company, clearly different title (e.g. "Software Engineer" vs
  "Product Marketing Manager") → new job created, **no** `JobMergeCandidate` row.
- **No repeat proposals:** a pair already `dismissed` does not get a new candidate row on a
  subsequent collection run that re-observes both jobs.
- **Merge reassigns lineage:** `resolve_merge_candidate(..., action="merge")` moves the
  merged-away job's `JobSource` and `JobVersion` rows to the survivor; survivor's job
  listing shows both original sources.
- **Merge link collision:** merged-away job has a `JobSource` for a `Source` the survivor
  is already linked to → no unique-constraint violation, the more-recently-seen link wins.
- **Unmerge is exact:** merge, then collect a third source against the surviving job
  (adding a new `JobSource`), then unmerge → only the originally-moved rows return to the
  merged-away job; the third source's link stays on the survivor.
- **Audit trail:** merge and unmerge each produce exactly one `SystemEvent` with the
  expected `event_type`/`entity_id`/`data`.
- **User isolation:** merge candidates and resolution actions are scoped by `user_id`,
  matching every other service in this codebase (regression-style test, same shape as the
  existing two-user isolation tests in `test_sources_service.py`).

## Out of scope

- Merging/de-aliasing `Company` rows themselves (e.g. unifying "OpenAI" and "OpenAI, Inc."
  into one `Company`). Tier 2 fuzzy matching works around this by comparing company name
  strings directly rather than requiring a shared `company_id`, so job-level dedup does not
  depend on this being solved first.
- The broader jobs-review workspace (search/filter/status decisions) — Issue 11.
- Any AI/embedding-based similarity — CLAUDE.md rule 6 and Issue 11's "no AI required" both
  point at deterministic filters first; `difflib`-based scoring is sufficient for the
  wording variance seen in ATS data and keeps this fully unit-testable with fixtures.
- Performance/indexing work for the Tier 2 candidate search at scale (e.g. blocking/
  trigram indexes) — current job volumes are in the hundreds to low thousands per source;
  a full per-company candidate scan is cheap. Revisit if volume grows enough to matter.
