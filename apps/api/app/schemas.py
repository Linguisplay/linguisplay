from datetime import date, datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, EmailStr, Field

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
    avatar_url: Optional[str] = None
    subscription_tier: str = "free"


class MePatch(BaseModel):
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None


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
    avatar_url: Optional[str] = None


class Persona(PersonaInput):
    id: str
    is_default: bool = False


# ── stories ───────────────────────────────────────────────
class Character(BaseModel):
    id: Optional[str] = None
    name: str = ""
    role: Optional[str] = None
    is_lead: bool = False
    avatar_url: Optional[str] = None
    persona_text: Optional[str] = None
    background: Optional[str] = None
    # how THIS character reads & expresses emotion (their EQ style) — so empathy stays
    # in-character (a gruff character shows care differently than a warm one). Optional.
    eq_style: Optional[str] = None
    # this character's OWN goal/agenda/stance in the story — what THEY are after,
    # independent of the player. Drives autonomous, self-interested behavior. Optional.
    agenda: Optional[str] = None
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
    appears_from_act: int = 0


class StoryEvent(BaseModel):
    id: Optional[str] = None
    what_happens: str = ""
    who_character_ids: list[str] = []
    linked_secret_ids: list[str] = []
    # ☠️ characters this event kills the moment it fires (authored deaths are final —
    # the engine books them dead, no two-stage ladder)
    kills_character_ids: list[str] = []


class AdvanceCondition(BaseModel):
    """HARD gate for leaving this act → advancing to the next. ALL conditions must be
    met (program-checked, not prompt-driven). If a list is empty / affinity_min 0, that
    sub-condition is vacuously satisfied. An act with NO conditions falls back to soft
    (model/affinity) advance for backward compatibility."""
    required_fragment_ids: list[str] = []   # key info the player MUST have discovered
    required_event_ids: list[str] = []      # plot events that MUST have fired
    affinity_min: int = 0


class ChoiceOption(BaseModel):
    """One selectable answer at a key-moment decision. Picking it applies its effects
    deterministically, then the label is played as the player's own words/action."""
    id: str = ""
    label: str = ""                      # what the player says/does by picking this
    flag: Optional[str] = None           # set state.flags[flag] = True (endings can gate on it)
    affinity_delta: int = 0              # global 好感 effect
    character_id: Optional[str] = None   # optional target for the relationship deltas below
    closeness_delta: int = 0
    romance_delta: int = 0


class ActChoice(BaseModel):
    """An explicit VN-style decision presented when this act begins (关键节点抉择).
    Answered at most once per run; free input stays available alongside it."""
    prompt: str = ""
    options: list[ChoiceOption] = []


class ActTime(BaseModel):
    """⏳ 时间锚点: when this act happens in STORY time. Entering the act snaps the run's
    clock FORWARD to here (never backward), so the 🕐 chip, everyone's 作息 and the prose
    all tell the same hour. day = 第几天 (0 = keep current), slot = 晨/午/夜 ("" = keep)."""
    day: int = 0
    slot: str = ""


class Act(BaseModel):
    id: Optional[str] = None
    index: int = 0
    title: str = ""
    goal: str = ""  # the player's small objective during this act (shown as 🎯 guidance)
    advance: AdvanceCondition = AdvanceCondition()  # hard requirements to leave this act
    events: list[StoryEvent] = []
    choice: Optional[ActChoice] = None  # key-moment explicit decision on entering this act
    time: Optional[ActTime] = None  # ⏳ story-time anchor: 这一幕发生在第几天、什么时段


