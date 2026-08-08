"""Long-horizon memory: turns that slide out of the verbatim window are folded into a
rolling digest (state['memory']), so a long, player-uploaded script stays coherent past
the last-8-turns window without per-turn tokens growing without bound.

Security: the digest is built only from `history` (player input + spoken dialogue), which
by construction holds only ALREADY-revealed info. A locked secret's body must never appear
in the digest, no matter how long the run runs."""

from app.engine import runtime

# A story with one secret that is hard to unlock (high thresholds) — it stays LOCKED for
# the whole run, so its body must never enter history nor the digest.
STORY = {
    "story": {
        "id": "st",
        "world_long": "一栋深夜空楼",
        "characters": [{"id": "c1", "name": "阿明", "is_lead": True, "persona_text": "守夜人"}],
        "acts": [{"index": 1, "title": "夜", "events": []}],
        "endings": [],
    },
    "secrets": [{
        "id": "sec1", "character_id": "c1", "title": "尘封的名字",
        "fragments": [{
            "id": "f1", "content": "LOCKED_SECRET_BODY_XYZ", "retrieval_key": "名字 真相",
            "known_by_character_ids": ["c1"],
            "unlock": {"affinity_min": 999, "act_min": 9, "asks_min": 99},  # effectively unreachable
        }],
    }],
}


def _drive(turns: int):
    """Play `turns` turns, mimicking runs.py's history mapping (player + dialogue beats)."""
    state = runtime.default_state()
    history: list[dict[str, str]] = []
    persona = {"name": "玩家", "background": ""}
    for t in range(turns):
        res = runtime.run_turn(STORY, state, persona, f"第{t}句：随便聊聊", history=history)
        state = res["state"]
        history.append({"role": "user", "content": f"第{t}句：随便聊聊"})
        for b in res["beats"]:
            if b["type"] == "dialogue":
                history.append({"role": "assistant", "content": b["text"]})
    return state, history


def test_short_run_keeps_memory_empty():
    # Everything still fits in the verbatim window — nothing to summarize yet.
    state, _ = _drive(4)
    assert state["memory"] == ""
    assert state["memory_covered"] == 0


def test_long_run_accumulates_digest():
    # 「长」的定义跟着窗口走: 逐字窗口 = MEMORY_WINDOW 个回合, 再多 MEMORY_BATCH 个
    # 才够折一次。2026-08-06 窗口 14→24 之后, 写死的 15 回合就再也折不出摘要了。
    # 折得更晚不是退步 —— 那些回合现在【原样】在提示词里, 比摘要更全。
    state, history = _drive(runtime.MEMORY_WINDOW + runtime.MEMORY_BATCH + 4)
    # the digest has fired and advanced past the window
    assert state["memory"], "expected a non-empty rolling digest on a long run"
    assert state["memory_covered"] > 0
    # only turns OLDER than the verbatim window are folded in
    assert state["memory_covered"] <= len(history) - runtime.MEMORY_WINDOW + runtime.MEMORY_BATCH


def test_locked_secret_never_enters_digest():
    # The leak tripwire: a never-unlocked secret's body must not surface in memory.
    # ⚠️ 回合数按【玩家回合】算 (2026-08-08「同一把尺」): 窗口留 24 个回合,
    #    要压缩得先超过它 + MEMORY_BATCH。旧夹具的 20 在新尺下压根滑不出窗口。
    state, history = _drive(runtime.MEMORY_WINDOW + runtime.MEMORY_BATCH + 2)
    assert state["memory"], "digest should exist after a long run"
    assert "LOCKED_SECRET_BODY_XYZ" not in state["memory"]
    # and it was never even spoken into history (the gate kept it out upstream)
    assert all("LOCKED_SECRET_BODY_XYZ" not in h["content"] for h in history)
