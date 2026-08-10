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


def current_user_optional(
    lp_session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
) -> User | None:
    """🧩 对齐包B: 公开可读、登录更好的页面 (社区面板/评论区/作者主页) —— 未登录给
    公共视图, 登录了才有 liked/faved/following 这类「我」的态。永不 401。"""
    if not lp_session:
        return None
    user_id = read_session_token(lp_session)
    return db.get(User, user_id) if user_id else None
