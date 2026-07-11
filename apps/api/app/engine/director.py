# -*- coding: utf-8 -*-
"""🎬 规则导演 v1 — 引擎状态直接驱动演出 (零 LLM、零延迟).

分工: 剧情节奏归恐怖引擎的张弛导演 (pressure/dooms), 视听表达归这里 —
每拍注记 {sfx 音效插点 / fx 惊吓白闪 / expr 表情位}, 随 beat 直接下发;
每回合一张演出单 {bgm 选曲 / tint 色调}, 以 direct 事件收尾下发.

法度: 规则全部确定性; 素材缺失客户端静默降级; 一回合白闪至多一次,
同名音效不重复 (阈下适应 — 吓人的东西响两次就不吓人了)。
"""
from __future__ import annotations

import re
from typing import Any

from .scene import _SFX

# 惊吓语法: 突发副词 + 撞击/断灭动词, 或独立的高声压词 → 白闪
_FLASH_RE = re.compile(
    r"尖叫|惨叫|巨响|炸裂|轰然"
    r"|(猛地|猛然|骤然|突然|陡然|倏地)[^。！？\n]{0,12}(响|撞|砸|扑|抓|拽|拍|摔|碎|灭|熄|断|裂|窜|闪|亮)")
# 心理惊悚的底噪: 没有实体音效可插时, 心跳声顶上
_HEARTBEAT_RE = re.compile(r"心跳|心脏(狂|猛|骤)|窒息|屏住呼吸|汗毛|脊背发凉|寒意|冷汗")

# 压力压过场景 mood 的选曲阈值; battle/grimdark 本身够紧, 不夺
_TENSE_OVERRIDE_SKIP = {"battle", "grimdark", "tense"}


class TurnStage:
    """One turn's per-beat director memory: sfx dedupe + the single flash."""

    def __init__(self) -> None:
        self.used: set[str] = set()
        self.flashed = False

    def beat_fx(self, text: str, mood: str | None = None) -> dict[str, Any]:
        """演出注记 — rides the streamed beat dict. Keys absent when nothing fires."""
        t = text or ""
        out: dict[str, Any] = {}
        for kw, name in _SFX:
            if kw in t:
                if name not in self.used:
                    self.used.add(name)
                    out["sfx"] = name
                break
        if "sfx" not in out and "heartbeat" not in self.used and _HEARTBEAT_RE.search(t):
            self.used.add("heartbeat")
            out["sfx"] = "heartbeat"
        if not self.flashed and _FLASH_RE.search(t):
            self.flashed = True
            out["fx"] = "flash"
        if mood:
            out["expr"] = mood   # 表情差分位: 差分素材上线即用, 现在先随拍下发
        return out


def stage_turn(final: dict[str, Any]) -> dict[str, Any]:
    """回合演出单 {bgm?, tint} from the turn's final meta. tint 总是给 (none=复位):
    danger (猎手贴脸/压力爆表) > frail (理智见底) > night (夜) > none."""
    out: dict[str, Any] = {}
    scene = final.get("scene") or {}
    mood = str(scene.get("mood") or "daily")
    pv = final.get("pressure_view") or {}
    tv = final.get("threat_view") or {}
    sv = final.get("sanity_view") or {}
    try:
        pressure = int(pv.get("value") or 0)
    except (TypeError, ValueError):
        pressure = 0
    hot = bool(tv.get("alert")) or pressure >= 70
    frail = False
    try:
        if sv:
            frail = int(sv.get("value", 999)) <= int(sv.get("max", 100)) * 3 // 10
    except (TypeError, ValueError):
        pass
    if hot and mood not in _TENSE_OVERRIDE_SKIP:
        out["bgm"] = "tense"
    if hot:
        out["tint"] = "danger"
    elif frail:
        out["tint"] = "frail"
    elif scene.get("night"):
        out["tint"] = "night"
    else:
        out["tint"] = "none"
    return out
