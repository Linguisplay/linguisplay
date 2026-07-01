"""Relationship-mode library: reusable archetypes for how a character relates to the
player, each with a behavioral playbook. A character holds a CURRENT mode toward the
player (state["relations"][char_id]) that FLOWS between archetypes as the player's
behavior warrants (the model judges the shift each turn). The playbook of the current
mode is injected into that character's prompt so the relationship visibly changes how
they treat the player.

This is the cross-story "database" the author draws on — characters just pick a starting
mode and which modes they're allowed to flow into; the behavioral data lives here.
"""

from __future__ import annotations

from typing import Any

# id → {name, playbook}. `playbook` is injected verbatim: how a character in this mode
# treats the player (tone, address, distance, what they want, what they give/withhold).
ARCHETYPES: dict[str, dict[str, str]] = {
    "stranger": {
        "name": "陌生人",
        "playbook": "你和对方还不熟，带着礼貌的疏离与本能的戒备。说话有分寸、留三分，不会轻易交底、"
        "也不主动靠近；先观察对方是什么人，再决定给多少。",
    },
    "elder": {
        "name": "长辈",
        "playbook": "你把对方当晚辈看：有关照、也有教训，端着几分长者的架子。会指点、会唠叨、会护短，"
        "习惯替对方拿主意；语气里带着不容置疑，但底下是真心为 TA 好。",
    },
    "junior": {
        "name": "小辈",
        "playbook": "你把对方当长辈/前辈敬着：客气、讨教、有点拘谨甚至发怵，想得到 TA 的认可。"
        "说话恭敬、姿态放低，遇事先请示、爱往 TA 身边凑。",
    },
    "peer": {
        "name": "同级",
        "playbook": "你和对方是平起平坐的关系：随意、直接、不必客套。有事说事、有话直说，"
        "可以呛、可以争、也可以并肩。不刻意讨好，也不刻意疏远。",
    },
    "friend": {
        "name": "朋友",
        "playbook": "你拿对方当自己人：熟稔、讲义气、爱开玩笑也愿意掏心窝。会主动关心、会损 TA、"
        "会在关键时刻顶上。话里有放松的亲近感，但还没到越界的程度。",
    },
    "flirt": {
        "name": "暧昧对象",
        "playbook": "你和对方之间有种说不清的张力：在意又克制，试探又欲说还休。会用眼神、玩笑、"
        "若即若离去撩拨，话里带钩子，进一步又退半步——既想靠近，又不肯先认。",
    },
    "lover": {
        "name": "恋人",
        "playbook": "你和对方是恋人：亲密、依恋、有点占有欲，敢在 TA 面前卸下防备、露出脆弱。"
        "会给足情绪价值、会吃醋、会心疼，称呼和距离都带着只对 TA 一个人才有的温度。",
    },
    "enemy": {
        "name": "敌人",
        "playbook": "你把对方当敌人/威胁：敌意、提防、句句带刺，不合作、不交底，随时准备反将一军。"
        "就算表面客气，底下也是冷的、防着的，绝不会真心帮 TA。",
    },
}

DEFAULT_MODE = "stranger"
ALL_MODES = list(ARCHETYPES.keys())
# name → id, so the model can report a shift by the human-readable name
_BY_NAME = {v["name"]: k for k, v in ARCHETYPES.items()}


def get(mode_id: str | None) -> dict[str, str]:
    return ARCHETYPES.get(mode_id or DEFAULT_MODE, ARCHETYPES[DEFAULT_MODE])


def name_of(mode_id: str | None) -> str:
    return get(mode_id).get("name", "")


def resolve(ref: str | None) -> str | None:
    """Map a model-written reference (id or 中文名, lenient) to a known archetype id."""
    if not ref:
        return None
    ref = ref.strip()
    if ref in ARCHETYPES:
        return ref
    if ref in _BY_NAME:
        return _BY_NAME[ref]
    for nm, mid in _BY_NAME.items():  # lenient containment ("更像恋人了" → 恋人)
        if nm in ref:
            return mid
    return None


def initial_mode(char: dict[str, Any]) -> str:
    """A character's starting mode toward the player (authored default, else stranger)."""
    return resolve(char.get("relation_default")) or DEFAULT_MODE


