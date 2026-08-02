from datetime import date, datetime
from typing import Annotated, Any, Literal, Optional

from pydantic import BaseModel, BeforeValidator, EmailStr, Field


# 🛡 作者填的数字槽一律宽收 (实弹 2026-07-19: 手机上 type=number 可输任意文本 →
# 前端 parseInt→NaN→JSON null → 一格烂输入 422 掉整本剧本的保存)。
# None/""/垃圾 → 默认值, 绝不让格式炸掉保存; 语义默认 0 = 该门槛不生效, 保守无害。
def _lax_int(v: Any) -> Any:
    if v is None or v == "":
        return 0
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def _lax_opt_int(v: Any) -> Any:
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


LaxInt = Annotated[int, BeforeValidator(_lax_int)]
LaxOptInt = Annotated[Optional[int], BeforeValidator(_lax_opt_int)]


# 🔒 作者可填的资产 URL: 只认【本站相对路径】, 其余一律清成 None (存储型 XSS 第二道闸;
# 第一道是前端转义 tests/client_units.test.js)。实弹 2026-08-02 审查:
# avatar_url 零校验 + 前端 src="${...}" 直插属性 = 已发布剧本的作者可在其他玩家
# 浏览器里执行 JS。清洗而不抛错 — 本模型入库出库共用, 抛错会让库里已有的脏行
# 整本读不出 (500); 清洗则恶意值进不了库、老脏行也读得出且无害。
def _safe_asset_url(v: Any) -> Any:
    if v is None or v == "":
        return v
    s = str(v).strip()
    # 必须以单个 / 开头 (「//host」是协议相对地址, 会跳站外), 且不含引号/尖括号/
    # 反斜杠/控制字符 (属性逃逸与伪协议的载体), 也不许 .. 穿越
    if not s.startswith("/") or s.startswith("//"):
        return None
    if any(c in s for c in '"\'<>\\ \t\n\r') or ".." in s:
        return None
    return s


AssetUrl = Annotated[Optional[str], BeforeValidator(_safe_asset_url)]

# ── auth ──────────────────────────────────────────────────
class SignupIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    dob: date
    accepted_tos: bool


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class ResetIn(BaseModel):
    email: EmailStr


class SessionUser(BaseModel):
    id: str
    email: str
    display_name: Optional[str] = None


# ── me ────────────────────────────────────────────────────
class Me(BaseModel):
    id: str
    email: str
    display_name: Optional[str] = None
    avatar_url: AssetUrl = None
    subscription_tier: str = "free"


class MePatch(BaseModel):
    display_name: Optional[str] = None
    avatar_url: AssetUrl = None


class Settings(BaseModel):
    content_level: Literal["mild", "moderate", "mature"] = "mild"
    notifications_enabled: bool = True
    default_privacy_private: bool = True


class ContentLevelIn(BaseModel):
    content_level: Literal["mild", "moderate", "mature"]
    tropes: list[str] = []


# ── personas ──────────────────────────────────────────────
class PersonaInput(BaseModel):
    name: str
    pronouns: Optional[Literal["she", "they", "he", "custom"]] = None
    pronouns_custom: Optional[str] = None
    tagline: Optional[str] = None
    background: Optional[str] = None
    avatar_url: AssetUrl = None


class Persona(PersonaInput):
    id: str
    is_default: bool = False


