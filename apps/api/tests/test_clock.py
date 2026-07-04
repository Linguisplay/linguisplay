"""⏳ The diegetic clock: turns spend 时段 (晨/午/夜), slots roll into days, characters
keep per-slot 作息 (or go AWAY), the model can declare a time skip, and an authored
deadline hard-ends the story when it slips past."""

from app.engine import logic, runtime


def _story(tuning=None, clock=None, schedule=None, endings=None):
    return {
        "story": {"id": "s",
                  "characters": [
                      {"id": "a", "name": "甲", "is_lead": True},
                      {"id": "b", "name": "乙", "home_location_id": "hall",
                       **({"schedule": schedule} if schedule else {})},
                  ],
                  "acts": [{"index": 1, "title": "一"}],
                  "locations": [{"id": "hall", "name": "门厅", "detail": "一盏吊灯",
                                 "exits": ["后巷"]},
                                {"id": "alley", "name": "后巷", "detail": "潮湿", "exits": ["门厅"]}],
                  **({"tuning": tuning} if tuning else {}),
                  **({"clock": clock} if clock else {}),
                  **({"endings": endings} if endings else {})},
        "secrets": [],
    }


class ClockLLM:
    """Primary can declare a time skip; otherwise a plain one-liner."""

    def __init__(self, **fields):
        self.fields = fields
        self.prompts = []

    def generate(self, prompt):
        if prompt.get("intro") or prompt.get("observe") or prompt.get("suggest") or prompt.get("risk_judge"):
            return {"risk": 100} if prompt.get("risk_judge") else \
                   {"beats": [{"type": "description", "speaker_name": None, "text": "x"}],
                    "affinity_delta": 0, "advance_act": False, "ending": None}
        self.prompts.append(prompt)
        out = {"beats": [{"type": "dialogue", "speaker_name": prompt.get("speaker_name"), "text": "嗯"}],
               "affinity_delta": 0, "advance_act": False, "ending": None}
        if prompt.get("group_mode") in ("primary", None):
            out.update(self.fields)
        return out


def _turns(content, st, n, llm=None):
    for _ in range(n):
        st = runtime.run_turn(content, st, {"name": "我"}, "聊聊",
                              channel="say", llm=llm or ClockLLM())["state"]
    return st


def test_slots_roll_into_days_and_narrate():
    content = _story(tuning={"turns_per_slot": 2})
    st = runtime.default_state()
    st = _turns(content, st, 1)
    assert st["clock"] == {"day": 1, "slot": 0, "turns_in_slot": 1}
    out = runtime.run_turn(content, st, {"name": "我"}, "再聊", channel="say", llm=ClockLLM())
    st = out["state"]
    assert st["clock"]["slot"] == 1 and st["clock"]["turns_in_slot"] == 0
    assert any("日头" in b.get("text", "") for b in out["beats"])   # the hour is announced
    assert out["clock_view"]["label"] == "第1天·午"
    st = _turns(content, st, 4)                                     # 午→夜→次日晨
    assert st["clock"]["day"] == 2 and st["clock"]["slot"] == 0


def test_clock_off_and_think_costs_nothing():
    content = _story(tuning={"turns_per_slot": 0})
    st = _turns(content, runtime.default_state(), 3)
    assert st["clock"]["day"] == 1 and st["clock"]["slot"] == 0
    assert runtime.clock_view(content, st) is None
    # a look-around never spends time even with the clock on
    content2 = _story(tuning={"turns_per_slot": 1})
    out = runtime.run_turn(content2, runtime.default_state(), {"name": "我"}, "看看四周",
                           channel="think", llm=ClockLLM())
    assert out["state"]["clock"]["turns_in_slot"] == 0


def test_prompt_carries_the_hour():
    content = _story(tuning={"turns_per_slot": 4},
                     clock={"deadline_day": 3, "deadline_text": "清寨行动"})
    llm = ClockLLM()
    runtime.run_turn(content, runtime.default_state(), {"name": "我"}, "你好",
                     channel="say", llm=llm)
    ck = llm.prompts[0].get("clock") or ""
    assert "第1天·晨" in ck and "清寨行动" in ck and "还有2天" in ck


def test_time_skip_jumps_to_next_morning():
    content = _story(tuning={"turns_per_slot": 9})
    out = runtime.run_turn(content, runtime.default_state(), {"name": "我"}, "睡一觉",
                           channel="say", llm=ClockLLM(time_skip="次日"))
    clk = out["state"]["clock"]
    assert clk["day"] == 2 and clk["slot"] == 0 and clk["turns_in_slot"] == 0
    out2 = runtime.run_turn(content, out["state"], {"name": "我"}, "等到天黑",
                            channel="say", llm=ClockLLM(time_skip="下一时段"))
    assert out2["state"]["clock"]["slot"] == 1


def test_slot_schedule_moves_characters_and_away():
    # 乙 works the hall by day and only by day — at night, with no covering entry, AWAY
    content = _story(tuning={"turns_per_slot": 1},
                     schedule=[{"from_act": 1, "location_id": "hall", "slots": ["晨", "午"]}])
    st = runtime.default_state()
    st["location_id"] = "hall"
    assert any(c["id"] == "b" for c in runtime.scene_characters(content, st))
    st["clock"] = {"day": 1, "slot": 2, "turns_in_slot": 0}          # 夜
    assert all(c["id"] != "b" for c in runtime.scene_characters(content, st))
    assert runtime.character_profile(content, st, "b")["where"] == "此刻不知去向"
    assert all("乙" not in n.get("chars", []) for n in runtime.map_view(content, st)["nodes"])
    # a night entry takes over (slot-specific beats generic on the same from_act)
    content2 = _story(tuning={"turns_per_slot": 1},
                      schedule=[{"from_act": 1, "location_id": "hall"},
                                {"from_act": 1, "location_id": "alley", "slots": ["夜"]}])
    assert runtime.char_home(content2["story"]["characters"][1], 1, "夜") == "alley"
    assert runtime.char_home(content2["story"]["characters"][1], 1, "午") == "hall"