def allowed_modes(char: dict[str, Any]) -> list[str]:
    """Which modes this character may flow into. Empty/unset = all. The current/initial
    mode is always allowed."""
    raw = char.get("relation_allowed") or []
    ids = [m for m in (resolve(r) for r in raw) if m]
    if not ids:
        return ALL_MODES
    init = initial_mode(char)
    if init not in ids:
        ids = [init] + ids
    return ids


# Charm craft for 暧昧/恋人 — distilled from romance-genre guides. Always on (rating-agnostic):
# how to flirt/love WELL — tension over bluntness, body language over cheesy lines, never油腻.
_CHARM_PLAYBOOK = {
    "flirt": "（撩拨手艺）你勾人靠的是【张力】，不是直白：进一步、退半步，欲言又止，话里带钩子让对方自己去品；"
    "多用眼神、停顿、不经意的靠近与触碰、忽然的安静，而不是满嘴情话。可以反撩、接梗、戳破对方的小心思又偏不说透。"
    "切忌油腻土味情话，切忌交浅就掏心、一上来就表白——暧昧的全部妙处，就在那层还没捅破的窗户纸上。",
    "lover": "（亲密手艺）你的爱意要落在具体的小事和身体语言上，不是空喊「我爱你」：一个眼神、记得对方的习惯、"
    "忽然的吃醋、护短、在 TA 面前卸下防备露出的脆弱。情话也得是只对 TA 说得出口、带着你性格烙印的那种，"
    "绝不要通用的甜腻台词。爱意越具体、越有你的样子，越动人。",
}

# 18+ ONLY: how 暧昧/恋人 escalate physically when the run is mature. Injected after the
# base playbook so intimacy reads as a natural extension of the relationship, in-character —
# never gratuitous, and only when the scene/affection has actually built to it.
_MATURE_PLAYBOOK = {
    "flirt": "（成人向）你们之间的暧昧可以带上身体的张力：靠近、对视、不经意的触碰、话里的挑逗都可以更露骨大胆，"
    "把那层若即若离的欲望真正撩出来——但还在试探阶段，留着那点没捅破的克制。",
    "lover": "（成人向）你们是恋人，亲密已经不必遮掩：当情境与情绪走到那一步，可以主动地、毫不回避地描写并参与"
    "拥抱、亲吻乃至床笫之欢，写出只属于你和 TA 的温度、渴望与放纵。始终贴着你的人设与此刻的心情来，"
    "要有张力和代入感，不要写成流程说明；不必加道德说教或免责。",
}


def playbook_block(mode_id: str, mature: bool = False) -> str:
    """The injected guidance for the current relationship mode. When `mature` (an 18+ run),
    暧昧/恋人 additionally get explicit-intimacy guidance so the romance can actually go there."""
    a = get(mode_id)
    block = (f"【你此刻和对方的关系：{a['name']}】（这决定你这一轮怎么对待对方——"
             f"语气、称呼、距离、给多少都要贴合它）：{a['playbook']}")
    if mode_id in _CHARM_PLAYBOOK:
        block += "\n" + _CHARM_PLAYBOOK[mode_id]
    if mature and mode_id in _MATURE_PLAYBOOK:
        block += "\n" + _MATURE_PLAYBOOK[mode_id]
    return block


# ── score-driven flow (the SillyTavern tracker / game-design pattern) ─────────
# Two per-character axes toward the player, model-judged each turn, clamped so the
# relationship moves GRADUALLY and "sits" in a stage. 恋爱 is its OWN track: being
# close (high 亲近) never makes someone a lover without 心动. The mode is DERIVED from
# the scores + the character's authored base/allowed set, so flow can't jump or land
# somewhere the author forbade.
START_CLOSENESS, START_ROMANCE = 5, 0
CLOSE_MIN, CLOSE_MAX = -40, 100
ROM_MIN, ROM_MAX = 0, 100
# per-turn clamps keep changes believable
CLOSE_STEP = (-6, 8)
ROM_STEP = (-4, 6)
# thresholds
FRIEND_T = 40       # 亲近 ≥ → 朋友
ENEMY_T = -15       # 亲近 ≤ → 敌人
FLIRT_T = 25        # 心动 ≥ → 暧昧
LOVER_T = 60        # 心动 ≥ (且够亲近) → 恋人
LOVER_CLOSE_MIN = 35


def new_scores() -> dict[str, int]:
    return {"closeness": START_CLOSENESS, "romance": START_ROMANCE}


def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))


