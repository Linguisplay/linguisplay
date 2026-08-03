"""🕸 The NPC↔NPC relationship web: authored ties come alive, the primary's judgment
shifts stances between PRESENT characters (clamped, never the player), performances
carry the stance line, and the dossier shows only ties toward people the player met."""

from app.engine import logic, runtime

STORY = {
    "story": {"id": "s", "characters": [
        {"id": "a", "name": "甲", "is_lead": True,
         "ties": [{"char_id": "b", "stance": 2, "label": "过命的交情"},
                  {"char_id": "c", "stance": -1}]},
        {"id": "b", "name": "乙"},
        {"id": "c", "name": "丙", "appears_from_act": 2},
    ], "acts": [{"index": 1, "title": "一"}, {"index": 2, "title": "二"}],
       "locations": [{"id": "hall", "name": "门厅", "detail": "一盏吊灯", "exits": []}]},
    "secrets": [],
}


class WebLLM:
    def __init__(self, **fields):
        self.fields = fields
        self.prompts = []

    def generate(self, prompt):
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


def test_ties_seed_and_prompt_carries_stances():
    llm = WebLLM(next_speakers=[])
    st = runtime.default_state()
    out = runtime.run_turn(STORY, st, {"name": "我"}, "大家好", channel="say", llm=llm)
    st = out["state"]
    # 拆向后边是 {ab, ba, log} (0e14595): 授权方向带作者 label, 对向兜底同 stance
    assert st["npc_rel"]["a|b"]["ab"] == {"stance": 2, "label": "过命的交情"}
    assert st["npc_rel"]["a|b"]["log"] == []
    assert runtime.npc_stance(st, "a", "b") == {"stance": 2, "label": "过命的交情"}
    assert runtime.npc_stance(st, "a", "c")["stance"] == -1
    assert st["npc_rel"]["a|c"]["ab"]["label"] is None      # 作者没写 label, 原样存
    # the speaker's performance knows their charged stances toward who's HERE (丙 hasn't entered)
    line = llm.prompts[0].get("npc_stances") or ""
    assert "你与乙：过命的交情" in line and "丙" not in line


def test_judged_shift_applies_with_guardrails():
    llm = WebLLM(next_speakers=[],
                 npc_shifts=[{"a": "甲", "b": "乙", "delta": -1, "why": "当众下不来台"},
                             {"a": "甲", "b": "丙", "delta": 1, "why": "不在场，应拒绝"},
                             {"a": "甲", "b": "我", "delta": 1, "why": "玩家，应拒绝"}])
    st = runtime.default_state()
    out = runtime.run_turn(STORY, st, {"name": "我"}, "你们俩吵什么", channel="say", llm=llm)
    st = out["state"]
    e = st["npc_rel"]["a|b"]
    assert e["ab"]["stance"] == 1 and e["ab"]["label"] is None   # evolved past the authored flavor
    assert e["log"][-1]["why"] == "当众下不来台"
    assert "a|我" not in str(st["npc_rel"])                  # player never enters the web
    assert runtime.npc_stance(st, "a", "c")["stance"] == -1  # absent char untouched
    ms = [m for m in out["moments"] if m["kind"] == "npc_rel"]
    assert ms == [{"kind": "npc_rel", "a": "甲", "b": "乙", "delta": -1, "stance": 1}]


def test_stance_clamps_and_zero_crossing_drops_entryless():
    st = runtime.default_state()
    runtime._ensure_npc_rel(STORY, st)
    st["act"] = 2  # 丙 enters
    # pushing past +2 refuses (no change → no moment)
    assert runtime.apply_npc_shift(STORY, st, "甲", "乙", 1, "", 1) is None
    # unknown name refuses
    assert runtime.apply_npc_shift(STORY, st, "甲", "路人", 1, "", 1) is None
    # a fresh pair starts at 0 and can go up
    got = runtime.apply_npc_shift(STORY, st, "乙", "丙", 1, "一起扛过一遭", 1)
    assert got == {"a": "乙", "b": "丙", "delta": 1, "stance": 1}
    assert runtime.npc_stance(st, "c", "b") == {"stance": 1, "label": "交好"}


def test_dossier_ties_only_show_met_people():
    st = runtime.default_state()
    runtime._ensure_npc_rel(STORY, st)
    st["met_ids"] = ["a", "b"]      # the player has never seen 丙
    ties = runtime.character_profile(STORY, st, "a")["ties"]
    assert ties == [{"name": "乙", "stance": 2, "label": "过命的交情"}]
    st["met_ids"] = ["a", "b", "c"]
    names = [t["name"] for t in runtime.character_profile(STORY, st, "a")["ties"]]
    assert names == ["丙", "乙"]     # worst-first


def test_linter_flags_bad_ties():
    bad = {"story": {"id": "s", "characters": [
        {"id": "a", "name": "甲", "ties": [{"char_id": "nope", "stance": 1},
                                           {"char_id": "a", "stance": 1}]}],
        "acts": [{"index": 1, "title": "一"}]}, "secrets": []}
    codes = {i["code"] for i in logic.lint_story(bad)}
    assert "bad_tie" in codes and "self_tie" in codes
