# -*- coding: utf-8 -*-
"""恐怖主题包三件套: 🧠 sanity ledger (CoC-SAN 蓝本) + 🎬 pacing director
(menace waves, Alien-Isolation 蓝本) + 📜 house rules (规则怪谈, program-enforced).
All story-agnostic: everything activates off authored story config only."""
from app.engine import runtime, sanity, threat


def _story(patrol=("lB",), cannot=(), player_rules=None, sanity_on=True, hunter=True):
    st = {
        "id": "hh",
        "characters": [{"id": "c1", "name": "Mara", "is_lead": True, "persona_text": "a"},
                       {"id": "h1", "name": "巡夜人", "persona_text": "b"}],
        "acts": [{"index": 1}],
        "locations": [
            {"id": "lA", "name": "病房", "detail": "d", "exits": ["走廊"]},
            {"id": "lB", "name": "走廊", "detail": "d", "exits": ["病房", "井口"]},
            {"id": "lC", "name": "井口", "detail": "d", "exits": ["走廊"]},
        ],
        "threat": {"char_id": "h1", "patrol": list(patrol), "cannot_enter": list(cannot),
                   "return_to": "lB", "unfightable": True},
    }
    if not hunter:
        st.pop("threat")
    if sanity_on:
        st["sanity"] = {"enabled": True, "name": "理智", "start": 100, "regen": 1}
    if player_rules is not None:
        st["rules"] = player_rules
    return {"story": st, "secrets": []}


RULES = [
    {"id": "r1", "text": "不要开手电。",
     "violate": {"keywords": ["开手电"], "channel": ["do"]},
     "consequence": {"sanity": -6, "threat_aggro": True, "text": "灯灭了一格。"}},
    {"id": "r2", "text": "别信广播。"},                        # flavor: no teeth, no fire
    {"id": "r3", "text": "太平间里不要吹口哨。",
     "when": {"location_id": "lC"},
     "violate": {"keywords": ["吹口哨"], "channel": ["do"]},
     "consequence": {"sanity": -4}},
]


def _st(loc="lA"):
    return {**runtime.default_state(), "location_id": loc}


def _play(content, state, text, channel="do"):
    return runtime.run_turn(content, state, {"name": "我"}, text, channel=channel)


def _rig(monkeypatch, roll=10):
    # min(b, roll): d20 rolls `roll`, small ranges hit their ceiling, d100 misses 4%
    monkeypatch.setattr(runtime._rng, "randint", lambda a, b: min(b, roll))


# ── 🧠 sanity pure pieces ─────────────────────────────────────────────────────────
def test_sanity_bands_and_teeth():
    assert sanity.dc_mod(90) == 0 and sanity.dc_mod(50) == 1
    assert sanity.dc_mod(20) == 2 and sanity.dc_mod(5) == 3
    scfg = sanity.cfg(_story())
    assert scfg and scfg["start"] == 100
    assert sanity.anchor(scfg, 90) == ""                 # steady mind, no directive
    assert "不对劲" in sanity.anchor(scfg, 30)           # unreliable narration unlocked
    assert sanity.cfg({"story": {}}) is None


# ── 📜 house rules ────────────────────────────────────────────────────────────────
def test_rule_violation_collects_the_price(monkeypatch):
    _rig(monkeypatch)
    content = _story(player_rules=RULES, patrol=("lA",))   # hunter two doors away
    o = _play(content, _st("lC"), "我打开手电四下照")
    # -6 rule + -1 near-cue: the light ALSO drew it one door closer (systems compose)
    assert o["state"]["sanity"] == 93
    assert o["state"]["threat"]["alert"] == 3             # it heard. it is coming.
    assert any(m.get("kind") == "rule" for m in o.get("moments") or [])
    assert any("灯灭了一格" in (b.get("text") or "") for b in o.get("beats") or [])


