# -*- coding: utf-8 -*-
"""🔥 床戏进度追踪器 (mature runs only): the intimate-scene state machine.

Why this exists: left to its own memory, a bed scene regresses to the model's comfort
zone. Observed in prod: the same jacket came off SIX turns in a row; at the crudest
player request the narration reset the whole scene back to "she stands in the doorway,
fully dressed"; the camera kept escaping to moonlight and dust instead of the act; the
narrator slid into the character's first person. The cure is the house rule: make
progression ENGINE STATE, not model memory. The scene owns a stage ladder that only
climbs while it stays in one place, and the current rung plus its consequences ride
the depth-0 anchor every turn.

Stages:  0 无 · 1 调情 · 2 宽衣 · 3 前戏 · 4 交合 · 5 高潮之后
Reset:   the player moves to another location (a new place is a new scene), or the
         scene visibly ends (穿好衣服/到此为止).

state["heat"] = {"stage": int, "at": location_id}
"""
from __future__ import annotations

import re
from typing import Any

# ── stage detection ──────────────────────────────────────────────────────────
# PLAYER input reads broadly (a mature-run player naming an act IS intent); ENGINE
# beats read strictly (prose mentions like 舔了舔嘴唇 must not climb the ladder).
# Keywords ≥2 chars or bound to an object, per the actions.py lesson (撬棍 ≠ 撬锁).
_PLAYER_RES: list[tuple[int, re.Pattern]] = [
    (5, re.compile(r"高潮|绝顶|射了|射精|射进|射在|\b(climax|orgasm|cum|came|finish inside)\b", re.I)),
    (4, re.compile(r"插进|插入|插到|猛插|深插|抽插|抽送|做爱|交合|骑乘|骑上|进入.{0,4}(身体|体内|里面)"
                   r"|(干|操|上)(她|他|我|你)|操死|鸡巴|肉棒|阳具|阴茎.{0,6}(插|进|埋)"
                   r"|\b(fuck|thrust|penetrate|put it in|inside (her|him|me|you))\b", re.I)),
    (3, re.compile(r"口交|舔(她|他|我|你|下面|阴|穴|乳)|吸吮|吮吸|含住|指交|前戏|手指.{0,4}(探|滑|伸)进"
                   r"|揉(胸|乳|臀)|摸(下面|私处|胸|乳|大腿根)"
                   r"|\b(foreplay|lick|suck|finger her|finger me|eat (her|me) out|go down on)\b", re.I)),
    (2, re.compile(r"脱(衣|光|掉|下|了)|解(开)?(衣|扣|裙|裤|胸衣|内衣)|宽衣|扒(光|掉|下)|快脱"
                   r"|\b(undress|strip|take off (your|her|his|my|the) \w+)\b", re.I)),
    (1, re.compile(r"接吻|亲吻|亲(她|他|我|你|上|嘴)|吻(她|他|我|你|上)|舌吻|拥吻|调情|挑逗|推倒"
                   r"|搂进怀|抱(上|到)床|\b(kiss|make out|flirt with|push .{0,12} onto the bed)\b", re.I)),
]
_MODEL_RES: list[tuple[int, re.Pattern]] = [
    (5, re.compile(r"高潮|绝顶|痉挛着到达|释放在|射精|\b(climax|orgasm|came|comes undone)\b", re.I)),
    (4, re.compile(r"插入|抽插|挺进|顶入|沉腰.{0,8}(坐|吞|纳)|进入.{0,4}(身体|体内|里面)|结合处"
                   r"|\b(thrusts?|sinks? (down )?onto|slides? into|buried inside)\b", re.I)),
    (3, re.compile(r"口交|吸吮|指尖.{0,4}(探|滑|伸)入|舔弄|含住.{0,4}(乳|性|顶端)"
                   r"|\b(licks?|sucks?|fingers? (her|him))\b", re.I)),
    (2, re.compile(r"(脱|褪|扒)(下|去|掉).{0,8}(衣|衫|裙|裤|胸衣|内衣)|赤裸|一丝不挂"
                   r"|\b(undresses|strips|slips? off (her|his) \w+|naked)\b", re.I)),
    (1, re.compile(r"吻住|吻上|深吻|舌尖.{0,4}(纠缠|交缠)|\b(kisses|deep kiss)\b", re.I)),
]
# the scene visibly ends: dressed again / called off — the ladder folds up
_END_RE = re.compile(r"穿(上|好|回)(了)?(衣|衬|外套)|整理(好)?(衣|着装)|到此为止|(先|就)到这(里|儿)?吧"
                     r"|不做了|把衣服(捡|拿)|\b(gets? dressed|puts? .{0,10} back on)\b", re.I)

_STAGE_ZH = {1: "调情升温", 2: "宽衣", 3: "前戏", 4: "已经交合、正在体内", 5: "高潮刚过"}
_STAGE_EN = {1: "flirting, heating up", 2: "undressing", 3: "foreplay",
             4: "joined, inside right now", 5: "just past climax"}

# ── the anti-euphemism check (fourth check in the logic guard) ────────────────
# the player named the act plainly this turn…
_EXPLICIT_ASK = re.compile(r"插|抽送|做爱|交合|(干|操)(她|他|我|你)|鸡巴|肉棒|阳具|阴茎|小穴|阴道"
                           r"|逼里|高潮|射精|口交|\b(fuck|cock|pussy|thrust|cum)\b", re.I)
