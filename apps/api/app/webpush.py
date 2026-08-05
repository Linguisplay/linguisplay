# -*- coding: utf-8 -*-
"""🔔 Web Push (活世界 P3): 角色把话推到玩家的现实世界.

法度: VAPID 密钥不配 = 整层静默降级 (dev/测试环境天然关闭);
死信箱 (404/410) 自动剪除; 静默时段 (Asia/Shanghai 墙钟) 不敲窗 —
推送只是敲窗, 消息本体永远躺在小手机账本里, 错过敲窗不错过消息.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from .config import get_settings

try:
    from pywebpush import webpush as _webpush
except Exception:                     # dep missing → layer disabled
    _webpush = None

try:
    from zoneinfo import ZoneInfo
    _TZ = ZoneInfo("Asia/Shanghai")
except Exception:                     # Windows without tzdata — 上海无夏令时, 固定 +8 等价
    _TZ = timezone(timedelta(hours=8))


def enabled() -> bool:
    s = get_settings()
    return bool(_webpush and s.vapid_private_key and s.vapid_public_key)


def quiet_now(now: datetime | None = None, tz: str = "") -> bool:
    """深夜敲窗是差评之源。按【玩家本地】的钟点判, 跨零点也算得对。

    tz 是 IANA 名 (来自 run.state["tz"])。空/认不出 → 退回服务器时区 (+8),
    与这个参数存在之前逐位相同 —— 从前全船都按北京的夜算, 纽约的玩家在他自己的
    下午被判成"深夜"。"""
    s = get_settings()
    _tz = _TZ
    if tz:
        try:
            from zoneinfo import ZoneInfo
            _tz = ZoneInfo(tz)
        except Exception:
            pass
    h = (now or datetime.now(_tz)).hour
    start, end = int(s.push_quiet_start), int(s.push_quiet_end)
    if start == end:
        return False
    if start < end:
        return start <= h < end
    return h >= start or h < end


def send_one(sub: dict[str, Any], payload: dict[str, Any]) -> str:
    """One mailbox. Returns ok | gone | fail — gone means prune the row."""
    if not enabled():
        return "fail"
    s = get_settings()
    try:
        _webpush(subscription_info=sub,
                 data=json.dumps(payload, ensure_ascii=False),
                 vapid_private_key=s.vapid_private_key,
                 vapid_claims={"sub": s.vapid_sub},
                 ttl=24 * 3600)
        return "ok"
    except Exception as e:
        code = getattr(getattr(e, "response", None), "status_code", None)
        return "gone" if code in (404, 410) else "fail"


def push_to_user(db, owner_id: str, title: str, body: str,
                 url: str = "/play", tag: str = "lp") -> int:
    """Every mailbox this user registered; prunes the dead. Returns delivered count."""
    if not enabled():
        return 0
    from .models import PushSub
    sent = 0
    rows = db.query(PushSub).filter(PushSub.owner_id == owner_id).all()
    for row in rows:
        r = send_one({"endpoint": row.endpoint,
                      "keys": {"p256dh": row.p256dh, "auth": row.auth}},
                     {"title": title[:60], "body": body[:140], "url": url, "tag": tag})
        if r == "ok":
            sent += 1
        elif r == "gone":
            db.delete(row)
    db.commit()
    return sent
