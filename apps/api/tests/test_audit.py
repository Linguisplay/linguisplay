"""📋 Event audit: every model-reported event lands in the turn's audit sheet — accepted
(derived from moments) or REJECTED with the reason. The debuggable "运行逻辑" surface."""

from app.engine import runtime

STORY = {
    "story": {
        "id": "au",
        "characters": [{"id": "a1", "name": "Mara", "is_lead": True}],
        "acts": [{"index": 1, "title": "一"}],
        "locations": [{"id": "l1", "name": "堂屋", "detail": "一张方桌", "exits": []}],
    },
    "secrets": [],
}


class Reporter:
    """A director that reports one legit event and two impossible ones."""

    def generate(self, prompt):
        if prompt.get("suggest") or prompt.get("arrive") or prompt.get("offscreen") \
                or prompt.get("farewell") or prompt.get("summarize") \
                or prompt.get("golden_moment"):
            return {}
        if prompt.get("risk_judge"):
            return {"risk": 100}
        return {"beats": [{"type": "dialogue", "speaker_name": "Mara", "text": "拿着吧。"}],
                "affinity_delta": 0, "advance_act": False, "ending": None,
                "gained": "铜哨",             # legit: lands in the pocket
                "lost": "幽灵剑",             # impossible: never carried
                "died": "不存在的人",          # impossible: nobody by that name here
                "next_speakers": []}


def test_audit_records_rejections_and_derives_accepts():
    st = {**runtime.default_state(), "location_id": "l1"}
    out = runtime.run_turn(STORY, st, {"name": "我"}, "你好", channel="say", llm=Reporter())
    audit = out.get("audit") or []
    assert audit, "audit sheet missing from final"
    ok = {(e["e"], e.get("data")) for e in audit if e["ok"]}
    bad = {e["e"]: e.get("why", "") for e in audit if not e["ok"]}
    assert ("item.gained", "铜哨") in ok            # accept derived from moments
    assert "item.lost" in bad and "身上没有" in bad["item.lost"]
    assert "death" in bad and "不在场" in bad["death"]
    # the sheet also rides on state for the next fetch
    assert out["state"].get("last_audit")


def test_audit_resets_every_turn():
    st = {**runtime.default_state(), "location_id": "l1"}
    out1 = runtime.run_turn(STORY, st, {"name": "我"}, "你好", channel="say", llm=Reporter())
    n1 = len(out1["audit"])
    out2 = runtime.run_turn(STORY, out1["state"], {"name": "我"}, "又见面了",
                            channel="say", llm=Reporter())
    # a fresh sheet, not an accumulating one (gained now rejects as duplicate)
    assert len(out2["audit"]) <= n1 + 1
    assert any(e["e"] == "item.gained" and not e["ok"] for e in out2["audit"])
