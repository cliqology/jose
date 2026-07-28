import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from jose.models import Source, User
from jose.schemas import SourceCreate, SourceUpdate


class SourceNotFoundError(Exception):
    pass


class DuplicateSourceUrlError(Exception):
    pass


class DeleteConfirmationRequiredError(Exception):
    pass


def list_sources(session: Session, user: User) -> list[Source]:
    return list(
        session.scalars(
            select(Source)
            .where(Source.user_id == user.id)
            .order_by(Source.priority, Source.name)
        ).all()
    )


def get_source(session: Session, user: User, source_id: uuid.UUID) -> Source:
    source = session.scalar(
        select(Source).where(Source.id == source_id, Source.user_id == user.id)
    )
    if not source:
        raise SourceNotFoundError(str(source_id))
    return source


def _raise_if_duplicate_url(
    session: Session, user: User, url: str, *, exclude_id: uuid.UUID | None = None
) -> None:
    query = select(Source).where(Source.user_id == user.id, Source.url == url)
    if exclude_id is not None:
        query = query.where(Source.id != exclude_id)
    if session.scalar(query):
        raise DuplicateSourceUrlError(url)


def create_source(session: Session, user: User, payload: SourceCreate) -> Source:
    url = str(payload.url)
    _raise_if_duplicate_url(session, user, url)

    data = payload.model_dump(mode="json")
    data["url"] = url
    source = Source(user_id=user.id, **data)
    session.add(source)
    session.commit()
    session.refresh(source)
    return source


def update_source(
    session: Session, user: User, source_id: uuid.UUID, payload: SourceUpdate
) -> Source:
    source = get_source(session, user, source_id)
    data = payload.model_dump(mode="json", exclude_unset=True)

    if "url" in data and data["url"] is not None:
        _raise_if_duplicate_url(session, user, data["url"], exclude_id=source.id)

    for field, value in data.items():
        setattr(source, field, value)

    session.commit()
    session.refresh(source)
    return source


def delete_source(session: Session, user: User, source_id: uuid.UUID, confirm: bool) -> None:
    source = get_source(session, user, source_id)
    if not confirm:
        raise DeleteConfirmationRequiredError(str(source_id))
    session.delete(source)
    session.commit()