# ── stories ───────────────────────────────────────────────
class Character(BaseModel):
    id: Optional[str] = None
    name: str = ""
    role: Optional[str] = None
    is_lead: bool = False
    avatar_url: AssetUrl = None
    persona_text: Optional[str] = None
    background: Optional[str] = None
    # ── 🎭 角色卡 v2 (剧组重建 P0, docs/troupe-design.md) ──
    # 性别: 称呼与代词（他/她、哥/姐）从卡上走，不再让模型从名字猜。
    # 班底多样性由 linter 守卫（性别混合/年龄跨度），生成合同同规。
    # 🗣 语言指纹 (2026-07-26 情商军令): 句长习惯/口头禅/绝不说的词/标点脾气 —
    # 「像一个人」与「像AI演一个人」的分水岭; 台词范例给腔调, 指纹给规律
    voice_print: Optional[str] = None
    # 🎬 表演指纹 v3 (2026-07-26 Yi: 把「细腻」拆成可执行锚点; 和 voice_print 同哲学, 但管
    # 动作/感官/描写而非台词): 每角色一套, 生成点注入, 亲密/情感高光拍放满、日常轻描。
    # 冷/钝的人就该快就该钝——是每角色的指纹, 绝不做全局规则。
    act_pace: Optional[str] = None        # 行动节奏: 分阶段推进有确认 | 利落一步到位 | 冲动急促
    sense_focus: Optional[str] = None     # 感官侧重: 触觉/视觉/听觉 哪种主导、更常被描写
    emote_form: Optional[str] = None      # 情感表达形式: 动作暗示+内心独白 | 直球说出口 | 只做事不表达
    # 🧩 已确知 (2026-07-26 治「角色现编不该知道的私事」如周三休假): 授权此角色确切知道的、
    # 关于玩家/局势的事实。模型只能读、不能编; 此外只认玩家在对话里亲口说过的。留空=只认对话。
    known_facts: Optional[str] = None
    gender: Optional[str] = None          # 男 | 女 | 其他
    age_band: Optional[str] = None        # 少年 | 青年 | 中年 | 老年
    # 🎙 配音选角 {"id": CosyVoice音色名, "speed": 语速}: 语气音精灵按 id 取
    # /scene/voice/<id>/ 下的短音频; 台词播放键按 id+speed 现场合成。缺省 = 无配音,
    # 全链路静默降级 (玩家可扮角色按 galgame 惯例不配)。选角只是演出层, 不进正史。
    voice: dict[str, Any] = {}
    # 🐱 非人角色的物种 (猫/犬/龙…): 立绘与头像提示词据此换词——「男性青年」对猫角色
    # 会召唤出人类身影 (猫铃堂实弹: 布偶猫背后站了个男青年)
    species: Optional[str] = None
    # 性格三轴 (1~5, 3=中): 给导演排冲突/排主动权用的可推理量; 散文人设仍是主体
    traits: dict[str, int] = {}           # {外向, 温度, 主导}
    fear: Optional[str] = None            # 软肋一句 (冲突的抓手)
    line: Optional[str] = None            # 底线一句 (一推就破的角色不可信)
    # 人生当前目标的授权起点: {text, stage?, obstacle?} — 运行时在 char_sim.agenda
    # 长成活台账 (stage/obstacle/log 由引擎推进); 缺省时回落 wants/agenda
    life_goal: dict[str, Any] = {}
    # how THIS character reads & expresses emotion (their EQ style) — so empathy stays
    # in-character (a gruff character shows care differently than a warm one). Optional.
    eq_style: Optional[str] = None
    # this character's OWN goal/agenda/stance in the story — what THEY are after,
    # independent of the player. Drives autonomous, self-interested behavior. Optional.
    agenda: Optional[str] = None
    # 🎯 想办成的事: seeds the ENGINE-OWNED live agenda (char_sim.agenda.goal). The
    # offscreen tick advances it between scenes and dialogue remembers the latest step.
    # `agenda` above is the legacy static alias; `wants` wins when both are set.
    wants: Optional[str] = None
    # 💘 防御风格 (courtship-resistance style): 傲娇/冷感慢热/回避型/占有欲/直球 (id or
    # 中文名; see engine/relationships.LOVE_STYLES). Engine schedules the push-pull:
    # after a warm spike the character pulls back at the NEXT meeting. Optional.
    love_style: Optional[str] = None
    # 分层小传: [{closeness_min, text}] — closeness unlocks the character's backstory
    # layer by layer (getting to KNOW someone is itself the collection loop)
    bio_layers: list[dict[str, Any]] = []
    # 🎒 starting pocket items when the player EMBODIES this character: [{name, detail}]
    items: list[dict[str, Any]] = []
    # 作息表: where this character is per act — [{from_act, location_id}], last entry with
    # from_act <= current act wins; falls back to home_location_id. Makes the world move.
    schedule: list[dict[str, Any]] = []
    # 🕸 authored NPC↔NPC stances seeding the live relationship web:
    # [{char_id, stance -2..2, label?}] — see engine/runtime._ensure_npc_rel
    ties: list[dict[str, Any]] = []
    # relationship mode toward the player: the starting archetype (e.g. "陌生人"/"长辈"/
    # "暧昧对象") and which archetypes it may FLOW into. Empty allowed = any. See
    # engine/relationships.py for the library.
    relation_default: Optional[str] = None
    relation_allowed: list[str] = []
    # the place this character is normally found (a Location id). The player only meets them
    # by being at this location (or after inviting them to follow). Empty/unset = ubiquitous:
    # present in every scene of their act (backward-compatible old behavior).
    home_location_id: Optional[str] = None
    # whether the player may EMBODY this character (character mode). The story is authored
    # from the protagonist's POV, so antagonists/late-arrivals usually aren't playable —
    # picking them breaks the plot. If NO character in a story is flagged playable, the
    # engine falls back to "any present character" (legacy behavior, no regression).
    playable: bool = False
    # auto-generated background knowledge ("智能增强"): a structured lore block the model
    # can draw on for this character (IP setting, era, relations, signature details).
    knowledge: Optional[str] = None
    relations: list[dict[str, Any]] = []
    linked_event_ids: list[str] = []
    # presence in the scene: "present" = a live, addressable participant; "offstage" =
    # exists in the story (can own secrets / be referenced / haunt) but is NOT in the room
    # to be talked to normally (e.g. a ghost, an absent person).
    presence: Literal["present", "offstage"] = "present"
    # if >0, this character only becomes present from that act onward (a later entrance).
    appears_from_act: LaxInt = 0
    # 📚 provenance: imported from this library card (COPY semantics — editing the card
    # later never mutates this story). None = authored directly in the story.
    source_card_id: Optional[str] = None
    # 台词范例 carried from the card: lines that ARE this voice (future mes_example hook;
    # kept in the schema so publish doesn't silently drop them)
    examples: list[str] = []
    # 🎙 作者写定的开场白 (Yi 2026-07-21): 开场时TA对玩家说的第一句话 — 引擎原样上台,
    # 模型只围绕它写动作; 空 = 模型即兴
    opening_line: str = ""
    # 🏛 所属阵营 id (story.factions 里的) — 声望底色随阵营, 个人恩怨仍归关系双轴
    faction_id: Optional[str] = None
    # 📱🔍 authored 设备素材 (查TA手机时深翻可见): [{with, msgs:[..], reveals?: fragment_id}]
    # — 悬疑本的关键证物写死在这, 既是叙事又可触发碎片解锁
    device_peek: list[dict[str, Any]] = []


