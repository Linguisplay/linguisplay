# -*- coding: utf-8 -*-
"""🎀 galgame 生成器 P0+P1: parse → normalize → chapter compile obeys the pacing
contract; choices move the affinity ledger (伪分支); the ending fork is engine
law (真分歧只在结局); 🔞 stripping is an engine defense; expression portraits
ride one seed per character; reserved fields (voice/cg/adult/fx) ride every beat."""
import pytest

from app.engine import gal
from app.engine.llm import MockLLM

SRC = "林晚在天台遇见了沈刻。" * 40   # ≥200 chars


def _parsed():
    g = gal.parse_story(MockLLM(), SRC, "天台")
    g["source_text"] = SRC
    return g


def test_parse_normalizes_ids_and_protagonist():
    out = _parsed()
    assert [c["id"] for c in out["characters"]] == ["c1", "c2"]
    assert out["protagonist_id"] == "c1"                 # 林晚 by name match
    assert [s["id"] for s in out["scenes"]] == ["s1", "s2"]
    assert len(out["chapters"]) == 2
    assert all("voice" in c for c in out["characters"])  # 🔊 reserved for TTS
    # 💘 可攻略 flag survives normalization — the affinity ledger needs it
    assert [c["route"] for c in out["characters"]] == [False, True]


def test_compile_obeys_contract_shape():
    beats, summary = gal.compile_chapter(MockLLM(), _parsed(), 1)
    assert summary
    normal = [b for b in beats if b.get("type") != "choice"]
    assert len(normal) >= 8
    assert normal[0]["id"] == "c1b001"
    for b in normal:
        for k in ("cg", "adult", "fx", "voice", "expr", "scene", "bgm",
                  "date", "sfx", "require", "weather"):
            assert k in b                                # reserved fields present
        assert b["scene"] in ("s1", "s2")
        assert b["who"] in (None, "c1", "c2")
    assert any(b["cg"] for b in normal)                  # the CG moment survived
    # 🎬 the protagonist has no face on screen — main line AND branches
    assert all(b.get("who_face") is None
               for b in gal._walk_beats(beats) if b["who"] == "c1")


def test_compile_normalizes_and_splices_choices():
    beats, _ = gal.compile_chapter(MockLLM(), _parsed(), 1)
    choices = [b for b in beats if b.get("type") == "choice"]
    assert len(choices) == 1
    c = choices[0]
    assert c["id"] == "c1q1"
    # TEXT anchor (实弹《余音》: numeric indexes went stale) — the choice lands
    # right after the beat whose text the anchor quotes
    assert beats[7] is c and "明天" in beats[6]["text"]
    assert len(c["options"]) == 2
    o1, o2 = c["options"]
    assert o1["fx"] == {"c2": 2} and o2["fx"] == {"c2": -1}   # ledger moves, clamped
    assert o1["beats"][0]["id"] == "c1q1o1b01"                # branch ids are stable
    assert o2["beats"][0]["id"] == "c1q1o2b01"


def test_inline_choice_shape_still_tolerated():
    class InlineLLM(MockLLM):
        def generate(self, prompt):
            out = super().generate(prompt)
            if prompt.get("gal_compile"):
                ch = out.pop("choices")[0]
                out["beats"].insert(7, {"options": ch["options"]})
            return out
    beats, _ = gal.compile_chapter(InlineLLM(), _parsed(), 1)
    assert sum(1 for b in beats if b.get("type") == "choice") == 1


def test_missing_choices_retried_once():
    # field case (HP build, DeepSeek): a clean chapter with zero choices — the
    # compiler re-asks once with the sharpened reminder before failing
    class ForgetOnceLLM(MockLLM):
        calls = 0
        def generate(self, prompt):
            out = super().generate(prompt)
            if prompt.get("gal_compile"):
                ForgetOnceLLM.calls += 1
                if not (prompt.get("retry") or {}).get("choices"):
                    out.pop("choices")
            return out
    beats, _ = gal.compile_chapter(ForgetOnceLLM(), _parsed(), 1)
    assert ForgetOnceLLM.calls == 2
    assert any(b.get("type") == "choice" for b in beats)


