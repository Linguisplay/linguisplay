"""🎯 Engine-owned NPC agendas: authored `wants` seeds a live goal; the offscreen tick
advances it (step) and dialogue prompts carry goal+step — the world runs on records."""

from app.engine import runtime

STORY = {
    "story": {
        "id": "ag",
        "characters": [
            {"id": "n1", "name": "老木", "wants": "把东墙的破洞在入冬前补上",
             "home_location_id": "l2"},
            {"id": "n2", "name": "阿禾", "wants": "攒钱盘下巷口的豆腐摊",
             "home_location_id": "l2"},
            {"id": "n3", "name": "石头", "wants": "找到走失的猎犬", "home_location_id": "l1"},
        ],
        "acts": [{"index": 1, "title": "一"}],
        "locations": [
            {"id": "l1", "name": "村口", "detail": "一棵老槐树", "exits": ["集市"]},
            {"id": "l2", "name": "集市", "detail": "青石板", "exits": ["村口"]},
        ],
    },
    "secrets": [],
}


def test_agenda_seeds_from_wants_and_renders_one_line():
    st = runtime.default_state()
    c = STORY["story"]["characters"][0]
    ag = runtime.char_agenda(STORY, st, c)
    assert ag["goal"] == "把东墙的破洞在入冬前补上" and ag["step"] == ""
    ag["step"] = "从集市赊到了半车砖"
    line = runtime._agenda_prompt(STORY, st, c)
    assert "东墙" in line and "半车砖" in line
    # persisted in char_sim, not recomputed
    assert runtime.char_agenda(STORY, st, c)["step"] == "从集市赊到了半车砖"


def test_offscreen_tick_advances_both_agendas():
    st = {**runtime.default_state(), "location_id": "l1"}

    class OffLLM:
        def __init__(self):
            self.prompt = None

        def generate(self, prompt):
            self.prompt = prompt
            return {"rumor": "老木在集市跟阿禾赊了半车砖", "delta": 1}

    llm = OffLLM()
    out = runtime.offscreen_drama(STORY, st, llm)
    assert out and "砖" in out["rumor"]
    # the tick fed both goals into the prompt…
    assert "东墙" in (llm.prompt["a"].get("goal", "") + llm.prompt["b"].get("goal", ""))
    # …and booked the moment as both characters' latest step
    assert runtime.char_agenda(STORY, st, STORY["story"]["characters"][0])["step"]
    assert runtime.char_agenda(STORY, st, STORY["story"]["characters"][1])["step"]


def test_dialogue_prompt_carries_goal_and_step():
    st = {**runtime.default_state(), "location_id": "l1"}
    runtime.char_agenda(STORY, st, STORY["story"]["characters"][2])["step"] = "在村口贴了寻犬启事"

    class Spy:
        def __init__(self):
            self.prompts = []

        def generate(self, prompt):
            self.prompts.append(prompt)
            if prompt.get("risk_judge"):
                return {"risk": 100}
            if any(prompt.get(k) for k in ("suggest", "arrive", "offscreen", "farewell",
                                           "summarize", "golden_moment")):
                return {}
            return {"beats": [{"type": "dialogue", "speaker_name": "石头", "text": "嗯。"}],
                    "affinity_delta": 0, "advance_act": False, "ending": None,
                    "next_speakers": []}

    spy = Spy()
    runtime.run_turn(STORY, st, {"name": "我"}, "狗找到了吗？", channel="say", llm=spy)
    main = next(p for p in spy.prompts if p.get("speaker_name") == "石头")
    assert "走失的猎犬" in main["agenda"] and "寻犬启事" in main["agenda"]