class CharacterCardInput(BaseModel):
    """📚 角色卡库 payload: the PORTABLE persona subset of Character — everything about
    who they are, nothing about where they stand in a particular story (no schedule/
    ties/home_location/presence: those are authored after import, per story)."""
    name: str = ""
    role: Optional[str] = None
    persona_text: Optional[str] = None
    background: Optional[str] = None
    eq_style: Optional[str] = None
    voice_print: Optional[str] = None   # 🗣 语言指纹随卡走 (卡库往返不丢腔调)
    act_pace: Optional[str] = None      # 🎬 表演指纹: 行动节奏
    sense_focus: Optional[str] = None   # 🎬 表演指纹: 感官侧重
    emote_form: Optional[str] = None    # 🎬 表演指纹: 情感表达形式
    known_facts: Optional[str] = None   # 🧩 已确知: 授权的玩家/局势事实 (防现编)
    agenda: Optional[str] = None
    knowledge: Optional[str] = None
    bio_layers: list[dict[str, Any]] = []
    items: list[dict[str, Any]] = []
    # 台词范例 (mes_example-style few-shot): lines that ARE this character's voice
    examples: list[str] = []
    visibility: Literal["private", "public"] = "private"


class CharacterCard(CharacterCardInput):
    id: str
    avatar_url: AssetUrl = None
    updated_at: Optional[datetime] = None
    author: Optional[str] = None   # 🌐 广场: who shared this card (display name)
    mine: bool = True              # whether the requesting user owns it


class StoryEvent(BaseModel):
    id: Optional[str] = None
    what_happens: str = ""
    who_character_ids: list[str] = []
    linked_secret_ids: list[str] = []
    # ☠️ characters this event kills the moment it fires (authored deaths are final —
    # the engine books them dead, no two-stage ladder)
    kills_character_ids: list[str] = []
    # 📱🔍 authored 机会窗口: 事件落地时该角色的设备就搁在手边 (确定性开窗, 不掷骰)
    peek_cid: Optional[str] = None


