# -*- coding: utf-8 -*-
"""🗣 语言指纹 (情商军令③): 角色的说话规律进提示词宪章 — 数据侧强声线。"""
from app.engine import qwen, runtime


def test_voice_print_reaches_charter():
    sys = qwen._build_system({"speaker_name": "阿珍", "voice_print": "短句居多，句尾爱带「咯」",
                              "channel": "say"})
    assert "语言指纹" in sys and "句尾爱带「咯」" in sys


def test_no_print_no_block():
    sys = qwen._build_system({"speaker_name": "阿珍", "channel": "say"})
    assert "语言指纹" not in sys


def test_speaker_prompt_carries_it():
    story = {"story": {"id": "s", "tuning": {"turns_per_slot": 6},
                       "characters": [{"id": "a", "name": "阿珍", "is_lead": True,
                                       "voice_print": "从不说客套话"}],
                       "acts": [{"index": 1, "title": "一"}]}, "secrets": []}

    class Spy:
        def __init__(self): self.prompts = []
        def generate(self, prompt):
            if prompt.get("speaker_name"): self.prompts.append(prompt)
            return {"beats": [{"type": "dialogue", "speaker_name": "阿珍", "text": "嗯。"}],
                    "affinity_delta": 0, "advance_act": False, "ending": None}

    llm = Spy()
    runtime.run_turn(story, runtime.default_state(), {"name": "我"}, "你好",
                     channel="say", llm=llm)
    assert any(p.get("voice_print") == "从不说客套话" for p in llm.prompts)


def test_voice_whisper_sits_next_to_generation():
    """🗣 声纹耳语 (考卷实锤: 指纹埋 system 开头写到后面就忘): 贴生成点复读一行。"""
    a = qwen._depth_anchor({"speaker_name": "阿珍", "voice_print": "短句，句尾带啦",
                            "clock": "第1天·夜", "channel": "say"})
    assert "记住你是「阿珍」" in a and "句尾带啦" in a


def test_no_whisper_without_print():
    a = qwen._depth_anchor({"speaker_name": "阿珍", "clock": "第1天·夜", "channel": "say"})
    assert "记住你是" not in a
