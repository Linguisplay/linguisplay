"""People never just pop in/out of the cast bar: the hour or a new act moving someone
into/out of the scene gets a concrete narrated line (looks + role / where they went),
and walking into a place pans across everyone present and what they're doing."""

from app.engine import runtime

STORY = {
    "story": {"id": "s", "tuning": {"turns_per_slot": 1},
              "characters": [
                  {"id": "a", "name": "甲", "is_lead": True, "home_location_id": "hall",
                   "role": "店主", "persona_text": "五十上下，围裙上永远沾着面粉。爱哼老歌。"},
                  {"id": "b", "name": "乙", "role": "夜班巡逻",
                   "persona_text": "高个子，制服袖口磨得发亮。",
                   "schedule": [{"from_act": 1, "location_id": "hall", "slots": ["夜"]},
                                {"from_act": 1, "location_id": "alley", "slots": ["晨", "午"]}]},
                  {"id": "c", "name": "丙", "appears_from_act": 2, "home_location_id": "hall",
                   "role": "远房侄子", "persona_text": "背一只旧帆布包，眼神躲闪。"},
              ],
              "acts": [{"index": 1, "title": "一"}, {"index": 2, "title": "二"}],
              "locations": [{"id": "hall", "name": "门厅", "detail": "一盏吊灯照着积灰的柜台",
                             "exits": ["后巷"]},
                            {"id": "alley", "name": "后巷", "detail": "潮湿", "exits": ["门厅"]}]},
    "secrets": [],
}


class PlainLLM:
    def __init__(self, **fields):
        self.fields = fields
        self.prompts = []

    def generate(self, prompt):
        if prompt.get("arrive"):
            self.prompts.append(prompt)
            return self.fields.get("arrive_out", {})
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


def test_hour_change_narrates_who_comes_and_goes():
    st = runtime.default_state()
    st["location_id"] = "hall"
    st["clock"] = {"day": 1, "slot": 1, "turns_in_slot": 0}   # 午: 乙 is off in the alley
    # this turn rolls 午→夜 → 乙's shift brings him INTO the hall
    out = runtime.run_turn(STORY, st, {"name": "我"}, "聊聊", channel="say",
                           llm=PlainLLM(next_speakers=[]))
    texts = [b.get("text", "") for b in out["beats"]]
    arrival = next(t for t in texts if "乙来了" in t)
    assert "夜班巡逻" in arrival and "制服袖口" in arrival and "夜色里" in arrival
    # …and the next roll (夜→次日晨) narrates him leaving, with where he's headed
    out2 = runtime.run_turn(STORY, out["state"], {"name": "我"}, "再聊", channel="say",
                            llm=PlainLLM(next_speakers=[]))
    gone = next(t for t in (b.get("text", "") for b in out2["beats"]) if "乙已经离开" in t)
    assert "后巷" in gone


def test_act_entrance_and_death_makes_no_exit_line():
    st = runtime.default_state()
    st["location_id"] = "hall"
    st["turns_in_act"] = 99
    llm = PlainLLM(advance_act=True, next_speakers=[])
    out = runtime.run_turn(STORY, st, {"name": "我"}, "往下走吧", channel="say", llm=llm)
    assert out["state"]["act"] == 2
    entrance = next(t for t in (b.get("text", "") for b in out["beats"]) if "丙来了" in t)
    assert "远房侄子" in entrance and "帆布包" in entrance
    # a death this turn is mourned by the death machinery — never "他已经离开了"
    st2 = out["state"]
    out3 = runtime.run_turn(STORY, st2, {"name": "我"}, "动手", channel="say",
                            llm=PlainLLM(died="丙", next_speakers=[]))
    assert not any("丙已经离开" in (b.get("text") or "") for b in out3["beats"])


def test_arrival_narration_llm_and_fallback():
    st = runtime.default_state()
    st["location_id"] = "hall"
    st["clock"] = {"day": 1, "slot": 2, "turns_in_slot": 0}   # 夜: 甲+乙 both in the hall
    llm = PlainLLM(arrive_out={"beats": [{"type": "description", "speaker_name": None,
                                          "text": "吊灯昏黄，甲正擦着柜台哼歌，乙靠在门边抬起了头。"}]})
    txt = runtime.arrival_narration(STORY, st, {"name": "我"}, llm=llm)
    assert "乙靠在门边" in txt
    # the model was fed the scene: place detail + each person's look/role/relation
    ctx = llm.prompts[0]
    assert ctx["place"] == "门厅" and "吊灯" in ctx["detail"]
    names = {p["name"] for p in ctx["people"]}
    assert names == {"甲", "乙"} and all(p["relation"] for p in ctx["people"])
    # mock path (no prose) → deterministic pan still names everyone with a concrete stroke
    txt2 = runtime.arrival_narration(STORY, st, {"name": "我"}, llm=PlainLLM())
    assert "甲正在这里——店主" in txt2 and "乙" in txt2 and "吊灯" in txt2
