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


# ── 🗣 指纹自动出生: AI 生出来的角色, 出生就带说话规律 ──

def test_sandbox_cast_borns_with_voice():
    class CastLLM:
        def generate(self, prompt):
            assert prompt.get("sandbox_cast")
            return {"characters": [{"name": "阿箬", "role": "药铺学徒",
                                    "persona": "细声细气",
                                    "voice": "气音短句，句尾轻，从不抬嗓"}]}

    content = {"story": {"id": "s", "sandbox": {"enabled": True}, "characters": [],
                         "world_long": "海边小城"}, "secrets": []}
    runtime.seed_sandbox_cast(content, llm=CastLLM())
    assert content["story"]["characters"][0]["voice_print"] == "气音短句，句尾轻，从不抬嗓"


def test_emergent_new_char_third_segment_is_voice():
    story = {"story": {"id": "s", "tuning": {"turns_per_slot": 6},
                       "characters": [{"id": "a", "name": "阿珍", "is_lead": True}],
                       "acts": [{"index": 1, "title": "一"}]}, "secrets": []}

    class Spy:
        def generate(self, prompt):
            return {"beats": [{"type": "dialogue", "speaker_name": "阿珍", "text": "嗯。"}],
                    "new_char": "王二｜码头挑夫，背比人宽｜嗓门大，句句带「嘿」",
                    "affinity_delta": 0, "advance_act": False, "ending": None}

    runtime.run_turn(story, runtime.default_state(), {"name": "我"}, "你好",
                     channel="say", llm=Spy())
    nc = next(c for c in story["story"]["characters"] if c["name"] == "王二")
    assert nc["voice_print"] == "嗓门大，句句带「嘿」"
    assert nc["persona_text"] == "码头挑夫，背比人宽"      # 指纹段(末段)不混进人设


def test_emergent_new_char_four_segments_keeps_appearance_in_persona():
    """审查回归: 模型把「身份与外貌」拆成两段 → 四段输入, 外貌绝不能被当腔调误存。"""
    story = {"story": {"id": "s", "tuning": {"turns_per_slot": 6},
                       "characters": [{"id": "a", "name": "阿珍", "is_lead": True}],
                       "acts": [{"index": 1, "title": "一"}]}, "secrets": []}

    class Spy:
        def generate(self, prompt):
            return {"beats": [{"type": "dialogue", "speaker_name": "阿珍", "text": "嗯。"}],
                    "new_char": "王二｜码头挑夫｜背比人宽的汉子｜嗓门大句句带嘿",
                    "affinity_delta": 0, "advance_act": False, "ending": None}

    runtime.run_turn(story, runtime.default_state(), {"name": "我"}, "你好",
                     channel="say", llm=Spy())
    nc = next(c for c in story["story"]["characters"] if c["name"] == "王二")
    assert nc["voice_print"] == "嗓门大句句带嘿"       # 只有末段是腔调
    assert "背比人宽的汉子" in nc["persona_text"]        # 外貌留在人设, 没丢
    assert "码头挑夫" in nc["persona_text"]


def test_emergent_new_char_without_voice_still_births():
    story = {"story": {"id": "s", "tuning": {"turns_per_slot": 6},
                       "characters": [{"id": "a", "name": "阿珍", "is_lead": True}],
                       "acts": [{"index": 1, "title": "一"}]}, "secrets": []}

    class Spy:
        def generate(self, prompt):
            return {"beats": [{"type": "dialogue", "speaker_name": "阿珍", "text": "嗯。"}],
                    "new_char": "王二｜码头挑夫，背比人宽",
                    "affinity_delta": 0, "advance_act": False, "ending": None}

    runtime.run_turn(story, runtime.default_state(), {"name": "我"}, "你好",
                     channel="say", llm=Spy())
    nc = next(c for c in story["story"]["characters"] if c["name"] == "王二")
    assert nc["voice_print"] == "" and nc["persona_text"] == "码头挑夫，背比人宽"


