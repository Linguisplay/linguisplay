from fastapi import Cookie, Depends, HTTPException
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import User
from .security import read_session_token

settings = get_settings()


def current_user(
    lp_session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
) -> User:
    if not lp_session:
        raise HTTPException(401, "not authenticated")
    user_id = read_session_token(lp_session)
    if not user_id:
        raise HTTPException(401, "invalid session")
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(401, "user not found")
    return user
