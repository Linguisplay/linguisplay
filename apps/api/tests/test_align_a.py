# -*- coding: utf-8 -*-
"""🧩 前端对齐·包A（契约薄适配）：59屏设计稿审计（2026-08-10）定下的先决项。

前端要开工，列表就得一次给够料（orb 三态/Lobby 卡/ChatList 未读），开档第一屏
就得有演出单（BGM 断线 bug），观战要能按角色筛（Beat 得带 speaker_id）。
这些全是「底子在、差一环」的接线活 —— 本文件给每一环立一个执法点。
"""

import os

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./test_e2e.db")
os.environ.setdefault("JWT_SECRET", "test")

import io  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, engine  # noqa: E402
from app.engine import logic  # noqa: E402
from app.main import app  # noqa: E402

API = "/api/v1"


def _fresh():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _signup(c, email="align@x.com", **extra):
    return c.post(f"{API}/auth/signup",
                  json={"email": email, "password": "password1",
                        "dob": "1990-01-01", "accepted_tos": True, **extra})


def _story_and_run(c, title="AlignA"):
    """一个带幕/地点的最小可玩本 + 一档。"""
    story = c.post(f"{API}/stories", json={
        "title": title, "visibility": "public",
        "characters": [{"id": "c1", "name": "阿元", "is_lead": True}],
        "acts": [{"index": 1, "title": "一", "goal": "先站稳"},
                 {"index": 2, "title": "二"}],
        "locations": [
            {"id": "la_hall", "name": "门厅", "detail": "旧木门厅", "exits": ["后院"]},
            {"id": "la_yard", "name": "后院", "detail": "青苔石阶", "exits": ["门厅"]},
        ],
    }).json()
    sid = story["id"]
    assert c.post(f"{API}/stories/{sid}/publish").status_code == 200
    persona = c.post(f"{API}/personas", json={"name": "Ash"}).json()
    run = c.post(f"{API}/runs", json={"story_id": sid, "persona_id": persona["id"]}).json()
    return sid, persona, run


# ── ① 注册收 display_name ────────────────────────────────
def test_signup_display_name():
    _fresh()
    with TestClient(app) as c:
        r = _signup(c, display_name="Yi")
        assert r.status_code == 201
        assert r.json()["display_name"] == "Yi"
        assert c.get(f"{API}/me").json()["display_name"] == "Yi"


def test_signup_display_name_optional():
    _fresh()
    with TestClient(app) as c:
        assert _signup(c).status_code == 201  # 不带也照常


# ── ② RunSummary 列表一次给够料 ──────────────────────────
def test_run_summary_enriched():
    _fresh()
    with TestClient(app) as c:
        _signup(c)
        _story_and_run(c)
        rows = c.get(f"{API}/runs").json()
        assert len(rows) == 1
        row = rows[0]
        assert row["acts_total"] == 2
        assert isinstance(row["goal"], str)          # 下一步钩子（可为空串，不许缺席）
        assert isinstance(row["entries"], int)       # 词条数
        assert isinstance(row["unread"], int)        # 真未读（不再是写死的 False）
        assert isinstance(row["map_pct"], int)       # 有地图的本必须给 0~100
        assert 0 <= row["map_pct"] <= 100
        assert isinstance(row["direct"], dict)       # 进档演出单随列表走


# ── ③ 开档 BGM 断线修复：RunState.direct 不再被 pydantic 丢弃 ──
def test_boot_direct_survives_runstate():
    _fresh()
    with TestClient(app) as c:
        _signup(c)
        _sid, _p, run = _story_and_run(c)
        got = c.get(f"{API}/runs/{run['id']}").json()
        assert "direct" in got["state"]              # 字段存在（曾被静默丢弃）
        assert isinstance(got["state"]["direct"], dict)
        # 复审补刀：现网 play.html 读的是【顶层】run.direct —— 两层都得有
        assert isinstance(got["direct"], dict)


def test_state_sse_event_excludes_direct():
    """回合内演出权威是单独的 direct 事件；state 事件里混一份会打架（tint 闪断）。"""
    _fresh()
    import json as _json
    with TestClient(app) as c:
        _signup(c)
        _sid, _p, run = _story_and_run(c)
        r = c.post(f"{API}/runs/{run['id']}/play", json={"input": "你好", "channel": "say"})
        states = [_json.loads(ln[len("data: "):]) for ln in r.text.splitlines()
                  if ln.startswith("data: ") and '"event": "state"' in ln]
        assert states, "回合流必须有 state 事件"
        assert all("direct" not in s["state"] for s in states)


