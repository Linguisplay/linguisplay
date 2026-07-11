# -*- coding: utf-8 -*-
"""🔔 Web Push 订阅管理 (活世界 P3). 订阅随浏览器走, 归属随登录人走."""
from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import webpush
from ..config import get_settings
from ..db import get_db
from ..deps import current_user
from ..models import PushSub, User

router = APIRouter(prefix="/push", tags=["push"])


@router.get("/vapid")
def vapid_key():
    """The applicationServerKey the browser needs to mint a subscription."""
    s = get_settings()
    if not s.vapid_public_key:
        raise HTTPException(503, "推送未配置")
    return {"key": s.vapid_public_key}


@router.post("/subscribe")
def subscribe(body: dict = Body(...), user: User = Depends(current_user),
              db: Session = Depends(get_db)):
    ep = str(body.get("endpoint") or "").strip()
    keys = body.get("keys") or {}
    if not ep or not keys.get("p256dh") or not keys.get("auth"):
        raise HTTPException(400, "订阅数据不完整")
    row = db.query(PushSub).filter(PushSub.endpoint == ep).first()
    if row:   # 换号登录同一浏览器 → 信箱跟人走
        row.owner_id, row.p256dh, row.auth = user.id, keys["p256dh"], keys["auth"]
    else:
        db.add(PushSub(owner_id=user.id, endpoint=ep,
                       p256dh=keys["p256dh"], auth=keys["auth"]))
    db.commit()
    return {"ok": True}


@router.post("/unsubscribe")
def unsubscribe(body: dict = Body(default={}), user: User = Depends(current_user),
                db: Session = Depends(get_db)):
    ep = str(body.get("endpoint") or "").strip()
    if ep:
        db.query(PushSub).filter(PushSub.endpoint == ep,
                                 PushSub.owner_id == user.id).delete()
        db.commit()
    return {"ok": True}


@router.post("/test")
def push_test(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """自检一条 (无视静默时段 — 按钮是你自己按的)."""
    n = webpush.push_to_user(db, user.id, "LinguisPlay",
                             "推送通道已打通。角色现在能找到你了。")
    return {"sent": n}
