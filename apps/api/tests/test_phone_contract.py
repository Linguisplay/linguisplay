"""📱 传讯合同 (Yi, 2026-07-09): the phone is a real comms system with ledger teeth —
contacts are met-people only (no omniscience), a summon pins the character to the
player's place, an errand becomes their standing intent, and texting someone standing
right next to you is a MOMENT they get to react to (never a silent normal reply)."""

from app.engine import runtime

STORY = {
    "story": {"id": "s",
              "characters": [
                  {"id": "a", "name": "甲", "is_lead": True, "home_location_id": "hall"},
                  {"id": "b", "name": "乙", "home_location_id": "alley"},
                  {"id": "c", "name": "丙", "home_location_id": "alley"},
              ],
              "acts": [{"index": 1, "title": "一"}],
              "locations": [{"id": "hall", "name": "门厅", "exits": ["后巷"]},
                            {"id": "alley", "name": "后巷", "exits": ["门厅"]}]},
    "secrets": [],
}


class PhoneSpy:
    def __init__(self, **out):
        self.out = out
        self.prompts = []

    def generate(self, prompt):
        if prompt.get("phone_reply"):
            self.prompts.append(prompt)
            return {"msgs": ["好。"], "closeness": 0, "romance": 0, **self.out}
        return {}


def _st(loc="hall", met=("a", "b", "c")):
    st = runtime.default_state()
    st["location_id"] = loc
    st["met_ids"] = list(met)
    return st


def test_contacts_are_met_people_only():
    st = _st(met=("b",))          # only 乙 has been met
    view = runtime.phone_threads_view(STORY, st)
    ids = [c["char_id"] for c in view["contacts"]]
    assert ids == ["b"]           # 丙 exists in the story but is INVISIBLE here
    assert view["contacts"][0]["has_thread"] is False


def test_summon_pins_the_character_to_the_player():
    llm = PhoneSpy(coming=True)
    st = _st(loc="hall")          # 乙 lives in alley — absent
    view = runtime.phone_send(STORY, st, {"name": "我"}, "b", "过来门厅找我", llm=llm)
    assert view["coming"] is True
    assert st["char_pins"] == {"b": "hall"}       # TA真的会来：行踪已钉
    assert llm.prompts[0].get("same_room") is False


def test_task_becomes_standing_intent():
    llm = PhoneSpy(task="盯着丙的动静")
    st = _st(loc="hall")
    view = runtime.phone_send(STORY, st, {"name": "我"}, "b", "帮我盯着丙", llm=llm)
    assert view["task"] == "盯着丙的动静"
    assert st["char_sim"]["b"]["intent"] == "盯着丙的动静"


def test_same_room_text_is_a_moment_not_a_summon():
    llm = PhoneSpy(coming=True)   # even if the model says coming, presence wins
    st = _st(loc="alley")         # the player walked INTO 乙's alley
    view = runtime.phone_send(STORY, st, {"name": "我"}, "b", "在吗", llm=llm)
    assert llm.prompts[0].get("same_room") is True   # the tease directive fires
    assert view["coming"] is False
    assert not st.get("char_pins")                   # no pin — TA已经在场
