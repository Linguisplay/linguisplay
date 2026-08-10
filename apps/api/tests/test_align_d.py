# -*- coding: utf-8 -*-
"""🧩 前端对齐·包D（局内社交拟真）：玩家发帖被角色看见 → 拉黑因果+非对称账本 →
世界论坛/按幕锁消息/浏览器历史；前置修理 = peek 触发正则中西通吃。
新逻辑住 engine/socialfic.py（新文件），runtime 只留薄钩子。
"""

import os

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./test_e2e.db")
os.environ.setdefault("JWT_SECRET", "test")

from app.engine import runtime, socialfic  # noqa: E402

CONTENT = {
    "story": {"id": "s", "phone": {"device": "手机"},
              "sandbox": {"enabled": True},
              "characters": [
                  {"id": "a", "name": "甲", "is_lead": True},
                  {"id": "b", "name": "乙", "eq_style": "嘴硬心软",
                   "persona_text": "夜班门房"}],
              "acts": [{"index": 1, "title": "一"}, {"index": 2, "title": "二"},
                       {"index": 3, "title": "三"}],
              "locations": [{"id": "hall", "name": "门厅", "detail": "一盏吊灯"}]},
    "secrets": [],
}


def _en_content():
    import copy
    c = copy.deepcopy(CONTENT)
    c["story"]["language"] = "en"
    c["story"]["characters"][1]["name"] = "Edward"
    return c


def _st():
    st = runtime.default_state()
    st["met_ids"] = ["a", "b"]
    st["contact_ids"] = ["a", "b"]
    st["rel"] = {"b": {**runtime.relationships.new_scores(), "closeness": 35}}
    st["npc_rel"] = {"a|b": {"stance": 1, "label": "", "log": [{"why": "同桌喝了顿酒"}]}}
    return st


class MockL:
    """未知键一律 {} —— 所有包D生成路径必须有确定性兜底。"""
    def __init__(self):
        self.prompts = []

    def generate(self, prompt):
        self.prompts.append(prompt)
        return {}


# ── 前置修理：peek 触发中西通吃 ──────────────────────────
def test_peek_ref_bilingual():
    assert runtime._peek_ref("我偷偷翻看乙的手机") == "乙"
    assert runtime._peek_ref("I quietly check Edward's phone") == "Edward"
    assert runtime._peek_ref("pick up Mrs. Ainsley's pager and read it") == "Mrs. Ainsley"
    assert runtime._peek_ref("glance at Edward’s phone") == "Edward"   # 弯引号
    assert runtime._peek_ref("聊聊今天的天气") is None
    assert runtime._peek_ref("The phone rings twice") is None


def test_peek_attempt_en_full_path():
    content = _en_content()
    st = _st()
    st["dead_character_ids"] = ["b"]          # 尸体免骰：确定性走到深翻
    out = runtime.peek_attempt(content, st, "I check Edward's phone", "do", MockL())
    assert out is not None and out.get("view"), "英文构式必须点得着偷看"


# ── 按幕锁消息（设计稿 23b「到第三幕才能读」） ────────────
def test_device_peek_act_lock():
    import copy
    content = copy.deepcopy(CONTENT)
    content["story"]["characters"][1]["device_peek"] = [
        {"with": "unknown", "msgs": ["现在就能看"]},
        {"with": "edmund", "msgs": ["深处的事"], "act_min": 3},
    ]
    st = _st()
    st["dead_character_ids"] = ["b"]
    out = runtime.peek_attempt(content, st, "翻乙的手机", "do", MockL())
    view = out["view"]
    withs = [t.get("with") for t in view["threads"]]
    assert "edmund" not in str(withs), "act_min=3 的线程在第一幕必须锁住"
    assert view.get("locked_msgs") == 1 and view.get("unlock_act") == 3
    st2 = _st()
    st2["dead_character_ids"] = ["b"]
    st2["act"] = 3
    out2 = runtime.peek_attempt(content, st2, "翻乙的手机", "do", MockL())
    assert "edmund" in str([t.get("with") for t in out2["view"]["threads"]])


# ── 深翻附带：浏览器历史 + TA 的未发送草稿（确定性兜底） ──
def test_deep_peek_browser_and_drafts():
    st = _st()
    st["dead_character_ids"] = ["b"]
    out = runtime.peek_attempt(CONTENT, st, "翻乙的手机", "do", MockL())
    view = out["view"]
    assert view.get("browser"), "深翻必须给搜索历史（LLM 空手时走确定性兜底）"
    assert isinstance(view.get("drafts"), list)