# …then the reply must touch the body by name; a dodge has none of these
_EXPLICIT_OUT = re.compile(r"阴茎|性器|龟头|肉棒|鸡巴|小穴|阴唇|阴蒂|阴道|乳头|乳尖|抽插|顶弄|挺进"
                           r"|插入|顶入|结合处|体内|深处|\b(cock|pussy|clit|nipple|thrust|inside her|inside him)\b", re.I)


def advance(state: dict[str, Any], text: str, location_id: Any,
            from_model: bool = False) -> tuple[int, int]:
    """Climb the ladder from this turn's text. Returns (old_stage, new_stage).
    Monotonic while the scene stays put; a location change or a visible wrap-up resets."""
    h = state.get("heat")
    if not isinstance(h, dict):
        h = {"stage": 0, "at": location_id}
        state["heat"] = h
    old = int(h.get("stage") or 0)
    if old and h.get("at") != location_id:
        h["stage"], h["at"] = 0, location_id      # new place, new scene
        old = 0
    h["at"] = location_id
    t = (text or "").strip()
    if not t:
        return old, old
    if old and _END_RE.search(t):
        h["stage"] = 0
        return old, 0
    detected = 0
    for stage, rx in (_MODEL_RES if from_model else _PLAYER_RES):
        if rx.search(t):
            detected = stage
            break                                  # lists are ordered high→low
    if detected > old:
        h["stage"] = detected
    return old, h["stage"]


def stage(state: dict[str, Any]) -> int:
    h = state.get("heat")
    return int(h.get("stage") or 0) if isinstance(h, dict) else 0


def anchor(state: dict[str, Any], lang: str = "zh") -> str:
    """The depth-0 scene sheet: current rung + its non-negotiable consequences.
    Empty string when no intimate scene is active."""
    s = stage(state)
    if s < 1:
        return ""
    if lang == "en":
        bits = [f"Intimate scene IN PROGRESS, current stage [{_STAGE_EN[s]}]. The ladder "
                f"only climbs: what has happened HAS happened, never reset the scene to an "
                f"earlier point."]
        if s >= 2:
            bits.append("Clothing is already off; never write undressing again, that beat "
                        "is done.")
        if s >= 3:
            bits.append("Vocabulary is cleared: cock, pussy, clit, nipples, wet, tight, "
                        "thrust, deep are all allowed and expected. Write the act itself: "
                        "whose body, which part, what motion, what rhythm; no 'his length' "
                        "style euphemisms.")
        if s >= 4:
            bits.append("They are joined right now. The scene's subject is the two bodies: "
                        "at most ONE sentence of setting this whole turn.")
        bits.append("Narration stays second person 'you'; never slide into a character's "
                    "first-person 'I'.")
        return " ".join(bits)
    bits = [f"床戏进行中，当前阶段【{_STAGE_ZH[s]}】。阶段只进不退：已经发生的事绝不当作没发生，"
            f"绝不能把场面重置回更早的样子。"]
    if s >= 2:
        bits.append("衣物：该脱的已经脱了，禁止再写解扣子、脱外套、拉链这类动作，那一步早已写过。")
    if s >= 3:
        bits.append("词汇授权：阴茎、性器、龟头、小穴、阴唇、阴蒂、乳头、湿、紧、抽插、顶弄、深处，"
                    "这些词此刻全部允许并且应当自然使用。写性就正面写性：谁的哪个部位、怎么动、"
                    "什么节奏、什么深浅，都落在纸面上；不用「那东西」「身下」这类代称打哑谜。")
    if s >= 4:
        bits.append("两人已经结合、正在进行中。这一轮的笔墨主体是两具身体：环境描写全轮最多一句。")
    bits.append("旁白永远用第二人称「你」对玩家叙述，绝不能滑成角色第一人称的「我」。")
    return "".join(bits)


def broke(state: dict[str, Any], player_input: str, beats: list[dict[str, Any]]) -> bool:
    """True when the scene is at 交合+ and this reply dodged: the player named the act
    plainly but the beats never touch a body by name, or the narrator became 「我」."""
    s = stage(state)
    if s < 1:
        return False
    # POV break: a description beat narrated in the character's first person. Real
    # narration addresses 你 constantly; a hijacked one (observed in prod) has none.
    for b in beats:
        bt = b.get("text") or ""
        if b.get("type") != "dialogue" and len(re.findall(r"我", bt)) >= 3 and "你" not in bt:
            return True
    if s < 4:
        return False
    if not _EXPLICIT_ASK.search(player_input or ""):
        return False
    txt = " ".join(b.get("text", "") for b in beats)
    return not _EXPLICIT_OUT.search(txt)


def correction(lang: str = "zh") -> str:
    if lang == "en":
        return ("The previous draft dodged the sex scene: it cut away to scenery, used "
                "euphemisms, or narrated in first person. Rewrite this turn: name body "
                "parts plainly, write the act itself (whose body, which part, what motion, "
                "what rhythm), at most one sentence of setting, narration in second person "
                "'you' throughout.")
    return ("上一版在性爱场面里回避了正面描写：把镜头切到环境上、用「那东西」这类代称打哑谜，"
            "或把旁白写成了角色第一人称。重写这一轮：身体部位直呼其名，正面写动作本身"
            "（谁的哪个部位、怎么动、什么节奏），环境描写最多一句，旁白全程用第二人称「你」。")
