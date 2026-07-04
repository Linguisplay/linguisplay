import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    dob: Mapped[datetime] = mapped_column(DateTime)
    accepted_tos: Mapped[bool] = mapped_column(Boolean, default=False)

    display_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    subscription_tier: Mapped[str] = mapped_column(String(32), default="free")

    # settings
    content_level: Mapped[str] = mapped_column(String(16), default="mild")
    tropes: Mapped[list] = mapped_column(JSON, default=list)
    notifications_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    default_privacy_private: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    personas: Mapped[list["Persona"]] = relationship(
        back_populates="owner", cascade="all, delete-orphan"
    )


class Persona(Base):
    """A player 'mask'. Run storage key = (user, persona, story_version)."""

    __tablename__ = "personas"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)

    name: Mapped[str] = mapped_column(String(120))
    pronouns: Mapped[str | None] = mapped_column(String(16), nullable=True)
    pronouns_custom: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tagline: Mapped[str | None] = mapped_column(String(255), nullable=True)
    background: Mapped[str | None] = mapped_column(Text, nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    owner: Mapped[User] = relationship(back_populates="personas")


class Story(Base):
    __tablename__ = "stories"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)

    title: Mapped[str] = mapped_column(String(255), default="Untitled")
    cover_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    one_liner: Mapped[str | None] = mapped_column(String(500), nullable=True)
    synopsis: Mapped[str | None] = mapped_column(Text, nullable=True)
    world_long: Mapped[str | None] = mapped_column(Text, nullable=True)
    relations_overview: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Hard physical canon injected into EVERY prompt (spatial layout, props, fixed
    # headcounts/invariants). Spoiler-safe: only observable facts, never locked secrets.
    world_facts: Mapped[str | None] = mapped_column(Text, nullable=True)
    trope_tags: Mapped[list] = mapped_column(JSON, default=list)

    # M1: characters/acts stored as JSON; promote to tables if M2 needs them queryable.
    characters: Mapped[list] = mapped_column(JSON, default=list)
    acts: Mapped[list] = mapped_column(JSON, default=list)
    # Concrete physical places: [{id,name,detail,exits:[...]}]. Anchors the player's
    # spatial position so descriptions stay grounded & consistent. Spoiler-safe. Optional
    # (a story with none keeps the looser world_facts-only behavior).
    locations: Mapped[list] = mapped_column(JSON, default=list)
    # Endings (true/normal/bad/death) with unlock conditions. JSON like characters/acts.
    endings: Mapped[list] = mapped_column(JSON, default=list)
    # Per-story pacing/balance knob overrides (see engine/runtime.DEFAULT_TUNING and
    # docs/tuning.md). Empty = engine defaults.
    tuning: Mapped[dict] = mapped_column(JSON, default=dict)
    # ⚠️ pressure meter config {name,hint,ending_id,levels:[{at,note}]}; None = off
    pressure: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # ⏳ clock config {deadline_day, deadline_text, deadline_ending_id}; None = no deadline
    # (the clock itself runs off tuning.turns_per_slot)
    clock: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # 📱 小手机 config {enabled: bool, device: "手机"|"传呼机"|"口信"…}; None = defaults
    phone: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # 🔍 指认结案 config {prompt, options:[{id,label,correct,text?}], attempts, act_min,
    # fail_ending_id}; None = the story runs no verdict
    verdict: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # 18+ flag. When on, the engine permits explicit adult content (still refusing
    # minors). Players are already age-gated 18+ at signup (DOB gate).
    mature: Mapped[bool] = mapped_column(Boolean, default=False)

    visibility: Mapped[str] = mapped_column(String(16), default="private")
    status: Mapped[str] = mapped_column(String(16), default="draft")
    version: Mapped[int] = mapped_column(Integer, default=0)  # 0 = unpublished draft

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    secrets: Mapped[list["Secret"]] = relationship(
        back_populates="story", cascade="all, delete-orphan"
    )


class StorySnapshot(Base):
    """Immutable published snapshot. In-progress runs pin a version; new runs bind latest."""

    __tablename__ = "story_snapshots"
    __table_args__ = (UniqueConstraint("story_id", "version", name="uq_story_version"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    story_id: Mapped[str] = mapped_column(ForeignKey("stories.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    content: Mapped[dict] = mapped_column(JSON)  # frozen Story + secrets/fragments
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Secret(Base):
    """A character secret revealed via gated fragments (the core differentiator)."""

    __tablename__ = "secrets"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    story_id: Mapped[str] = mapped_column(ForeignKey("stories.id"), index=True)
    character_id: Mapped[str | None] = mapped_column(String(32), nullable=True)

    title: Mapped[str] = mapped_column(String(255), default="")
    sensitivity: Mapped[str] = mapped_column(String(16), default="light")

    story: Mapped[Story] = relationship(back_populates="secrets")
    fragments: Mapped[list["Fragment"]] = relationship(
        back_populates="secret", cascade="all, delete-orphan", order_by="Fragment.layer"
    )


class Fragment(Base):
    """One layer of a secret. Gated server-side BEFORE pgvector retrieval (M2)."""

    __tablename__ = "fragments"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    secret_id: Mapped[str] = mapped_column(ForeignKey("secrets.id"), index=True)

    layer: Mapped[int] = mapped_column(Integer, default=0)
    content: Mapped[str] = mapped_column(Text, default="")  # full text — NEVER embedded raw
    retrieval_key: Mapped[str | None] = mapped_column(Text, nullable=True)  # sanitized; embedded
    # 🗣 the AUTHORED lie: what the knower tells while this layer is LOCKED — one
    # coherent cover story instead of improvised fibs. Safe to speak by design.
    cover: Mapped[str | None] = mapped_column(Text, nullable=True)
    known_by_character_ids: Mapped[list] = mapped_column(JSON, default=list)

    # unlock conditions (all ANDed). Kept as JSON for M1; engine reads in M2.
    unlock: Mapped[dict] = mapped_column(JSON, default=dict)

    secret: Mapped[Secret] = relationship(back_populates="fragments")


class Run(Base):
    """One playthrough = (user, persona, pinned story_version).

    pinned_content freezes the story+secrets at run start so an author editing the
    draft can never break or leak into an in-progress run (MIGRATION risk #3).
    """

    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    story_id: Mapped[str] = mapped_column(ForeignKey("stories.id"), index=True)
    persona_id: Mapped[str] = mapped_column(ForeignKey("personas.id"))
    story_version: Mapped[int] = mapped_column(Integer, default=0)

    pinned_content: Mapped[dict] = mapped_column(JSON, default=dict)

    # Run state. Sticky unlocked set; asks counted per secret_id.
    # {act, affinity, flags:{}, unlocked_fragment_ids:[], asks:{secret_id:n}, triggered_event_ids:[]}
    state: Mapped[dict] = mapped_column(JSON, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    beats: Mapped[list["Beat"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="Beat.seq"
    )


class StoryMeta(Base):
    """🌱 Per-(user, story) progress that OUTLIVES runs: the cross-run ending gallery,
    earned achievements, and the NG+ (二周目) unlock. Written whenever a run reaches an
    ending; read on the story pick screen and at run creation (perk validation)."""

    __tablename__ = "story_meta"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    story_id: Mapped[str] = mapped_column(ForeignKey("stories.id"), index=True)

    endings_achieved: Mapped[list] = mapped_column(JSON, default=list)  # ending ids
    achievements: Mapped[list] = mapped_column(JSON, default=list)      # [{id,name,desc}]
    # 🃏 minted cards [{id,kind,name,text,payload?}] — emergent chars/places + 名场面
    cards: Mapped[list] = mapped_column(JSON, default=list)
    runs_ended: Mapped[int] = mapped_column(Integer, default=0)         # runs that reached ≥1 ending

    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class Beat(Base):
    """One rendered turn segment. type ∈ {description, think, dialogue}."""

    __tablename__ = "beats"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer, default=0)

    type: Mapped[str] = mapped_column(String(16), default="description")
    speaker_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    text: Mapped[str] = mapped_column(Text, default="")
    # 'player' for the player's own input echoed back, else 'engine'
    author: Mapped[str] = mapped_column(String(16), default="engine")
    # character ids PRESENT when this beat happened → gives each character a per-witness view
    # of history (they only "remember" scenes they were in). None on legacy beats = witnessed
    # by everyone (backward-compatible, no isolation for old runs).
    present_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # 📟 心象仪: the speaker's judged TRUE inner state when this line landed (nullable)
    mood: Mapped[str | None] = mapped_column(String(24), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    run: Mapped[Run] = relationship(back_populates="beats")