# ── 刀① 玩家发帖 → 角色看见 / 记忆 / 对白引用 ────────────
def test_player_post_flow():
    st = _st()
    post = socialfic.player_post(CONTENT, st, "三天没出门了。我居然不讨厌这里。")
    assert post["mine"] and post["text"].startswith("三天")
    posts = (st.get("social") or {}).get("posts") or []
    assert posts and posts[0].get("mine")
    # 已认识的角色记在心里（进各自的 memory_by_char，不开天眼）
    assert "动态" in (st.get("memory_by_char") or {}).get("b", "")
    # 亲密度≥30 的自动点赞（确定性，不烧调用）
    assert "乙" in (posts[0].get("liked_by") or [])
    # 对白引用：主叙者拿一次就核销
    line = socialfic.take_echo(CONTENT, st)
    assert line and "三天没出门" in line
    assert socialfic.take_echo(CONTENT, st) is None


def test_player_post_validation():
    st = _st()
    import pytest
    with pytest.raises(ValueError):
        socialfic.player_post(CONTENT, st, "   ")
    socialfic.player_post(CONTENT, st, "x" * 999)
    assert len(((st.get("social") or {}).get("posts") or [])[0]["text"]) <= 280


# ── 刀② 拉黑三档 + 非对称账本 ────────────────────────────
def test_mute_silences_badge_only():
    st = _st()
    st.setdefault("phone", {}).setdefault("threads", {})["b"] = {
        "msgs": [{"from": "them", "text": "在吗", "at": "夜"}], "unread": 2}
    base = runtime.phone_total_unread(CONTENT, st)
    socialfic.set_block(CONTENT, st, "b", "mute")
    assert runtime.phone_total_unread(CONTENT, st) == base - 2
    # mute 不拦投递（只是不吵你）
    p = runtime.phone_push(CONTENT, st, CONTENT["story"]["characters"][1], ["还在吗"], "夜")
    assert p is not None


def test_block_holds_messages_and_release_replays():
    st = _st()
    socialfic.set_block(CONTENT, st, "b", "block")
    ch = CONTENT["story"]["characters"][1]
    p = runtime.phone_push(CONTENT, st, ch, ["我知道你能看到", "就当我说给墙听"], "夜")
    assert p is None, "拉黑期消息必须被暂扣，不投递不冒泡"
    th = ((st.get("phone") or {}).get("threads") or {}).get("b") or {}
    assert not (th.get("msgs") or []), "线程里一条都不能出现"
    held = socialfic.held_count(st, "b")
    assert held == 2
    # TA 记在心里 + 关系确定性受挫
    assert "拉黑" in (st.get("memory_by_char") or {}).get("b", "")
    assert ((st.get("rel") or {}).get("b") or {}).get("closeness", 99) < 35
    # 解除：暂扣按原时序回放进线程（未读亮起）
    out = socialfic.set_block(CONTENT, st, "b", None)
    assert out.get("released") == 2
    th = ((st.get("phone") or {}).get("threads") or {}).get("b") or {}
    assert len(th.get("msgs") or []) == 2 and int(th.get("unread") or 0) >= 2
    assert socialfic.held_count(st, "b") == 0


def test_removed_leaves_the_stage_and_returns():
    import copy
    content = copy.deepcopy(CONTENT)
    st = _st()
    socialfic.set_block(content, st, "b", "removed")
    ids = [c.get("id") for c in runtime.cast_for(content, 1, state=st)]
    assert "b" not in ids, "移出剧情 = 下台（走 presence 机制）"
    socialfic.set_block(content, st, "b", None)
    ids = [c.get("id") for c in runtime.cast_for(content, 1, state=st)]
    assert "b" in ids, "撤销后人要回来（可撤销不删档）"


def test_blocked_rider_reaches_the_actor_prompt():
    import copy
    content = copy.deepcopy(CONTENT)
    st = _st()
    socialfic.set_block(content, st, "b", "block")

    class Spy(MockL):
        def generate(self, prompt):
            self.prompts.append(prompt)
            if prompt.get("risk_judge"):
                return {"risk": 100}
            return {"beats": [{"type": "dialogue", "speaker_name": "乙", "text": "……"}],
                    "affinity_delta": 0, "advance_act": False, "ending": None,
                    "next_speakers": []}

    spy = Spy()
    runtime.run_turn(content, st, {"name": "我"}, "对乙：我们谈谈", channel="say", llm=spy)
    riders = [p.get("blocked_line") for p in spy.prompts if p.get("blocked_line")]
    assert riders, "被拉黑的角色，演员提示词里必须有这回事"