class LocationUnlock(BaseModel):
    """When this place becomes reachable. ALL conditions ANDed. Empty = available from the
    start. Lets a place stay hidden until the player has learned it exists THIS act (e.g.
    a rooftop only the trusted are shown), instead of every exit being open from turn one."""
    act_min: int = 0
    affinity_min: int = 0
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
    affinity_min: int = 0
    act_min: int = 0  # 0 = only at the final act
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
    title: Optional[str] = None
    cover_url: Optional[str] = None
    one_liner: Optional[str] = None
    synopsis: Optional[str] = None
    world_long: Optional[str] = None
    relations_overview: Optional[str] = None
    world_facts: Optional[str] = None
    trope_tags: Optional[list[str]] = None
    mature: Optional[bool] = None
    visibility: Optional[Literal["private", "public"]] = None
    characters: Optional[list[Character]] = None
    acts: Optional[list[Act]] = None
    endings: Optional[list[Ending]] = None
    locations: Optional[list[Location]] = None
    tuning: Optional[dict] = None  # pacing/balance knob overrides (docs/tuning.md)
    pressure: Optional[dict] = None  # ⚠️ pressure meter {name,hint,ending_id,levels:[{at,note}]}
    clock: Optional[dict] = None  # ⏳ {deadline_day, deadline_text, deadline_ending_id}
    phone: Optional[dict] = None  # 📱 {enabled, device: "手机"|"传呼机"|"口信"…}
    verdict: Optional[dict] = None  # 🔍 {prompt, options, attempts, act_min, fail_ending_id}


class Story(BaseModel):
    id: str
    title: str
    cover_url: Optional[str] = None
    one_liner: Optional[str] = None
    synopsis: Optional[str] = None
    world_long: Optional[str] = None
    relations_overview: Optional[str] = None
    world_facts: Optional[str] = None
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
    clock: Optional[dict] = None
    phone: Optional[dict] = None
    verdict: Optional[dict] = None
    completion: float = 0.0


class StoryCard(BaseModel):
    id: str
    title: str
    cover_url: Optional[str] = None
    one_liner: Optional[str] = None
    trope_tags: list[str] = []
    # the mystery affordance up front: how much is LOCKED in here (counts only, no titles)
    secrets_count: int = 0
    endings_count: int = 0
    characters_count: int = 0


class StoryCardPage(BaseModel):
    items: list[StoryCard]
    next_cursor: Optional[str] = None


# ── secrets / fragments ───────────────────────────────────
class Unlock(BaseModel):
    affinity_min: Optional[int] = None
    act_min: Optional[int] = None
    asks_min: Optional[int] = None
    trigger_event_ids: list[str] = []
    # the player must BE at this place for the fragment to unlock — turns talking-only
    # investigation into go-there exploration (物理探索). None = anywhere.
    location_id: Optional[str] = None


class FragmentInput(BaseModel):
    layer: int = 0
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
    pending_choice: Optional[dict[str, Any]] = None  # an unanswered key-moment decision
    player_character_name: Optional[str] = None  # name of the embodied character (character mode)
    pressure: int = 0                    # ⚠️ story pressure meter value (0~100)
    identity: Optional[str] = None       # 🎖 the player's current 身份 (None = as authored)
    inventory: list[dict[str, Any]] = [] # 🎒 pocket items [{name, detail?}]
    pressure_name: Optional[str] = None  # the meter's authored name (None = story runs none)
    clock: Optional[dict[str, Any]] = None  # ⏳ {day,slot,label,deadline?} (None = no clock)
    promises: list[dict[str, Any]] = []  # 🤝 open appointments [{name,what,when,place,romantic}]
    phone_unread: int = 0  # 📱 unread incoming messages (badge)
    verdict: Optional[dict[str, Any]] = None  # 🔍 the case-closing panel (None until unlocked)


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
    cover_url: Optional[str] = None
    persona_id: str
    last_beat_preview: Optional[str] = None
    unread: bool = False
    updated_at: Optional[datetime] = None
    act: int = 1
    mode: str = "character"
    player_character_name: Optional[str] = None
    ended: bool = False


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


class Beat(BaseModel):
    id: str
    type: Literal["description", "think", "dialogue"] = "description"
    speaker_name: Optional[str] = None
    text: str = ""
    author: str = "engine"
    mood: Optional[str] = None  # 📟 the speaker's judged true inner state (心象仪)


class PlayIn(BaseModel):
    input: str
    channel: Literal["say", "think", "do"] = "say"
    target_character_id: Optional[str] = None  # who the player is addressing (optional)


class MoveIn(BaseModel):
    # destination location: an id or a name (matched leniently against authored locations)
    location: str
    # if a character is leading the player there (accepted a 带去 invite), they travel along
    with_character_id: Optional[str] = None
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


class PhoneSendIn(BaseModel):
    # 📱 a text message the player sends from the 信息 app
    text: str


class VerdictIn(BaseModel):
    # 🔍 the formal accusation the player commits to
    option_id: str
