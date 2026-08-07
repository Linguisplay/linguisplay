# -*- coding: utf-8 -*-
"""🫂 任何时候都有一个关系 (Yi 2026-08-06)。

Yi:「人与人之间无论什么时候都有一个关系存在，AI 角色和玩家也不例外。现在开始
AI 角色和玩家之间在关系网里的关系、角色对玩家的情绪，都要有这个关系。然后这个
关系就是要定时结合上下文得出判断。」

查出来的现状，三条都不满足:

① 【不是任何时候都有】relweb 里 `sc = rel_all.get(cid); if not sc: continue` ——
   见过面但还没打过分的人，关系网上跟玩家之间【一条边都没有】。
   生产实测: 205 人次里 19 个 (9%) 无边, 3 局整局画不出一条玩家边。

② 【情绪跟关系是脱节的】state 里那个 mood 是【场面情绪】(日常/温馨/悬疑/战斗),
   给配乐用的, 不是"TA 此刻对玩家什么感觉"。角色对玩家的情绪压根没有存过。

③ 【没有任何重判】关系 = derive_mode(亲近, 心动) 比阈值, 纯算术, 不看上下文,
   也从来不重算 —— 只有分数变了它才变。

节奏为什么不能挂在记忆折叠上: 那条路要等 history 长到 20 条才第一次开火,
而生产中位一局 14 拍。挂上去等于大多数玩家永远等不到 —— 跟 offline_pulse
同一个坑 (它只在"玩家离开又回来"那一拍开火, 而中位玩家从来没回来过)。
关系恰恰是头几拍定下来的, 所以第一次重判必须早。
"""
import pytest

from app.engine import runtime, relationships


CONTENT = {"story": {
    "id": "s", "title": "t",
    "characters": [
        {"id": "a", "name": "阿彩", "is_lead": True, "persona_text": "洗头妹",
         "home_location_id": "hall"},
        {"id": "b", "name": "十二少", "persona_text": "四子之一", "base_mode": "peer",
         "home_location_id": "hall"},
    ],
    "acts": [{"index": 1, "title": "一"}],
    "locations": [{"id": "hall", "name": "祥记面档", "detail": "面档", "exits": []}]}, "secrets": []}


def _st(**kw):
    st = runtime.default_state()
    st["location_id"] = "hall"
    st["clock"] = {"day": 1, "slot": 0, "turns_in_slot": 0}
    st.update(kw)
    return st


# ── ① 见了面就有关系, 不许是空的 ──────────────────────────────────────────────

def test_a_met_character_always_has_a_relation():
    """没打过分不等于没关系 —— 那也是一种关系 (初识/同僚/戒备)。"""
    st = _st(met_ids=["a"])
    got = runtime.relation_of(CONTENT, st, "a")
    assert got, "见过面的人, 关系是空的"
    assert got.get("mode"), f"没有关系档位: {got}"


def test_it_falls_back_to_what_the_author_wrote():
    """作者给十二少写了 base_mode=peer, 没分数时就该是它, 不该凭空捏一个。"""
    st = _st(met_ids=["b"])
    assert runtime.relation_of(CONTENT, st, "b").get("mode") == \
        relationships.initial_mode(CONTENT["story"]["characters"][1])


def test_scores_still_win_when_they_exist():
    """有账就按账走 —— 这一刀不许把 rel_events 那本账架空。"""
    st = _st(met_ids=["a"], rel={"a": {"closeness": 90, "romance": 90}})
    tun = runtime.tuning_for(CONTENT)
    want = relationships.derive_mode(CONTENT["story"]["characters"][0],
                                     st["rel"]["a"], tun)
    assert runtime.relation_of(CONTENT, st, "a").get("mode") == want


def test_a_stranger_you_never_met_has_no_relation():
    """认知边界: 没见过的人不该凭空有关系。"""
    assert runtime.relation_of(CONTENT, _st(), "a") is None


def test_the_player_character_has_no_relation_with_themselves():
    st = _st(met_ids=["a"], player_character_id="a")
    assert runtime.relation_of(CONTENT, st, "a") is None


