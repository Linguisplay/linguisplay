# -*- coding: utf-8 -*-
"""🦇 猎手系统 (the stalker): a story-declared threat that hunts by its SENSES.

The horror doctrine here is the same law the rest of the engine converged to:
文与实不许分家. A monster that lives only in prose is toothless one turn and
omniscient the next; dread needs LEARNABLE rules executed by the program.
So the story declares WHO hunts and WHAT draws it (story.threat, all flavor
authored per-剧本 — this module hardcodes no 剧本 content), and the ENGINE
owns the ledger: where it stands, how alert it is, how many times it has
caught you, and what each catch costs (escalation ladder → the hp system).

Everything here is PURE: classification + graph walking + config parsing.
State mutation, beats and dice live in runtime's threat phase.

story.threat = {
  "char_id": "...",              # which character is the hunter (required)
  "patrol": ["loc_a", ...],      # its beat, walked one step per turn (required)
  "senses": ["sound", "light"],  # what draws it (default both)
  "cannot_enter": ["loc_x"],     # squeeze-spaces it can never reach
  "return_to": "loc_a",          # where strike 1 deposits the player ("请回")
  "ladder": ["return", "hurt", "dying"],   # escalation per catch; beyond → dead
  "cues": {"far": [...], "near": [...], "here": [...]}   # authored 先声后形 lines
}

state["threat"] = {"pos": loc_id, "alert": 0-3, "strikes": 0, "band": "far"}
"""
from __future__ import annotations

from typing import Any

DEFAULT_LADDER = ["return", "hurt", "dying"]


def cfg(content: dict[str, Any]) -> dict[str, Any] | None:
    """The story's authored threat, or None. Requires a real char_id + a patrol of
    authored location ids; garbage configs disable the system rather than half-run."""
    t = (content.get("story") or {}).get("threat") or {}
    if not isinstance(t, dict) or not (t.get("char_id") or "").strip():
        return None
    loc_ids = {(l.get("id") or "").strip()
               for l in (content.get("story") or {}).get("locations") or []}
    patrol = [p for p in (t.get("patrol") or []) if p in loc_ids]
    if not patrol:
        return None
    return {
        "char_id": t["char_id"].strip(),
        "patrol": patrol,
        "senses": [s for s in (t.get("senses") or ["sound", "light"])
                   if s in ("sound", "light")] or ["sound"],
        "cannot_enter": {c for c in (t.get("cannot_enter") or []) if c in loc_ids},
        "return_to": (t.get("return_to") or "").strip() or patrol[0],
        "ladder": [s for s in (t.get("ladder") or DEFAULT_LADDER)
                   if s in ("return", "hurt", "dying", "dead")] or DEFAULT_LADDER,
        "cues": t.get("cues") or {},
    }


def default_state(tcfg: dict[str, Any]) -> dict[str, Any]:
    return {"pos": tcfg["patrol"][0], "alert": 0, "strikes": 0, "band": "far"}


# ── 噪音分贝 (deterministic loudness of the player's turn) ─────────────────────────
# The point of classifying in CODE: the player can LEARN these rules and the
# rules never have moods. 0 silent / 1 normal / 2 loud / 3 blatant.
_LOUD_DO = ("跑", "奔", "冲", "狂奔", "砸", "踹", "撞", "撬", "掀", "摔", "拖", "踢",
            "敲", "拍门", "翻倒", "run", "sprint", "smash", "kick", "slam", "bash")
_SHOUT = ("喊", "大叫", "吼", "尖叫", "大声", "叫喊", "呼救", "嚷", "shout", "scream", "yell")
_QUIET = ("潜行", "蹑手蹑脚", "轻手轻脚", "屏住呼吸", "悄悄", "偷偷", "低声", "耳语",
          "压低", "小声", "轻声", "躲", "藏", "不出声", "quietly", "whisper", "sneak",
          "hide", "hold my breath", "hold your breath")
_LIGHT = ("手电", "打光", "开灯", "照过去", "照向", "直照", "晃了晃", "flashlight",
          "torch", "shine")
_LOUD_CLASSES = {"强攻": 3, "破闯": 3, "豪赌": 2, "追逃": 2, "腾跃": 2}


