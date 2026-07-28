from urllib.parse import parse_qs, urlsplit

from jose.collectors.base import CollectedJob, CollectorError
from jose.collectors.http import create_http_client, safe_get
from jose.collectors.utils import html_to_text, parse_datetime


class GreenhouseCollector:
    name = "greenhouse"

    @staticmethod
    def _board_token(source_url: str) -> str:
        parts = urlsplit(source_url)
        path_parts = [part for part in parts.path.split("/") if part]
        if parts.netloc in {"boards.greenhouse.io", "job-boards.greenhouse.io"} and path_parts:
            return path_parts[0]
        query = parse_qs(parts.query)
        if "for" in query and query["for"]:
            return query["for"][0]
        raise CollectorError("Unable to determine Greenhouse board token")

    def collect(self, source_name: str, source_url: str) -> list[CollectedJob]:
        token = self._board_token(source_url)
        endpoint = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs"
        with create_http_client() as client:
            response = safe_get(client, endpoint, params={"content": "true"})
            data = response.json()

        jobs: list[CollectedJob] = []
        for item in data.get("jobs", []):
            departments = item.get("departments") or []
            jobs.append(
                CollectedJob(
                    company_name=source_name,
                    title=item.get("title") or "Untitled role",
                    application_url=item.get("absolute_url"),
                    source_job_url=item.get("absolute_url"),
                    description_text=html_to_text(item.get("content")),
                    description_html=item.get("content"),
                    department=departments[0].get("name") if departments else None,
                    location=(item.get("location") or {}).get("name"),
                    ats_type="greenhouse",
                    external_job_id=str(item.get("id")) if item.get("id") is not None else None,
                    published_at=parse_datetime(item.get("first_published")),
                    raw_payload=item,
                )
            )
        return jobs
