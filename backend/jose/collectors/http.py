import ipaddress
import socket
from typing import Any

import httpx

from jose.collectors.base import AccessDeniedError, CollectorError, RateLimitError, UnsafeURLError
from jose.config import get_settings

_CGNAT_NETWORK = ipaddress.ip_network("100.64.0.0/10")


class SafeHTTPTransport(httpx.HTTPTransport):
    def handle_request(self, request: httpx.Request) -> httpx.Response:
        url = request.url
        if url.scheme not in ("http", "https"):
            raise UnsafeURLError(f"Unsafe URL scheme: {url.scheme}")

        host = url.host
        try:
            infos = socket.getaddrinfo(host, None)
        except OSError as exc:
            raise UnsafeURLError(f"Unable to resolve host: {host}") from exc

        for _family, _type, _proto, _canonname, sockaddr in infos:
            ip = ipaddress.ip_address(sockaddr[0])
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

        return super().handle_request(request)


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

        return httpx.Response(
            status_code=response.status_code,
            headers=response.headers,
            content=bytes(body),
            request=response.request,
        )
