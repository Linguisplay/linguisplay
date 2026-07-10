# -*- coding: utf-8 -*-
"""🎀 galgame 生成器 P0+P1: parse → normalize → chapter compile obeys the pacing
contract; choices move the affinity ledger (伪分支); the ending fork is engine
law (真分歧只在结局); 🔞 stripping is an engine defense; the expression sheet
crops clean; reserved fields (voice/cg/adult/fx) ride every beat."""
import io

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
        for k in ("cg", "adult", "fx", "voice", "expr", "scene", "bgm"):
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
    assert beats[7] is c                     # spliced right after the 7th normal beat
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
                if not prompt.get("choice_retry"):
                    out.pop("choices")
            return out
    beats, _ = gal.compile_chapter(ForgetOnceLLM(), _parsed(), 1)
    assert ForgetOnceLLM.calls == 2
    assert any(b.get("type") == "choice" for b in beats)


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


def test_sheet_crop_quadrants():
    from PIL import Image
    im = Image.new("RGB", (720, 1280), (10, 20, 30))
    buf = io.BytesIO()
    im.save(buf, format="JPEG")
    pieces = gal.crop_sheet(buf.getvalue())
    assert len(pieces) == 4
    for p in pieces:
        q = Image.open(io.BytesIO(p))
        assert q.size == (360, 640)
