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


def detect_adapter(source_url: str, requested: str = "auto") -> str:
    if requested != "auto":
        return requested
    host = urlsplit(source_url).netloc.lower()
    if host == "jobs.ashbyhq.com":
        return "ashby"
    if host in {"boards.greenhouse.io", "job-boards.greenhouse.io"}:
        return "greenhouse"
    if host == "jobs.lever.co":
        return "lever"
    return "jsonld"


def get_collector(source_url: str, requested: str = "auto") -> Collector:
    adapter = detect_adapter(source_url, requested)
    collector = COLLECTORS.get(adapter)
    if collector is None:
        raise UnsupportedSourceError(f"Unsupported collector adapter: {adapter}")
    return collector