# ── ④ Beat 带 speaker_id + present_ids（观战按角色筛的地基） ──
def test_beat_speaker_id_and_present_ids():
    _fresh()
    with TestClient(app) as c:
        _signup(c)
        _sid, _p, run = _story_and_run(c)
        c.post(f"{API}/runs/{run['id']}/play", json={"input": "你好", "channel": "say"})
        beats = c.get(f"{API}/runs/{run['id']}/play").json()
        assert beats, "回放不能为空"
        for b in beats:
            assert "speaker_id" in b and "present_ids" in b
        # 台词拍的 speaker_name 能在班底里对上号的，speaker_id 必须解析出来
        named = [b for b in beats
                 if b["type"] == "dialogue" and b["author"] == "engine"
                 and b.get("speaker_name") == "阿元"]
        assert named, "mock 回合必须有阿元的台词拍"
        assert all(b["speaker_id"] == "c1" for b in named)


# ── ⑤ per-run 局内名 ─────────────────────────────────────
def test_player_name_override():
    _fresh()
    with TestClient(app) as c:
        _signup(c)
        story = c.post(f"{API}/stories", json={
            "title": "Naming", "visibility": "public",
            "characters": [{"id": "n1", "name": "掌柜", "is_lead": True}],
            "acts": [{"index": 1, "title": "一"}],
        }).json()
        c.post(f"{API}/stories/{story['id']}/publish")
        persona = c.post(f"{API}/personas", json={"name": "Ash"}).json()
        run = c.post(f"{API}/runs", json={"story_id": story["id"],
                                          "persona_id": persona["id"],
                                          "player_name": "沈青梧"}).json()
        c.post(f"{API}/runs/{run['id']}/play", json={"input": "在下有礼", "channel": "say"})
        beats = c.get(f"{API}/runs/{run['id']}/play").json()
        mine = [b for b in beats if b["author"] == "player"]
        assert mine and all(b["speaker_name"] == "沈青梧" for b in mine)


def test_player_name_rejects_cast_collision():
    """复审：撞剧中人名（含互为子串）→ POV 守卫每回合空转 + 观战按名筛错人，拒收。"""
    _fresh()
    with TestClient(app) as c:
        _signup(c)
        story = c.post(f"{API}/stories", json={
            "title": "Collide", "visibility": "public",
            "characters": [{"id": "n1", "name": "掌柜", "is_lead": True}],
            "acts": [{"index": 1, "title": "一"}],
        }).json()
        c.post(f"{API}/stories/{story['id']}/publish")
        persona = c.post(f"{API}/personas", json={"name": "Ash"}).json()
        for bad in ("掌柜", "柜", "老掌柜", "掌"):   # 同名/子串/超串/单字
            r = c.post(f"{API}/runs", json={"story_id": story["id"],
                                            "persona_id": persona["id"],
                                            "player_name": bad})
            assert r.status_code == 400, f"{bad!r} 该被拒"
        ok = c.post(f"{API}/runs", json={"story_id": story["id"],
                                         "persona_id": persona["id"],
                                         "player_name": "沈青梧"})
        assert ok.status_code == 201


# ── ⑥ persona 头像：上传 + AI 生成 ───────────────────────
def _tiny_jpg() -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (200, 160, 120)).save(buf, format="JPEG")
    return buf.getvalue()


def test_persona_avatar_upload():
    _fresh()
    with TestClient(app) as c:
        _signup(c)
        p = c.post(f"{API}/personas", json={"name": "Ash"}).json()
        r = c.post(f"{API}/personas/{p['id']}/avatar",
                   files={"file": ("a.jpg", _tiny_jpg(), "image/jpeg")})
        assert r.status_code == 200
        url = r.json()["avatar_url"]
        assert url and url.startswith("/scene/avatar/")
        assert any(x["avatar_url"] == url for x in c.get(f"{API}/personas").json())


def test_persona_gen_avatar(monkeypatch):
    _fresh()
    calls = []
    from app.routers import runs as runs_mod
    monkeypatch.setattr(runs_mod, "_enqueue_image",
                        lambda *a, **k: calls.append((a, k)))
    with TestClient(app) as c:
        _signup(c)
        p = c.post(f"{API}/personas", json={"name": "Ash", "tagline": "浪游的抄书人"}).json()
        r = c.post(f"{API}/personas/{p['id']}/gen_avatar")
        assert r.status_code == 200 and r.json()["queued"] is True
        assert calls, "必须走统一生图队列"
        assert calls[0][1].get("overwrite") is True, "重画必须走 overwrite 旗，不许先删旧图"
        assert any(x["avatar_url"] for x in c.get(f"{API}/personas").json())
        # 复审：计费调用要有冷却 —— 同一用户立刻再点 → 429
        assert c.post(f"{API}/personas/{p['id']}/gen_avatar").status_code == 429


