# -*- coding: utf-8 -*-
"""💘 心动系统批次2 (Spec 2026-07-25): E 记忆回调 (真账素材+验真+防敷衍升级)
F 推拉节拍 (相位归引擎) J 负面清单 (按档查表+称呼上限)。"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./test_e2e.db")
os.environ.setdefault("JWT_SECRET", "test")

from app.engine import relationships as R  # noqa: E402
from app.engine import runtime  # noqa: E402

STORY = {"story": {"id": "s", "tuning": {"callback_every": 2},
                   "characters": [{"id": "a", "name": "甲", "is_lead": True,
                                   "relation_allowed": ["stranger", "peer", "friend",
                                                        "flirt", "lover"],
                                   "home_location_id": "hall"}],
                   "acts": [{"index": 1, "title": "一"}],
                   "locations": [{"id": "hall", "name": "门厅", "detail": "x",
                                  "exits": []}]},
         "secrets": []}


def _warm():
    st = runtime.default_state()
    st["growth"] = {"turn": 5, "last": 0, "blanks": 0}
    runtime.rel_log(st, "a", 1, "gift", "雨夜你把伞塞给了TA。")
    runtime.rel_log(st, "a", 1, "talk", "TA说过最怕打雷。")
    return st


def test_callback_material_is_real_and_verified():
    seen = {}

    class WeaveLLM:
        def generate(self, prompt):
            if prompt.get("speaker_name") or prompt.get("speaker"):
                seen["cb"] = prompt.get("callback")
                return {"beats": [{"type": "dialogue", "speaker_name": "甲",
                                   "text": "还记得雨夜你把伞塞给我，我到现在没还。"}],
                        "callback_done": "雨夜你把伞塞给我",
                        "affinity_delta": 0, "advance_act": False, "ending": None}
            return {}

    st = _warm()
    out = runtime.run_turn(STORY, st, {"name": "我"}, "在想什么", channel="say",
                           llm=WeaveLLM())
    # 素材来自真实账本 (rel_log 旧条目优先, 掐掉最新)
    assert "把伞塞给" in seen["cb"]["material"]
    # 验真通过 → 账本重置 + 素材入 used 不复读
    cb = out["state"]["callback"]
    assert cb["blanks"] == 0 and cb["last"] == out["state"]["growth"]["turn"]
    assert any("伞" in u for u in cb["used"])


def test_callback_lie_counts_as_blank_and_escalates():
    seen = []

    class LiarLLM:
        def generate(self, prompt):
            if prompt.get("speaker_name") or prompt.get("speaker"):
                seen.append((prompt.get("callback") or {}).get("mode"))
                return {"beats": [{"type": "dialogue", "speaker_name": "甲", "text": "嗯。"}],
                        "callback_done": "我们看过流星雨",   # 拍里根本没有这句 → 谎报
                        "affinity_delta": 0, "advance_act": False, "ending": None}
            return {}

    st = _warm()
    for i in range(4):
        st["growth"]["turn"] = 5 + i
        out = runtime.run_turn(STORY, st, {"name": "我"}, f"聊聊{i}", channel="say",
                               llm=LiarLLM())
        st = out["state"]
    assert st["callback"]["blanks"] == 4          # 谎报按无计
    assert seen[3] == "hard"                      # 连续敷衍 → 升硬指令


def test_pushpull_sequence_and_negatives():
    pp = {}
    phases = [R.pushpull_tick(pp, True, give=2, hold=1) for _ in range(7)]
    assert phases == ["give", "give", "hold", "comp", "give", "give", "hold"]
    assert R.pushpull_tick({}, False) == ""       # 非暧昧不激活
    # 负面清单: 档位称呼上限 + 表白禁令随档
    nf = R.negative_list("flirt")
    assert "宝宝" in nf and "摊牌式表白" in nf
    nl = R.negative_list("lover")
    assert "摊牌式表白" not in nl                  # 恋人档解禁表白
    assert "查户口" in R.negative_list("stranger")


def test_negatives_ride_every_speaker_prompt():
    seen = {}

    class NLLm:
        def generate(self, prompt):
            if prompt.get("speaker_name") or prompt.get("speaker"):
                seen["neg"] = prompt.get("negatives")
                return {"beats": [{"type": "dialogue", "speaker_name": "甲", "text": "嗯。"}],
                        "affinity_delta": 0, "advance_act": False, "ending": None}
            return {}

    runtime.run_turn(STORY, runtime.default_state(), {"name": "我"}, "你好",
                     channel="say", llm=NLLm())
    assert seen["neg"] and "绝不许做" in seen["neg"]


def test_disclosure_reciprocity_next_turn():
    """🎁 Spec G: 玩家开窗 → 下一轮主答者收到按档查表的回礼指令。"""
    seen = []

    class DLLm:
        def generate(self, prompt):
            if prompt.get("speaker_name") or prompt.get("speaker"):
                seen.append(prompt.get("disclose"))
                return {"beats": [{"type": "dialogue", "speaker_name": "甲", "text": "嗯。"}],
                        "affinity_delta": 0, "advance_act": False, "ending": None}
            return {}

    st = runtime.default_state()
    out = runtime.run_turn(STORY, st, {"name": "我"}, "我小时候差点淹死在河里",
                           channel="say", llm=DLLm())
    st = out["state"]
    assert seen[0] is None and st.get("owe_disclosure")       # 本轮记账
    out2 = runtime.run_turn(STORY, st, {"name": "我"}, "所以我怕水", channel="say",
                            llm=DLLm())
    assert seen[1] and "偏好" in seen[1]                       # 下轮回礼 (stranger 档浅层)
    assert not out2["state"].get("owe_disclosure")             # 债清 (pop)
    assert "偏好" not in (seen[2] if len(seen) > 2 else "x")   # 不复发


def test_reach_out_is_variable_ratio_with_cooldown():
    """🎰 Spec H: 主动发起是掷出来的 — 永不保证; 单角色冷却防轰炸。"""
    import copy

    class PulseLLM:
        def generate(self, prompt):
            if prompt.get("away_pulse") or prompt.get("compose"):
                return {"msgs": ["路过糖水铺想起你了"]}
            return {}

    story = copy.deepcopy(STORY)
    base = runtime.default_state()
    base["met_ids"] = ["a"]
    base["rel"] = {"a": {"closeness": 50, "romance": 70}}     # lover 档 p=0.75
    base["clock"] = {"day": 5, "slot": 0, "ticks": 0}
    hits = 0
    for seed in range(30):
        st = copy.deepcopy(base)
        runtime._rng.seed(seed)
        out = runtime.offline_pulse(story, st, set(), 6.0, PulseLLM())
        hits += 1 if out else 0
        if out:
            assert st["initiate"]["a"]["day"] == 5             # 冷却入账
            # 冷却期内再来一次 → 必不发
            assert runtime.offline_pulse(story, st, set(), 6.0, PulseLLM()) == []
    assert 8 <= hits <= 29                                     # 概率发, 永不保证也永不为零
