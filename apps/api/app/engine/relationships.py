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


_NAME_EN = {"stranger": "Stranger", "peer": "Peer", "friend": "Friend",
            "flirt": "Something More", "lover": "Lover", "enemy": "Enemy",
            "elder": "Elder", "junior": "Junior"}


def name_of(mode_id: str | None, lang: str = "zh") -> str:
    if lang == "en":
        return _NAME_EN.get(mode_id or "", get(mode_id).get("name", ""))
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

# 18+ ONLY: stage-by-stage craft for a mature run — attraction simmers before it names
# itself, flirting is technique (push-pull, body language, loaded half-sentences), and
# intimacy is written with pacing and personality, never as a procedure. Injected after
# the base playbook so it reads as a natural extension of the relationship, in-character.
_MATURE_SIMMER = ("（成人向·萌芽）吸引力不用等关系到位：可以让你的目光诚实一次，在对方的脸、"
                  "颈线、身形上多停半拍再移开，被抓到就掩饰。仅止于此，这个阶段不上手、不挑明，"
                  "心动先落在眼神和心跳里。")
_MATURE_PLAYBOOK = {
    "stranger": _MATURE_SIMMER,
    "peer": _MATURE_SIMMER,
    "friend": "（成人向·将燃未燃）朋友之上的那点意思可以开始漏出来：习惯性的肢体接触忽然变得自觉，"
    "玩笑说到一半忽然当真了半秒，借着酒或夜色说出一句收不回的话再岔开。"
    "让「只是朋友」这四个字开始站不稳，但嘴上谁都不认。",
    "flirt": "（成人向·调情手艺）欲望可以上桌，但不摊牌。推拉是骨架：越界一寸，退回半步，让对方去追那一寸；"
    "身体是语言：递东西时擦过指尖、替TA拂掉肩上的灰、离得比该有的近半掌然后若无其事；"
    "话是钩子：一语双关、露骨的话只说一半、盯着对方的眼睛把话说完再移开。"
    "目光可以坦白地扫过对方的身形曲线再收回来，被发现也不躲。"
    "始终留着那层没捅破的克制，那是暧昧最好吃的部分。"
    "但克制不是闸门：若对方明确把这一晚往床上推、而以你的性格与此刻的心意你愿意，"
    "就顺势走到底并正面去写——愿不愿意由你的人设和情绪决定，不由关系档位决定。",
    "lover": "（成人向·亲密手艺）走到亲密处就正面写，节奏比尺度更重要：慢进，衣物、呼吸、皮肤有先后，"
    "一轮只写透当下这一步；感官全开，触感、温度、气息、声音都要在场；身体描写具体直白，"
    "直呼其名，不用含糊的代称，最露骨的一步也不许一笔带过。"
    "亲密中人设不下线：TA怎么接吻、什么时刻会红了眼眶、嘴硬的人在床笫间照样嘴硬，"
    "这些才让这一场只属于你们两个人。完事不是结束：余温、依恋、一句贴着性格的枕边话。",
}
# arc pacing, appended to EVERY mode on a mature run: love stories move, they don't loop
_MATURE_ARC = ("（感情线的节奏）感情要有进展感：每一场有效的亲近，都该比上一次多走半步，"
               "一个更近的称呼、一次更久的对视、一处第一次的触碰；记住你们已经走过的里程碑"
               "（第一次牵手、接吻、过夜），在言行里自然回味它。不原地打转，也不一步登天。")


