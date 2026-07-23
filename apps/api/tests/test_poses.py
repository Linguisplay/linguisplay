# -*- coding: utf-8 -*-
"""🧍 动作差分 (Yi 2026-07-21: 角色的动作可以增加, 但角色不能崩):
帧表 self_position 是唯一动作来源 (零新字段) → 规则导演认出四个有素材的动作 →
随最后一句台词下发; 素材侧崩-gate 拦变形差分, 非人形角色跳过人类动作。"""
import io
import os

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./test_e2e.db")
os.environ.setdefault("JWT_SECRET", "test")

from PIL import Image  # noqa: E402

from app.engine import director, runtime, sprites  # noqa: E402


def test_pose_of_recognizes_gestures():
    assert director.pose_of("朝你挥了挥手") == "挥手"
    assert director.pose_of("抱着双臂靠在门框上") == "抱臂"
    assert director.pose_of("低头翻着手里的档案") == "低头"
    assert director.pose_of("伸出手递过一支烟") == "伸手"
    # 认不出就不动 — 常态站姿比错误的动作好
    assert director.pose_of("坐在吧台后擦枪") is None
    assert director.pose_of("") is None and director.pose_of(None) is None


def test_beat_fx_pose_beats_mood_expr():
    stage = director.TurnStage()
    # 明确的肢体动作压过表情差分
    assert stage.beat_fx("走了", "警惕", "抱臂")["expr"] == "抱臂"
    # 野字段进不了差分位 (报审: 只认白名单), 回落到表情
    assert stage.beat_fx("走了", "警惕", "劈叉")["expr"] == "惊"
    # 无动作无情绪 → 不给 expr
    assert "expr" not in stage.beat_fx("走了", None, None)


def _rgba_bytes(w: int, h: int, alpha: int = 255) -> bytes:
    im = Image.new("RGBA", (w, h), (120, 90, 60, alpha))
    buf = io.BytesIO()
    im.save(buf, format="WEBP")
    return buf.getvalue()


def test_intact_gate_blocks_broken_diffs(tmp_path, monkeypatch):
    monkeypatch.setattr(sprites, "SPRITE_DIR", tmp_path)
    (tmp_path / "c1.webp").write_bytes(_rgba_bytes(400, 900))
    # 轮廓相近 → 过; 动作幅度内的加宽 (伸手) → 过
    assert sprites._intact(_rgba_bytes(400, 900), "c1")
    assert sprites._intact(_rgba_bytes(560, 860), "c1")
    # 人缩了一半 / 全透明 (人没了) → 否
    assert not sprites._intact(_rgba_bytes(400, 430), "c1")
    assert not sprites._intact(_rgba_bytes(400, 900, alpha=0), "c1")
    # 没有常态底可比 → 放行 (宁可少限制)
    assert sprites._intact(_rgba_bytes(400, 900), "nobody")


def test_pose_pack_skips_species_chars(tmp_path, monkeypatch):
    monkeypatch.setattr(sprites, "SPRITE_DIR", tmp_path)
    monkeypatch.setattr(sprites, "AVATAR_DIR", tmp_path)
    for cid in ("hum", "cat"):
        (tmp_path / f"{cid}_src.jpg").write_bytes(_rgba_bytes(400, 900))
    calls: list[str] = []

    def fake_edit(raw, instr, mime="image/jpeg"):
        calls.append(instr)
        return None   # 失败静默跳过, 只数调用

    monkeypatch.setattr(sprites, "edit_image", fake_edit)
    rep = sprites.build_expr_pack(["hum", "cat"], no_pose_cids={"cat"})
    # 人形: 4 表情 + 4 动作; 非人形: 只有 4 表情
    assert len(calls) == 8 + 4
    assert len(rep["failed"]) == 12


def test_act_rides_last_dialogue_line():
    story = {"story": {"id": "s", "characters": [{"id": "a", "name": "甲", "is_lead": True}],
                       "acts": [{"index": 1, "title": "一"}],
                       "locations": [{"id": "hall", "name": "门厅", "detail": "x",
                                      "exits": []}]},
             "secrets": []}

    class PoseLLM:
        def generate(self, prompt):
            if prompt.get("risk_judge"):
                return {"risk": 100}
            return {"beats": [
                {"type": "dialogue", "speaker_name": "甲", "text": "先这样。"},
                {"type": "dialogue", "speaker_name": "甲", "text": "回头见。"},
            ], "self_position": "朝你挥了挥手",
                "affinity_delta": 0, "advance_act": False, "ending": None}

    out = runtime.run_turn(story, runtime.default_state(), {"name": "我"}, "再见",
                           channel="say", llm=PoseLLM())
    lines = [b for b in out["beats"] if b.get("type") == "dialogue"]
    assert lines and lines[-1].get("act") == "挥手"
    assert all(not b.get("act") for b in lines[:-1])   # 只挂最后一句