def noise_of(player_input: str, channel: str, action_cls: str = "",
             dice_outcome: str = "", senses: list[str] | None = None) -> int:
    """How loud this turn was, 0..3. Look/think turns are silent; a critical botch
    always clatters (+1) — failure doesn't just cost, it CALLS."""
    senses = senses or ["sound", "light"]
    text = (player_input or "").strip()
    low = text.lower()
    n = 0
    if channel in ("say", "do"):
        n = 1 if channel == "say" else 1
        if any(k in text or k in low for k in _QUIET):
            n = 0
        if channel == "do" and action_cls in _LOUD_CLASSES:
            n = max(n, _LOUD_CLASSES[action_cls])
        if any(k in text or k in low for k in _LOUD_DO) and channel == "do":
            n = max(n, 3)
        if any(k in text or k in low for k in _SHOUT):
            n = max(n, 3)
        if "light" in senses and any(k in text or k in low for k in _LIGHT):
            n = max(n, 3)
    if dice_outcome == "crit_fail":
        n = min(3, n + 1)
    return max(0, min(3, n))


# ── the building as a graph ──────────────────────────────────────────────────────
def neighbors(content: dict[str, Any]) -> dict[str, set]:
    """Symmetric adjacency by location exits (exits are NAMES; map back to ids)."""
    locs = (content.get("story") or {}).get("locations") or []
    by_name = {(l.get("name") or "").strip(): (l.get("id") or "").strip()
               for l in locs if l.get("id") and l.get("name")}
    adj: dict[str, set] = {(l.get("id") or "").strip(): set() for l in locs if l.get("id")}
    for l in locs:
        lid = (l.get("id") or "").strip()
        for en in l.get("exits") or []:
            nid = by_name.get((en or "").strip())
            if nid and nid != lid:
                adj[lid].add(nid)
                adj.setdefault(nid, set()).add(lid)
    return adj


def step_toward(adj: dict[str, set], src: str, dst: str, blocked: set) -> str:
    """One BFS step from src toward dst, never entering `blocked`. If dst itself is
    unreachable, walk toward the closest reachable NEIGHBOR of dst (it waits at the
    mouth of the vent you crawled into). No path at all → stay put."""
    if src == dst:
        return src
    targets = {dst} if dst not in blocked else (adj.get(dst, set()) - blocked)
    if not targets:
        return src
    seen = {src}
    frontier = [(src, None)]  # (node, first_step)
    while frontier:
        nxt = []
        for node, first in frontier:
            for nb in adj.get(node, set()):
                if nb in seen or nb in blocked:
                    continue
                f = first or nb
                if nb in targets:
                    return f
                seen.add(nb)
                nxt.append((nb, f))
        frontier = nxt
    return src


def step_patrol(tcfg: dict[str, Any], pos: str) -> str:
    """Next stop on the authored beat (cycle). Off-beat (was hunting) → walk back
    toward the nearest patrol stop is overkill; just resume at the first stop's
    successor by index of the closest match, falling back to patrol[0]."""
    patrol = tcfg["patrol"]
    if pos in patrol:
        return patrol[(patrol.index(pos) + 1) % len(patrol)]
    return patrol[0]


def band_of(adj: dict[str, set], threat_pos: str, player_pos: str | None) -> str:
    """here = same room, near = one door away, far = anywhere else."""
    if not player_pos:
        return "far"
    if threat_pos == player_pos:
        return "here"
    if player_pos in adj.get(threat_pos, set()):
        return "near"
    return "far"


def cue_line(tcfg: dict[str, Any], band: str, turn_index: int, zh: bool = True) -> str:
    """The 先声后形 whisper for this distance. Authored cues rotate (so the dread
    doesn't repeat itself verbatim); fallback lines are deliberately bland — a story
    that wants real teeth writes its own."""
    lines = [s for s in (tcfg.get("cues") or {}).get(band) or [] if (s or "").strip()]
    if lines:
        return lines[turn_index % len(lines)].strip()
    return {
        "here": "它就在这里。" if zh else "It is in the room.",
        "near": "很近的地方，有什么动了一下。" if zh else "Something moved, close by.",
        "far": "" if zh else "",
    }.get(band, "")
