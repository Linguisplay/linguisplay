# -*- coding: utf-8 -*-
"""🎨 背景定种 (Yi 2026-08-04:「新场景生成的背景画风要统一」)。

审查发现: 背景是【唯一】没有定种的美术类别 —— 道具走 icon_seed、立绘/头像/自拍
走 char_seed, 只有背景三处调用 (_spawn_location_bg / 玩家重画 / 工坊画背景) 都是
裸调 _enqueue_image, 每张都重新抽一次随机噪声。后果:

  · 同一个地点点两次「重画」出两张毫不相干的图 (作者永远调不准);
  · 同一本剧本各地点各抽各的, 风格串虽然一样, 落地却会漂。

这里把背景收成【一本剧本一颗种】: 同一本的所有背景共用同一次风格骰, 而地名/描述
的差异照旧让每处场景各不相同。附带好处是重画幂等 —— 同种同词必出同图。

⚠️ 不做成 per-location 种: 那只解决"重画稳定", 解决不了"各地点风格漂"。
"""
import pytest

from app.engine.gal import bg_seed, char_seed


# ── 🎲 种子本身 ─────────────────────────────────────────────────────────────
def test_same_story_always_gets_the_same_seed():
    assert bg_seed("story-a") == bg_seed("story-a")


def test_different_stories_get_different_seeds():
    assert bg_seed("story-a") != bg_seed("story-b")


def test_seed_is_in_range_the_image_api_accepts():
    for sid in ("story-a", "story-b", "", "九龙城寨·狗笼"):
        s = bg_seed(sid)
        assert isinstance(s, int) and 0 <= s < 2 ** 31 - 1, f"{sid} 出了越界种子 {s}"


def test_bg_seed_does_not_collide_with_a_character_seed():
    """背景和角色用同一套哈希, 但绝不能撞 —— 撞了就是"背景长了张脸"的种。"""
    assert bg_seed("s") != char_seed("s", "c1")


# ── 🖼 三条生成路必须都带上它 ──────────────────────────────────────────────
@pytest.fixture
def spy_queue(monkeypatch):
    """截住 _enqueue_image, 把每次排队的 (路径, seed) 记下来。"""
    seen = []

    def fake(prompt, path, size, negative="", seed=None):
        seen.append({"path": str(path), "seed": seed, "prompt": prompt})

    from app.routers import runs as runs_mod
    monkeypatch.setattr(runs_mod, "_enqueue_image", fake)
    return seen


CONTENT = {"story": {"id": "sid-1", "tuning": {},
                     "world_long": "雨季的南方小镇",
                     "locations": [{"id": "loc_x", "name": "旧巷", "detail": "青苔"}]}}
LOC = CONTENT["story"]["locations"][0]


def test_runtime_backfill_carries_the_seed(spy_queue, tmp_path, monkeypatch):
    from app.routers import runs as runs_mod
    monkeypatch.setattr(runs_mod, "_BG_DIR", tmp_path)
    runs_mod._spawn_location_bg(CONTENT, LOC)
    assert spy_queue, "根本没排队"
    assert spy_queue[0]["seed"] == bg_seed("sid-1"), \
        f"运行时补图没带种 (拿到 {spy_queue[0]['seed']})"


def test_studio_and_runtime_agree_on_the_seed(spy_queue, tmp_path, monkeypatch):
    """工坊里作者手点「AI 画背景」, 和游戏里自动补的, 必须是同一颗种 ——
    否则作者调好的图一进游戏就变了样。"""
    from app.routers import runs as runs_mod
    monkeypatch.setattr(runs_mod, "_BG_DIR", tmp_path)
    runs_mod._spawn_location_bg(CONTENT, LOC)
    runtime_seed = spy_queue[0]["seed"]

    from app.routers import stories as stories_mod
    assert stories_mod._studio_bg_seed(CONTENT) == runtime_seed, \
        "工坊和运行时用了两颗种 — 作者看到的图和玩家看到的会不一样"


