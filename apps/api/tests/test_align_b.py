# -*- coding: utf-8 -*-
"""🧩 前端对齐·包B（平台社区层）：59屏审计里成片缺席的那一片 ——
点赞/收藏/关注/评论评分/搜索/热度/精选/handle/作者主页。
全是"世界之外"的平台社交（剧内朋友圈是另一套, 在 /runs/{id}/social, 别混）。
"""

import os

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./test_e2e.db")
os.environ.setdefault("JWT_SECRET", "test")

from datetime import datetime, timedelta  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402

API = "/api/v1"


def _fresh():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _signup(c, email, **extra):
    r = c.post(f"{API}/auth/signup",
               json={"email": email, "password": "password1",
                     "dob": "1990-01-01", "accepted_tos": True, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def _publish_story(c, title="社区本", tags=None):
    story = c.post(f"{API}/stories", json={
        "title": title, "visibility": "public", "trope_tags": tags or [],
        "characters": [{"id": "b1", "name": "阿岚", "is_lead": True}],
        "acts": [{"index": 1, "title": "一"}],
    }).json()
    assert c.post(f"{API}/stories/{story['id']}/publish").status_code == 200
    return story["id"]


# ── ① 点赞 / 收藏 ────────────────────────────────────────
def test_like_toggle_and_counts():
    _fresh()
    with TestClient(app) as c:
        _signup(c, "liker@x.com")
        sid = _publish_story(c)
        assert c.post(f"{API}/stories/{sid}/like").status_code == 200
        assert c.post(f"{API}/stories/{sid}/like").status_code == 200   # 幂等
        st = c.get(f"{API}/stories/{sid}/community").json()
        assert st["likes"] == 1 and st["liked"] is True
        assert c.delete(f"{API}/stories/{sid}/like").status_code == 200
        st = c.get(f"{API}/stories/{sid}/community").json()
        assert st["likes"] == 0 and st["liked"] is False


def test_favorite_and_me_favorites():
    _fresh()
    with TestClient(app) as c:
        _signup(c, "fav@x.com")
        sid = _publish_story(c, title="收藏这本")
        c.post(f"{API}/stories/{sid}/favorite")
        favs = c.get(f"{API}/me/favorites").json()
        assert [f["id"] for f in favs] == [sid]
        assert favs[0]["title"] == "收藏这本"
        c.delete(f"{API}/stories/{sid}/favorite")
        assert c.get(f"{API}/me/favorites").json() == []


# ── ② 评论评分 ───────────────────────────────────────────
def test_review_upsert_reply_like_delete():
    _fresh()
    with TestClient(app) as c:
        _signup(c, "author@x.com", display_name="作者甲")
        sid = _publish_story(c)
        r = c.post(f"{API}/stories/{sid}/reviews", json={"rating": 5, "text": "克制得漂亮"})
        assert r.status_code == 200, r.text
        # 同人再评 = 改评（一人一评）
        c.post(f"{API}/stories/{sid}/reviews", json={"rating": 3, "text": "回味后改三星"})
        lst = c.get(f"{API}/stories/{sid}/reviews").json()
        assert len(lst) == 1 and lst[0]["rating"] == 3
        rid = lst[0]["id"]
        assert lst[0]["author"]["name"] == "作者甲"
        # 回复 + 点赞
        assert c.post(f"{API}/reviews/{rid}/reply", json={"text": "同感"}).status_code == 200
        assert c.post(f"{API}/reviews/{rid}/like").status_code == 200
        lst = c.get(f"{API}/stories/{sid}/reviews").json()
        assert lst[0]["likes"] == 1 and lst[0]["liked"] is True
        assert len(lst[0]["replies"]) == 1 and lst[0]["replies"][0]["text"] == "同感"
        # 评分进社区面板
        st = c.get(f"{API}/stories/{sid}/community").json()
        assert st["reviews"] == 1 and st["rating_avg"] == 3.0
        # 删除连回复一起走
        assert c.delete(f"{API}/reviews/{rid}").status_code == 200
        assert c.get(f"{API}/stories/{sid}/reviews").json() == []


def test_review_needs_rating_and_owner_only_delete():
    _fresh()
    with TestClient(app) as c:
        _signup(c, "a@x.com")
        sid = _publish_story(c)
        assert c.post(f"{API}/stories/{sid}/reviews", json={"text": "没打星"}).status_code == 400
        c.post(f"{API}/stories/{sid}/reviews", json={"rating": 4})
        rid = c.get(f"{API}/stories/{sid}/reviews").json()[0]["id"]
        c.post(f"{API}/auth/logout")
        _signup(c, "b@x.com")
        assert c.delete(f"{API}/reviews/{rid}").status_code == 404   # 别人的评删不动


def test_second_reply_and_reply_after_unpublish():
    """复审 high：三列唯一约束曾把「同一人回同一条第二次」炸成 500；
    复审 medium：本子转私密后评论区必须关门。"""
    _fresh()
    with TestClient(app) as c:
        _signup(c, "rr@x.com")
        sid = _publish_story(c)
        c.post(f"{API}/stories/{sid}/reviews", json={"rating": 5, "text": "好"})
        rid = c.get(f"{API}/stories/{sid}/reviews").json()[0]["id"]
        assert c.post(f"{API}/reviews/{rid}/reply", json={"text": "一楼"}).status_code == 200
        assert c.post(f"{API}/reviews/{rid}/reply", json={"text": "二楼"}).status_code == 200
        lst = c.get(f"{API}/stories/{sid}/reviews").json()
        assert [r["text"] for r in lst[0]["replies"]] == ["一楼", "二楼"]
        # 下架 → 评论区随之关门
        from app.db import SessionLocal
        from app.models import Story as StoryModel
        db = SessionLocal()
        db.get(StoryModel, sid).visibility = "private"
        db.commit(); db.close()
        assert c.post(f"{API}/reviews/{rid}/reply", json={"text": "三楼"}).status_code == 404
        assert c.post(f"{API}/reviews/{rid}/like").status_code == 404


def test_review_list_newest_first_and_edit_echo_real_state():
    _fresh()
    with TestClient(app) as c:
        _signup(c, "first@x.com")
        sid = _publish_story(c)
        c.post(f"{API}/stories/{sid}/reviews", json={"rating": 4, "text": "先来"})
        rid = c.get(f"{API}/stories/{sid}/reviews").json()[0]["id"]
        c.post(f"{API}/reviews/{rid}/like")
        c.post(f"{API}/reviews/{rid}/reply", json={"text": "自答"})
        # 改评的响应必须带真实的赞与回复（复审：曾写死 0/空）
        got = c.post(f"{API}/stories/{sid}/reviews",
                     json={"rating": 5, "text": "改五星"}).json()
        assert got["likes"] == 1 and got["liked"] is True
        assert [x["text"] for x in got["replies"]] == ["自答"]
        c.post(f"{API}/auth/logout")
        _signup(c, "second@x.com")
        c.post(f"{API}/stories/{sid}/reviews", json={"rating": 2, "text": "后到"})
        lst = c.get(f"{API}/stories/{sid}/reviews").json()
        assert [r["text"] for r in lst] == ["后到", "改五星"]   # 新的在前


def test_dirty_avatar_sanitized_on_the_way_out():
    """08-02 存储型 XSS 家法：老脏行出库也要消毒 —— author dict 绕过了 AssetUrl
    验证器，_user_brief 必须自己过一遍。"""
    _fresh()
    with TestClient(app) as c:
        u = _signup(c, "dirty@x.com")
        sid = _publish_story(c)
        c.post(f"{API}/stories/{sid}/reviews", json={"rating": 5, "text": "x"})
        from app.db import SessionLocal
        from app.models import User
        db = SessionLocal()
        db.get(User, u["id"]).avatar_url = '//evil.example/x.jpg"onerror="1'
        db.commit(); db.close()
        lst = c.get(f"{API}/stories/{sid}/reviews").json()
        assert lst[0]["author"]["avatar_url"] is None
        items = c.get(f"{API}/stories").json()["items"]
        assert items[0]["author"]["avatar_url"] is None


# ── ③ 关注 + 作者主页 ────────────────────────────────────
def test_follow_and_author_profile():
    _fresh()
    with TestClient(app) as c:
        au = _signup(c, "writer@x.com", display_name="莫姑娘", handle="moorwitch")
        sid = _publish_story(c, title="她的名作")
        c.post(f"{API}/runs", json={"story_id": sid, "persona_id":
               c.post(f"{API}/personas", json={"name": "P"}).json()["id"]})
        c.post(f"{API}/auth/logout")
        _signup(c, "fan@x.com")
        assert c.post(f"{API}/users/{au['id']}/follow").status_code == 200
        prof = c.get(f"{API}/users/{au['id']}").json()
        assert prof["handle"] == "moorwitch" and prof["name"] == "莫姑娘"
        assert prof["followers"] == 1 and prof["following"] is True
        assert prof["plays"] >= 1
        assert [w["title"] for w in prof["works"]] == ["她的名作"]
        assert c.delete(f"{API}/users/{au['id']}/follow").status_code == 200
        assert c.get(f"{API}/users/{au['id']}").json()["followers"] == 0


def test_no_self_follow():
    _fresh()
    with TestClient(app) as c:
        me = _signup(c, "self@x.com")
        assert c.post(f"{API}/users/{me['id']}/follow").status_code == 400


# ── ④ handle ─────────────────────────────────────────────
def test_handle_set_unique_and_validated():
    _fresh()
    with TestClient(app) as c:
        _signup(c, "h1@x.com", handle="yi_01")
        assert c.get(f"{API}/me").json()["handle"] == "yi_01"
        c.post(f"{API}/auth/logout")
        _signup(c, "h2@x.com")
        assert c.patch(f"{API}/me", json={"handle": "yi_01"}).status_code == 409   # 撞名
        assert c.patch(f"{API}/me", json={"handle": "大写不行"}).status_code == 400
        assert c.patch(f"{API}/me", json={"handle": "ok_name2"}).status_code == 200
        assert c.get(f"{API}/me").json()["handle"] == "ok_name2"


# ── ⑤ discover：搜索 / 热度 / 精选 / 卡片带作者与计数 ─────
def test_discover_search_hot_featured_and_card_extras():
    _fresh()
    with TestClient(app) as c:
        _signup(c, "d@x.com", display_name="出品人", handle="maker")
        sid_a = _publish_story(c, title="雾中灯塔", tags=["romance"])
        sid_b = _publish_story(c, title="莽原快车", tags=["mystery"])
        # 热度：给 B 一个赞一档游玩
        c.post(f"{API}/stories/{sid_b}/like")
        c.post(f"{API}/runs", json={"story_id": sid_b, "persona_id":
               c.post(f"{API}/personas", json={"name": "P"}).json()["id"]})
        # 搜索
        items = c.get(f"{API}/stories", params={"q": "灯塔"}).json()["items"]
        assert [s["id"] for s in items] == [sid_a]
        # 热度排序：B 在前
        items = c.get(f"{API}/stories", params={"sort": "hot"}).json()["items"]
        assert items[0]["id"] == sid_b
        assert items[0]["likes"] == 1 and items[0]["plays"] == 1
        assert items[0]["author"]["handle"] == "maker"
        assert "mature" in items[0] and "featured" in items[0]
        # 精选位：手动点亮（运营操作，先走 DB）
        from app.db import SessionLocal
        from app.models import Story as StoryModel
        db = SessionLocal()
        db.get(StoryModel, sid_a).featured = True
        db.commit(); db.close()
        items = c.get(f"{API}/stories", params={"featured": True}).json()["items"]
        assert [s["id"] for s in items] == [sid_a]


def test_discover_search_beats_the_limit():
    """搜索也得在截断前：51 本新书压着一本老的《雾里老屋》，q 必须捞得到。"""
    _fresh()
    with TestClient(app) as c:
        u = _signup(c, "bulk@x.com")
        from app.db import SessionLocal
        from app.models import Story as StoryModel
        db = SessionLocal()
        base = datetime(2026, 1, 1)
        db.add(StoryModel(owner_id=u["id"], title="雾里老屋", status="published",
                          visibility="public", updated_at=base))
        for i in range(53):
            db.add(StoryModel(owner_id=u["id"], title=f"填充{i}", status="published",
                              visibility="public", updated_at=base + timedelta(days=i + 1)))
        db.commit(); db.close()
        items = c.get(f"{API}/stories", params={"q": "老屋"}).json()["items"]
        assert any(s["title"] == "雾里老屋" for s in items)


# ── ⑥ 社区数据不许渗进剧本快照（防剧透盾同款事故） ────────
def test_story_schema_untouched_by_community():
    _fresh()
    with TestClient(app) as c:
        _signup(c, "clean@x.com")
        sid = _publish_story(c)
        c.post(f"{API}/stories/{sid}/like")
        body = c.get(f"{API}/stories/{sid}").json()
        for k in ("likes", "plays", "author", "featured"):
            assert k not in body, f"Story 对象不许长出社区字段 {k}（会被钉进 run 快照）"
