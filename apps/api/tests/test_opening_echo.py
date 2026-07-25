# -*- coding: utf-8 -*-
"""🔁 开场白复读守卫 (实弹: 角色不停把作者开场白再念一遍): 任何一拍逐字重现
开场白 ≥14 连字(归一化) = 硬伤 → 重演一次, 再犯剐掉复读的句子。跟演不受罚。"""
from app.engine import logic

OPENING = ("暴雨拍在铁皮棚上。你攥着那封没有署名的信，站在牌坊底下，"
           "城寨的灯一盏一盏灭了。")


def _verify(beats):
    return logic.verify_turn(beats, absent_names=[], locked_location_names=[],
                             locked_fragment_texts=[], opening_text=OPENING)


def test_verbatim_echo_is_hard():
    v = _verify([{"type": "dialogue", "speaker_name": "阿珍",
                  "text": "你攥着那封没有署名的信，站在牌坊底下。还愣着干什么？"}])
    assert any("开场白" in h for h in v["hard"])


def test_narration_echo_is_hard_too():
    v = _verify([{"type": "description", "speaker_name": None,
                  "text": "城寨的灯一盏一盏灭了，暴雨拍在铁皮棚上。"}])
    assert any("开场白" in h for h in v["hard"])


def test_fresh_prose_and_short_overlap_pass():
    # 跟演: 承接开场的时空往下写, 只共用零星词汇 — 不算复读
    v = _verify([{"type": "dialogue", "speaker_name": "阿珍",
                  "text": "雨还没停，先进来喝口热的。信的事，坐下慢慢说。"}])
    assert v["hard"] == []


def test_no_opening_no_check():
    v = logic.verify_turn([{"type": "dialogue", "text": OPENING}], absent_names=[],
                          locked_location_names=[], locked_fragment_texts=[])
    assert v["hard"] == []


def test_scrub_drops_only_the_echo_sentence():
    beats = [{"type": "dialogue", "speaker_name": "阿珍",
              "text": "你攥着那封没有署名的信，站在牌坊底下。进来坐，外头冷。"}]
    out = logic.scrub_beats(beats, [], opening_text=OPENING)
    assert out and out[0]["text"] == "进来坐，外头冷。"


def test_scrub_drops_beat_that_empties():
    beats = [{"type": "description", "speaker_name": None,
              "text": "暴雨拍在铁皮棚上。城寨的灯一盏一盏灭了。"},
             {"type": "dialogue", "speaker_name": "阿珍", "text": "跟我来。"}]
    out = logic.scrub_beats(beats, [], opening_text=OPENING)
    assert len(out) == 1 and out[0]["text"] == "跟我来。"


def test_scrub_without_opening_keeps_legacy_behavior():
    beats = [{"type": "dialogue", "speaker_name": "阿珍", "text": "跟我来。"}]
    assert logic.scrub_beats(beats, []) == beats


# ── 英文剧本: 阈值抬高, 惯用短语不误伤, 整句照搬照抓 ──────────────────────────

EN_OPENING = ("Rain hammers the tin roof. You clutch the unsigned letter, "
              "standing under the archway as the walled city goes dark.")


def _verify_en(beats):
    return logic.verify_turn(beats, absent_names=[], locked_location_names=[],
                             locked_fragment_texts=[], opening_text=EN_OPENING)


def test_en_verbatim_sentence_is_hard():
    v = _verify_en([{"type": "dialogue", "speaker_name": "M",
                     "text": "You clutch the unsigned letter, standing under the archway."}])
    assert any("开场白" in h for h in v["hard"])


def test_en_idiom_overlap_passes():
    # 与开场白只共用惯用短语 (不足 5 词连串) — 正常续写, 不算复读
    v = _verify_en([{"type": "dialogue", "speaker_name": "M",
                     "text": "The rain again. Come in before the letter gets soaked."}])
    assert v["hard"] == []


def test_en_case_change_does_not_escape():
    v = _verify_en([{"type": "description", "speaker_name": None,
                     "text": "RAIN HAMMERS THE TIN ROOF as the walled city goes dark."}])
    assert any("开场白" in h for h in v["hard"])


# ── runtime 穿线: 复读的主拍被重演, 屡教不改就剐句 ────────────────────────────

def test_runtime_guard_scrubs_persistent_echo():
    from app.engine import runtime
    story = {"story": {"id": "s", "opening": OPENING,
                       "characters": [{"id": "a", "name": "阿珍", "is_lead": True}],
                       "acts": [{"index": 1, "title": "一"}]},
             "secrets": []}

    class ParrotLLM:
        def __init__(self):
            self.turn_calls = 0
            self.saw_correction = False

        def generate(self, prompt):
            if prompt.get("intro") or prompt.get("observe") or prompt.get("suggest") \
                    or prompt.get("risk_judge") or prompt.get("intro_vignettes"):
                return {}
            self.turn_calls += 1
            if prompt.get("logic_correction"):
                self.saw_correction = True
            return {"beats": [{"type": "dialogue", "speaker_name": "阿珍",
                               "text": "你攥着那封没有署名的信，站在牌坊底下。"},
                              {"type": "dialogue", "speaker_name": "阿珍",
                               "text": "坐下说。"}],
                    "affinity_delta": 0, "advance_act": False, "ending": None}

    llm = ParrotLLM()
    st = runtime.default_state()
    out = runtime.run_turn(story, st, {"name": "我"}, "你好", channel="say", llm=llm)
    texts = " ".join(b.get("text", "") for b in out["beats"])
    assert "没有署名的信" not in texts, "复读句必须被剐掉"
    assert "坐下说" in texts, "干净句要留下"
    assert llm.saw_correction, "必须先给过一次带定向纠正的重演机会"
