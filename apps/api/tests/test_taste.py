# -*- coding: utf-8 -*-
"""🧭 口味罗盘 (Yi 2026-07-22: 「了解玩家的喜好非常重要，这方面一定要很强」):
硬信号记账+指数衰减; 点击建议加倍; 样本门槛保守注入; 账号级慢沉淀+新档温启动。"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./test_e2e.db")
os.environ.setdefault("JWT_SECRET", "test")

from app.engine import runtime, taste  # noqa: E402


def test_note_decay_and_confidence_gate():
    st = {}
    taste.note(st, ["探查"])
    assert taste.top(st) == []                       # 样本不够, 保守不猜
    assert taste.prompt_line(st) == ""
    for _ in range(9):
        taste.note(st, ["探查", "冒险"])
    t = taste.top(st)
    assert t and t[0] == "探查" or t[0] == "冒险"     # 双热门都在
    assert "冒险" in t and "探查" in t
    assert "口味" in taste.prompt_line(st)
    # 衰减: 近期行为压过陈年积累
    for _ in range(30):
        taste.note(st, ["心动"])
    assert taste.top(st)[0] == "心动"


def test_click_doubles_and_junk_ignored():
    st = {}
    taste.note(st, ["探索"], clicked=True)
    taste.note(st, ["闲话"], clicked=False)
    assert st["taste"]["探索"] > st["taste"]["闲话"]
    taste.note(st, ["修仙飞升"])                      # 野类别不入账
    assert "修仙飞升" not in st["taste"]


def test_account_blend_and_seed():
    acct = {}
    run_taste = {"探查": 6.0, "心动": 2.0}
    for _ in range(50):
        acct = taste.blend_account(acct, run_taste)
    assert acct["探查"] > acct["心动"] > 0
    seed = taste.seed_from_account(acct)
    assert abs(sum(seed.values()) - taste.SEED_WEIGHT) < 0.1   # 先验总权重固定
    assert seed["探查"] > seed["心动"]
    assert taste.seed_from_account(None) == {}
    assert taste.seed_from_account({"垃圾": 3}) == {}


def test_turn_books_probe_and_click():
    story = {"story": {"id": "s",
                       "characters": [{"id": "a", "name": "甲", "is_lead": True}],
                       "acts": [{"index": 1, "title": "一"}],
                       "locations": [{"id": "hall", "name": "门厅", "detail": "x",
                                      "exits": []}]},
             "secrets": [{"id": "s1", "character_id": "a", "title": "那笔旧账",
                          "fragments": [{"id": "f1", "layer": 1, "content": "x",
                                         "retrieval_key": "旧账"}]}]}

    class PlainLLM:
        def generate(self, prompt):
            return {"beats": [{"type": "dialogue", "speaker_name": "甲", "text": "嗯。"}],
                    "affinity_delta": 0, "advance_act": False, "ending": None}

    # 追问秘密关键词 → 探查入账
    st = runtime.default_state()
    out = runtime.run_turn(story, st, {"name": "我"}, "跟我说说那笔旧账", channel="say",
                           llm=PlainLLM())
    assert out["state"]["taste"].get("探查", 0) >= 1
    # 点了上一轮的建议 chips → 当回合加倍
    st2 = runtime.default_state()
    st2["suggestions"] = ["跟我说说那笔旧账"]
    out2 = runtime.run_turn(story, st2, {"name": "我"}, "跟我说说那笔旧账", channel="say",
                            llm=PlainLLM())
    assert out2["state"]["taste"]["探查"] > out["state"]["taste"]["探查"]
    # 口味视图随档下发 (归一化)
    assert out2["state"]["taste"]


def test_curiosity_counts_without_authored_secrets():
    """沙盒无秘密也要认得出探查 (实弹: 「说说最近的怪事」曾被记成闲话)。"""
    story = {"story": {"id": "s",
                       "characters": [{"id": "a", "name": "甲", "is_lead": True}],
                       "acts": [{"index": 1, "title": "一"}],
                       "locations": [{"id": "hall", "name": "门厅", "detail": "x",
                                      "exits": []}]},
             "secrets": []}

    class PlainLLM:
        def generate(self, prompt):
            return {"beats": [{"type": "dialogue", "speaker_name": "甲", "text": "嗯。"}],
                    "affinity_delta": 0, "advance_act": False, "ending": None}

    out = runtime.run_turn(story, runtime.default_state(), {"name": "我"},
                           "跟我说说这片地界最近的怪事", channel="say", llm=PlainLLM())
    assert out["state"]["taste"].get("探查", 0) >= 1
    assert "闲话" not in out["state"]["taste"]
