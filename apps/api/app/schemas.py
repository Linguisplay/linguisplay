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


class AdvanceCondition(BaseModel):
    """HARD gate for leaving this act → advancing to the next. ALL conditions must be
    met (program-checked, not prompt-driven). If a list is empty / affinity_min 0, that
    sub-condition is vacuously satisfied. An act with NO conditions falls back to soft
    (model/affinity) advance for backward compatibility."""
    required_fragment_ids: list[str] = []   # key info the player MUST have discovered
    required_event_ids: list[str] = []      # plot events that MUST have fired
    affinity_min: int = 0


class Act(BaseModel):
    id: Optional[str] = None
    index: int = 0
    title: str = ""
    goal: str = ""  # the player's small objective during this act (shown as 🎯 guidance)
    advance: AdvanceCondition = AdvanceCondition()  # hard requirements to leave this act
    events: list[StoryEvent] = []


class Location(BaseModel):
    """A concrete physical place in the story world. `detail` should name specific,
    sensible fixtures/objects (not vague mood) so narration stays grounded; `exits` lists
    the names of adjacent places the player can move to. Spoiler-safe."""
    id: Optional[str] = None
    name: str = ""
    detail: str = ""  # concrete fixtures/props/layout/lighting at this place
    exits: list[str] = []  # names of places reachable from here


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
    completion: float = 0.0


class StoryCard(BaseModel):
    id: str
    title: str
    cover_url: Optional[str] = None
    one_liner: Optional[str] = None
    trope_tags: list[str] = []


class StoryCardPage(BaseModel):
    items: list[StoryCard]
    next_cursor: Optional[str] = None


# ── secrets / fragments ───────────────────────────────────
class Unlock(BaseModel):
    affinity_min: Optional[int] = None
    act_min: Optional[int] = None
    asks_min: Optional[int] = None
    trigger_event_ids: list[str] = []


class FragmentInput(BaseModel):
    layer: int = 0
    content: str = ""
    retrieval_key: Optional[str] = None
    known_by_character_ids: list[str] = []
    unlock: Unlock = Unlock()


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


class Run(BaseModel):
    id: str
    story_id: str
    story_version: int
    persona_id: str
    state: RunState
    cast: list[dict[str, Any]] = []  # [{id, name, is_lead, avatar_url}] for the play UI
    created_at: Optional[datetime] = None


class RunSummary(BaseModel):
    id: str
    story_id: str
    story_title: str
    cover_url: Optional[str] = None
    persona_id: str
    last_beat_preview: Optional[str] = None
    unread: bool = False
    updated_at: Optional[datetime] = None


class RunCreate(BaseModel):
    story_id: str
    persona_id: str
    # "character" = embody one of the story's characters; "god" = invisible observer
    # (watch the cast interact with each other — the 旁观/CP mode).
    mode: Literal["character", "god"] = "character"
    player_character_id: Optional[str] = None  # which character you play (character mode)


class Beat(BaseModel):
    id: str
    type: Literal["description", "think", "dialogue"] = "description"
    speaker_name: Optional[str] = None
    text: str = ""
    author: str = "engine"


class PlayIn(BaseModel):
    input: str
    channel: Literal["say", "think", "do"] = "say"
    target_character_id: Optional[str] = None  # who the player is addressing (optional)
