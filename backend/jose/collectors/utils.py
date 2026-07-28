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
