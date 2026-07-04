"""📟 心象仪: the speaker's judged TRUE inner state (may contradict the words) rides on
their last spoken line for the UI gauge. Per-story switchable; absent judgment = no-op."""

from app.engine import runtime

STORY = {
    "story": {"id": "s", "characters": [{"id": "a", "name": "甲", "is_lead": True}],
              "acts": [{"index": 1, "title": "一"}],
              "locations": [{"id": "hall", "name": "门厅", "detail": "x", "exits": []}]},
    "secrets": [],
}


class MoodLLM:
    def __init__(self, mood=None):
        self.mood = mood

    def generate(self, prompt):
        if prompt.get("risk_judge"):
            return {"risk": 100}
        if prompt.get("suggest"):
            return {"suggestions": []}
        out = {"beats": [
            {"type": "description", "speaker_name": None, "text": "他顿了顿。"},
            {"type": "dialogue", "speaker_name": "甲", "text": "没什么好说的。"},
        ], "affinity_delta": 0, "advance_act": False, "ending": None}
        if self.mood is not None:
            out["self_state"] = self.mood
        return out


def test_mood_rides_the_last_spoken_line():
    out = runtime.run_turn(STORY, runtime.default_state(), {"name": "我"}, "你在瞒什么？",
                           channel="say", llm=MoodLLM("强装镇定"))
    dlg = next(b for b in out["beats"] if b.get("type") == "dialogue")
    assert dlg["mood"] == "强装镇定"
    assert all("mood" not in b for b in out["beats"] if b.get("type") == "description")


def test_mood_respects_the_switch_and_absence():
    off = {"story": {**STORY["story"], "tuning": {"mind_reader": 0}}, "secrets": []}
    out = runtime.run_turn(off, runtime.default_state(), {"name": "我"}, "喂",
                           channel="say", llm=MoodLLM("心里发虚"))
    assert all("mood" not in b for b in out["beats"])
    out2 = runtime.run_turn(STORY, runtime.default_state(), {"name": "我"}, "喂",
                            channel="say", llm=MoodLLM(None))
    assert all("mood" not in b for b in out2["beats"])
