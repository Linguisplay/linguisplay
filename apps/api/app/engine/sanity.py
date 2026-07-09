# -*- coding: utf-8 -*-
"""🧠 理智账本 (the sanity ledger) — 恐怖主题的「修为」, CoC-SAN 蓝本.

Terrible knowledge and terrible encounters COST: witnessing the hunter, prying
open heavy truths, watching someone die, breaking a house rule. Quiet turns in
safe company give a little back. The ledger has TEETH at thresholds: shaking
hands raise every DC, and below the waterline the ENGINE tells the director to
write small unreliable details into the narration (never announced). Zero is a
terminal break.

Story-agnostic: activates only when the story authors `story.sanity`
({"enabled": true, "name": "理智", "start": 100, "regen": 1, "ending_id": ...});
everything here is pure — runtime owns the state mutations.
"""
from __future__ import annotations

from typing import Any


def cfg(content: dict[str, Any]) -> dict[str, Any] | None:
    s = (content.get("story") or {}).get("sanity") or {}
    if not isinstance(s, dict) or not s.get("enabled"):
        return None
    return {"name": (s.get("name") or "理智").strip(),
            "start": max(10, min(200, int(s.get("start") or 100))),
            "regen": max(0, min(5, int(s.get("regen") or 1))),
            "ending_id": (s.get("ending_id") or "").strip() or None}


# threshold bands: (floor, zh label, en label, dc penalty)
_BANDS = [
    (70, "尚稳", "steady", 0),
    (40, "手在抖", "hands shaking", 1),
    (15, "耳鸣不止", "ears ringing", 2),
    (1,  "濒临崩溃", "at the breaking point", 3),
    (0,  "崩断", "broken", 4),
]


def band_of(value: int) -> tuple[int, str, str, int]:
    """(floor, zh, en, dc_mod) for a sanity value."""
    for floor, zh, en, dc in _BANDS:
        if value >= floor:
            return (floor, zh, en, dc)
    return _BANDS[-1]


def dc_mod(value: int) -> int:
    return band_of(value)[3]


def anchor(scfg: dict[str, Any], value: int, zh: bool = True) -> str:
    """Depth-0 line for the director. Below the waterline the narration itself is
    allowed to go quietly wrong — the classic unreliable-perception move, never
    announced, never explained."""
    floor, lab_zh, lab_en, _ = band_of(value)
    if floor >= 70:
        return ""
    name = scfg["name"]
    if zh:
        line = f"【{name}实态】玩家的{name}正在流失（{lab_zh}）。恐惧写在动作里：手、呼吸、错听。"
        if floor <= 39:
            line += ("旁白可以夹进一两处极小的不对劲（数目对不上、余光里的错位、"
                     "听见有人极轻地叫了名字）——绝不点破、绝不解释、每轮至多一处。")
        if floor <= 14:
            line += "TA已经很难分清哪些是真的；连TA自己的判断，文字也不必替TA担保。"
        return line
    line = f"[{name} ledger] The player's {name} is fraying ({lab_en})."
    if floor <= 39:
        line += (" The narration may slip in ONE tiny wrongness per turn (a count "
                 "that doesn't match, a name half-heard) — never point at it.")
    return line


def label_view(scfg: dict[str, Any], value: int) -> dict[str, Any]:
    floor, lab_zh, _, _ = band_of(value)
    return {"name": scfg["name"], "value": int(value), "max": scfg["start"],
            "label": lab_zh}