class AdvanceCondition(BaseModel):
    """HARD gate for leaving this act → advancing to the next. ALL conditions must be
    met (program-checked, not prompt-driven). If a list is empty / affinity_min 0, that
    sub-condition is vacuously satisfied. An act with NO conditions falls back to soft
    (model/affinity) advance for backward compatibility."""
    required_fragment_ids: list[str] = []   # key info the player MUST have discovered
    required_event_ids: list[str] = []      # plot events that MUST have fired
    affinity_min: LaxInt = 0


class ChoiceOption(BaseModel):
    """One selectable answer at a key-moment decision. Picking it applies its effects
    deterministically, then the label is played as the player's own words/action."""
    id: str = ""
    label: str = ""                      # what the player says/does by picking this
    flag: Optional[str] = None           # set state.flags[flag] = True (endings can gate on it)
    affinity_delta: LaxInt = 0              # global 好感 effect
    character_id: Optional[str] = None   # optional target for the relationship deltas below
    closeness_delta: LaxInt = 0
    romance_delta: LaxInt = 0


class ActChoice(BaseModel):
    """An explicit VN-style decision presented when this act begins (关键节点抉择).
    Answered at most once per run; free input stays available alongside it."""
    prompt: str = ""
    options: list[ChoiceOption] = []


class ActTime(BaseModel):
    """⏳ 时间锚点: when this act happens in STORY time. Entering the act snaps the run's
    clock FORWARD to here (never backward), so the 🕐 chip, everyone's 作息 and the prose
    all tell the same hour. day = 第几天 (0 = keep current), slot = 晨/午/夜 ("" = keep)."""
    day: LaxInt = 0
    slot: str = ""


class Act(BaseModel):
    id: Optional[str] = None
    index: LaxInt = 0
    title: str = ""
    goal: str = ""  # the player's small objective during this act (shown as 🎯 guidance)
    # 🎬 情节底稿 (Yi 2026-07-25): 作者想让这一幕发生的情节走向 (自由文本) —
    # 喂给导演当路标不当轨道: 顺着玩家的回应自然引出, 玩家不接就换个方式再引
    script: str = ""
    advance: AdvanceCondition = AdvanceCondition()  # hard requirements to leave this act
    events: list[StoryEvent] = []
    choice: Optional[ActChoice] = None  # key-moment explicit decision on entering this act
    time: Optional[ActTime] = None  # ⏳ story-time anchor: 这一幕发生在第几天、什么时段


class LocationUnlock(BaseModel):
    """When this place becomes reachable. ALL conditions ANDed. Empty = available from the
    start. Lets a place stay hidden until the player has learned it exists THIS act (e.g.
    a rooftop only the trusted are shown), instead of every exit being open from turn one."""
    act_min: LaxInt = 0
    affinity_min: LaxInt = 0
    required_fragment_ids: list[str] = []  # info the player must have uncovered first


class LocationProp(BaseModel):
    """A searchable fixture at a place (现场物证). Examining/searching it BY NAME while
    standing here yields its payload: unlock a fragment (the physical evidence) and/or
    trigger a story event. `detail` is what turning it over reveals when it carries no
    clue (or as extra color). Names are concrete nouns the author wrote — spoiler-safe."""
    id: Optional[str] = None
    name: str = ""
    detail: str = ""
    fragment_id: Optional[str] = None  # unlocks this fragment when searched
    event_id: Optional[str] = None     # triggers this story event when searched
    take: bool = False  # 搜到即入包 (可拿走)。2026-07-15 补: schema 缺此字段时,
    #                     API 编辑过的剧本 round-trip 会把种子里的 take 静默剥掉


class Location(BaseModel):
    """A concrete physical place in the story world. `detail` should name specific,
    sensible fixtures/objects (not vague mood) so narration stays grounded; `exits` lists
    the names of adjacent places the player can move to. Spoiler-safe."""
    id: Optional[str] = None
    name: str = ""
    detail: str = ""  # concrete fixtures/props/layout/lighting at this place
    exits: list[str] = []  # names of places reachable from here
    unlock: LocationUnlock = LocationUnlock()  # gate: appears only once these are met
    props: list["LocationProp"] = []  # searchable physical evidence at this place


class EndingCondition(BaseModel):
    """All conditions ANDed. By default an ending is only eligible at the final act;
    set act_min to make it eligible earlier. required_fragment_ids must all be unlocked."""
    affinity_min: LaxInt = 0
    act_min: LaxInt = 0  # 0 = only at the final act
    required_fragment_ids: list[str] = []
    required_flags: dict[str, Any] = {}


