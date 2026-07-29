import logging
from urllib.parse import parse_qs, urlsplit

from jose.collectors.base import CollectedJob, CollectionResult, CollectorError
from jose.collectors.http import create_http_client, safe_get
from jose.collectors.utils import html_to_text, parse_datetime

logger = logging.getLogger(__name__)


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

    def collect(self, source_name: str, source_url: str) -> CollectionResult:
        token = self._board_token(source_url)
        endpoint = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs"
        with create_http_client() as client:
            response = safe_get(client, endpoint, params={"content": "true"})
            data = response.json()

        if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
            raise CollectorError(f"Unexpected Greenhouse response shape from {endpoint}")

        jobs: list[CollectedJob] = []
        rejected_count = 0
        for item in data["jobs"]:
            if not isinstance(item, dict):
                logger.warning("Skipping non-dict Greenhouse job entry: %r", item)
                rejected_count += 1
                continue

            application_url = item.get("absolute_url")
            if not application_url:
                logger.warning(
                    "Skipping Greenhouse job missing application URL: id=%s title=%s",
                    item.get("id"),
                    item.get("title"),
                )
                rejected_count += 1
                continue

            departments = item.get("departments") or []
            jobs.append(
                CollectedJob(
                    company_name=item.get("company_name") or source_name,
                    title=item.get("title") or "Untitled role",
                    application_url=application_url,
                    source_job_url=application_url,
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
        return CollectionResult(jobs=jobs, rejected_count=rejected_count)
