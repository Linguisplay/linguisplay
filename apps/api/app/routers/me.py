import pathlib

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_user
from ..models import User
from ..schemas import ContentLevelIn, Me, MePatch, Settings

router = APIRouter(prefix="/me", tags=["me"])


def _to_me(u: User) -> Me:
    return Me(
        id=u.id,
        email=u.email,
        display_name=u.display_name,
        avatar_url=u.avatar_url,
        subscription_tier=u.subscription_tier,
    )


def _to_settings(u: User) -> Settings:
    return Settings(
        content_level=u.content_level,
        notifications_enabled=u.notifications_enabled,
        default_privacy_private=u.default_privacy_private,
    )


@router.get("", response_model=Me)
def get_me(user: User = Depends(current_user)):
    return _to_me(user)


@router.patch("", response_model=Me)
def patch_me(body: MePatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if body.display_name is not None:
        user.display_name = body.display_name
    if body.avatar_url is not None:
        user.avatar_url = body.avatar_url
    db.commit()
    return _to_me(user)


@router.get("/settings", response_model=Settings)
def get_settings_(user: User = Depends(current_user)):
    return _to_settings(user)


@router.patch("/settings", response_model=Settings)
def patch_settings(
    body: Settings, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    user.content_level = body.content_level
    user.notifications_enabled = body.notifications_enabled
    user.default_privacy_private = body.default_privacy_private
    db.commit()
    return _to_settings(user)


@router.get("/stories")
def my_stories(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """工坊的剧本列表。

    🤝 共享创作库开着时列【全站】的剧本与沙盒, 不只是自己的 (Yi 2026-08-02:
    「让所有账号都可以看见编辑剧本和沙盒」) —— 剧本是要合写的。
    gal 作品不进这张表: 它有自己的书架 (/galshelf), 混进来会把工坊列表冲垮。
    每行带 mine, 前端好标出哪些是自己的。"""
    from ..models import Story as StoryModel
    from .stories import SHARED_LIBRARY

    q = db.query(StoryModel).filter(StoryModel.kind != "gal")
    if not SHARED_LIBRARY:
        q = q.filter(StoryModel.owner_id == user.id)
    rows = q.order_by(StoryModel.updated_at.desc()).all()
    plays = _play_counts(db, [s.id for s in rows])
    return [
        {"id": s.id, "title": s.title, "status": s.status, "version": s.version,
         "visibility": s.visibility, "mine": s.owner_id == user.id,
         **_shelf_stats(s, plays.get(s.id, 0))}
        for s in rows
    ]


# ── 🙈 整理书架 (Yi 2026-08-03:「把之前做的不好的剧本和沙盒都隐藏一下」) ──────
# 判「好不好」不靠感觉, 靠三条能数出来的证据: 有没有人形 (立绘)、有没有景 (背景图)、
# 有没有人玩过 (档数)。列表把证据摆在每行上, 由作者自己勾。

_SCENE = pathlib.Path(__file__).resolve().parents[1] / "static" / "scene"


def _has_art(sub: str, key: str) -> bool:
    return any((_SCENE / sub / f"{key}{ext}").exists()
               for ext in (".webp", ".jpg", ".png"))


def _play_counts(db: Session, ids: list[str]) -> dict[str, int]:
    """一次分组查询数出每本被开过多少档 — 别在循环里查库。"""
    from sqlalchemy import func

    from ..models import Run as RunModel
    if not ids:
        return {}
    return dict(db.query(RunModel.story_id, func.count(RunModel.id))
                .filter(RunModel.story_id.in_(ids))
                .group_by(RunModel.story_id).all())


def _shelf_stats(s, runs: int) -> dict:
    chars, locs = s.characters or [], s.locations or []
    return {
        "chars": len(chars), "locs": len(locs), "runs": runs,
        "sprites": sum(1 for c in chars if _has_art("sprite", c.get("id") or "")),
        "bgs": sum(1 for x in locs if _has_art("bg", x.get("id") or "")),
        "sandbox": bool((s.sandbox or {}).get("enabled")),
    }


class VisibilityBatch(BaseModel):
    ids: list[str] = []
    visibility: str = "private"


@router.post("/stories/visibility")
def set_visibility(body: VisibilityBatch,
                   user: User = Depends(current_user),
                   db: Session = Depends(get_db)):
    """批量翻可见性 —— 只动这一个字段。

    刻意【不走】PATCH /stories/{id}: 那条要整本回写, 会碰乐观锁和作者正在编的内容。
    藏起来是可逆的 (私密只是从玩家大厅消失, 工坊照旧能开、存档照旧能续), 所以
    共享库开着时谁都能整理书架 —— 与删除不同, 这一条不设主人门槛。"""
    from ..models import Story as StoryModel
    if body.visibility not in ("private", "public"):
        raise HTTPException(400, "visibility 只能是 private 或 public")
    if not body.ids:
        return {"changed": 0}
    rows = db.query(StoryModel).filter(StoryModel.id.in_(body.ids),
                                       StoryModel.kind != "gal").all()
    n = 0
    for s in rows:
        if s.visibility != body.visibility:
            s.visibility = body.visibility
            n += 1
    db.commit()
    return {"changed": n, "visibility": body.visibility}


@router.put("/content-level")
def put_content_level(
    body: ContentLevelIn, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    user.content_level = body.content_level
    user.tropes = body.tropes
    db.commit()
    return {"ok": True}
