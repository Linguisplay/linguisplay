"""🤝 约定: a character sets a FUTURE appointment with the player (place + day + 时段).
Showing up = a dedicated scene + a relationship reward (romance-tier = a date, 心动 too);
standing them up costs the relationship and they voice the grudge exactly once. All of
it hangs off the diegetic clock — clock-off stories never see the machinery."""

from app.engine import runtime

STORY = {
    "story": {"id": "s", "tuning": {"turns_per_slot": 1},
              "characters": [{"id": "a", "name": "甲", "is_lead": True},
                             {"id": "b", "name": "乙"}],
              "acts": [{"index": 1, "title": "一"}],
              "locations": [{"id": "hall", "name": "门厅", "detail": "一盏吊灯", "exits": ["后巷"]},
                            {"id": "alley", "name": "后巷", "detail": "潮湿", "exits": ["门厅"]}]},
    "secrets": [],
}


class PromiseLLM:
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


def test_promise_made_validated_and_announced():
    llm = PromiseLLM(next_speakers=[],
                     promise={"what": "去后巷看样东西", "day_offset": 0, "slot": "夜", "place": "后巷"})
    st = runtime.default_state()
    out = runtime.run_turn(STORY, st, {"name": "我"}, "改天带我去看看？", channel="say", llm=llm)
    st = out["state"]
    pr = st["promises"][0]
    assert (pr["char_id"], pr["day"], pr["slot"], pr["location_id"], pr["status"]) == \
        ("a", 1, "夜", "alley", "open")
    assert pr["romantic"] is False                       # closeness 5 → not a date
    assert any("约定立下了" in b.get("text", "") for b in out["beats"])
    assert any(m["kind"] == "promise" and m["status"] == "made" for m in out["moments"])
    assert out["promises"][0]["when"] == "今天" + "夜"
    # the same character can't stack a second open promise
    out2 = runtime.run_turn(STORY, st, {"name": "我"}, "再约一个",
                            channel="say", llm=PromiseLLM(next_speakers=[],
                            promise={"what": "又一件事", "day_offset": 2, "slot": "午"}))
    assert len([p for p in out2["state"]["promises"] if p["status"] == "open"]) == 1


def test_promise_rejects_past_time_and_clock_off():
    st = runtime.default_state()
    # a time not in the future refuses (day_offset 0, slot 晨 == now)
    assert runtime.make_promise(STORY, st, {"id": "a", "name": "甲"},
                                {"what": "x", "day_offset": 0, "slot": "晨"},
                                runtime.tuning_for(STORY)) is None
    off_story = {"story": {**STORY["story"], "tuning": {"turns_per_slot": 0}}, "secrets": []}
    assert runtime.make_promise(off_story, st, {"id": "a", "name": "甲"},
                                {"what": "x", "day_offset": 1, "slot": "午"},
                                runtime.tuning_for(off_story)) is None


def test_showing_up_is_the_scene_and_the_reward():
    st = runtime.default_state()
    st["promises"] = [{"char_id": "a", "char_name": "甲", "what": "夜里聊聊",
                       "day": 1, "slot": "夜", "location_id": "hall",
                       "romantic": True, "status": "open"}]
    st["clock"] = {"day": 1, "slot": 2, "turns_in_slot": 0}   # 夜, at the hall
    llm = PromiseLLM(next_speakers=[])
    out = runtime.run_turn(STORY, st, {"name": "我"}, "我来了", channel="say", llm=llm)
    st = out["state"]
    assert st["promises"][0]["status"] == "kept"
    # the scene steered to 甲, whose prompt carries the date block
    appo = llm.prompts[0].get("appointment")
    assert appo and appo["romantic"] is True and "夜里聊聊" in appo["what"]
    # showing up pays: closeness AND (romantic) 心动 both move
    assert st["rel"]["a"]["closeness"] > 5 and st["rel"]["a"]["romance"] > 0
    assert any(m["kind"] == "promise" and m["status"] == "kept" for m in out["moments"])
    assert any(e["kind"] == "promise" for e in st["rel_log"]["a"])
    assert out["promises"] == []                              # nothing left hanging


def test_standing_them_up_stings_then_gets_voiced_once():
    st = runtime.default_state()
    st["promises"] = [{"char_id": "a", "char_name": "甲", "what": "晌午来找我",
                       "day": 1, "slot": "午", "location_id": "hall",
                       "romantic": False, "status": "open"}]
    st["clock"] = {"day": 1, "slot": 1, "turns_in_slot": 0}   # 午 right now…
    st["location_id"] = "alley"                               # …but the player is elsewhere
    # wrong place → not kept; the turn ends, time rolls to 夜 → missed
    out = runtime.run_turn(STORY, st, {"name": "我"}, "先不去了", channel="say",
                           llm=PromiseLLM(next_speakers=[]))
    st = out["state"]
    assert st["promises"][0]["status"] == "missed"
    assert st["rel"]["a"]["closeness"] < 5                    # it cost the relationship
    assert any(m["kind"] == "promise" and m["status"] == "missed" for m in out["moments"])
    assert any("过了时辰" in b.get("text", "") for b in out["beats"])
    # next scene with 甲: the grudge is voiced once, then it's history
    st["location_id"] = "hall"
    llm2 = PromiseLLM(next_speakers=[])
    st = runtime.run_turn(STORY, st, {"name": "我"}, "抱歉来晚了", channel="say", llm=llm2)["state"]
    assert llm2.prompts[0].get("broken_promise") == "晌午来找我"
    assert st["promises"][0]["status"] == "missed_noted"
    llm3 = PromiseLLM(next_speakers=[])
    runtime.run_turn(STORY, st, {"name": "我"}, "还生气吗", channel="say", llm=llm3)
    assert not llm3.prompts[0].get("broken_promise")


def test_journal_lists_the_promise_history():
    st = runtime.default_state()
    st["promises"] = [
        {"char_id": "a", "char_name": "甲", "what": "老地方见", "day": 2, "slot": "晨",
         "romantic": True, "status": "open"},
        {"char_id": "b", "char_name": "乙", "what": "赔罪酒", "day": 1, "slot": "午",
         "romantic": False, "status": "missed"},
    ]
    jd = runtime.journal(STORY, st)
    assert [(p["status"], p["what"]) for p in jd["promises"]] == \
        [("open", "老地方见"), ("missed", "赔罪酒")]


def test_unscheduled_char_shows_up_at_promise_hour():
    """🤝 无作息角色的约定 (台账实弹): 到点脚必须在约定地 — 老逻辑TA永远站在默认位,
    没人赴约, 玩家还要吃爽约扣分; 钟点没到/约定已结 都不许提前站桩。"""
    st = runtime.default_state()
    st["location_id"] = "hall"
    char = dict(STORY["story"]["characters"][1])   # 乙: 无作息无 home
    pr = runtime.make_promise(STORY, st, char,
                              {"what": "去后巷看样东西", "day_offset": 0,
                               "slot": "夜", "place": "后巷"},
                              runtime.tuning_for(STORY))
    assert pr and pr["location_id"] == "alley"
    # 还没到钟点: 人在默认位 (门厅), 不提前去后巷站桩
    assert runtime.char_position(STORY, st, char) == "hall"
    # 钟拨到约定时段: 如约而至
    st["clock"] = {"day": 1, "slot": 2, "turns_in_slot": 0}
    assert runtime.char_position(STORY, st, char) == "alley"
    # 赴约结清后不再钉着
    st["promises"][0]["status"] = "kept"
    assert runtime.char_position(STORY, st, char) == "hall"
