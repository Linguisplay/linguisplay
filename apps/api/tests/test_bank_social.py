# -*- coding: utf-8 -*-
"""🏦📸 小手机新 app (Yi 拍板 2026-07-20, P0 纯内环): 银行=money 账本视图+转账落账;
社媒=活世界账本的可见面 (指纹缓存/点赞回好感一次/评论限频)。皮肤铁律: 仅现代设定默认开。"""

from app.engine import runtime

MODERN = {
    "story": {"id": "s", "phone": {"device": "手机"},
              "sandbox": {"enabled": True, "currency": "元", "start_money": 100},
              "characters": [
                  {"id": "a", "name": "甲", "is_lead": True},
                  {"id": "b", "name": "乙", "eq_style": "嘴硬心软"}],
              "acts": [{"index": 1, "title": "一"}],
              "locations": [{"id": "hall", "name": "门厅", "detail": "一盏吊灯"}]},
    "secrets": [],
}
PERIOD = {"story": {**MODERN["story"], "phone": {"device": "传呼机"}}, "secrets": []}


class AppLLM:
    def __init__(self):
        self.prompts = []

    def generate(self, prompt):
        self.prompts.append(prompt)
        if prompt.get("compose_msg"):
            return {"msgs": ["钱收到了。你什么意思？"]}
        if prompt.get("social_posts"):
            return {"posts": [{"name": "乙", "text": "夜里的巷子比白天诚实。"}]}
        if prompt.get("social_reply"):
            return {"reply": "就你会说话。", "closeness": 1}
        return {}


def _st(money=100):
    st = runtime.default_state()
    st["money"] = money
    st["met_ids"] = ["b"]
    st["contact_ids"] = ["b"]
    st["npc_rel"] = {"a|b": {"stance": 1, "label": "", "log": [{"why": "同桌喝了顿酒"}]}}
    return st


def test_apps_skin_law():
    assert runtime.phone_apps(MODERN) == {"bank", "social"}     # 现代默认开
    custom = {"story": {**PERIOD["story"], "phone": {"device": "传呼机", "apps": ["bank"]}},
              "secrets": []}
    assert runtime.phone_apps(custom) == {"bank"}               # 作者显式配置优先


# ── 📱 沙盒的小手机任何年代全开 (Yi 2026-08-04) ───────────────────────────────
# ⚠️ 这一条是对旧合同「传呼机时代没有 app」的【有意反转】, 不是回归。
# 玩家自己写的世界可能是任何年代, 传讯符也好飞鸽也好, 那是称谓; 功能是界面,
# 不该被年代关掉。称谓换皮在客户端做 (古风叫「风声」「账房」)。
def test_a_sandbox_keeps_every_app_no_matter_what_the_device_is_called():
    assert runtime.phone_apps(PERIOD) == {"bank", "social"}, \
        "沙盒里换个设备名就少一个 app = 年代把功能关掉了"
    for device in ("传呼机", "传讯符", "飞鸽", "纸鹤", "沃克斯通讯珠", "pager"):
        c = {"story": {**MODERN["story"], "phone": {"device": device}}, "secrets": []}
        assert runtime.phone_apps(c) == {"bank", "social"}, f"{device} 少了 app"


def test_an_authored_story_still_goes_by_its_device_skin():
    """放开的只有沙盒。授权剧情本的年代与设备是作者写死的, 引擎不越权替他改。"""
    period_story = {**MODERN["story"], "phone": {"device": "传讯符"}, "sandbox": {}}
    assert runtime.phone_apps({"story": period_story, "secrets": []}) == set()
    modern_story = {**MODERN["story"], "phone": {"device": "手机"}, "sandbox": {}}
    assert runtime.phone_apps({"story": modern_story, "secrets": []}) == {"bank", "social"}


def test_the_bank_is_still_gated_by_the_money_ledger_not_by_the_era():
    """银行还有第二道门 (phone_threads_view): 没有钱账本就不亮。

    这【不是年代门】—— 没有账本的银行是个空壳, 点进去只有一句「无账可管」,
    那不叫开启, 叫上了个假图标。这条专门盯着它, 免得下次有人当成漏掉的。
    """
    st = runtime.default_state()
    st["money"] = None                      # 没有钱账本的剧情本
    view = runtime.phone_threads_view(PERIOD, st)
    assert view["apps"] == ["social"], "没有账本却亮了银行"
    st["money"] = 0                         # 有账本 (余额为 0 也算有)
    assert set(runtime.phone_threads_view(PERIOD, st)["apps"]) == {"bank", "social"}


def test_bank_transfer_books_and_echoes():
    st = _st(100)
    out = runtime.bank_transfer(MODERN, st, {"name": "我"}, "b", 30, llm=AppLLM())
    assert st["money"] == 70
    assert any(l["delta"] == -30 and "乙" in l["why"] for l in st["money_log"])
    assert "转了30" in st["memory_by_char"]["b"]                 # TA 记得这笔钱
    assert out["reply"]["msgs"]                                  # TA 的短信回应进了线程
    assert st["phone"]["threads"]["b"]["unread"] >= 1
    # 拒绝面: 余额不够 / 没联系方式
    try:
        runtime.bank_transfer(MODERN, st, {"name": "我"}, "b", 999, llm=AppLLM())
        assert False
    except ValueError as e:
        assert "余额" in str(e)
    st2 = _st(100)
    st2["contact_ids"] = []
    st2["phone"] = {}
    try:
        runtime.bank_transfer(MODERN, st2, {"name": "我"}, "b", 10, llm=AppLLM())
        assert False
    except ValueError as e:
        assert "联系方式" in str(e)