# ── ② 角色对玩家的情绪, 挂在这个关系上 ────────────────────────────────────────

def test_the_relation_carries_a_feeling():
    st = _st(met_ids=["a"])
    runtime.apply_relation_read(st, "a", {
        "mode": "戒备的熟人", "feeling": "还在气你当众驳他，但没打算翻脸",
        "why": "你当着老张的面驳了他"})
    got = runtime.relation_of(CONTENT, st, "a")
    assert "气你" in (got.get("feeling") or ""), f"情绪没挂上: {got}"
    assert got.get("why"), "判断没有依据 —— 空话没法验"


def test_the_read_overrides_the_arithmetic_label():
    """「结合上下文得出判断」的价值就在这儿: 算术说朋友, 上下文可以说「面和心不和」。"""
    st = _st(met_ids=["a"], rel={"a": {"closeness": 60, "romance": 0}})
    before = runtime.relation_of(CONTENT, st, "a")["mode"]
    runtime.apply_relation_read(st, "a", {"mode": "面和心不和", "feeling": "笑着，心里记着账"})
    after = runtime.relation_of(CONTENT, st, "a")
    assert after["mode"] == "面和心不和" and after["mode"] != before


def test_the_ledger_mode_is_still_reachable():
    """覆盖不等于抹掉: 算术那档要留着, 引擎里靠它开门的地方 (同行/看手机/床戏) 不能受影响。"""
    st = _st(met_ids=["a"], rel={"a": {"closeness": 90, "romance": 90}})
    runtime.apply_relation_read(st, "a", {"mode": "面和心不和", "feeling": "x"})
    got = runtime.relation_of(CONTENT, st, "a")
    assert got.get("ledger_mode") == "lover", f"账上那档丢了: {got}"


def test_a_junk_read_is_refused():
    """模型吐空话不许落账 —— 落了就再也分不清哪些是真判过的。"""
    st = _st(met_ids=["a"])
    runtime.apply_relation_read(st, "a", {"mode": "", "feeling": ""})
    assert not (st.get("rel_read") or {}).get("a")


# ── ③ 定时重判: 节奏必须早, 否则等于没做 ──────────────────────────────────────

def test_the_first_read_fires_early():
    """中位一局 14 拍。第一次重判要是等到第 20 拍, 大多数玩家一辈子等不到。"""
    st = _st(met_ids=["a"])
    fired = next((n for n in range(1, 21)
                  if runtime.relation_read_due(st, "a", n)), None)
    assert fired is not None and fired <= 4, f"第一次重判要等到第 {fired} 拍, 太晚"


def test_it_does_not_fire_every_turn():
    """每拍都判 = 每拍多一次模型调用, 而且正是 Yi 定过的「不许每句话打分」。"""
    st = _st(met_ids=["a"])
    hits = 0
    for n in range(1, 41):
        if runtime.relation_read_due(st, "a", n):
            hits += 1
            runtime.apply_relation_read(st, "a", {"mode": "熟人", "feeling": "还行"}, at=n)
    assert 2 <= hits <= 9, f"40 拍里判了 {hits} 次"


def test_a_fresh_read_suppresses_the_next_one():
    st = _st(met_ids=["a"])
    runtime.apply_relation_read(st, "a", {"mode": "熟人", "feeling": "还行"}, at=10)
    assert not runtime.relation_read_due(st, "a", 11)


def test_it_is_per_character():
    """认知边界: 判过阿彩不等于判过十二少。"""
    st = _st(met_ids=["a", "b"])
    runtime.apply_relation_read(st, "a", {"mode": "熟人", "feeling": "x"}, at=3)
    assert not runtime.relation_read_due(st, "a", 4)
    assert runtime.relation_read_due(st, "b", 4)


def test_an_unmet_character_is_never_due():
    assert not runtime.relation_read_due(_st(), "a", 9)


# ── ④ 判出来的东西必须真进提示词, 否则关系只是个摆设 ──────────────────────────