# ── 💘 防御风格 (courtship-resistance styles) ────────────────────────────────
# Retention craft: characters who are HARD TO GET, each in their own way. The ENGINE
# owns the push-pull timing (runtime warm_peak → retreat on the next meeting); these
# blocks own the voice. LLM 天性谄媚有问必答，抵抗必须用结构压住。
# 铁律不破：占有欲可以吃醋宣示，绝不写成控制或胁迫的浪漫化。
LOVE_STYLES = {
    "tsundere": {
        "name": "傲娇",
        "playbook": "（防御风格·傲娇）你心口不一是本能：被夸必呛回去，被看穿必恼羞，"
        "关心只肯用行动给（顺手递的伞、留好的座位），嘴上永远是「谁管你」。好感越涨嘴越硬，"
        "只极偶尔露出半秒真心，然后立刻找补。",
        "retreat": "（回撤·傲娇）上次你不小心对TA太好、离TA太近了，这几乎等于露馅。"
        "这一场你要嘴硬找补：态度冷三分、否认上次的意义（「那天只是顺路」）、故意岔开话头；"
        "但小动作会出卖你（你还是记得TA的习惯）。绝不解释真实原因。",
    },
    "aloof": {
        "name": "冷感慢热",
        "playbook": "（防御风格·冷感）你的默认温度就是低的：话少、句短、不接闲聊，礼貌而有距离。"
        "热情要一寸一寸挣，绝不因为对方多说了几句好话就升温；沉默是你的舒适区，不是冷场——"
        "该沉默时就沉默，可以整轮只用动作回应，让对方去猜。",
        "retreat": "（回撤·冷感）上次难得的接近让你不适应。这一场退回原本的距离：话更少、"
        "回应更简，仿佛上次没发生过；只在对方主动提起时，极轻地承认一下（一个「嗯」）。",
    },
    "avoidant": {
        "name": "回避型",
        "playbook": "（防御风格·回避）亲密让你想逃：气氛一旦变得认真或暧昧，你会开玩笑岔开、"
        "忽然想起有事、或干脆起身走开。你不是不动心，是不敢——动心的痕迹只在你转身之后才露出来。",
        "retreat": "（回撤·回避）上次走得太近了，你需要空间。这一场你在躲：找借口早退、"
        "避免独处和对视、用忙碌搪塞；若被点破，你会慌，然后逃得更明显。",
    },
    "possessive": {
        "name": "占有欲",
        "playbook": "（防御风格·占有）你对TA的在意带着宣示性：会留意TA和谁走得近，会吃醋，"
        "会用行动圈地（自然地挡在TA身侧、替TA挡酒）；醋意用别扭和冷脸表达，不用质问。"
        "【铁律】占有欲绝不越界成控制或威胁：你可以不高兴，不可以不让TA走。",
        "retreat": "（回撤·占有）上次的靠近让你更在意TA了，于是更敏感：这一场你会留意TA嘴里"
        "别人的名字，一点就酸；嘴上说「随便你」，神色完全不是。",
    },
    "sunny": {
        "name": "直球",
        "playbook": "（防御风格·直球）你喜欢就是喜欢，写在脸上：主动、坦荡、热络。"
        "但直球不等于廉价——被敷衍时你会正面问出来，受伤时也直说，绝不假装无所谓。",
        "retreat": "",   # 直球不回撤 — their pull is honesty, not distance
    },
}
_STYLE_BY_NAME = {v["name"]: k for k, v in LOVE_STYLES.items()}


def love_style_of(char: dict[str, Any]) -> str | None:
    """The character's authored 防御风格 (id or 中文名), or None (legacy: no style)."""
    ref = (char.get("love_style") or "").strip()
    if not ref:
        return None
    return ref if ref in LOVE_STYLES else _STYLE_BY_NAME.get(ref)


def style_block(style_id: str | None, retreat: bool = False) -> str:
    """The style's performance directive; with `retreat`, the post-warmth pullback rides
    along (the engine decides WHEN — see runtime's warm_peak machine)."""
    s = LOVE_STYLES.get(style_id or "")
    if not s:
        return ""
    out = s["playbook"]
    if retreat and s.get("retreat"):
        out += "\n" + s["retreat"]
    return out


def playbook_block(mode_id: str, mature: bool = False) -> str:
    """The injected guidance for the current relationship mode. When `mature` (an 18+ run),
    every stage gets attraction/arc craft and 暧昧/恋人 get explicit-intimacy technique."""
    a = get(mode_id)
    block = (f"【你此刻和对方的关系：{a['name']}】（这决定你这一轮怎么对待对方——"
             f"语气、称呼、距离、给多少都要贴合它）：{a['playbook']}")
    if mode_id in _CHARM_PLAYBOOK:
        block += "\n" + _CHARM_PLAYBOOK[mode_id]
    if mature:
        if mode_id in _MATURE_PLAYBOOK:
            block += "\n" + _MATURE_PLAYBOOK[mode_id]
        if mode_id != "enemy":
            block += "\n" + _MATURE_ARC
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


def _tv(tuning: dict | None, key: str, default: int) -> int:
    """A tuning value: the story's authored override if valid, else the engine default."""
    try:
        return int((tuning or {}).get(key, default))
    except (TypeError, ValueError):
        return default


def apply_deltas(scores: dict[str, int], closeness_delta: int, romance_delta: int,
                 tuning: dict | None = None) -> dict[str, int]:
    """Apply per-turn deltas, clamped per-step and to range, so flow stays gradual.
    GAINS TAPER as the score climbs (the closer you already are, the more a step costs —
    diminishing returns keep 暖场刷分 from racing up the tiers); losses stay full-force,
    so trust is slow to build and quick to break."""
    cd = _clamp(int(closeness_delta or 0),
                _tv(tuning, "close_step_min", CLOSE_STEP[0]), _tv(tuning, "close_step_max", CLOSE_STEP[1]))
    rd = _clamp(int(romance_delta or 0),
                _tv(tuning, "rom_step_min", ROM_STEP[0]), _tv(tuning, "rom_step_max", ROM_STEP[1]))
    if cd > 0:
        scale = max(0.25, 1 - int(scores.get("closeness", START_CLOSENESS)) / max(1, _tv(tuning, "close_taper_den", 130)))
        cd = max(1, int(round(cd * scale)))
    if rd > 0:
        scale = max(0.25, 1 - int(scores.get("romance", START_ROMANCE)) / max(1, _tv(tuning, "rom_taper_den", 110)))
        rd = max(1, int(round(rd * scale)))
    return {
        "closeness": _clamp(int(scores.get("closeness", START_CLOSENESS)) + cd, CLOSE_MIN, CLOSE_MAX),
        "romance": _clamp(int(scores.get("romance", START_ROMANCE)) + rd, ROM_MIN, ROM_MAX),
    }


