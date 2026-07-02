"""18禁 (mature/R18) + 智能增强 (knowledge) — ported from the old persona project.

R18: when a run is mature the engine appends an adult-content permission block to the
system prompt (still refusing minors). 智能增强: a per-character knowledge block is
injected as reference. Both are off by default and shape the live qwen prompt only."""

from app.engine import qwen, runtime


def test_autonomy_block_and_agenda_in_prompt():
    base = {"speaker_name": "龙卷风", "speaker_persona": "话事人", "persona": {"name": "我"},
            "channel": "say", "context": {}}
    sys = qwen._build_system(base)
    assert "独立的人" in sys and "不是工具人" in sys      # autonomy directive always present
    assert "声音只属于你" in sys                           # distinct-voice instruction present
    # an authored agenda is injected as the character's own goal
    sys2 = qwen._build_system({**base, "agenda": "守住城寨那条门路"})
    assert "守住城寨那条门路" in sys2


def test_r18_block_only_when_mature():
    base = {"speaker_name": "A", "speaker_persona": "p", "persona": {"name": "我"},
            "channel": "say", "context": {}}
    assert "成人内容许可" not in qwen._build_system(base)
    sys = qwen._build_system({**base, "mature": True})
    assert "成人内容许可" in sys and "18禁" in sys
    assert "未成年" in sys  # the one hard refusal is always stated


def test_knowledge_block_injected_when_present():
    base = {"speaker_name": "A", "speaker_persona": "p", "persona": {"name": "我"},
            "channel": "say", "context": {}}
    assert "背景知识" not in qwen._build_system(base)
    sys = qwen._build_system({**base, "knowledge": "【人物设定】传说中的刀客。"})
    assert "背景知识" in sys and "传说中的刀客" in sys


def test_generate_knowledge_degrades_without_key(monkeypatch):
    # with no search/model key, enrich must return "" (degrade), never raise — no network call
    class _NoKey:
        dashscope_api_key = ""
        llm_model = "qwen-max"

    monkeypatch.setattr(qwen, "get_settings", lambda: _NoKey())
    assert qwen.generate_knowledge("某人", "一个神秘的角色", "某个世界") == ""


def test_mature_defaults_off_and_flows_through_run():
    story = {"story": {"id": "s", "characters": [{"id": "c1", "name": "M", "is_lead": True}],
                       "acts": [{"index": 1, "title": "a"}]}, "secrets": []}
    st = runtime.default_state()
    assert st["mature"] is False
    # a mature run forwards the flag into the prompt the engine builds
    captured = {}

    class SpyLLM:
        def generate(self, prompt):
            # only speaker prompts carry the flag (auxiliary calls like the
            # suggestions prompt have no speaker_name and would overwrite it)
            if prompt.get("speaker_name"):
                captured["mature"] = prompt.get("mature")
            return {"beats": [{"type": "dialogue", "speaker_name": prompt.get("speaker_name"), "text": "."}],
                    "affinity_delta": 0, "advance_act": False, "ending": None}

    st["mature"] = True
    runtime.run_turn(story, st, {"name": "我"}, "hi", channel="say", llm=SpyLLM())
    assert captured.get("mature") is True
