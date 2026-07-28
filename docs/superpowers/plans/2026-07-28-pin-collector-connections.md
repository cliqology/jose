# Pin Collector Connections to Validated IPs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate the resolve-then-connect DNS-rebinding race in `SafeHTTPTransport`, per `docs/backlog/PHASE_0_1_BACKLOG.md` Issue 03a and `docs/superpowers/specs/2026-07-28-pin-collector-connections-design.md`.

**Architecture:** `SafeHTTPTransport.handle_request` already resolves and validates every address for a hostname via `socket.getaddrinfo` before delegating to `httpx.HTTPTransport`. That delegation currently passes the *original* request through unchanged, so httpcore re-resolves DNS independently to connect — a second, unvalidated resolution. This plan extracts the validation loop into a `_resolve_and_validate()` helper that returns the validated addresses, then rewrites the delegated `httpx.Request`'s URL host to the literal pinned IP (a literal address needs no DNS lookup) while setting the `sni_hostname` extension to the original hostname (so TLS/cert validation still checks the real domain) and preserving the original `Host:` header.

**Tech Stack:** Python 3.12, httpx 0.28.1, httpcore 1.0.9 (verified: `httpcore.HTTPConnection._connect` reads `request.extensions.get("sni_hostname")` for the TLS `server_hostname`, falling back to the connection's own origin host — confirmed by reading the installed source directly), pytest, ruff.

## Global Constraints

- Python 3.12; ruff `target-version = "py312"`, `line-length = 100`, lint rules `["E", "F", "I", "B", "UP", "SIM"]`, `quote-style = "double"` (`backend/pyproject.toml`).
- No live network calls in unit tests — extend the existing monkeypatch approach in `backend/tests/test_collector_http_hardening.py`.
- Only `backend/jose/collectors/http.py` and `backend/tests/test_collector_http_hardening.py` change. No changes to `create_http_client()`, `safe_get()`, `base.py`, `config.py`, the four adapters, or `services/collection.py`.
- Address selection: when `socket.getaddrinfo` returns multiple validated addresses, pin to the first one, in the OS resolver's own order — no retry/fallback across the remaining addresses.
- No persisted schema changes, so no Alembic migration is needed.
- Run tests with `docker compose run --rm --no-deps api pytest tests/test_collector_http_hardening.py -v` (these tests need no database — see note below) and the full suite with `docker compose run --rm api pytest` (requires the db; use `--no-deps` only for this file). If port 5432 is occupied by another checkout's container, either stop it or temporarily remap this checkout's `docker-compose.yml` db port and revert before the final commit.
- Run lint with `docker compose run --rm api ruff check jose tests`.

---

### Task 1: Pin `SafeHTTPTransport` connections to validated IPs

**Files:**
- Modify: `backend/jose/collectors/http.py` (whole file)
- Modify: `backend/tests/test_collector_http_hardening.py` (add new tests; existing tests are unaffected and must still pass unchanged — none of them assert request identity, only the raised exception or the returned response)

**Interfaces:**
- Consumes: `UnsafeURLError` (from `jose.collectors.base`, unchanged).
- Produces: `SafeHTTPTransport.handle_request(request: httpx.Request) -> httpx.Response` — same public signature as today; `create_http_client()` and `safe_get()` are unaffected and need no changes, since they only ever construct `SafeHTTPTransport()` and never call its internals directly.

- [ ] **Step 1: Write the failing tests**

Add these tests to `backend/tests/test_collector_http_hardening.py` (after the existing `test_transport_rejects_non_http_scheme` test, before the `_FakeStreamResponse` class):

```python
def test_transport_pins_connection_to_validated_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    call_count = 0

    def counting_getaddrinfo(*_a: object, **_k: object) -> list[tuple]:
        nonlocal call_count
        call_count += 1
        return _addrinfo("93.184.216.34")

    monkeypatch.setattr(socket, "getaddrinfo", counting_getaddrinfo)

    captured: dict[str, httpx.Request] = {}

    def fake_handle_request(self: httpx.HTTPTransport, request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, request=request)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", fake_handle_request)

    transport = SafeHTTPTransport()
    request = httpx.Request("GET", "https://example.com/jobs?x=1")
    transport.handle_request(request)

    assert call_count == 1
    pinned_request = captured["request"]
    assert str(pinned_request.url) == "https://93.184.216.34/jobs?x=1"
    assert pinned_request.extensions["sni_hostname"] == "example.com"
    assert pinned_request.headers["host"] == "example.com"


def test_transport_does_not_set_sni_hostname_for_plain_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_a, **_k: _addrinfo("93.184.216.34"))

    captured: dict[str, httpx.Request] = {}

    def fake_handle_request(self: httpx.HTTPTransport, request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, request=request)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", fake_handle_request)

    transport = SafeHTTPTransport()
    request = httpx.Request("GET", "http://example.com/jobs")
    transport.handle_request(request)

    assert "sni_hostname" not in captured["request"].extensions


def test_transport_pins_ipv6_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_a, **_k: [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2606:4700:4700::1111", 0, 0, 0))],
    )

    captured: dict[str, httpx.Request] = {}

    def fake_handle_request(self: httpx.HTTPTransport, request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, request=request)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", fake_handle_request)

    transport = SafeHTTPTransport()
    request = httpx.Request("GET", "https://example.com/jobs")
    transport.handle_request(request)

    pinned_request = captured["request"]
    assert pinned_request.url.host == "2606:4700:4700::1111"
    assert str(pinned_request.url) == "https://[2606:4700:4700::1111]/jobs"
    assert pinned_request.extensions["sni_hostname"] == "example.com"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose run --rm --no-deps api pytest tests/test_collector_http_hardening.py -v`
Expected: FAIL — `test_transport_pins_connection_to_validated_ip` fails because `captured["request"].url` still has `host == "example.com"` (the current code delegates the original, unmodified request), not `"93.184.216.34"`; `test_transport_pins_ipv6_connection` fails for the same reason.

- [ ] **Step 3: Rewrite `backend/jose/collectors/http.py`**

Replace the full contents of `backend/jose/collectors/http.py`:

```python
import ipaddress
import socket
from typing import Any

import httpx

from jose.collectors.base import AccessDeniedError, CollectorError, RateLimitError, UnsafeURLError
from jose.config import get_settings

_CGNAT_NETWORK = ipaddress.ip_network("100.64.0.0/10")


def _resolve_and_validate(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError as exc:
        raise UnsafeURLError(f"Unable to resolve host: {host}") from exc

    addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for _family, _type, _proto, _canonname, sockaddr in infos:
        ip = ipaddress.ip_address(sockaddr[0])
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        is_cgnat = isinstance(ip, ipaddress.IPv4Address) and ip in _CGNAT_NETWORK
        if (
            ip.is_loopback
            or ip.is_private
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_unspecified
            or ip.is_reserved
            or is_cgnat
        ):
            raise UnsafeURLError(f"Refusing to contact unsafe host: {host} ({ip})")
        addresses.append(ip)
    return addresses


class SafeHTTPTransport(httpx.HTTPTransport):
    def handle_request(self, request: httpx.Request) -> httpx.Response:
        url = request.url
        if url.scheme not in ("http", "https"):
            raise UnsafeURLError(f"Unsafe URL scheme: {url.scheme}")

        addresses = _resolve_and_validate(url.host)
        pinned = addresses[0]

        extensions = dict(request.extensions)
        if url.scheme == "https":
            extensions["sni_hostname"] = url.host

        pinned_request = httpx.Request(
            method=request.method,
            url=url.copy_with(host=str(pinned)),
            headers=request.headers,
            stream=request.stream,
            extensions=extensions,
        )
        return super().handle_request(pinned_request)


def create_http_client() -> httpx.Client:
    settings = get_settings()
    return httpx.Client(
        timeout=settings.collector_timeout_seconds,
        follow_redirects=True,
        max_redirects=settings.collector_max_redirects,
        headers={"User-Agent": settings.collector_user_agent},
        transport=SafeHTTPTransport(),
    )


def safe_get(client: httpx.Client, url: str, **kwargs: Any) -> httpx.Response:
    max_bytes = get_settings().collector_max_response_bytes

    with client.stream("GET", url, **kwargs) as response:
        if response.status_code == 429:
            raise RateLimitError(f"Rate limited by {url}")
        if response.status_code in (401, 403):
            raise AccessDeniedError(f"Access denied by {url}: HTTP {response.status_code}")
        if response.status_code >= 400:
            raise CollectorError(f"Request to {url} failed with status {response.status_code}")

        body = bytearray()
        for chunk in response.iter_bytes():
            body.extend(chunk)
            if len(body) > max_bytes:
                raise CollectorError(f"Response from {url} exceeded {max_bytes} bytes")

        headers = httpx.Headers(
            [
                (name, value)
                for name, value in response.headers.items()
                if name.lower() not in ("content-encoding", "content-length")
            ]
        )
        return httpx.Response(
            status_code=response.status_code,
            headers=headers,
            content=bytes(body),
            request=response.request,
        )
```

(Only `SafeHTTPTransport` changed; `create_http_client()` and `safe_get()` are reproduced here unchanged, verbatim from the current file, so the whole-file replacement doesn't lose anything.)

- [ ] **Step 4: Run the new tests to verify they pass**

Run: `docker compose run --rm --no-deps api pytest tests/test_collector_http_hardening.py -v`
Expected: PASS — all tests, including the three new ones and every pre-existing test in this file (scheme rejection, private/loopback/CGNAT/IPv4-mapped blocking, public-allowed, all `safe_get` tests).

- [ ] **Step 5: Run ruff**

Run: `docker compose run --rm api ruff check jose tests`
Expected: no findings.

- [ ] **Step 6: Run the full backend test suite for a regression check**

Run: `docker compose run --rm api pytest` (start the db first if needed; see Global Constraints for the port-conflict workaround)
Expected: PASS — all pre-existing tests plus the three new ones, no regressions in the four collector adapters (their tests go through `SafeHTTPTransport` only when a fixture explicitly exercises it; the four adapter tests in `test_collectors_http.py` mock `create_http_client` entirely and never reach `SafeHTTPTransport`, so they are unaffected by this change).

- [ ] **Step 7: Commit**

```bash
git add backend/jose/collectors/http.py backend/tests/test_collector_http_hardening.py
git commit -m "feat: pin SafeHTTPTransport connections to validated IPs (Issue 03a)"
```

---

## Post-plan verification

- [ ] Re-read `docs/superpowers/specs/2026-07-28-pin-collector-connections-design.md` and `docs/backlog/PHASE_0_1_BACKLOG.md`'s Issue 03a acceptance criteria against this task: (1) the pinned IP is the same one validated — proven by `test_transport_pins_connection_to_validated_ip` capturing the actual delegated request's URL host; (2) redirect-hop checking is unchanged — `handle_request` is still re-invoked by httpx once per hop, each hop independently re-resolving/re-validating/re-pinning, no change to that mechanism; (3) no regression to the existing Issue 03 suite — confirmed by Step 6's full-suite run.
