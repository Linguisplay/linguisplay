"""E2E 复核: 用真 QwenLLM.generate (只挡住 HTTP), 跑一整拍 run_turn_stream。"""
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


def test_main_turn_dies_once_rel_read_is_populated(monkeypatch):
    clean = {"met_ids": ["c1"]}
    got_ok = _run(clean, monkeypatch)
    assert any(b.get("type") == "dialogue" for b in got_ok), got_ok

    poisoned = {"met_ids": ["c1"],
                "rel_read": {"c1": {"mode": "旧相识", "feeling": "念着旧情",
                                    "why": "上回替我挡了一刀", "at": 3}}}
    got_bad = _run(poisoned, monkeypatch)
    assert not any(b.get("type") == "dialogue" for b in got_bad), got_bad
