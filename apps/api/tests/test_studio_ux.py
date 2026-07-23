# -*- coding: utf-8 -*-
"""✍️ 创作 UX 首期 (Yi 2026-07-18 拍板, memory linguisplay-studio-ux):
A 引擎本起草 + lint 硬门是绑定的安全包 — 这里是它的执法点。
门控铁律: 起草只许 act_min 单维; 生成→lint→确定性降级, 落地必须打得通。"""
import os
import time

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./test_e2e.db")
os.environ.setdefault("JWT_SECRET", "test")

from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, engine  # noqa: E402
from app.engine import logic  # noqa: E402
from app.main import app  # noqa: E402


def _client():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    c = TestClient(app)
    c.post("/api/v1/auth/signup",
           json={"email": "ux@x.com", "password": "password1",
                 "dob": "1990-01-01", "accepted_tos": True})
    return c


def test_humanize_issue_handwritten_fixes():
    msg = logic.humanize_issue({"code": "gate_deadlock", "msg": "第2幕死锁"})
    assert "卡死" in msg and "👉" in msg          # 手写指引, 不是术语
    assert "修正" in logic.humanize_issue({"code": "unknown_code", "msg": "x"})


def test_publish_hard_gate_blocks_broken_story():
    """lint 硬门: 死锁本不再能一键上架; 修好后放行。"""
    with _client() as c:
        sid = c.post("/api/v1/stories", json={
            "title": "坏本", "visibility": "public",
            "characters": [{"id": "c1", "name": "甲", "is_lead": True}],
            "acts": [{"index": 1, "title": "一",
                      "advance": {"required_fragment_ids": ["f1"],
                                  "required_event_ids": [], "affinity_min": 0}},
                     {"index": 2, "title": "二"}],
        }).json()["id"]
        c.post(f"/api/v1/stories/{sid}/secrets", json={
            "character_id": "c1", "title": "旧账",
            "fragments": [{"id": "f1", "layer": 1, "content": "X",
                           "retrieval_key": "k", "known_by_character_ids": ["c1"],
                           "unlock": {"act_min": 2}}]})   # 第1幕要求第2幕才解锁 = 死锁
        r = c.post(f"/api/v1/stories/{sid}/publish")
        assert r.status_code == 422
        errs = r.json()["detail"]["lint_errors"]
        assert errs and any("卡死" in e or "死锁" in e for e in errs)   # 人话
        # 修好 (碎片解锁提前) → 放行
        secs = c.get(f"/api/v1/stories/{sid}/secrets").json()
        c.delete(f"/api/v1/stories/{sid}/secrets/{secs[0]['id']}")
        c.post(f"/api/v1/stories/{sid}/secrets", json={
            "character_id": "c1", "title": "旧账",
            "fragments": [{"id": "f1", "layer": 1, "content": "X",
                           "retrieval_key": "k", "known_by_character_ids": ["c1"],
                           "unlock": {"act_min": 1}}]})
        assert c.post(f"/api/v1/stories/{sid}/publish").status_code == 200


def test_draft_engine_produces_lint_clean_conservative_story():
    """A 全链路 (MockLLM): 起草 → act_min 夹逼 (Mock 埋了越界 9 的靶子) →
    lint 干净 → 落库带 ai_draft 埋点 → 直接可发布 → 发布记录 _edit_ratio。"""
    with _client() as c:
        jb = c.post("/api/v1/stories/draft_engine",
                    json={"text": "深夜码头，一本对不上的账，把我卷进一桩旧事。"}).json()
        sid = None
        for _ in range(40):
            r = c.get(f"/api/v1/stories/draft_engine/{jb['job']}").json()
            if r["status"] == "done":
                sid = r["story_id"]
                break
            assert r["status"] == "working", r
            time.sleep(0.1)
        assert sid, "起草任务没完成"
        s = c.get(f"/api/v1/stories/{sid}").json()
        assert s["title"] == "码头夜话" and len(s["acts"]) == 3
        assert any(ch["name"] == "码头老陈" for ch in s["characters"])
        assert s["tuning"]["_origin"] == "ai_draft" and s["tuning"]["_draft_size"] > 0
        secs = c.get(f"/api/v1/stories/{sid}/secrets").json()
        assert secs, "秘密没起草出来"
        for sec in secs:
            for f in sec["fragments"]:
                u = f.get("unlock") or {}
                amin = u.get("act_min", 1)
                assert 1 <= amin <= 3, f"act_min 越界未被夹逼: {amin}"
                # 起草只许 act_min 单维 (响应 schema 会补缺省键, 校验其余维度全零)
                assert not u.get("affinity_min") and not u.get("asks_min") \
                    and not u.get("trigger_event_ids") and not u.get("location_id"), \
                    f"起草混进了组合门控: {u}"
        # 落地草稿必须打得通: 硬门直接放行
        pub = c.post(f"/api/v1/stories/{sid}/publish")
        assert pub.status_code == 200, pub.text
        s2 = c.get(f"/api/v1/stories/{sid}").json()
        assert "_edit_ratio" in s2["tuning"]        # 质量信号落了
        assert s2["tuning"]["_edit_ratio"] < 0.2    # 一字未改 → 痕迹≈0


