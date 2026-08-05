# -*- coding: utf-8 -*-
"""🎼 节奏改造批次1 (Spec 2026-07-25): A 情绪→节奏带查表 B 沉默权阶梯
C 手机形状+【已读】记账 D deliver_at 延迟投递。回归项: 被搭话空白不得复活。"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./test_e2e.db")
os.environ.setdefault("JWT_SECRET", "test")

from app.engine import runtime  # noqa: E402

STORY = {"story": {"id": "s", "tuning": {}, "phone": {"enabled": True},
                   "characters": [{"id": "a", "name": "甲", "is_lead": True,
                                   "home_location_id": "hall"}],
                   "acts": [{"index": 1, "title": "一"}],
                   "locations": [{"id": "hall", "name": "门厅", "detail": "x",
                                  "exits": []}]},
         "secrets": []}


def test_pace_band_table():
    st = {}
    assert runtime.pace_band(st, {})["band"] == "default"
    st["bgm_led"] = {"track": "tense2"}
    assert runtime.pace_band(st, {})["band"] == "taut"       # 变奏尾号剥掉
    st["bgm_led"] = {"track": "warm"}
    assert runtime.pace_band(st, {})["band"] == "open"
    st["bgm_led"] = {"track": "romantic"}
    assert runtime.pace_band(st, {})["band"] == "charged"
    st["bgm_led"] = {}
    st["heat"] = {"stage": 1}
    assert runtime.pace_band(st, {})["band"] == "charged"    # 亲密硬状态压表
    # tuning 整表覆盖
    st2 = {"bgm_led": {"track": "tense"}}
    out = runtime.pace_band(st2, {"pace_bands": {"taut": {"line": "只许一个字"}}})
    assert out["line"] == "只许一个字"


def test_silence_ladder_and_streak():
    seen = []

    class QuietLLM:
        def generate(self, prompt):
            if prompt.get("speaker_name") or prompt.get("speaker"):
                seen.append(bool(prompt.get("must_speak")))
                return {"beats": [{"type": "description", "speaker_name": None,
                                   "text": "他没应声，指节在桌沿敲了敲。"}],
                        "affinity_delta": 0, "advance_act": False, "ending": None}
            return {}

    st = runtime.default_state()
    out = runtime.run_turn(STORY, st, {"name": "我"}, "说话啊", channel="say",
                           llm=QuietLLM())
    st = out["state"]
    # 第一轮: 允许沉默 (must_speak False), 沉默计数入账
    assert seen[0] is False
    assert st["char_sim"]["a"]["silent_streak"] == 1
    # 第二轮: 连续守卫 — must_speak 升 True (回归项: 空白不得复活)
    runtime.run_turn(STORY, st, {"name": "我"}, "还不说？", channel="say", llm=QuietLLM())
    assert seen[1] is True


def test_probed_char_must_speak():
    story = {"story": {**STORY["story"]},
             "secrets": [{"id": "s1", "character_id": "a", "title": "旧账",
                          "fragments": [{"id": "f1", "layer": 1, "content": "x",
                                         "retrieval_key": "旧账"}]}]}
    seen = []

    class Q2(object):
        def generate(self, prompt):
            if prompt.get("speaker_name") or prompt.get("speaker"):
                seen.append(bool(prompt.get("must_speak")))
                return {"beats": [{"type": "dialogue", "speaker_name": "甲", "text": "……问这个干嘛。"}],
                        "affinity_delta": 0, "advance_act": False, "ending": None}
            return {}

    runtime.run_turn(story, runtime.default_state(), {"name": "我"}, "说说那笔旧账",
                     channel="say", llm=Q2())
    assert seen[0] is True                                    # 秘密被戳 → 阶梯顶格必答


def test_phone_read_ignored_books_and_delivers_later():
    class ReadLLM:
        def __init__(self):
            self.prompts = []

        def generate(self, prompt):
            if prompt.get("phone_reply"):
                self.prompts.append(prompt)
                if len(self.prompts) == 1:
                    return {"msgs": ["【已读：在气你昨天的事】", "稍后：昨天是我不对。"]}
                return {"msgs": ["嗯，消气了。"]}
            return {}

    llm = ReadLLM()
    st = runtime.default_state()
    st["met_ids"] = ["a"]
    st["clock"] = {"day": 1, "slot": 0, "ticks": 0}
    view = runtime.phone_send(STORY, st, {"name": "我"}, "a", "昨晚怎么不理我", llm=llm)
    th = st["phone"]["threads"]["a"]
    # 晾着: 已读灰条入账、补偿进 pending、正式消息里没有补偿文本
    assert th["last_read"]["reason"] == "在气你昨天的事"
    assert th["msgs"][-1].get("kind") == "read"
    assert th["pending"] and "我不对" in th["pending"][0]["text"]
    assert view.get("replied") in (False, None) or not view.get("replied")
    # 时间推进跨过到期时刻 → 投递 + 未读 + 债清
    # ⏱ 2026-08-05: 待发从【时段轴】换成了【墙钟轴】—— 时段轴在 real_clock 下等于
    #    1 分钟到 11 小时的不可控随机, 在虚构钟的本里干脆冻住不动 (死信箱)。
    #    所以这里推进的是墙钟, 不再是 clock.slot。
    for _p in th["pending"]:
        _p["due_ts"] = runtime._wall_ts() - 1
    moved = runtime.deliver_due_phone(STORY, st)
    assert moved == 1
    assert th["msgs"][-1]["text"] == "昨天是我不对。"
    assert th["unread"] >= 1 and "last_read" not in th
    # 追问一致性: 晾着期间的下一条, prompt 带上次已读原因
    st2 = runtime.default_state()
    st2["met_ids"] = ["a"]
    llm2 = ReadLLM()
    runtime.phone_send(STORY, st2, {"name": "我"}, "a", "怎么不理我", llm=llm2)
    runtime.phone_send(STORY, st2, {"name": "我"}, "a", "你到底怎么了", llm=llm2)
    assert llm2.prompts[1].get("last_ignored") == "在气你昨天的事"
