"""🧩 Input analysis: the player's line decomposed into ENGINE-VERIFIED referents that
ride the prompt at depth-0. The digest states only what the engine can verify — never
guessed intent."""

from app.engine import intent, runtime

STORY = {
    "story": {
        "id": "it",
        "characters": [
            {"id": "c1", "name": "穆宁雪", "home_location_id": "l2"},
            {"id": "c2", "name": "莫凡", "home_location_id": "l1"},
        ],
        "acts": [{"index": 1, "title": "一"}],
        "locations": [
            {"id": "l1", "name": "元素大厅", "detail": "公告屏",
             "exits": ["猎者工会"], "props": [{"id": "p1", "name": "悬浮公告屏"}]},
            {"id": "l2", "name": "猎者工会", "detail": "悬赏板", "exits": ["元素大厅"]},
        ],
    },
    "secrets": [],
}


def _st():
    return {**runtime.default_state(), "location_id": "l1",
            "inventory": [{"name": "短刃"}]}


def test_analyze_verifies_every_referent_against_live_state():
    a = intent.analyze(STORY, _st(), "把短刃给莫凡看看，然后问穆宁雪猎者工会的悬浮公告屏怎么用", "say")
    chars = {c["name"]: c for c in a["chars"]}
    assert chars["莫凡"]["present"] is True          # he's in this scene
    assert chars["穆宁雪"]["present"] is False       # she's at the guild
    assert a["items"] == [{"name": "短刃", "held": True}]
    assert a["locations"] and a["locations"][0]["name"] == "猎者工会"
    assert a["props"] and a["props"][0]["name"] == "悬浮公告屏"
    assert any("询问" in v for v in a["verbs"]) and any("给予" in v for v in a["verbs"])


def test_digest_speaks_both_languages_and_stays_quiet_on_plain_lines():
    a = intent.analyze(STORY, _st(), "问问莫凡，穆宁雪去哪了", "say")
    d = intent.digest(a, "zh")
    assert "引擎已核实" in d and "穆宁雪（不在场）" in d and "莫凡" in d
    den = intent.digest(a, "en")
    assert "engine-verified" in den and "not here" in den
    # a bare line names nothing → no digest, no noise
    assert intent.digest(intent.analyze(STORY, _st(), "嗯。", "say")) == ""


def test_digest_rides_the_responder_prompt():
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
            return {"beats": [{"type": "dialogue", "speaker_name": "莫凡", "text": "嗯。"}],
                    "affinity_delta": 0, "advance_act": False, "ending": None,
                    "next_speakers": []}

    spy = Spy()
    runtime.run_turn(STORY, _st(), {"name": "我"}, "问问莫凡，穆宁雪现在人在哪", channel="say",
                     llm=spy)
    main = next(p for p in spy.prompts if p.get("speaker_name") == "莫凡")
    assert "穆宁雪（不在场）" in main["intent_digest"]
