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


class PushSub(Base):
    """🔔 Web-Push mailbox (活世界 P3): one row per browser subscription.
    endpoint is the identity; dead mailboxes (404/410 on send) are pruned."""

    __tablename__ = "push_subs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    endpoint: Mapped[str] = mapped_column(Text, unique=True)
    p256dh: Mapped[str] = mapped_column(String(255))
    auth: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


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
    taste: Mapped[dict] = mapped_column(JSON, default=dict)   # 🧭 账号级口味 (跨档风格沉淀)

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


class CharacterCard(Base):
    """📚 角色卡库: a character that lives OUTSIDE any story (Character.AI-style).
    Authored once — persona, voice, example lines — then imported into any 剧本 as a
    COPY (the story character records source_card_id for provenance; later edits to
    the card never mutate stories that already imported it)."""

    __tablename__ = "character_cards"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)

    name: Mapped[str] = mapped_column(String(120))
    visibility: Mapped[str] = mapped_column(String(16), default="private")
    avatar_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    # the portable persona payload (role/persona_text/eq_style/agenda/knowledge/
    # bio_layers/items/examples) — one JSON blob, same philosophy as Story's columns
    content: Mapped[dict] = mapped_column(JSON, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class Story(Base):
    __tablename__ = "stories"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)

    title: Mapped[str] = mapped_column(String(255), default="Untitled")
    # story language: "zh" | "en" — drives the engine's OUTPUT language (prompt directive
    # + localized deterministic narration). NA-market stories author with "en".
    language: Mapped[str] = mapped_column(String(8), default="zh")
    cover_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    one_liner: Mapped[str | None] = mapped_column(String(500), nullable=True)
    synopsis: Mapped[str | None] = mapped_column(Text, nullable=True)
    world_long: Mapped[str | None] = mapped_column(Text, nullable=True)
    relations_overview: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Hard physical canon injected into EVERY prompt (spatial layout, props, fixed
    # headcounts/invariants). Spoiler-safe: only observable facts, never locked secrets.
    world_facts: Mapped[str | None] = mapped_column(Text, nullable=True)
    # ✍️ 文风: the SOURCE WORK's narrative voice (author + fandom register) — sentence
    # rhythm, vocabulary, trope conventions. Injected into every generation so 斗罗大陆
    # reads like 网文 and Warhammer 40K reads like grimdark gothic, not one house style.
    style: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    # 🦇 hunter config {char_id,patrol,senses,cannot_enter,return_to,ladder,cues}; None = off
    threat: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # 🧠 sanity ledger config {enabled,name,start,regen,ending_id}; None = off
    sanity: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # 📜 house rules (规则怪谈) [{id,text,when,violate,consequence}]; None = off
    rules: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # 🚪 authored dooms [{id,day,char_id,to,text,warn_text,prevented_text,prevent}]; None = off
    dooms: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # ⏳ clock config {deadline_day, deadline_text, deadline_ending_id}; None = no deadline
    # (the clock itself runs off tuning.turns_per_slot)
    clock: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # 📱 小手机 config {enabled: bool, device: "手机"|"传呼机"|"口信"…}; None = defaults
    phone: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # 🔍 指认结案 config {prompt, options:[{id,label,correct,text?}], attempts, act_min,
    # fail_ending_id}; None = the story runs no verdict
    verdict: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # 🏖 无尽沙盒 {enabled, real_time}; None = a normal authored story
    sandbox: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # 🐲 生物账本 (第三实体类, Yi 拍板 2026-07-20): 兽/龙/鬼 — 行为实体非社交实体
    creatures: Mapped[list] = mapped_column(JSON, default=list)
    factions: Mapped[list] = mapped_column(JSON, default=list)   # 🏛 阵营
    opening: Mapped[str | None] = mapped_column(Text, nullable=True)   # 🎬 作者开场白
    # 🎀 galgame 生成器 (docs/galgame-maker.md): kind="gal" marks a compiled work;
    # gal = {status, progress, source_text, characters, scenes, script{pov:{chapters}},
    #        manifest, protagonist_id, art_style_preset}
    kind: Mapped[str] = mapped_column(String(16), default="story")
    gal: Mapped[dict | None] = mapped_column(JSON, nullable=True)

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
    # 🙈 隐藏而非删除: an archived run leaves the continue list but keeps everything
    archived: Mapped[bool] = mapped_column(Integer, default=0)

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
    # 重说/回溯 (docs/ux-design.md P1): run state as it stood BEFORE this player turn —
    # every player beat is a rewind point. NULL on engine beats / legacy rows.
    state_before: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # …and when a turn MUTATED the run's story copy (minted a character/place, wrote a
    # world fact), the pre-turn content snapshot rides the turn's first beat — so a
    # rewind erases the whole timeline, including what only that timeline created.
    content_before: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    run: Mapped[Run] = relationship(back_populates="beats")


class Wallet(Base):
    """💎 平台币钱包 (P1 影子系统, Yi 拍板 Roblox 三阶段): 月石只买内容资格。
    P1 不接支付 — 首次访问赠 200 内测币; P2 真钱阶段接充值与提现。"""

    __tablename__ = "wallets"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    balance: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class StoryPack(Base):
    """💎 创作者收费包: 挂在剧本上的内容资格 (门票/开局礼包/金手指位…)。
    grants 全确定性发货 (run 创建时结算), 一分钱 LLM 不烧。"""

    __tablename__ = "story_packs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    story_id: Mapped[str] = mapped_column(ForeignKey("stories.id"), index=True)
    name: Mapped[str] = mapped_column(String(40), default="")
    desc: Mapped[str] = mapped_column(String(200), default="")
    price: Mapped[int] = mapped_column(Integer, default=0)          # 月石
    grants: Mapped[dict] = mapped_column(JSON, default=dict)        # {access?, start_money_bonus?, powers?, items?}
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class PackPurchase(Base):
    """💎 购买台账 = 玩家的 entitlement + 创作者的分成凭据 (一张表两本账)。"""

    __tablename__ = "pack_purchases"
    __table_args__ = (UniqueConstraint("user_id", "pack_id", name="uq_user_pack"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    story_id: Mapped[str] = mapped_column(ForeignKey("stories.id"), index=True)
    pack_id: Mapped[str] = mapped_column(ForeignKey("story_packs.id"), index=True)
    price: Mapped[int] = mapped_column(Integer, default=0)          # 成交价快照
    creator_share: Mapped[int] = mapped_column(Integer, default=0)  # 创作者分成 (70%)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
