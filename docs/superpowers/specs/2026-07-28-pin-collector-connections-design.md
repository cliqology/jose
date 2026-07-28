# Design: Pin Collector Connections to Validated IPs (Backlog Issue 03a)

## Goal

Eliminate the resolve-then-connect DNS-rebinding race in `SafeHTTPTransport`
(`backend/jose/collectors/http.py`), per `docs/backlog/PHASE_0_1_BACKLOG.md`
Issue 03a, filed as a follow-up during Issue 03's final review.

## Acceptance criteria (from backlog)

- The IP address JOSE's collectors connect to is the same IP that was
  validated by `SafeHTTPTransport`, with no second independent DNS
  resolution between check and connect.
- Redirect-hop checking (one fresh validation per `Location:` header)
  continues to work as it does today.
- No regression to the existing Issue 03 test suite.

## Current state

`SafeHTTPTransport(httpx.HTTPTransport)` overrides `handle_request()`:
rejects non-http(s) schemes, resolves the request host via
`socket.getaddrinfo`, raises `UnsafeURLError` if any resolved address is
loopback/private/link-local/multicast/unspecified/reserved/CGNAT
(`100.64.0.0/10`, with IPv4-mapped-IPv6 forms normalized first), then calls
`super().handle_request(request)` unchanged.

That last step is the gap: `httpx.HTTPTransport.handle_request` builds an
`httpcore.Request` from `request.url.raw_host` and delegates to httpcore's
`ConnectionPool`, whose `HTTPConnection._connect` calls
`self._network_backend.connect_tcp(host=self._origin.host, ...)` — a
*second*, fully independent call into the OS resolver
(`socket.getaddrinfo` under the hood). An attacker controlling DNS for the
target hostname can answer the validation lookup with a public IP and the
connection lookup with a private/loopback/metadata address, bypassing the
check within a single hop. This was verified against the pinned versions in
this repo (httpx 0.28.1, httpcore 1.0.9) by reading
`HTTPConnection._connect`'s source directly.

## Design

### 1. Validation helper returns addresses instead of only raising

Extract the current per-address validation loop in `handle_request` into a
helper, e.g.:

```python
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
```

This preserves today's behavior exactly (raise on the first unsafe address
found) but returns the full validated list so `handle_request` can pick one
to pin. `socket.getaddrinfo` is still called exactly once per
`handle_request` invocation — unchanged from today.

### 2. Pin the connection by rewriting the delegated request

`handle_request` becomes:

```python
def handle_request(self, request: httpx.Request) -> httpx.Response:
    url = request.url
    if url.scheme not in ("http", "https"):
        raise UnsafeURLError(f"Unsafe URL scheme: {url.scheme}")

    addresses = _resolve_and_validate(url.host)
    pinned = addresses[0]

    pinned_request = httpx.Request(
        method=request.method,
        url=url.copy_with(host=_url_host(pinned)),
        headers=request.headers,
        stream=request.stream,
        extensions={**request.extensions, "sni_hostname": url.host}
        if url.scheme == "https"
        else request.extensions,
    )
    return super().handle_request(pinned_request)
```

with a tiny formatter for URL-safe host text:

```python
def _url_host(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str:
    return f"[{ip}]" if isinstance(ip, ipaddress.IPv6Address) else str(ip)
```

Because a literal IP address requires no DNS lookup, httpcore's
`connect_tcp` connects directly to `pinned` with no second resolution. The
`sni_hostname` extension (already read by httpcore's `HTTPConnection._connect`
for the TLS `server_hostname`, per the source above) keeps certificate
validation checking the real hostname, not the IP. `request.headers` is
passed through unchanged, so the `Host:` header — already set by httpx to
the original hostname when the client built the request, before this
transport ever sees it — is preserved, and virtual-hosted origin servers
keep receiving the correct value.

Redirect handling is unaffected: httpx re-invokes `transport.handle_request`
once per redirect hop with a fresh `Request` for the new URL, so each hop
independently re-resolves, re-validates, and re-pins — the existing
per-hop SSRF protection carries over unchanged.

### 3. Address selection

When `getaddrinfo` returns multiple addresses, pin to `addresses[0]` — the
first entry, in the OS resolver's own order — with no additional retry or
fallback logic across the remaining validated addresses. This matches
today's implicit behavior (the transport never inspected which address
would ultimately be used) and keeps the change minimal per YAGNI. If the
pinned address's connection fails, that surfaces as httpx's normal
`ConnectError`/`ConnectTimeout`, handled by the adapters' existing generic
exception handling — no new exception type.

### 4. Testing strategy

No live network calls; extends the existing monkeypatch approach in
`backend/tests/test_collector_http_hardening.py`:

- A call-counting wrapper around `socket.getaddrinfo` proves exactly one
  resolution happens per `handle_request` call (matching today).
- `httpx.HTTPTransport.handle_request` is monkeypatched to capture the
  `httpx.Request` it receives (instead of touching the network), and the
  test asserts: the captured request's `url.host` equals the pinned
  literal IP (not the original hostname); for an `https://` URL,
  `request.extensions["sni_hostname"]` equals the original hostname; the
  `Host:` header on the captured request is unchanged from the original.
- A dedicated test resolves to an IPv6-only address to confirm the `[...]`
  bracket formatting produces a URL whose `.host` round-trips to the plain
  IPv6 literal, the same way httpx already handles a user-supplied
  IPv6-literal URL.
- All existing `SafeHTTPTransport` tests (scheme rejection, private,
  loopback, CGNAT, IPv4-mapped, public-allowed) are re-run to confirm no
  regression. None of them assert request identity — only the returned
  response — so they're expected to keep passing against the now-rewritten
  delegated request.

## Out of scope

- Retrying across multiple validated addresses if the pinned one fails to
  connect (YAGNI; not required by the acceptance criteria).
- Network-level egress firewalling (iptables/security groups) as an
  additional defense-in-depth layer — a valid complementary control, but a
  separate, infrastructure-level change with a different cost/consistency
  profile (per CLAUDE.md's "local and cloud versions must use the same
  code and containers" rule) and not what Issue 03a's acceptance criteria
  ask for.
- Any change to `create_http_client()`, `safe_get()`, the four collector
  adapters, or `services/collection.py` — this is fully contained within
  `SafeHTTPTransport.handle_request` and its new helper.
