import uuid
from typing import Literal
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from jose.collectors.base import CollectorError
from jose.collectors.http import create_http_client, safe_get
from jose.collectors.registry import match_known_ats_host
from jose.collectors.utils import find_json_ld_postings
from jose.models import Source, User
from jose.models.base import utcnow
from jose.services.error_sanitizer import sanitize_error_text

AGGREGATOR_SIGNATURES: dict[str, str] = {
    "getro.com": "getro",
    "consider.com": "consider",
}

DetectionStatus = Literal["supported", "unsupported", "uncertain", "error"]


class ProbeOutcome(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: DetectionStatus
    adapter: str | None
    detected_platform: str | None
    detected_application_url: str | None
    error: str | None


def _contains_json_ld_job_posting(html: str) -> bool:
    return bool(find_json_ld_postings(html))


def _match_aggregator_signature(host: str, html: str) -> str | None:
    for needle, platform in AGGREGATOR_SIGNATURES.items():
        if needle in host or needle in html:
            return platform
    return None


def probe_source(url: str) -> ProbeOutcome:
    try:
        with create_http_client() as client:
            response = safe_get(client, url)
    except (CollectorError, httpx.HTTPError) as exc:
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
        try:
            outcome = probe_source(source.url)
        except Exception as exc:  # noqa: BLE001 - a bad source must never abort the batch
            outcome = ProbeOutcome(
                status="error",
                adapter=None,
                detected_platform=None,
                detected_application_url=None,
                error=str(exc),
            )

        if outcome.status != "error":
            source.adapter = outcome.adapter
            source.detected_platform = outcome.detected_platform
            source.detected_application_url = outcome.detected_application_url
            source.last_error = None
        else:
            # `outcome.error` may come from `probe_source`'s own internal
            # CollectorError/httpx.HTTPError handling (the common case, which never
            # raises past this point) or from the `except Exception` above (an
            # unexpected escape). Sanitize at this single assignment point so
            # `Source.last_error` — rendered in full on the source detail page —
            # never carries a secret regardless of which path produced the text.
            source.last_error = sanitize_error_text(outcome.error) if outcome.error else None
        source.detection_status = outcome.status
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
