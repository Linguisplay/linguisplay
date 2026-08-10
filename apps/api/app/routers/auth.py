from datetime import datetime, time

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import User
from ..schemas import LoginIn, ResetIn, SessionUser, SignupIn
from ..security import hash_password, is_adult, make_session_token, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()


def _set_session_cookie(response: Response, user_id: str) -> None:
    response.set_cookie(
        key=settings.cookie_name,
        value=make_session_token(user_id),
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=settings.session_days * 24 * 3600,
        path="/",
    )


@router.post("/signup", status_code=201, response_model=SessionUser)
def signup(body: SignupIn, response: Response, db: Session = Depends(get_db)):
    if not body.accepted_tos:
        raise HTTPException(422, "must accept Terms of Service")
    dob_dt = datetime.combine(body.dob, time.min)
    if not is_adult(dob_dt):
        raise HTTPException(422, "must be 18 or older")
    if db.query(User).filter(User.email == body.email.lower()).first():
        raise HTTPException(400, "email already registered")

    user = User(
        email=body.email.lower(),
        password_hash=hash_password(body.password),
        dob=dob_dt,
        accepted_tos=True,
        # 🧩 对齐包A: 注册屏一并收用户名, 不再逼前端注册完补一刀 PATCH /me
        display_name=(body.display_name or "").strip()[:80] or None,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    _set_session_cookie(response, user.id)
    return SessionUser(id=user.id, email=user.email, display_name=user.display_name)


@router.post("/login", response_model=SessionUser)
def login(body: LoginIn, response: Response, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == body.email.lower()).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "invalid email or password")
    _set_session_cookie(response, user.id)
    return SessionUser(id=user.id, email=user.email, display_name=user.display_name)


@router.post("/logout", status_code=204)
def logout(response: Response):
    response.delete_cookie(settings.cookie_name, path="/")


@router.post("/reset", status_code=202)
def reset(body: ResetIn):
    # Always 202 to avoid email enumeration. Real email dispatch lands in M3.
    return None