def _sys(**kw):
    from app.engine import qwen
    p = {"speaker_name": "阿彩", "speaker_persona": "洗头妹", "channel": "say",
         "persona": {"name": "蔡妍"}, "context": {}}
    p.update(kw)
    return qwen._build_system(p)


def test_the_feeling_reaches_the_scene_prompt():
    s = _sys(relation_read={"mode": "面和心不和", "feeling": "笑着，心里记着账",
                            "why": "你当众驳了他"})
    assert "笑着，心里记着账" in s, "TA 对玩家的感觉没进主拍"
    assert "面和心不和" in s


def test_no_read_no_block():
    """没判过就不该平白多一段提示词 (每回合都在花 token)。"""
    assert "心里记着账" not in _sys()
    assert "此刻对TA" not in _sys()


def test_the_feeling_reaches_the_phone_too():
    """线上线下不许对不上: 当面记着账, 短信里就不该突然热络。"""
    from app.engine import qwen
    q = qwen.QwenLLM.__new__(qwen.QwenLLM)
    q._url = q._key = q._model = "x"
    box = {}

    def fake(url, key, body, **k):
        box["sys"] = body["messages"][0]["content"]

        class R:
            def json(self):
                return {"choices": [{"message": {"content": '{"msgs":["嗯"]}'}}]}
        return R()

    old = qwen._post_chat
    qwen._post_chat = fake
    try:
        q._phone_reply({"phone_reply": True, "device": "手机", "shape": "normal",
                        "char": {"name": "阿彩", "persona_text": "洗头妹"},
                        "relation": "熟人", "context": {}, "player_name": "蔡妍",
                        "relation_read": {"mode": "面和心不和", "feeling": "笑着，心里记着账"},
                        "text": "在吗"})
    finally:
        qwen._post_chat = old
    assert "记着账" in box.get("sys", "")


# ── ⑤ 判官本身 ──────────────────────────────────────────────────────────────

def test_the_judge_asks_for_all_three_fields():
    """关系/感觉/依据缺一不可 —— 没有依据的判断没法验, 就是空话。"""
    from app.engine import qwen
    q = qwen.QwenLLM.__new__(qwen.QwenLLM)
    q._url = q._key = q._model = q._summary_model = "x"
    box = {}

    def fake(url, key, body, **k):
        box["sys"] = body["messages"][0]["content"]
        box["user"] = body["messages"][1]["content"]

        class R:
            def json(self):
                return {"choices": [{"message": {"content":
                        '{"mode":"面和心不和","feeling":"笑着，心里记着账","why":"你当众驳了他"}'}}]}
        return R()

    old = qwen._post_chat
    qwen._post_chat = fake
    try:
        out = q._relation_read({"relation_read": True, "char": {"name": "阿彩"},
                                "player_name": "蔡妍", "ledger_mode": "friend",
                                "lines": [{"role": "user", "content": "我不是那个意思"},
                                          {"role": "assistant", "content": "算了。"}]})
    finally:
        qwen._post_chat = old
    assert out.get("mode") == "面和心不和" and out.get("feeling") and out.get("why")
    t = box["sys"] + box["user"]
    assert "阿彩" in t and "蔡妍" in t
    assert "我不是那个意思" in t, "没把最近的对话喂给判官, 那还叫什么结合上下文"


def test_the_judge_degrades_quietly():
    """判不出来不许炸 —— 关系读不到只是这一拍没更新, 不能拖垮回合。"""
    from app.engine import qwen
    q = qwen.QwenLLM.__new__(qwen.QwenLLM)
    q._url = q._key = q._model = q._summary_model = "x"

    def boom(*a, **k):
        raise RuntimeError("网络炸了")

    old = qwen._post_chat
    qwen._post_chat = boom
    try:
        assert q._relation_read({"relation_read": True, "char": {"name": "阿彩"},
                                 "player_name": "蔡妍", "lines": []}) == {}
    finally:
        qwen._post_chat = old