class Ending(BaseModel):
    id: Optional[str] = None
    kind: Literal["true", "normal", "bad", "death"] = "normal"
    # non-empty = this ending never fires from normal condition matching; it's invoked
    # only by the named mechanism (e.g. "pressure" = the meter blowing out at 100)
    trigger: Optional[str] = None
    title: str = ""
    text: str = ""  # the closing narration shown to the player
    condition: EndingCondition = EndingCondition()


class StoryInput(BaseModel):
    # 🔒 乐观锁: 客户端载入草稿时拿到的 updated_at 原样回传; 服务器不一致就 409,
    # 拒绝"旧快照整本盖新草稿"。不传 = 老客户端, 放行 (渐进启用)。
    if_rev: Optional[str] = None
    title: Optional[str] = None
    # "zh" | "en" — the language the engine performs this story in (output directive +
    # localized deterministic narration). Default zh keeps every existing story unchanged.
    language: Optional[str] = None
    cover_url: AssetUrl = None
    one_liner: Optional[str] = None
    synopsis: Optional[str] = None
    world_long: Optional[str] = None
    relations_overview: Optional[str] = None
    world_facts: Optional[str] = None
    style: Optional[str] = None  # ✍️ 文风: source work's narrative voice
    trope_tags: Optional[list[str]] = None
    mature: Optional[bool] = None
    visibility: Optional[Literal["private", "public"]] = None
    characters: Optional[list[Character]] = None
    acts: Optional[list[Act]] = None
    endings: Optional[list[Ending]] = None
    locations: Optional[list[Location]] = None
    tuning: Optional[dict] = None  # pacing/balance knob overrides (docs/tuning.md)
    pressure: Optional[dict] = None  # ⚠️ pressure meter {name,hint,ending_id,levels:[{at,note}]}
    threat: Optional[dict] = None  # 🦇 hunter {char_id,patrol,senses,cannot_enter,return_to,ladder,cues}
    dooms: Optional[list] = None  # 🚪 [{id,day,char_id,to,text,warn_text,prevented_text,prevent}]
    sanity: Optional[dict] = None  # 🧠 {enabled,name,start,regen,ending_id}
    rules: Optional[list] = None  # 📜 规则怪谈 [{id,text,when,violate,consequence}]
    clock: Optional[dict] = None  # ⏳ {deadline_day, deadline_text, deadline_ending_id}
    phone: Optional[dict] = None  # 📱 {enabled, device: "手机"|"传呼机"|"口信"…}
    verdict: Optional[dict] = None  # 🔍 {prompt, options, attempts, act_min, fail_ending_id}
    sandbox: Optional[dict] = None  # 🏖 {enabled, real_time} 无尽沙盒：玩家开局自定义世界观
    # 🐲 生物账本: [{id,name,kind,desc,killable,menace,lair,territory,habits,drops,speech}]
    creatures: Optional[list] = None
    # 🏛 阵营: [{id,name,detail,rivals:[id]}] — 权谋/宫斗/帮派的声望地基
    factions: Optional[list] = None
    # 🎬 作者亲笔开场白 (Yi 2026-07-25): 开场的第一段旁白原样上台; 空 = AI 即兴
    opening: Optional[str] = None


class Story(BaseModel):
    id: str
    title: str
    # 🔒 乐观锁票据 (透明字符串, 进快照 JSON 也安全): 草稿最后一次改动的时刻 —
    # 客户端保存时回传 if_rev, 不一致 409 (实弹: 陈旧标签页整本覆盖回滚了修好的草稿)
    updated_at: Optional[str] = None
    language: str = "zh"
    cover_url: AssetUrl = None
    one_liner: Optional[str] = None
    synopsis: Optional[str] = None
    world_long: Optional[str] = None
    relations_overview: Optional[str] = None
    world_facts: Optional[str] = None
    style: str = ""  # ✍️ 文风
    trope_tags: list[str] = []
    mature: bool = False
    visibility: str = "private"
    status: str = "draft"
    version: int = 0
    characters: list[Character] = []
    acts: list[Act] = []
    endings: list[Ending] = []
    locations: list[Location] = []
    tuning: dict = {}
    pressure: Optional[dict] = None
    threat: Optional[dict] = None
    dooms: Optional[list] = None
    sanity: Optional[dict] = None
    rules: Optional[list] = None
    clock: Optional[dict] = None
    phone: Optional[dict] = None
    verdict: Optional[dict] = None
    sandbox: Optional[dict] = None
    creatures: Optional[list] = None   # 🐲 生物账本
    factions: Optional[list] = None    # 🏛 阵营声望
    opening: Optional[str] = None      # 🎬 作者亲笔开场白
    completion: float = 0.0


