# -*- coding: utf-8 -*-
"""🎬 表演指纹 v3 (Yi 2026-07-26: 把「细腻」拆成可执行锚点): 行动节奏/感官侧重/情感表达
形式, 和 voice_print 同哲学但管动作/描写。每角色一套、生成点注入、亲密拍放满; 不设不注入。"""
from app.engine import qwen, runtime


def test_stage_print_injected_when_set():
    sys = qwen._build_system({"speaker_name": "夜见", "speaker_persona": "温柔护士",
                              "persona": {"name": "你"}, "channel": "say", "context": {},
                              "act_pace": "分阶段推进，每步间有确认",
                              "sense_focus": "触觉最敏感，写温度与震颤",
                              "emote_form": "动作暗示+内心独白"})
    assert "表演指纹" in sys
    assert "分阶段推进" in sys and "触觉最敏感" in sys and "动作暗示" in sys
    assert "情绪浓/亲密时放满" in sys      # 亲密拍加权、日常轻描


def test_partial_stage_print_only_shows_set_dims():
    sys = qwen._build_system({"speaker_name": "细辉", "speaker_persona": "闷汉修车匠",
                              "persona": {"name": "你"}, "channel": "say", "context": {},
                              "act_pace": "利落，一步到位"})     # 只设一维
    assert "行动节奏=利落，一步到位" in sys
    assert "感官侧重" not in sys and "情感表达" not in sys        # 没设的不硬凑


def test_no_stage_print_block_when_unset():
    sys = qwen._build_system({"speaker_name": "细辉", "speaker_persona": "闷汉",
                              "persona": {"name": "你"}, "channel": "say", "context": {}})
    assert "表演指纹" not in sys


def test_fields_reach_speaker_prompt():
    story = {"story": {"id": "s", "tuning": {"turns_per_slot": 6},
                       "characters": [{"id": "a", "name": "夜见", "is_lead": True,
                                       "persona_text": "温柔护士",
                                       "act_pace": "分阶段推进", "sense_focus": "触觉",
                                       "emote_form": "内心独白"}],
                       "acts": [{"index": 1, "title": "一"}]}, "secrets": []}

    class Spy:
        def __init__(self): self.prompts = []
        def generate(self, prompt):
            if prompt.get("speaker_name"): self.prompts.append(prompt)
            return {"beats": [{"type": "dialogue", "speaker_name": "夜见", "text": "嗯。"}],
                    "affinity_delta": 0, "advance_act": False, "ending": None}

    llm = Spy()
    runtime.run_turn(story, runtime.default_state(), {"name": "你"}, "你好",
                     channel="say", llm=llm)
    p = next(x for x in llm.prompts)
    assert p.get("act_pace") == "分阶段推进" and p.get("sense_focus") == "触觉"


def test_draft_contract_asks_for_stage_print():
    """起草合同 (char_from_text) 要出这三维, 新角色自动带表演指纹。"""
    from app.engine.llm import MockLLM
    from app.routers.stories import _sanitize_cards
    out = MockLLM().generate({"char_from_text": True, "text": "码头老陈是个账房"})
    cards = _sanitize_cards(out)
    assert cards[0].get("act_pace") and cards[0].get("emote_form")


def test_card_library_keeps_stage_print():
    from app.routers.cards import _content_of
    from app.schemas import CharacterCardInput
    body = CharacterCardInput(name="夜见", act_pace="分阶段", sense_focus="触觉", emote_form="内心独白")
    d = _content_of(body)
    assert d["act_pace"] == "分阶段" and d["sense_focus"] == "触觉" and d["emote_form"] == "内心独白"
