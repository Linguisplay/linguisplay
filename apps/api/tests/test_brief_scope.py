# -*- coding: utf-8 -*-
"""🎬 场次单缓存按局隔离 (台账 P1 串账): 同剧本同地点同时段同班底的两局,
A 局的戏眼/心事绝不许指挥 B 局。键里带 run 级命名空间 state.brief_ns。"""
import time

from app.engine import runtime

STORY = {"story": {"id": "s", "tuning": {"turns_per_slot": 6, "troupe": 1},
                   "characters": [{"id": "c1", "name": "甲"}],
                   "acts": [{"index": 1, "title": "一"}],
                   "locations": [{"id": "L", "name": "堂口"}]},
         "secrets": []}


class BriefLLM:
    def __init__(self, crux):
        self.crux = crux

    def generate(self, prompt):
        assert prompt.get("director_brief")
        return {"crux": self.crux, "minds": {"甲": "惦记着" + self.crux}}


def test_brief_cache_is_run_scoped():
    stA, stB = runtime.default_state(), runtime.default_state()
    stA["location_id"] = stB["location_id"] = "L"
    runtime.ensure_scene_brief(STORY, stA, {"name": "我"}, BriefLLM("A局的戏眼"))
    # 等后台线程把 A 局的单子写进全局缓存
    for _ in range(100):
        if any(b.get("crux") == "A局的戏眼" for b in runtime._BRIEF_CACHE.values()):
            break
        time.sleep(0.05)
    else:
        raise AssertionError("A 局的单子没进缓存")
    # B 局同场同班底首问: 老 bug 会直接吃到 A 局的单子; 现在必须空手 (自己的在后台做)
    got = runtime.ensure_scene_brief(STORY, stB, {"name": "我"}, BriefLLM("B局的戏眼"))
    assert got == {}
    assert not (stB.get("scene_brief") or {}).get("crux") == "A局的戏眼"
    assert stA["brief_ns"] != stB["brief_ns"]


def test_empty_brief_is_not_cached_forever():
    st = runtime.default_state()
    st["location_id"] = "L"

    class DeadLLM:
        def generate(self, prompt):
            raise RuntimeError("超时")

    runtime.ensure_scene_brief(STORY, st, {"name": "我"}, DeadLLM())
    ns = st["brief_ns"]
    time.sleep(0.3)   # 后台线程收尸
    # 失败的空单不入缓存 (缓存住 = 这一场永远没导演), inflight 也已清
    assert not any(k.startswith(ns + "|") for k in runtime._BRIEF_CACHE)
    assert not any(k.startswith(ns + "|") for k in runtime._BRIEF_INFLIGHT)
