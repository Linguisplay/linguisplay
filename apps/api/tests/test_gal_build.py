# -*- coding: utf-8 -*-
"""🎀 galgame 生成器 P0: parse → normalize → chapter compile obeys the pacing
contract shape; the expression sheet crops clean; reserved fields (voice/cg/adult/
fx) ride every beat so nothing returns later as a migration."""
import io

from app.engine import gal
from app.engine.llm import MockLLM

SRC = "林晚在天台遇见了沈刻。" * 40   # ≥200 chars


def test_parse_normalizes_ids_and_protagonist():
    out = gal.parse_story(MockLLM(), SRC, "天台")
    assert [c["id"] for c in out["characters"]] == ["c1", "c2"]
    assert out["protagonist_id"] == "c1"                 # 林晚 by name match
    assert [s["id"] for s in out["scenes"]] == ["s1", "s2"]
    assert len(out["chapters"]) == 2
    assert all("voice" in c for c in out["characters"])  # 🔊 reserved for TTS


def test_compile_obeys_contract_shape():
    g = gal.parse_story(MockLLM(), SRC, "天台")
    g["source_text"] = SRC
    beats = gal.compile_chapter(MockLLM(), g, 1)
    assert len(beats) >= 8
    assert beats[0]["id"] == "c1b001"
    for b in beats:
        for k in ("cg", "adult", "fx", "voice", "expr", "scene", "bgm"):
            assert k in b                                # reserved fields present
        assert b["scene"] in ("s1", "s2")
        assert b["who"] in (None, "c1", "c2")
    assert any(b["cg"] for b in beats)                   # the CG moment survived
    # 🎬 the protagonist has no face on screen
    assert all(b.get("who_face") is None for b in beats if b["who"] == g["protagonist_id"])


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
