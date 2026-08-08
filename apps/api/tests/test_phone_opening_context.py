# -*- coding: utf-8 -*-
"""📱 手机上的开场白也要结合上下文 (Yi 2026-08-08)。

主拍那条手机【回复】路 2026-08-06 就接上了 recent_scene (「你们最近当面发生的事」)。
但角色【主动】发的那些消息走的是另一条路 (compose_message → _compose_msg), 它拿得到
人设、关系、事实账、线程尾巴 —— 唯独拿不到刚才当面发生了什么。

后果最明显的是初次见面那条自我介绍: 你们刚一起经历了整场开场戏, 分开之后手机响一声,
内容却只能是「阿彩。」这种放之四海而皆准的话。第一句话是这台设备对玩家说的第一句,
它最不该是空的。

reachout_after_event 更离谱: 它的名字就是「刚一起经历了点什么, 事后来一条」，
而它看不见那件事。

认知边界照旧走 history_for 的见证过滤 —— 我不在场的那场雨我不该在短信里提。
"""
from app.engine import qwen, runtime


CONTENT = {"story": {
    "id": "s",
    # ⚠️ 甲 的家安在别处: reachout_on_meet 有一条闸「人还站在你面前时不发」——
    #    当面聊着天、手机响一声「你好我是甲」很蠢。自我介绍要等你们分开之后才到。
    "characters": [{"id": "a", "name": "甲", "is_lead": True, "persona_text": "码头挑夫",
                    "home_location_id": "l2"},
                   {"id": "b", "name": "乙", "persona_text": "看铺子的",
                    "home_location_id": "l2"}],
    "acts": [{"index": 1, "title": "一"}],
    "locations": [{"id": "l1", "name": "旧巷", "detail": "x", "exits": ["码头"]},
                  {"id": "l2", "name": "码头", "detail": "x", "exits": ["旧巷"]}]}}

BEATS = [
    {"author": "player", "type": "dialogue", "text": "外面雨好大", "present_ids": ["a"]},
    {"author": "engine", "type": "description",
     "text": "甲把外套脱下来罩在你头上，自己淋着。", "present_ids": ["a"]},
    {"author": "engine", "type": "dialogue", "speaker_name": "甲",
     "text": "走快点，前面有檐子。", "present_ids": ["a"]},
    # 乙 全程不在场
    {"author": "engine", "type": "description",
     "text": "乙在铺子里数着铜板。", "present_ids": ["b"]},
]


class _Spy:
    """只记下 compose_msg 那一次的 payload。"""

    def __init__(self):
        self.seen = None

    def generate(self, p):
        if p.get("compose_msg"):
            self.seen = p
            return {"msgs": ["嗯。"]}
        return {}


def _st():
    st = runtime.default_state()
    st["location_id"] = "l1"
    return st


# ── 上下文真的传下去了 ────────────────────────────────────────────────────────

def test_the_composer_gets_what_just_happened():
    llm = _Spy()
    runtime.compose_message(CONTENT, _st(), CONTENT["story"]["characters"][0],
                            "初次见面", "报个名号", "甲。", llm, beat_log=BEATS)
    rs = (llm.seen or {}).get("recent_scene") or []
    assert rs, "开场白还是瞎写的 —— 刚才当面那场戏一个字都没进去"
    assert any("外套" in s for s in rs), f"喂进去的不是这一场: {rs}"


def test_witness_isolation_still_holds():
    """⚠️ 认知边界是护城河, 不许为了「上下文更丰富」拆掉。
    乙 全程不在场, TA 的开场白里不该有那件事。"""
    llm = _Spy()
    runtime.compose_message(CONTENT, _st(), CONTENT["story"]["characters"][1],
                            "初次见面", "报个名号", "乙。", llm, beat_log=BEATS)
    rs = (llm.seen or {}).get("recent_scene") or []
    assert not any("外套" in s for s in rs), f"乙 不在场却知道了: {rs}"


def test_no_beat_log_behaves_exactly_as_before():
    """可逆: 拿不到历史的调用方 (旧签名) 一个字都不变。"""
    llm = _Spy()
    runtime.compose_message(CONTENT, _st(), CONTENT["story"]["characters"][0],
                            "初次见面", "报个名号", "甲。", llm)
    assert not ((llm.seen or {}).get("recent_scene") or [])


# ── 提示词层真的用上了 ────────────────────────────────────────────────────────

def test_the_prompt_actually_uses_it():
    """传下去了但提示词不读, 等于没传 —— 这条接缝我今天已经栽过一次。"""
    sent = {}

    def _fake_post(url, key, body, **kw):
        sent["sys"] = body["messages"][0]["content"]

        class _R:
            @staticmethod
            def json():
                return {"choices": [{"message": {"content": "嗯。"}}]}
        return _R()

    old = qwen._post_chat
    qwen._post_chat = _fake_post
    try:
        llm = qwen.QwenLLM.__new__(qwen.QwenLLM)
        llm._url, llm._key, llm._model = "http://never", "k", "m"
        llm._compose_msg({"compose_msg": True, "char": {"name": "甲"},
                          "hint": "报个名号",
                          "recent_scene": ["你：外面雨好大", "甲把外套罩在你头上"]})
    finally:
        qwen._post_chat = old
    assert "外套" in sent.get("sys", ""), "recent_scene 传下去了, 提示词却没读"


def test_the_prompt_is_unchanged_without_it():
    """没有上下文时不许平白多一段 —— 每条消息都在花 token。"""
    sent = {}

    def _fake_post(url, key, body, **kw):
        sent["sys"] = body["messages"][0]["content"]

        class _R:
            @staticmethod
            def json():
                return {"choices": [{"message": {"content": "嗯。"}}]}
        return _R()

    old = qwen._post_chat
    qwen._post_chat = _fake_post
    try:
        llm = qwen.QwenLLM.__new__(qwen.QwenLLM)
        llm._url, llm._key, llm._model = "http://never", "k", "m"
        llm._compose_msg({"compose_msg": True, "char": {"name": "甲"}, "hint": "x"})
    finally:
        qwen._post_chat = old
    assert "刚才当面" not in sent.get("sys", "")


# ── 端到端: 自我介绍那一条真的接上了 ──────────────────────────────────────────

def test_the_first_intro_text_is_written_with_the_scene():
    """这一条是 Yi 报的那件事本身。单测传参对了不算数, 要真的从调用链走下来。"""
    llm = _Spy()
    st = _st()
    st["met_ids"] = ["a"]
    st.setdefault("phone", {}).setdefault("seen", {})["a"] = 1
    runtime.grant_contact_on_meet(CONTENT, st)
    runtime.reachout_on_meet(CONTENT, st, llm, beat_log=BEATS)
    rs = (llm.seen or {}).get("recent_scene") or []
    assert rs and any("外套" in s for s in rs), \
        f"自我介绍那条还是瞎写的（调用链没接上）: {rs}"
