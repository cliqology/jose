from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from jose.db.session import get_db
from jose.models import User
from jose.services.users import get_or_create_default_user

DBSession = Annotated[Session, Depends(get_db)]


def get_current_user(db: DBSession) -> User:
    return get_or_create_default_user(db)


CurrentUser = Annotated[User, Depends(get_current_user)]