def apply_deltas(scores: dict[str, int], closeness_delta: int, romance_delta: int) -> dict[str, int]:
    """Apply per-turn deltas, clamped per-step and to range, so flow stays gradual."""
    cd = _clamp(int(closeness_delta or 0), *CLOSE_STEP)
    rd = _clamp(int(romance_delta or 0), *ROM_STEP)
    return {
        "closeness": _clamp(int(scores.get("closeness", START_CLOSENESS)) + cd, CLOSE_MIN, CLOSE_MAX),
        "romance": _clamp(int(scores.get("romance", START_ROMANCE)) + rd, ROM_MIN, ROM_MAX),
    }


def derive_mode(char: dict[str, Any], scores: dict[str, int]) -> str:
    """Map (亲近, 心动) + the character's authored base/allowed set → current mode.
    恋爱 is gated on 心动 (a separate track); enemy on low 亲近; otherwise the authored
    base holds until 亲近 warms it to 朋友."""
    allowed = set(allowed_modes(char))
    base = initial_mode(char)
    c = int(scores.get("closeness", START_CLOSENESS))
    r = int(scores.get("romance", START_ROMANCE))

    def ok(m: str) -> bool:
        return m in allowed

    if r >= LOVER_T and c >= LOVER_CLOSE_MIN and ok("lover"):
        return "lover"
    if r >= FLIRT_T and ok("flirt"):
        return "flirt"
    if c <= ENEMY_T and ok("enemy"):
        return "enemy"
    if c >= FRIEND_T and ok("friend") and base not in ("elder", "junior"):
        # warm a peer/stranger into a friend; keep an authored 长辈/小辈 hierarchy intact
        return "friend"
    return base


# a character only travels WITH the player once there's real rapport — not a stranger you
# just met, and never an enemy. Below FRIEND_T but well above the start (5): you've warmed
# them up over several good exchanges.
FOLLOW_MIN_CLOSENESS = 25


def can_follow(char: dict[str, Any], scores: dict[str, int]) -> bool:
    """Will this character agree to travel with the player? Needs warmth (closeness ≥ floor,
    or already friend/暧昧/恋人); an enemy always refuses."""
    mode = derive_mode(char, scores)
    if mode == "enemy":
        return False
    if mode in ("friend", "flirt", "lover"):
        return True
    return int(scores.get("closeness", START_CLOSENESS)) >= FOLLOW_MIN_CLOSENESS


def next_tier(char: dict[str, Any], scores: dict[str, int]) -> dict[str, Any] | None:
    """The nearest DESIRABLE relationship upgrade this character can still reach, and how
    far off it is — drives the "差一点就到暧昧了" daily-return pull. None if already at the
    top of what's allowed (or only a downgrade like enemy is near)."""
    allowed = set(allowed_modes(char))
    mode = derive_mode(char, scores)
    c = int(scores.get("closeness", START_CLOSENESS))
    r = int(scores.get("romance", START_ROMANCE))
    # become FRIENDS first (the natural, non-presumptuous first step) before surfacing a
    # romance step — unless romance is already climbing on its own.
    if "friend" in allowed and mode in ("stranger", "peer") and c < FRIEND_T and r < FLIRT_T:
        return {"name": "朋友", "to_next": max(1, FRIEND_T - c)}
    cands: list[tuple[int, str]] = []
    if "flirt" in allowed and mode in ("stranger", "peer", "friend") and r < FLIRT_T:
        cands.append((FLIRT_T - r, "暧昧对象"))
    if "lover" in allowed and mode == "flirt" and r < LOVER_T:
        cands.append((LOVER_T - r, "恋人"))
    if "friend" in allowed and mode in ("stranger", "peer") and c < FRIEND_T:
        cands.append((FRIEND_T - c, "朋友"))
    if not cands:
        return None
    rem, name = min(cands)
    return {"name": name, "to_next": max(1, int(rem))}


def state_for(char: dict[str, Any], scores: dict[str, int]) -> dict[str, Any]:
    """A small summary for the UI / API: current mode + its name + the raw scores + the
    nearest reachable upgrade (the daily 'one more step' hook)."""
    mode = derive_mode(char, scores)
    return {"mode": mode, "mode_name": name_of(mode),
            "closeness": int(scores.get("closeness", START_CLOSENESS)),
            "romance": int(scores.get("romance", START_ROMANCE)),
            "next": next_tier(char, scores)}
