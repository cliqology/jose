from urllib.parse import urlsplit

from jose.collectors.ashby import AshbyCollector
from jose.collectors.base import Collector, UnsupportedSourceError
from jose.collectors.greenhouse import GreenhouseCollector
from jose.collectors.jsonld import JsonLdCollector
from jose.collectors.lever import LeverCollector

COLLECTORS: dict[str, Collector] = {
    "ashby": AshbyCollector(),
    "greenhouse": GreenhouseCollector(),
    "lever": LeverCollector(),
    "jsonld": JsonLdCollector(),
}

_ATS_HOSTS: dict[str, str] = {
    "jobs.ashbyhq.com": "ashby",
    "boards.greenhouse.io": "greenhouse",
    "job-boards.greenhouse.io": "greenhouse",
    "jobs.lever.co": "lever",
}


def match_known_ats_host(host: str) -> str | None:
    return _ATS_HOSTS.get(host.lower())


def detect_adapter(source_url: str, requested: str = "auto") -> str:
    if requested != "auto":
        return requested
    host = urlsplit(source_url).netloc.lower()
    return match_known_ats_host(host) or "jsonld"


def get_collector(source_url: str, requested: str = "auto") -> Collector:
    adapter = detect_adapter(source_url, requested)
    collector = COLLECTORS.get(adapter)
    if collector is None:
        raise UnsupportedSourceError(f"Unsupported collector adapter: {adapter}")
    return collector