def test_social_feed_cached_by_ledger_mark():
    st = _st()
    llm = AppLLM()
    v1 = runtime.social_feed(MODERN, st, llm=llm)
    assert any("巷子" in p["text"] for p in v1["posts"])
    n_calls = sum(1 for p in llm.prompts if p.get("social_posts"))
    runtime.social_feed(MODERN, st, llm=llm)                     # 账本没动 → 不再调用
    assert sum(1 for p in llm.prompts if p.get("social_posts")) == n_calls


def test_social_like_once_and_comment_limited():
    st = _st()
    llm = AppLLM()
    v = runtime.social_feed(MODERN, st, llm=llm)
    pid = v["posts"][0]["id"]
    runtime.social_like(MODERN, st, pid)
    c1 = int(st["rel"]["b"]["closeness"])
    runtime.social_like(MODERN, st, pid)                          # 重复点赞不叠加
    assert int(st["rel"]["b"]["closeness"]) == c1 and c1 >= 1
    out = runtime.social_comment(MODERN, st, {"name": "我"}, pid, "写得好", llm=llm)
    assert out["reply"] == "就你会说话。"
    assert [c["from"] for c in out["comments"]] == ["me", "them"]
    st["social"]["cnum"] = 5                                      # 当日限频
    try:
        runtime.social_comment(MODERN, st, {"name": "我"}, pid, "再说一句", llm=llm)
        assert False
    except ValueError as e:
        assert "限5条" in str(e)


def test_opening_visitor_authored_override():
    """🎬 开场访客点名 (实弹: 男主标 stranger 永远轮不到, 开场被 peer 配角抢走):
    sandbox.opening_visitor 点谁谁来接场; 点名无效回落档位排序。"""
    content = {"story": {
        "sandbox": {"enabled": True, "opening_visitor": "hero"},
        "characters": [
            {"id": "extra", "name": "跑龙套", "relation_default": "peer",
             "home_location_id": "far"},
            {"id": "hero", "name": "男主", "relation_default": "stranger",
             "home_location_id": "far"}],
        "acts": [{"index": 1, "title": "一"}],
        "locations": [{"id": "start", "name": "起点", "detail": "空"},
                      {"id": "far", "name": "远处", "detail": "远"}]},
        "secrets": []}
    st = runtime.default_state()
    st["location_id"] = "start"
    runtime.build_opening(content, st)
    au = [a for a in st.get("last_audit") or [] if a.get("e") == "opening.visitor"]
    assert au and au[0]["data"] == "男主"
    # 点名无效 (乱写的id) → 回落档位: peer 的跑龙套接场
    content2 = {"story": {**content["story"],
                          "sandbox": {"enabled": True, "opening_visitor": "nobody"}},
                "secrets": []}
    st2 = runtime.default_state()
    st2["location_id"] = "start"
    runtime.build_opening(content2, st2)
    au2 = [a for a in st2.get("last_audit") or [] if a.get("e") == "opening.visitor"]
    assert au2 and au2[0]["data"] == "跑龙套"


def test_approach_tactics_by_relation():
    """🎯 手段库 (Yi: 干活维持剧情太扁平 — 不同初始关系用不同手段):
    追求线走追求阶梯绝不派差事; 长辈吩咐差事合理; playbook 注入手段块。"""
    from app.engine import relationships as R
    court_char = {"name": "男主", "relation_default": "stranger", "love_style": "sunny"}
    blk = R.approach_block(court_char, "stranger")
    assert "刷存在感" in blk and "绝不派差事" in blk and "留个口实" in blk
    elder_blk = R.approach_block({"name": "师父"}, "elder")
    assert "吩咐" in elder_blk and "刷存在感" not in elder_blk
    pb = R.playbook_block("stranger", char=court_char)
    assert "追求阶梯" in pb                                   # 手段块进了 playbook
    assert "追求阶梯" not in R.playbook_block("stranger")     # 不传 char 不注入 (兼容)


def test_opening_hook_court_vs_errand():
    """🎬 开场钩子分道: 追求线访客留口实 (不派差事); 长辈访客照旧吩咐差事。"""
    def story(visitor):
        return {"story": {
            "sandbox": {"enabled": True, "opening_visitor": "v1"},
            "characters": [visitor,
                           {"id": "far1", "name": "远人", "home_location_id": "far"}],
            "acts": [{"index": 1, "title": "一"}],
            "locations": [{"id": "start", "name": "起点", "detail": "空"},
                          {"id": "far", "name": "远处", "detail": "远"}]},
            "secrets": []}
    court = {"id": "v1", "name": "男主", "relation_default": "stranger",
             "love_style": "sunny", "home_location_id": "far",
             "examples": ["第一句。", "顺路买了两份糖水，一起？"]}

    class NullLLM:                                  # 打确定性兜底分支 (Mock 孪生自带钩子)
        def generate(self, prompt):
            return {}
    st = runtime.default_state()
    st["location_id"] = "start"
    beats = runtime.build_opening(story(court), st, llm=NullLLM())
    au = [a for a in st.get("last_audit") or [] if a.get("e") == "opening.hook"]
    assert au and "捎样东西" not in au[0]["data"]              # 不是差事
    assert any("糖水" in (b.get("text") or "") for b in beats)  # 台词范例当了口实
    assert any("道声谢" in s for s in st.get("suggestions") or [])
    elder = {"id": "v1", "name": "师父", "relation_default": "elder",
             "home_location_id": "far"}
    st2 = runtime.default_state()
    st2["location_id"] = "start"
    runtime.build_opening(story(elder), st2, llm=NullLLM())
    au2 = [a for a in st2.get("last_audit") or [] if a.get("e") == "opening.hook"]
    assert au2 and "捎样东西" in au2[0]["data"]                # 上下级照旧派差事
