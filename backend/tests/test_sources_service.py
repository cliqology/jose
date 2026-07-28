import uuid

import pytest
from sqlalchemy import select

from jose.models import Company, Job, JobSource
from jose.schemas import SourceCreate, SourceUpdate
from jose.services.sources import (
    DeleteConfirmationRequiredError,
    DuplicateSourceUrlError,
    SourceNotFoundError,
    create_source,
    delete_source,
    get_source,
    list_sources,
    update_source,
)


def test_create_source_persists_with_defaults(db_session, user):
    source = create_source(
        db_session,
        user,
        SourceCreate(name="Acme Careers", url="https://acme.example.com/careers"),
    )

    assert source.id is not None
    assert source.user_id == user.id
    assert source.name == "Acme Careers"
    assert source.url == "https://acme.example.com/careers"
    assert source.category == "user_added"
    assert source.adapter == "auto"
    assert source.enabled is True
    assert source.priority == 100


def test_create_source_duplicate_url_same_user_raises(db_session, user):
    create_source(
        db_session, user, SourceCreate(name="First", url="https://dup.example.com/jobs")
    )

    with pytest.raises(DuplicateSourceUrlError):
        create_source(
            db_session, user, SourceCreate(name="Second", url="https://dup.example.com/jobs")
        )


def test_create_source_same_url_different_user_allowed(db_session, user, other_user):
    create_source(
        db_session, user, SourceCreate(name="Mine", url="https://shared.example.com/jobs")
    )

    other_source = create_source(
        db_session,
        other_user,
        SourceCreate(name="Theirs", url="https://shared.example.com/jobs"),
    )

    assert other_source.user_id == other_user.id


def test_list_sources_only_returns_own_sources(db_session, user, other_user):
    create_source(db_session, user, SourceCreate(name="Mine", url="https://mine.example.com"))
    create_source(
        db_session, other_user, SourceCreate(name="Theirs", url="https://theirs.example.com")
    )

    results = list_sources(db_session, user)

    assert [s.name for s in results] == ["Mine"]


def test_get_source_returns_own_source(db_session, user):
    created = create_source(
        db_session, user, SourceCreate(name="Mine", url="https://get-mine.example.com")
    )

    fetched = get_source(db_session, user, created.id)

    assert fetched.id == created.id


def test_get_source_raises_for_unknown_id(db_session, user):
    with pytest.raises(SourceNotFoundError):
        get_source(db_session, user, uuid.uuid4())


def test_get_source_raises_for_other_users_source(db_session, user, other_user):
    created = create_source(
        db_session, other_user, SourceCreate(name="Theirs", url="https://get-theirs.example.com")
    )

    with pytest.raises(SourceNotFoundError):
        get_source(db_session, user, created.id)


def test_update_source_changes_fields(db_session, user):
    created = create_source(
        db_session, user, SourceCreate(name="Old Name", url="https://update-me.example.com/careers")
    )

    updated = update_source(
        db_session, user, created.id, SourceUpdate(name="New Name", priority=5)
    )

    assert updated.name == "New Name"
    assert updated.priority == 5
    assert updated.url == "https://update-me.example.com/careers"


def test_update_source_raises_for_other_users_source(db_session, user, other_user):
    created = create_source(
        db_session,
        other_user,
        SourceCreate(name="Theirs", url="https://update-theirs.example.com"),
    )

    with pytest.raises(SourceNotFoundError):
        update_source(db_session, user, created.id, SourceUpdate(name="Hijacked"))


def test_update_source_duplicate_url_raises(db_session, user):
    create_source(db_session, user, SourceCreate(name="A", url="https://a.example.com"))
    b = create_source(db_session, user, SourceCreate(name="B", url="https://b.example.com"))

    with pytest.raises(DuplicateSourceUrlError):
        update_source(db_session, user, b.id, SourceUpdate(url="https://a.example.com"))


def test_update_source_keeping_same_url_does_not_raise(db_session, user):
    created = create_source(
        db_session, user, SourceCreate(name="Same", url="https://same-url.example.com/jobs")
    )

    updated = update_source(
        db_session, user, created.id, SourceUpdate(url="https://same-url.example.com/jobs")
    )

    assert updated.url == "https://same-url.example.com/jobs"


def test_delete_source_without_confirm_raises(db_session, user):
    created = create_source(
        db_session, user, SourceCreate(name="Deletable", url="https://delete-me.example.com")
    )

    with pytest.raises(DeleteConfirmationRequiredError):
        delete_source(db_session, user, created.id, confirm=False)

    assert get_source(db_session, user, created.id) is not None


def test_delete_source_with_confirm_removes_source(db_session, user):
    created = create_source(
        db_session, user, SourceCreate(name="Deletable", url="https://delete-confirmed.example.com")
    )

    delete_source(db_session, user, created.id, confirm=True)

    with pytest.raises(SourceNotFoundError):
        get_source(db_session, user, created.id)


def test_delete_source_raises_for_other_users_source(db_session, user, other_user):
    created = create_source(
        db_session,
        other_user,
        SourceCreate(name="Theirs", url="https://delete-theirs.example.com"),
    )

    with pytest.raises(SourceNotFoundError):
        delete_source(db_session, user, created.id, confirm=True)


def _link_job_to_source(session, user, source) -> Job:
    company = Company(user_id=user.id, name="Acme", normalized_name="acme")
    session.add(company)
    session.flush()
    job = Job(
        user_id=user.id,
        company_id=company.id,
        title="COO",
        normalized_title="coo",
        application_url="https://acme.example.com/apply/1",
        canonical_url="https://acme.example.com/apply/1",
        fingerprint="fp-1",
        content_hash="hash-1",
    )
    session.add(job)
    session.flush()
    session.add(JobSource(user_id=user.id, job_id=job.id, source_id=source.id))
    session.commit()
    session.refresh(job)
    return job


def test_delete_source_does_not_delete_canonical_job_found_elsewhere(db_session, user):
    source_a = create_source(
        db_session, user, SourceCreate(name="Source A", url="https://source-a.example.com")
    )
    source_b = create_source(
        db_session, user, SourceCreate(name="Source B", url="https://source-b.example.com")
    )
    job = _link_job_to_source(db_session, user, source_a)
    db_session.add(JobSource(user_id=user.id, job_id=job.id, source_id=source_b.id))
    db_session.commit()

    delete_source(db_session, user, source_a.id, confirm=True)

    surviving_job = db_session.get(Job, job.id)
    assert surviving_job is not None
    remaining_links = db_session.scalars(
        select(JobSource).where(JobSource.job_id == job.id)
    ).all()
    assert [link.source_id for link in remaining_links] == [source_b.id]
