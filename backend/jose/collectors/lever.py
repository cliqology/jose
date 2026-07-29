import logging
from typing import Any
from urllib.parse import urlsplit

import httpx

from jose.collectors.base import CollectedJob, CollectionResult, CollectorError
from jose.collectors.http import create_http_client, safe_get
from jose.collectors.utils import html_to_text, parse_datetime

logger = logging.getLogger(__name__)


class LeverCollector:
    name = "lever"
    PAGE_SIZE = 100
    MAX_PAGES = 50

    def collect(self, source_name: str, source_url: str) -> CollectionResult:
        parts = [part for part in urlsplit(source_url).path.split("/") if part]
        if not parts:
            raise CollectorError("Unable to determine Lever site name")
        site = parts[0]
        endpoint = f"https://api.lever.co/v0/postings/{site}"
        with create_http_client() as client:
            items = self._fetch_all_pages(client, endpoint)

        jobs: list[CollectedJob] = []
        rejected_count = 0
        for item in items:
            if not isinstance(item, dict):
                logger.warning("Skipping non-dict Lever job entry: %r", item)
                rejected_count += 1
                continue

            application_url = item.get("applyUrl") or item.get("hostedUrl")
            if not application_url:
                logger.warning(
                    "Skipping Lever job missing application URL: id=%s title=%s",
                    item.get("id"),
                    item.get("text"),
                )
                rejected_count += 1
                continue

            categories = item.get("categories") or {}
            salary_range = item.get("salaryRange") or {}
            description_html = item.get("description") or item.get("descriptionBody")
            jobs.append(
                CollectedJob(
                    company_name=source_name,
                    title=item.get("text") or "Untitled role",
                    application_url=application_url,
                    source_job_url=item.get("hostedUrl"),
                    description_text=html_to_text(description_html),
                    description_html=description_html,
                    department=categories.get("department") or categories.get("team"),
                    location=categories.get("location"),
                    remote_type=categories.get("commitment"),
                    employment_type=categories.get("commitment"),
                    compensation_min=salary_range.get("min"),
                    compensation_max=salary_range.get("max"),
                    currency=salary_range.get("currency"),
                    ats_type="lever",
                    external_job_id=item.get("id"),
                    published_at=parse_datetime(item.get("createdAt")),
                    raw_payload=item,
                )
            )
        return CollectionResult(jobs=jobs, rejected_count=rejected_count)

    def _fetch_all_pages(self, client: httpx.Client, endpoint: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        skip = 0
        for _ in range(self.MAX_PAGES):
            response = safe_get(
                client,
                endpoint,
                params={"mode": "json", "skip": skip, "limit": self.PAGE_SIZE},
            )
            data = response.json()
            if not isinstance(data, list):
                raise CollectorError(f"Unexpected Lever response shape from {endpoint}")
            items.extend(data)
            if len(data) < self.PAGE_SIZE:
                return items
            skip += self.PAGE_SIZE
        logger.warning(
            "Lever pagination hit MAX_PAGES=%s cap for %s; results may be incomplete",
            self.MAX_PAGES,
            endpoint,
        )
        return items
