# Design: Discover Portfolio-Board Platform Types (Issue 05)

## Goal

Determine the platform behind every VC source in the spreadsheet, per `docs/backlog/PHASE_0_1_BACKLOG.md` Issue 05:

- Each VC source has a configured adapter or an explicit `unsupported` status.
- Platform detection results are stored and reviewable.
- Redirected ATS links are captured as canonical application URLs.
- Findings are documented in `docs/source-catalog.md`.
- No source is silently assigned JSON-LD when platform detection is uncertain.

## Research findings

- The 17 VC sources come from the `"VC FIRM"` section of `data/import/VC_Job_Search_Resources.xlsx`, imported into `sources` with `category="vc_portfolio"` by `backend/jose/services/source_import.py` (e.g. a16z, Sequoia, Index Ventures, Greylock, Kleiner Perkins, Accel, YC, Bessemer, and others). `Source.portfolio_firm` is already populated with the firm name for these rows.
- `Source.adapter` defaults to `"auto"` at import time and is never updated afterward. `backend/jose/collectors/registry.py::detect_adapter` matches the source URL's hostname against `jobs.ashbyhq.com` / `boards.greenhouse.io` / `job-boards.greenhouse.io` / `jobs.lever.co`, and **falls through to `"jsonld"` for every other host** — including all 17 VC sources today, since none of them resolve to a direct ATS hostname. This is the exact silent-fallback behavior the last acceptance criterion targets.
- There is currently no `platform_type`/detection-result field anywhere, no `unsupported` status value in use, and no persisted detection metadata. `backend/tests/test_collectors.py::test_detect_adapter` locks in today's fallback behavior for the general case and is not touched by this change (see Scope below).
- `docs/source-catalog.md` does not exist yet. No other doc catalogs individual sources.
- The existing SSRF-safe HTTP stack (`backend/jose/collectors/http.py::create_http_client` / `safe_get`) already follows redirects (bounded, size-capped, timeout-bounded) and is reused as-is here — no new HTTP code is needed.

## Scope

This issue is a **cataloging/detection pass**, not a collector. It is scoped to sources with `category="vc_portfolio"` only:

- `detect_adapter`'s runtime fallback behavior for non-VC sources is unchanged; `test_detect_adapter` is unchanged.
- Building an actual aggregator adapter (e.g. for whatever the most valuable detected platform turns out to be) is Issue 06, not this issue.
- The specific non-ATS aggregator platforms in use by these 17 firms (e.g. whether any use a common white-label job-board SaaS) are not assumed in advance — the signature table below starts small and is expected to be filled in based on what the live probe actually finds when it's run against the real 17 URLs, not on guessed platform names.

## Data model change

Migration adds four nullable columns to `sources`:

- `detected_platform: str | None` (`String(100)`) — the signature found (e.g. `"greenhouse"`, or a specific aggregator name), or `null` if nothing recognizable was found.
- `detection_status: str | None` (`String(20)`) — one of `"supported"`, `"unsupported"`, `"uncertain"`, `"error"`.
- `detected_application_url: str | None` (`Text`) — the final URL after following redirects. Stored separately from the existing human-configured `url` column; detection never silently rewrites `url`.
- `detected_at: datetime | None` (`DateTime(timezone=True)`) — when the probe last ran for this source.

`Source.adapter` becomes the authoritative field once a source has been probed:

