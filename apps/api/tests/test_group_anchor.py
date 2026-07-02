"""Group-turn role anchoring: after this-turn lines are appended as assistant messages,
a closing user-role cue re-anchors WHOSE turn it is — otherwise the model continues the
conversation chain and a member answers the player's question AS the player (the
十二少-answers-for-the-player bug)."""

from app.engine import qwen


class _FakeResp:
    status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return {"choices": [{"message": {
            "tool_calls": [{"function": {"name": "render_turn",
                                         "arguments": "{\"speech\": \"嗯。\"}"}}],
            "content": ""}}]}


def _capture_generate(prompt):
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["body"] = json
        return _FakeResp()

    orig = qwen.httpx.post
    qwen.httpx.post = fake_post
    try:
        llm = qwen.DeepSeekLLM.__new__(qwen.DeepSeekLLM)
        llm._url = "http://fake"
        llm._key = "k"
        llm._model = "m"
        llm._summary_model = "m"
        llm.generate(prompt)
    finally:
        qwen.httpx.post = orig
    return captured["body"]["messages"]


BASE = {"speaker_name": "十二少", "speaker_persona": "愣头青", "persona": {"name": "蔡妍"},
        "channel": "say", "context": {}, "cast": ["龙卷风"], "player_input": "龙哥是吧，我是新来的。"}


def test_member_gets_turn_anchor_after_said_lines():
    msgs = _capture_generate({**BASE, "group_mode": "member",
                              "said_this_turn": [{"speaker": "龙卷风", "text": "你会什么手艺？"}]})
    # the primary's line rides in as an assistant turn...
    assert any(m["role"] == "assistant" and "你会什么手艺" in m["content"] for m in msgs)
    # ...and the FINAL message is a user-role cue re-anchoring identity + forbidding
    # answering on the player's behalf
    last = msgs[-1]
    assert last["role"] == "user"
    assert "十二少" in last["content"] and "蔡妍" in last["content"] and "作答" in last["content"]


def test_no_anchor_when_nothing_said_yet():
    msgs = _capture_generate(dict(BASE))  # primary speaks first: no said_this_turn
    assert "该你了" not in (msgs[-1]["content"] or "")


def test_member_speech_field_forbids_answering_for_player():
    tool = qwen._render_tool({**BASE, "group_mode": "member"}, "十二少", False, "member", "say", "hint")
    sd = tool["function"]["parameters"]["properties"]["speech"]["description"]
    assert "蔡妍" in sd and "绝不替" in sd
