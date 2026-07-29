import json
import uuid
from typing import Any, Literal
from urllib.parse import urlsplit

from bs4 import BeautifulSoup
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from jose.collectors.base import CollectorError
from jose.collectors.http import create_http_client, safe_get
from jose.collectors.registry import match_known_ats_host
from jose.models import Source, User
from jose.models.base import utcnow

AGGREGATOR_SIGNATURES: dict[str, str] = {
    "getro.com": "getro",
}

DetectionStatus = Literal["supported", "unsupported", "uncertain", "error"]


class ProbeOutcome(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: DetectionStatus
    adapter: str | None
    detected_platform: str | None
    detected_application_url: str | None
    error: str | None


def _has_job_posting(value: Any) -> bool:
    if isinstance(value, dict):
        if value.get("@type") == "JobPosting":
            return True
        graph = value.get("@graph")
        if graph and _has_job_posting(graph):
            return True
        return any(
            _has_job_posting(child)
            for key, child in value.items()
            if key != "@graph" and isinstance(child, (dict, list))
        )
    if isinstance(value, list):
        return any(_has_job_posting(item) for item in value)
    return False


def _contains_json_ld_job_posting(html: str) -> bool:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            parsed = json.loads(tag.string or tag.get_text())
        except json.JSONDecodeError:
            continue
        if _has_job_posting(parsed):
            return True
    return False


def _match_aggregator_signature(host: str, html: str) -> str | None:
    for needle, platform in AGGREGATOR_SIGNATURES.items():
        if needle in host or needle in html:
            return platform
    return None


def probe_source(url: str) -> ProbeOutcome:
    try:
        with create_http_client() as client:
            response = safe_get(client, url)
    except CollectorError as exc:
        return ProbeOutcome(
            status="error",
            adapter=None,
            detected_platform=None,
            detected_application_url=None,
            error=str(exc),
        )

    final_url = str(response.url)
    host = urlsplit(final_url).netloc.lower()
    html = response.text

    matched_adapter = match_known_ats_host(host)
    if matched_adapter:
        return ProbeOutcome(
            status="supported",
            adapter=matched_adapter,
            detected_platform=matched_adapter,
            detected_application_url=final_url,
            error=None,
        )

    if _contains_json_ld_job_posting(html):
        return ProbeOutcome(
            status="supported",
            adapter="jsonld",
            detected_platform="jsonld",
            detected_application_url=final_url,
            error=None,
        )

    aggregator = _match_aggregator_signature(host, html)
    if aggregator:
        return ProbeOutcome(
            status="unsupported",
            adapter="unsupported",
            detected_platform=aggregator,
            detected_application_url=final_url,
            error=None,
        )

    return ProbeOutcome(
        status="uncertain",
        adapter="unsupported",
        detected_platform=None,
        detected_application_url=final_url,
        error=None,
    )


class ProbeResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_id: uuid.UUID
    source_name: str
    status: DetectionStatus
    adapter: str | None
    detected_platform: str | None
    detected_application_url: str | None
    error: str | None


def detect_platforms_for_vc_sources(session: Session, user: User) -> list[ProbeResult]:
    sources = list(
        session.scalars(
            select(Source).where(
                Source.user_id == user.id, Source.category == "vc_portfolio"
            )
        ).all()
    )

    results: list[ProbeResult] = []
    for source in sources:
        outcome = probe_source(source.url)
        if outcome.status != "error":
            source.adapter = outcome.adapter
        else:
            source.last_error = outcome.error
        source.detected_platform = outcome.detected_platform
        source.detection_status = outcome.status
        source.detected_application_url = outcome.detected_application_url
        source.detected_at = utcnow()
        results.append(
            ProbeResult(
                source_id=source.id,
                source_name=source.name,
                status=outcome.status,
                adapter=outcome.adapter,
                detected_platform=outcome.detected_platform,
                detected_application_url=outcome.detected_application_url,
                error=outcome.error,
            )
        )

    session.commit()
    return results


def render_source_catalog(session: Session, user: User) -> str:
    sources = list(
        session.scalars(
            select(Source)
            .where(Source.user_id == user.id, Source.category == "vc_portfolio")
            .order_by(Source.name)
        ).all()
    )

    lines = [
        "# Source Catalog: VC Portfolio Boards",
        "",
        "Generated by `python -m jose.cli detect-vc-platforms`. The table below is "
        "overwritten on every run — add manual research findings in the Notes section "
        "at the bottom instead.",
        "",
        "| Source | Configured URL | Detected Platform | "
        "Adapter / Status | Detected Application URL |",
        "| --- | --- | --- | --- | --- |",
    ]
    for source in sources:
        status = source.detection_status or "not probed"
        platform = source.detected_platform or "—"
        app_url = source.detected_application_url or "—"
        lines.append(
            f"| {source.name} | {source.url} | {platform} | "
            f"{source.adapter} / {status} | {app_url} |"
        )
    lines.extend(["", "## Notes", "", "_Add manual research findings here._"])
    return "\n".join(lines) + "\n"