class StoryCard(BaseModel):
    id: str
    title: str
    cover_url: AssetUrl = None
    one_liner: Optional[str] = None
    trope_tags: list[str] = []
    # 🎬 大厅门面 (hero 卡): 卡面图 (自动封面宽幅→作者封面→首个有图地点兜底) 与开场白引子
    art_url: Optional[str] = None
    opening_tease: Optional[str] = None
    # 🎴 自动封面的竖版盒绘 (班底站中间 + 烫了标题的成品)。大厅卡用宽幅那张,
    # 这张给选角页/工坊/分享 —— 它是"这本书"本身, 不是卡面的背景板。
    poster_url: Optional[str] = None
    # the mystery affordance up front: how much is LOCKED in here (counts only, no titles)
    secrets_count: int = 0
    endings_count: int = 0
    characters_count: int = 0
    # 分型 (docs/ux-design.md P0): a sandbox plays nothing like an authored story —
    # the card must say which game this is, or players hunt story characters in sandboxes
    sandbox: bool = False
    acts_count: int = 0
    progression: Optional[str] = None  # sandbox growth ladder, e.g. 生面人 → … → 城寨王


class StoryCardPage(BaseModel):
    items: list[StoryCard]
    next_cursor: Optional[str] = None


# ── secrets / fragments ───────────────────────────────────
class Unlock(BaseModel):
    affinity_min: LaxOptInt = None
    act_min: LaxOptInt = None
    asks_min: LaxOptInt = None
    # 📱🔍 藏在TA设备里 (查手机玩法的碎片通道): 深翻该角色的设备即解锁。
    # lint 强制它必须有备用通路 (crit_fail 会永久锁设备, 不能锁死整本)
    device_of: Optional[str] = None
    trigger_event_ids: list[str] = []
    # the player must BE at this place for the fragment to unlock — turns talking-only
    # investigation into go-there exploration (物理探索). None = anywhere.
    location_id: Optional[str] = None


class FragmentInput(BaseModel):
    # authored/stable id (optional): cross-references (act gates, location props/unlocks,
    # ending conditions) point at fragment ids, so authors may pin them; empty = generated
    id: Optional[str] = None
    layer: LaxInt = 0
    content: str = ""
    retrieval_key: Optional[str] = None
    known_by_character_ids: list[str] = []
    unlock: Unlock = Unlock()
    # 🗣 the AUTHORED cover story: told (consistently, by every knower) while this
    # layer is locked; the truth replaces it on unlock; a confront shatters it
    cover: Optional[str] = None


class Fragment(FragmentInput):
    id: str


class SecretInput(BaseModel):
    character_id: Optional[str] = None
    title: str = ""
    sensitivity: Literal["light", "medium", "heavy"] = "light"
    fragments: list[FragmentInput] = []


class Secret(BaseModel):
    id: str
    character_id: Optional[str] = None
    title: str = ""
    sensitivity: str = "light"
    fragments: list[Fragment] = []


class PublishResult(BaseModel):
    story_id: str
    version: int


