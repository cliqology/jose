from collections.abc import Iterable
from typing import Any

from jose.collectors.base import CollectedJob, CollectionResult, CollectorError
from jose.collectors.http import create_http_client, safe_get
from jose.collectors.utils import find_json_ld_postings, html_to_text, parse_datetime


class JsonLdCollector:
    name = "jsonld"

    def collect(self, source_name: str, source_url: str) -> CollectionResult:
        with create_http_client() as client:
            response = safe_get(client, source_url)

        postings = find_json_ld_postings(response.text)

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
        return CollectionResult(jobs=jobs)

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
