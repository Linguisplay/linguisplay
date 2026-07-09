# -*- coding: utf-8 -*-
"""🚷 观察也走合同 (Yi field case): a look-around must not SUMMON an absent character
to answer it — the present-cast ledger is law for the observe channel too. Guard:
absent name + spoken dialogue in the narration → one stern rewrite."""
from app.engine import runtime
from app.engine.llm import MockLLM

STORY = {"story": {
    "id": "ob",
    "characters": [{"id": "c1", "name": "陆七", "is_lead": True, "persona_text": "a",
                    "home_location_id": "lA"}],
    "acts": [{"index": 1}],
    "locations": [
        {"id": "lA", "name": "病房", "detail": "d", "exits": ["走廊"]},
        {"id": "lB", "name": "走廊", "detail": "d", "exits": ["病房"]},
    ]}, "secrets": []}


class SummonLLM(MockLLM):
    """First observe reply illegally stages the absent 陆七 with dialogue; the
    corrected retry behaves."""
    def generate(self, prompt):
        if prompt.get("observe"):
            if not prompt.get("logic_correction"):
                return {"beats": [{"type": "description", "speaker_name": None,
                                   "text": "陆七拧开水龙头洗了把脸，「办公室在负一层，"
                                           "拿好这把钥匙。」他把钥匙推给你。"}],
                        "affinity_delta": 0, "advance_act": False, "ending": None}
            return {"beats": [{"type": "description", "speaker_name": None,
                               "text": "走廊尽头的应急灯闪了一下。这里没有别人，"
                                       "只有你自己的呼吸声。"}],
                    "affinity_delta": 0, "advance_act": False, "ending": None}
        return super().generate(prompt)


def test_observe_cannot_summon_the_absent():
    st = {**runtime.default_state(), "location_id": "lB"}   # 陆七 lives in lA
    o = runtime.run_turn(STORY, st, {"name": "我"}, "我怎么去院长办公室",
                         channel="think", llm=SummonLLM())
    text = " ".join((b.get("text") or "") for b in o.get("beats") or [])
    assert "钥匙" not in text and "负一层" not in text     # the summoned scene was rewritten
    assert "应急灯" in text                                 # the corrected take landed


def test_mere_mention_without_dialogue_is_allowed():
    class ThinkLLM(MockLLM):
        def generate(self, prompt):
            if prompt.get("observe") and not prompt.get("logic_correction"):
                return {"beats": [{"type": "description", "speaker_name": None,
                                   "text": "你想起陆七说过的话，走廊安静得能听见水管的滴声。"}],
                        "affinity_delta": 0, "advance_act": False, "ending": None}
            return super().generate(prompt)
    st = {**runtime.default_state(), "location_id": "lB"}
    o = runtime.run_turn(STORY, st, {"name": "我"}, "这里是哪", channel="think",
                         llm=ThinkLLM())
    text = " ".join((b.get("text") or "") for b in o.get("beats") or [])
    assert "想起陆七" in text                               # memories stay legal
