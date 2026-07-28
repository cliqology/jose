from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol


@dataclass(slots=True)
class CollectedJob:
    company_name: str
    title: str
    application_url: str
    source_job_url: str | None = None
    description_text: str | None = None
    description_html: str | None = None
    department: str | None = None
    location: str | None = None
    remote_type: str | None = None
    employment_type: str | None = None
    compensation_min: int | None = None
    compensation_max: int | None = None
    currency: str | None = None
    ats_type: str | None = None
    external_job_id: str | None = None
    published_at: datetime | None = None
    raw_payload: dict[str, Any] = field(default_factory=dict)


class CollectorError(RuntimeError):
    pass


class UnsupportedSourceError(CollectorError):
    pass


class Collector(Protocol):
    name: str

    def collect(self, source_name: str, source_url: str) -> list[CollectedJob]: ...