def test_scout_mint_carries_voice():
    class L:
        def generate(self, prompt):
            if prompt.get("describe_place"):
                return {"name": "天台画室", "detail": "一方晒不到太阳的天台。"}
            return {}

    content = {"story": {"id": "s", "sandbox": {"enabled": True}, "characters": [],
                         "locations": [{"id": "l1", "name": "巷口", "exits": []}],
                         "acts": [{"index": 1, "title": "一"}]}, "secrets": []}
    st = {**runtime.default_state(), "location_id": "l1"}
    out = runtime.mint_sought_character(
        content, st, "蓝信一",
        {"fits": True, "who": "天台画画的怪人", "where": "天台画室",
         "persona": "寡言。", "voice": "画比话多，开口只给半句"}, L())
    assert out and out["char"]["voice_print"] == "画比话多，开口只给半句"


def test_parsed_cards_keep_voice_print():
    from app.routers.stories import _sanitize_cards
    cards = _sanitize_cards({"characters": [
        {"name": "码头老陈", "voice_print": "短句，爱用账房话打比方"}]})
    assert cards[0]["voice_print"] == "短句，爱用账房话打比方"


def test_parsed_cards_clamp_runaway_voice_print():
    """审查回归: 啰嗦模型把整段散文塞进 voice_print, 代码侧硬截 60 字, 别让脏数据入库。"""
    from app.routers.stories import _sanitize_cards
    cards = _sanitize_cards({"characters": [
        {"name": "话痨", "voice_print": "性格" * 200}]})
    assert len(cards[0]["voice_print"]) == 60


def test_card_library_keeps_voice_print():
    from app.routers.cards import _content_of
    from app.schemas import CharacterCardInput
    body = CharacterCardInput(name="阿珍", voice_print="句尾爱带「啦」")
    assert _content_of(body)["voice_print"] == "句尾爱带「啦」"


# ── 🗣 存量补票: 提案先验收后落库, 作者手写的永不覆盖 ──

def test_backfill_draft_maps_names_to_ids():
    import backfill_voice_prints as bvp
    from app.engine.llm import MockLLM

    class S:
        title, language, world_long, style = "T", "zh", "海边小城", ""

    chars = [{"id": "c1", "name": "阿箬"}, {"id": "c2", "name": "老宋"}]
    prints = bvp._draft(MockLLM(), S(), chars)
    assert [p["id"] for p in prints] == ["c1", "c2"]
    assert len({p["voice_print"] for p in prints}) == 2   # 互不撞腔调


def test_backfill_draft_matches_padded_names():
    """审查回归 #4: 库里名字带首尾空白也要匹配得上, 别静默丢提案。"""
    import backfill_voice_prints as bvp
    from app.engine.llm import MockLLM

    class S:
        title, language, world_long, style = "T", "zh", "", ""

    prints = bvp._draft(MockLLM(), S(), [{"id": "c1", "name": " 王二 "}, {"id": "c2", "name": "老宋"}])
    assert {p["id"] for p in prints} == {"c1", "c2"}      # 带空白的也补上了


def test_backfill_draft_drops_ambiguous_duplicate_names():
    """审查回归: 重名角色提案无法确定归属, 整个弃掉而非张冠李戴。"""
    import backfill_voice_prints as bvp
    from app.engine.llm import MockLLM

    class S:
        title, language, world_long, style = "T", "zh", "", ""

    prints = bvp._draft(MockLLM(), S(), [{"id": "c1", "name": "王二"}, {"id": "c2", "name": "王二"}])
    assert all(p["name"] != "王二" for p in prints)


def test_backfill_fill_never_overwrites_authored():
    import backfill_voice_prints as bvp
    chars = [{"id": "a", "name": "阿珍", "voice_print": "作者手写"},
             {"id": "b", "name": "细辉", "voice_print": ""}]
    n = bvp._fill(chars, {"a": {"voice_print": "提案A", "name": "阿珍"},
                          "b": {"voice_print": "提案B", "name": "细辉"}})
    assert n == 1
    assert chars[0]["voice_print"] == "作者手写"
    assert chars[1]["voice_print"] == "提案B"


def test_backfill_fill_skips_renamed_char():
    """审查回归 #5: 同 id 但作者改过名的历史副本, 不许盖上今天这个不同角色的指纹。"""
    import backfill_voice_prints as bvp
    chars = [{"id": "a", "name": "沈青梧", "voice_print": ""}]   # 老档里 id=a 曾叫阿珍
    n = bvp._fill(chars, {"a": {"voice_print": "句尾带啦", "name": "阿珍"}})
    assert n == 0 and chars[0]["voice_print"] == ""