def test_degrade_strips_gates_when_unfixable():
    """确定性降级单元: 死锁挑不好就把碎片门控压回第一幕。"""
    from app.routers.stories import _degrade_draft, _strip_all_gates
    content = {"story": {"acts": [
        {"index": 1, "advance": {"required_fragment_ids": ["f1"],
                                 "required_event_ids": [], "affinity_min": 0}},
        {"index": 2, "advance": {"required_fragment_ids": [],
                                 "required_event_ids": [], "affinity_min": 0}}],
        "locations": [], "endings": [], "characters": [{"id": "c1", "name": "甲"}]},
        "secrets": [{"character_id": "c1", "fragments": [
            {"id": "f1", "unlock": {"act_min": 2}}]}]}
    _degrade_draft(content, [{"code": "gate_deadlock", "where": "act:1"}])
    assert content["secrets"][0]["fragments"][0]["unlock"]["act_min"] == 1
    _strip_all_gates(content)
    assert content["story"]["acts"][0]["advance"]["required_fragment_ids"] == []


def test_save_survives_garbage_numbers():
    """🛡 宽收数字槽 (实弹 2026-07-19: 手机 type=number 输出垃圾 → parseInt→NaN→null,
    一格烂输入 422 掉整本剧本的保存, 玩家对着「[object Object]」连按五次)。"""
    with _client() as c:
        sid = c.post("/api/v1/stories", json={
            "title": "宽收", "visibility": "private",
            "characters": [{"id": "c1", "name": "甲", "is_lead": True}],
            "acts": [{"index": 1, "title": "一"}]}).json()["id"]
        r = c.patch(f"/api/v1/stories/{sid}", json={
            "characters": [{"id": "c1", "name": "甲", "is_lead": True,
                            "appears_from_act": None}],
            "acts": [{"index": "abc", "title": "一",
                      "advance": {"affinity_min": ""},
                      "time": {"day": None, "slot": ""}}],
            "endings": [{"kind": "bad", "title": "败", "text": "……",
                         "condition": {"affinity_min": "x", "act_min": None}}],
            "locations": [{"id": "l1", "name": "门厅",
                           "unlock": {"act_min": "", "affinity_min": None}}]})
        assert r.status_code == 200, r.text
        s = r.json()
        assert s["characters"][0]["appears_from_act"] == 0
        assert s["acts"][0]["index"] == 0 and s["acts"][0]["advance"]["affinity_min"] == 0
        assert s["endings"][0]["condition"]["affinity_min"] == 0
        assert s["locations"][0]["unlock"]["act_min"] == 0
        # 真格式错误仍是 422, 且 detail 是数组 (studio 靠它翻人话)
        bad = c.patch(f"/api/v1/stories/{sid}", json={"title": {"x": 1}})
        assert bad.status_code == 422 and isinstance(bad.json()["detail"], list)


def test_dangling_exit_names_source_location():
    """🧹 lint 报错要说清「谁的出口」(实弹 2026-07-19: 玩家删地点后被拦,
    报错只说目标不说来源, 十个地点里盲找)。"""
    from app.engine import logic
    issues = logic.lint_story({"story": {
        "characters": [{"id": "c1", "name": "甲", "is_lead": True}],
        "acts": [{"index": 1, "title": "一"}],
        "locations": [{"id": "l1", "name": "码头", "exits": ["后巷"]}]},
        "secrets": []})
    ex = next(i for i in issues if i["code"] == "dangling_exit")
    assert "码头" in ex["msg"] and "后巷" in ex["msg"]


def test_sandbox_lint_skips_designed_absences():
    """🏖 沙盒无结局/无 playable 是设计, lint 不该喊 (实弹: 狗笼报告里两条噪音 warn)。"""
    from app.engine import logic
    base = {"story": {
        "characters": [{"id": "c1", "name": "甲", "is_lead": True}],
        "acts": [{"index": 1, "title": "一"}],
        "locations": [{"id": "l1", "name": "码头"}]},
        "secrets": []}
    codes = {i["code"] for i in logic.lint_story(base)}
    assert "no_endings" in codes and "no_playable" in codes   # 普通本照喊
    sb = {"story": {**base["story"], "sandbox": {"enabled": True}}, "secrets": []}
    codes_sb = {i["code"] for i in logic.lint_story(sb)}
    assert "no_endings" not in codes_sb and "no_playable" not in codes_sb


def test_optimistic_lock_rejects_stale_tab():
    """🔒 乐观锁 (实弹: 陈旧标签页的整本覆盖式保存把修好的草稿静默回滚):
    if_rev 不一致 409; 一致放行并跳新票据; 不传 (老客户端) 放行。"""
    with _client() as c:
        sid = c.post("/api/v1/stories", json={
            "title": "锁", "visibility": "private",
            "characters": [{"id": "c1", "name": "甲", "is_lead": True}],
            "acts": [{"index": 1, "title": "一"}]}).json()["id"]
        rev = c.get(f"/api/v1/stories/{sid}").json()["updated_at"]
        assert rev
        bad = c.patch(f"/api/v1/stories/{sid}", json={"title": "旧快照", "if_rev": "1999-01-01"})
        assert bad.status_code == 409 and "别的窗口" in bad.json()["detail"]
        ok = c.patch(f"/api/v1/stories/{sid}", json={"title": "新", "if_rev": rev})
        assert ok.status_code == 200 and ok.json()["title"] == "新"
        legacy = c.patch(f"/api/v1/stories/{sid}", json={"title": "无票据也行"})
        assert legacy.status_code == 200
