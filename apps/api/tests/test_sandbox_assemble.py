# -*- coding: utf-8 -*-
"""🧩 沙盒 payload 组装: 世界件+角色+阶梯+答案 → StoryInput 形状。
确定性部分绝不烧模型: 经济映射/phone 开合/单幕/endings=[] 全是查表和惯例。"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./test_sbasm.db")
os.environ.setdefault("JWT_SECRET", "test")

from app.engine.llm import MockLLM  # noqa: E402
from app.routers.stories import _assemble_sandbox  # noqa: E402
from app.schemas import StoryInput  # noqa: E402

WORLD = MockLLM().generate({"sandbox_world": True, "answers": {}, "summary": "x"})
CHARS = [{"id": "ch_1", "name": "甲", "playable": False, "schedule": [], "ties": []}]
PROG = {"name": "剑心", "ranks": ["淬体", "凝气", "问剑", "御剑", "剑心通明", "化神"]}


def _p(answers=None, prog=PROG):
    return _assemble_sandbox(WORLD, CHARS, prog, answers or {"题材": "修仙"}, "")


def test_payload_passes_story_input_schema():
    StoryInput(**_p())   # 与 studio/draft_engine 共用同一道门, 不许私有格式


def test_sandbox_conventions_hold():
    p = _p()
    assert p["endings"] == [] and len(p["acts"]) == 1, "沙盒惯例: 单幕无结局"
    assert p["visibility"] == "private" and p["language"] == "zh"
    sb = p["sandbox"]
    assert sb["enabled"] is True and sb["real_time"] is True
    assert sb["opening_visitor"] == "ch_1"
    assert sb["start_location"] == "loc_1"
    assert sb["progression"]["name"] == "剑心"


def test_genre_maps_economy_deterministically():
    assert _p({"题材": "修仙"})["sandbox"]["currency"] == "灵石"
    assert _p({"题材": "星际"})["sandbox"]["start_money"] == 200
    assert _p({"题材": "没听过的题材"})["sandbox"]["currency"] == "元"


def test_powers_come_from_answers_one_per_line_clamped():
    p = _p({"题材": "修仙", "金手指": "能看见他人头顶的死期\n" + "长" * 60 + "\nc\nd\ne"})
    ps = p["sandbox"]["default_powers"]
    assert len(ps) == 4 and all(len(x) <= 40 for x in ps)
    assert ps[0] == "能看见他人头顶的死期"


def test_tech_level_drives_phone():
    assert _p()["phone"] == {"enabled": False}   # mock 世界 tech_level=ancient
    modern = dict(WORLD, tech_level="modern")
    p = _assemble_sandbox(modern, CHARS, None, {"题材": "都市异能"}, "")
    assert p["phone"] == {"enabled": True, "device": "手机"}


def test_no_progression_means_no_key_at_all():
    p = _p(prog=None)
    assert "progression" not in p["sandbox"], "留空才轮得到开局 ensure_progression 兜底"


def test_style_and_locations_ride_along():
    p = _p()
    assert "忌" in p["style"]
    assert p["locations"][0]["id"] == "loc_1"
    assert all(l["unlock"]["act_min"] == 0 for l in p["locations"])