def test_slice_source_cuts_at_from_quotes():
    src = "一月的故事开头。" * 10 + "二月的转折来了。" * 10 + "三月的结尾到了。" * 10
    chs = [{"i": 1, "summary": "a", "from": "一月的故事开头"},
           {"i": 2, "summary": "b", "from": "二月的转折来了"},
           {"i": 3, "summary": "c", "from": "三月的结尾到了"}]
    s = gal.slice_source(src, chs)
    assert len(s) == 3
    assert s[0].startswith("一月") and "二月" not in s[0]
    assert s[1].startswith("二月") and "三月" not in s[1]
    assert s[2].startswith("三月")
    # unusable quotes → even split fallback, never a crash
    s2 = gal.slice_source(src, [{"from": "原文里没有这句"}, {"from": ""}])
    assert len(s2) == 2 and s2[0] and s2[1]


def test_compiler_sees_only_its_slice():
    # 实弹《余音》根治: greedy whole-book adaptation — every chapter compiled the
    # arc to the finale. The compiler cannot re-tell what it cannot see.
    class CaptureLLM(MockLLM):
        seen = {}
        def generate(self, prompt):
            if prompt.get("gal_compile"):
                CaptureLLM.seen[prompt["chapter"]["i"]] = prompt["source"]
            return super().generate(prompt)
    g = _parsed()
    g["source_text"] = "第一幕天台相遇。" * 30 + "第二幕教室对峙。" * 30
    g["chapters"] = [{"i": 1, "summary": "a", "from": "第一幕天台相遇"},
                     {"i": 2, "summary": "b", "from": "第二幕教室对峙"}]
    gal.compile_chapter(CaptureLLM(), g, 1)
    gal.compile_chapter(CaptureLLM(), g, 2)
    assert "第二幕" not in CaptureLLM.seen[1]
    assert CaptureLLM.seen[2].startswith("第二幕")


def test_opening_echo_named_retry_fixes_it():
    # 实弹 (《余音》第2/5章): the model re-tells chapter 1's opening — the echo
    # guard catches it and the named retry gets a fresh opening
    class EchoOnceLLM(MockLLM):
        def generate(self, prompt):
            out = super().generate(prompt)
            if prompt.get("gal_compile") and not (prompt.get("retry") or {}).get("echo"):
                out["beats"][0]["text"] = "风从天台的边缘掀过来。"
            return out
    beats, _ = gal.compile_chapter(EchoOnceLLM(), _parsed(), 2,
                                   prior_openings=["风从天台的边缘掀过来。"])
    first = next(b["text"] for b in beats if b.get("type") != "choice")
    assert first != "风从天台的边缘掀过来。"


def test_opening_echo_persistent_fails_loud():
    class HardEchoLLM(MockLLM):
        def generate(self, prompt):
            out = super().generate(prompt)
            if prompt.get("gal_compile"):
                out["beats"][0]["text"] = "风从天台的边缘掀过来。"
            return out
    with pytest.raises(ValueError):
        gal.compile_chapter(HardEchoLLM(), _parsed(), 2,
                            prior_openings=["风从天台的边缘掀过来。"])


def test_translate_source_chunks_and_joins():
    class TransLLM(MockLLM):
        calls = 0
        def generate(self, prompt):
            if prompt.get("gal_translate"):
                TransLLM.calls += 1
                return {"text": f"译文{TransLLM.calls}。"}
            return super().generate(prompt)
    jp = ("日本語のテキストです。" * 40 + "\n") * 20     # kana-heavy, multi-chunk
    assert gal.needs_translation(jp)
    assert not gal.needs_translation("这是一段中文文本。" * 60)
    out = gal.translate_source(TransLLM(), jp)
    assert TransLLM.calls >= 2                          # chunked, not one giant call
    assert out.count("译文") == TransLLM.calls          # all chunks joined


def test_foreign_language_beats_retried_then_fail_loud():
    # 实弹《野菊之墓》: Japanese source → the compiler mirrored the language
    JP = "後の月という時分になると、どうしても思い出さずにはいられない。"
    class JpOnceLLM(MockLLM):
        def generate(self, prompt):
            out = super().generate(prompt)
            if prompt.get("gal_compile") and not (prompt.get("retry") or {}).get("lang"):
                for b in out["beats"]:
                    b["text"] = JP
            return out
    beats, _ = gal.compile_chapter(JpOnceLLM(), _parsed(), 1)
    assert not any(gal._kana_heavy(b["text"]) for b in gal._walk_beats(beats))

    class JpAlwaysLLM(MockLLM):
        def generate(self, prompt):
            out = super().generate(prompt)
            if prompt.get("gal_compile"):
                for b in out["beats"]:
                    b["text"] = JP
            return out
    with pytest.raises(ValueError):
        gal.compile_chapter(JpAlwaysLLM(), _parsed(), 1)


