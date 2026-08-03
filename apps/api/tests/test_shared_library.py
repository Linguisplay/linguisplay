# -*- coding: utf-8 -*-
"""🤝 共享创作库的四条底线 (Yi 2026-08-02:「让所有账号都可以看见编辑剧本和沙盒」)。

  ① 剧本要能合写: 别人的本子, 登录了就能打开、能改、能发布
  ② 删除【不放开】: 它连存档带快照一起抹, 不可逆 — 仍然只有主人能做
  ③ 放开的只有【剧本本体】: 存档 / 人格 是私事, 一格都不许漏出去
  ④ gal 作品不进工坊列表 (它有自己的书架)
"""
import os
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./test_shared.db")
os.environ.setdefault("JWT_SECRET", "test")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import SessionLocal, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Story  # noqa: E402


def _signup(c, tag):
    r = c.post("/api/v1/auth/signup", json={
        "email": f"{tag}-{uuid.uuid4().hex[:8]}@sharedlib.com",
        "password": "pw12345678", "dob": "1990-01-01", "accepted_tos": True})
    assert r.status_code in (200, 201), r.text
    return r


@pytest.fixture()
def two_authors():
    init_db()
    a, b = TestClient(app), TestClient(app)
    _signup(a, "amy")
    _signup(b, "bob")
    sid = a.post("/api/v1/stories", json={"title": "合写测试本"}).json()["id"]
    yield a, b, sid
    db = SessionLocal()
    s = db.get(Story, sid)
    if s:
        db.delete(s)
        db.commit()
    db.close()


# ── ① 能合写 ──────────────────────────────────────────────────────────────
def test_another_account_can_open_and_edit_someone_elses_story(two_authors):
    a, b, sid = two_authors
    assert b.get(f"/api/v1/stories/{sid}").status_code == 200, "别人的本子打不开"
    r = b.patch(f"/api/v1/stories/{sid}", json={"title": "被乙改过"})
    assert r.status_code == 200, r.text
    assert a.get(f"/api/v1/stories/{sid}").json()["title"] == "被乙改过"


def test_a_collaborator_reads_the_FULL_story_not_the_spoiler_shielded_one(two_authors):
    """工坊编辑就是用这条读的。合写者若拿到删减版 (剧透盾抹掉结局/幕内事件/角色小传),
    一保存就把作者的东西抹没了 —— 这是数据丢失, 不是显示问题。"""
    a, b, sid = two_authors
    a.patch(f"/api/v1/stories/{sid}", json={
        "endings": [{"id": "e1", "kind": "true", "title": "真结局", "text": "答案"}],
        "characters": [{"id": "c1", "name": "甲角", "bio_layers": [
            {"closeness_min": 0, "text": "只有作者看得见的小传"}]}]})
    got = b.get(f"/api/v1/stories/{sid}?edit=1").json()
    assert got["endings"], "合写者读不到结局 — 他一保存就把结局抹了"
    assert got["characters"][0].get("bio_layers"), "合写者读不到分层小传"


def test_the_play_path_never_gets_the_answer_key(two_authors):
    """同一条路由播放页也在用 (chooseRole)。不带 ?edit=1 就必须吃剧透盾 ——
    否则每个玩家一打开剧本就看到结局和答案 (第一版真这样, test_sweep 当场红)。"""
    a, b, sid = two_authors
    a.patch(f"/api/v1/stories/{sid}", json={
        "visibility": "public", "synopsis": "梗概",
        "acts": [{"index": 1, "title": "一幕"}],
        "characters": [{"id": "c1", "name": "甲角", "is_lead": True, "playable": True,
                        "bio_layers": [{"closeness_min": 0, "text": "作者底牌"}]}],
        "endings": [{"id": "e1", "kind": "true", "title": "真结局", "text": "答案"}]})
    assert a.post(f"/api/v1/stories/{sid}/publish").status_code == 200
    got = b.get(f"/api/v1/stories/{sid}").json()          # 播放页的读法
    assert got["endings"] == [], "玩家不该看到结局"
    assert not got["characters"][0].get("bio_layers"), "玩家不该看到分层小传"


def test_a_logged_out_visitor_still_gets_the_spoiler_shield(two_authors):
    """共享库放开的是【登录的合写者】, 不是全世界。剧透盾对玩家照旧生效。"""
    a, b, sid = two_authors
    # 发布要过 lint 硬门 (空本子会被 422 挡回来), 所以先把幕和角色补齐
    a.patch(f"/api/v1/stories/{sid}", json={
        "visibility": "public", "synopsis": "一句梗概",
        "acts": [{"index": 1, "title": "一幕"}],
        "characters": [{"id": "c1", "name": "甲角", "is_lead": True, "playable": True}],
        "endings": [{"id": "e1", "kind": "true", "title": "真结局", "text": "答案"}]})
    r = a.post(f"/api/v1/stories/{sid}/publish")
    assert r.status_code == 200, r.text
    anon = TestClient(app)
    got = anon.get(f"/api/v1/stories/{sid}")
    assert got.status_code == 200
    assert got.json()["endings"] == [], "没登录的访客不该看到结局"


def test_the_studio_list_shows_everyones_stories_and_marks_whose(two_authors):
    a, b, sid = two_authors
    rows = b.get("/api/v1/me/stories").json()
    row = next((x for x in rows if x["id"] == sid), None)
    assert row, "共享库开着, 乙的工坊列表里应该看得见甲的本子"
    assert row["mine"] is False, "得标出这不是自己的, 免得合写时不知道在动谁的"
    assert next(x for x in a.get("/api/v1/me/stories").json()
                if x["id"] == sid)["mine"] is True


# ── ② 删除不放开 ──────────────────────────────────────────────────────────
def test_deleting_someone_elses_story_is_still_refused(two_authors):
    a, b, sid = two_authors
    assert b.delete(f"/api/v1/stories/{sid}").status_code in (403, 404), \
        "删除会连存档带快照一起抹, 不可逆 — 共享库不该放开这一条"
    assert a.get(f"/api/v1/stories/{sid}").status_code == 200, "本子必须还在"


def test_the_owner_can_still_delete_their_own(two_authors):
    a, b, sid = two_authors
    assert a.delete(f"/api/v1/stories/{sid}").status_code == 204
    assert a.get(f"/api/v1/stories/{sid}").status_code == 404


# ── ③ 私事不许漏 ──────────────────────────────────────────────────────────
def test_saves_and_personas_stay_private(two_authors):
    a, b, sid = two_authors
    pid = a.post("/api/v1/personas", json={"name": "甲的人格"}).json()["id"]
    rid = a.post("/api/v1/runs", json={"story_id": sid, "persona_id": pid}).json()["id"]
    assert b.get(f"/api/v1/runs/{rid}").status_code in (403, 404), "存档是私事, 不许被别人读"
    assert not [p for p in b.get("/api/v1/personas").json() if p["id"] == pid], \
        "人格是私事, 不许出现在别人的列表里"


# ── ④ gal 作品不混进工坊列表 ──────────────────────────────────────────────
def test_gal_works_stay_out_of_the_studio_list(two_authors):
    a, b, sid = two_authors
    db = SessionLocal()
    db.get(Story, sid).kind = "gal"
    db.commit()
    db.close()
    assert not [x for x in b.get("/api/v1/me/stories").json() if x["id"] == sid], \
        "gal 作品有自己的书架, 混进工坊列表会把它冲垮"
