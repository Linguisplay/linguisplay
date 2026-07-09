# -*- coding: utf-8 -*-
"""🦇 猎手系统: the story-declared stalker is a LEDGER, not a vibe — deterministic
noise classification, graph-walked patrol/stalk, program-enforced strike ladder
(请回→打伤→濒死→死), and the 🚪 authored dooms (someone is taken on the appointed
night unless the player earned the prevention)."""
from app.engine import runtime, threat


def _story(extra_story=None, dooms=None):
    st = {
        "id": "hx",
        "characters": [
            {"id": "c1", "name": "Mara", "is_lead": True, "persona_text": "a"},
            {"id": "h1", "name": "巡夜人", "persona_text": "b"},
        ],
        "acts": [{"index": 1, "title": "一"}],
        "locations": [
            {"id": "lA", "name": "病房", "detail": "一间病房", "exits": ["走廊"]},
            {"id": "lB", "name": "走廊", "detail": "长走廊", "exits": ["病房", "井口"]},
            {"id": "lC", "name": "井口", "detail": "检修井", "exits": ["走廊"]},
        ],
        "threat": {"char_id": "h1", "patrol": ["lB"], "senses": ["sound", "light"],
                   "cannot_enter": ["lC"], "return_to": "lB",
                   "ladder": ["return", "hurt", "dying"]},
    }
    st.update(extra_story or {})
    if dooms is not None:
        st["dooms"] = dooms
    return {"story": st, "secrets": []}


def _st(loc="lA"):
    return {**runtime.default_state(), "location_id": loc}


def _play(content, state, text, channel="do"):
    return runtime.run_turn(content, state, {"name": "我"}, text, channel=channel)


# ── pure pieces ──────────────────────────────────────────────────────────────────
def test_cfg_validates_or_disables():
    assert threat.cfg({"story": {}}) is None
    assert threat.cfg({"story": {"threat": {"char_id": "x", "patrol": ["nowhere"]},
                                 "locations": []}}) is None
    c = threat.cfg(_story())
    assert c and c["patrol"] == ["lB"] and c["cannot_enter"] == {"lC"}


def test_noise_is_learnable():
    assert threat.noise_of("我悄悄挪到门边", "do") == 0            # quiet words hush a do
    assert threat.noise_of("我一脚踹开柜门", "do", action_cls="破闯") == 3
    assert threat.noise_of("你们都听我说", "say") == 1
    assert threat.noise_of("我压低声音说：别动", "say") == 0
    assert threat.noise_of("我大喊救命", "say") == 3
    assert threat.noise_of("打开手电照向走廊尽头", "do") == 3       # light IS a sense
    assert threat.noise_of("打开手电照向走廊尽头", "do", senses=["sound"]) == 1
    assert threat.noise_of("我看看四周", "do", dice_outcome="crit_fail") == 2  # botch clatters


def test_graph_walk_stops_at_the_mouth():
    adj = threat.neighbors(_story())
    assert adj["lA"] == {"lB"} and adj["lB"] == {"lA", "lC"}
    assert threat.step_toward(adj, "lB", "lA", set()) == "lA"
    # player hides in the squeeze-space → the hunter waits at the mouth, never enters
    assert threat.step_toward(adj, "lA", "lC", {"lC"}) == "lB"
    assert threat.band_of(adj, "lB", "lC") == "near"


# ── the strike ladder, program-enforced ──────────────────────────────────────────
def test_loud_turns_summon_and_the_ladder_costs(monkeypatch):
    monkeypatch.setattr(runtime._rng, "randint", lambda a, b: 3)  # every roll fails
    content = _story()
    st = _st("lA")
    o1 = _play(content, st, "我抡起椅子砸向铁门")   # noise 3 → alert 2 → he comes → caught
    th = o1["state"]["threat"]
    assert th["strikes"] == 1
    assert o1["state"]["location_id"] == "lB"      # strike 1 = 请回 return_to
    assert o1["state"].get("player_hp", "healthy") == "healthy"
    o2 = _play(content, o1["state"], "我大喊着砸门")
    assert o2["state"]["threat"]["strikes"] == 2
    assert o2["state"]["player_hp"] == "hurt"      # strike 2 hurts for real
    assert any(m.get("kind") == "player_hp" for m in o2.get("moments") or [])
    o3 = _play(content, o2["state"], "我继续砸")
    assert o3["state"]["player_hp"] == "dying"     # strike 3: one breath left
    o4 = _play(content, o3["state"], "我还要砸")
    assert o4["state"]["player_hp"] == "dead"      # a dying body has nothing left to pay


