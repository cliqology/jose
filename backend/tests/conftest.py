import uuid
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from jose.api.main import app
from jose.db.session import SessionLocal
from jose.models import User


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def make_user(session: Session, *, email: str | None = None) -> User:
    user = User(email=email or f"test-{uuid.uuid4()}@example.com")
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


@pytest.fixture
def user(db_session: Session) -> Generator[User, None, None]:
    created = make_user(db_session)
    try:
        yield created
    finally:
        db_session.delete(created)
        db_session.commit()


@pytest.fixture
def other_user(db_session: Session) -> Generator[User, None, None]:
    created = make_user(db_session)
    try:
        yield created
    finally:
        db_session.delete(created)
        db_session.commit()


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as test_client:
        yield test_client


def _make_company(session, user, name="Acme"):
    from jose.models import Company

    company = Company(user_id=user.id, name=name, normalized_name=name.lower())
    session.add(company)
    session.flush()
    return company


def _make_job(session, user, company, **overrides):
    import uuid as _uuid

    from jose.models import Job

    defaults = dict(
        user_id=user.id,
        company_id=company.id,
        title="Software Engineer",
        normalized_title="software engineer",
        location="San Francisco, CA",
        application_url="https://acme.example.com/jobs/1",
        canonical_url="https://acme.example.com/jobs/1",
        fingerprint=_uuid.uuid4().hex,
        content_hash=_uuid.uuid4().hex,
    )
    defaults.update(overrides)
    job = Job(**defaults)
    session.add(job)
    session.flush()
    return job


def _make_candidate(session, user, job, candidate_job, **overrides):
    from jose.models import JobMergeCandidate

    defaults = dict(
        user_id=user.id,
        job_id=job.id,
        candidate_job_id=candidate_job.id,
        similarity_score=0.9,
        matched_signals={"company": 1.0, "title": 1.0, "location": 1.0},
        status="pending",
    )
    defaults.update(overrides)
    candidate = JobMergeCandidate(**defaults)
    session.add(candidate)
    session.flush()
    return candidate
