"""Natural turn allocation: a broadcast is not a roll call. The primary's next_speakers
judgment decides who (0~2) chimes in and in what order; characters the player named or
whose secret was probed always get to speak; no judgment → legacy everyone-answers."""

from app.engine import runtime

STORY = {
    # golden/snap 是概率触发的额外 LLM 调用 — 这里断言【精确调用清单】, 必须关掉
    # (潜伏雷: 全局 RNG 流被前面的测试位移就会炸, 2026-07-15 实弹)
    "story": {"id": "s", "tuning": {"golden_chance": 0, "snap_chance": 0},
              "characters": [
        {"id": "a", "name": "甲", "is_lead": True},
        {"id": "b", "name": "乙"},
        {"id": "c", "name": "丙"},
    ], "acts": [{"index": 1, "title": "一"}]},
    "secrets": [{"id": "s1", "character_id": "c", "title": "丙的旧账",
                 "fragments": [{"id": "f1", "content": "X", "retrieval_key": "旧账",
                                "known_by_character_ids": ["c"],
                                "unlock": {"affinity_min": 999}}]}],
}


class CasterLLM:
    """Primary returns a fixed next_speakers judgment; every call answers with a line."""

    def __init__(self, picks):
        self.picks = picks
        self.calls = []

    def generate(self, prompt):
        if prompt.get("music_judge"):
            return {}   # 🎼 乐师是并行旁路, 不算发言调用
        if prompt.get("track_scene"):
            return {}                      # 🎥 the tracker pass is not a casting call
        if prompt.get("intro") or prompt.get("observe") or prompt.get("suggest"):
            return {"beats": [{"type": "description", "speaker_name": None, "text": "x"}],
                    "affinity_delta": 0, "advance_act": False, "ending": None}
        sp = prompt.get("speaker_name")
        self.calls.append(sp)
        out = {"beats": [{"type": "dialogue", "speaker_name": sp, "text": f"{sp}的话"}],
               "affinity_delta": 0, "advance_act": False, "ending": None}
        if prompt.get("group_mode") == "primary":
            out["next_speakers"] = self.picks
        return out


def _speakers(out):
    return [b["speaker_name"] for b in out["beats"] if b["type"] == "dialogue"]


def test_only_judged_members_speak_in_order():
    llm = CasterLLM(["丙", "乙"])
    out = runtime.run_turn(STORY, runtime.default_state(), {"name": "我"}, "大家好啊",
                           channel="say", llm=llm)
    assert _speakers(out) == ["甲", "丙", "乙"]   # judged order, not cast order


def test_nobody_chimes_in_when_judged_empty():
    llm = CasterLLM([])
    out = runtime.run_turn(STORY, runtime.default_state(), {"name": "我"}, "大家好啊",
                           channel="say", llm=llm)
    assert _speakers(out) == ["甲"]               # a quiet room is allowed
    assert llm.calls == ["甲"]                    # members not even called → cheaper


def test_named_character_always_gets_to_speak():
    llm = CasterLLM([])
    out = runtime.run_turn(STORY, runtime.default_state(), {"name": "我"}, "乙，你觉得呢？",
                           channel="say", llm=llm)
    assert "乙" in _speakers(out)                 # named by the player → must-speak


def test_probed_secret_owner_always_gets_to_speak():
    llm = CasterLLM([])
    out = runtime.run_turn(STORY, runtime.default_state(), {"name": "我"}, "那笔旧账到底怎么回事",
                           channel="say", llm=llm)
    assert "丙" in _speakers(out)                 # their secret was probed → must-speak


def test_no_judgment_keeps_legacy_everyone():
    out = runtime.run_turn(STORY, runtime.default_state(), {"name": "我"}, "大家好啊",
                           channel="say")          # MockLLM: no next_speakers field
    assert set(_speakers(out)) >= {"甲", "乙", "丙"}
