# -*- coding: utf-8 -*-
"""引擎法守卫: engine code must never carry a specific 剧本's content. 「城寨」 leaked
into the asylum's prose because a Kowloon-era line was hardcoded in the engine —
this guard fails the build the moment a story-specific word lands in any engine
source line that isn't a pure comment."""
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1] / "app" / "engine"

# words that belong to SEEDS, never to the engine (grow this list with each new 剧本)
BANNED = ("城寨", "蓝信一", "龙卷风", "老周", "苏婷", "陈工",
          "铁松", "阿枝", "陆九秋", "温以宁", "贺院长", "疗养院", "寂声",
          "迦南", "史莱克", "明珠学院", "唐三", "小舞", "穆宁雪", "莫凡",
          "莫格街", "末班车上", "婚约之下", "浮生",
          "不朽野心号", "卡拉维尔", "科瓦兹", "货舱镇",
          "雌火龙", "灭尽龙", "大凶豺龙", "艾露猫", "星辰集会所",
          "猫铃堂", "福婆", "麻薯")


def test_engine_source_carries_no_story_content():
    hits = []
    for py in sorted(ENGINE.glob("*.py")):
        for i, line in enumerate(py.read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue  # design notes may cite history; shipped strings may not
            for w in BANNED:
                if w in line:
                    hits.append(f"{py.name}:{i} contains 「{w}」: {line.strip()[:60]}")
    assert not hits, "\n".join(hits)