# ── 复审修复的执法点 ─────────────────────────────────────
def test_act_lock_also_gates_fragment_harvest():
    """复审 high：按幕锁曾只锁字不锁碎片——玩家一个字没见着，秘密却解了。"""
    import copy
    content = copy.deepcopy(CONTENT)
    content["story"]["characters"][1]["device_peek"] = [
        {"with": "edmund", "msgs": ["深处的事"], "act_min": 3, "reveals": "f_deep"},
    ]
    st = _st()
    st["dead_character_ids"] = ["b"]
    out = runtime.peek_attempt(content, st, "翻乙的手机", "do", MockL())
    assert "f_deep" not in out["frag_ids"], "第一幕不许收到第三幕条目的碎片"
    st3 = _st()
    st3["dead_character_ids"] = ["b"]
    st3["act"] = 3
    out3 = runtime.peek_attempt(content, st3, "翻乙的手机", "do", MockL())
    assert "f_deep" in out3["frag_ids"]


def test_memory_pronoun_convention():
    """复审 high：memory_by_char 里 你=角色本人、对方=玩家（写反=角色栽赃自己）。"""
    import copy
    content = copy.deepcopy(CONTENT)
    st = _st()
    socialfic.set_block(content, st, "b", "block")
    assert "对方把你拉黑了" in (st.get("memory_by_char") or {}).get("b", "")
    st2 = _st()
    socialfic.player_post(CONTENT, st2, "第一天进城，落脚在门厅边上。")
    assert "对方公开发过" in (st2.get("memory_by_char") or {}).get("b", "")


def test_mute_charges_nothing():
    """mute 是玩家单方面静音，TA 无从知晓：不扣关系、不写记忆。"""
    st = _st()
    socialfic.set_block(CONTENT, st, "b", "mute")
    assert ((st.get("rel") or {}).get("b") or {}).get("closeness") == 35
    assert "拉黑" not in (st.get("memory_by_char") or {}).get("b", "")


def test_downgrade_to_mute_replays_held():
    """block→mute 降档 = 不再拦投递 → 积压立刻回放，不许卡在账本里烂掉。"""
    st = _st()
    socialfic.set_block(CONTENT, st, "b", "block")
    ch = CONTENT["story"]["characters"][1]
    runtime.phone_push(CONTENT, st, ch, ["还在吗"], "夜")
    out = socialfic.set_block(CONTENT, st, "b", "mute")
    assert out["released"] == 1
    th = ((st.get("phone") or {}).get("threads") or {}).get("b") or {}
    assert len(th.get("msgs") or []) == 1


def test_removed_respects_authored_offstage():
    """作者本来就 offstage 的人（鬼/未登场），移出再解除不许被强行上台。"""
    import copy
    content = copy.deepcopy(CONTENT)
    content["story"]["characters"][1]["presence"] = "offstage"
    st = _st()
    socialfic.set_block(content, st, "b", "removed")
    socialfic.set_block(content, st, "b", None)
    assert content["story"]["characters"][1]["presence"] == "offstage"


def test_held_cap_counts_dropped():
    """封顶顶掉的要记数：blocked_line 的「N条」不许冻在12，回放要交代丢了几条。"""
    st = _st()
    socialfic.set_block(CONTENT, st, "b", "block")
    ch = CONTENT["story"]["characters"][1]
    for i in range(15):
        runtime.phone_push(CONTENT, st, ch, [f"第{i}条"], "夜")
    assert socialfic.held_count(st, "b") == 15
    out = socialfic.set_block(CONTENT, st, "b", None)
    assert out["released"] == 12
    th = ((st.get("phone") or {}).get("threads") or {}).get("b") or {}
    assert any("3条" in (m.get("text") or "") for m in th.get("msgs") or []), \
        "被顶掉的 3 条要在回放里留一句交代"


def test_deliver_due_diverts_to_held_when_blocked():
    """复审：延迟投递曾绕过拦截——拉黑后，之前判了延迟的回复照样弹进线程。"""
    st = _st()
    st.setdefault("phone", {}).setdefault("threads", {})["b"] = {
        "msgs": [], "unread": 0,
        "pending": [{"text": "晚点回你", "due_ts": 0}]}
    socialfic.set_block(CONTENT, st, "b", "block")
    runtime.deliver_due_phone(CONTENT, st)
    th = st["phone"]["threads"]["b"]
    assert not th["msgs"] and not th["pending"]
    assert socialfic.held_count(st, "b") == 1


def test_bank_transfer_gate():
    st = _st()
    st["money"] = 100
    socialfic.set_block(CONTENT, st, "b", "block")
    import pytest
    with pytest.raises(ValueError):
        runtime.bank_transfer(CONTENT, st, {"name": "我"}, "b", 10, MockL())
    assert st["money"] == 100, "钱一分不许动"


def test_invite_picker_skips_blocked():
    from app.engine import living
    st = _st()
    st.setdefault("contact_ids", ["b"])
    socialfic.set_block(CONTENT, st, "b", "block")
    pick = living._pick_invite_char(CONTENT, st)
    assert not (pick and pick.get("id") == "b"), "拉黑的人不许被选来发邀约"