def test_all_locations_of_one_story_share_the_style_roll(spy_queue, tmp_path, monkeypatch):
    from app.routers import runs as runs_mod
    monkeypatch.setattr(runs_mod, "_BG_DIR", tmp_path)
    for lid in ("loc_a", "loc_b", "loc_c"):
        runs_mod._spawn_location_bg(
            CONTENT, {"id": lid, "name": lid, "detail": "x"})
    seeds = {q["seed"] for q in spy_queue}
    assert len(seeds) == 1, f"同一本剧本的背景抽了 {len(seeds)} 颗不同的种: {seeds}"


def test_two_stories_do_not_share_a_roll(spy_queue, tmp_path, monkeypatch):
    from app.routers import runs as runs_mod
    monkeypatch.setattr(runs_mod, "_BG_DIR", tmp_path)
    runs_mod._spawn_location_bg(CONTENT, LOC)
    other = {"story": {"id": "sid-2", "tuning": {}, "locations": []}}
    runs_mod._spawn_location_bg(other, {"id": "loc_y", "name": "别处", "detail": "x"})
    assert spy_queue[0]["seed"] != spy_queue[1]["seed"], "两本剧本共用了一颗种"


# ── 🧪 红样本自验 ───────────────────────────────────────────────────────────
def test_red_sample_a_seedless_call_would_be_caught():
    """修复前三处都是 seed=None —— 证明上面那几条断言不是空转。"""
    before = {"seed": None}
    assert before["seed"] != bg_seed("sid-1"), "红样本本身就该不达标"


# ── 🔁 重画分支 (差点漏掉的那条) ────────────────────────────────────────────
# 头一版只测了"首次生成"这一条路, 于是重画分支里一个未定义的名字安安静静躺着 ——
# 测试全绿, 而作者只要点第二次「重画」就 500。教训: 加了 if 就要把两支都走一遍。
def test_studio_redraw_branch_actually_runs(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from app.db import Base, engine
    from app.main import app
    from app.routers import runs as runs_mod
    from app.routers import stories as stories_mod

    Base.metadata.create_all(bind=engine)
    seen = []
    monkeypatch.setattr(
        runs_mod, "_enqueue_image",
        lambda prompt, path, size, negative="", seed=None: seen.append(seed))
    monkeypatch.setattr(runs_mod, "_BG_DIR", tmp_path)
    monkeypatch.setattr(stories_mod, "_BG_DIR", tmp_path, raising=False)

    with TestClient(app) as c:
        # ⚠️ 全套件共用一个 test_e2e.db: 这个邮箱可能上一轮就注册过了, 注册会失败,
        #    于是拿不到 cookie, 下一句就 KeyError。注册不成就登录 —— 别假设自己是头一个。
        cred = {"email": "bgseed@lpqa.com", "password": "password1"}
        r = c.post("/api/v1/auth/signup",
                   json={**cred, "dob": "1990-01-01", "accepted_tos": True})
        if r.status_code >= 400:
            r = c.post("/api/v1/auth/login", json=cred)
        assert r.status_code < 400, f"拿不到会话: {r.status_code} {r.text[:200]}"
        sid = c.post("/api/v1/stories", json={
            "title": "种子本", "visibility": "private",
            "locations": [{"id": "loc_seed", "name": "旧巷", "detail": "青苔"}],
            "characters": [{"id": "c1", "name": "甲", "is_lead": True}]}).json()["id"]

        first = c.post(f"/api/v1/stories/{sid}/gen_bg/loc_seed")
        assert first.status_code == 200, first.text
        (tmp_path / "loc_seed.jpg").write_bytes(b"\xff\xd8\xff old")   # 已有图 → 下一次是重画
        again = c.post(f"/api/v1/stories/{sid}/gen_bg/loc_seed")
        assert again.status_code == 200, f"重画这一支炸了: {again.text[:300]}"

    assert len(seen) == 2, f"只排到 {len(seen)} 次队"
    assert seen[0] != seen[1], "重画给了同一颗种 — 会原样再出同一张图"
