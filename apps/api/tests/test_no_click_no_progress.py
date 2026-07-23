# -*- coding: utf-8 -*-
"""⚖️ 无点击不推进 (Yi 2026-07-14 拍板): 玩家没点, 对话就不许走.

这是这条法条的执法点. 四条底线:
  ① 心跳 world_tick 在结构上拿不到 LLM (签名里没有) — 跑完不落一拍、不发一条
     短信、不写一个字的戏文; 词债只押不演 (living_news.pend)
  ② 押下的词债只在玩家亲手点开的回合由 settle_pending 补演
  ③ 命运岔口默认不代选 (fate_auto_resolve=0), 世界事件默认不自燃 (world_event_every=0)
  ④ /leave 的 beacon 只暂存 parting_pending — 一拍不加 (test_hooks.py 管 HTTP 层),
     /play 的 drive 观剧拍有服务端最小间隔, client_turn_id 幂等键挡网络层重放
新功能破了这里的断言 = 破了法条 — 先去 memory 里把 Yi 的原话读一遍再动手.
"""
import inspect
import os

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./test_e2e.db")
os.environ.setdefault("JWT_SECRET", "test")

from app.engine import living, runtime  # noqa: E402
from app.engine.llm import MockLLM  # noqa: E402

STORY = {
    "story": {"id": "s", "tuning": {"turns_per_slot": 1, "phone": 1},
              "characters": [{"id": "a", "name": "甲", "is_lead": True},
                             {"id": "b", "name": "乙"}],
              "acts": [{"index": 1, "title": "一"}],
              "locations": [{"id": "hall", "name": "门厅", "detail": "一盏吊灯",
                             "exits": []}]},
    "secrets": [],
}


class BombLLM:
    """无点击路径上的 LLM 引信: 谁点着它谁违法."""

    def generate(self, prompt):
        raise AssertionError(f"no-click path called the LLM: {sorted(prompt)[:4]}")


def _staged_state():
    """一个万事俱备的心跳现场: 过期的约 + 可邀约的暖角色 + 满月纪念日."""
    st = runtime.default_state()
    st["met_ids"] = ["a", "b"]
    st["contact_ids"] = ["a", "b"]
    st["promises"] = [{"char_id": "a", "char_name": "甲", "what": "夜里聊聊",
                       "day": 1, "slot": "夜", "location_id": "hall",
                       "romantic": True, "status": "open"}]
    st["clock"] = {"day": 1, "slot": 0, "turns_in_slot": 0}
    living.set_living(st, True)
    return st


def test_world_tick_structurally_cannot_speak():
    # ① 签名里没有 llm — 心跳想写词都没有笔
    assert "llm" not in inspect.signature(living.world_tick).parameters


def test_heartbeat_stages_everything_performs_nothing():
    st = _staged_state()
    out = living.world_tick(STORY, st)
    assert out["advanced"]
    # 状态数学落了账: 时钟走了, 约翻了, 分掉了
    assert st["clock"]["day"] == 2
    assert st["promises"][0]["status"] == "missed"
    # 但一个字都没写、一条短信都没发、一拍都没落
    assert not (st.get("phone") or {}).get("threads")
    assert not (st.get("rel_log") or {})
    staged = [n for n in st["living_news"] if n.get("pend")]
    assert staged, "词债必须押在 pend 里"
    assert all(not n.get("text") or n["kind"] == "anniv" for n in staged)
    # 没补演的词债, 播报口也不吐 (serve 不许把空戏文当新闻讲)
    assert living.serve_living_news(dict(st)) == []


def test_word_debts_settle_only_on_click_turn():
    st = _staged_state()
    living.world_tick(STORY, st)
    events = living.settle_pending(STORY, st, MockLLM())
    # 点击回合里: 戏文写了、短信到了、约订上了
    assert any("你没来" in e["text"] for e in (st.get("rel_log") or {}).get("a") or [])
    assert events and ((st.get("phone") or {}).get("threads") or {})
    assert not [n for n in st["living_news"] if n.get("pend")], "词债结清"
    assert living.serve_living_news(st), "结清后播报口才开"


def test_turn_pipeline_never_settles_on_think():
    """think 是内心戏不是对世界的点击推进 — 词债在 think 回合按兵不动."""
    st = _staged_state()
    living.world_tick(STORY, st)
    out = runtime.run_turn(STORY, st, {"name": "我"}, "（想想）", channel="think",
                           llm=MockLLM())
    assert [n for n in out["state"]["living_news"] if n.get("pend")], \
        "think 回合不许补演词债"


def test_fate_and_world_event_default_off():
    # ③ 引擎出厂默认: 玩家没点的选择不代点, 事件不自燃
    assert runtime.DEFAULT_TUNING["fate_auto_resolve"] == 0
    assert runtime.DEFAULT_TUNING["world_event_every"] == 0


def test_pending_fate_waits_forever_by_default():
    st = runtime.default_state()
    st["pending_choice"] = {"kind": "fate", "prompt": "杀还是放？", "expires": 1,
                            "options": [{"id": "f1", "label": "杀"},
                                        {"id": "f2", "label": "放"}]}
    st["fate_effects"] = {"f1": {"kind": "story", "target": "", "mandate": "x"},
                          "f2": {"kind": "story", "target": "", "mandate": "y"}}
    out = runtime.run_turn(STORY, st, {"name": "我"}, "先不选", channel="say",
                           llm=MockLLM())
    # 岔口原地等着, 宽限不倒数, 引擎没替玩家落子
    pc = out["state"].get("pending_choice")
    assert pc and pc["kind"] == "fate" and pc["expires"] == 1
    assert not any("命运替你落了子" in (b.get("text") or "") for b in out["beats"])


def test_heartbeat_pass_runs_llm_free(monkeypatch):
    """调度器整条链路 (runs.living_heartbeat_pass → world_tick) 不许摸 LLM:
    把 get_llm 换成引信, 心跳照样跑完."""
    from app.db import Base, engine
    from app.routers import runs as runs_router
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(runs_router, "get_llm", lambda: BombLLM())
    monkeypatch.setattr("app.engine.llm.get_llm", lambda: BombLLM())
    # 没有到期 run 也要走完整个 pass — 证明路径上没有任何 LLM 依赖
    assert isinstance(runs_router.living_heartbeat_pass(), int)