def test_quiet_player_decays_alert_and_is_passed_over(monkeypatch):
    monkeypatch.setattr(runtime._rng, "randint", lambda a, b: 10)
    content = _story()
    st = _st("lB")           # standing ON his patrol stop, silent
    o = _play(content, st, "我屏住呼吸，悄悄贴住墙角")
    th = o["state"]["threat"]
    assert th["strikes"] == 0 and o["state"].get("player_hp", "healthy") == "healthy"
    assert th["alert"] == 0  # silence starves the alert


def test_hiding_roll_can_save_you(monkeypatch):
    monkeypatch.setattr(runtime._rng, "randint", lambda a, b: 20)  # nat 20 → slips away
    content = _story()
    st = _st("lA")
    o = _play(content, st, "我砸开药柜")
    th = o["state"]["threat"]
    assert th["strikes"] == 0 and o["state"].get("player_hp", "healthy") == "healthy"
    assert th["alert"] <= 1   # it moved on


def test_threat_view_rides_the_final_payload(monkeypatch):
    monkeypatch.setattr(runtime._rng, "randint", lambda a, b: 10)
    content = _story()
    o = _play(content, _st("lA"), "我环顾四周", channel="think")
    tv = o.get("threat_view")
    assert tv and tv["name"] == "巡夜人" and tv["band"] in ("here", "near", "far")
    assert runtime.threat_view_of(content, o["state"]) == tv


def test_no_threat_config_is_a_full_noop():
    content = {"story": {"id": "p", "characters": [{"id": "c1", "name": "M", "is_lead": True}],
                         "acts": [{"index": 1}], "locations": []}, "secrets": []}
    o = _play(content, runtime.default_state(), "我砸门")
    assert "threat" not in o["state"] and o.get("threat_view") is None


# ── 🚪 预定命运 ──────────────────────────────────────────────────────────────────
DOOM = [{"id": "d1", "day": 2, "char_id": "h1", "to": "lC",
         "text": "他不见了。", "warn_text": "就是今夜。",
         "prevent": {"fragment_ids": [], "closeness_min": 10}}]


def _doom_story():
    # the doomed char must NOT be the hunter for a clean test — use a 3rd character
    s = _story(dooms=[{**DOOM[0], "char_id": "c2"}])
    s["story"]["characters"].append({"id": "c2", "name": "阿花", "persona_text": "c",
                                     "home_location_id": "lB"})
    s["story"].pop("threat")   # isolate the doom mechanics
    return s


def test_doom_fires_on_the_appointed_night():
    content = _doom_story()
    st = _st("lA")
    st["clock"] = {"day": 3, "slot": 0, "turns_in_slot": 0}   # slept past day 2
    o = _play(content, st, "我看看走廊", channel="say")
    assert "d1" in (o["state"].get("dooms_fired") or [])
    assert (o["state"].get("taken") or {}).get("c2") == "lC"
    assert any(m.get("kind") == "doom" and m.get("status") == "taken"
               for m in o.get("moments") or [])
    # position override: she is WHERE she was taken to, findable
    c2 = next(c for c in content["story"]["characters"] if c["id"] == "c2")
    assert runtime.char_position(content, o["state"], c2) == "lC"


def test_doom_prevented_by_trust():
    content = _doom_story()
    st = _st("lA")
    st["clock"] = {"day": 3, "slot": 0, "turns_in_slot": 0}
    st["rel"] = {"c2": {"closeness": 20, "romance": 0}}
    o = _play(content, st, "我看看走廊", channel="say")
    assert "d1" in (o["state"].get("dooms_fired") or [])
    assert "c2" not in (o["state"].get("taken") or {})
    assert any(m.get("kind") == "doom" and m.get("status") == "averted"
               for m in o.get("moments") or [])


def test_doom_waits_while_you_are_with_them():
    content = _doom_story()
    st = _st("lB")   # the player is standing WITH 阿花 tonight
    st["clock"] = {"day": 3, "slot": 0, "turns_in_slot": 0}
    o = _play(content, st, "我陪着她", channel="say")
    assert "d1" not in (o["state"].get("dooms_fired") or [])
    assert "c2" not in (o["state"].get("taken") or {})

