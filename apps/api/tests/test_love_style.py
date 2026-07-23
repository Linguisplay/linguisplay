"""💘 防御风格: hard-to-get as ENGINE law — the style's voice always rides the prompt,
and after a warm spike the pullback happens at the next meeting, exactly once."""

from app.engine import relationships as R
from app.engine import runtime

STORY = {
    "story": {
        "id": "ls",
        "characters": [{"id": "t1", "name": "阿霜", "love_style": "tsundere",
                        "home_location_id": "l1"}],
        "acts": [{"index": 1, "title": "一"}],
        "locations": [{"id": "l1", "name": "廊下", "detail": "一盏灯", "exits": []}],
    },
    "secrets": [],
}


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
        return {"beats": [{"type": "dialogue", "speaker_name": "阿霜", "text": "哼。"}],
                "affinity_delta": 0, "advance_act": False, "ending": None,
                "next_speakers": []}


def _main_prompt(spy):
    return next(p for p in spy.prompts if p.get("speaker_name") == "阿霜")


def test_style_library_resolves_and_renders():
    assert R.love_style_of({"love_style": "tsundere"}) == "tsundere"
    assert R.love_style_of({"love_style": "傲娇"}) == "tsundere"
    assert R.love_style_of({}) is None
    assert "心口不一" in R.style_block("tsundere")
    assert "回撤" in R.style_block("tsundere", retreat=True)
    assert "回撤" not in R.style_block("tsundere", retreat=False)
    assert R.style_block("sunny", retreat=True).count("回撤") == 0  # 直球不回撤


def test_style_voice_always_rides_the_prompt():
    st = {**runtime.default_state(), "location_id": "l1"}
    spy = Spy()
    runtime.run_turn(STORY, st, {"name": "我"}, "今天也好看。", channel="say", llm=spy)
    assert "傲娇" in _main_prompt(spy)["relationship_playbook"]


def test_retreat_fires_once_at_the_next_meeting():
    st = {**runtime.default_state(), "location_id": "l1"}
    runtime._sim(st, "t1")["warm_peak"] = {"t": runtime._time_index(st) - 1, "served": False}
    spy = Spy()
    out = runtime.run_turn(STORY, st, {"name": "我"}, "昨天谢谢你。", channel="say", llm=spy)
    assert "回撤" in _main_prompt(spy)["relationship_playbook"]
    assert any(e["e"] == "style.retreat" and e["ok"] for e in out["audit"])
    # served exactly once — the meeting after plays the base style only
    spy2 = Spy()
    runtime.run_turn(STORY, out["state"], {"name": "我"}, "又见面了。", channel="say", llm=spy2)
    pb2 = _main_prompt(spy2)["relationship_playbook"]
    assert "傲娇" in pb2 and "回撤" not in pb2


def test_stale_warm_peak_expires_without_retreat():
    st = {**runtime.default_state(), "location_id": "l1"}
    runtime._sim(st, "t1")["warm_peak"] = {"t": runtime._time_index(st) - 10, "served": False}
    spy = Spy()
    runtime.run_turn(STORY, st, {"name": "我"}, "好久不见。", channel="say", llm=spy)
    assert "回撤" not in _main_prompt(spy)["relationship_playbook"]
    assert runtime._sim(st, "t1")["warm_peak"]["served"] is True


def test_charm_playbook_hooks_and_friend_gating():
    """🪝 撩拨+期待感手艺 (Yi 2026-07-22: 撩玩家要制造期待感): 暧昧/恋人档带离场钩子;
    朋友档的将撩未撩只给可恋爱的角色 (工具人同事不许发烫)。"""
    from app.engine import relationships as R
    romantic = {"relation_allowed": ["stranger", "peer", "friend", "flirt", "lover"]}
    plain = {"relation_allowed": ["stranger", "peer"]}
    # 暧昧/恋人: 撩拨手艺 + 期待感钩子
    assert "期待感" in R.playbook_block("flirt")
    assert "期待感" in R.playbook_block("lover")
    # 朋友档: 可恋爱角色有将撩未撩, 不可恋爱的没有
    assert "将撩未撩" in R.playbook_block("friend", char=romantic)
    assert "将撩未撩" not in R.playbook_block("friend", char=plain)
    assert "将撩未撩" not in R.playbook_block("friend")   # 不传 char 保守不注入
    # 陌生人档不带撩 (交浅不许言深)
    assert "撩" not in R.playbook_block("stranger")
