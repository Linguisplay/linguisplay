# -*- coding: utf-8 -*-
"""🌱 世界生长预算 (Yi 2026-07-25 拍板: 判官上线后 58 回合零铸造 — 删硬程序时把
节拍器也删了)。三权分立: 引擎管什么时候长 (这里), 模型管长什么 (world_seed 报审),
判官管长得对不对 (地名判官/名字守卫/配额原样在岗)。

Yi 钉死的四条:
① 防敷衍升级档 — 到期是软邀请 (可填无), 连续 BLANK_ESCALATE 次填无后升级硬指令
   (去掉逃生舱); 连续无次数入账可观测。
② 场景挂起 — 对峙/亲密/战斗/结案这类高张力场景里到期状态挂起顺延, 计数照走,
   场景一换立即放行 (硬塞新面孔判官挑不出毛病, 叙事上是灾难)。
③ 双通道共享额度 — 预算铸造/提及即立档/探索意图/人物出生, 任何通道的新实体都
   调 note_mint 重置同一本账, 总量天然守住。
④ 三数监控 — due/blank/mint/reject 全打 metrics ("growth" 事件), 目标区间:
   沙盒 5-8 回合一个新实体, 判官否决率 <30% (否决率高 = 模型在压力下产垃圾)。

口味输入合宪性: taste 罗盘全确定性 (硬信号计数, 零 LLM) — 节奏归引擎成立。
"""
from __future__ import annotations

import re
from typing import Any

BASE_PERIOD = 8       # 沙盒缺省: 每 8 回合到期 (tuning.growth_every 可调, 0=关)
TASTE_BONUS = 2       # 探索口味在册 → 周期 -2 (确定性信号)
BLANK_ESCALATE = 3    # 连续填无 3 次后, 第 4 次升级硬指令
# 高张力/封闭场景 (state.scene.mood 英文键): 到期挂起
_HOT_MOODS = {"tense", "battle", "eerie", "romantic"}

# 探索意图 (无目的地的「带我出去」): 硬出口的确定性识别
_EXPLORE_RE = re.compile(
    r"出去(走走|转转|逛逛|晃晃|溜达)|随便(逛逛|走走|转转)|到处(看看|走走|逛逛)"
    r"|四处(走走|逛逛|转转)|去外面(转|走|逛)|出门(转转|走走|逛逛)")


def _g(state: dict[str, Any]) -> dict[str, Any]:
    g = state.get("growth")
    if not isinstance(g, dict):
        g = {"turn": 0, "last": 0, "blanks": 0}
        state["growth"] = g
    return g


def tick(state: dict[str, Any]) -> None:
    _g(state)["turn"] = int(_g(state).get("turn", 0) or 0) + 1


def scene_hot(state: dict[str, Any]) -> bool:
    """② 场景挂起判定 — 全确定性: 场面情绪/亲密阶段/压强/未决抉择/有兽在场。"""
    if ((state.get("scene") or {}).get("mood") or "") in _HOT_MOODS:
        return True
    heat = state.get("heat")
    if isinstance(heat, dict) and int(heat.get("stage", 0) or 0) >= 1:
        return True
    if int(state.get("pressure", 0) or 0) >= 40:
        return True
    if state.get("pending_choice"):
        return True
    return False


def period_of(content: dict[str, Any], state: dict[str, Any],
              taste_top: list[str] | None) -> int:
    """预算周期: 沙盒缺省 BASE_PERIOD; 授权本缺省关闭 (策展的世界不乱长),
    除非作者在 tuning 里显式给了 growth_every。探索口味确定性加速。"""
    story = (content.get("story") or {})
    raw = (story.get("tuning") or {}).get("growth_every")
    if raw is not None:
        try:
            period = int(raw)
        except (TypeError, ValueError):
            period = 0
    else:
        sb = story.get("sandbox") or {}
        period = BASE_PERIOD if (isinstance(sb, dict) and sb.get("enabled")) else 0
    if period and "探索" in (taste_top or []):
        period = max(3, period - TASTE_BONUS)
    return max(0, period)


def due(content: dict[str, Any], state: dict[str, Any],
        taste_top: list[str] | None) -> str:
    """"" = 不到期/挂起; "soft" = 软邀请 (可填无); "hard" = 硬指令 (连续敷衍后)。"""
    period = period_of(content, state, taste_top)
    if not period:
        return ""
    g = _g(state)
    if int(g.get("turn", 0)) - int(g.get("last", 0)) < period:
        return ""
    if scene_hot(state):
        return ""   # 🧊 挂起: 计数照走, 场景一换立即到期
    return "hard" if int(g.get("blanks", 0)) >= BLANK_ESCALATE else "soft"


def note_blank(state: dict[str, Any]) -> int:
    """①: 填无入账, 返回连续次数 (可观测指标第一位)。"""
    g = _g(state)
    g["blanks"] = int(g.get("blanks", 0) or 0) + 1
    return g["blanks"]


def note_mint(state: dict[str, Any]) -> None:
    """③: 任何通道的新实体 (预算/提及/探索/出生) 共享这本额度。"""
    g = _g(state)
    g["last"] = int(g.get("turn", 0) or 0)
    g["blanks"] = 0


def explore_intent(text: str | None) -> bool:
    return bool(_EXPLORE_RE.search(text or ""))
