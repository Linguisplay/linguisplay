"""🏖 无尽沙盒: real-world time IS story time (turns spend nothing, skips refused);
the sandbox never ends (a declared death becomes a body state); the player's own body
breaks on the same two-stage ladder — and the dead lose 说/做, keeping only the watch."""

from datetime import datetime, timedelta, timezone

import pytest

from app.engine import logic, runtime

TZ = timezone(timedelta(hours=8))

STORY = {
    "story": {"id": "s", "sandbox": {"enabled": True, "real_time": True},
              "characters": [{"id": "a", "name": "甲", "is_lead": True}],
              "acts": [{"index": 1, "title": "无尽"}],
              "locations": [{"id": "hall", "name": "门厅", "detail": "x", "exits": []}]},
    "secrets": [],
}


class SandLLM:
    def __init__(self, **fields):
        self.fields = fields
        self.prompts = []

    def generate(self, prompt):
        if prompt.get("risk_judge"):
            return {"risk": 100}
        if prompt.get("intro") or prompt.get("observe") or prompt.get("suggest") \
                or prompt.get("arrive") or prompt.get("farewell") or prompt.get("offscreen") \
                or prompt.get("opening_hook") or prompt.get("sandbox_cast"):
            self.prompts.append(prompt)
            return {} if not (prompt.get("intro") or prompt.get("observe")) else \
                   {"beats": [{"type": "description", "speaker_name": None, "text": "x"}],
                    "affinity_delta": 0, "advance_act": False, "ending": None}
        self.prompts.append(prompt)
        out = {"beats": [{"type": "dialogue", "speaker_name": prompt.get("speaker_name"), "text": "嗯"}],
               "affinity_delta": 0, "advance_act": False, "ending": None}
        if prompt.get("group_mode") in ("primary", None):
            out.update(self.fields)
        return out


def _at(monkeypatch, y, mo, d, h, mi=0):
    monkeypatch.setattr(runtime, "_now", lambda: datetime(y, mo, d, h, mi, tzinfo=TZ))


def _st():
    st = runtime.default_state()
    st["location_id"] = "hall"
    return st


def test_real_clock_mirrors_the_wall(monkeypatch):
    _at(monkeypatch, 2026, 7, 4, 20, 41)
    out = runtime.run_turn(STORY, _st(), {"name": "我"}, "你好", channel="say",
                           llm=SandLLM(next_speakers=[]))
    clk = out["state"]["clock"]
    assert (clk["day"], clk["slot"]) == (1, 2)               # 20:41 → 夜
    assert "20:41" in out["clock_view"]["label"]
    # turns spend nothing, and real time cannot be slept away
    st = out["state"]
    for _ in range(3):
        st = runtime.run_turn(STORY, st, {"name": "我"}, "聊聊", channel="say",
                              llm=SandLLM(next_speakers=[], time_skip="次日"))["state"]
    assert (st["clock"]["day"], st["clock"]["slot"]) == (1, 2)
    # the real world moved on: the next visit is tomorrow morning — day 2, narrated
    _at(monkeypatch, 2026, 7, 5, 8)
    out2 = runtime.run_turn(STORY, st, {"name": "我"}, "早", channel="say",
                            llm=SandLLM(next_speakers=[]))
    clk2 = out2["state"]["clock"]
    assert (clk2["day"], clk2["slot"]) == (2, 0)
    assert any("晨光" in b.get("text", "") for b in out2["beats"])


def test_player_death_is_two_stage_and_strips_channels(monkeypatch):
    _at(monkeypatch, 2026, 7, 4, 20)
    llm = SandLLM(player_harm="重伤", next_speakers=[])
    out = runtime.run_turn(STORY, _st(), {"name": "我"}, "冲进火场", channel="say", llm=llm)
    st = out["state"]
    assert st["player_hp"] == "dying"                        # a killing blow never kills outright
    assert any(m["kind"] == "player_hp" and m["hp"] == "dying" for m in out["moments"])
    assert next(p for p in llm.prompts if p.get("speaker_name")).get("sandbox") is True             # the scene knows the rules
    out2 = runtime.run_turn(STORY, st, {"name": "我"}, "还想撑住", channel="say",
                            llm=SandLLM(player_harm="致命", next_speakers=[]))
    st = out2["state"]
    assert st["player_hp"] == "dead"
    assert out2["ending"] is None                            # death is a state, not an exit
    assert not st.get("ended")
    # dead: 说 is refused with a notice, the turn falls to watching
    out3 = runtime.run_turn(STORY, st, {"name": "我"}, "救命", channel="say",
                            llm=SandLLM(next_speakers=[]))
    assert any("你已经死了" in b.get("text", "") for b in out3["beats"])
    assert out3["state"]["player_hp"] == "dead"
    # ...and the phone stays silent too
    with pytest.raises(ValueError):
        runtime.phone_send({"story": {**STORY["story"], "phone": {"enabled": True}},
                            "secrets": []}, st, {"name": "我"}, "a", "在吗",
                           llm=SandLLM())


def test_wounds_heal_one_step_at_a_time(monkeypatch):
    _at(monkeypatch, 2026, 7, 4, 9)
    out = runtime.run_turn(STORY, _st(), {"name": "我"}, "翻墙摔了下来", channel="say",
                           llm=SandLLM(player_harm="轻伤", next_speakers=[]))
    assert out["state"]["player_hp"] == "hurt"
    out2 = runtime.run_turn(STORY, out["state"], {"name": "我"}, "处理伤口", channel="say",
                            llm=SandLLM(player_harm="好转", next_speakers=[]))
    assert out2["state"]["player_hp"] == "healthy"
    assert any(m["kind"] == "player_hp" and m["hp"] == "healthy" for m in out2["moments"])


