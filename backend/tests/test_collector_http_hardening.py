import socket
from collections.abc import Iterator
from contextlib import contextmanager

import httpx
import pytest

from jose.collectors.base import AccessDeniedError, CollectorError, RateLimitError, UnsafeURLError
from jose.collectors.http import SafeHTTPTransport, safe_get
from jose.config import get_settings


def _addrinfo(ip: str) -> list[tuple]:
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]


def test_transport_blocks_private_address(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_a, **_k: _addrinfo("10.0.0.5"))
    transport = SafeHTTPTransport()
    request = httpx.Request("GET", "https://internal.example.com/")
    with pytest.raises(UnsafeURLError):
        transport.handle_request(request)


def test_transport_blocks_loopback_address(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_a, **_k: _addrinfo("127.0.0.1"))
    transport = SafeHTTPTransport()
    request = httpx.Request("GET", "https://internal.example.com/")
    with pytest.raises(UnsafeURLError):
        transport.handle_request(request)


def test_transport_blocks_cgnat_address(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_a, **_k: _addrinfo("100.64.1.1"))
    transport = SafeHTTPTransport()
    request = httpx.Request("GET", "https://internal.example.com/")
    with pytest.raises(UnsafeURLError):
        transport.handle_request(request)


def test_transport_blocks_ipv4_mapped_cgnat_address(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda *_a, **_k: _addrinfo("::ffff:100.64.1.1")
    )
    transport = SafeHTTPTransport()
    request = httpx.Request("GET", "https://internal.example.com/")
    with pytest.raises(UnsafeURLError):
        transport.handle_request(request)


def test_transport_allows_public_address(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_a, **_k: _addrinfo("93.184.216.34"))
    expected = httpx.Response(200, request=httpx.Request("GET", "https://example.com/"))
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", lambda self, request: expected)
    transport = SafeHTTPTransport()
    request = httpx.Request("GET", "https://example.com/")
    assert transport.handle_request(request) is expected


def test_transport_rejects_non_http_scheme() -> None:
    transport = SafeHTTPTransport()
    request = httpx.Request("GET", "file:///etc/passwd")
    with pytest.raises(UnsafeURLError):
        transport.handle_request(request)


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
        lambda *_a, **_k: [
            (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2606:4700:4700::1111", 0, 0, 0))
        ],
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


class _FakeStreamResponse:
    def __init__(
        self, status_code: int, body: bytes, headers: dict[str, str] | None = None
    ) -> None:
        self.status_code = status_code
        self.headers = httpx.Headers(headers or {})
        self._body = body
        self.request = httpx.Request("GET", "https://example.com/jobs")

    def iter_bytes(self) -> Iterator[bytes]:
        chunk_size = 64
        for i in range(0, len(self._body), chunk_size):
            yield self._body[i : i + chunk_size]


class _FakeStreamClient:
    def __init__(self, response: _FakeStreamResponse) -> None:
        self._response = response

    @contextmanager
    def stream(self, method: str, url: str, **_: object) -> Iterator[_FakeStreamResponse]:
        yield self._response


def test_safe_get_maps_429_to_rate_limit_error() -> None:
    client = _FakeStreamClient(_FakeStreamResponse(429, b"{}"))
    with pytest.raises(RateLimitError):
        safe_get(client, "https://example.com/jobs")


def test_safe_get_maps_401_to_access_denied_error() -> None:
    client = _FakeStreamClient(_FakeStreamResponse(401, b"{}"))
    with pytest.raises(AccessDeniedError):
        safe_get(client, "https://example.com/jobs")


def test_safe_get_maps_403_to_access_denied_error() -> None:
    client = _FakeStreamClient(_FakeStreamResponse(403, b"{}"))
    with pytest.raises(AccessDeniedError):
        safe_get(client, "https://example.com/jobs")


def test_safe_get_maps_other_4xx_to_collector_error() -> None:
    client = _FakeStreamClient(_FakeStreamResponse(418, b"{}"))
    with pytest.raises(CollectorError):
        safe_get(client, "https://example.com/jobs")


def test_safe_get_enforces_response_size_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "collector_max_response_bytes", 10)
    client = _FakeStreamClient(_FakeStreamResponse(200, b"x" * 1000))
    with pytest.raises(CollectorError):
        safe_get(client, "https://example.com/jobs")


def test_safe_get_returns_full_response_on_success() -> None:
    client = _FakeStreamClient(_FakeStreamResponse(200, b'{"ok": true}'))
    response = safe_get(client, "https://example.com/jobs")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_safe_get_strips_stale_content_encoding_header() -> None:
    client = _FakeStreamClient(
        _FakeStreamResponse(
            200,
            b'{"ok": true}',
            headers={"content-encoding": "gzip", "content-length": "999"},
        )
    )
    response = safe_get(client, "https://example.com/jobs")
    assert "content-encoding" not in response.headers
    # httpx recomputes content-length from the actual bytes on construction;
    # the point is the stale "999" value from the fake upstream is gone.
    assert response.headers["content-length"] == str(len(b'{"ok": true}'))
