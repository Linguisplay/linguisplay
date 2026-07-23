# -*- coding: utf-8 -*-
"""📱🔍 查TA的设备 (Yi 拍板 2026-07-20): 随身版搜查物证。
执法点: 机会窗口 (账本无新货不开窗/每游戏日一次) · 浅翻结构化防泄密 (素材不含秘密) ·
渲染缓存一次生成 · 立场跳变插转折 · crit_fail 锁死 · device_of 通道 + lint 三规。"""

from app.engine import logic, runtime

STORY = {
    "story": {"id": "s", "phone": {"device": "传呼机"},
              "tuning": {"peek_drop_chance": 100},
              "characters": [
                  {"id": "a", "name": "甲", "is_lead": True},
                  {"id": "b", "name": "乙", "eq_style": "嘴硬",
                   "ties": [{"char_id": "c", "stance": 1, "label": "老搭档"}],
                   "device_peek": [{"with": "神秘号码", "msgs": ["货到了", "老地方"],
                                    "reveals": "f_dev"}]},
                  {"id": "c", "name": "丙"}],
              "acts": [{"index": 1, "title": "一"}],
              "locations": [{"id": "hall", "name": "门厅", "detail": "一盏吊灯"}]},
    "secrets": [
        {"id": "s1", "character_id": "b", "title": "毒药的事", "sensitivity": "heavy",
         "fragments": [
             {"id": "f_dev", "content": "SECRETX 毒药藏在夹层", "retrieval_key": "毒药",
              "unlock": {"asks_min": 3, "device_of": "b"}}]},
    ],
}


class PeekLLM:
    def __init__(self):
        self.prompts = []

    def generate(self, prompt):
        self.prompts.append(prompt)
        if prompt.get("peek_nickname"):
            return {"nickname": "多管闲事的"}
        if prompt.get("peek_threads"):
            return {"msgs": ["丙:钱呢", "乙:月底一定给"]}
        if prompt.get("peek_twist"):
            return {"msgs": ["以后别用这个号找我"]}
        return {}


class _Roll:
    def __init__(self, v):
        self.v = v

    def randint(self, a, b):
        return self.v


def _state_with_ledger():
    st = runtime.default_state()
    st["npc_rel"] = {"b|c": {"stance": 1, "label": "老搭档", "log": [{"why": "分账"}]}}
    st["met_ids"] = ["b", "c"]
    return st


def test_window_gates_ledger_and_daily_cap(monkeypatch):
    st = _state_with_ledger()
    ev = runtime.peek_maybe_drop(STORY, st, "b", "乙")
    assert ev and ev["kind"] == "peek_window"          # 账本有货 + 100% → 开窗
    st["phone_peek"]["b"]["window"] = 0                # 窗口过期后同日再离场
    assert runtime.peek_maybe_drop(STORY, st, "b", "乙") is None   # 每游戏日一次
    st2 = runtime.default_state()                      # 账本全空 → 不开窗不骗人
    assert runtime.peek_maybe_drop(STORY, st2, "b", "乙") is None


def test_shallow_structural_no_secret_then_deep_unlocks(monkeypatch):
    monkeypatch.setattr(runtime, "_rng", _Roll(20))
    st = _state_with_ledger()
    runtime.peek_open_window(st, "b")
    llm = PeekLLM()
    out1 = runtime.peek_attempt(STORY, st, "翻乙的传呼机", "do", llm)
    text1 = out1["beats"][0]["text"]
    assert "多管闲事的" in text1 and out1["frag_ids"] == []       # 浅翻: 备注名彩蛋, 无碎片
    # 🛡 防泄密压测: 渲染素材结构化保证不含秘密 (retrieval_key/正文都不进提示词)
    blob = str(llm.prompts)
    assert "SECRETX" not in blob and "毒药" not in blob
    out2 = runtime.peek_attempt(STORY, st, "翻乙的传呼机", "do", llm)   # 同窗第二次=深翻
    text2 = out2["beats"][0]["text"]
    assert "货到了" in text2                                       # authored 素材可见
    # 📱 P1 手机壳: 浅/深翻都要带结构化视图 (前端渲染TA的设备界面)
    assert out1["view"]["mode"] == "shallow" and out1["view"]["nickname"] == "多管闲事的"
    assert out2["view"]["mode"] == "deep"
    assert any(t["with"] == "神秘号码" for t in out2["view"]["threads"])
    assert "f_dev" in out2["frag_ids"]                             # device_of + reveals 收成
    # 缓存一次生成: 两次尝试 peek_threads 只调过一次
    assert sum(1 for p in llm.prompts if p.get("peek_threads")) == 1


def test_crit_fail_locks_device_forever(monkeypatch):
    monkeypatch.setattr(runtime, "_rng", _Roll(1))
    st = _state_with_ledger()
    runtime.peek_open_window(st, "b")
    llm = PeekLLM()
    out = runtime.peek_attempt(STORY, st, "翻乙的传呼机", "do", llm)
    assert any(m["kind"] == "peek_caught" for m in out["moments"])
    assert st["phone_peek"]["b"]["locked"]
    assert int(st["rel"]["b"]["closeness"]) < 0                    # 好感真掉了
    assert "抓住" in st["memory_by_char"]["b"]                     # TA记了一笔
    monkeypatch.setattr(runtime, "_rng", _Roll(20))
    runtime.peek_open_window(st, "b")                              # 锁死后连窗口都白开
    out2 = runtime.peek_attempt(STORY, st, "翻乙的传呼机", "do", llm)
    assert "封死" in out2["beats"][0]["text"]


