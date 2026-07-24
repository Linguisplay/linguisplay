# -*- coding: utf-8 -*-
"""📔 每日回忆结算 (Yi 2026-07-25 二改: 回忆不只一种 — 通盘总结当天互动打标签,
收进小手机回忆册, 零弹窗, 翻天定时更新): 标签白名单、心里话只随心动/甜蜜、
相处太少不记、机械 rel_up 弹窗只留恋人档。"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./test_e2e.db")
os.environ.setdefault("JWT_SECRET", "test")

from app.engine import runtime  # noqa: E402

STORY = {"story": {"id": "s", "tuning": {"turns_per_slot": 1},
                   "characters": [{"id": "a", "name": "阿岚", "is_lead": True,
                                   "relation_allowed": ["stranger", "peer", "friend",
                                                        "flirt", "lover"],
                                   "home_location_id": "hall"}],
                   "acts": [{"index": 1, "title": "一"}],
                   "locations": [{"id": "hall", "name": "门厅", "detail": "x",
                                  "exits": []}]},
         "secrets": []}


def _warm_state():
    st = runtime.default_state()
    st["clock"] = {"day": 1, "slot": 2, "ticks": 0}   # slot 是索引: 2=夜
    ph = st.setdefault("phone", {"threads": {}})
    ph["threads"]["a"] = {"msgs": [
        {"from": "me", "text": "到家了吗", "at": "夜"},
        {"from": "them", "text": "刚到，给你带了糖水", "at": "夜"},
        {"from": "me", "text": "明天一起吃", "at": "夜"},
        {"from": "them", "text": "一言为定", "at": "夜"}], "unread": 0}
    return st


class NightLLM:
    def __init__(self, out=None):
        self.out = out
        self.digest_prompt = None

    def generate(self, prompt):
        if prompt.get("heart_digest"):
            self.digest_prompt = prompt
            return dict(self.out or {})
        if prompt.get("speaker_name") or prompt.get("speaker"):
            return {"beats": [{"type": "dialogue", "speaker_name": "阿岚",
                               "text": "今天就到这吧。"}], "time_skip": "next_morning",
                    "affinity_delta": 0, "advance_act": False, "ending": None}
        return {}


def test_sweet_day_books_album_card_quietly():
    llm = NightLLM({"tag": "甜蜜", "title": "糖水之约",
                    "text": "你说明天一起吃糖水，我答一言为定。",
                    "heart": "其实吃什么都行，见的是你就好。"})
    out = runtime.run_turn(STORY, _warm_state(), {"name": "我"}, "晚安", channel="say",
                           llm=llm)
    st = out["state"]
    assert out["new_day"] and llm.digest_prompt
    card = next(a for a in st["album"] if a["kind"] == "daily")
    assert card["title"].startswith("🍬甜蜜") and "糖水之约" in card["title"]
    assert "一言为定" in card["text"] and "见的是你" in card["text"]   # 心里话随卡
    assert card["rarity"] == 2
    # 零弹窗: 不发手机消息、无 moments 横幅
    assert all("见的是你" not in (m.get("text") or "")
               for m in st["phone"]["threads"]["a"]["msgs"])
    assert all(m.get("kind") != "rel_up" for m in out["moments"])


def test_funny_day_tag_no_heart_line():
    llm = NightLLM({"tag": "搞笑", "title": "滑跪名场面",
                    "text": "你踩到鱼蛋摔了个滑跪，我笑到打嗝。",
                    "heart": "这句不该出现"})
    out = runtime.run_turn(STORY, _warm_state(), {"name": "我"}, "晚安", channel="say",
                           llm=llm)
    card = next(a for a in out["state"]["album"] if a["kind"] == "daily")
    assert card["title"].startswith("🤣搞笑")
    assert "这句不该出现" not in card["text"]     # 心里话只随心动/甜蜜
    assert card["rarity"] == 1


def test_junk_tag_rejected():
    llm = NightLLM({"tag": "抽象", "title": "x", "text": "y"})
    out = runtime.run_turn(STORY, _warm_state(), {"name": "我"}, "晚安", channel="say",
                           llm=llm)
    assert all(a.get("kind") != "daily" for a in (out["state"].get("album") or []))


def test_thin_day_skips_digest():
    llm = NightLLM({"tag": "开心", "title": "x", "text": "y"})
    st = _warm_state()
    st["phone"]["threads"]["a"]["msgs"] = []
    runtime.run_turn(STORY, st, {"name": "我"}, "晚安", channel="say", llm=llm)
    assert llm.digest_prompt is None                          # 材料不够压根不问
