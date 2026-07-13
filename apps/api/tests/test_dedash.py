"""The punctuation guard: em-dashes in GENERATED text are rewritten in code (the style
instruction alone doesn't hold). Mid-sentence runs become commas, runs glued to existing
punctuation vanish, and only the dramatic cut-off (end of line / before a closing quote)
survives. Applied at every output choke point, so no provider can leak them."""

from app.engine import runtime


def test_dedash_rules():
    d = runtime.dedash
    # mid-sentence run → comma
    assert d("他站起身——把剃刀搁下——走到门口") == "他站起身，把剃刀搁下，走到门口"
    # glued to punctuation → dropped, no doubling
    assert d("他愣住了。——那不可能。") == "他愣住了。那不可能。"
    assert d("「进来吧——，别站着」") == "「进来吧，别站着」"
    # leading run → dropped
    assert d("——第二天清晨") == "第二天清晨"
    # dramatic cut-off survives: end of string / before a closing quote
    assert d("你别——") == "你别——"
    assert d("「你听我说——」他被打断了") == "「你听我说——」他被打断了"
    # single-char dash runs treated the same; clean text passes untouched
    assert d("他看了你一眼—没说话") == "他看了你一眼，没说话"
    assert d("平常的一句话。") == "平常的一句话。"
    assert d("") == ""


def test_dedash_guards_the_turn_pipeline():
    story = {"story": {"id": "s", "characters": [{"id": "a", "name": "甲", "is_lead": True}],
                       "acts": [{"index": 1, "title": "一"}],
                       "locations": [{"id": "hall", "name": "门厅", "detail": "x", "exits": []}]},
             "secrets": []}

    class DashLLM:
        def generate(self, prompt):
            if prompt.get("risk_judge"):
                return {"risk": 100}
            if prompt.get("suggest"):
                return {"suggestions": ["去问问他——那件事"]}
            return {"beats": [
                {"type": "description", "speaker_name": None, "text": "灯闪了一下——熄了。"},
                {"type": "dialogue", "speaker_name": "甲", "text": "你——你怎么进来的——说！"},
            ], "affinity_delta": 0, "advance_act": False, "ending": None}

    out = runtime.run_turn(story, runtime.default_state(), {"name": "我"}, "你好",
                           channel="say", llm=DashLLM())
    texts = [b.get("text", "") for b in out["beats"]]
    assert "灯闪了一下，熄了。" in texts
    assert "你，你怎么进来的，说！" in texts
    assert all("——" not in t for t in texts)
    # dedashed chip leads; the row is ALWAYS topped up to exactly 2 (Yi 定)
    assert out["suggestions"][0] == "去问问他，那件事"
    assert len(out["suggestions"]) == 2