def test_stance_flip_inserts_twist(monkeypatch):
    monkeypatch.setattr(runtime, "_rng", _Roll(20))
    st = _state_with_ledger()
    runtime.peek_open_window(st, "b")
    llm = PeekLLM()
    runtime.peek_attempt(STORY, st, "翻乙的传呼机", "do", llm)      # 建缓存 snap=1
    st["npc_rel"]["b|c"]["stance"] = -2                            # 翻脸
    runtime.peek_open_window(st, "b")
    st["phone_peek"]["b"]["shallow_done"] = False
    runtime.peek_attempt(STORY, st, "翻乙的传呼机", "do", llm)
    assert any(p.get("peek_twist") for p in llm.prompts)
    th = st["phone_peek"]["b"]["threads"]["c"]
    assert th["snap"] == -2 and "别用这个号" in th["msgs"][-1]


def test_peek_lint_rules():
    base = {"story": {
        "phone": {"device": "口信"},
        "characters": [{"id": "c1", "name": "甲", "is_lead": True}],
        "acts": [{"index": 1, "title": "一"}],
        "locations": [{"id": "l1", "name": "码头"}]},
        "secrets": [{"id": "s1", "character_id": "c1", "title": "秘",
                     "fragments": [{"id": "f1", "content": "x",
                                    "unlock": {"device_of": "ghost"}}]}]}
    codes = {i["code"] for i in logic.lint_story(base)}
    assert {"peek_bad_char", "peek_no_device", "peek_no_backup"} <= codes
    ok = {"story": {
        "phone": {"device": "手机"},
        "characters": [{"id": "c1", "name": "甲", "is_lead": True}],
        "acts": [{"index": 1, "title": "一"}],
        "locations": [{"id": "l1", "name": "码头"}]},
        "secrets": [{"id": "s1", "character_id": "c1", "title": "秘",
                     "fragments": [{"id": "f1", "content": "x",
                                    "unlock": {"device_of": "c1", "asks_min": 3}}]}]}
    codes_ok = {i["code"] for i in logic.lint_story(ok)}
    assert not ({"peek_bad_char", "peek_no_device", "peek_no_backup"} & codes_ok)


def test_window_ticks_away():
    st = _state_with_ledger()
    runtime.peek_open_window(st, "b")
    for _ in range(3):
        runtime.peek_tick(st)
    llm = PeekLLM()
    out = runtime.peek_attempt(STORY, st, "翻乙的传呼机", "do", llm)
    assert "不在你够得到" in out["beats"][0]["text"]                # 机会稍纵即逝


def test_near_location_reroutes_instead_of_generating():
    """🧭 近似命中改道 (Yi 实弹:「城寨外」对「九龙城寨室外」漏配 → 弹造新地点条):
    有近亲就指真名确认, 绝不铸重复的幽灵地点; 真正的新地名照旧可造。"""
    content = {"story": {
        "characters": [{"id": "a", "name": "甲", "is_lead": True}],
        "acts": [{"index": 1, "title": "一"}],
        "locations": [
            {"id": "l1", "name": "天台", "exits": ["九龙城寨室外"]},
            {"id": "l2", "name": "九龙城寨室外", "exits": ["天台"]}]},
        "secrets": []}
    assert runtime.near_location(content, "城寨外")["id"] == "l2"     # LCS=城寨/寨外 ≥2
    assert runtime.near_location(content, "阿柒冰室") is None          # 真新地名不误配
    assert runtime.resolve_location(content, "城寨外") is None         # 严格解析器保持严格


def test_mention_mints_location_without_travel():
    """📍 提及即立档 (Yi: 玩家不去也该先生成): 说起新去处 → 地点当场进世界与地图,
    确认条变普通去处 (minted 标); 玩家原地不动。"""
    content = {"story": {
        "sandbox": {"enabled": True},
        "characters": [{"id": "a", "name": "甲", "is_lead": True}],
        "acts": [{"index": 1, "title": "一"}],
        "locations": [{"id": "start", "name": "起点", "detail": "空", "exits": []}]},
        "secrets": []}

    class PlaceLLM:
        def generate(self, prompt):
            if prompt.get("describe_place"):
                return {"name": "河湾旧渡口", "detail": "锈链系着半沉的木船"}
            if prompt.get("intro") or prompt.get("observe") or prompt.get("suggest") \
                    or prompt.get("risk_judge"):
                return {"risk": 100} if prompt.get("risk_judge") else \
                       {"beats": [{"type": "description", "speaker_name": None, "text": "x"}],
                        "affinity_delta": 0, "advance_act": False, "ending": None}
            return {"beats": [{"type": "dialogue", "speaker_name": "甲", "text": "嗯"}],
                    "affinity_delta": 0, "advance_act": False, "ending": None}

    st = runtime.default_state()
    st["location_id"] = "start"
    out = runtime.run_turn(content, st, {"name": "我"}, "去河湾旧渡口看看", channel="do",
                           llm=PlaceLLM())
    mr = out.get("move_request") or {}
    assert mr.get("minted") and mr.get("to")                     # 普通确认条, 非 generate
    names = [l.get("name") for l in content["story"]["locations"]]
    assert "河湾旧渡口" in names                                  # 已立档进世界
    assert out["state"].get("location_id") == "start"            # 玩家没动
    assert out.get("content_mutated")                            # 私有副本会持久化
    au = [a for a in out["state"].get("last_audit") or [] if a.get("e") == "place.mint"]
    assert au and "立档" in au[0].get("why", "")