- Set to a real collector name (`"ashby"` / `"greenhouse"` / `"lever"` / `"jsonld"`) only on a confident match (`detection_status="supported"`).
- Set to the literal `"unsupported"` for every other outcome — both a recognized-but-uncollectible platform and a genuinely uncertain result — so it is never left on `"auto"` (which is what causes today's silent JSON-LD fallback) and so `get_collector()` fails loudly (`UnsupportedSourceError`) rather than being reachable at all.
- `detection_status` is what distinguishes the two `"unsupported"` cases for human review: `"unsupported"` (we found a specific platform, e.g. `detected_platform="getro"`, but have no adapter for it) vs. `"uncertain"` (we found nothing recognizable at all).

Probe failures (network error, non-2xx, timeout, blocked) reuse the existing `last_error` column instead of adding a new one, and set `detection_status="error"`. `adapter` is left untouched on error — a failed probe must never be recorded as a confident `"unsupported"` finding, per CLAUDE.md rule #5 applied by analogy ("a failed collector is a failure, never a successful zero-result run").

## Detection logic

New module `backend/jose/services/platform_detection.py`:

```python
class ProbeResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    source_id: uuid.UUID
    status: Literal["supported", "unsupported", "uncertain", "error"]
    adapter: str | None          # unchanged (None) on "error"
    detected_platform: str | None
    detected_application_url: str | None
    error: str | None
```

`probe_source(url: str) -> ProbeResult` fetches the URL via the existing `create_http_client()` / `safe_get()`, then classifies in order:

1. **Known ATS host match** on the final resolved URL (after redirects) — reuses the same hostname list `detect_adapter` already uses for `ashby` / `greenhouse` / `lever` (extracted into a shared helper so the list isn't duplicated). Match → `status="supported"`, `adapter=<name>`, `detected_application_url=<final URL>`.
2. **JSON-LD `JobPosting` present in the response body** → `status="supported"`, `adapter="jsonld"`. This is the concrete fix for the last acceptance criterion: JSON-LD is only ever assigned when structured data is actually found in the fetched body, never as a blind default for an unrecognized host.
3. **Known aggregator signature** — a small, explicitly extensible table (`AGGREGATOR_SIGNATURES: dict[str, ...]`) matching hostname or body substrings for non-ATS platforms. Seeded minimally at implementation time and expected to grow once probes run against the real 17 sources. Match → `status="unsupported"`, `adapter="unsupported"`, `detected_platform=<name>`.
4. **Nothing recognized** → `status="uncertain"`, `adapter="unsupported"`, `detected_platform=None`.
5. **Request fails** (raises `CollectorError`/`UnsafeURLError`/`RateLimitError`/`AccessDeniedError`, or any transport error) → `status="error"`, `adapter=None`, `error=<message>`.

`detect_platforms_for_vc_sources(session, user) -> list[ProbeResult]`:

- Loads all `Source` rows for `user` with `category="vc_portfolio"`.
- Calls `probe_source` for each. One source's failure is caught locally and recorded as `status="error"` — it never aborts the batch.
- Updates the row's `adapter` (only when not `"error"`), `detected_platform`, `detection_status`, `detected_application_url`, `detected_at=utcnow()`, and `last_error` (only when `"error"`), then commits.
- Returns the full list of `ProbeResult` for CLI reporting and catalog rendering.

This is the only place with business logic, per CLAUDE.md ("do not put business logic in route handlers"); the CLI command below is a thin wrapper.

## CLI command

`detect-vc-platforms` in `backend/jose/cli.py`, following the existing pattern (`seed`, `import-sources`, `collect-source`):

```python
@app.command("detect-vc-platforms")
def detect_vc_platforms() -> None:
    """Probe VC portfolio sources and record their platform/adapter status."""
    with SessionLocal() as session:
        user = get_or_create_default_user(session)
        results = detect_platforms_for_vc_sources(session, user)
        catalog_path = Path("docs/source-catalog.md")
        catalog_path.write_text(render_source_catalog(session, user))
    for result in results:
        ...  # one line per source: name, status, adapter, detected_platform, application_url or error
    typer.echo(f"Wrote {catalog_path}")
```

## `docs/source-catalog.md`

Generated, not hand-written, via `render_source_catalog(session, user) -> str` in the same service module: queries all `vc_portfolio` sources (post-probe state) and renders a markdown table with columns Source, Configured URL, Detected Platform, Adapter/Status, Detected Application URL. Regenerated in full every time the CLI command runs, so it can never drift from DB state. A trailing free-text "Notes" section below the table is left for Scott to hand-edit for anything the automated probe can't capture (e.g. manual research on an `"uncertain"` source) — the render only owns the table.

## Error handling

- Per-source probe failures are caught inside `detect_platforms_for_vc_sources` and recorded as `status="error"`; they never raise out of the batch or abort remaining sources.
- `"error"` and `"uncertain"` are kept as distinct `detection_status` values end-to-end (DB, CLI output, catalog table) so a transient network failure is never mistaken for a confident "nothing here" finding.
- Non-negotiable rules 1–2 (approval before applying/messaging) are not implicated — this issue only reads pages and writes catalog metadata. Rule 12 (no bypassing CAPTCHA/MFA/rate limits/robots/security controls) — the probe issues a single plain GET per source through the existing safe client; no bypass logic of any kind is added. Rule 4 ("unknown information remains unknown") is the reason `"uncertain"` exists as a distinct, honestly-labeled outcome rather than being coerced into either `"supported"` or a confidently-labeled `"unsupported"`.

## Testing plan

All fixture-based (no live network calls), following the `FakeResponse`/`FakeClient` monkeypatch style in `backend/tests/test_collectors_http.py`:

**`test_platform_detection.py`** — `probe_source`:
- Final URL resolves (via redirect) to a known ATS host → `status="supported"`, `adapter` matches, `detected_application_url` is the final URL.
- Body contains a valid JSON-LD `JobPosting` → `status="supported"`, `adapter="jsonld"`.
- Body/host matches a seeded aggregator signature → `status="unsupported"`, `detected_platform` set, `adapter="unsupported"`.
- Body matches nothing → `status="uncertain"`, `adapter="unsupported"`, `detected_platform=None`.
- Fetch raises / returns a non-2xx status → `status="error"`, `error` populated, `adapter=None`.

**Service-level test** for `detect_platforms_for_vc_sources`:
- Seeds a `db_session` with two `vc_portfolio` sources and one non-VC source; asserts only the VC sources are probed/updated and the non-VC source's `adapter` is untouched.
- Asserts user-scoping: a second user's `vc_portfolio` source is not touched by a run scoped to the first user (CLAUDE.md rule #7).
- Asserts one source's probe failure doesn't prevent the others from being processed.

**Catalog render test**:
- Given a small set of post-probe `Source` rows, asserts the rendered markdown table contains the expected columns/rows.

No changes to `backend/tests/test_collectors.py::test_detect_adapter` — confirmed out of scope.

## Out of scope

- Building a real collector/adapter for any detected non-ATS aggregator platform — Issue 06.
- Changing `detect_adapter`'s runtime fallback for non-VC sources.
- Crawling into individual job-listing links found on a VC's board page (board-level detection only, per design discussion — a source's own redirect chain is captured, but the tool does not parse the board's HTML for a representative job link to follow further).
- Expanding the aggregator signature table beyond a minimal starting set as part of this design — real signatures are expected to be added once the tool is run against the live 17 sources.
