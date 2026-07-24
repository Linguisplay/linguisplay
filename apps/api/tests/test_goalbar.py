# 🎯 目标栏执法点: 账本裁剪家法 — open 条目永不静默消失 (实弹: 玩家自立目标
# 被 8 条差事历史冲掉, 无 audit 无痕; 任务账本同款)
from app.engine import runtime


def test_goal_trim_never_drops_open_self_goal():
    state: dict = {}
    runtime.goal_push(state, "self", "查清阿婆的身世", src="player")
    for i in range(10):
        runtime.goal_push(state, "errand", f"替人跑腿第{i}趟", src="npc")
    gs = state["goals"]
    assert len(gs) <= 9  # cap 之上只容忍 open 溢出
    opens = [g for g in gs if g["status"] == "open"]
    assert any(g["kind"] == "self" and g["text"] == "查清阿婆的身世" for g in opens), \
        "自立目标被历史条目静默冲掉了"
    # errand 层只留最新一条 open
    assert sum(1 for g in opens if g["kind"] == "errand") == 1
    # errand 结掉后, 目标条回落到 self 层
    runtime.goal_settle(state, "errand", "done")
    assert runtime.goal_top({}, state) == "查清阿婆的身世"


def test_trim_ledger_keeps_open_quests():
    rows = [{"title": "最早接的活", "status": "open"}] + \
           [{"title": f"完结{i}", "status": "done"} for i in range(8)]
    out = runtime._trim_ledger(rows, cap=8)
    assert {"title": "最早接的活", "status": "open"} in out
    assert len(out) == 8
    # 被裁的是最老的历史, 不是 open
    assert out[0]["status"] == "open" and out[1]["title"] == "完结1"


def test_player_goal_beats_errand_then_falls_back():
    state: dict = {}
    runtime.goal_push(state, "errand", "替人跑腿", src="npc")
    got = runtime.player_goal_set({}, state, "在城寨开一间自己的铺子")
    assert got == "在城寨开一间自己的铺子" == state["goal"]  # player 层压过差事
    runtime.player_goal_set({}, state, "")  # 留空 = 撤下, 回落差事层
    assert state["goal"] == "替人跑腿"


def test_player_goal_suggest_is_worldly_and_capped():
    content = {"story": {"locations": [{"id": "l1", "name": "龙记理发店"}],
                         "characters": []}}
    state: dict = {"location_id": "l0"}
    for _ in range(6):
        t = runtime.player_goal_suggest(content, state)
        assert t and len(t) <= 40