# ── runs / play ───────────────────────────────────────────
class RunState(BaseModel):
    act: int = 1
    affinity: int = 0
    flags: dict[str, Any] = {}
    unlocked_fragment_ids: list[str] = []
    scene: Optional[dict[str, Any]] = None
    ended: bool = False
    ending: Optional[dict[str, Any]] = None  # {kind, title, text} when the run has concluded
    mode: str = "character"
    player_character_id: Optional[str] = None
    goal: str = ""  # the player's current small objective (this act)
    progress: Optional[dict[str, Any]] = None  # clue checklist {items, done, total}
    location: Optional[dict[str, Any]] = None  # where the player is now {id,name,detail,exits}
    relations: dict[str, Any] = {}  # {char_id:{mode,mode_name,closeness,romance}} toward player
    following: list[str] = []  # character ids currently traveling WITH the player
    here: list[dict[str, Any]] = []  # characters in the player's CURRENT scene [{id,name,...}]
    beasts: list[dict[str, Any]] = []  # 🐲 creatures in the scene (standee + HUD)
    factions: list[dict[str, Any]] = []  # 🏛 玩家已有名声的阵营 [{id,name,value,label}]
    taste: list[dict[str, Any]] = []     # 🧭 口味分布 [{k,w}] (归一化, 验证/UI用)
    pending_choice: Optional[dict[str, Any]] = None  # an unanswered key-moment decision
    player_character_name: Optional[str] = None  # name of the embodied character (character mode)
    pressure: int = 0                    # ⚠️ story pressure meter value (0~100)
    identity: Optional[str] = None       # 🎖 the player's current 身份 (None = as authored)
    inventory: list[dict[str, Any]] = [] # 🎒 pocket items [{name, detail?}]
    pressure_name: Optional[str] = None  # the meter's authored name (None = story runs none)
    threat: Optional[dict[str, Any]] = None  # 🦇 {name,band,alert} the hunter as felt (or None)
    sanity: Optional[dict[str, Any]] = None  # 🧠 {name,value,max,label} (or None)
    clock: Optional[dict[str, Any]] = None  # ⏳ {day,slot,label,deadline?} (None = no clock)
    promises: list[dict[str, Any]] = []  # 🤝 open appointments [{name,what,when,place,romantic}]
    player_events: list[dict[str, Any]] = []  # 🗓 玩家自己的行程 [{id,text,day,slot,told,when,passed}]
    player_notes: list[dict[str, Any]] = []   # 📔 玩家备忘录 [{id,text}] — 叙事罗盘
    phone_unread: int = 0  # 📱 unread incoming messages (badge)
    phone_on: bool = True  # 📵 false = this story has no signal (texting/calls/mail dead)
    verdict: Optional[dict[str, Any]] = None  # 🔍 the case-closing panel (None until unlocked)
    cultivation: Optional[dict[str, Any]] = None  # ⚡ {name, rank, prog, ready} story ladder
    attrs: Optional[dict[str, int]] = None  # 🎯 五维 {力量,敏捷,体质,心思,气运} 1~10
    player_hp: str = "healthy"  # 💀 sandbox: healthy/hurt/dying/dead（dead = 说/做被剥夺）
    money: Optional[int] = None  # 💰 cash balance (None = this run keeps no ledger)
    currency: Optional[str] = None  # 💰 what money is called in this world
    quests: list[dict[str, Any]] = []  # 📋 [{title,reward,deadline_day,giver,status}]
    can_reincarnate: bool = False  # 🔄 dead in a sandbox → the world offers a second life
    powers: list[str] = []  # ✨ 金手指 the world acknowledges as real


class Run(BaseModel):
    id: str
    story_id: str
    story_version: int
    persona_id: str
    state: RunState
    cast: list[dict[str, Any]] = []  # [{id, name, is_lead, avatar_url}] for the play UI
    created_at: Optional[datetime] = None
    # arrival discoveries from a /move (走到对的地方，真相当场揭开) — [{title, text}]
    discoveries: list[dict[str, Any]] = []
    # fresh next-step chips for the scene just entered (only set by /move)
    suggestions: list[str] = []


class RunSummary(BaseModel):
    id: str
    story_id: str
    story_title: str
    cover_url: AssetUrl = None
    persona_id: str
    last_beat_preview: Optional[str] = None
    unread: bool = False
    updated_at: Optional[datetime] = None
    act: int = 1
    mode: str = "character"
    player_character_name: Optional[str] = None
    ended: bool = False
    # 🎬 存档卡视觉化 (Yi): 最后停留的场景 + 在场的脸 — 存档长什么样, 打开前就看得见
    scene_bg: Optional[str] = None      # /scene/bg/<lid>.jpg (文件真存在才给)
    scene_name: Optional[str] = None
    faces: list[dict] = []              # [{id, name, avatar}] ≤3, 有头像的优先
    # 🎵 进档那一屏的演出单 {bgm, cue, mood, tint}。以前 direct 只在回合流里发,
    # 于是新开一档【第一屏是没有音乐的】—— 得等玩家打完第一个回合才响。开场曲就是这么没的。
    direct: dict[str, Any] = {}


class CalendarIn(BaseModel):
    """🗓 玩家往自己日历上记一笔行程"""
    text: str = ""
    day: int = 1
    slot: str = ""      # "" = 全天, 或 晨/午/夜
    told: str = "all"   # all = 角色们知道会关心; none = 私密备忘, 绝不入戏


