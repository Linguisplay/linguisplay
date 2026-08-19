import time as _time_mod
from datetime import datetime, time

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import User
from ..schemas import LoginIn, ResetIn, SessionUser, SignupIn
from ..security import hash_password, is_adult, make_session_token, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()

# 🔐 撞库防线 (2026-08-19 上线准备): SSH 一周挨 2.9 万次暴破, HTTP 登录口公开后
# 只会更多。同邮箱 15 分钟 5 次密码错误锁窗 (成功清零); 同 IP 每小时 10 次注册
# (刷小号绕每日配额的路顺手堵上)。进程内字典足矣 — 单进程部署, 重启清零可接受。
_FAIL_WINDOW, _FAIL_MAX = 15 * 60, 5
_LOGIN_FAILS: dict[str, list[float]] = {}
_SIGNUP_WINDOW, _SIGNUP_MAX = 3600, 10
_SIGNUP_HITS: dict[str, list[float]] = {}


def _over_limit(bucket: dict[str, list[float]], key: str,
                window: int, cap: int) -> bool:
    """滚动窗口计数: 顺手把过期时间戳扫掉, 字典不会无限长胖。"""
    now = _time_mod.time()
    bucket[key] = [t for t in bucket.get(key, []) if now - t < window]
    return len(bucket[key]) >= cap


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
def signup(body: SignupIn, request: Request, response: Response,
           db: Session = Depends(get_db)):
    ip = request.client.host if request.client else "?"
    if _over_limit(_SIGNUP_HITS, ip, _SIGNUP_WINDOW, _SIGNUP_MAX):
        raise HTTPException(429, "注册太频繁了，过一会儿再来")
    _SIGNUP_HITS.setdefault(ip, []).append(_time_mod.time())
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
    # 🧩 对齐包B: @handle 也在注册屏收 (可空); 校验与查重走同一入口
    if (body.handle or "").strip():
        from .me import claim_handle
        claim_handle(db, user, body.handle)
    db.add(user)
    try:
        db.commit()
    except IntegrityError as e:
        # 查重是先查后写, 并发缝里由唯一索引兜底 —— 翻译成人话而不是 500
        db.rollback()
        if "handle" in str(getattr(e, "orig", e)):
            raise HTTPException(409, "这个用户名已经有人用了")
        raise HTTPException(400, "email already registered")
    db.refresh(user)
    _set_session_cookie(response, user.id)
    return SessionUser(id=user.id, email=user.email, display_name=user.display_name,
                       handle=user.handle)


@router.post("/login", response_model=SessionUser)
def login(body: LoginIn, response: Response, db: Session = Depends(get_db)):
    key = body.email.lower()
    # 锁的是「尝试」不是「密码对错」— 窗口内连对的密码也得等, 不给暴破者反馈信号
    if _over_limit(_LOGIN_FAILS, key, _FAIL_WINDOW, _FAIL_MAX):
        raise HTTPException(429, "尝试次数太多，15 分钟后再试")
    user = db.query(User).filter(User.email == key).first()
    if not user or not verify_password(body.password, user.password_hash):
        _LOGIN_FAILS.setdefault(key, []).append(_time_mod.time())
        raise HTTPException(401, "invalid email or password")
    _LOGIN_FAILS.pop(key, None)
    _set_session_cookie(response, user.id)
    return SessionUser(id=user.id, email=user.email, display_name=user.display_name)


@router.post("/logout", status_code=204)
def logout(response: Response):
    response.delete_cookie(settings.cookie_name, path="/")


@router.post("/reset", status_code=202)
def reset(body: ResetIn):
    # Always 202 to avoid email enumeration. Real email dispatch lands in M3.
    return None
