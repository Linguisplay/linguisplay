"""📱 小手机 phase 1 (信息): absent characters REACH OUT for a live reason — a promise
whose hour is next, being stood up, or a lover just parted from — and the player can
text back from anywhere. The gate holds over text; 已读不回 is a valid answer; the
scene remembers the thread. Period stories rename the device (城寨 → 口信)."""

import pytest

from app.engine import runtime

STORY = {
    "story": {"id": "s", "tuning": {"turns_per_slot": 1},
              "phone": {"device": "口信"},
              "characters": [
                  {"id": "a", "name": "甲", "is_lead": True, "home_location_id": "hall"},
                  {"id": "b", "name": "乙", "home_location_id": "alley",
                   "eq_style": "嘴硬心软"},
              ],
              "acts": [{"index": 1, "title": "一"}],
              "locations": [{"id": "hall", "name": "门厅", "detail": "一盏吊灯", "exits": ["后巷"]},
                            {"id": "alley", "name": "后巷", "detail": "潮湿", "exits": ["门厅"]}]},
    "secrets": [
        {"id": "s1", "character_id": "b", "title": "夜里的事",
         "fragments": [{"id": "f1", "content": "SMS_KNOWN", "retrieval_key": "夜",
                        "unlock": {"asks_min": 0}},
                       {"id": "f2", "content": "SMS_LOCKED", "retrieval_key": "更深",
                        "unlock": {"affinity_min": 999}}]},
    ],
}


class PhoneLLM:
    def __init__(self, **fields):
        self.fields = fields
        self.prompts = []

    def generate(self, prompt):
        if prompt.get("compose_msg"):
            self.prompts.append(prompt)
            return self.fields.get("compose_out", {})
        if prompt.get("phone_reply"):
            self.prompts.append(prompt)
            return self.fields.get("reply_out", {"msgs": ["嗯。"], "closeness": 0, "romance": 0})
        if prompt.get("intro") or prompt.get("observe") or prompt.get("suggest") \
                or prompt.get("risk_judge") or prompt.get("arrive"):
            return {"risk": 100} if prompt.get("risk_judge") else \
                   ({} if prompt.get("arrive") else
                    {"beats": [{"type": "description", "speaker_name": None, "text": "x"}],
                     "affinity_delta": 0, "advance_act": False, "ending": None})
        self.prompts.append(prompt)
        out = {"beats": [{"type": "dialogue", "speaker_name": prompt.get("speaker_name"), "text": "嗯"}],
               "affinity_delta": 0, "advance_act": False, "ending": None}
        if prompt.get("group_mode") in ("primary", None):
            out.update(self.fields)
        return out


def _met(st, *ids):
    st["met_ids"] = sorted(set(st.get("met_ids") or []) | set(ids))
    return st


def test_promise_reminder_text_arrives_once():
    st = _met(runtime.default_state(), "b")
    st["location_id"] = "hall"                          # 乙 lives in the alley — absent
    st["promises"] = [{"char_id": "b", "char_name": "乙", "what": "夜里后巷见",
                       "day": 1, "slot": "夜", "location_id": "alley",
                       "romantic": False, "status": "open"}]
    st["clock"] = {"day": 1, "slot": 0, "turns_in_slot": 0}
    # this turn rolls 晨→午; the promise (夜) is now exactly one slot ahead → reminder
    out = runtime.run_turn(STORY, st, {"name": "我"}, "先忙点别的", channel="say",
                           llm=PhoneLLM(next_speakers=[]))
    st = out["state"]
    th = st["phone"]["threads"]["b"]
    assert th["unread"] == 1 and "别忘了" in th["msgs"][0]["text"]
    assert st["promises"][0]["reminded"] is True
    assert any(m["kind"] == "phone" and m["device"] == "口信" for m in out["moments"])
    assert out["phone_unread"] == 1
    # the flag stops a second reminder
    out2 = runtime.run_turn(STORY, st, {"name": "我"}, "嗯", channel="say",
                            llm=PhoneLLM(next_speakers=[]))
    assert len(out2["state"]["phone"]["threads"]["b"]["msgs"]) == 1