class NoteIn(BaseModel):
    """📔 玩家备忘录: 一条笔记 (新增/改写共用)"""
    text: str = ""


class GoalIn(BaseModel):
    """🎯 沙盒玩家目标: text=自己写 (空串=撤下), roll=让引擎随机推荐一个"""
    text: Optional[str] = None
    roll: bool = False


class RunCreate(BaseModel):
    story_id: str
    persona_id: str
    # "character" = embody one of the story's characters; "god" = invisible observer
    # (watch the cast interact with each other — the 旁观/CP mode).
    mode: Literal["character", "god"] = "character"
    player_character_id: Optional[str] = None  # which character you play (character mode)
    # 🌱 NG+ start perk ("veteran" | "instinct"); only honored once this story has been
    # completed (any ending reached) by this user at least once
    perk: Optional[str] = None
    # 🃏 a character card (from the cross-run collection) to carry into this run —
    # an old acquaintance from a previous life walks back in. NG+ only.
    carry_card_id: Optional[str] = None
    # 🏖 sandbox only: the worldview the player defines at run start (their private
    # copy of the story runs on it; ignored for normal authored stories)
    worldview: str = ""
    # 🔞 sandbox only: per-run 18+ opt-in (players are already DOB-gated 18+ at signup;
    # authored stories keep using their story-level mature flag instead)
    mature: bool = False
    # ✨ sandbox only: the player's declared 金手指 (one per line, ≤4) — abilities THIS
    # world acknowledges as real; empty = the story's default powers (if authored)
    powers: str = ""


class Beat(BaseModel):
    id: str
    seq: int = 0   # turn ordering; player beats double as 回溯 rewind points
    type: Literal["description", "think", "dialogue"] = "description"
    speaker_name: Optional[str] = None
    text: str = ""
    author: str = "engine"
    mood: Optional[str] = None  # 📟 the speaker's judged true inner state (心象仪)


class PlayIn(BaseModel):
    input: str
    channel: Literal["say", "think", "do", "drive"] = "say"  # drive = ▶ 看下去 (director advances)
    target_character_id: Optional[str] = None  # who the player is addressing (optional)
    client_turn_id: Optional[str] = None  # 🎫 幂等键: 每次点击唯一, 重放的请求不再推进剧情


class MarketBuyIn(BaseModel):
    item_id: str


class RewindIn(BaseModel):
    """重说/回溯: rewind the run to how it stood before a player turn. seq omitted →
    the latest player turn (the 重说 button); explicit seq → that turn (长按回溯)."""
    seq: Optional[int] = None


class MoveIn(BaseModel):
    # destination location: an id or a name (matched leniently against authored locations)
    location: str
    # if a character is leading the player there (accepted a 带去 invite), they travel along
    with_character_id: Optional[str] = None
    # 🚶 present characters the player chose to bring along on this trip (each gated by 好感
    # while still in the current scene, before we move); refusers are reported back
    bring: list[str] = []
    # True = this place is NOT on the authored map yet; it emerged in play and should be
    # generated on the fly (name → concrete detail), wired in, and moved to.
    generate: bool = False


class FollowIn(BaseModel):
    character_id: str
    follow: bool = True  # True = invite to travel with you; False = part ways


class ChooseIn(BaseModel):
    option_id: str  # the picked ChoiceOption.id of the run's pending choice


class ConfrontIn(BaseModel):
    # 🃏 证据对峙: present an UNLOCKED fragment to the character its secret belongs to
    fragment_id: str
    character_id: str


class RenameIn(BaseModel):
    # 🪪 player renames an EMERGENT character (fix bad births like「谁看见」)
    name: str


class PhoneSendIn(BaseModel):
    # 📱 a text message the player sends from the 信息 app
    text: str


class TTSIn(BaseModel):
    # 🎙 台词播放键: which character says the line + the exact line text.
    # 服务端按角色卡 voice 字段选音色; 文本超长截断 (engine/voice.MAX_CHARS)。
    speaker_name: str
    text: str


class TransferIn(BaseModel):
    # 🏦 银行转账: 给角色打钱 (真钱落账, TA 会有反应)
    char_id: str
    amount: LaxInt = 0


class SocialLikeIn(BaseModel):
    post_id: str


class SocialCommentIn(BaseModel):
    post_id: str
    text: str


class VerdictIn(BaseModel):
    # 🔍 the formal accusation the player commits to
    option_id: str