def test_declared_ending_reroutes_to_the_body(monkeypatch):
    _at(monkeypatch, 2026, 7, 4, 9)
    out = runtime.run_turn(STORY, _st(), {"name": "我"}, "跳下去", channel="say",
                           llm=SandLLM(ending={"kind": "death", "title": "x", "text": "y"},
                                       next_speakers=[]))
    assert out["ending"] is None
    assert out["state"]["player_hp"] == "dying"              # rerouted into the ladder


def test_sandbox_cast_is_conjured_with_a_fallback():
    class CastLLM:
        def __init__(self, out):
            self.out = out

        def generate(self, prompt):
            assert prompt.get("sandbox_cast")
            return self.out

    content = {"story": {"id": "s", "sandbox": {"enabled": True}, "characters": [],
                         "world_long": "海边小城"}, "secrets": []}
    runtime.seed_sandbox_cast(content, llm=CastLLM(
        {"characters": [{"name": "阿箬", "role": "药铺学徒", "persona": "细声细气",
                         "items": ["药杵|磨得发亮", {"name": "碎银"}, "多余的|x"]},
                        {"name": "阿箬"},                    # dupe dropped
                        {"name": "老宋", "role": "码头管事"}]}))
    chars = content["story"]["characters"]
    assert [c["name"] for c in chars] == ["阿箬", "老宋"]
    assert chars[0]["is_lead"] and not chars[1]["is_lead"]
    assert all(c["generated"] for c in chars)
    # 🎒 conjured people carry real, normalized things (capped at 2)
    assert chars[0]["items"] == [{"name": "药杵", "detail": "磨得发亮"},
                                 {"name": "碎银", "detail": ""}]
    assert runtime.char_items(content, runtime.default_state(), chars[0]["id"])[0]["name"] == "药杵"
    # a silent model still leaves someone to meet
    content2 = {"story": {"id": "s", "sandbox": {"enabled": True}, "characters": []},
                "secrets": []}
    runtime.seed_sandbox_cast(content2, llm=CastLLM({}))
    assert len(content2["story"]["characters"]) == 1
    assert content2["story"]["characters"][0]["is_lead"]


def test_start_locations_are_unique_per_run(map_writes_on):
    # each mapless run gets its OWN start place id, so its AI background never
    # collides with another world's
    class PlaceLLM:
        def generate(self, prompt):
            assert prompt.get("start_place")
            return {"name": "码头", "detail": "潮气很重"}

    ids = set()
    for _ in range(2):
        content = {"story": {"id": "s", "characters": [], "acts": [{"index": 1}],
                             "locations": []}, "secrets": []}
        st = runtime.default_state()
        loc = runtime.ensure_start_location(content, st, llm=PlaceLLM())
        assert loc["generated"] and st["location_id"] == loc["id"]
        ids.add(loc["id"])
    assert len(ids) == 2


def test_god_mode_arrival_is_an_unseen_viewpoint():
    content = {"story": {"id": "s",
                         "characters": [{"id": "a", "name": "甲", "is_lead": True}],
                         "acts": [{"index": 1, "title": "一"}],
                         "locations": [{"id": "L", "name": "堂屋", "detail": "x",
                                        "exits": []}]},
               "secrets": []}

    class Spy:
        def __init__(self):
            self.p = None

        def generate(self, prompt):
            self.p = prompt
            return {}

    st = runtime.default_state()
    st["mode"] = "god"
    st["location_id"] = "L"
    spy = Spy()
    runtime.arrival_narration(content, st, {"name": "我"}, llm=spy)
    assert spy.p and spy.p.get("arrive") and spy.p.get("observer") is True


def test_mature_playbook_carries_craft_and_arc():
    from app.engine import relationships
    # every stage on a mature run gets the arc-pacing line (except enemies)
    assert "感情线的节奏" in relationships.playbook_block("friend", mature=True)
    assert "感情线的节奏" in relationships.playbook_block("stranger", mature=True)
    assert "感情线的节奏" not in relationships.playbook_block("enemy", mature=True)
    # flirting gets technique, intimacy gets pacing; none of it leaks into SFW runs
    assert "调情手艺" in relationships.playbook_block("flirt", mature=True)
    assert "亲密手艺" in relationships.playbook_block("lover", mature=True)
    for mode in ("stranger", "friend", "flirt", "lover"):
        assert "成人向" not in relationships.playbook_block(mode, mature=False)


def test_linter_warns_on_ignored_machinery():
    content = {"story": {"id": "s", "sandbox": {"enabled": True},
                         "characters": [{"id": "a", "name": "甲"}],
                         "acts": [{"index": 1, "title": "一"}, {"index": 2, "title": "二"}],
                         "locations": [],
                         "endings": [{"id": "e1", "kind": "bad", "title": "x", "text": "y"}],
                         "verdict": {"options": [{"id": "v1", "label": "x", "correct": True},
                                                 {"id": "v2", "label": "y"}]},
                         "clock": {"deadline_day": 3}},
               "secrets": []}
    codes = {i["code"] for i in logic.lint_story(content)}
    assert {"sandbox_endings", "sandbox_verdict", "sandbox_deadline", "sandbox_acts"} <= codes
