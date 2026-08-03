from fastapi import APIRouter, Depends
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
    return [
        {"id": s.id, "title": s.title, "status": s.status, "version": s.version,
         "visibility": s.visibility, "mine": s.owner_id == user.id}
        for s in rows
    ]


@router.put("/content-level")
def put_content_level(
    body: ContentLevelIn, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    user.content_level = body.content_level
    user.tropes = body.tropes
    db.commit()
    return {"ok": True}
