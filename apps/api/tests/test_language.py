"""🌐 story.language ("en"): the engine performs in English — every prompt carries the
language stamp (lang_llm wrapper), and the engine's own deterministic narration
(act divider / search lines / slot turns…) speaks the story's language. zh default
stays byte-identical (the whole existing suite is the regression net for that)."""

from app.engine import runtime


STORY_EN = {
    "story": {"id": "s", "language": "en",
              "tuning": {"min_turns_per_act": 0, "turns_per_slot": 0},
              "characters": [{"id": "a", "name": "Mara", "is_lead": True}],
              "acts": [{"index": 1, "title": "One"}, {"index": 2, "title": "Two"}],
              "locations": [{"id": "l1", "name": "hall", "detail": "a desk", "exits": [],
                             "props": [{"name": "desk", "detail": "a locked drawer"}]}]},
    "secrets": [],
}


class SpyLLM:
    def __init__(self, advance=False):
        self.prompts = []
        self.advance = advance

    def generate(self, prompt):
        self.prompts.append(prompt)
        if prompt.get("suggest") or prompt.get("arrive") or prompt.get("offscreen") \
                or prompt.get("farewell") or prompt.get("summarize") \
                or prompt.get("golden_moment"):
            return {}
        if prompt.get("risk_judge"):
            return {"risk": 100}
        return {"beats": [{"type": "dialogue", "speaker_name": prompt.get("speaker_name"),
                           "text": "Hm."}],
                "affinity_delta": 0, "advance_act": self.advance, "ending": None,
                "next_speakers": []}


def test_lang_helpers():
    assert runtime.lang_of(STORY_EN) == "en"
    assert runtime.lang_of({"story": {}}) == "zh"
    assert runtime._t(STORY_EN, "中", "EN") == "EN"
    assert runtime._t({"story": {}}, "中", "EN") == "中"


def test_every_prompt_carries_the_language_stamp():
    llm = SpyLLM()
    runtime.run_turn(STORY_EN, runtime.default_state(), {"name": "me"}, "hello",
                     channel="say", llm=llm)
    assert llm.prompts, "no prompts made"
    assert all(p.get("language") == "en" for p in llm.prompts)
    # zh story → no stamp injected (wrapper is a no-op)
    llm2 = SpyLLM()
    zh = {"story": {**STORY_EN["story"], "language": "zh"}, "secrets": []}
    runtime.run_turn(zh, runtime.default_state(), {"name": "me"}, "你好",
                     channel="say", llm=llm2)
    assert all("language" not in p for p in llm2.prompts)


def test_deterministic_narration_speaks_english():
    llm = SpyLLM(advance=True)
    out = runtime.run_turn(STORY_EN, runtime.default_state(), {"name": "me"},
                           "let's move on", channel="say", llm=llm)
    texts = [b.get("text", "") for b in out["beats"]]
    assert any("✦ Act 2 · Two ✦" in t for t in texts)          # divider localized
    # prop search line localized (做-channel, names the prop)
    out2 = runtime.run_turn(STORY_EN, runtime.default_state(), {"name": "me"},
                            "I search the desk", channel="do", llm=SpyLLM())
    assert any("(You search the desk" in b.get("text", "") for b in out2["beats"])
    # the same story in zh keeps the Chinese divider
    zh = {"story": {**STORY_EN["story"], "language": "zh"}, "secrets": []}
    out3 = runtime.run_turn(zh, runtime.default_state(), {"name": "me"},
                            "继续", channel="say", llm=SpyLLM(advance=True))
    assert any("✦ 第2幕" in b.get("text", "") for b in out3["beats"])


def test_parting_teaser_localized():
    st = runtime.default_state()
    st["location_id"] = "l1"
    beats = runtime.build_parting_hook(STORY_EN, st, {"name": "me"},
                                       llm=SpyLLM())
    assert any("[Next act] Act 2" in b["text"] for b in beats)