def test_rules_respect_scope_and_flavor_stays_inert(monkeypatch):
    _rig(monkeypatch)
    content = _story(player_rules=RULES, hunter=False)
    o = _play(content, _st("lA"), "我吹口哨给自己壮胆")   # r3 is scoped to lC
    assert o["state"]["sanity"] == 100
    assert not any(m.get("kind") == "rule" for m in o.get("moments") or [])
    o2 = _play(content, o["state"], "广播里的声音真怪")   # flavor rule has no teeth
    assert not any(m.get("kind") == "rule" for m in o2.get("moments") or [])


# ── 🧠 losses + recovery through the pipeline ────────────────────────────────────
def test_terrible_knowledge_costs(monkeypatch):
    _rig(monkeypatch)
    content = _story(hunter=False)
    content["secrets"] = [{
        "id": "s1", "character_id": "c1", "title": "黑真相", "sensitivity": "heavy",
        "fragments": [{"id": "f1", "content": "BODY", "retrieval_key": "真相 黑",
                       "known_by_character_ids": ["c1"],
                       "unlock": {"affinity_min": 0, "act_min": 1, "asks_min": 1}}],
    }]
    o = _play(content, _st("lA"), "告诉我 真相", channel="say")
    assert "f1" in o["state"]["unlocked_fragment_ids"]
    assert o["state"]["sanity"] == 95                     # heavy knowledge bites -5


def test_quiet_turn_far_away_breathes_back(monkeypatch):
    _rig(monkeypatch)
    content = _story(patrol=("lA",))
    st = _st("lC")                                        # two doors from its beat
    st["sanity"] = 50
    o = _play(content, st, "我靠着墙喘口气", channel="say")
    assert o["state"]["sanity"] == 51                     # +regen on a no-loss turn


def test_sanity_zero_is_a_terminal_break(monkeypatch):
    _rig(monkeypatch)
    content = _story(player_rules=RULES, hunter=False)
    st = _st("lA")
    st["sanity"] = 4
    o = _play(content, st, "我打开手电四下照")            # -6 → 0
    assert o["state"]["sanity"] == 0
    assert o["state"].get("ended") is True
    assert (o.get("ending") or {}).get("terminal") is True


# ── 🎬 pacing director ────────────────────────────────────────────────────────────
def test_menace_forces_a_backstage_breather(monkeypatch):
    _rig(monkeypatch)
    content = _story(patrol=("lB",), cannot=("lC",))
    st = _st("lC")                                        # hiding at the vent mouth
    for _ in range(8):                                    # near every turn: menace +2
        o = _play(content, st, "我贴着管壁不出声", channel="say")
        st = o["state"]
        if st["threat"].get("away", 0) > 0:
            break
    assert st["threat"]["away"] > 0                       # the director called it off
    assert (o.get("threat_view") or {}).get("band") == "far"


def test_long_comfort_gets_restaged(monkeypatch):
    _rig(monkeypatch)
    content = _story(patrol=("lA",))
    st = _st("lC")                                        # far and cozy
    seen_near = False
    for _ in range(12):
        o = _play(content, st, "我小声整理笔记", channel="say")
        st = o["state"]
        if (o.get("threat_view") or {}).get("band") in ("near", "here"):
            seen_near = True
            break
    assert seen_near                                      # it came drifting back


def test_unfightable_attack_hands_yourself_over(monkeypatch):
    _rig(monkeypatch)
    content = _story(patrol=("lB",))
    st = _st("lB")                                        # same room as its beat
    o = _play(content, st, "我挥拳猛攻巡夜人")
    assert o["state"]["threat"]["strikes"] == 1           # no alert needed — it's a gift
    assert o["state"]["sanity"] <= 94                     # the catch costs the mind too


def test_hide_spot_gets_learned(monkeypatch):
    _rig(monkeypatch, roll=20)                            # always slips away
    content = _story(patrol=("lB",))
    st = _st("lB")
    for _ in range(2):
        o = _play(content, st, "我砸了一下柜子又躲进柜子里")
        st = o["state"]
    assert st["threat"]["hides"].get("柜", 0) >= 2        # it knows that trick now

