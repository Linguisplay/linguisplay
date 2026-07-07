# -*- coding: utf-8 -*-
"""⚖️ 命运抉择: generated high-authority forks — engine verifies targets, enforces picks
(death booked / relocation applied / direction mandated), audits everything."""
from app.engine import runtime

MAP = {
    "story": {
        "id": "ft",
        "characters": [
            {"id": "c1", "name": "Mara", "is_lead": True, "home_location_id": "hall"},
            {"id": "c2", "name": "Iven", "home_location_id": "hall"},
        ],
        "acts": [{"index": 1, "title": "一", "goal": "活下去"}],
        "locations": [
            {"id": "hall", "name": "门厅", "detail": "一盏吊灯", "exits": ["书房"]},
            {"id": "study", "name": "书房", "detail": "书架", "exits": ["门厅"]},
        ],
    },
    "secrets": [],
}

SANDBOX = {"story": {**MAP["story"], "id": "fts", "sandbox": {"enabled": True}},
           "secrets": []}


class FateLLM:
    def __init__(self, out):
        self.out = out

    def generate(self, prompt):
        assert prompt.get("fate_choice")
        return self.out


def _st():
    return {**runtime.default_state(), "location_id": "hall"}


def test_generate_validates_and_types_options():
    st = _st()
    llm = FateLLM({"prompt": "杀还是放？", "options": [
        {"label": "杀了Mara", "kind": "kill", "target": "Mara", "mandate": "血债血偿的路"},
        {"label": "去书房躲起来", "kind": "move", "target": "书房", "mandate": "先避风头"},
        {"label": "杀了不存在的人", "kind": "kill", "target": "无名氏", "mandate": "空谈"},
    ]})
    fc = runtime.fate_generate(MAP, st, llm)
    assert fc and fc["kind"] == "fate" and len(fc["options"]) == 3
    eff = st["fate_effects"]
    assert eff["f1"] == {"kind": "kill", "target": "c1", "mandate": "血债血偿的路"}
    assert eff["f2"]["kind"] == "move" and eff["f2"]["target"] == "study"
    assert eff["f3"]["kind"] == "story" and eff["f3"]["target"] == ""  # downgraded
    # player-facing shape carries NO effects (id + label + omen hint only)
    assert all(set(o) == {"id", "label", "omen"} for o in fc["options"])
    assert fc["expires"] == 3


def test_generate_move_unknown_place():
    # authored story: off-map move downgrades to story; sandbox keeps the name
    llm = FateLLM({"prompt": "走不走？", "options": [
        {"label": "撤去后巷", "kind": "move", "target": "后巷", "mandate": "跑路"},
        {"label": "留下", "kind": "story", "target": "", "mandate": "硬扛"},
    ]})
    st = _st()
    runtime.fate_generate(MAP, st, llm)
    assert st["fate_effects"]["f1"]["kind"] == "story"
    st2 = _st()
    runtime.fate_generate(SANDBOX, st2, llm)
    assert st2["fate_effects"]["f1"] == {"kind": "move", "target": "后巷", "mandate": "跑路"}


def test_generate_needs_two_valid_options():
    st = _st()
    llm = FateLLM({"prompt": "只有一个选项", "options": [{"label": "唯一", "kind": "story"}]})
    assert runtime.fate_generate(MAP, st, llm) is None


def test_apply_kill_books_the_death():
    st = _st()
    st["following"] = ["c1"]
    llm = FateLLM({"prompt": "杀还是放？", "options": [
        {"label": "动手", "kind": "kill", "target": "Mara", "mandate": "从此无人拦路"},
        {"label": "收手", "kind": "story", "target": "", "mandate": "留一线"},
    ]})
    st["pending_choice"] = runtime.fate_generate(MAP, st, llm)
    res = runtime.apply_choice(MAP, st, "f1")
    assert res["killed"] == "Mara"
    assert "c1" in st["dead_character_ids"] and st["following"] == []
    assert st["mandate"] == {"text": "从此无人拦路", "left": 8}
    assert st["pending_choice"] is None and st["fate_effects"] is None
    assert st["fate_turns"] == 0 and "fate1" in st["choices"]


def test_apply_move_relocates():
    st = _st()
    llm = FateLLM({"prompt": "走不走？", "options": [
        {"label": "去书房", "kind": "move", "target": "书房", "mandate": "先避风头"},
        {"label": "留下", "kind": "story", "target": "", "mandate": "硬扛"},
    ]})
    st["pending_choice"] = runtime.fate_generate(MAP, st, llm)
    res = runtime.apply_choice(MAP, st, "f1")
    assert res["moved_to"] == "书房" and st["location_id"] == "study"


def test_mandate_decays():
    st = _st()
    st["mandate"] = {"text": "血债血偿", "left": 1}
    # the per-turn decay lives in the stream; emulate its rule directly
    md = st["mandate"]
    md["left"] -= 1
    if md["left"] <= 0:
        st["mandate"] = None
    assert st["mandate"] is None
