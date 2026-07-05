"""台词范例 (mes_example): a character's authored voice lines ride into every prompt
that speaks as them — scene turns, texts, calls, letters — as a compact few-shot
anchor. The most durable 去AI味 lever, now wired end-to-end (card → story → engine)."""

from app.engine import runtime
from app.engine.qwen import _build_system

STORY = {
    "story": {"id": "s", "tuning": {"turns_per_slot": 0},
              "characters": [
                  {"id": "a", "name": "沈砚", "is_lead": True,
                   "eq_style": "关心藏在做的事里",
                   "examples": ["书比人诚实。", "……你上次说到一半的那件事，后来呢。"]}],
              "acts": [{"index": 1, "title": "一"}]},
    "secrets": [],
}


class SpyLLM:
    def __init__(self):
        self.prompts = []

    def generate(self, prompt):
        self.prompts.append(prompt)
        if prompt.get("phone_reply"):
            return {"msgs": ["嗯。"], "closeness": 0, "romance": 0}
        if prompt.get("compose_msg") or prompt.get("compose_letter") \
                or prompt.get("suggest") or prompt.get("summarize") \
                or prompt.get("golden_moment"):
            return {}
        if prompt.get("risk_judge"):
            return {"risk": 100}
        return {"beats": [{"type": "dialogue", "speaker_name": "沈砚", "text": "嗯。"}],
                "affinity_delta": 0, "advance_act": False, "ending": None,
                "next_speakers": []}


def test_examples_reach_scene_and_phone_prompts():
    llm = SpyLLM()
    runtime.run_turn(STORY, runtime.default_state(), {"name": "我"}, "你好",
                     channel="say", llm=llm)
    sp = next(p for p in llm.prompts if p.get("speaker_name") == "沈砚")
    assert sp["examples"] == ["书比人诚实。", "……你上次说到一半的那件事，后来呢。"]
    # texting the same character carries the voice lines in the char payload
    st = runtime.default_state()
    st["met_ids"] = ["a"]
    llm2 = SpyLLM()
    runtime.phone_send(STORY, st, {"name": "我"}, "a", "在吗", llm=llm2)
    ph = next(p for p in llm2.prompts if p.get("phone_reply"))
    assert "书比人诚实。" in (ph["char"].get("examples") or [])


def test_build_system_carries_the_voice_block():
    sys = _build_system({"speaker_name": "沈砚", "speaker_persona": "话少",
                         "channel": "say", "context": {}, "persona": {"name": "我"},
                         "examples": ["书比人诚实。"]})
    assert "台词范例" in sys and "书比人诚实。" in sys
    # no examples → no block (lean prompt stays lean)
    sys2 = _build_system({"speaker_name": "沈砚", "speaker_persona": "话少",
                          "channel": "say", "context": {}, "persona": {"name": "我"}})
    assert "台词范例" not in sys2
