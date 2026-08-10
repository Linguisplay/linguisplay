# -*- coding: utf-8 -*-
"""🧩 局内社交拟真的 HTTP 面 (对齐包D): 发动态 / 拉黑三档 / 世界论坛。
剧内玩法, 全部挂在 /runs/{id} 下; 逻辑住 engine/socialfic.py, 这里只做
属主校验-入参消毒-落库三件事 (runs.py 的 _notes_commit 同款持久化家法)。"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from ..db import get_db
from ..deps import current_user
from ..engine import runtime
from ..engine import socialfic as sf
from ..models import User

router = APIRouter(tags=["socialfic"])


class PostIn(BaseModel):
    text: str = Field(default="", max_length=1000)


class ForumPostIn(BaseModel):
    text: str = Field(default="", max_length=1000)
    channel: str = Field(default="", max_length=20)


class BlockIn(BaseModel):
    level: str = Field(default="block", max_length=10)   # mute | block | removed


def _own_run(run_id: str, user: User, db: Session):
    from .runs import _own_run as _o
    return _o(run_id, user, db)


def _commit(r, st, db, content_touched: bool = False):
    r.state = st
    flag_modified(r, "state")
    if content_touched:
        flag_modified(r, "pinned_content")
    db.commit()


@router.post("/runs/{run_id}/social/post")
def social_post(run_id: str, body: PostIn,
                user: User = Depends(current_user), db: Session = Depends(get_db)):
    """玩家发动态 (设计稿 31): 世界内角色会看到 — 记进各自的账, 亲密的当场点赞,
    主叙者下回合可当面提起。"""
    r = _own_run(run_id, user, db)
    st = dict(r.state or {})
    if (st.get("mode") or "character") == "god":
        raise HTTPException(403, "旁观者没有自己的账号")
    try:
        post = sf.player_post(r.pinned_content or {}, st, body.text)
    except ValueError as e:
        raise HTTPException(400, str(e))
    _commit(r, st, db)
    return {"post": post}


@router.post("/runs/{run_id}/character/{char_id}/block")
def block_character(run_id: str, char_id: str, body: BlockIn,
                    user: User = Depends(current_user), db: Session = Depends(get_db)):
    """拉黑三档 (设计稿 36: relationship state, not deletion)。removed 走 presence
    机制下台 — 动的是这一档的私有剧本副本, 所以要连 pinned_content 一起落库。"""
    r = _own_run(run_id, user, db)
    st = dict(r.state or {})
    # 旁观者与陌生人两道门 (复审抓的: 同文件发帖有门, 拉黑没有)
    if (st.get("mode") or "character") == "god":
        raise HTTPException(403, "旁观者没有自己的社交关系")
    if char_id not in set(st.get("met_ids") or []):
        raise HTTPException(403, "还没见过的人，谈不上拉黑")
    content = r.pinned_content or {}
    try:
        out = sf.set_block(content, st, char_id, (body.level or "block").strip())
    except ValueError as e:
        raise HTTPException(400, str(e))
    _commit(r, st, db, content_touched=True)
    return {"ok": True, **out, "blocks": sf.levels_view(st)}


@router.delete("/runs/{run_id}/character/{char_id}/block")
def unblock_character(run_id: str, char_id: str,
                      user: User = Depends(current_user), db: Session = Depends(get_db)):
    """解除: 人回台, 拉黑期被暂扣的消息按原时序回放进线程 (非对称账本的谢幕)。"""
    r = _own_run(run_id, user, db)
    st = dict(r.state or {})
    content = r.pinned_content or {}
    try:
        out = sf.set_block(content, st, char_id, None)
    except ValueError as e:
        raise HTTPException(400, str(e))
    _commit(r, st, db, content_touched=True)
    return {"ok": True, **out, "blocks": sf.levels_view(st)}


@router.get("/runs/{run_id}/forum")
def forum(run_id: str,
          user: User = Depends(current_user), db: Session = Depends(get_db)):
    """世界内论坛 (设计稿 25): 账本指纹驱动铸帖, 一次生成永久缓存。

    ⚠️ 落库是【只并 forum 键】不整包覆盖 (复审抓的): 铸帖夹着最多两次同步 LLM
    调用 (几十秒窗口), 期间玩家可能打完一个回合 — 整包写回会把那回合的 final
    state 全部盖掉。forum 键只有本端点写, 键级合并没有竞争。"""
    r = _own_run(run_id, user, db)
    st = dict(r.state or {})
    content = r.pinned_content or {}
    llm = runtime.lang_llm(runtime.get_llm(), content)
    feed = sf.forum_feed(content, st, llm)
    db.expire_all()
    r2 = _own_run(run_id, user, db)   # 重读最新 state, 只并 forum 键
    st2 = dict(r2.state or {})
    st2["forum"] = st.get("forum")
    _commit(r2, st2, db)
    return feed


@router.post("/runs/{run_id}/forum/post")
def forum_post(run_id: str, body: ForumPostIn,
               user: User = Depends(current_user), db: Session = Depends(get_db)):
    """玩家以局内身份发论坛帖 (设计稿 49)。"""
    r = _own_run(run_id, user, db)
    st = dict(r.state or {})
    if (st.get("mode") or "character") == "god":
        raise HTTPException(403, "旁观者没有自己的账号")
    try:
        post = sf.forum_player_post(r.pinned_content or {}, st, body.text, body.channel)
    except ValueError as e:
        raise HTTPException(400, str(e))
    _commit(r, st, db)
    return {"post": post}
