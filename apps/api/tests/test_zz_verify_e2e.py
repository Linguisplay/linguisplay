# -*- coding: utf-8 -*-
"""🧪 E2E: 用真 QwenLLM.generate (只挡住 HTTP) 跑一整拍 run_turn_stream。

⚠️ 这个文件抓到过一个只有 e2e 才撞得出来的实弹 (2026-08-08, 我自己造的):
qwen.generate 的【分派键】叫 relation_read, 而主拍载荷里也有一个同名键
(TA 此刻怎么看玩家)。于是关系一落账, 整个主回合就被路由到关系判官 ——
一个 beat 都不出, 角色彻底哑掉。而且没有任何守卫开枪、审计单干干净净,
单测全绿 (它们只测 _build_system 的字符串, 测不到分派)。

教训跟今天早上那次「角色不能发言」是同一个: 组件各自都对, 接缝上错了。
只有真的把一整拍跑完才看得见。
"""
import json

from app.engine import qwen, runtime

STORY = {
    "story": {
        "id": "s",
        "characters": [{"id": "c1", "name": "阿珍", "is_lead": True}],
        "acts": [{"index": 1, "title": "一"}],
    },
    "secrets": [],
}


class _Resp:
    def __init__(self, payload):
        self._p = payload

    def json(self):
        return self._p


def _fake_post(url, key, body, timeout=None, kind=None, **kw):
    if body.get("tools"):
        args = json.dumps({"narration": "雨敲在铁皮棚上。",
                           "speech": ["你怎么这时候来了。"],
                           "affinity_delta": 1, "advance_act": False})
        return _Resp({"choices": [{"message": {
            "content": "", "tool_calls": [{"function": {"name": "render_turn",
                                                        "arguments": args}}]}}]})
    return _Resp({"choices": [{"message": {"content": "（一段旁白。）"}}]})


def _llm():
    o = qwen.QwenLLM.__new__(qwen.QwenLLM)
    o._url, o._key = "http://never", "k"
    o._model = o._summary_model = o._aux_model = "m"
    return o


def _run(state, monkeypatch):
    monkeypatch.setattr(qwen, "_post_chat", _fake_post)
    monkeypatch.setattr(runtime.get_settings(), "logic_guard", False, raising=False)
    beats = []
    for kind, payload in runtime.run_turn_stream(STORY, state, {"name": "我"},
                                                 "你还好吗", llm=_llm()):
        if kind == "beat":
            beats.append(payload)
    return beats


def test_a_populated_relation_does_not_kill_the_turn(monkeypatch):
    """关系落了账, 主拍照样得出台词。(修之前: 0 个 beat, 角色彻底哑掉。)"""
    clean = _run({"met_ids": ["c1"]}, monkeypatch)
    assert any(b.get("type") == "dialogue" for b in clean), clean

    withrel = _run({"met_ids": ["c1"],
                    "rel_read": {"c1": {"mode": "旧相识", "feeling": "念着旧情",
                                        "why": "上回替我挡了一刀", "at": 3}}}, monkeypatch)
    assert any(b.get("type") == "dialogue" for b in withrel), withrel
    assert any(b.get("type") == "description" for b in withrel), withrel


def test_even_a_bare_timestamp_does_not_kill_the_turn(monkeypatch):
    """最小复现: 只有 at 也会触发 —— 因为它跟提示词无关, 纯粹是分派被劫。"""
    got = _run({"met_ids": ["c1"], "rel_read": {"c1": {"at": 3}}}, monkeypatch)
    assert any(b.get("type") == "dialogue" for b in got), got

def test_the_dispatch_key_never_collides_with_a_payload_key():
    """真正的合同: generate 的【分派键】不许跟主拍载荷里的键同名。

    同名 = 主拍被静默路由去别的处理器 —— 审计单干净、守卫不响、单测全绿
    (它们只测 _build_system 吐出来的字符串, 测不到分派这一层)。
    只看真正的分派行, generate 里顺手读的 channel/speaker_name 那些不算。
    """
    import inspect
    import re as _re
    src = inspect.getsource(qwen.QwenLLM.generate)
    dispatch = set(_re.findall(
        r'if\s+prompt\.get\("(\w+)"\)\s*:\s*\n\s*return\s+self\.', src))
    assert dispatch, "一条分派行都没认出来 — 正则跟代码对不上, 这条合同在空转"
    payload = set(_re.findall(r'prompt\.get\("(\w+)"\)',
                              inspect.getsource(qwen._build_system)))
    clash = dispatch & payload
    assert not clash, f"分派键与主拍载荷键撞名: {sorted(clash)}"
