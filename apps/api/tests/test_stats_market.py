"""🎯 数值账本 (Yi 2026-07-09): 玩家五维动真骰子、NPC 也有位阶和身家、集市买卖是
真账——money down, item in pocket, one audit line."""

from app.engine import actions, runtime
from app.engine.llm import MockLLM

SANDBOX = {
    "story": {"id": "s",
              "sandbox": {"enabled": True, "currency": "灵币", "start_money": 80,
                          "progression": {"name": "修为", "ranks": ["魂士", "魂师", "魂尊"]}},
              "characters": [{"id": "a", "name": "甲", "is_lead": True,
                              "home_location_id": "hall"}],
              "acts": [{"index": 1, "title": "无尽"}],
              "locations": [{"id": "hall", "name": "校场", "exits": []}]},
    "secrets": [],
}


def test_attrs_move_the_dice_dc():
    st = {**runtime.default_state(), "attrs": {"力量": 9, "敏捷": 5, "体质": 5,
                                               "心思": 1, "气运": 9}}
    strong = actions.classify(SANDBOX, st, "我一拳砸向石锁")      # 强攻→力量9 → -2
    assert strong and strong["dc"] == 8 - 2 - 1                  # 力量-2, 气运高照-1
    weak = actions.classify(SANDBOX, st, "我谎称自己是巡查")      # 欺瞒→心思1 → +2
    assert weak and weak["dc"] == 8 + 2 - 1
    # no attrs minted yet → base DC, no crash
    st0 = runtime.default_state()
    base = actions.classify(SANDBOX, st0, "我一拳砸向石锁")
    assert base and base["dc"] == 8


def test_player_attrs_minted_once_and_exposed():
    st = runtime.default_state()
    got = runtime.ensure_player_attrs(SANDBOX, st, {"name": "我"}, llm=MockLLM())
    assert got == {k: 5 for k in runtime.ATTRS}
    st["attrs"]["力量"] = 9
    again = runtime.ensure_player_attrs(SANDBOX, st, {"name": "我"}, llm=MockLLM())
    assert again["力量"] == 9        # judged once — never re-rolled


def test_npc_gets_a_rank_and_pocket_money():
    st = runtime.default_state()
    char = SANDBOX["story"]["characters"][0]
    e = runtime.ensure_npc_rank(SANDBOX, st, char, MockLLM())
    assert e["rank"] == "魂士"                        # mock: lowest band
    assert st["char_sim"]["a"]["money"] == 80
    line = runtime._own_rank_line(SANDBOX, st, char, MockLLM())
    assert "魂士" in line and "80灵币" in line


def test_contest_signal_patterns():
    assert runtime.contest_signal("开始吧")
    assert runtime.contest_signal("来吧，放马过来")
    assert runtime.contest_signal("那就切磋一场")
    assert not runtime.contest_signal("先别开始，我还没热身")
    assert not runtime.contest_signal("你好")


def test_start_signal_rolls_the_contest_and_briefs_the_director():
    """竞技合同 (Yi): 约好较量、玩家喊开始 → 骰子当场落地（说的通道也触发），
    DC 按位阶差压上去，判定必须进导演提示词——不许再摆三拍架势。"""

    class SpyLLM:
        def __init__(self):
            self.prompts = []

        def generate(self, prompt):
            if prompt.get("rank_judge"):
                return {"rank_i": 2, "money": 10}       # 对手=魂尊(第3档) vs 玩家魂士
            if prompt.get("gen_attrs"):
                return {"attrs": {k: 5 for k in runtime.ATTRS}}
            if prompt.get("summarize"):
                return {"memory": ""}
            if prompt.get("suggest"):
                return {"suggestions": []}
            if prompt.get("speaker_name"):
                self.prompts.append(prompt)
            return {"beats": [{"type": "dialogue", "speaker_name": "甲", "text": "承让。"}],
                    "affinity_delta": 0, "advance_act": False, "ending": None}

    llm = SpyLLM()
    st = {**runtime.default_state(), "location_id": "hall"}
    out = runtime.run_turn(SANDBOX, st, {"name": "我"}, "开始吧", channel="say", llm=llm)
    d = out["dice"]
    assert d and d.get("contest") == "甲"
    assert d["dc"] == 8 + 2 * 2          # 位阶差+2档 → DC 12（五维全5无增减）
    assert llm.prompts[0].get("check") == d   # the verdict reaches the director
    # a plain line never rolls a contest
    out2 = runtime.run_turn(SANDBOX, {**runtime.default_state(), "location_id": "hall"},
                            {"name": "我"}, "今天天气不错", channel="say", llm=SpyLLM())
    assert out2["dice"] is None


def test_market_buys_are_ledger_ops():
    st = {**runtime.default_state(), "money": 30}
    view = runtime.market_view(SANDBOX, st, llm=MockLLM())
    assert view["currency"] == "灵币" and len(view["items"]) == 3
    cheap = next(i for i in view["items"] if i["name"] == "热汤面")
    out = runtime.market_buy(SANDBOX, st, cheap["id"], llm=MockLLM())
    assert out["money"] == 27 and out["bought"] == "热汤面"
    assert any(i.get("name") == "热汤面" for i in st["inventory"])
    # broke player hits a readable wall, not a crash
    st["money"] = 1
    pricey = next(i for i in view["items"] if i["price"] > 1)
    try:
        runtime.market_buy(SANDBOX, st, pricey["id"], llm=MockLLM())
        raise AssertionError("should have raised")
    except ValueError as e:
        assert "钱不够" in str(e)
    # same-day view is cached; a new day restocks
    st["clock"] = {"day": 2, "slot": 0}
    v2 = runtime.market_view(SANDBOX, st, llm=MockLLM())
    assert v2["day"] == 2 and all(i["id"].startswith("mk2_") for i in v2["items"])