def test_gen_avatar_keeps_old_face_until_new_bytes(monkeypatch):
    """复审：从前先 unlink 再排队 —— 生图 API 欠费那天玩家的脸会被永久删没。"""
    _fresh()
    from app.routers import runs as runs_mod
    monkeypatch.setattr(runs_mod, "_enqueue_image", lambda *a, **k: None)  # 生成永远不落地
    with TestClient(app) as c:
        _signup(c)
        p = c.post(f"{API}/personas", json={"name": "Ash"}).json()
        c.post(f"{API}/personas/{p['id']}/avatar",
               files={"file": ("a.jpg", _tiny_jpg(), "image/jpeg")})
        path = runs_mod._AV_DIR / f"{p['id']}.jpg"
        assert path.exists()
        c.post(f"{API}/personas/{p['id']}/gen_avatar")
        assert path.exists(), "重画排队失败时旧脸必须还在"


# ── ⑦ /me/stories 书架行补字段 ───────────────────────────
def test_shelf_rows_carry_updated_at_and_acts():
    _fresh()
    with TestClient(app) as c:
        _signup(c)
        _story_and_run(c)
        rows = c.get(f"{API}/me/stories").json()
        mine = [r for r in rows if r["title"] == "AlignA"]
        assert mine
        assert mine[0].get("updated_at")
        assert mine[0].get("acts_count") == 2


# ── ⑧ lint：层间阈值倒挂检查（设计稿 15b 画的那条警告） ──
def _content_with_frags(frags):
    return {"story": {"id": "s", "title": "t",
                      "characters": [{"id": "a", "name": "甲", "is_lead": True}],
                      "acts": [{"index": 1, "title": "一"}],
                      "locations": []},
            "secrets": [{"id": "sec1", "title": "旧事", "character_id": "a",
                         "fragments": frags}]}


def test_lint_flags_inverted_layer_thresholds():
    inverted = _content_with_frags([
        {"id": "f_outer", "layer": 1, "content": "外", "unlock": {"affinity_min": 40}},
        {"id": "f_core", "layer": 3, "content": "核", "unlock": {"affinity_min": 20}},
    ])
    codes = {i["code"] for i in logic.lint_story(inverted)}
    assert "frag_gate_inverted" in codes


def test_lint_inversion_immune_to_sibling_order():
    """复审实测抓的：同层兄弟排列顺序曾能骗过检查（L1=30, L2=40, L2=20 静默放行）。"""
    tricky = _content_with_frags([
        {"id": "f_outer", "layer": 1, "content": "外", "unlock": {"affinity_min": 30}},
        {"id": "f_mid_hi", "layer": 2, "content": "中甲", "unlock": {"affinity_min": 40}},
        {"id": "f_mid_lo", "layer": 2, "content": "中乙", "unlock": {"affinity_min": 20}},
    ])
    codes = {i["code"] for i in logic.lint_story(tricky)}
    assert "frag_gate_inverted" in codes


def test_lint_ok_when_thresholds_ascend():
    fine = _content_with_frags([
        {"id": "f_outer", "layer": 1, "content": "外", "unlock": {"affinity_min": 20}},
        {"id": "f_core", "layer": 3, "content": "核", "unlock": {"affinity_min": 60}},
    ])
    codes = {i["code"] for i in logic.lint_story(fine)}
    assert "frag_gate_inverted" not in codes
    # 深层用别的维度锁（act/asks）、不写 affinity —— 不算倒挂
    other_dim = _content_with_frags([
        {"id": "f_outer", "layer": 1, "content": "外", "unlock": {"affinity_min": 40}},
        {"id": "f_core", "layer": 3, "content": "核", "unlock": {"act_min": 3}},
    ])
    codes = {i["code"] for i in logic.lint_story(other_dim)}
    assert "frag_gate_inverted" not in codes


# ── ⑨ discover：tags 过滤挪到截断前 ──────────────────────
def test_discover_tag_filter_beats_the_limit():
    _fresh()
    with TestClient(app) as c:
        _signup(c)
        from app.db import SessionLocal
        from app.models import Story as StoryModel
        from app.models import User
        db = SessionLocal()
        uid = db.query(User).first().id
        base = datetime(2026, 1, 1)
        # 最老的一本带标签，后面 54 本新的没标签 —— 旧实现先掐 50 再过滤，必漏
        db.add(StoryModel(owner_id=uid, title="老书", status="published",
                          visibility="public", trope_tags=["gothic"],
                          updated_at=base))
        for i in range(54):
            db.add(StoryModel(owner_id=uid, title=f"新书{i}", status="published",
                              visibility="public", trope_tags=[],
                              updated_at=base + timedelta(days=i + 1)))
        db.commit()
        db.close()
        items = c.get(f"{API}/stories", params={"tags": ["gothic"]}).json()["items"]
        assert any(s["title"] == "老书" for s in items)
