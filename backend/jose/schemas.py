import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class SourceCategory(StrEnum):
    VC_PORTFOLIO = "vc_portfolio"
    COMPANY_CAREER_PAGE = "company_career_page"
    ATS_JOB_BOARD = "ats_job_board"
    NEWSLETTER = "newsletter"
    TALENT_NETWORK = "talent_network"
    USER_ADDED = "user_added"


class SourceAdapter(StrEnum):
    AUTO = "auto"
    ASHBY = "ashby"
    GREENHOUSE = "greenhouse"
    LEVER = "lever"
    JSONLD = "jsonld"
    UNSUPPORTED = "unsupported"


class CollectionFrequency(StrEnum):
    HOURLY = "hourly"
    EVERY_6_HOURS = "every_6_hours"
    TWICE_DAILY = "twice_daily"
    DAILY = "daily"
    WEEKLY = "weekly"
    MANUAL = "manual"


class JobMergeAction(StrEnum):
    MERGE = "merge"
    DISMISS = "dismiss"


class JobMergeKeep(StrEnum):
    JOB = "job"
    CANDIDATE = "candidate"


class SourceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=250)
    url: HttpUrl
    category: SourceCategory = SourceCategory.USER_ADDED
    portfolio_firm: str | None = None
    adapter: SourceAdapter = SourceAdapter.AUTO
    enabled: bool = True
    priority: int = Field(default=100, ge=1, le=1000)
    collection_frequency: CollectionFrequency = CollectionFrequency.DAILY
    notes: str | None = None


class SourceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=250)
    url: HttpUrl | None = None
    category: SourceCategory | None = None
    portfolio_firm: str | None = None
    adapter: SourceAdapter | None = None
    enabled: bool | None = None
    priority: int | None = Field(default=None, ge=1, le=1000)
    collection_frequency: CollectionFrequency | None = None
    notes: str | None = None


class SourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    url: str
    category: str
    portfolio_firm: str | None
    adapter: str
    enabled: bool
    priority: int
    collection_frequency: str
    last_attempt_at: datetime | None
    last_success_at: datetime | None
    last_job_count: int | None
    last_error: str | None
    detected_platform: str | None
    detection_status: str | None
    detected_application_url: str | None
    detected_at: datetime | None


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    normalized_title: str
    location: str | None
    remote_type: str | None
    employment_type: str | None
    application_url: str
    ats_type: str | None
    published_at: datetime | None
    first_seen_at: datetime
    last_seen_at: datetime
    status: str


class JobMergeResolveRequest(BaseModel):
    action: JobMergeAction
    keep: JobMergeKeep | None = None


class JobMergeCandidateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    job_id: uuid.UUID
    candidate_job_id: uuid.UUID
    status: str
    similarity_score: float
    matched_signals: dict[str, float]
    kept_job_id: uuid.UUID | None
    merged_job_id: uuid.UUID | None
    created_at: datetime
    resolved_at: datetime | None


class JobMergeSummary(BaseModel):
    id: uuid.UUID
    title: str
    company_name: str
    location: str | None
    application_url: str
    status: str


class JobMergeCandidateListRead(BaseModel):
    id: uuid.UUID
    status: str
    similarity_score: float
    matched_signals: dict[str, float]
    created_at: datetime
    job: JobMergeSummary
    candidate_job: JobMergeSummary


class TaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    task_type: str
    status: str
    attempts: int
    payload_version: int
    scheduled_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    last_error: str | None


class QueueResponse(BaseModel):
    queued: int
    task_ids: list[uuid.UUID]


class DashboardSummary(BaseModel):
    sources_total: int
    sources_enabled: int
    sources_failing: int
    jobs_total: int
    jobs_seen_last_24h: int
    jobs_new_last_24h: int
    jobs_changed_last_24h: int
    jobs_removed_last_24h: int
    jobs_reposted_last_24h: int
    queued_tasks: int
    running_tasks: int


class ImportRowOutcomeRead(BaseModel):
    row_number: int
    name: str
    url: str
    category: str | None
    action: str
    reason: str | None


class ImportPreviewRead(BaseModel):
    filename: str
    created: int
    updated: int
    skipped: int
    flagged: int
    rows: list[ImportRowOutcomeRead]


class ImportRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    created_count: int
    updated_count: int
    skipped_count: int
    flagged_count: int
    flagged_rows: list[dict]
    completed_at: datetime
