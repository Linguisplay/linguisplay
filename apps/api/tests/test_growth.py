# -*- coding: utf-8 -*-
"""🌱 世界生长预算 (Yi 2026-07-25 四条拍板): 节奏归引擎 — 判官上线后 58 回合零铸造
的解药。①防敷衍升级档 ②高张力场景挂起 ③双通道共享额度 ④软/硬两档措辞。"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./test_e2e.db")
os.environ.setdefault("JWT_SECRET", "test")

from app.engine import growth, runtime  # noqa: E402

SANDBOX = {"story": {"id": "s", "sandbox": {"enabled": True},
                     "characters": [{"id": "a", "name": "甲", "is_lead": True,
                                     "home_location_id": "hall"}],
                     "acts": [{"index": 1, "title": "一"}],
                     "locations": [{"id": "hall", "name": "门厅", "detail": "x",
                                    "exits": []}]},
           "secrets": []}


def test_period_and_due_ladder():
    st = {}
    # 授权本缺省关; 沙盒缺省 8; tuning 显式覆盖; 探索口味 -2
    assert growth.period_of({"story": {}}, st, []) == 0
    assert growth.period_of(SANDBOX, st, []) == 8
    assert growth.period_of(SANDBOX, st, ["探索"]) == 6
    tuned = {"story": {"tuning": {"growth_every": 5}}}
    assert growth.period_of(tuned, st, []) == 5
    # 到期阶梯: 不足不到期 → 软邀请 → 连续3次填无后硬指令
    for _ in range(7):
        growth.tick(st)
    assert growth.due(SANDBOX, st, []) == ""
    growth.tick(st)
    assert growth.due(SANDBOX, st, []) == "soft"
    for _ in range(3):
        growth.note_blank(st)
    assert growth.due(SANDBOX, st, []) == "hard"
    # 任何通道铸造 → 额度重置, 敷衍计数清零
    growth.note_mint(st)
    assert growth.due(SANDBOX, st, []) == ""
    assert st["growth"]["blanks"] == 0


def test_hot_scene_suspends():
    st = {}
    for _ in range(9):
        growth.tick(st)
    st["scene"] = {"mood": "tense"}
    assert growth.due(SANDBOX, st, []) == ""       # 对峙戏挂起
    st["scene"] = {"mood": "daily"}
    st["pending_choice"] = {"q": "x"}
    assert growth.due(SANDBOX, st, []) == ""       # 未决抉择挂起
    st.pop("pending_choice")
    assert growth.due(SANDBOX, st, []) == "soft"   # 场景一换立即放行


def test_seed_place_mints_and_resets():
    seen = {}

    class SeedLLM:
        def generate(self, prompt):
            if prompt.get("describe_place"):
                nm = (prompt.get("place_name") or "").strip()
                return {"name": nm[:12], "detail": f"{nm}的样子。"}
            if prompt.get("speaker_name"):
                seen["ws"] = prompt.get("world_seed")
                return {"beats": [{"type": "dialogue", "speaker_name": "甲",
                                   "text": "前面有个渡口。"}],
                        "world_seed": "地点：竹棚渡口",
                        "affinity_delta": 0, "advance_act": False, "ending": None}
            return {}

    st = runtime.default_state()
    for _ in range(8):
        growth.tick(st)
    out = runtime.run_turn(SANDBOX, st, {"name": "我"}, "往前走", channel="do",
                           llm=SeedLLM())
    assert seen["ws"] == "soft"                            # 软邀请下发到主拍
    assert any(l.get("name") == "竹棚渡口"
               for l in SANDBOX["story"]["locations"])     # 判官过了, 铸进世界
    mr = out.get("move_request")
    assert mr and mr.get("minted") and mr.get("to_name") == "竹棚渡口"
    assert out["state"]["growth"]["last"] == out["state"]["growth"]["turn"]  # 额度重置


def test_seed_blank_escalates_to_hard():
    import copy
    content = copy.deepcopy(SANDBOX)
    seen = []

    class LazyLLM:
        def generate(self, prompt):
            if prompt.get("speaker_name"):
                seen.append(prompt.get("world_seed"))
                return {"beats": [{"type": "dialogue", "speaker_name": "甲", "text": "嗯。"}],
                        "world_seed": "无",
                        "affinity_delta": 0, "advance_act": False, "ending": None}
            return {}

    st = runtime.default_state()
    for _ in range(8):
        growth.tick(st)
    for i in range(4):
        out = runtime.run_turn(content, st, {"name": "我"}, f"聊聊{i}", channel="say",
                               llm=LazyLLM())
        st = out["state"]
    # 前三次软邀请被无掉, 第四次升级硬指令 (逃生舱焊死)
    assert seen[:3] == ["soft", "soft", "soft"] and seen[3] == "hard"
    assert st["growth"]["blanks"] == 4


def test_seed_char_births_via_pipeline():
    import copy
    content = copy.deepcopy(SANDBOX)

    class FaceLLM:
        def generate(self, prompt):
            if prompt.get("speaker_name"):
                return {"beats": [{"type": "dialogue", "speaker_name": "甲",
                                   "text": "那不是陈皮吗。"}],
                        "world_seed": "人物：陈皮|收保护费的瘦子",
                        "affinity_delta": 0, "advance_act": False, "ending": None}
            return {}

    st = runtime.default_state()
    for _ in range(8):
        growth.tick(st)
    out = runtime.run_turn(content, st, {"name": "我"}, "看看街上", channel="say",
                           llm=FaceLLM())
    born = [c for c in content["story"]["characters"] if c.get("name") == "陈皮"]
    assert born and born[0]["generated"] and "保护费" in born[0]["persona_text"]
    assert out["state"]["growth"]["blanks"] == 0


def test_explore_intent_hard_exit():
    import copy

    from app.engine.llm import MockLLM
    content = copy.deepcopy(SANDBOX)
    assert growth.explore_intent("我们出去走走")
    assert growth.explore_intent("随便逛逛吧")
    assert not growth.explore_intent("先四下看看这地方")   # 原地打量不是探索
    out = runtime.run_turn(content, runtime.default_state(), {"name": "我"},
                           "我们出去走走", channel="do", llm=MockLLM())
    mr = out.get("move_request")
    assert mr and mr.get("minted") and mr.get("self_go")   # 判官发明的去处, 确认条自去
    assert out["state"]["growth"]["last"] == out["state"]["growth"]["turn"]
