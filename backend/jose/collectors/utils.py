import difflib
import hashlib
import json
import re
from datetime import UTC, datetime
from html import unescape
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup


def normalize_whitespace(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", value).strip()


def normalize_name(value: str) -> str:
    cleaned = normalize_whitespace(value).casefold()
    return re.sub(r"[^a-z0-9]+", " ", cleaned).strip()


def normalize_title(value: str) -> str:
    return normalize_name(value)


def html_to_text(value: str | None) -> str | None:
    if not value:
        return None
    return normalize_whitespace(BeautifulSoup(unescape(value), "html.parser").get_text(" "))


def _is_job_posting_type(value: object) -> bool:
    if isinstance(value, str):
        return value == "JobPosting"
    if isinstance(value, list):
        return "JobPosting" in value
    return False


def _find_job_postings(value: object) -> list[dict]:
    results: list[dict] = []
    if isinstance(value, dict):
        if _is_job_posting_type(value.get("@type")):
            results.append(value)
        graph = value.get("@graph")
        if graph:
            results.extend(_find_job_postings(graph))
        for key, child in value.items():
            if key != "@graph" and isinstance(child, (dict, list)):
                results.extend(_find_job_postings(child))
    elif isinstance(value, list):
        for child in value:
            results.extend(_find_job_postings(child))
    return results


def find_json_ld_postings(html: str) -> list[dict]:
    """Parse `<script type="application/ld+json">` tags and return JobPosting records.

    Matches both the plain-string form (`"@type": "JobPosting"`) and schema.org's
    list form (`"@type": ["JobPosting", "SomeOtherType"]`).
    """
    soup = BeautifulSoup(html, "html.parser")
    results: list[dict] = []
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            parsed = json.loads(tag.string or tag.get_text())
        except json.JSONDecodeError:
            continue
        results.extend(_find_job_postings(parsed))
    return results


def canonicalize_url(value: str) -> str:
    parts = urlsplit(value)
    query = [
        (key, item)
        for key, item in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_")
    ]
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), parts.path, urlencode(query), "")
    )


def parse_datetime(value: str | int | float | None) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        seconds = value / 1000 if value > 10_000_000_000 else value
        try:
            return datetime.fromtimestamp(seconds, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def stable_hash(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def job_fingerprint(
    company_name: str,
    title: str,
    location: str | None,
    application_url: str,
    external_job_id: str | None,
) -> str:
    payload = {
        "company": normalize_name(company_name),
        "title": normalize_title(title),
        "location": normalize_name(location or ""),
        "url": canonicalize_url(application_url),
        "external_id": external_job_id or "",
    }
    return stable_hash(payload)


COMPANY_ALIAS_THRESHOLD = 0.6
FUZZY_MATCH_THRESHOLD = 0.80
# Same company + same location already contributes 0.6 to the composite, so any
# title ratio above 0.5 clears FUZZY_MATCH_THRESHOLD on its own. Distinct roles at
# one company ("Product Manager" vs "Product Marketing Manager", 0.750) need their
# own gate; re-titlings of one role ("Software Engineer" vs "Software Engineer II",
# 0.919) stay above it.
TITLE_MATCH_THRESHOLD = 0.85


def fuzzy_match_score(
    company_a: str,
    title_a: str,
    location_a: str,
    company_b: str,
    title_b: str,
    location_b: str,
) -> dict[str, float]:
    company = difflib.SequenceMatcher(
        None, normalize_name(company_a), normalize_name(company_b)
    ).ratio()
    title = difflib.SequenceMatcher(
        None, normalize_title(title_a), normalize_title(title_b)
    ).ratio()
    location = difflib.SequenceMatcher(
        None, normalize_name(location_a), normalize_name(location_b)
    ).ratio()
    composite = 0.5 * company + 0.4 * title + 0.1 * location
    return {"company": company, "title": title, "location": location, "composite": composite}