def test_stood_up_text_and_afterglow():
    st = _met(runtime.default_state(), "b")
    st["location_id"] = "hall"
    st["promises"] = [{"char_id": "b", "char_name": "乙", "what": "晌午的事",
                       "day": 1, "slot": "午", "location_id": "alley",
                       "romantic": False, "status": "missed"}]
    out = runtime.run_turn(STORY, st, {"name": "我"}, "唉", channel="say",
                           llm=PhoneLLM(next_speakers=[]))
    msgs = out["state"]["phone"]["threads"]["b"]["msgs"]
    assert any("你没来" in m["text"] for m in msgs)
    # afterglow: a lover the player was JUST with, now apart, sends the missing-you note
    st2 = _met(runtime.default_state(), "b")
    st2["location_id"] = "hall"
    st2["rel"] = {"b": {"closeness": 60, "romance": 70}}
    st2["phone"] = {"threads": {}, "seen": {"b": runtime._time_index(st2)}}
    out2 = runtime.run_turn(STORY, st2, {"name": "我"}, "接着走吧", channel="say",
                            llm=PhoneLLM(next_speakers=[]))
    msgs2 = out2["state"]["phone"]["threads"]["b"]["msgs"]
    assert any("想你" in m["text"] for m in msgs2)
    # one note per parting — the auto_idx cap holds next turn
    out3 = runtime.run_turn(STORY, out2["state"], {"name": "我"}, "嗯", channel="say",
                            llm=PhoneLLM(next_speakers=[]))
    assert len(out3["state"]["phone"]["threads"]["b"]["msgs"]) == len(msgs2)


def test_texting_back_gate_holds_and_read_receipt():
    st = _met(runtime.default_state(), "b")
    st["unlocked_fragment_ids"] = ["f1"]
    llm = PhoneLLM(reply_out={"msgs": ["睡不着。", "你呢？"], "closeness": 2, "romance": 1})
    view = runtime.phone_send(STORY, st, {"name": "我"}, "b", "在吗", llm=llm)
    assert view["replied"] is True and view["device"] == "口信"
    assert [m["text"] for m in view["msgs"]] == ["在吗", "睡不着。", "你呢？"]
    assert st["rel"]["b"]["closeness"] > 5 and st["rel"]["b"]["romance"] > 0
    # the reply prompt got ONLY revealed content — the locked layer never rides along
    ctx = llm.prompts[0]["context"]
    assert any("SMS_KNOWN" in r["content"] for r in ctx["reveal"])
    assert "SMS_LOCKED" not in str(llm.prompts[0])
    # 已读不回: empty msgs = read receipt, thread keeps only the player's line
    st2 = _met(runtime.default_state(), "b")
    view2 = runtime.phone_send(STORY, st2, {"name": "我"}, "b", "喂",
                               llm=PhoneLLM(reply_out={"msgs": [], "closeness": -1, "romance": 0}))
    assert view2["replied"] is False and len(view2["msgs"]) == 1


def test_send_validation_and_scene_remembers_thread():
    st = runtime.default_state()
    with pytest.raises(ValueError, match="还不认识"):
        runtime.phone_send(STORY, st, {"name": "我"}, "b", "喂", llm=PhoneLLM())
    st = _met(st, "b")
    st["dead_character_ids"] = ["b"]
    with pytest.raises(ValueError, match="不在人世"):
        runtime.phone_send(STORY, st, {"name": "我"}, "b", "喂", llm=PhoneLLM())
    # the thread tail is injected into that character's next SCENE prompt
    st3 = _met(runtime.default_state(), "a", "b")
    st3["phone"] = {"threads": {"a": {"msgs": [{"from": "me", "text": "老地方等我", "at": ""},
                                               {"from": "them", "text": "好。", "at": ""}],
                                      "unread": 0}}, "seen": {}}
    st3["location_id"] = "hall"
    llm = PhoneLLM(next_speakers=[])
    runtime.run_turn(STORY, st3, {"name": "我"}, "我来了", channel="say", llm=llm)
    scene_prompt = next(p for p in llm.prompts if p.get("speaker_name") == "甲")
    assert "老地方等我" in (scene_prompt.get("sms_tail") or "")


def test_phone_disabled_story():
    off = {"story": {**STORY["story"], "phone": {"enabled": False}}, "secrets": []}
    st = _met(runtime.default_state(), "b")
    with pytest.raises(ValueError, match="没有这种联系方式"):
        runtime.phone_send(off, st, {"name": "我"}, "b", "喂", llm=PhoneLLM())
    assert runtime.phone_deliveries(off, st, set(), PhoneLLM()) == []
