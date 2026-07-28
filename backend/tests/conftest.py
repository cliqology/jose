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
