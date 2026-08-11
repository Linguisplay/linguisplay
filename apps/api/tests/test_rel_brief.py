# -*- coding: utf-8 -*-
"""🫂 好感度的白话呈现 (Yi 拍板 2026-08-11): 主界面不出数字, 关系网里给一段
【按上下文总结】的文字 —— 有过程感 (从X到Y), 零数字, 账本指纹缓存 (关系没变
不重写), 模型断供走确定性兜底。builder 在 relationships.rel_brief。
"""

import os

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./test_e2e.db")
os.environ.setdefault("JWT_SECRET", "test")

import re  # noqa: E402

from app.engine import relationships  # noqa: E402


def _mat(feeling="有点在意你", log=None, tags=None):
    return {"mode_name": "暧昧对象", "feeling": feeling, "why": "昨晚你替TA挡了话头",
            "tags": tags or ["守约之交"],
            "log": log if log is not None else ["初次见面", "你们成了「朋友」", "如约赴了茶馆之约"]}


class SpyLLM:
    def __init__(self, reply=None):
        self.calls = 0
        self.reply = reply

    def generate(self, prompt):
        self.calls += 1
        return {"brief": self.reply} if self.reply else {}


def test_fallback_is_deterministic_and_numberless():
    st = {}
    text = relationships.rel_brief(st, "b", _mat(), SpyLLM(), "zh")
    assert text and "暧昧对象" in text
    assert not re.search(r"\d", text), "拍板：好感呈现零数字"


def test_llm_path_cached_by_fingerprint():
    st = {}
    spy = SpyLLM(reply="从初见的客气，到肯把没说完的话留给你。")
    t1 = relationships.rel_brief(st, "b", _mat(), spy, "zh")
    assert "没说完的话" in t1 and spy.calls == 1
    # 素材没变 → 不再烧调用
    t2 = relationships.rel_brief(st, "b", _mat(), spy, "zh")
    assert t2 == t1 and spy.calls == 1
    # 大事记长了 → 指纹变 → 重写
    relationships.rel_brief(st, "b", _mat(log=["初次见面", "大吵一架"]), spy, "zh")
    assert spy.calls == 2


def test_no_budget_returns_fallback_without_caching():
    st = {}
    spy = SpyLLM(reply="这句不该被调用到")
    t = relationships.rel_brief(st, "b", _mat(), spy, "zh", allow_llm=False)
    assert t and spy.calls == 0
    # 预算回来后要能升级成 LLM 版（兜底不许把缓存位占死）
    t2 = relationships.rel_brief(st, "b", _mat(), spy, "zh")
    assert spy.calls == 1 and t2 != t


def test_llm_numbers_get_scrubbed_to_fallback():
    """模型不听话写了数字 → 弃用，走兜底（数字黑箱是硬约束不是措辞建议）。"""
    st = {}
    spy = SpyLLM(reply="好感度大概72分，快到恋人了")
    t = relationships.rel_brief(st, "b", _mat(), spy, "zh")
    assert "72" not in t


def test_relweb_edges_carry_summary():
    from fastapi.testclient import TestClient

    from app.db import Base, engine
    from app.main import app
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    API = "/api/v1"
    with TestClient(app) as c:
        c.post(f"{API}/auth/signup", json={"email": "rb@x.com", "password": "password1",
                                           "dob": "1990-01-01", "accepted_tos": True})
        story = c.post(f"{API}/stories", json={
            "title": "RelBrief", "visibility": "public",
            "characters": [{"id": "n1", "name": "掌柜", "is_lead": True}],
            "acts": [{"index": 1, "title": "一"}],
        }).json()
        c.post(f"{API}/stories/{story['id']}/publish")
        p = c.post(f"{API}/personas", json={"name": "Ash"}).json()
        run = c.post(f"{API}/runs", json={"story_id": story["id"],
                                          "persona_id": p["id"]}).json()
        c.post(f"{API}/runs/{run['id']}/play", json={"input": "你好", "channel": "say"})
        web = c.get(f"{API}/runs/{run['id']}/relweb").json()
        assert web["player"], "见了面就有玩家边"
        for edge in web["player"]:
            assert (edge.get("summary") or "").strip(), "每条玩家边都要有白话总结"
            assert not re.search(r"\d", edge["summary"])
