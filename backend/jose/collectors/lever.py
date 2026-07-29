from urllib.parse import urlsplit

from jose.collectors.base import CollectedJob, CollectionResult, CollectorError
from jose.collectors.http import create_http_client, safe_get
from jose.collectors.utils import html_to_text, parse_datetime


class LeverCollector:
    name = "lever"

    def collect(self, source_name: str, source_url: str) -> CollectionResult:
        parts = [part for part in urlsplit(source_url).path.split("/") if part]
        if not parts:
            raise CollectorError("Unable to determine Lever site name")
        site = parts[0]
        endpoint = f"https://api.lever.co/v0/postings/{site}"
        with create_http_client() as client:
            response = safe_get(client, endpoint, params={"mode": "json"})
            data = response.json()

        jobs: list[CollectedJob] = []
        for item in data:
            categories = item.get("categories") or {}
            description_html = item.get("description") or item.get("descriptionBody")
            jobs.append(
                CollectedJob(
                    company_name=source_name,
                    title=item.get("text") or "Untitled role",
                    application_url=item.get("applyUrl") or item.get("hostedUrl"),
                    source_job_url=item.get("hostedUrl"),
                    description_text=html_to_text(description_html),
                    description_html=description_html,
                    department=categories.get("department") or categories.get("team"),
                    location=categories.get("location"),
                    remote_type=categories.get("commitment"),
                    employment_type=categories.get("commitment"),
                    ats_type="lever",
                    external_job_id=item.get("id"),
                    published_at=parse_datetime(item.get("createdAt")),
                    raw_payload=item,
                )
            )
        return CollectionResult(jobs=jobs)
