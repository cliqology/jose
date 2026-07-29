import logging
from urllib.parse import urlsplit

from jose.collectors.base import CollectedJob, CollectionResult, CollectorError
from jose.collectors.http import create_http_client, safe_get
from jose.collectors.utils import html_to_text, parse_datetime

logger = logging.getLogger(__name__)


def _as_integer_compensation(value: object) -> int | None:
    # Ashby represents hourly-rate comp as a fractional dollar amount (e.g. 60.58);
    # our schema stores whole-dollar integers, so a non-integer value is unknown,
    # not something to round or truncate.
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


class AshbyCollector:
    name = "ashby"

    def collect(self, source_name: str, source_url: str) -> CollectionResult:
        board_name = urlsplit(source_url).path.strip("/").split("/")[0]
        if not board_name:
            raise CollectorError("Unable to determine Ashby job-board name")

        endpoint = f"https://api.ashbyhq.com/posting-api/job-board/{board_name}"
        with create_http_client() as client:
            response = safe_get(client, endpoint, params={"includeCompensation": "true"})
            data = response.json()

        if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
            raise CollectorError(f"Unexpected Ashby response shape from {endpoint}")

        jobs: list[CollectedJob] = []
        rejected_count = 0
        for item in data["jobs"]:
            if not isinstance(item, dict):
                logger.warning("Skipping non-dict Ashby job entry: %r", item)
                rejected_count += 1
                continue

            application_url = item.get("applyUrl") or item.get("jobUrl")
            if not application_url:
                logger.warning(
                    "Skipping Ashby job missing application URL: id=%s title=%s",
                    item.get("id"),
                    item.get("title"),
                )
                rejected_count += 1
                continue

            compensation = item.get("compensation") or {}
            salary_components = [
                component
                for component in compensation.get("summaryComponents", [])
                if component.get("compensationType") == "Salary"
            ]
            salary = salary_components[0] if salary_components else {}
            jobs.append(
                CollectedJob(
                    company_name=source_name,
                    title=item.get("title") or "Untitled role",
                    application_url=application_url,
                    source_job_url=item.get("jobUrl"),
                    description_text=item.get("descriptionPlain")
                    or html_to_text(item.get("descriptionHtml")),
                    description_html=item.get("descriptionHtml"),
                    department=item.get("department") or item.get("team"),
                    location=item.get("location"),
                    remote_type=item.get("workplaceType")
                    or ("Remote" if item.get("isRemote") else None),
                    employment_type=item.get("employmentType"),
                    compensation_min=_as_integer_compensation(salary.get("minValue")),
                    compensation_max=_as_integer_compensation(salary.get("maxValue")),
                    currency=salary.get("currencyCode"),
                    ats_type="ashby",
                    external_job_id=item.get("id") or item.get("jobUrl"),
                    published_at=parse_datetime(item.get("publishedAt")),
                    raw_payload=item,
                )
            )
        return CollectionResult(jobs=jobs, rejected_count=rejected_count)
