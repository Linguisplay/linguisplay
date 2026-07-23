# -*- coding: utf-8 -*-
"""💎 平台币 P1 影子系统 (Yi 拍板 Roblox 三阶段, 2026-07-20):
月石钱包 (首访赠 200 内测币, 不接支付) + 创作者收费包 (内容资格, 确定性发货) +
购买台账 (玩家 entitlement 与创作者 70% 分成同一张表)。
红线: 月石只买内容资格 — 不卖剧情内货币/属性直充 (开局礼包的 start_money_bonus
属于开局配置, 在拍板讨论里归为可接受)。"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_user
from ..models import PackPurchase, Story as StoryModel, StoryPack, User, Wallet
from ..schemas import LaxInt

router = APIRouter(tags=["packs"])

CURRENCY = "月石"
FIRST_GRANT = 200          # P1 内测赠币
CREATOR_SHARE_PCT = 70     # 创作者分成 (平台 30, Roblox 档)
MAX_PACKS_PER_STORY = 6
MAX_PRICE = 9999


def _wallet(db: Session, user_id: str) -> Wallet:
    w = db.get(Wallet, user_id)
    if w is None:
        w = Wallet(user_id=user_id, balance=FIRST_GRANT)
        db.add(w)
        db.commit()
        db.refresh(w)
    return w


class PackIn(BaseModel):
    name: str = ""
    desc: str = ""
    price: LaxInt = 0
    # {access?: bool, start_money_bonus?: int, powers?: [str], items?: [{name,detail}]}
    grants: dict = {}


def _pack_view(p: StoryPack, owned: bool = False) -> dict:
    return {"id": p.id, "name": p.name, "desc": p.desc, "price": p.price,
            "grants": p.grants or {}, "active": p.active, "owned": owned}


@router.get("/wallet")
def get_wallet(user: User = Depends(current_user), db: Session = Depends(get_db)):
    w = _wallet(db, user.id)
    return {"balance": w.balance, "currency": CURRENCY}


@router.get("/stories/{story_id}/packs")
def list_packs(story_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    s = db.get(StoryModel, story_id)
    if not s:
        raise HTTPException(404, "story not found")
    packs = (db.query(StoryPack).filter(StoryPack.story_id == story_id,
                                        StoryPack.active.is_(True))
             .order_by(StoryPack.created_at).all())
    owned = {pp.pack_id for pp in db.query(PackPurchase)
             .filter(PackPurchase.user_id == user.id,
                     PackPurchase.story_id == story_id).all()}
    is_owner = s.owner_id == user.id
    return {"currency": CURRENCY, "is_owner": is_owner,
            "packs": [_pack_view(p, owned=(is_owner or p.id in owned)) for p in packs]}


@router.post("/stories/{story_id}/packs")
def create_pack(story_id: str, body: PackIn,
                user: User = Depends(current_user), db: Session = Depends(get_db)):
    s = db.get(StoryModel, story_id)
    if not s or s.owner_id != user.id:
        raise HTTPException(404, "story not found")
    n = db.query(StoryPack).filter(StoryPack.story_id == story_id,
                                   StoryPack.active.is_(True)).count()
    if n >= MAX_PACKS_PER_STORY:
        raise HTTPException(400, f"一本剧本最多 {MAX_PACKS_PER_STORY} 个收费包")
    name = (body.name or "").strip()[:40]
    if not name:
        raise HTTPException(400, "收费包得有个名字")
    price = max(0, min(MAX_PRICE, int(body.price or 0)))
    p = StoryPack(story_id=story_id, name=name, desc=(body.desc or "").strip()[:200],
                  price=price, grants=_clean_grants(body.grants))
    db.add(p)
    db.commit()
    db.refresh(p)
    return _pack_view(p, owned=True)


def _clean_grants(g: dict) -> dict:
    """发货面消毒: 只认白名单键 — 收费包永远不能写任意 state。"""
    g = g or {}
    out: dict = {}
    if g.get("access"):
        out["access"] = True
    try:
        b = int(g.get("start_money_bonus") or 0)
        if b > 0:
            out["start_money_bonus"] = min(b, 9999)
    except (TypeError, ValueError):
        pass
    pw = [str(x).strip()[:40] for x in (g.get("powers") or []) if str(x).strip()][:2]
    if pw:
        out["powers"] = pw
    items = [{"name": str(i.get("name") or "").strip()[:16],
              "detail": str(i.get("detail") or "").strip()[:60]}
             for i in (g.get("items") or []) if isinstance(i, dict)
             and str(i.get("name") or "").strip()][:3]
    if items:
        out["items"] = items
    return out


@router.patch("/packs/{pack_id}")
def update_pack(pack_id: str, body: PackIn,
                user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = db.get(StoryPack, pack_id)
    s = db.get(StoryModel, p.story_id) if p else None
    if not p or not s or s.owner_id != user.id:
        raise HTTPException(404, "没有这个收费包")
    if (body.name or "").strip():
        p.name = body.name.strip()[:40]
    p.desc = (body.desc or "").strip()[:200]
    p.price = max(0, min(MAX_PRICE, int(body.price or 0)))
    p.grants = _clean_grants(body.grants)
    db.commit()
    return _pack_view(p, owned=True)


@router.delete("/packs/{pack_id}", status_code=204)
def retire_pack(pack_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """下架 (软删): 已买玩家的资格永久有效 — 台账不动。"""
    p = db.get(StoryPack, pack_id)
    s = db.get(StoryModel, p.story_id) if p else None
    if not p or not s or s.owner_id != user.id:
        raise HTTPException(404, "没有这个收费包")
    p.active = False
    db.commit()


@router.post("/packs/{pack_id}/buy")
def buy_pack(pack_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = db.get(StoryPack, pack_id)
    s = db.get(StoryModel, p.story_id) if p else None
    if not p or not p.active or not s:
        raise HTTPException(404, "没有这个收费包")
    if s.owner_id == user.id:
        raise HTTPException(400, "自己的剧本自动拥有全部收费包，不用买")
    if s.status != "published":
        raise HTTPException(400, "这本还没发布")
    if db.query(PackPurchase).filter(PackPurchase.user_id == user.id,
                                     PackPurchase.pack_id == pack_id).first():
        raise HTTPException(409, "已经拥有了")
    w = _wallet(db, user.id)
    if w.balance < p.price:
        raise HTTPException(400, f"月石不够：要 {p.price}，你有 {w.balance}")
    w.balance -= p.price
    share = p.price * CREATOR_SHARE_PCT // 100
    db.add(PackPurchase(user_id=user.id, story_id=p.story_id, pack_id=pack_id,
                        price=p.price, creator_share=share))
    db.commit()
    return {"ok": True, "balance": w.balance,
            "pack": _pack_view(p, owned=True)}


@router.get("/stories/{story_id}/earnings")
def earnings(story_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """💰 创作者分成看板 (P1 只记账不提现)。"""
    s = db.get(StoryModel, story_id)
    if not s or s.owner_id != user.id:
        raise HTTPException(404, "story not found")
    rows = db.query(PackPurchase).filter(PackPurchase.story_id == story_id).all()
    by_pack: dict = {}
    for r in rows:
        e = by_pack.setdefault(r.pack_id, {"count": 0, "share": 0})
        e["count"] += 1
        e["share"] += r.creator_share
    return {"currency": CURRENCY, "sales": len(rows),
            "total_share": sum(r.creator_share for r in rows),
            "by_pack": by_pack, "share_pct": CREATOR_SHARE_PCT}


def owned_grants(db: Session, user_id: str, story_id: str, is_owner: bool) -> list[dict]:
    """Run 创建时的发货清单: 已购包 (作者=全拥有) 的 grants 列表。"""
    if is_owner:
        packs = db.query(StoryPack).filter(StoryPack.story_id == story_id,
                                           StoryPack.active.is_(True)).all()
        return [p.grants or {} for p in packs]
    owned_ids = {pp.pack_id for pp in db.query(PackPurchase)
                 .filter(PackPurchase.user_id == user_id,
                         PackPurchase.story_id == story_id).all()}
    packs = db.query(StoryPack).filter(StoryPack.id.in_(owned_ids or {""})).all()
    return [p.grants or {} for p in packs]


def access_blocked(db: Session, user_id: str, story_id: str, is_owner: bool) -> bool:
    """门票检查: 有 access 包且玩家一张没买 → 拦。"""
    if is_owner:
        return False
    gate = (db.query(StoryPack)
            .filter(StoryPack.story_id == story_id, StoryPack.active.is_(True)).all())
    gate_ids = {p.id for p in gate if (p.grants or {}).get("access")}
    if not gate_ids:
        return False
    owned = {pp.pack_id for pp in db.query(PackPurchase)
             .filter(PackPurchase.user_id == user_id,
                     PackPurchase.story_id == story_id).all()}
    return not (gate_ids & owned)
