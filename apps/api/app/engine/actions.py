# -*- coding: utf-8 -*-
"""行动解算 (action resolution) — the difficulty layer of the 做 channel.

The old flow let the model decide WHETHER an action was risky (risk=100 → no roll), so
most stunts slipped past the dice. Now the ENGINE classifies the attempt first:

    verb class → base difficulty tier → (model may adjust ±1 tier via the existing
    risk judgment, clamped) → deterministic state modifiers → DC → d20

Classified actions ALWAYS roll — the model no longer holds a no-roll veto over them.
Unclassified actions keep the legacy model-judged path (no regression). Deterministic
twins (move/seek/search/…) and by-name 金手指 invocations never reach this layer at all.

Story-agnostic: the taxonomy is the frame; keywords are ≥2 chars to avoid 打开/追问
style false hits.
"""
from __future__ import annotations

from typing import Any

TIER_DC = {"easy": 5, "normal": 10, "hard": 15, "extreme": 19}
_TIER_ORDER = ["easy", "normal", "hard", "extreme"]

# (class label zh, keywords, base tier)
_CLASSES: list[tuple[str, tuple[str, ...], str]] = [
    ("强攻", ("揍", "砍", "劈", "踹", "挥拳", "一拳", "一脚", "出手", "动手", "攻击", "偷袭",
              "掐住", "扑向", "punch", "strike at", "attack", "tackle"), "normal"),
    ("潜行", ("偷偷", "悄悄", "潜入", "溜进", "顺走", "偷走", "摸走", "扒下", "蹑手蹑脚",
              "sneak", "steal", "pickpocket", "slip past"), "hard"),
    ("破闯", ("撬开", "撬锁", "撬门", "闯入", "闯进", "破门", "翻墙", "撞开", "砸开", "砸锁",
              "强行", "break in", "pry open", "force open", "kick down"), "hard"),
    ("腾跃", ("攀上", "爬上", "翻上", "跳过", "跃过", "飞身", "荡过",
              "climb", "leap over", "vault", "scale the"), "normal"),
    ("追逃", ("追上", "追赶", "甩开", "狂奔", "逃出", "冲出去", "拦住",
              "chase down", "outrun", "flee from", "cut them off"), "normal"),
    ("欺瞒", ("骗过", "谎称", "冒充", "伪装", "假扮", "糊弄", "蒙混",
              "bluff", "impersonate", "pass myself off"), "normal"),
    ("威慑", ("威胁", "恐吓", "吓唬", "逼问", "放狠话",
              "intimidate", "threaten", "stare down"), "normal"),
    ("巧手", ("修好", "拆开", "组装", "改装", "接线", "配药", "开锁",
              "repair", "dismantle", "rig", "pick the lock"), "normal"),
    ("卖艺", ("表演", "献艺", "弹一曲", "唱一段", "露一手",
              "perform", "put on a show"), "easy"),
    ("豪赌", ("徒手接", "硬接", "硬扛", "以一敌", "单挑", "赤手",
              "bare-handed", "single-handed", "head-on"), "extreme"),
    # ⚡ absorbing wild energy into your own body: the cultivation-world gamble.
    # Success feeds the progression ladder (runtime settles the gain off the dice).
    ("炼化", ("吸收", "炼化", "吞噬", "汲取", "抽取", "纳入体内", "炼入", "吸入体内",
              "absorb", "devour the", "siphon", "drain the"), "hard"),
]


def _clamp_tier(tier: str, base: str) -> str:
    """The model may move difficulty ONE tier from the engine's base, never more."""
    ti, bi = _TIER_ORDER.index(tier), _TIER_ORDER.index(base)
    return _TIER_ORDER[max(bi - 1, min(bi + 1, ti))]


def _risk_to_tier(risk: int) -> str | None:
    """Map the legacy risk-judgment % (higher = safer) onto a tier. 100 = the model
    saw no risk → None (no adjustment opinion)."""
    r = max(0, min(100, int(risk)))
    if r >= 100:
        return None
    if r >= 75:
        return "easy"
    if r >= 50:
        return "normal"
    if r >= 25:
        return "hard"
    return "extreme"


def classify(content: dict[str, Any], state: dict[str, Any], text: str) -> dict[str, Any] | None:
    """Deterministic first pass: does this 做-attempt fall in a rollable class?
    Returns {"cls", "tier", "dc", "mods": [...]} or None (→ legacy model-judged path)."""
    t = (text or "").strip()
    if not t:
        return None
    low = t.lower()
    hit = None
    for label, kws, tier in _CLASSES:
        if any((k in t) if any("一" <= ch <= "鿿" for ch in k) else (k in low) for k in kws):
            hit = (label, tier)
            break
    if not hit:
        return None
    label, tier = hit
    dc = TIER_DC[tier]
    mods: list[str] = []
    # deterministic state modifiers — the body you're in and the tools you hold
    hp = state.get("player_hp") or "healthy"
    if hp == "hurt":
        dc, _ = dc + 2, mods.append("带伤+2")
    elif hp == "dying":
        dc, _ = dc + 5, mods.append("濒死+5")
    for it in state.get("inventory") or []:
        nm = (it.get("name") or "").strip()
        if nm and nm in t:
            dc, _ = dc - 2, mods.append(f"称手（{nm}）-2")
            break
    return {"cls": label, "tier": tier, "dc": max(2, min(19, dc)), "mods": mods}


def resolve_dc(base: dict[str, Any], judged_risk: int | None) -> dict[str, Any]:
    """Fold the model's risk opinion into the engine's base: ±1 tier at most, then
    re-apply the deterministic modifier delta. Returns the final {tier, dc, adjusted}."""
    tier = base["tier"]
    adjusted = False
    if judged_risk is not None:
        mt = _risk_to_tier(judged_risk)
        if mt is not None:
            nt = _clamp_tier(mt, tier)
            adjusted = nt != tier
            tier = nt
    mod_delta = base["dc"] - TIER_DC[base["tier"]]   # wound/equipment delta already computed
    return {"tier": tier, "dc": max(2, min(19, TIER_DC[tier] + mod_delta)),
            "adjusted": adjusted}
