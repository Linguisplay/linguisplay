# -*- coding: utf-8 -*-
"""🗓 手账摘要 — 手账是工具, 不是每回合的上下文 (Yi 2026-08-09)。

Yi 的原话:「不进上下文, 就是一个工具, 然后每过一个礼拜就简单总结一次然后给上下文」。

从前: 公开行程取「将来 3 条」、笔记取前 8 条, 每一个玩家回合原样塞进主叙者的
提示词。玩家写得越多, 每回合的常驻占位越大 —— 而这些字大部分时候跟眼前这一场
戏没关系。上一轮把输入框放宽到 400 字之后, 这个占位还会成倍长。

现在: 手账原文不再进提示词。跨一个游戏周蒸一次摘要, 只有摘要进。

⚠️ 披露边界是既有法条, 摘要不许把它抹平 —— 所以摘要是【两格】不是一格:
  · plans   ← 公开行程 (told=all)。角色知道, 可以顺着关心。
  · compass ← 笔记。角色【看不见本子】, 只作叙事罗盘: 故事顺着它出牌,
              角色绝不许提及或凭空知道其中内容。
  · 私密行程 (told=none) 两格都不进 ——「绝不入戏」原样保留。
两格合成一格会让角色说出本子里的话, 那是玩家私人的东西。别合。

蒸馏走后台线程, 下一回合 apply_pending 合账 (同 profile.py 的家法: 线程绝不碰
state)。零关键路径开销。

⏱ 关于节拍: DIGEST_EVERY_DAYS=7 是照 Yi 的字面要求写的。线上实测 186 个存档里
88% 从没离开过第 1 天, 只有 2 个到过第 8 天 —— 所以这条节拍在当前的留存下几乎
不会触发, 手账实际上等于纯工具。profile.py 踩过同一个坑并改了节拍 (见那边的
DISTILL_FIRST 注释)。要让它真的响, 把节拍改成按玩家回合数或按手账变动次数。
"""
from __future__ import annotations

from typing import Any

DIGEST_EVERY_DAYS = 7   # 🗓 跨几个游戏日算「一个礼拜」
PLANS_CAP = 90          # 摘要进 prompt, 要省着花
COMPASS_CAP = 90
MATERIAL_PLANS = 20     # 送去蒸的料上限 (与日历本身的 20 条上限对齐)
MATERIAL_NOTES = 12     # 同笔记本的 12 条上限


def _diary(state: dict[str, Any]) -> dict[str, Any]:
    d = state.get("diary")
    if not isinstance(d, dict):
        d = {"week": -1, "plans": "", "compass": ""}
        state["diary"] = d
    return d


def _week(state: dict[str, Any]) -> int:
    day = int(((state.get("clock") or {}).get("day")) or 1)
    return max(0, (day - 1) // max(1, DIGEST_EVERY_DAYS))


def material(state: dict[str, Any]) -> dict[str, list[str]]:
    """要蒸的料。私密行程 (told=none) 一个字都不给 —— 它连摘要都不许进。"""
    plans = []
    for e in state.get("player_events") or []:
        if (e.get("told") or "all") != "all":
            continue
        txt = str(e.get("text") or "").strip()
        if not txt:
            continue
        plans.append(f"第{int(e.get('day', 1) or 1)}天{e.get('slot') or ''}：{txt}")
    notes = [str(n.get("text") or "").strip() for n in state.get("player_notes") or []]
    return {"plans": plans[:MATERIAL_PLANS],
            "notes": [t for t in notes if t][:MATERIAL_NOTES]}


def due(state: dict[str, Any]) -> bool:
    """该蒸了吗: 当前这一周还没蒸过, 手账里确实有料, 且上一次还没在飞。

    ⏱【第一次不等一周】——初值 week=-1, 所以玩家第一次往手账里写东西的那一拍就蒸,
    之后才是每跨一周重蒸。这是【故意的, 不是 -1 的副作用】: 88% 的存档活不过第 1 天,
    真等满七天再蒸, 手账对绝大多数玩家等于永远不进上下文。profile.py 踩过并改过
    同一个坑 (「收集要落在玩家还在的窗口里, 否则建了给谁看」)。改动此处前先重读这段。

    在飞时不点火 —— 否则线程回来之前的每一拍都会再点一次火, 一周烧掉好几次调用。
    week 只在【合账成功】时才盖章 (见 _merge), 所以蒸失败了下一拍会自己重试,
    不会白丢一整周。"""
    if state.get("diary_pending"):
        return False
    m = material(state)
    if not (m["plans"] or m["notes"]):
        return False
    return _week(state) != int(_diary(state).get("week", -1))


def plans_line(state: dict[str, Any]) -> str:
    """角色知道的那格 (公开行程的摘要)。"""
    return str(_diary(state).get("plans") or "")[:PLANS_CAP]


def compass_line(state: dict[str, Any]) -> str:
    """叙事罗盘那格 (笔记的摘要) —— 角色不许提及。"""
    return str(_diary(state).get("compass") or "")[:COMPASS_CAP]


def view(state: dict[str, Any]) -> dict[str, Any]:
    """UI/审计用: 当前摘要与它是哪一周蒸的。"""
    d = _diary(state)
    return {"plans": plans_line(state), "compass": compass_line(state),
            "week": int(d.get("week", -1)), "day": int(d.get("day", 0) or 0)}


def _merge(state: dict[str, Any], out: Any) -> bool:
    """把一次蒸馏的模型输出合进手账摘要 (只在主线程调用)。"""
    if not isinstance(out, dict):
        return False
    plans = str(out.get("plans") or "").strip()[:PLANS_CAP]
    compass = str(out.get("compass") or "").strip()[:COMPASS_CAP]
    if not (plans or compass):
        return False        # 空回执不盖章 —— 下一拍照旧重试
    d = _diary(state)
    d["plans"], d["compass"] = plans, compass
    d["week"] = _week(state)
    d["day"] = int(((state.get("clock") or {}).get("day")) or 1)
    return True


# ── ⚡ 后台蒸馏: 主线程备料, 线程只跑模型, 结果下一回合 apply_pending 合账 ──
_PENDING: dict = {}
_PENDING_CAP = 30


def distill_async(state: dict[str, Any], llm: Any) -> None:
    import threading
    import uuid
    m = material(state)
    if not (m["plans"] or m["notes"]):
        return
    payload = {"diary_digest": True, "plans": m["plans"], "notes": m["notes"],
               "prior": {"plans": plans_line(state), "compass": compass_line(state)},
               "day": int(((state.get("clock") or {}).get("day")) or 1)}
    tok = uuid.uuid4().hex[:12]
    state["diary_pending"] = tok

    def _work():
        try:
            out = llm.generate(payload) or {}
        except Exception:
            out = {}
        while len(_PENDING) >= _PENDING_CAP:
            _PENDING.pop(next(iter(_PENDING)), None)
        _PENDING[tok] = {"out": out}

    threading.Thread(target=_work, daemon=True).start()


def apply_pending(state: dict[str, Any]) -> bool:
    """回合开头收上一轮的后台蒸馏 (没好就留着下回合再收)。"""
    tok = state.get("diary_pending")
    if not tok:
        return False
    ent = _PENDING.pop(tok, None)
    if ent is None:
        return False
    state.pop("diary_pending", None)
    return _merge(state, ent.get("out"))