def test_deadline_warns_then_ends():
    endings = [{"id": "end_late", "kind": "bad", "trigger": "clock",
                "title": "为时已晚", "text": "一切都结束了。"}]
    content = _story(tuning={"turns_per_slot": 9},
                     clock={"deadline_day": 2, "deadline_text": "火并之夜",
                            "deadline_ending_id": "end_late"},
                     endings=endings)
    st = runtime.default_state()
    out = runtime.run_turn(content, st, {"name": "我"}, "睡吧", channel="say",
                           llm=ClockLLM(time_skip="次日"))
    assert any("就在今天" in b.get("text", "") for b in out["beats"])  # crossed INTO the day
    assert not out["state"].get("ended")
    out2 = runtime.run_turn(content, out["state"], {"name": "我"}, "再睡", channel="say",
                            llm=ClockLLM(time_skip="次日"))
    assert out2["ending"] and out2["ending"]["id"] == "end_late" and out2["ending"]["terminal"]
    assert out2["state"]["ended"] is True
    # trigger:"clock" endings never fire from normal condition matching
    assert runtime.evaluate_ending(content, runtime.default_state(), None) is None


def test_act_anchor_snaps_time_forward():
    # 剧本说第二幕发生在第2天夜里 → 进幕时钟就到第2天夜里，并播报时辰
    content = _story(tuning={"turns_per_slot": 9, "min_turns_per_act": 0})
    content["story"]["acts"] = [{"index": 1, "title": "一"},
                                {"index": 2, "title": "二",
                                 "time": {"day": 2, "slot": "夜"}}]
    out = runtime.run_turn(content, runtime.default_state(), {"name": "我"}, "走",
                           channel="say", llm=ClockLLM(advance_act=True))
    assert out["state"]["act"] == 2
    clk = out["state"]["clock"]
    assert (clk["day"], clk["slot"]) == (2, 2)
    assert out["clock_view"]["label"] == "第2天·夜"
    assert any("夜幕" in b.get("text", "") for b in out["beats"])   # the hour is narrated


def test_act_anchor_only_flows_forward():
    # an anchor BEHIND the current day never rewinds; a bare-slot 晨 lands on the NEXT 晨
    content = _story(tuning={"turns_per_slot": 9, "min_turns_per_act": 0})
    content["story"]["acts"] = [{"index": 1, "title": "一"},
                                {"index": 2, "title": "二",
                                 "time": {"day": 1, "slot": "晨"}}]
    st = runtime.default_state()
    st["clock"] = {"day": 3, "slot": 1, "turns_in_slot": 0}          # 第3天·午
    out = runtime.run_turn(content, st, {"name": "我"}, "走", channel="say",
                           llm=ClockLLM(advance_act=True))
    clk = out["state"]["clock"]
    assert (clk["day"], clk["slot"]) == (4, 0)                       # 次日晨, not day 1


def test_opening_aligns_to_act_one_anchor():
    # a night story OPENS at night — and the intro prose is told the hour
    content = _story(tuning={"turns_per_slot": 9})
    content["story"]["acts"] = [{"index": 1, "title": "一", "time": {"slot": "夜"}}]

    class Spy(ClockLLM):
        def generate(self, prompt):
            self.prompts.append(prompt)
            return super().generate(prompt)

    st = runtime.default_state()
    llm = Spy()
    runtime.build_opening(content, st, llm=llm)
    assert st["clock"]["slot"] == 2
    intro = next(p for p in llm.prompts if p.get("intro"))
    assert "第1天·夜" in (intro.get("clock") or "")


def test_linter_flags_bad_act_time():
    content = _story(tuning={"turns_per_slot": 2},
                     clock={"deadline_day": 2, "deadline_text": "大限"})
    content["story"]["acts"] = [
        {"index": 1, "title": "一", "time": {"day": 1, "slot": "黄昏"}},   # no such slot
        {"index": 2, "title": "二", "time": {"day": 2}},
        {"index": 3, "title": "三", "time": {"day": 1}},                   # time rewinds
        {"index": 4, "title": "四", "time": {"day": 3}},                   # past the deadline
    ]
    codes = {i["code"] for i in logic.lint_story(content)}
    assert {"bad_act_time", "act_time_backwards", "act_time_past_deadline"} <= codes
    content2 = _story(tuning={"turns_per_slot": 0})
    content2["story"]["acts"] = [{"index": 1, "title": "一", "time": {"slot": "夜"}}]
    assert "act_time_no_clock" in {i["code"] for i in logic.lint_story(content2)}


def test_linter_flags_bad_slots_and_deadline():
    content = _story(schedule=[{"from_act": 1, "location_id": "hall", "slots": ["半夜"]}],
                     clock={"deadline_day": 2, "deadline_ending_id": "nope"})
    codes = {i["code"] for i in logic.lint_story(content)}
    assert "bad_slot" in codes and "bad_deadline_ending" in codes
    content2 = _story(tuning={"turns_per_slot": 0},
                      schedule=[{"from_act": 1, "location_id": "hall", "slots": ["夜"]}])
    assert "slots_no_clock" in {i["code"] for i in logic.lint_story(content2)}
