# Design: Productionize ATS Collectors (Issue 04)

## Goal

Reliably collect direct Ashby, Greenhouse, and Lever boards, per `docs/backlog/PHASE_0_1_BACKLOG.md` Issue 04:

- Fixture tests cover empty, paginated, malformed, and changed responses.
- Collector identifies actual company rather than relying solely on source label when data permits.
- Compensation parsing is normalized without guessing.
- Publication timestamps are timezone aware.
- Jobs lacking application URLs are rejected and logged.
- Raw payload retention can be disabled by configuration.

## Research findings (grounded against the live public APIs, not assumed)

- **Ashby** (`GET /posting-api/job-board/{name}`): single response containing all live postings, no pagination. No company-name field anywhere in the payload (top level or per job) — company identity only appears as unstructured prose inside the job description HTML, which is not something we should parse (would be guessing).
- **Greenhouse** (`GET /v1/boards/{token}/jobs`): single response, no pagination (a `meta.total` count exists but the endpoint returns everything in one call). Confirmed via a live call against a real board that each job **does** include a `company_name` field on the list endpoint, contrary to some third-party docs claiming it's list-only omitted.
- **Lever** (`GET /v0/postings/{site}`): top-level response is a bare JSON array (or, on error, a dict like `{"ok": false, "error": "..."}` alongside a non-2xx status). No company field in the payload. Real pagination via `skip`/`limit` query params — confirmed empirically (`limit=5&skip=100` returns the next slice). No total count is returned; a client must keep requesting pages until a short page comes back. Postings carry a structured `salaryRange: {currency, interval, min, max}` field that today's collector ignores entirely.
- All three collectors currently do `data.get("jobs", [])` (or iterate a non-list without checking), which means a genuinely broken/unexpected response shape silently becomes a "successful" zero-result run — a direct violation of CLAUDE.md rule #5 ("a failed collector is a failure, never a successful zero-result run").

## Collector contract change

`Collector.collect()` currently returns `list[CollectedJob]`, with no channel to report jobs that were dropped during collection. `base.py` gains:

```python
class CollectionResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    jobs: list[CollectedJob]
    rejected_count: int = 0
```

- `AshbyCollector`, `GreenhouseCollector`, `LeverCollector` return `CollectionResult` instead of a bare list.
- `JsonLdCollector` wraps its existing return value as `CollectionResult(jobs=jobs)` (rejected_count always 0) — no behavior change to its internal logic; it is out of scope for this issue but must match the shared `Collector` protocol.
- `collect_source()` in `services/collection.py` reads `result.jobs` for the upsert loop and `result.rejected_count` to populate the new `SourceRun.jobs_rejected` field.
- `Collector` Protocol in `base.py` updates its `collect` signature return type accordingly.

## Malformed vs. empty vs. changed responses

Each collector validates the top-level shape before iterating, and raises `CollectorError` (a real run failure) when the shape doesn't match, instead of defaulting to an empty list:

