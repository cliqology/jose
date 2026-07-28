from sqlalchemy import select
from sqlalchemy.orm import Session

from jose.config import get_settings
from jose.models import User


def get_or_create_default_user(session: Session) -> User:
    email = get_settings().jose_default_user_email.strip().lower()
    user = session.scalar(select(User).where(User.email == email))
    if user:
        return user
    user = User(email=email, display_name="Scott Hoffman")
    session.add(user)
    session.commit()
    session.refresh(user)
    return user
