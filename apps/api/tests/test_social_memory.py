# -*- coding: utf-8 -*-
"""📸 朋友圈的记忆断头路 (2026-08-04 实弹):

`social_feed` 给模型的素材只有: persona[:80] + eq_style[:60] + 此刻地点 + hooks[:2]。
没有 memory、没有 recent_scene、没有玩家是谁 —— 角色在【物理上不可能】提到你们刚
发生过的事。所以他能在你们刚吵完架的当天, 发一条没事人的动态。

这是 Yi 定的第三条方向(记忆必须跨渠道共享)里唯一还没通的一段: 场上↔短信已经共用
memory_by_char, 唯独朋友圈是断的。

认知边界照旧: 只喂【这个角色自己的】私有备忘录, 绝不给全局摘要, 也绝不给未解锁秘密。
"""
from app.engine import runtime


CID = "c1"
CONTENT = {"story": {"characters": [
    {"id": CID, "name": "阿彩", "persona_text": "银彩发廊的洗头妹", "eq_style": "嘴快心软"},
    {"id": "c2", "name": "十二少", "persona_text": "城寨四子之一", "eq_style": "吊儿郎当"},
], "acts": [{"index": 1, "title": "一"}], "locations": [{"id": "hall", "name": "祥记面档"}]},
    "secrets": []}


class _Spy:
    """截下 social_posts 那一发的 prompt。"""
    def __init__(self):
        self.social = None

    def generate(self, p):
        if p.get("social_posts"):
            self.social = p
            return {"posts": []}
        return {}


def _state_with_history():
    st = runtime.default_state()
    st["location_id"] = "hall"
    st["met_ids"] = [CID, "c2"]
    st["char_pins"] = {CID: "hall"}
    # 这个角色自己的私有备忘录 (场上↔短信共用的同一本)
    st["memory_by_char"] = {CID: "今天你为了那笔账跟她吵了一架，她摔门走了，临走说了句「你自己看着办」。"}
    # 让 hooks 非空, 否则这个角色根本不进素材池
    st["char_sim"] = {CID: {"intent": "把那笔账查清楚"}}
    return st


def test_social_material_carries_the_characters_own_memory():
    st = _state_with_history()
    spy = _Spy()
    runtime.social_feed(CONTENT, st, llm=spy)
    assert spy.social, "没走到 social_posts 这一发"
    it = next((i for i in spy.social["items"] if i.get("cid") == CID), None)
    assert it, "阿彩不在素材里"
    assert (it.get("memory") or ""), "素材里没有这个角色的记忆 — 她不可能提起今天的事"
    assert "摔门" in it["memory"], f"喂进去的不是她自己的那本账: {it.get('memory')!r}"


def test_social_material_knows_who_the_player_is():
    st = _state_with_history()
    st["profile"] = {"by_char": {CID: {"text": "你嘴上硬，心软得很"}}, "facts": [], "turns": 0}
    spy = _Spy()
    runtime.social_feed(CONTENT, st, llm=spy)
    it = next(i for i in spy.social["items"] if i.get("cid") == CID)
    assert "嘴上硬" in (it.get("player_read") or ""), "TA 眼里的你没进朋友圈素材"


def test_another_characters_memory_never_leaks_into_my_post():
    """认知边界: 十二少的私账绝不能出现在阿彩的素材里。"""
    st = _state_with_history()
    st["memory_by_char"]["c2"] = "十二少私下告诉你的那件事"
    st["char_sim"]["c2"] = {"intent": "躲着龙卷风"}
    spy = _Spy()
    runtime.social_feed(CONTENT, st, llm=spy)
    mine = next(i for i in spy.social["items"] if i.get("cid") == CID)
    assert "十二少私下" not in (mine.get("memory") or ""), "串账了 — 认知边界破了"


def test_the_prompt_actually_uses_the_memory():
    """喂进去还得用上: 提示词里要看得见这段近事, 并且明确要求含蓄不复述对白。"""
    from app.engine import qwen
    q = qwen.QwenLLM.__new__(qwen.QwenLLM)
    sys_txt = qwen.QwenLLM._social_material(q, [{
        "name": "阿彩", "persona": "洗头妹", "eq_style": "嘴快",
        "hooks": ["正在办：查账"], "at": "祥记面档",
        "memory": "今天为了那笔账吵了一架，她摔门走了。",
        "player_read": "你嘴上硬心软得很"}])
    assert "摔门" in sys_txt, "记忆没进提示词"
    assert "祥记面档" in sys_txt
