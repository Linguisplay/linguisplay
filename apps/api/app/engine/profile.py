# -*- coding: utf-8 -*-
"""🪞 玩家档案 (活世界 P2): AI 角色针对当前玩家建立 portfolio.

两层账本, 认知有边界 (Yi 的法条: 各角色只知道自己见证的):
  facts    — 引擎眼中的玩家习惯/偏好/雷点 (跨角色, 喂给世界心跳与事件个性化,
             不直接进对白 — 角色不开上帝视角)
  by_char  — 每个角色各自相处出来的「TA眼中的你」(只有在场见证过的角色才更新,
             注入该角色自己的对白 prompt)

蒸馏节拍: 每 DISTILL_EVERY 个玩家真实回合一次 (廉价调用, 失败静默, 下轮再试);
模型只负责措辞, 见证名单由引擎裁定。
"""
from __future__ import annotations

from typing import Any

DISTILL_EVERY = 8      # 玩家真实回合间隔 (说/做才算, 观剧/上帝位不算)
FACTS_CAP = 6
IMPRESSION_CAP = 60    # 单角色印象长度上限 (进 prompt, 要省着花)


def _prof(state: dict[str, Any]) -> dict[str, Any]:
    p = state.get("profile")
    if not isinstance(p, dict):
        p = {"facts": [], "by_char": {}, "turns": 0}
        state["profile"] = p
    return p


def impression_of(state: dict[str, Any], cid: str | None) -> str:
    """这个角色相处出来的玩家印象 (没有=空串, prompt 侧自然省位)."""
    if not cid:
        return ""
    ent = (_prof(state).get("by_char") or {}).get(cid) or {}
    return str(ent.get("text") or "")[:IMPRESSION_CAP]


def facts_of(state: dict[str, Any]) -> list[str]:
    return [str(f) for f in (_prof(state).get("facts") or [])][:FACTS_CAP]


def note_turn(state: dict[str, Any]) -> bool:
    """记一个玩家真实回合; 到蒸馏节拍返回 True (调用方负责真的去蒸)."""
    p = _prof(state)
    p["turns"] = int(p.get("turns") or 0) + 1
    return p["turns"] % DISTILL_EVERY == 0


def distill(content: dict[str, Any], state: dict[str, Any],
            recent_lines: list[str], witnesses: list[dict[str, Any]],
            llm: Any) -> bool:
    """一次蒸馏: 近期对话 → facts 增量合并 + 在场角色的印象更新.
    witnesses = [{id, name}] — 引擎裁定的见证名单, 模型无权越界."""
    if not witnesses and not recent_lines:
        return False
    p = _prof(state)
    prior = {"facts": facts_of(state),
             "impressions": {w["id"]: impression_of(state, w["id"])
                             for w in witnesses if w.get("id")}}
    try:
        out = llm.generate({"player_profile": True,
                            "recent": [str(x)[:120] for x in recent_lines[-16:]],
                            "prior": prior,
                            "witnesses": [{"id": w.get("id"), "name": w.get("name")}
                                          for w in witnesses if w.get("id")]}) or {}
    except Exception:
        return False
    if not isinstance(out, dict):
        return False
    facts = [str(f).strip()[:40] for f in (out.get("facts") or []) if str(f).strip()]
    if facts:
        p["facts"] = facts[:FACTS_CAP]
    allowed = {w.get("id") for w in witnesses}
    imps = out.get("impressions") or {}
    if isinstance(imps, dict):
        day = int(((state.get("clock") or {}).get("day")) or 1)
        for cid, txt in imps.items():
            t = str(txt or "").strip()[:IMPRESSION_CAP]
            if cid in allowed and t:   # 认知边界: 没见证过的角色不许有印象
                p.setdefault("by_char", {})[cid] = {"text": t, "day": day}
    return True