- **Ashby / Greenhouse**: response must be a `dict` with a `"jobs"` key whose value is a `list`. Anything else (missing key, wrong type, non-dict top level) raises `CollectorError`. `"jobs": []` is a legitimate, successful zero-result run.
- **Lever**: response must be a `list`. A `dict` response body (Lever's own error shape) raises `CollectorError` if it somehow arrives with a 2xx status; the ordinary case (404 with `{"ok": false, ...}`) is already caught by `safe_get`'s status-code handling before we get here.

Within a valid top-level shape, individual malformed entries (not a dict, or lacking enough identifying data to be useful) are skipped with `logger.warning(...)` and counted in `rejected_count` rather than aborting the whole run — this is what "changed responses" fixture tests exercise (e.g., a field renamed or a job entry with an unexpected shape).

## Rejected jobs (missing application URL)

Each collector computes the candidate application URL before constructing `CollectedJob`:

- Ashby: `item.get("applyUrl") or item.get("jobUrl")`
- Greenhouse: `item.get("absolute_url")`
- Lever: `item.get("applyUrl") or item.get("hostedUrl")`

If empty/falsy, `logger.warning(...)` with the title and any external id, skip the item, and increment a local rejected counter — never construct a `CollectedJob` with a missing URL.

## Per-adapter changes

### Greenhouse
- `company_name = item.get("company_name") or source_name`.

### Ashby, Lever
- Company identification unchanged (`source_name`) — no structured field exists in either payload to prefer over it. Not touched further.

### Lever pagination
- Loop `GET .../postings/{site}?mode=json&skip={skip}&limit=100`, accumulating pages until a page returns fewer than 100 items.
- Hard cap of 50 pages (5,000 jobs): if hit, log a warning and stop rather than looping forever against a misbehaving or enormous board.

### Lever compensation
- Parse `salaryRange.min` / `.max` / `.currency` into `compensation_min` / `compensation_max` / `currency` when present. `interval` is not persisted (no corresponding field on `CollectedJob`/`Job`). No fabrication when `salaryRange` is absent — fields stay `None`.

### Publication timestamps
- Already timezone-aware end-to-end via `parse_datetime` (forces UTC when no offset is present, correctly parses Greenhouse's `-04:00`-style offsets and Lever's epoch-millisecond `createdAt`). No code change required; covered by regression tests to lock in the behavior.

## Configuration: raw payload retention

- New setting in `config.py`: `collector_retain_raw_payload: bool = True`.
- Enforced centrally in `_upsert_job` (`services/collection.py`), not per-collector: when `False`, both the create and update paths persist `{}` for `Job.raw_payload` instead of `item.raw_payload`. Collectors themselves always populate `CollectedJob.raw_payload` normally; the toggle is a persistence-layer decision, avoiding duplicated logic across three adapters.

## Data model change

- Migration adds `SourceRun.jobs_rejected: int`, default `0`, alongside the existing `jobs_created` / `jobs_updated` columns.
- `collect_source()` sets `run.jobs_rejected = result.rejected_count` (summed across all collectors' contributions during the run — for Issue 04 there is exactly one collector call per run, so this is just the single `CollectionResult.rejected_count`).

## Testing plan

All fixture-based (no live network calls), extending `backend/tests/test_collectors_http.py` and the existing `backend/tests/fixtures/{ashby,greenhouse,lever}.json`:

- **Empty**: `"jobs": []` (Ashby/Greenhouse) / `[]` (Lever) → `CollectionResult(jobs=[], rejected_count=0)`, no error.
- **Paginated**: Lever fixture split across two fake pages (first page returns 100 items via a param-aware fake client, second returns fewer) → collector concatenates both pages into one result.
- **Malformed**: top-level shape missing `"jobs"` (Ashby/Greenhouse) or a dict instead of a list (Lever) → raises `CollectorError`.
- **Changed/mixed**: a fixture with one well-formed job and one job missing its application URL → result contains only the valid job, `rejected_count == 1`.
- **Company identification**: Greenhouse fixture job carries `company_name` different from the source label → `CollectedJob.company_name` reflects the payload, not the label.
- **Compensation**: Lever fixture job with `salaryRange` → `compensation_min`/`compensation_max`/`currency` populated; a job without `salaryRange` leaves them `None`.
- **Raw payload retention**: a `collection.py`-level test (not per-collector) verifying `Job.raw_payload` is `{}` when `collector_retain_raw_payload=False` and unchanged when `True`.
- **Regression**: existing single-page happy-path and epoch-millisecond timezone tests continue to pass under the new `CollectionResult` return shape.

## Out of scope

- `JsonLdCollector`'s internal collection logic (malformed handling, rejected jobs, company identification) — it shares the protocol change only.
- VC portfolio/aggregator boards (Issue 05/06) — company identification there is a separate, harder problem (redirected ATS links, portfolio company vs. VC firm) explicitly deferred to those issues.
- Changing how `Source.name` is populated at import time — out of scope for the collector layer.
