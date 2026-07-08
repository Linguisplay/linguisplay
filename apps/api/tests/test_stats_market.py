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
