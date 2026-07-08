"""plan/render 双拍合同 (docs/plan-render.md): the plan beat judges, the render beat
streams prose. Covers: the pilot switch, the plan tool's shape (judgments preserved,
prose dropped, lockstep with render_turn), the render directive being prose-only,
token events streaming ahead of the canonical beats, plan judgments settling, and
MockLLM parity through the two-beat seam."""

from app.engine import runtime
from app.engine.llm import MockLLM
from app.engine.qwen import _plan_tool, _render_directive, _render_tool

STORY = {
    "story": {
        "id": "s",
        "tuning": {"plan_render": 1},
        "characters": [{"id": "c1", "name": "M", "is_lead": True}],
        "acts": [{"index": 1, "title": "一"}],
    },
    "secrets": [],
}


class TwoBeatLLM:
    """Scripted backend: plan_and_render streams tokens then a generate()-shaped final;
    generate() serves every aux call (suggest/summarize/…) with a harmless default."""

    def __init__(self):
        self.plan_calls = 0

    def generate(self, prompt):
        if prompt.get("summarize"):
            return {"memory": ""}
        if prompt.get("suggest"):
            return {"suggestions": []}
        return {"beats": [{"type": "dialogue", "speaker_name": prompt.get("speaker_name"),
                           "text": "嗯。"}],
                "affinity_delta": 0, "advance_act": False, "ending": None}

    def plan_and_render(self, prompt):
        self.plan_calls += 1
        for tok in ("M挑了挑眉，", "「你来啦。」", "她把杯子放下。"):
            yield ("token", tok)
        yield ("final", {
            "beats": [{"type": "description", "speaker_name": None,
                       "text": "M挑了挑眉，把杯子放下。"},
                      {"type": "dialogue", "speaker_name": "M", "text": "你来啦。"}],
            "affinity_delta": 2, "advance_act": False, "ending": None,
            "self_intent": "先看看他想干什么",
        })


def test_switch_default_off_and_tuning_pilot():
    assert runtime.plan_render_on({"story": {"id": "x"}}) is False
    assert runtime.plan_render_on(STORY) is True
    en = {"story": {"id": "x", "language": "en", "tuning": {"plan_render": 1}}}
    assert runtime.plan_render_on(en) is False  # 「」 speech splitter is zh-shaped


def test_plan_tool_drops_prose_keeps_judgments():
    prompt = {"cast": ["N"], "place": "酒馆", "persona": {"name": "我"}}
    tool = _plan_tool(prompt, "M", False, None, "say", "hint")
    fn = tool["function"]
    props = fn["parameters"]["properties"]
    assert fn["name"] == "plan_turn"
    for gone in ("narration", "speech", "inner_read"):
        assert gone not in props
    for kept in ("affinity", "advance", "self_state", "self_intent"):
        assert kept in props
    assert fn["parameters"]["required"][:2] == ["grounding", "outline"]
    # every plan judgment must exist under the SAME name in render_turn — the two
    # contracts share _parse_tool_args and may never drift apart
    rt = _render_tool(prompt, "M", False, None, "say", "hint")
    rt_props = rt["function"]["parameters"]["properties"]
    for k in props:
        if k not in ("grounding", "outline"):
            assert k in rt_props


def test_render_directive_prose_only():
    d = _render_directive({"channel": "say"}, "M", ["递酒", "点破来意"])
    assert "1. 递酒" in d and "2. 点破来意" in d
    assert "好感" not in d and "推进" not in d  # no metadata lines in the render beat
    t = _render_directive({"channel": "think", "persona": {"name": "我"}}, "M", [])
    assert "内心独白" in t


def test_line_protocol_parse_and_stream():
    """行协议（2026-07-08 深夜）：每行声明 旁白：/名字：，台词物理上进不了旁白行；
    切分器边流边给出 (kind, speaker, text)，气泡从第一个字就是对的。"""
    from app.engine.qwen import _LineSegmenter, _parse_line_beats

    text = "旁白：方叔摸出一根烟。\n方叔：「那屋啊。」\n旁白：他顿了顿。"
    beats = _parse_line_beats(text)
    assert [b["type"] for b in beats] == ["description", "dialogue", "description"]
    assert beats[1]["speaker_name"] == "方叔" and beats[1]["text"] == "那屋啊。"
    assert _parse_line_beats("没有任何前缀的自由散文，两句都没有冒号收尾") is None

    seg = _LineSegmenter("方叔")
    toks = []
    for d in ("旁白：方叔摸出", "一根烟。\n方叔：「那", "屋啊。」\n"):
        toks += seg.feed(d)
    toks += seg.flush()
    joined: dict = {}
    for k, w, t in toks:
        joined[(k, w)] = joined.get((k, w), "") + t
    assert joined[("narration", None)] == "方叔摸出一根烟。"
    assert joined[("speech", "方叔")] == "那屋啊。"


def test_tokens_stream_before_beats_and_plan_settles():
    llm = TwoBeatLLM()
    st = runtime.default_state()
    events = list(runtime.run_turn_stream(STORY, st, {"name": "我"}, "你好",
                                          channel="say", llm=llm))
    assert llm.plan_calls == 1
    token_idx = [i for i, (k, _) in enumerate(events) if k == "token"]
    assert token_idx, "render tokens must surface as stream events"
    first_m_beat = next(i for i, (k, v) in enumerate(events)
                        if k == "beat" and v.get("speaker_name") == "M")
    assert all(i < first_m_beat for i in token_idx)
    final = next(v for k, v in events if k == "final")
    # the plan's judgments settled through the normal cascade
    assert (final["state"].get("char_sim", {}).get("c1", {}).get("intent")
            == "先看看他想干什么")


def test_flag_off_never_calls_plan():
    story_off = {"story": {**STORY["story"], "tuning": {}}, "secrets": []}
    llm = TwoBeatLLM()
    st = runtime.default_state()
    events = list(runtime.run_turn_stream(story_off, st, {"name": "我"}, "你好",
                                          channel="say", llm=llm))
    assert llm.plan_calls == 0
    assert not any(k == "token" for k, _ in events)


def test_mock_llm_two_beat_parity():
    st = runtime.default_state()
    out = runtime.run_turn(STORY, st, {"name": "我"}, "你好", channel="say",
                           llm=MockLLM())
    assert out["beats"]  # Mock's plan_and_render delegates to generate — turn completes