def test_choice_fx_backfilled_when_model_forgets():
    class ForgetfulLLM(MockLLM):
        def generate(self, prompt):
            out = super().generate(prompt)
            if prompt.get("gal_compile"):
                for ch in out["choices"]:
                    for o in ch["options"]:
                        o["fx"] = {}
            return out
    beats, _ = gal.compile_chapter(ForgetfulLLM(), _parsed(), 1)
    c = next(b for b in beats if b.get("type") == "choice")
    # 数值必须动: the engine backfills +1 so the ending threshold stays reachable
    assert any(v > 0 for o in c["options"] for v in o["fx"].values())


def test_nonfinal_chapter_without_choice_fails_loud():
    class NoChoiceLLM(MockLLM):
        def generate(self, prompt):
            out = super().generate(prompt)
            if prompt.get("gal_compile"):
                out.pop("choices", None)
            return out
    g = _parsed()
    with pytest.raises(ValueError):
        gal.compile_chapter(NoChoiceLLM(), g, 1)          # ch1 of 2 must offer a fork
    beats, _ = gal.compile_chapter(NoChoiceLLM(), g, 2)   # the final chapter may not:
    assert beats                                          # its fork IS the endings


def test_adult_stripped_unless_mature():
    class SpicyLLM(MockLLM):
        def generate(self, prompt):
            out = super().generate(prompt)
            if prompt.get("gal_compile"):
                out["beats"][0]["adult"] = True
            return out
    g = _parsed()
    beats, _ = gal.compile_chapter(SpicyLLM(), g, 1)                 # default: not mature
    assert not any(b["adult"] for b in gal._walk_beats(beats))       # 防线在引擎
    beats, _ = gal.compile_chapter(SpicyLLM(), g, 1, mature=True)
    assert any(b["adult"] for b in gal._walk_beats(beats))


def test_values_meta_and_threshold():
    g = _parsed()
    b1, _ = gal.compile_chapter(MockLLM(), g, 1)
    b2, _ = gal.compile_chapter(MockLLM(), g, 2)
    vm = gal.values_meta([b1, b2], g["characters"], g["protagonist_id"])
    assert vm["routes"] == ["c2"] and vm["target"] == "c2"
    assert vm["max"]["c2"] == 4                  # two choices × best option +2
    assert vm["threshold"]["c2"] == 2            # 60% of max, rounded


def test_endings_engine_owns_the_fork():
    g = _parsed()
    b1, _ = gal.compile_chapter(MockLLM(), g, 1)
    b2, _ = gal.compile_chapter(MockLLM(), g, 2)
    g["values"] = gal.values_meta([b1, b2], g["characters"], g["protagonist_id"])
    ends = gal.compile_endings(MockLLM(), g)
    assert len(ends) == 2
    assert ends[0]["cond"] == {"char": "c2", "gte": 2}   # 真分歧只在结局: threshold law
    assert ends[1]["cond"] == {"default": True}          # and there is always a floor
    assert all(len(e["beats"]) >= 6 for e in ends)
    assert ends[0]["beats"][0]["id"] == "e1b001"
    assert ends[0]["title"] and ends[1]["title"]


def test_set_beat_text_reaches_everywhere():
    g = _parsed()
    b1, _ = gal.compile_chapter(MockLLM(), g, 1)
    g["script"] = {g["protagonist_id"]: {"chapters": [b1]}}
    g["values"] = gal.values_meta([b1], g["characters"], g["protagonist_id"])
    g["endings"] = gal.compile_endings(MockLLM(), g)
    # main line, a choice branch, and an ending — 改字 must reach all three
    branch_id = next(b for b in b1 if b.get("type") == "choice")["options"][0]["beats"][0]["id"]
    for bid in ("c1b001", branch_id, "e1b001"):
        assert gal.set_beat_text(g, bid, "改过的字。")
    assert not gal.set_beat_text(g, "nope", "x")
    assert not gal.set_beat_text(g, "c1b001", "")     # empty text refused
    texts = [b["text"] for ch in g["script"][g["protagonist_id"]]["chapters"]
             for b in gal._walk_beats(ch)]
    assert texts.count("改过的字。") == 2              # main + branch


