# -*- coding: utf-8 -*-
"""🚶 同行: 玩家能带 AI 角色一起走。P1 对话答应即自动同行 (文实不分家)；
accept_companion 只挡敌意、必须在场、幂等。"""
from app.engine import runtime


def _story():
    return {"story": {"id": "s", "tuning": {"turns_per_slot": 6},
                      "characters": [
                          {"id": "a", "name": "阿珍", "is_lead": True, "home_location_id": "l1"},
                          {"id": "b", "name": "细辉", "home_location_id": "l1"}],
                      "locations": [{"id": "l1", "name": "巷口", "exits": ["河边"]},
                                    {"id": "l2", "name": "河边", "exits": ["巷口"]}],
                      "acts": [{"index": 1, "title": "一"}]}, "secrets": []}


def test_dialogue_agreement_auto_follows():
    """角色当面答应同去 → 进 following, 玩家一挪步 TA 就跟着到新地点。"""
    content = _story()
    st = {**runtime.default_state(), "location_id": "l1"}

    class Spy:
        def generate(self, prompt):
            return {"beats": [{"type": "dialogue", "speaker_name": "阿珍", "text": "好，我陪你去。"}],
                    "companion_join": "阿珍",
                    "affinity_delta": 0, "advance_act": False, "ending": None}

    out = runtime.run_turn(content, st, {"name": "我"}, "陪我去河边好不好", channel="say", llm=Spy())
    st2 = out["state"]
    assert "a" in (st2.get("following") or [])
    # 挪到河边, 同行的人一起在场
    runtime.apply_move(content, st2, "河边")
    here = {c["id"] for c in runtime.scene_characters(content, st2)}
    assert "a" in here and st2["location_id"] == "l2"


def test_enemy_wont_be_dragged_along():
    content = _story()
    st = {**runtime.default_state(), "location_id": "l1",
          "rel": {"a": {"closeness": -30, "romance": 0}}}   # 亲近 ≤ -15 → 敌意
    # 直接调 accept_companion, 敌意角色不作数
    res = runtime.accept_companion(content, st, "阿珍")
    assert res is None and "a" not in (st.get("following") or [])


def test_absent_character_cannot_join():
    content = _story()
    st = {**runtime.default_state(), "location_id": "l2"}   # 玩家在河边, 阿珍家在巷口
    res = runtime.accept_companion(content, st, "阿珍")
    assert res is None


def test_accept_companion_is_idempotent():
    content = _story()
    st = {**runtime.default_state(), "location_id": "l1", "following": ["a"]}
    res = runtime.accept_companion(content, st, "阿珍")
    assert res is None                                 # 已在同行, 不重复
    assert (st.get("following") or []).count("a") == 1


def test_join_skipped_when_also_leaving():
    """同一回合既『答应同行』又『起身离开』→ 离开赢 (旁白把 TA 写去了别处)。"""
    content = _story()
    st = {**runtime.default_state(), "location_id": "l1"}

    class Spy:
        def generate(self, prompt):
            return {"beats": [{"type": "dialogue", "speaker_name": "阿珍", "text": "我先走了。"}],
                    "companion_join": "阿珍",
                    "npc_moves": [{"who": "阿珍", "to": "河边"}],
                    "affinity_delta": 0, "advance_act": False, "ending": None}

    out = runtime.run_turn(content, st, {"name": "我"}, "一起走吧", channel="say", llm=Spy())
    assert "a" not in (out["state"].get("following") or [])