# ── 刀③ 世界论坛 ─────────────────────────────────────────
def test_forum_feed_mints_and_player_posts():
    st = _st()
    feed = socialfic.forum_feed(CONTENT, st, MockL())
    assert feed["channels"], "频道从剧本数据推导（不许写死具体剧本）"
    assert feed["posts"], "首铸必须有帖（LLM 空手走确定性兜底）"
    anon = [p for p in feed["posts"] if p.get("anon")]
    assert anon and all(p.get("author") not in ("甲", "乙") for p in anon), \
        "匿名帖不许露真名"
    assert all(p.get("cid") is None for p in anon), \
        "复审 high：匿名帖的真实 cid 不许出 API（devtools 一眼穿=没有马甲）"
    # met 门：没见过的角色不进论坛素材（信息不开天眼）
    st_unmet = _st()
    st_unmet["met_ids"] = ["a"]          # 乙没见过
    mat = socialfic._forum_material(CONTENT, st_unmet)
    assert all(i["cid"] != "b" for i in mat)
    # 自名洗涤：账本句里发帖人自己的名字改第一人称
    st_name = _st()
    st_name["npc_rel"] = {"a|b": {"stance": 1, "label": "",
                                  "log": [{"why": "乙把甲堵在后巷质问"}]}}
    mat2 = socialfic._forum_material(CONTENT, st_name)
    b_item = next((i for i in mat2 if i["cid"] == "b"), None)
    if b_item:
        assert all("乙" not in h for h in b_item["hooks"]), "匿名者不许喊自己的名字"
    # 玩家发帖
    mine = socialfic.forum_player_post(CONTENT, st, "有人真的在这里过过冬吗？",
                                       feed["channels"][0])
    assert mine.get("author") == "you"
    feed2 = socialfic.forum_feed(CONTENT, st, MockL())
    my = next(p for p in feed2["posts"] if p.get("author") == "you")
    assert my.get("replies"), "玩家的帖要有人接话（下次取流时铸一条回复）"


def test_forum_spoiler_safety():
    """论坛素材只走账本人话，锁着的秘密正文一个字不许上墙。"""
    import copy
    content = copy.deepcopy(CONTENT)
    content["secrets"] = [{"id": "sec1", "title": "旧事", "character_id": "b",
                           "fragments": [{"id": "f1", "layer": 1,
                                          "content": "SECRET_BODY_XYZ",
                                          "unlock": {"affinity_min": 99}}]}]
    st = _st()
    feed = socialfic.forum_feed(content, st, MockL())
    assert "SECRET_BODY_XYZ" not in str(feed)


# ── HTTP 面 ──────────────────────────────────────────────
def test_http_endpoints_roundtrip():
    from fastapi.testclient import TestClient

    from app.db import Base, engine
    from app.main import app
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    API = "/api/v1"
    with TestClient(app) as c:
        c.post(f"{API}/auth/signup", json={"email": "d@x.com", "password": "password1",
                                           "dob": "1990-01-01", "accepted_tos": True})
        story = c.post(f"{API}/stories", json={
            "title": "PackD", "visibility": "public",
            "characters": [{"id": "n1", "name": "掌柜", "is_lead": True}],
            "acts": [{"index": 1, "title": "一"}],
        }).json()
        c.post(f"{API}/stories/{story['id']}/publish")
        persona = c.post(f"{API}/personas", json={"name": "Ash"}).json()
        run = c.post(f"{API}/runs", json={"story_id": story["id"],
                                          "persona_id": persona["id"]}).json()
        rid = run["id"]
        # 发动态
        r = c.post(f"{API}/runs/{rid}/social/post", json={"text": "第一天进城。"})
        assert r.status_code == 200 and r.json()["post"]["mine"]
        assert any(p.get("mine") for p in c.get(f"{API}/runs/{rid}/social").json()["posts"])
        # 拉黑 → 手机发送被拒 → 状态可见 → 解除（先打个照面：没见过的人拉不了黑）
        c.post(f"{API}/runs/{rid}/play", json={"input": "你好", "channel": "say"})
        assert c.post(f"{API}/runs/{rid}/character/n1/block",
                      json={"level": "block"}).status_code == 200
        assert c.post(f"{API}/runs/{rid}/phone/n1",
                      json={"text": "在吗"}).status_code == 400
        assert (c.get(f"{API}/runs/{rid}").json()["state"].get("blocks") or {}) \
            .get("n1") == "block"
        assert c.delete(f"{API}/runs/{rid}/character/n1/block").status_code == 200
        # 论坛
        f = c.get(f"{API}/runs/{rid}/forum").json()
        assert f["channels"] and isinstance(f["posts"], list)
        r = c.post(f"{API}/runs/{rid}/forum/post",
                   json={"text": "掌柜的酒是不是掺水了？", "channel": f["channels"][0]})
        assert r.status_code == 200