def test_outline_and_survey():
    out = gal.outline_story(MockLLM(), "天台上的恋爱故事，甜中带虐")
    assert out["title"] and len(out["outline"]) == 2
    idea = gal.survey_idea(MockLLM(), {"题材": "校园恋爱", "口味": "甜"})
    assert len(idea) >= 50
    with pytest.raises(ValueError):
        class EmptyLLM(MockLLM):
            def generate(self, prompt):
                if prompt.get("gal_outline"):
                    return {}
                return super().generate(prompt)
        gal.outline_story(EmptyLLM(), "x")


def test_bad_parse_fails_loud():
    class EmptyLLM(MockLLM):
        def generate(self, prompt):
            if prompt.get("gal_parse"):
                return {}
            return super().generate(prompt)
    try:
        gal.parse_story(EmptyLLM(), SRC, "x")
        assert False, "should have raised"
    except ValueError:
        pass


def test_portrait_prompts_share_everything_but_the_expression():
    # 差分表已废: per-expression portraits ride the SAME seed and prompts that
    # differ only in the expression phrase — that's what keeps the face
    char = {"id": "c2", "name": "沈刻", "looks": "高瘦青年，金丝眼镜"}
    prompts = {e: gal.portrait_prompt(char, "天台的故事", "日漫", e)
               for e in gal.EXPRESSIONS}
    assert len(set(prompts.values())) == 4                 # expressions differ
    for e, p in prompts.items():
        assert "沈刻" in p and "只有这一个人" in p
        assert gal._EXPR_FACE[e] in p
        # everything except the expression phrase is byte-identical
        assert p.replace(gal._EXPR_FACE[e], "") == \
               prompts["常态"].replace(gal._EXPR_FACE["常态"], "")


def test_cg_ledger_first_per_chapter_only():
    g = _parsed()
    b1, _ = gal.compile_chapter(MockLLM(), g, 1)
    b2, _ = gal.compile_chapter(MockLLM(), g, 2)
    # over-tag a second beat in ch1 — generation-side law keeps only the FIRST
    extras = [b for b in b1 if b.get("type") != "choice" and not b["cg"]]
    extras[-1]["cg"] = True
    g["script"] = {g["protagonist_id"]: {"chapters": [b1, b2]}}
    g["values"] = gal.values_meta([b1, b2], g["characters"], g["protagonist_id"])
    g["endings"] = gal.compile_endings(MockLLM(), g)
    ids = [b["id"] for b in gal.cg_beats(g)]
    assert ids == ["c1b006", "c2b006"]        # one per chapter, the first one
    assert len(ids) == len(set(ids))


def test_cg_prompt_faceless_protagonist():
    g = _parsed()
    beat_other = {"who": "c2", "text": "他笑了。", "scene": "s1"}
    beat_pro = {"who": "c1", "text": "你转过身。", "scene": "s1"}
    assert "沈刻" in gal.cg_prompt(g, beat_other, "")
    # the protagonist has no face — their CG is an atmosphere shot
    assert "空镜" in gal.cg_prompt(g, beat_pro, "")


def test_image_diet():
    import io as _io

    from PIL import Image
    im = Image.new("RGBA", (720, 1280), (0, 0, 0, 0))       # transparent backdrop
    for x in range(200, 500):
        for y in range(300, 900):
            im.putpixel((x, y), (200, 100, 50, 255))         # the "figure"
    buf = _io.BytesIO()
    im.save(buf, format="PNG")
    w = gal.to_webp(buf.getvalue())
    out = Image.open(_io.BytesIO(w))
    assert out.format == "WEBP"
    assert "A" in out.mode or "transparency" in out.info      # alpha survives
    big = _io.BytesIO()
    Image.new("RGB", (720, 1280), (10, 20, 30)).save(big, format="JPEG", quality=100)
    assert len(gal.shrink_jpg(big.getvalue())) <= len(big.getvalue())


def test_char_seed_stable_per_character():
    a = gal.char_seed("work1", "c2")
    assert a == gal.char_seed("work1", "c2")               # stable across calls
    assert a != gal.char_seed("work1", "c3")               # differs per character
    assert a != gal.char_seed("work2", "c2")               # and per work
    assert 0 <= a < 2 ** 31 - 1