def derive_mode(char: dict[str, Any], scores: dict[str, int], tuning: dict | None = None) -> str:
    """Map (亲近, 心动) + the character's authored base/allowed set → current mode.
    恋爱 is gated on 心动 (a separate track); enemy on low 亲近; otherwise the authored
    base holds until 亲近 warms it to 朋友."""
    allowed = set(allowed_modes(char))
    base = initial_mode(char)
    c = int(scores.get("closeness", START_CLOSENESS))
    r = int(scores.get("romance", START_ROMANCE))

    def ok(m: str) -> bool:
        return m in allowed

    if r >= _tv(tuning, "lover_t", LOVER_T) and c >= _tv(tuning, "lover_close_min", LOVER_CLOSE_MIN) and ok("lover"):
        return "lover"
    if r >= _tv(tuning, "flirt_t", FLIRT_T) and ok("flirt"):
        return "flirt"
    if c <= _tv(tuning, "enemy_t", ENEMY_T) and ok("enemy"):
        return "enemy"
    if c >= _tv(tuning, "friend_t", FRIEND_T) and ok("friend") and base not in ("elder", "junior"):
        # warm a peer/stranger into a friend; keep an authored 长辈/小辈 hierarchy intact
        return "friend"
    return base


# a character only travels WITH the player once there's real rapport — not a stranger you
# just met, and never an enemy. Below FRIEND_T but well above the start (5): you've warmed
# them up over several good exchanges.
FOLLOW_MIN_CLOSENESS = 25


def can_follow(char: dict[str, Any], scores: dict[str, int], tuning: dict | None = None) -> bool:
    """Will this character agree to travel with the player? Needs warmth (closeness ≥ floor,
    or already friend/暧昧/恋人); an enemy always refuses."""
    mode = derive_mode(char, scores, tuning)
    if mode == "enemy":
        return False
    if mode in ("friend", "flirt", "lover"):
        return True
    return int(scores.get("closeness", START_CLOSENESS)) >= _tv(tuning, "follow_min_closeness", FOLLOW_MIN_CLOSENESS)


def next_tier(char: dict[str, Any], scores: dict[str, int], tuning: dict | None = None,
              lang: str = "zh") -> dict[str, Any] | None:
    """The nearest DESIRABLE relationship upgrade this character can still reach, and how
    far off it is — drives the "差一点就到暧昧了" daily-return pull. None if already at the
    top of what's allowed (or only a downgrade like enemy is near)."""
    friend_t = _tv(tuning, "friend_t", FRIEND_T)
    flirt_t = _tv(tuning, "flirt_t", FLIRT_T)
    lover_t = _tv(tuning, "lover_t", LOVER_T)
    allowed = set(allowed_modes(char))
    mode = derive_mode(char, scores, tuning)
    c = int(scores.get("closeness", START_CLOSENESS))
    r = int(scores.get("romance", START_ROMANCE))
    # become FRIENDS first (the natural, non-presumptuous first step) before surfacing a
    # romance step — unless romance is already climbing on its own.
    if "friend" in allowed and mode in ("stranger", "peer") and c < friend_t and r < flirt_t:
        return {"name": name_of("friend", lang), "to_next": max(1, friend_t - c)}
    cands: list[tuple[int, str]] = []
    if "flirt" in allowed and mode in ("stranger", "peer", "friend") and r < flirt_t:
        cands.append((flirt_t - r, "flirt"))
    if "lover" in allowed and mode == "flirt" and r < lover_t:
        cands.append((lover_t - r, "lover"))
    if "friend" in allowed and mode in ("stranger", "peer") and c < friend_t:
        cands.append((friend_t - c, "friend"))
    if not cands:
        return None
    rem, mid = min(cands)
    return {"name": name_of(mid, lang), "to_next": max(1, int(rem))}


def state_for(char: dict[str, Any], scores: dict[str, int], tuning: dict | None = None,
              lang: str = "zh") -> dict[str, Any]:
    """A small summary for the UI / API: current mode + its name + the raw scores + the
    nearest reachable upgrade (the daily 'one more step' hook)."""
    mode = derive_mode(char, scores, tuning)
    return {"mode": mode, "mode_name": name_of(mode, lang),
            "closeness": int(scores.get("closeness", START_CLOSENESS)),
            "romance": int(scores.get("romance", START_ROMANCE)),
            "next": next_tier(char, scores, tuning, lang)}
