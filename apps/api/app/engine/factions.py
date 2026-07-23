# -*- coding: utf-8 -*-
"""🏛 阵营声望账本 (Yi 2026-07-22: 引擎要承担更多故事类型 — 权谋/宫斗/帮派/战争的地基).

对「人」有关系双轴, 对「势力」有声望一轴: 玩家的言行让在场角色所属的阵营对TA的
观感流动, 对头阵营看在眼里反向记账。引擎记账模型报审: 带阵营的发言者每回合可报
rep_delta (-3~3), 引擎钳制入账; 声望档位以提示块注入成员的底色 (不动关系档位账 —
个人恩怨仍归双轴, 你可以被一个仇视你的阵营里的某个人偷偷喜欢着)。

Story-agnostic: 只在剧本作者写了 `story.factions`
([{id, name, detail, rivals: [id]}]) 时激活; 本模块纯函数 — runtime 持有 state。
"""
from __future__ import annotations

from typing import Any

REP_MIN, REP_MAX = -100, 100
STEP = 3          # 单回合单发言者的报审钳制
RIPPLE_DIV = 2    # 对头反向记账: 你帮了这边, 那边迟早听说

# floors desc: (floor, zh, en)
BANDS = [(60, "器重", "esteemed"), (25, "接纳", "accepted"), (-24, "中立", "neutral"),
         (-59, "冷眼", "cold-shouldered"), (-101, "仇视", "hostile")]


def cfg(content: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for f in (content.get("story") or {}).get("factions") or []:
        if not isinstance(f, dict):
            continue
        fid = str(f.get("id") or "").strip()
        name = str(f.get("name") or "").strip()
        if not fid or not name:
            continue
        out.append({"id": fid, "name": name[:16],
                    "detail": str(f.get("detail") or "").strip()[:120],
                    "rivals": [str(r).strip() for r in (f.get("rivals") or [])
                               if str(r).strip()]})
    return out


def by_id(content: dict[str, Any], fid: str) -> dict[str, Any] | None:
    return next((f for f in cfg(content) if f["id"] == fid), None)


def of_char(content: dict[str, Any], char: dict[str, Any] | None) -> dict[str, Any] | None:
    fid = str((char or {}).get("faction_id") or "").strip()
    return by_id(content, fid) if fid else None


def rep(state: dict[str, Any], fid: str) -> int:
    try:
        return int((state.get("reputation") or {}).get(fid, 0))
    except (TypeError, ValueError):
        return 0


def band(value: int, zh: bool = True) -> str:
    for floor, b_zh, b_en in BANDS:
        if value >= floor:
            return b_zh if zh else b_en
    return BANDS[-1][1] if zh else BANDS[-1][2]


def apply_delta(state: dict[str, Any], content: dict[str, Any], fid: str,
                delta: int) -> dict[str, int]:
    """报审入账: 钳制 ±STEP; 对头阵营反向记一半。返回 {fid: 实际入账} 供审计。"""
    fac = by_id(content, fid)
    if fac is None or not delta:
        return {}
    d = max(-STEP, min(STEP, int(delta)))
    book = state.setdefault("reputation", {})
    applied: dict[str, int] = {}
    book[fid] = max(REP_MIN, min(REP_MAX, rep(state, fid) + d))
    applied[fid] = d
    ripple = -(abs(d) // RIPPLE_DIV) * (1 if d > 0 else -1)
    if ripple:
        for rv in fac["rivals"]:
            if by_id(content, rv) is not None:
                book[rv] = max(REP_MIN, min(REP_MAX, rep(state, rv) + ripple))
                applied[rv] = ripple
    return applied


def view(content: dict[str, Any], state: dict[str, Any]) -> list[dict[str, Any]]:
    """UI 面: 玩家已经在江湖上有了名声的阵营 (rep 非零), 按绝对值排序。"""
    out = []
    for f in cfg(content):
        v = rep(state, f["id"])
        if v:
            out.append({"id": f["id"], "name": f["name"], "value": v, "label": band(v)})
    out.sort(key=lambda x: -abs(x["value"]))
    return out


def block(content: dict[str, Any], state: dict[str, Any],
          char: dict[str, Any] | None, zh: bool = True) -> str:
    """发言者的阵营提示块: 归属 + 玩家在本阵营的风评底色 (+对头传闻)。"""
    fac = of_char(content, char)
    if fac is None:
        return ""
    v = rep(state, fac["id"])
    b = band(v, zh)
    if zh:
        line = (f"【你的阵营】你属于「{fac['name']}」"
                + (f"（{fac['detail']}）" if fac["detail"] else "") + "。")
        if v:
            line += (f"对方在你们阵营的风评是「{b}」——这决定你待TA的底色、给不给方便、"
                     "说话留几分；个人交情可以偏离这个底色，但你心里清楚立场在哪。")
        else:
            line += "对方在你们这儿还没什么名声，按陌生的规矩来。"
        heard = [f"「{rf['name']}」那边对TA{('有好话' if rep(state, rf['id']) > 0 else '有怨言')}"
                 for rf in (by_id(content, r) for r in fac["rivals"]) if rf
                 for _ in [0] if abs(rep(state, rf["id"])) >= 25]
        if heard:
            line += "你也有耳闻：" + "；".join(heard) + "。"
        return line
    line = f"[Your faction] You belong to \"{fac['name']}\"."
    if v:
        line += f" The player's standing with your faction: \"{b}\" — it colors how you treat them."
    return line
