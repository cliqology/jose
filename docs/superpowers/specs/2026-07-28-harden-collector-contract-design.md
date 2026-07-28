# Design: Harden the Collector Contract (Backlog Issue 03)

## Goal

Give every collector adapter (Ashby, Greenhouse, Lever, JSON-LD, and future
adapters) one tested, predictable interface, per
`docs/backlog/PHASE_0_1_BACKLOG.md` Issue 03.

## Acceptance criteria (from backlog)

- Collector results validate through a Pydantic schema.
- HTTP requests use bounded timeouts, a JOSE user agent, redirect limits, and
  response-size limits.
- Unsafe/private-network URLs are rejected to reduce SSRF risk.
- Rate-limit and access-denied errors are distinguishable.
- Unknown fields remain null.
- Live network calls are absent from unit tests.

## Current state

- `backend/jose/collectors/base.py` defines `CollectedJob` as a plain
  `@dataclass`, plus `CollectorError`/`UnsupportedSourceError` and a
  `Collector` protocol.
- Each adapter (`ashby.py`, `greenhouse.py`, `lever.py`, `jsonld.py`)
  independently constructs `httpx.Client(timeout=..., follow_redirects=True)`
  and calls `client.get(...)`; `response.raise_for_status()` is the only
  error handling.
- `services/collection.py::collect_source` calls `collector.collect(...)`,
  iterates the returned `list[CollectedJob]` via plain attribute access, and
  catches `Exception` broadly, recording `type(exc).__name__` as
  `SourceRun.error_type`.
- `tests/test_collectors_http.py` uses a hand-rolled `FakeClient`/
  `FakeResponse` monkeypatched over `httpx.Client` per adapter module — no
  live network calls today, and none should be added.

## Design

### 1. Shared hardened HTTP client (`backend/jose/collectors/http.py`, new)

- `create_http_client() -> httpx.Client`: builds a client with bounded
  timeout (existing `collector_timeout_seconds` setting), a JOSE user-agent
  header, `max_redirects` from settings, and `SafeHTTPTransport` (see below)
  as its transport.
- `safe_get(client: httpx.Client, url: str, **kwargs) -> httpx.Response`:
  replaces the current `client.get(...); response.raise_for_status()`
  pattern. Streams the response, checks the status code against the error
  taxonomy (Section 3) *before* reading the body, then reads the body
  incrementally up to `collector_max_response_bytes`, raising
  `CollectorError` if the cap is exceeded. Returns a fully-populated
  `httpx.Response` (constructed via `httpx.Response(status_code=..., headers=...,
  content=..., request=...)`) so adapters keep using `.json()` / `.text`
  exactly as they do today.

All four existing adapters switch from constructing `httpx.Client(...)`
inline to calling `create_http_client()`, and from `client.get(...)` to
`safe_get(client, ...)`.

### 2. SSRF protection

`SafeHTTPTransport(httpx.HTTPTransport)` overrides `handle_request()`:

1. Rejects any scheme other than `http`/`https`.
2. Resolves the request host via `socket.getaddrinfo`.
3. Rejects the request if any resolved address is loopback, private,
   link-local, multicast, unspecified, or otherwise reserved (via the
   `ipaddress` module).
4. Raises `UnsafeURLError(CollectorError)` naming the offending host.

Because httpx invokes `transport.handle_request()` once per redirect hop
when `follow_redirects=True`, this check runs on every hop automatically,
closing DNS-rebinding attacks that cross a redirect boundary (each new
`Location:` header gets its own fresh resolution and check).

This does **not** close a rebinding race within a single hop:
`handle_request` resolves and validates the host via its own
`socket.getaddrinfo` call, then calls `super().handle_request(request)`,
which performs an independent, second resolution to actually open the
connection. An attacker controlling DNS for the target host could answer
the validation lookup with a public IP and the connection lookup with a
private/loopback address (or the cloud metadata IP `169.254.169.254`),
bypassing the check within that hop. Closing this fully requires pinning
the connection to the already-validated IP (connecting directly to it
while preserving the Host header/SNI) — a larger change to the transport
layer than this issue scopes. Tracked as a follow-up: Issue 03a in
`docs/backlog/PHASE_0_1_BACKLOG.md`.

Since `JsonLdCollector` is designed to hit arbitrary VC-supplied career-page
URLs, this must be an IP-range blocklist (not a domain allowlist) — a fixed
allowlist would break its intended use case.

### 3. `CollectedJob` becomes a Pydantic model; new error taxonomy

`base.py` changes:

- `CollectedJob` becomes a frozen `pydantic.BaseModel`
  (`model_config = ConfigDict(frozen=True, extra="ignore")`) with the same
  field names/types it has today. `application_url` and `title` stay
  required `str`; everything else stays optional. `raw_payload` keeps its
  `dict[str, Any]` default factory. `extra="ignore"` ensures fields an
  adapter doesn't set stay `None` (never populated, never an error) —
  satisfying "unknown fields remain null."
- Adapters construct `CollectedJob(...)` exactly as before; Pydantic
  validates types at construction, turning a malformed upstream field (e.g.
  compensation arriving as a string) into a loud `ValidationError` instead
  of a silently-propagated bad value.
- New exceptions, all subclasses of `CollectorError` (so existing
  `except CollectorError` handling in `services/collection.py` is
  unaffected):
  - `RateLimitError` — raised by `safe_get` on HTTP 429.
  - `AccessDeniedError` — raised by `safe_get` on HTTP 401/403.
  - `UnsafeURLError` — raised by `SafeHTTPTransport`.
  - Other 4xx/5xx responses and existing adapter-specific errors (e.g.
    "couldn't determine board token") remain plain `CollectorError`.
- `SourceRun.error_type` already stores `type(exc).__name__`, so this
  taxonomy is visible in the dashboard/logs with no further schema change.

### 4. New settings (`backend/jose/config.py`)

All overridable via `.env`, alongside the existing
`collector_timeout_seconds`:

- `collector_user_agent: str = "JOSE-Collector/1.0"`
- `collector_max_redirects: int = 5`
- `collector_max_response_bytes: int = 5 * 1024 * 1024` (5 MB)

### 5. Testing strategy

No live network calls are added; the existing fixture/monkeypatch approach
is extended:

- `tests/test_collectors_http.py`: `FakeClient`/`FakeResponse` grow a
  `.stream()` context-manager mode (matching `safe_get`'s streaming usage)
  exposing `status_code`, `headers`, and `iter_bytes()`, alongside the
  existing `.get()` mode. The four existing adapter tests are updated to
  match the new call pattern and continue to assert the same behavior.
- New `tests/test_collector_http_hardening.py`:
  - `safe_get` maps 429 → `RateLimitError`, 401/403 → `AccessDeniedError`,
    other 4xx/5xx → `CollectorError`.
  - Response-size cap trips `CollectorError` before the full oversized body
    is buffered.
  - `SafeHTTPTransport` blocks a request when `socket.getaddrinfo` is
    monkeypatched to resolve a hostname to a private/loopback IP, and
    permits a request when it resolves to a public IP (verified against a
    mocked downstream transport, not a real connection).
- `CollectedJob` gets direct unit tests: constructing with a bad field type
  raises `pydantic.ValidationError`; an adapter omitting an optional field
  leaves it `None` rather than raising.

## Out of scope

- robots.txt checking / compliance (not in Issue 03's acceptance criteria;
  candidate for a future issue).
- Adding new adapters (Issue 04+).
- Changing `services/collection.py`'s persistence logic — it already
  consumes `CollectedJob` via attribute access, which the Pydantic model
  preserves unchanged.
