import json
from collections.abc import Iterable
from typing import Any

import httpx
from bs4 import BeautifulSoup

from jose.collectors.base import CollectedJob, CollectorError
from jose.collectors.utils import html_to_text, parse_datetime
from jose.config import get_settings


class JsonLdCollector:
    name = "jsonld"

    def collect(self, source_name: str, source_url: str) -> list[CollectedJob]:
        with httpx.Client(
            timeout=get_settings().collector_timeout_seconds, follow_redirects=True
        ) as client:
            response = client.get(source_url)
            response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        postings: list[dict[str, Any]] = []
        for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
            try:
                parsed = json.loads(tag.string or tag.get_text())
            except json.JSONDecodeError:
                continue
            postings.extend(self._find_postings(parsed))

        if not postings:
            raise CollectorError("No JSON-LD JobPosting records found")

        jobs: list[CollectedJob] = []
        for item in postings:
            organization = item.get("hiringOrganization") or {}
            location = self._location(item.get("jobLocation"))
            jobs.append(
                CollectedJob(
                    company_name=organization.get("name") or source_name,
                    title=item.get("title") or "Untitled role",
                    application_url=item.get("url") or source_url,
                    source_job_url=item.get("url") or source_url,
                    description_text=html_to_text(item.get("description")),
                    description_html=item.get("description"),
                    location=location,
                    remote_type=item.get("jobLocationType"),
                    employment_type=self._first(item.get("employmentType")),
                    ats_type="jsonld",
                    external_job_id=str(item.get("identifier") or item.get("url") or ""),
                    published_at=parse_datetime(item.get("datePosted")),
                    raw_payload=item,
                )
            )
        return jobs

    def _find_postings(self, value: Any) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        if isinstance(value, dict):
            if value.get("@type") == "JobPosting":
                results.append(value)
            graph = value.get("@graph")
            if graph:
                results.extend(self._find_postings(graph))
            for key, child in value.items():
                if key != "@graph" and isinstance(child, (dict, list)):
                    results.extend(self._find_postings(child))
        elif isinstance(value, list):
            for child in value:
                results.extend(self._find_postings(child))
        return results

    @staticmethod
    def _location(value: Any) -> str | None:
        entries: Iterable[Any] = value if isinstance(value, list) else [value]
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            address = entry.get("address") or {}
            parts = [
                address.get("addressLocality"),
                address.get("addressRegion"),
                address.get("addressCountry"),
            ]
            result = ", ".join(str(part) for part in parts if part)
            if result:
                return result
        return None

    @staticmethod
    def _first(value: Any) -> str | None:
        if isinstance(value, list):
            return str(value[0]) if value else None
        return str(value) if value else None
