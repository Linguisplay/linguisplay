# -*- coding: utf-8 -*-
"""🧩 对齐包B: 平台社区层 —— 点赞/收藏/关注/评论评分/作者主页。

这是【世界之外】的社交 (玩家之间, 关于剧本), 与剧内那套一个都不沾:
/runs/{id}/social 是虚构朋友圈, /runs/{id}/follow 是物理同行, cards 的「广场」
是角色卡分享。社区数据只长在自己的表和 CommunityStats/StoryCard 上, Story 对象
一个字段都不许长 —— 它会被钉进 run 快照 (剧透盾同款事故的社交版)。
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_user, current_user_optional
from ..models import ReviewLike, Run
from ..models import Story as StoryModel
from ..models import StoryFavorite, StoryLike, StoryReview, User, UserFollow
from ..schemas import (
    AuthorProfile,
    CommunityStats,
    ReviewIn,
    ReviewOut,
    StoryCard,
    _safe_asset_url,
)

router = APIRouter(tags=["community"])


def _commit_or_exists(db: Session) -> None:
    """幂等写的竞态兜底: 两个并发 POST 都过了 get() 检查时, 后到的 commit 撞主键 —
    目标状态 (行存在) 已达成, 回滚吞掉当成功, 不给 500。"""
    try:
        db.commit()
    except IntegrityError:
        db.rollback()


# ── helpers ───────────────────────────────────────────────
def _public_story(story_id: str, db: Session) -> StoryModel:
    s = db.get(StoryModel, story_id)
    if not s or s.visibility != "public" or s.status != "published":
        raise HTTPException(404, "story not found")
    return s


def _user_brief(u: User | None, viewer: User | None = None) -> dict:
    if not u:
        return {}
    # avatar_url 过 _safe_asset_url: 这些 brief 走 dict[str,Any] 字段, pydantic 的
    # AssetUrl 验证器管不到 —— 而这是第一批把【别人的】头像端给你看的口子,
    # 08-02 存储型 XSS 修复靠的就是出库也消毒 (复审抓的防线缺口)。
    return {"id": u.id, "name": u.display_name or "玩家",
            "handle": getattr(u, "handle", None),
            "avatar_url": _safe_asset_url(u.avatar_url),
            "mine": bool(viewer and viewer.id == u.id)}


def social_counts(db: Session, story_ids: list[str]) -> tuple[dict, dict]:
    """(likes, plays) 每本一格, 分组查询 — 别在循环里查库 (me._play_counts 同款)。
    in_ 分批 500: SQLite 绑定变量有上限, 全站 id 一把塞会在库大时炸。"""
    likes: dict = {}
    plays: dict = {}
    for i in range(0, len(story_ids), 500):
        chunk = story_ids[i:i + 500]
        likes.update(db.query(StoryLike.story_id, func.count())
                     .filter(StoryLike.story_id.in_(chunk))
                     .group_by(StoryLike.story_id).all())
        plays.update(db.query(Run.story_id, func.count())
                     .filter(Run.story_id.in_(chunk))
                     .group_by(Run.story_id).all())
    return likes, plays


def _cards_with_social(db: Session, rows: list[StoryModel]) -> list[StoryCard]:
    """一批卡的社区数据: 计数两次分组、作者一次 in_ —— 别一张卡查一次库。"""
    from .stories import _to_card
    likes, plays = social_counts(db, [s.id for s in rows])
    owners = {s.owner_id for s in rows}
    users = ({u.id: u for u in db.query(User).filter(User.id.in_(owners)).all()}
             if owners else {})
    return [_to_card(s, likes=likes.get(s.id, 0), plays=plays.get(s.id, 0),
                     author=_user_brief(users.get(s.owner_id)) or None)
            for s in rows]


# ── ❤️ 点赞 / 🔖 收藏 (幂等 toggle) ────────────────────────
def _toggle(db: Session, model, user_id: str, story_id: str, on: bool) -> None:
    row = db.get(model, (user_id, story_id))
    if on and not row:
        db.add(model(user_id=user_id, story_id=story_id))
    if not on and row:
        db.delete(row)
    _commit_or_exists(db)


@router.post("/stories/{story_id}/like")
def like_story(story_id: str, user: User = Depends(current_user),
               db: Session = Depends(get_db)):
    _public_story(story_id, db)
    _toggle(db, StoryLike, user.id, story_id, True)
    return {"ok": True}


@router.delete("/stories/{story_id}/like")
def unlike_story(story_id: str, user: User = Depends(current_user),
                 db: Session = Depends(get_db)):
    _toggle(db, StoryLike, user.id, story_id, False)
    return {"ok": True}


@router.post("/stories/{story_id}/favorite")
def favorite_story(story_id: str, user: User = Depends(current_user),
                   db: Session = Depends(get_db)):
    _public_story(story_id, db)
    _toggle(db, StoryFavorite, user.id, story_id, True)
    return {"ok": True}


@router.delete("/stories/{story_id}/favorite")
def unfavorite_story(story_id: str, user: User = Depends(current_user),
                     db: Session = Depends(get_db)):
    _toggle(db, StoryFavorite, user.id, story_id, False)
    return {"ok": True}


@router.get("/me/favorites", response_model=list[StoryCard])
def my_favorites(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """🔖 我的书架 (设计稿 16_Me 的 saved worlds), 新藏的在前。已下架的不列。"""
    rows = (db.query(StoryModel)
            .join(StoryFavorite, StoryFavorite.story_id == StoryModel.id)
            .filter(StoryFavorite.user_id == user.id,
                    StoryModel.visibility == "public",
                    StoryModel.status == "published")
            .order_by(StoryFavorite.created_at.desc()).limit(200).all())
    return _cards_with_social(db, rows)


# ── 📊 社区面板 (剧本详情页) ──────────────────────────────
@router.get("/stories/{story_id}/community", response_model=CommunityStats)
def community_stats(story_id: str, user: User | None = Depends(current_user_optional),
                    db: Session = Depends(get_db)):
    s = _public_story(story_id, db)
    likes = db.query(func.count()).select_from(StoryLike).filter(
        StoryLike.story_id == story_id).scalar() or 0
    favs = db.query(func.count()).select_from(StoryFavorite).filter(
        StoryFavorite.story_id == story_id).scalar() or 0
    n, avg = (db.query(func.count(), func.avg(StoryReview.rating))
              .filter(StoryReview.story_id == story_id,
                      StoryReview.parent_id.is_(None)).first()) or (0, None)
    au = db.get(User, s.owner_id)
    author = None
    if au:
        author = _user_brief(au)
        author["followers"] = db.query(func.count()).select_from(UserFollow).filter(
            UserFollow.followee_id == au.id).scalar() or 0
        author["following"] = bool(user and db.get(UserFollow, (user.id, au.id)))
    return CommunityStats(
        likes=likes, favorites=favs,
        liked=bool(user and db.get(StoryLike, (user.id, story_id))),
        faved=bool(user and db.get(StoryFavorite, (user.id, story_id))),
        reviews=int(n or 0),
        rating_avg=(round(float(avg), 1) if avg is not None else None),
        author=author,
    )


# ── ⭐ 评论评分 ───────────────────────────────────────────
def _review_out(db: Session, r: StoryReview, viewer: User | None,
                likes: dict, my_likes: set, users: dict,
                replies: dict | None = None) -> ReviewOut:
    return ReviewOut(
        id=r.id, rating=r.rating, text=r.text or "",
        author=_user_brief(users.get(r.user_id), viewer),
        likes=likes.get(r.id, 0), liked=r.id in my_likes,
        replies=[_review_out(db, c, viewer, likes, my_likes, users)
                 for c in (replies or {}).get(r.id, [])],
        created_at=r.created_at, updated_at=r.updated_at,
    )


@router.get("/stories/{story_id}/reviews", response_model=list[ReviewOut])
def list_reviews(story_id: str, user: User | None = Depends(current_user_optional),
                 db: Session = Depends(get_db)):
    _public_story(story_id, db)
    # 顶层新的在前、封顶 100; 回复只取这一页顶层的 (复审: 旧写法取「最老 400 行」,
    # 评论一多新评论永远上不了列表)。
    tops = (db.query(StoryReview)
            .filter(StoryReview.story_id == story_id, StoryReview.parent_id.is_(None))
            .order_by(StoryReview.created_at.desc()).limit(100).all())
    top_ids = [r.id for r in tops]
    kids = ((db.query(StoryReview)
             .filter(StoryReview.parent_id.in_(top_ids))
             .order_by(StoryReview.created_at.asc()).all()) if top_ids else [])
    rows = tops + kids
    replies: dict[str, list] = {}
    for r in kids:
        replies.setdefault(r.parent_id, []).append(r)          # 回复旧的在前
    ids = [r.id for r in rows]
    likes = dict(db.query(ReviewLike.review_id, func.count())
                 .filter(ReviewLike.review_id.in_(ids or [""]))
                 .group_by(ReviewLike.review_id).all())
    my_likes = ({rl.review_id for rl in db.query(ReviewLike)
                 .filter(ReviewLike.user_id == user.id,
                         ReviewLike.review_id.in_(ids or [""])).all()}
                if user else set())
    users = {u.id: u for u in db.query(User).filter(
        User.id.in_({r.user_id for r in rows} or {""})).all()}
    return [_review_out(db, r, user, likes, my_likes, users, replies) for r in tops]


def _single_out(db: Session, r: StoryReview, viewer: User | None) -> ReviewOut:
    """一条评的【真实】视图 (复审: 改评的响应曾写死 likes=0 replies=[])。"""
    cnt = db.query(func.count()).select_from(ReviewLike).filter(
        ReviewLike.review_id == r.id).scalar() or 0
    liked = bool(viewer and db.get(ReviewLike, (viewer.id, r.id)))
    kids = (db.query(StoryReview).filter(StoryReview.parent_id == r.id)
            .order_by(StoryReview.created_at.asc()).all())
    users = {u.id: u for u in db.query(User).filter(
        User.id.in_({r.user_id, *[k.user_id for k in kids]})).all()}
    return _review_out(db, r, viewer, {r.id: cnt}, {r.id} if liked else set(),
                       users, {r.id: kids})


@router.post("/stories/{story_id}/reviews", response_model=ReviewOut)
def post_review(story_id: str, body: ReviewIn, user: User = Depends(current_user),
                db: Session = Depends(get_db)):
    """一人一评; 再评 = 改评 (设计稿只画了一份自己的评价, 不需要评楼)。"""
    _public_story(story_id, db)
    if not body.rating:
        raise HTTPException(400, "先打个星（1~5）再说感受")
    r = (db.query(StoryReview)
         .filter(StoryReview.story_id == story_id, StoryReview.user_id == user.id,
                 StoryReview.parent_id.is_(None)).first())
    if r:
        r.rating, r.text = body.rating, body.text.strip()
        db.commit()
    else:
        r = StoryReview(story_id=story_id, user_id=user.id,
                        rating=body.rating, text=body.text.strip())
        db.add(r)
        try:
            db.commit()
        except IntegrityError:
            # 并发双发撞了顶层 partial 唯一索引 → 改到那条已落地的上
            db.rollback()
            r = (db.query(StoryReview)
                 .filter(StoryReview.story_id == story_id,
                         StoryReview.user_id == user.id,
                         StoryReview.parent_id.is_(None)).first())
            if not r:
                raise
            r.rating, r.text = body.rating, body.text.strip()
            db.commit()
    db.refresh(r)
    return _single_out(db, r, user)


@router.post("/reviews/{review_id}/reply", response_model=ReviewOut)
def reply_review(review_id: str, body: ReviewIn, user: User = Depends(current_user),
                 db: Session = Depends(get_db)):
    parent = db.get(StoryReview, review_id)
    if not parent or parent.parent_id:
        raise HTTPException(404 if not parent else 400,
                            "review not found" if not parent else "回复不能再套回复")
    _public_story(parent.story_id, db)   # 本子下架/转私密后评论区随之关门 (复审)
    if not (body.text or "").strip():
        raise HTTPException(400, "回复不能是空的")
    r = StoryReview(story_id=parent.story_id, user_id=user.id, rating=None,
                    text=body.text.strip(), parent_id=parent.id)
    db.add(r)
    db.commit()
    db.refresh(r)
    return _single_out(db, r, user)


@router.delete("/reviews/{review_id}")
def delete_review(review_id: str, user: User = Depends(current_user),
                  db: Session = Depends(get_db)):
    r = db.get(StoryReview, review_id)
    if not r or r.user_id != user.id:
        raise HTTPException(404, "review not found")   # 404 不 403: 别替人证实这条评存在
    kids = db.query(StoryReview).filter(StoryReview.parent_id == r.id).all()
    for k in kids:
        db.query(ReviewLike).filter(ReviewLike.review_id == k.id).delete()
        db.delete(k)
    db.query(ReviewLike).filter(ReviewLike.review_id == r.id).delete()
    db.delete(r)
    db.commit()
    return {"ok": True}


@router.post("/reviews/{review_id}/like")
def like_review(review_id: str, user: User = Depends(current_user),
                db: Session = Depends(get_db)):
    r = db.get(StoryReview, review_id)
    if not r:
        raise HTTPException(404, "review not found")
    _public_story(r.story_id, db)   # 下架的本子不再收互动 (复审)
    if not db.get(ReviewLike, (user.id, review_id)):
        db.add(ReviewLike(user_id=user.id, review_id=review_id))
        _commit_or_exists(db)
    return {"ok": True}


@router.delete("/reviews/{review_id}/like")
def unlike_review(review_id: str, user: User = Depends(current_user),
                  db: Session = Depends(get_db)):
    row = db.get(ReviewLike, (user.id, review_id))
    if row:
        db.delete(row)
        db.commit()
    return {"ok": True}


# ── 👤 作者主页 + 关注 ────────────────────────────────────
@router.get("/users/{user_id}", response_model=AuthorProfile)
def author_profile(user_id: str, user: User | None = Depends(current_user_optional),
                   db: Session = Depends(get_db)):
    au = db.get(User, user_id)
    if not au:
        raise HTTPException(404, "user not found")
    works = (db.query(StoryModel)
             .filter(StoryModel.owner_id == au.id,
                     StoryModel.visibility == "public",
                     StoryModel.status == "published")
             .order_by(StoryModel.updated_at.desc()).all())
    _likes, plays = social_counts(db, [s.id for s in works])
    return AuthorProfile(
        id=au.id, name=au.display_name or "玩家",
        handle=getattr(au, "handle", None), avatar_url=au.avatar_url,
        followers=db.query(func.count()).select_from(UserFollow).filter(
            UserFollow.followee_id == au.id).scalar() or 0,
        following=bool(user and db.get(UserFollow, (user.id, au.id))),
        plays=sum(plays.values()),
        works=_cards_with_social(db, works),
    )


@router.post("/users/{user_id}/follow")
def follow_user(user_id: str, user: User = Depends(current_user),
                db: Session = Depends(get_db)):
    if user_id == user.id:
        raise HTTPException(400, "自己不用关注自己")
    if not db.get(User, user_id):
        raise HTTPException(404, "user not found")
    if not db.get(UserFollow, (user.id, user_id)):
        db.add(UserFollow(follower_id=user.id, followee_id=user_id))
        _commit_or_exists(db)
    return {"ok": True}


@router.delete("/users/{user_id}/follow")
def unfollow_user(user_id: str, user: User = Depends(current_user),
                  db: Session = Depends(get_db)):
    row = db.get(UserFollow, (user.id, user_id))
    if row:
        db.delete(row)
        db.commit()
    return {"ok": True}
