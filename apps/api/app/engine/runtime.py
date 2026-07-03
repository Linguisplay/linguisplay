"""Per-turn orchestration: glue between the player's input, the gate, and the LLM.

    detect probing → mutate run state → evaluate unlocks → assemble gated context
    → LLM → beats

The state-mutation heuristics (affinity nudge, act progression, event triggers)
are deliberately simple PLACEHOLDERS. In M3 these become model-driven (the LLM
proposes affinity deltas / flag changes as structured side-effects). The gate
(gating.py) and this pipeline's shape are the parts meant to be permanent.
"""

from __future__ import annotations

import random

import re
from typing import Any

from ..config import get_settings
from . import gating
from . import logic
from . import relationships
from . import scene as scene_mod
from .llm import LLM, get_llm

# Split on whitespace + CJK/ASCII punctuation into keyword phrases. Crucially this
# keeps CJK phrases intact (the old [a-z0-9]+ tokenizer dropped all Chinese, so
# probing in Chinese never registered an "ask").
_SPLIT = re.compile(r"[\s,，。、!！?？:：;；.…·\"'“”‘’()（）\[\]【】]+")

# Friendly cues nudge affinity (placeholder for M3 model-driven deltas). Bilingual.
_FRIENDLY = (
    "like", "love", "thanks", "thank", "care", "trust", "happy", "miss", "sorry",
    "谢谢", "喜欢", "相信", "信任", "别怕", "没事", "我在", "陪", "帮", "求你", "拜托",
)


def _keywords(text: str) -> list[str]:
    return [w for w in _SPLIT.split((text or "").lower()) if w]


def _contains_any(haystack: str, needles) -> bool:
    h = (haystack or "").lower()
    return any(n and n.lower() in h for n in needles)


def default_state() -> dict[str, Any]:
    return {
        "act": 1,
        "affinity": 0,
        "flags": {},
        "choices": {},                  # answered key-moment decisions: {key: option_id}
        "searched_prop_ids": [],        # props already turned over (现场搜查, once each)
        "pressure": 0,                  # ⚠️ story pressure meter (暴露值/灵异度), 0~100
        "world_pulse": 0,               # 🌊 quiet turns since the world last moved by itself
        "turns_in_act": 0,              # pacing: turns spent in the current act
        "dead_character_ids": [],       # ☠️ killed characters: never appear again, remembered
        "identity": None,               # 🎖 the player's CURRENT 身份/职务 (None = as authored)
        "identity_log": [],             # [{act, text}] — how the identity evolved
        "inventory": [],                # 🎒 pocket: [{name, detail?}] carried items
        "stashes": {},                  # {location_id: [{name,...}]} items left somewhere
        "met_ids": [],                  # characters the player has already met (首次见面 log)
        "rel_log": {},                  # 关系大事记: {char_id: [{act, kind, text}]}
        "pending_choice": None,         # an authored decision awaiting the player's pick
        "unlocked_fragment_ids": [],
        "asks": {},
        "triggered_event_ids": [],
        "achieved_endings": [],
        "mode": "character",            # "character" | "god" (invisible observer)
        "player_character_id": None,    # which character the player embodies (character mode)
        "memory": "",                   # rolling story digest (long-horizon memory, see below)
        "stuck": 0,                     # consecutive locked-act turns w/o new clue (hint escalation)
        "memory_covered": 0,            # how many history turns are already folded into `memory`
        "location_id": None,            # the physical place the player is currently in (if authored)
        "player_emotion": "",           # last read of the player's underlying emotion (EQ continuity)
        "mature": False,                # 18+ run: engine may permit explicit adult content
        "rel": {},                      # per-character relationship toward player {cid:{closeness,romance}}
        "following": [],                # character ids currently traveling WITH the player
        "clock": {"day": 1, "slot": 0, "turns_in_slot": 0},  # ⏳ diegetic time (slot → SLOTS)
        "npc_rel": {},                  # 🕸 NPC↔NPC stances {"a|b": {stance,-2..2, label?, log:[]}}
        "promises": [],                 # 🤝 约定 [{char_id,char_name,what,day,slot,location_id?,romantic,status}]
        "phone": {"threads": {}},       # 📱 小手机: {threads: {cid: {msgs:[{from,text,at}], unread}}}
    }


# ── Long-horizon memory ──────────────────────────────────────────────────────
# The model is only shown the last MEMORY_WINDOW dialogue turns verbatim (qwen.py
# slices history[-8:]). In a long, player-uploaded script that window forgets act 1
# by act 5. So we keep a rolling digest: once enough turns have slid PAST the window,
# they're compressed into `state["memory"]` (injected into the system prompt as stable
# context). Net effect for long runs: recent turns in full + the whole arc in summary,
# with per-turn tokens staying roughly constant instead of growing without bound.
#
# SECURITY: the digest is built only from `history` (player inputs + spoken dialogue),
# which by construction contains only what characters have ALREADY revealed. Locked
# fragment bodies never enter history, so they never enter the digest — the gate holds.
# relationship-tier ordering, for detecting an UPGRADE (to celebrate) vs a downgrade.
_RANK = {"enemy": -1, "stranger": 0, "junior": 1, "elder": 1, "peer": 1,
         "friend": 2, "flirt": 3, "lover": 4}

MEMORY_WINDOW = 14  # dialogue turns shown verbatim — MUST match qwen.py's history[-14:]
MEMORY_BATCH = 6    # summarize only once this many turns have slid out of the window

# Stuck-hint escalation: consecutive locked-act turns with no new required clue. NUDGE =
# NPCs get noticeably more forthcoming; PUSH = a direct narrator hint pointing at one topic;
# SPELL = the narrator lays out the full remaining checklist + a concrete next step.
STUCK_NUDGE = 1
STUCK_PUSH = 2
STUCK_SPELL = 4

# Every pacing/balance knob, overridable PER STORY via story.tuning (a horror script and a
# romance script want different rhythms). Values here are the engine defaults — the module
# constants above stay the single source for them. See docs/tuning.md for the knob table.
DEFAULT_TUNING = {
    "affinity_clamp_min": -3,   # per-turn floor on summed 好感 delta
    "affinity_clamp_max": 8,    # per-turn ceiling on summed 好感 delta
    "act_backstop_div": 12,     # soft acts: act floor = 1 + affinity // this
    "stuck_nudge": STUCK_NUDGE,
    "stuck_push": STUCK_PUSH,
    "stuck_spell": STUCK_SPELL,
    # relationship thresholds (see engine/relationships.py)
    "friend_t": 40, "enemy_t": -15, "flirt_t": 25, "lover_t": 60, "lover_close_min": 35,
    "follow_min_closeness": 25,
    "close_step_min": -6, "close_step_max": 8, "rom_step_min": -4, "rom_step_max": 6,
    # hours away after which the next turn counts as a RETURN (角色接起上次的话头)
    "return_gap_hours": 6,
    "dice": 1,                  # 🎲 risky 做-actions get a visible fate roll (0 = off)
    # pacing brakes (推进太快 fix): gains taper as scores climb; a soft act needs real time
    "affinity_taper_den": 100,  # positive 好感 gain scales by (1 - affinity/this), floor 0.3
    "close_taper_den": 130,     # per-char 亲近 gain taper denominator (relationships.py)
    "rom_taper_den": 110,       # per-char 心动 gain taper denominator
    "min_turns_per_act": 6,     # soft acts: no advance (model OR backstop) before this many turns
    "max_new_characters": 4,    # 👋 emergent mid-story characters a run may accumulate
    "world_event_every": 4,     # 🌊 after this many quiet turns an authored act event fires itself (0 = off)
    "turns_per_slot": 6,        # ⏳ turns per 时段 (晨/午/夜); a day = 3 slots. 0 = clock off
    "confront_base": 55,        # 🃏 evidence-confrontation base success %, + closeness//2
    "confront_cost": 3,         # 🃏 closeness cost of a successful confrontation (fail ×2, 大失败 ×3)
    "promise_keep_bonus": 6,    # 🤝 closeness for showing up to a promise (romantic: 心动 too)
    "promise_break_cost": 4,    # 🤝 closeness lost for standing someone up
}

MAX_OPEN_PROMISES = 3  # 🤝 open appointments a run may hold at once (per char: one)

# ⏳ the diegetic clock: three slots make a day. Slot-restricted schedule entries and
# story deadlines (story.clock) hang off this. Story-agnostic — the names are the frame,
# not any script's content.
SLOTS = ("晨", "午", "夜")
AWAY = "__away__"  # a scheduled character whose no entry covers this hour: off somewhere, unreachable

_SLOT_NARR = {
    "晨": "（长夜过去，第{day}天的晨光透了进来，街面上有了新的动静。）",
    "午": "（不知不觉，日头已经爬到头顶。）",
    "夜": "（天色沉了下来，夜幕罩住了这一带。）",
}


def tuning_for(content: dict[str, Any]) -> dict[str, int]:
    """The effective knob set for this story: engine defaults overlaid with the story's
    authored `tuning` overrides (unknown keys and non-numeric values are ignored)."""
    t = dict(DEFAULT_TUNING)
    for k, v in ((content.get("story") or {}).get("tuning") or {}).items():
        if k in t:
            try:
                t[k] = int(v)
            except (TypeError, ValueError):
                pass
    return t


def history_for(beat_log: list[dict[str, Any]] | None, char_id: str | None) -> list[dict[str, str]]:
    """A character's PERSONAL view of the conversation: only the beats they witnessed (were
    present for). Legacy beats (present_ids None) are witnessed by everyone. This is what
    stops info silently leaking between characters/scenes — each one only recalls what it saw."""
    out: list[dict[str, str]] = []
    for b in beat_log or []:
        pres = b.get("present_ids")
        if not (pres is None or (char_id and char_id in pres)):
            continue
        if b.get("author") == "player":
            out.append({"role": "user", "content": b.get("text", "")})
        elif b.get("type") == "dialogue":
            # prefix the speaker so a character can tell who said what in a group scene
            sp = b.get("speaker_name")
            out.append({"role": "assistant", "content": (f"{sp}：" if sp else "") + b.get("text", "")})
    return out


def _update_memory_for(state: dict[str, Any], char_id: str, char_history: list[dict[str, str]],
                       llm: LLM) -> None:
    """Per-CHARACTER rolling digest: fold this character's own witnessed turns that slid out
    of the window into their private memory. Keeps isolation intact for long runs."""
    membyc = state.setdefault("memory_by_char", {})
    memcov = state.setdefault("memcov_by_char", {})
    covered = int(memcov.get(char_id, 0))
    cutoff = max(0, len(char_history) - MEMORY_WINDOW)
    if cutoff - covered < MEMORY_BATCH:
        return
    prior = membyc.get(char_id, "")
    try:
        out = llm.generate({"summarize": True, "prior_memory": prior,
                            "new_lines": char_history[covered:cutoff]})
        digest = (out or {}).get("memory")
    except Exception:
        digest = None
    if digest:
        membyc[char_id] = digest
        memcov[char_id] = cutoff


def _update_memory(state: dict[str, Any], history: list[dict[str, str]] | None, llm: LLM) -> None:
    """Fold turns that have slid out of the verbatim window into the rolling digest.

    Cheap, and only fires every ~MEMORY_BATCH turns (not every turn). Mutates state in
    place; degrades to leaving `memory` unchanged on any model failure."""
    history = history or []
    covered = int(state.get("memory_covered") or 0)
    cutoff = max(0, len(history) - MEMORY_WINDOW)   # everything older than the window
    if cutoff - covered < MEMORY_BATCH:
        return                                       # not enough new material yet
    new_lines = history[covered:cutoff]
    prior = state.get("memory") or ""
    try:
        out = llm.generate({"summarize": True, "prior_memory": prior, "new_lines": new_lines})
        digest = (out or {}).get("memory")
    except Exception:
        digest = None
    if digest:
        state["memory"] = digest
        state["memory_covered"] = cutoff


def _characters(content: dict[str, Any]) -> list[dict[str, Any]]:
    return (content.get("story") or {}).get("characters") or []


def lead_speaker(content: dict[str, Any]) -> dict[str, Any] | None:
    chars = _characters(content)
    if not chars:
        return None
    for c in chars:
        if c.get("is_lead"):
            return c
    return chars[0]


def _is_present(c: dict[str, Any], act: int) -> bool:
    """A character is a live participant only if present (not offstage/ghost) AND has
    already made their entrance (current act >= appears_from_act)."""
    if (c.get("presence") or "present") == "offstage":
        return False
    return int(act) >= int(c.get("appears_from_act") or 0)


def present_characters(content: dict[str, Any], act: int,
                       dead: set | None = None) -> list[dict[str, Any]]:
    dead = dead or set()
    return [c for c in _characters(content) if _is_present(c, act) and c.get("id") not in dead]


def _dead_ids(state: dict[str, Any]) -> set:
    return set(state.get("dead_character_ids") or [])


def clock_cfg(content: dict[str, Any]) -> dict[str, Any]:
    """The story's authored clock config (story.clock): optionally a hard deadline —
    {deadline_day, deadline_text, deadline_ending_id}. Empty dict when none authored."""
    return (content.get("story") or {}).get("clock") or {}


def active_slot(content: dict[str, Any], state: dict[str, Any]) -> str | None:
    """The current 时段 name, or None when this story runs no clock (slot-restricted
    schedule entries then apply at all hours — legacy behavior)."""
    if tuning_for(content)["turns_per_slot"] <= 0:
        return None
    clk = state.get("clock") or {}
    return SLOTS[int(clk.get("slot", 0) or 0) % len(SLOTS)]


def clock_view(content: dict[str, Any], state: dict[str, Any]) -> dict[str, Any] | None:
    """What the UI shows on the 🕐 chip: day/slot label + the authored deadline countdown.
    None = this story runs no clock."""
    slot = active_slot(content, state)
    if slot is None:
        return None
    day = int((state.get("clock") or {}).get("day", 1) or 1)
    view: dict[str, Any] = {"day": day, "slot": slot, "label": f"第{day}天·{slot}"}
    ccfg = clock_cfg(content)
    try:
        dd = int(ccfg.get("deadline_day") or 0)
    except (TypeError, ValueError):
        dd = 0
    if dd:
        view["deadline"] = {"text": (ccfg.get("deadline_text") or "").strip() or "大限",
                            "days_left": dd - day}
    return view


def char_home(c: dict[str, Any], act: int, slot: str | None = None) -> str | None:
    """Where this character is RIGHT NOW (作息表): among schedule entries with
    from_act <= act that cover the current 时段 (an entry may carry slots: ["夜"] —
    no slots = all hours), the highest from_act wins; slot-specific beats generic on a
    tie. A scheduled character whom no entry covers this hour is AWAY (off somewhere,
    unreachable) — home_location_id only backs up characters with no reached schedule.
    None = ubiquitous (legacy stories that don't pin characters to places)."""
    best = (-1, -1)
    best_loc = None
    reached = False
    for e in (c.get("schedule") or []):
        try:
            fa = int(e.get("from_act") or 0)
        except (TypeError, ValueError):
            continue
        lid = (e.get("location_id") or "").strip()
        if not lid or fa > int(act):
            continue
        reached = True
        entry_slots = [s for s in (e.get("slots") or []) if s]
        if entry_slots and slot is not None and slot not in entry_slots:
            continue
        key = (fa, 1 if entry_slots else 0)
        if key > best:
            best, best_loc = key, lid
    if best_loc:
        return best_loc
    if reached and slot is not None:
        return AWAY
    return c.get("home_location_id")


def _is_here(c: dict[str, Any], state: dict[str, Any], cur_loc_id: str | None,
             slot: str | None = None) -> bool:
    """Is this character in the player's CURRENT scene? A character pinned to a place
    (per-act/per-slot schedule, else home location) is only here when the player is AT
    that place, OR when the character is currently following the player. AWAY = off
    somewhere this hour, encounterable nowhere. A character with no place at all is
    ubiquitous (present everywhere in their act — backward-compatible)."""
    cid = c.get("id")
    if cid and cid in (state.get("following") or []):
        return True
    home = char_home(c, int(state.get("act", 1) or 1), slot)
    if home == AWAY:
        return False
    if not home:
        return True
    return cur_loc_id == home


def scene_characters(content: dict[str, Any], state: dict[str, Any]) -> list[dict[str, Any]]:
    """Present (entered this act, not offstage) AND in the player's current scene
    (at their location or following). This is "who the player can actually interact with
    right now" — the explore→encounter spine."""
    act = int(state.get("act", 1))
    # resolve the effective location (None → the opening/first place, as current_location does)
    cur = current_location(content, state)
    cur_id = cur.get("id") if cur else state.get("location_id")
    slot = active_slot(content, state)
    return [c for c in present_characters(content, act, _dead_ids(state))
            if _is_here(c, state, cur_id, slot)]


def playable_roles(content: dict[str, Any]) -> list[dict[str, Any]]:
    """Characters the player may EMBODY (character mode). Those explicitly flagged
    `playable` win; if a story flags none (legacy), fall back to every character present
    from the opening act — so old stories keep letting you pick any role."""
    chars = _characters(content)
    flagged = [c for c in chars if c.get("playable")]
    if flagged:
        return flagged
    return [c for c in chars if _is_present(c, 1)]


def cast_for(content: dict[str, Any], act: int, exclude_id: str | None = None,
             state: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """The addressable cast at this act (offstage/not-yet-arrived/dead excluded). In
    character mode `exclude_id` drops the embodied character (you don't talk to self)."""
    return [
        {"id": c.get("id"), "name": c.get("name"),
         "is_lead": c.get("is_lead", False), "avatar_url": c.get("avatar_url")}
        for c in present_characters(content, act, _dead_ids(state or {}))
        if c.get("id") != exclude_id
    ]


def _physical_roster(content: dict[str, Any], state: dict[str, Any], persona: dict[str, Any]) -> str:
    """Deterministic 'who is physically present right now', so the model never miscounts
    nor writes the player out of the scene. General: derived purely from the roster +
    presence flags, works for any story. Offstage/supernatural characters are listed
    separately as NOT counted among the living."""
    act = int(state.get("act", 1))
    mode = state.get("mode") or "character"
    pcid = state.get("player_character_id")
    present = scene_characters(content, state)  # only who is in THIS scene right now
    living = [c.get("name") for c in present if c.get("name") and c.get("id") != pcid]
    # the player is a body in the scene (except in god/observer mode)
    if mode == "god":
        player_label = None
    else:
        pc = _char_by_id(content, pcid) if pcid else None
        player_label = (pc.get("name") if pc else (persona or {}).get("name")) or "你"
    names = ([f"{player_label}（你）"] if player_label else []) + living
    offstage = [c.get("name") for c in _characters(content)
                if (c.get("presence") or "present") == "offstage" and c.get("name")]
    lines: list[str] = []
    if names:
        lines.append(
            f"此刻这个场景里实际在场的人：{'、'.join(names)}——共 {len(names)} 人。"
            "这个数字是确定的：不要数错、不要重算，也绝不要把“你”（玩家）自己漏掉或排除在外。"
        )
    if offstage:
        lines.append(
            f"以下并不是在场的活人，只会出现在镜中、暗处或传闻里——永远不要把 TA 算进在场人数，"
            f"也不要让 TA 像普通人一样正常参与对话：{'、'.join(offstage)}。"
        )
    return "\n".join(lines)


# ── Physical place (spatial anchor) ──────────────────────────────────────────
# Stories MAY author a list of concrete locations. When they do, we track which place the
# player is currently in and inject its concrete fixtures + exits into every prompt, so the
# narration stays grounded ("you are in X, you can see/reach Y, you can go to Z") instead of
# drifting through vague atmosphere or teleporting people around. Stories with no authored
# locations keep the looser world_facts-only behavior (place block is simply omitted).
def _locations(content: dict[str, Any]) -> list[dict[str, Any]]:
    return (content.get("story") or {}).get("locations") or []


def _location_by_id(content: dict[str, Any], lid: str | None) -> dict[str, Any] | None:
    if not lid:
        return None
    for loc in _locations(content):
        if loc.get("id") == lid:
            return loc
    return None


def resolve_location(content: dict[str, Any], ref: str | None) -> dict[str, Any] | None:
    """Match a free-text reference (an id, an exact name, or a name the model wrote) to an
    authored location. Used to apply the director's 地点 movement marker safely — an
    unrecognized place is ignored, so the model can never invent a room out of nowhere."""
    if not ref:
        return None
    ref = ref.strip()
    locs = _locations(content)
    for loc in locs:  # exact id or name first
        if loc.get("id") == ref or loc.get("name") == ref:
            return loc
    for loc in locs:  # then a lenient containment match on the name
        name = loc.get("name") or ""
        if name and (name in ref or ref in name):
            return loc
    return None


def current_location(content: dict[str, Any], state: dict[str, Any]) -> dict[str, Any] | None:
    """Where the player is now. Defaults to the first authored location if unset."""
    locs = _locations(content)
    if not locs:
        return None
    return _location_by_id(content, state.get("location_id")) or locs[0]


def location_available(content: dict[str, Any], state: dict[str, Any], loc: dict[str, Any] | None) -> bool:
    """Is this place reachable yet? A location stays hidden until its unlock conditions are
    met (act reached, affinity floor, required info uncovered) — so exits only appear once the
    player has learned the place exists THIS act. Empty unlock = always available."""
    if not loc:
        return False
    u = loc.get("unlock") or {}
    if int(state.get("act", 1)) < int(u.get("act_min") or 0):
        return False
    if int(state.get("affinity", 0)) < int(u.get("affinity_min") or 0):
        return False
    if not set(u.get("required_fragment_ids") or []) <= set(state.get("unlocked_fragment_ids") or []):
        return False
    return True


def location_view(content: dict[str, Any], state: dict[str, Any]) -> dict[str, Any] | None:
    """The current place for the UI, with its exits filtered to only the destinations that
    are currently UNLOCKED — locked places simply don't appear as options yet."""
    loc = current_location(content, state)
    if not loc:
        return None
    avail = []
    for name in (loc.get("exits") or []):
        dest = resolve_location(content, name)
        if dest and location_available(content, state, dest):
            avail.append(name)
    return {**loc, "exits": avail}


def apply_move(content: dict[str, Any], state: dict[str, Any], dest_ref: str) -> dict[str, Any]:
    """Move the player to an authored location reachable from where they are. Characters
    currently following the player come along automatically (they stay in `following`, so
    they're still 'here' at the new place). Returns the new location dict.
    Raises ValueError if the destination is unknown or not connected to the current place."""
    dest = resolve_location(content, dest_ref)
    if not dest or not dest.get("id"):
        raise ValueError("unknown location")
    if not location_available(content, state, dest):
        raise ValueError("not yet available")  # place not discovered/unlocked yet
    cur = current_location(content, state)
    exits = (cur or {}).get("exits") or []
    # if exits are authored, enforce them; an isolated/exitless map allows free travel
    if exits and dest.get("name") not in exits and dest.get("id") not in exits \
            and dest.get("id") != (cur or {}).get("id"):
        raise ValueError("not reachable from here")
    state["location_id"] = dest["id"]
    return dest


def ensure_start_location(content: dict[str, Any], state: dict[str, Any],
                          llm: LLM | None = None) -> dict[str, Any] | None:
    """ARCHITECTURAL INVARIANT: every run has a 'current location', so the whole spatial system
    (place anchor, movement, EMERGENT locations) works for EVERY story — not only the ones that
    authored a map. If the story authored no locations, synthesize a starting one from its
    opening setting and pin the player there. Mutates content + state (caller persists content).
    Called at run creation (policy layer); the engine itself stays location-agnostic so a raw
    run_turn_stream on a map-less story still behaves as before."""
    if _locations(content):
        loc = current_location(content, state)
        if loc and loc.get("id"):
            state["location_id"] = loc["id"]
        return loc
    story = content.get("story") or {}
    world = story.get("world_facts") or story.get("world_long") or ""
    act1 = current_act(content, 1) or {}
    setting = " ".join([act1.get("title", "")]
                       + [e.get("what_happens", "") for e in (act1.get("events") or [])]).strip()
    out: dict[str, Any] = {}
    try:
        out = (llm or get_llm()).generate({"start_place": True, "world": world, "setting": setting}) or {}
    except Exception:
        out = {}
    name = (out.get("name") or "").strip() or "此处"
    detail = (out.get("detail") or "").strip()
    loc = {"id": "loc_start", "name": name, "detail": detail, "exits": [], "unlock": {}, "generated": True}
    story.setdefault("locations", []).append(loc)
    content["story"] = story
    state["location_id"] = "loc_start"
    return loc


def generate_and_move(content: dict[str, Any], state: dict[str, Any], place_name: str,
                      persona: dict[str, Any] | None = None, llm: LLM | None = None) -> dict[str, Any]:
    """EMERGENT LOCATION: the player agreed to go somewhere that isn't on the authored map.
    Create that place for real — the model writes a concrete, people-free description grounded
    in the world + where you're coming from — wire it two-way to the current place, append it
    into the run's content (so it's a first-class location from now on), and move the player
    there. Mutates `content` (caller must persist it). Returns the new location dict.

    Idempotent-ish: if the name actually matches a place that already exists, just go there."""
    place_name = (place_name or "").strip()
    if not place_name:
        raise ValueError("unknown location")
    existing = resolve_location(content, place_name)
    if existing and existing.get("id"):
        state["location_id"] = existing["id"]
        return existing
    llm = llm or get_llm()
    cur = current_location(content, state)
    story = content.get("story") or {}
    world = story.get("world_facts") or story.get("world_long") or ""
    detail = ""
    try:
        detail = (llm.generate({"describe_place": True, "place_name": place_name, "world": world,
                                "from_place": (cur or {}).get("name", ""),
                                "mature": bool(state.get("mature"))}) or {}).get("detail") or ""
    except Exception:
        detail = ""
    import uuid
    lid = "loc_gen_" + uuid.uuid4().hex[:8]
    back = [(cur or {}).get("name")] if cur and cur.get("name") else []
    new_loc = {"id": lid, "name": place_name, "detail": detail.strip(),
               "exits": back, "unlock": {}, "generated": True}
    story.setdefault("locations", []).append(new_loc)
    content["story"] = story
    # link current place → new place so the exit shows up (and you can walk back and forth)
    if cur is not None:
        exits = cur.setdefault("exits", [])
        if place_name not in exits:
            exits.append(place_name)
    state["location_id"] = lid
    return new_loc


def set_follow(content: dict[str, Any], state: dict[str, Any],
               char_id: str, follow: bool) -> dict[str, Any]:
    """Toggle whether a character travels WITH the player. The character must currently be in
    the player's scene to invite/dismiss, AND (to invite) like the player enough — following
    is EARNED with 好感, not free for a stranger. Returns {ok, following, reason, name}."""
    char = _char_by_id(content, char_id)
    if not char:
        raise ValueError("unknown character")
    here_ids = {c.get("id") for c in scene_characters(content, state)}
    if char_id not in here_ids:
        raise ValueError("character not here")
    following = [c for c in (state.get("following") or []) if c != char_id]
    name = char.get("name") or "对方"
    if follow:
        rel_all = state.get("rel") or {}
        scores = rel_all.get(char_id) or relationships.new_scores()
        tun = tuning_for(content)
        if not relationships.can_follow(char, scores, tun):
            state["following"] = following
            mode = relationships.derive_mode(char, scores, tun)
            reason = (f"{name}对你满是戒备，不会跟你走。" if mode == "enemy"
                      else f"你和{name}还没熟到那份上——先多聊聊、把关系处近点，TA 才愿意跟你走。")
            return {"ok": False, "following": following, "name": name, "reason": reason}
        following.append(char_id)
        rel_log(state, char_id, int(state.get("act", 1) or 1), "follow",
                f"{name} 答应与你同行。")
    state["following"] = following
    return {"ok": True, "following": following, "name": name, "reason": ""}


def _physical_place(content: dict[str, Any], state: dict[str, Any]) -> str:
    """The 'you are here' block: this place's concrete fixtures + where you can go. Empty
    when the story authored no locations."""
    loc = current_location(content, state)
    if not loc:
        return ""
    name = loc.get("name") or "此处"
    # line 1 = the concrete locator (place + fixtures + exits) — this is what the depth
    # anchor reuses, so keep it self-contained and grounded. line 2 = the meta-instruction.
    concrete = f"此刻玩家所在的地点是【{name}】。"
    if loc.get("detail"):
        concrete += f"这里有：{loc['detail']}"
    exits = [e for e in (loc.get("exits") or []) if e]
    if exits:
        concrete += f"　从这里可以去：{'、'.join(exits)}。"
    props = [p.get("name") for p in (loc.get("props") or []) if p.get("name")]
    if props:
        concrete += f"　这里可以翻查：{'、'.join(props)}。"
    stash = [(i.get("name") or "") for i in (state.get("stashes") or {}).get(loc.get("id"), []) if i.get("name")]
    if stash:
        concrete += f"　玩家之前存放在这里的东西：{'、'.join(stash)}。"
    instruction = (
        "旁白只能描写这个地点里实际存在的东西，不要凭空添置别处的陈设；"
        "玩家要移动到别处，必须经由上面列出的通路，且要把移动过程写出来，不能瞬移。"
    )
    return concrete + "\n" + instruction


def _char_by_id(content: dict[str, Any], cid: str | None) -> dict[str, Any] | None:
    if not cid:
        return None
    for c in _characters(content):
        if c.get("id") == cid:
            return c
    return None


def _char_name(content: dict[str, Any], cid: str | None) -> str | None:
    c = _char_by_id(content, cid)
    return c.get("name") if c else None


def _secret_char_map(content: dict[str, Any]) -> dict[str, str]:
    return {s.get("id"): s.get("character_id") for s in (content.get("secrets") or [])}


def pick_responder(
    content: dict[str, Any],
    state: dict[str, Any],
    player_input: str,
    target_id: str | None,
    probed_char_ids: list[str],
    chars: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Choose which character answers this turn (the '两者结合' router).

    Priority: explicit @target → a character named in the input → the character
    whose secret is being probed → whoever spoke last → the lead. Keeps per-character
    gating clean (we only ever build context for ONE chosen speaker). `chars` limits the
    candidates to who's actually present this turn (offstage/ghosts excluded)."""
    chars = chars if chars is not None else _characters(content)
    if not chars:
        return None
    by_id = {c.get("id"): c for c in chars}
    # 1. explicit tap / @ (only honoured if that character is present)
    if target_id in by_id:
        return by_id[target_id]
    # 2. a character's name appears in what the player said
    for c in chars:
        name = c.get("name") or ""
        if name and name in (player_input or ""):
            return c
    # 3. the character whose secret the player is probing
    for cid in probed_char_ids:
        if cid in by_id:
            return by_id[cid]
    # 4. continue with whoever spoke last
    if state.get("last_speaker_id") in by_id:
        return by_id[state["last_speaker_id"]]
    # 5. default: the present lead (else the first present character)
    for c in chars:
        if c.get("is_lead"):
            return c
    return chars[0]


def current_act(content: dict[str, Any], act_index: int) -> dict[str, Any] | None:
    for act in (content.get("story") or {}).get("acts", []) or []:
        if int(act.get("index", 0)) == act_index:
            return act
    return None


def _max_act_index(content: dict[str, Any]) -> int:
    acts = (content.get("story") or {}).get("acts", []) or []
    return max((int(a.get("index", 0)) for a in acts), default=0)


def current_goal(content: dict[str, Any], act_index: int) -> str:
    """The player's small objective for this act (authored 🎯 guidance)."""
    a = current_act(content, act_index)
    return (a or {}).get("goal", "") if a else ""


def _frag_title_map(content: dict[str, Any]) -> dict[str, str]:
    """fragment_id → its secret's title (a sanitized topic label, never the body)."""
    out: dict[str, str] = {}
    for secret in content.get("secrets", []) or []:
        title = secret.get("title", "")
        for f in secret.get("fragments", []) or []:
            if f.get("id"):
                out[f["id"]] = title
    return out


def _frag_location_map(content: dict[str, Any]) -> dict[str, str]:
    """fragment id → the location_id its unlock requires the player to be at (if any)."""
    out: dict[str, str] = {}
    for sec in content.get("secrets", []) or []:
        for f in sec.get("fragments", []) or []:
            lid = (f.get("unlock") or {}).get("location_id")
            if f.get("id") and lid:
                out[f.get("id")] = lid
    return out


def _event_label_map(content: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for act in (content.get("story") or {}).get("acts", []) or []:
        for ev in act.get("events", []) or []:
            if ev.get("id"):
                out[ev["id"]] = ev.get("what_happens", "")
    return out


def _advance_cond(content: dict[str, Any], act_index: int) -> dict[str, Any]:
    return (current_act(content, act_index) or {}).get("advance") or {}


def act_has_gate(content: dict[str, Any], act_index: int) -> bool:
    """True if this act authored any hard advance condition (else soft-advance fallback)."""
    adv = _advance_cond(content, act_index)
    return bool(adv.get("required_fragment_ids") or adv.get("required_event_ids")
                or int(adv.get("affinity_min") or 0) > 0)


def can_advance(content: dict[str, Any], state: dict[str, Any], act_index: int) -> bool:
    """HARD gate (pure, program-checked): are ALL of this act's advance conditions met?

    Required fragments must be unlocked (= the player actually dug that info out), required
    events triggered, affinity at/above the floor. This is the security/structure twin of
    gating.py — progression can't be talked past, only earned by discovery."""
    adv = _advance_cond(content, act_index)
    unlocked = set(state.get("unlocked_fragment_ids") or [])
    triggered = set(state.get("triggered_event_ids") or [])
    if not set(adv.get("required_fragment_ids") or []) <= unlocked:
        return False
    if not set(adv.get("required_event_ids") or []) <= triggered:
        return False
    if int(state.get("affinity", 0)) < int(adv.get("affinity_min") or 0):
        return False
    return True


def act_progress(content: dict[str, Any], state: dict[str, Any], act_index: int) -> dict[str, Any]:
    """A guidance checklist for the current act: which required clues are found (✓) vs
    still missing (○). Labels are sanitized secret titles / authored event text — never
    fragment bodies. Empty when the act has no hard gate."""
    adv = _advance_cond(content, act_index)
    unlocked = set(state.get("unlocked_fragment_ids") or [])
    triggered = set(state.get("triggered_event_ids") or [])
    ftitles = _frag_title_map(content)
    elabels = _event_label_map(content)
    floc = _frag_location_map(content)
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for fid in adv.get("required_fragment_ids") or []:
        label = ftitles.get(fid, "线索")
        if label in seen:
            continue
        seen.add(label)
        done = fid in unlocked
        # a location-gated clue guides the player TO the place ("去X看看") once the
        # place itself is discoverable — turning the checklist into a travel plan
        if not done:
            lid = floc.get(fid)
            loc = _location_by_id(content, lid) if lid else None
            if loc and location_available(content, state, loc):
                label = f"{label}（去「{loc.get('name','')}」看看）"
        items.append({"label": label, "done": done})
    for eid in adv.get("required_event_ids") or []:
        items.append({"label": elabels.get(eid, "关键进展"), "done": eid in triggered})
    done = sum(1 for it in items if it["done"])
    return {"items": items, "done": done, "total": len(items)}


def _pending_topics(progress: dict[str, Any]) -> list[str]:
    """Titles of still-missing required clues (for steering the player / characters)."""
    return [it["label"] for it in progress.get("items", []) if not it["done"]]


def build_opening(content: dict[str, Any], state: dict[str, Any], llm: LLM | None = None) -> list[dict[str, Any]]:
    """A detailed, literary opening that INTRODUCES the player: who you are, where/when
    you are, what's happening, who's around — ending with your first small goal. One LLM
    call at run start (degrades to assembled narration). Secrets are never passed in."""
    llm = llm or get_llm()
    mode = state.get("mode") or "character"
    pcid = state.get("player_character_id")
    act1 = current_act(content, 1) or {}
    player_char = _char_by_id(content, pcid) if (mode == "character" and pcid) else None
    present = [c.get("name") for c in present_characters(content, 1)
              if c.get("name") and c.get("id") != pcid]
    # pin the starting place so the player has a concrete spatial anchor from turn 1
    start = current_location(content, state)
    if start and start.get("id"):
        state["location_id"] = start["id"]
    directed = llm.generate({
        "intro": True,
        "mode": mode,
        "player_char": player_char,
        "world": (content.get("story") or {}).get("world_long", "") or "",
        "act": act1,
        "goal": act1.get("goal", ""),
        "cast": present,
        "place": _physical_place(content, state),
        "mature": bool(state.get("mature")),
    })
    beats = [b for b in directed.get("beats", []) if b.get("type") == "description"]
    beats = beats or [{"type": "description", "speaker_name": None, "text": opening_narration(content)}]
    # ✨ 首局魔法时刻: within the first screen, someone SEES the player — one concrete
    # gesture, one crack of something withheld, one line spoken straight at them. The
    # "earned intimacy" promise made perceivable in 30 seconds.
    beats += opening_hook_beats(content, state, player_char, llm)
    return beats


def opening_hook_beats(content: dict[str, Any], state: dict[str, Any],
                       player_char: dict[str, Any] | None, llm: LLM) -> list[dict[str, Any]]:
    """The hook: the lead notices the player personally AND visibly swallows something
    unsaid (keyed to a secret's TITLE only — spoiler-safe by the same rule as hints).
    LLM writes both strokes; deterministic fallback keeps the withheld-crack narration."""
    if (state.get("mode") or "character") == "god":
        return []
    pcid = state.get("player_character_id")
    host = next((c for c in scene_characters(content, state)
                 if c.get("id") != pcid and c.get("is_lead")), None) \
        or next((c for c in scene_characters(content, state) if c.get("id") != pcid), None)
    if not host:
        return []
    tease = next((s.get("title") for s in content.get("secrets") or []
                  if (s.get("title") or "").strip()
                  and (s.get("character_id") == host.get("id"))), None) \
        or next((s.get("title") for s in content.get("secrets") or []
                 if (s.get("title") or "").strip()), None)
    narration = line = ""
    try:
        out = llm.generate({"opening_hook": True,
                            "char": {"name": host.get("name"), "role": host.get("role") or "",
                                     "persona_text": (host.get("persona_text") or "")[:200],
                                     "eq_style": (host.get("eq_style") or "")[:100]},
                            "player_name": (player_char or {}).get("name") or "你",
                            "player_role": (player_char or {}).get("role") or "",
                            "place": (current_location(content, state) or {}).get("name") or "",
                            "tease": tease or ""}) or {}
        narration = str(out.get("narration") or "").strip()
        line = str(out.get("line") or "").strip().strip("「」\"'")[:80]
    except Exception:
        pass
    if not narration and tease:
        narration = (f"（{host.get('name')}的目光落在你身上，多停了一瞬——像在掂量你，"
                     f"又像有什么关于「{tease}」的话到了嘴边，被咽了回去。）")
    beats: list[dict[str, Any]] = []
    if narration:
        beats.append({"type": "description", "speaker_name": None, "text": narration})
    if line:
        beats.append({"type": "dialogue", "speaker_name": host.get("name"), "text": line})
    return beats


def build_act_transition(content: dict[str, Any], state: dict[str, Any], old_act: int,
                          new_act: int, persona: dict[str, Any] | None = None,
                          llm: LLM | None = None) -> list[dict[str, Any]]:
    """Narration that carries the plot INTO a new act: the shift, the new situation, the
    new goal. One LLM call (degrades to the act's authored events). Spoiler-safe."""
    llm = llm or get_llm()
    mode = state.get("mode") or "character"
    pcid = state.get("player_character_id")
    act = current_act(content, new_act) or {}
    player_char = _char_by_id(content, pcid) if (mode == "character" and pcid) else None
    # only who's ACTUALLY at the player's current location — NOT every character who has
    # arrived by this act. A distant act-event (e.g. 王九 at 巷口) must reach the player as
    # news/sound, not teleport a crowd into the room the player is standing in.
    present = [c.get("name") for c in scene_characters(content, state)
               if c.get("name") and c.get("id") != pcid]
    prev = current_act(content, old_act) or {}
    directed = llm.generate({
        "transition": True,
        "mode": mode,
        "player_char": player_char,
        "world": (content.get("story") or {}).get("world_long", "") or "",
        "act": act,
        "prev_title": prev.get("title", ""),
        "goal": act.get("goal", ""),
        "cast": present,
        "place": _physical_place(content, state),
        "memory": state.get("memory", ""),
        "mature": bool(state.get("mature")),
    })
    beats = [b for b in directed.get("beats", []) if b.get("type") == "description"]
    # fallback: at least state the new act's events so the transition still carries info
    if not beats:
        ev = " ".join(e.get("what_happens", "") for e in (act.get("events") or []))
        if ev:
            beats = [{"type": "description", "speaker_name": None, "text": ev}]
    return beats


_ENDING_PRIORITY = {"true": 3, "normal": 2, "bad": 1, "death": 0}
_DEFAULT_ENDING_TITLE = {"death": "你死了", "bad": "坏结局", "normal": "结局", "true": "真结局"}


def evaluate_ending(
    content: dict[str, Any], state: dict[str, Any], model_ending: dict | None
) -> dict[str, Any] | None:
    """Decide whether the run concludes this turn.

    Two sources:
    1. The director declared a fatal/terminal player action (death/bad) → fires NOW,
       regardless of act. The consequence is already in the turn's narration.
    2. Authored endings whose conditions are all met. By default an authored ending is
       only eligible at the final act (so the player isn't yanked to an ending early);
       set its act_min to make it eligible sooner. Among eligible matches we pick the
       best (true > normal > bad), so reaching the true ending's bar beats the default.
    """
    if model_ending and model_ending.get("kind") in ("death", "bad"):
        kind = model_ending["kind"]
        # A fatal action is genuinely terminal — you can't keep exploring as a corpse.
        return {
            "id": "director",
            "kind": kind,
            "title": _DEFAULT_ENDING_TITLE[kind],
            "text": model_ending.get("reason") or "",
            "terminal": kind == "death",
        }

    endings = (content.get("story") or {}).get("endings") or []
    if not endings:
        return None
    max_act = _max_act_index(content)
    act = int(state.get("act", 1))
    aff = int(state.get("affinity", 0))
    unlocked = set(state.get("unlocked_fragment_ids") or [])
    flags = state.get("flags") or {}

    matches = []
    for e in endings:
        if e.get("trigger"):
            continue  # mechanism-invoked (e.g. pressure blowout) — never a normal match
        cond = e.get("condition") or {}
        gate_act = int(cond.get("act_min") or 0) or max_act  # 0 ⇒ only at the final act
        if act < gate_act:
            continue
        if aff < int(cond.get("affinity_min") or 0):
            continue
        if not set(cond.get("required_fragment_ids") or []) <= unlocked:
            continue
        rflags = cond.get("required_flags") or {}
        if any(flags.get(k) != v for k, v in rflags.items()):
            continue
        matches.append(e)
    if not matches:
        return None
    best = max(matches, key=lambda e: _ENDING_PRIORITY.get(e.get("kind", "normal"), 2))
    kind = best.get("kind", "normal")
    # Authored endings are MILESTONES in an open world — reaching one doesn't end the
    # run; the player keeps exploring (and may later reach a higher-tier ending).
    return {
        "id": best.get("id"),
        "kind": kind,
        "title": best.get("title") or _DEFAULT_ENDING_TITLE.get(kind, "结局"),
        "text": best.get("text", ""),
        "terminal": False,
    }


def _act_opening(act: dict[str, Any]) -> str:
    """Narration played when the run crosses into a new act — pushes the scene forward."""
    title = act.get("title", "")
    events = " ".join(e.get("what_happens", "") for e in (act.get("events") or []))
    head = f"〔第{act.get('index', '')}幕 · {title}〕"
    return (head + "  " + events).strip()


def opening_narration(content: dict[str, Any]) -> str:
    """Atmospheric scene-set for a brand-new run: worldbuilding + act-1 opening."""
    story = content.get("story") or {}
    parts: list[str] = []
    if story.get("world_long"):
        parts.append(story["world_long"])
    act1 = current_act(content, 1)
    if act1:
        ev = " ".join(e.get("what_happens", "") for e in (act1.get("events") or []))
        if ev:
            parts.append(ev)
    return "  ".join(parts) or "故事，就这样开始了。"


def _norm_line(s: str) -> str:
    """Normalize a line for echo comparison: drop whitespace + punctuation."""
    import re
    return re.sub(r"[\s，。、！？…—\-,.!?\"'「」（）()]+", "", s or "")


def _too_similar(text: str, said: list[dict[str, str]]) -> bool:
    """True if `text` is near-verbatim of something already said this turn (long shared
    prefix or near-equal length+overlap) — catches echoes that aren't byte-identical."""
    a = _norm_line(text)
    if len(a) < 6:
        return False
    for s in said:
        b = _norm_line(s.get("text", ""))
        if len(b) < 6:
            continue
        # long common prefix relative to the shorter line → it's parroting the opener
        n = min(len(a), len(b))
        common = 0
        while common < n and a[common] == b[common]:
            common += 1
        if common >= max(8, int(0.7 * n)):
            return True
    return False


def _logic_guard(llm, prompt: dict[str, Any], directed: dict[str, Any], content: dict[str, Any],
                 state: dict[str, Any], frags: list[dict[str, Any]]) -> dict[str, Any]:
    """Post-generation logic backstop for the addressed (primary) character. Deterministically
    checks this turn's beats against the LIVE scene state — no character who isn't here may be
    shown arriving/speaking, no still-locked secret may surface. On a hard break: regenerate
    ONCE with a targeted correction; if it still breaks, scrub the offending sentences. At most
    one extra LLM call, and only when something is actually wrong (clean turns cost nothing)."""
    pcid = state.get("player_character_id")
    here = scene_characters(content, state)
    here_ids = {c.get("id") for c in here}
    present_names = [c.get("name") for c in here if c.get("name")]
    absent_names = [c.get("name") for c in _characters(content)
                    if c.get("name") and c.get("id") not in here_ids and c.get("id") != pcid]
    locked_locs = [l.get("name") for l in _locations(content)
                   if l.get("name") and not location_available(content, state, l)]
    locked_texts = [f.get("content", "") for f in frags
                    if f.get("content") and gating.classify_guard(f, state) != "reveal"]

    def _check(d):
        return logic.verify_turn(d.get("beats", []), absent_names=absent_names,
                                 locked_location_names=locked_locs,
                                 locked_fragment_texts=locked_texts, present_names=present_names)

    verdict = _check(directed)
    if not verdict["hard"]:
        return directed
    # regenerate once, telling the model exactly what broke (labels only — never the secret body)
    corr = ("上一版出现了逻辑错误：" + "；".join(verdict["hard"]) +
            "。请重写这一轮：严格只写此刻在场的人（" + ("、".join(present_names) or "只有你和玩家") +
            "），绝不要让任何不在场的人出场、开口或走进来；也绝不要说出你此刻并不知道、尚未挑明的内情。")
    retry = llm.generate({**prompt, "logic_correction": corr})
    if not _check(retry)["hard"]:
        return retry
    # still broken → deterministically neutralize the intrusion so it never reaches the player
    retry["beats"] = logic.scrub_beats(retry.get("beats", []), absent_names)
    return retry


def _smart_suggestions(llm, all_beats, player_input, primary, content, state, location,
                       needed_topics, observer) -> list[str]:
    """LLM-generated next-step hints grounded in THIS turn's exchange + the current scene.
    Returns [] on any failure / mock, so the caller falls back to the template."""
    if observer or not primary:
        return []
    primary_name = primary.get("name") or "对方"
    # the primary's spoken line THIS turn (for grounding)
    reply = next((b.get("text", "") for b in reversed(all_beats)
                  if b.get("type") == "dialogue" and b.get("speaker_name") == primary_name), "")
    pcid = state.get("player_character_id")
    present = [c.get("name") for c in scene_characters(content, state)
               if c.get("name") and c.get("id") != pcid and c.get("id") != primary.get("id")]
    exits = (location or {}).get("exits") or []
    rels = state.get("rel") or {}
    rel_name = relationships.name_of(relationships.derive_mode(primary, rels.get(primary.get("id")) or relationships.new_scores(), tuning_for(content)))
    # the ROLE the player embodies — every suggestion must be spoken/acted from this POV.
    pc = _char_by_id(content, pcid) if pcid else None
    player_name = (pc or {}).get("name") or ""
    player_desc = ((pc or {}).get("role") or (pc or {}).get("persona_text")
                   or (pc or {}).get("background") or "").strip()[:60]
    try:
        out = llm.generate({"suggest": True, "sugg": {
            "speaker": primary_name, "player_input": player_input, "reply": reply[:120],
            "present": present, "exits": exits, "topics": needed_topics, "relation": rel_name,
            "player_name": player_name, "player_desc": player_desc,
            "place": (location or {}).get("name") or "",
        }})
        return [s for s in (out.get("suggestions") or []) if s][:3]
    except Exception:
        return []


def build_suggestions(context: dict[str, Any]) -> list[str]:
    """Nudge the player toward what's close to unlocking, without spoiling content.

    hint_topics are secrets exactly one condition short — steering the player there
    is a fair gameplay hint (it's the topic label, never the secret body)."""
    s: list[str] = []
    for t in context.get("hint_topics", [])[:2]:
        s.append(f"再追问「{t}」")
    if context.get("new_reveal"):
        s.append("顺着他刚说的继续深挖")
    if not s and context.get("has_hidden"):
        s.append("他像在回避，换个角度问问")
    s.append("用「做」描述你的一个动作")
    if len(s) < 3:
        s.append("跟他多聊聊，拉近距离")
    # de-dup preserving order
    seen, out = set(), []
    for x in s:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out[:3]


# ── entrances & exits: people never just pop in/out of the cast bar ─────────────
# Slot flavor prefixes for deterministic entrance lines (keyed by SLOTS names).
_SLOT_FLAVOR = {"晨": "晨光里", "午": "日头底下", "夜": "夜色里"}


def _first_sentence(s: str, cap: int = 48) -> str:
    return (s or "").strip().replace("\n", " ").split("。")[0][:cap]


def entrance_beat(content: dict[str, Any], state: dict[str, Any], c: dict[str, Any]) -> dict[str, Any]:
    """A CONCRETE arrival line for a character who just walked into the scene (the hour
    rolled / a new act brought them on): looks + role, not a bare name in the cast bar."""
    slot = active_slot(content, state)
    flavor = _SLOT_FLAVOR.get(slot or "", "")
    look = _first_sentence(c.get("persona_text") or "")
    role = (c.get("role") or "").strip()
    bits = "，".join(b for b in (role, look) if b)
    lead = f"{flavor}，" if flavor else ""
    return {"type": "description", "speaker_name": None,
            "text": f"（{lead}{c.get('name')}来了{('——' + bits) if bits else ''}。）"}


def _exit_dest(content: dict[str, Any], state: dict[str, Any],
               c: dict[str, Any]) -> tuple[str | None, str]:
    """Where a departing character is headed: (speakable destination name or None,
    narration tail). A discovered place gets named (探索钩子); an UNDISCOVERED one is
    hinted without spoiling geography; AWAY admits nobody knows."""
    home = char_home(c, int(state.get("act", 1) or 1), active_slot(content, state))
    loc = _location_by_id(content, home) if (home and home != AWAY) else None
    if loc and location_available(content, state, loc):
        return loc.get("name"), f"，往{loc.get('name')}那边去了"
    if loc:
        return None, "，往你还没去过的地方去了"
    if home == AWAY:
        return None, "——没人知道TA这个时辰去了哪"
    return None, ""


def farewell_beats(content: dict[str, Any], state: dict[str, Any], c: dict[str, Any],
                   llm: LLM) -> list[dict[str, Any]]:
    """A character leaving the scene SAYS GOODBYE first — one short in-voice line (which
    may name where they're off to), then a narration that tracks where they went. Nobody
    just evaporates from the cast bar."""
    dest, tail = _exit_dest(content, state, c)
    line = ""
    try:
        out = llm.generate({"farewell": True, "dest": dest or "",
                            "place": (current_location(content, state) or {}).get("name") or "",
                            "char": {"name": c.get("name"), "role": c.get("role") or "",
                                     "persona_text": (c.get("persona_text") or "")[:160],
                                     "eq_style": (c.get("eq_style") or "")[:100]}}) or {}
        line = str(out.get("line") or "").strip().strip("「」\"'")[:60]
    except Exception:
        line = ""
    if not line:
        line = f"我先走一步——{dest}那边还有事。" if dest else "先这样，我得走了。回头见。"
    return [
        {"type": "dialogue", "speaker_name": c.get("name"), "text": line},
        {"type": "description", "speaker_name": None,
         "text": f"（{c.get('name')}说着起身走了{tail}。）"},
    ]


def exit_beat(content: dict[str, Any], state: dict[str, Any], c: dict[str, Any]) -> dict[str, Any]:
    """The budget-friendly departure (no spoken line): still says where they went."""
    _, tail = _exit_dest(content, state, c)
    return {"type": "description", "speaker_name": None,
            "text": f"（不知什么时候，{c.get('name')}已经离开了{tail}。）"}


def arrival_narration(content: dict[str, Any], state: dict[str, Any], persona: dict[str, Any],
                      llm: LLM | None = None) -> str:
    """The moment the player WALKS INTO a place: a vivid 2~4 sentence pan — the space
    itself, then what each person present is DOING right now (posture/activity/attention,
    true to who they are), and who notices the player first. LLM-written; degrades to a
    deterministic per-person assembly so the scene is never a bare name list."""
    llm = llm or get_llm()
    loc = current_location(content, state) or {}
    pcid = state.get("player_character_id")
    tun = tuning_for(content)
    rels = state.get("rel") or {}
    people = []
    for c in scene_characters(content, state):
        if c.get("id") == pcid or not c.get("name"):
            continue
        mode = relationships.derive_mode(c, rels.get(c.get("id")) or relationships.new_scores(), tun)
        people.append({"name": c["name"], "role": (c.get("role") or "").strip(),
                       "look": _first_sentence(c.get("persona_text") or "", 60),
                       "relation": relationships.name_of(mode)})
    try:
        out = llm.generate({"arrive": True,
                            "place": loc.get("name") or "", "detail": (loc.get("detail") or "")[:160],
                            "slot": (clock_view(content, state) or {}).get("label", ""),
                            "people": people,
                            "player_name": (persona or {}).get("name") or ""}) or {}
        txt = next((b.get("text", "") for b in out.get("beats") or []
                    if b.get("type") == "description" and (b.get("text") or "").strip()), "")
    except Exception:
        txt = ""
    if txt:
        return txt
    bits = [_first_sentence(loc.get("detail") or "", 60)]
    for p in people:
        who = "，".join(b for b in (p["role"], p["look"]) if b)
        bits.append(f"{p['name']}正在这里{('——' + who) if who else ''}")
    return "（" + "。".join(b for b in bits if b) + "。）" if any(bits) else ""


def arrival_suggestions(content: dict[str, Any], state: dict[str, Any],
                        llm: LLM | None = None) -> list[str]:
    """Fresh next-step chips for a scene the player JUST WALKED INTO — the previous
    turn's suggestions point at people and things that are no longer here. Grounded in
    the current place, who is actually present, and the act's open topics; falls back
    to a deterministic set (talk to who's here / search what's here / look around)."""
    if (state.get("mode") or "character") == "god":
        return []
    llm = llm or get_llm()
    loc = current_location(content, state) or {}
    pcid = state.get("player_character_id")
    here = [c for c in scene_characters(content, state) if c.get("id") != pcid]
    if here:
        primary = next((c for c in here if c.get("is_lead")), here[0])
        smart = _smart_suggestions(
            llm, [], f"（你刚走进{loc.get('name') or '这里'}，还没开口）", primary,
            content, state, location_view(content, state),
            _pending_topics(act_progress(content, state, int(state.get("act", 1) or 1))),
            False)
        if smart:
            return smart
    det: list[str] = [f"和{c.get('name')}搭话" for c in here[:2] if c.get("name")]
    searched = set(state.get("searched_prop_ids") or [])
    prop = next((p.get("name") for p in (loc.get("props") or [])
                 if p.get("name") and p.get("id") not in searched), None)
    if prop:
        det.append(f"翻查{prop}")
    det.append("看看四周")
    return det[:3]


def _detect_asks(content: dict[str, Any], player_input: str) -> list[str]:
    """Secret ids the player appears to be probing this turn.

    Matches the input against each secret's title and its fragments'
    retrieval_key keyword phrases (sanitized — safe to match; NEVER the fragment
    content). Substring match so it works for Chinese as well as English."""
    hit: list[str] = []
    for secret in content.get("secrets", []) or []:
        kw = list(_keywords(secret.get("title", "")))
        for f in secret.get("fragments", []) or []:
            kw += _keywords(f.get("retrieval_key") or "")
        if _contains_any(player_input, kw):
            hit.append(secret.get("id"))
    return hit


def _apply_event_triggers(content: dict[str, Any], state: dict, player_input: str) -> None:
    """PROVISIONAL pass: fire a story event when the player's words overlap its keywords.
    The primary director call then judges which events truly occurred (occurred_events);
    keyword guesses it denies are rolled back — see the reconciliation in run_turn_stream."""
    triggered = set(state.get("triggered_event_ids") or [])
    for act in (content.get("story") or {}).get("acts", []) or []:
        for ev in act.get("events", []) or []:
            eid = ev.get("id")
            kws = [w for w in _keywords(ev.get("what_happens", "")) if len(w) >= 2]
            if eid and eid not in triggered and _contains_any(player_input, kws):
                triggered.add(eid)
    state["triggered_event_ids"] = sorted(triggered)


def _probe_candidates(content: dict[str, Any], state: dict) -> list[dict[str, Any]]:
    """Ask-judgment candidates for the director call: secrets that still hold locked
    fragments, as (id, sanitized title) — titles only, never bodies."""
    unlocked = set(state.get("unlocked_fragment_ids") or [])
    out = []
    for s in content.get("secrets", []) or []:
        title = (s.get("title") or "").strip()
        frags = s.get("fragments", []) or []
        if title and any(f.get("id") not in unlocked for f in frags):
            out.append({"id": s.get("id"), "title": title})
    return out


def _event_candidates(content: dict[str, Any], state: dict, act: int) -> list[dict[str, Any]]:
    """Event-judgment candidates: the current act's not-yet-triggered events, as
    (id, label). Labels come from what_happens, which the progress checklist already
    shows the player — spoiler-consistent."""
    triggered = set(state.get("triggered_event_ids") or [])
    out = []
    for ev in (current_act(content, act) or {}).get("events", []) or []:
        eid = ev.get("id")
        label = (ev.get("what_happens") or "").strip()
        if eid and eid not in triggered and label:
            out.append({"id": eid, "label": label[:40]})
    return out


def _match_candidates(cands: list[dict[str, Any]], judged, key: str) -> set:
    """Map the model's copied-back titles/labels to candidate ids (lenient: exact or
    containment either way, so a slightly trimmed copy still matches)."""
    got = set()
    for j in judged or []:
        jn = str(j).strip()
        if not jn:
            continue
        for c in cands:
            t = c.get(key) or ""
            if t and (t == jn or t in jn or jn in t):
                got.add(c["id"])
    return got


def _titles_for_fragments(content: dict[str, Any], frag_ids) -> list[str]:
    """The sanitized titles of the secrets owning these fragments (unique, ordered)."""
    idset = set(frag_ids or [])
    seen, out = set(), []
    for sec in content.get("secrets", []) or []:
        if any(f.get("id") in idset for f in sec.get("fragments", []) or []):
            t = (sec.get("title") or "").strip()
            if t and t not in seen:
                seen.add(t)
                out.append(t)
    return out


def _choice_options(act_dict: dict[str, Any]) -> list[dict[str, Any]]:
    """The act's valid choice options with STABLE ids (authored id or positional)."""
    ch = (act_dict or {}).get("choice") or {}
    out = []
    for i, o in enumerate(ch.get("options") or []):
        if (o.get("label") or "").strip():
            out.append({**o, "id": (o.get("id") or "").strip() or f"opt{i}"})
    return out


def choice_for_act(content: dict[str, Any], state: dict[str, Any], act: int) -> dict[str, Any] | None:
    """The act's authored key-moment decision (VN 抉择), if any and not yet answered.
    Player-facing shape: prompt + option ids/labels only (effects stay server-side)."""
    a = current_act(content, act) or {}
    ch = a.get("choice") or {}
    opts = _choice_options(a)
    if not (ch.get("prompt") or "").strip() or not opts:
        return None
    key = f"act{a.get('index', act)}"
    if key in (state.get("choices") or {}):
        return None
    return {"key": key, "act": int(a.get("index", act) or act), "prompt": ch["prompt"].strip(),
            "options": [{"id": o["id"], "label": o["label"]} for o in opts]}


def apply_choice(content: dict[str, Any], state: dict[str, Any], option_id: str) -> dict[str, Any]:
    """Resolve the pending decision: apply its deterministic effects (flag → endings can
    gate on it; global 好感; optional per-character relationship deltas), record the answer,
    clear the pending state. The picked label is returned so the caller can play it as the
    player's own words/action. Raises ValueError when nothing pends / option unknown."""
    pending = state.get("pending_choice") or {}
    if not pending:
        raise ValueError("no pending choice")
    a = current_act(content, int(pending.get("act") or state.get("act", 1) or 1)) or {}
    picked = next((o for o in _choice_options(a) if o["id"] == option_id), None)
    if picked is None:
        raise ValueError("unknown option")
    tun = tuning_for(content)
    if picked.get("flag"):
        flags = dict(state.get("flags") or {})
        flags[str(picked["flag"])] = True
        state["flags"] = flags
    ad = int(picked.get("affinity_delta") or 0)
    if ad:
        state["affinity"] = max(0, int(state.get("affinity", 0)) + ad)
    cid = picked.get("character_id")
    cd = int(picked.get("closeness_delta") or 0)
    rd = int(picked.get("romance_delta") or 0)
    if cid and (cd or rd):
        rel_all = state.setdefault("rel", {})
        rel_all[cid] = relationships.apply_deltas(
            rel_all.get(cid) or relationships.new_scores(), cd, rd, tun)
    answered = dict(state.get("choices") or {})
    answered[pending.get("key") or f"act{state.get('act', 1)}"] = option_id
    state["choices"] = answered
    state["pending_choice"] = None
    return {"label": picked.get("label") or "", "flag": picked.get("flag")}


def search_props(content: dict[str, Any], state: dict[str, Any],
                 player_input: str, channel: str = "say") -> list[dict[str, Any]]:
    """现场搜查: the player names a searchable prop at their CURRENT place on the 做/看
    channel → it's turned over. Mutates state: fires the prop's story event; returns the
    found props (with their evidence fragment ids) for the caller to unlock + narrate.
    Deterministic — physical evidence is found by physically looking, no dice."""
    if channel not in ("do", "think"):
        return []
    loc = current_location(content, state)
    if not loc:
        return []
    found: list[dict[str, Any]] = []
    searched = set(state.get("searched_prop_ids") or [])
    for i, prop in enumerate(loc.get("props") or []):
        name = (prop.get("name") or "").strip()
        if not name:
            continue
        pid = (prop.get("id") or "").strip() or f"{loc.get('id')}_prop{i}"
        if pid in searched or not _contains_any(player_input, [name]):
            continue
        searched.add(pid)
        if prop.get("event_id"):
            trig = set(state.get("triggered_event_ids") or [])
            trig.add(prop["event_id"])
            state["triggered_event_ids"] = sorted(trig)
        found.append({"id": pid, "name": name, "detail": (prop.get("detail") or "").strip(),
                      "fragment_id": prop.get("fragment_id"), "take": bool(prop.get("take"))})
    state["searched_prop_ids"] = sorted(searched)
    return found


def _fragment_content(content: dict[str, Any], fid: str | None) -> str:
    for sec in content.get("secrets", []) or []:
        for f in sec.get("fragments", []) or []:
            if f.get("id") == fid:
                return (f.get("content") or "").strip()
    return ""


def discover_on_arrival(content: dict[str, Any], state: dict[str, Any]) -> list[dict[str, Any]]:
    """After the player MOVES: unlock fragments whose only missing key was being HERE
    (unlock.location_id) and hand back discovery narrations — physical truths reveal the
    moment you stand in the right place, not a turn later. Mutates state (sticky)."""
    state["location_id"] = (current_location(content, state) or {}).get("id")
    frags = gating.iter_fragments(content)
    newly = gating.evaluate_unlocks(state, frags)
    here = state.get("location_id")
    # only fragments gated ON this place narrate as arrival discoveries; anything else
    # newly eligible stays for the normal turn flow (voiced by characters)
    found = [f for f in frags if f.get("id") in set(newly)
             and (f.get("unlock") or {}).get("location_id") == here]
    if not found:
        return []
    fids = [f.get("id") for f in found]
    state["unlocked_fragment_ids"] = sorted(
        set(state.get("unlocked_fragment_ids") or []) | set(fids))
    out = []
    for f in found:
        body = (f.get("content") or "").strip()
        title = (f.get("secret_title") or "").strip()
        out.append({"fragment_id": f.get("id"), "title": title,
                    "text": f"（到了这里你才看清——{body}）"})
    return out


def map_view(content: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    """The discovered world for the 🗺 map panel: unlocked places as nodes (current one
    flagged), exits filtered to unlocked destinations, who stands where right now.
    Locked places surface only as an unnamed count — the map never spoils geography."""
    locs = _locations(content)
    if not locs:
        return {"nodes": [], "hidden": 0, "current": None}
    act = int(state.get("act", 1) or 1)
    cur = (current_location(content, state) or {}).get("id")
    pcid = state.get("player_character_id")
    following = set(state.get("following") or [])
    avail = {l.get("id"): location_available(content, state, l) for l in locs}
    name_to_id = {l.get("name"): l.get("id") for l in locs if l.get("name")}
    at: dict[str, list[str]] = {}
    slot = active_slot(content, state)
    for c in present_characters(content, act, _dead_ids(state)):
        if c.get("id") == pcid:
            continue
        lid = cur if c.get("id") in following else char_home(c, act, slot)
        if lid and lid != AWAY and avail.get(lid) and c.get("name"):
            at.setdefault(lid, []).append(c["name"])
    nodes = []
    for l in locs:
        lid = l.get("id")
        if not avail.get(lid):
            continue
        exits = [{"id": name_to_id[en], "name": en}
                 for en in (l.get("exits") or []) if avail.get(name_to_id.get(en))]
        nodes.append({"id": lid, "name": l.get("name") or "", "here": lid == cur,
                      "chars": at.get(lid, []), "exits": exits})
    return {"nodes": nodes, "hidden": sum(1 for v in avail.values() if not v), "current": cur}


_rng = random.Random()  # module-level so tests can monkeypatch/seed


def _roll_check(risk: int) -> dict[str, Any]:
    """🎲 fate roll against a 0~99 risk (success chance %). Crit success on the top
    tenth of the success band; crit fail on a 97+ miss."""
    roll = _rng.randint(1, 100)
    if roll <= max(1, risk // 10):
        outcome = "crit_success"
    elif roll <= risk:
        outcome = "success"
    elif roll >= 97:
        outcome = "crit_fail"
    else:
        outcome = "fail"
    return {"risk": int(risk), "roll": roll, "outcome": outcome}


def pressure_cfg(content: dict[str, Any]) -> dict[str, Any] | None:
    """The story's authored pressure meter (卧底暴露值/灵异逼近…), or None when the story
    doesn't run one. Shape: {name, hint, ending_id, levels: [{at, note}]}"""
    cfg = (content.get("story") or {}).get("pressure") or {}
    return cfg if (cfg.get("name") or "").strip() else None


def _ending_by_id(content: dict[str, Any], eid: str | None) -> dict[str, Any] | None:
    for e in (content.get("story") or {}).get("endings", []) or []:
        if e.get("id") == eid:
            return e
    return None


# ── 🕸 NPC↔NPC relationship web ─────────────────────────────────────────────────
# Characters hold stances toward EACH OTHER (not just toward the player): authored
# initial ties evolve as scenes play out (the primary judges real shifts, the engine
# clamps and records them). Feeds performances, the dossier card, and god mode.
_STANCE_LABEL = {-2: "仇怨", -1: "不睦", 0: "", 1: "交好", 2: "同盟"}


def _pair_key(a: str, b: str) -> str:
    return "|".join(sorted([a or "", b or ""]))


def _ensure_npc_rel(content: dict[str, Any], state: dict[str, Any]) -> None:
    """Seed authored ties (character.ties: [{char_id, stance, label?}]) into the live web —
    idempotent: an existing pair entry (already seeded or already evolved) is never reset."""
    web = dict(state.get("npc_rel") or {})
    ids = {c.get("id") for c in _characters(content)}
    for c in _characters(content):
        cid = c.get("id")
        for t in (c.get("ties") or []):
            other = t.get("char_id")
            if not cid or other not in ids or other == cid:
                continue
            key = _pair_key(cid, other)
            if key in web:
                continue
            try:
                stance = max(-2, min(2, int(t.get("stance") or 0)))
            except (TypeError, ValueError):
                continue
            web[key] = {"stance": stance, "label": (t.get("label") or "").strip() or None,
                        "log": []}
    state["npc_rel"] = web


def npc_stance(state: dict[str, Any], a: str, b: str) -> dict[str, Any] | None:
    """The current stance between two characters: {stance, label} (label = authored flavor
    if any, else the engine name for the level). None when they have no charged relation."""
    e = (state.get("npc_rel") or {}).get(_pair_key(a, b))
    if not e or not int(e.get("stance") or 0):
        return None
    stance = int(e["stance"])
    return {"stance": stance, "label": e.get("label") or _STANCE_LABEL.get(stance, "")}


def apply_npc_shift(content: dict[str, Any], state: dict[str, Any], a_ref: str, b_ref: str,
                    delta: int, why: str, act: int) -> dict[str, Any] | None:
    """Apply ONE judged NPC↔NPC shift: both names must resolve to LIVING characters
    PRESENT in the player's scene (never the player), delta clamps to ±1, stance to
    [-2,2]. A shift past an authored label drops the label (the old flavor no longer
    fits). Returns {a,b,delta,stance} for the UI moment, or None when refused."""
    here = {(c.get("name") or ""): c for c in scene_characters(content, state)
            if c.get("id") != state.get("player_character_id")}

    def _resolve(ref):
        ref = (ref or "").strip()
        for nm, c in here.items():
            if nm and ref and (nm == ref or nm in ref or ref in nm):
                return c
        return None

    ca, cb = _resolve(a_ref), _resolve(b_ref)
    if not ca or not cb or ca.get("id") == cb.get("id"):
        return None
    delta = 1 if int(delta or 0) > 0 else -1 if int(delta or 0) < 0 else 0
    if not delta:
        return None
    web = dict(state.get("npc_rel") or {})
    key = _pair_key(ca["id"], cb["id"])
    e = dict(web.get(key) or {"stance": 0, "label": None, "log": []})
    new_stance = max(-2, min(2, int(e.get("stance") or 0) + delta))
    if new_stance == int(e.get("stance") or 0):
        return None
    e["stance"], e["label"] = new_stance, None  # evolved past the authored flavor
    log = list(e.get("log") or [])
    log.append({"act": int(act), "delta": delta, "why": (why or "").strip()[:60]})
    e["log"] = log[-12:]
    web[key] = e
    state["npc_rel"] = web
    return {"a": ca.get("name"), "b": cb.get("name"), "delta": delta, "stance": new_stance}


def npc_stance_line(content: dict[str, Any], state: dict[str, Any], sp_id: str,
                    others: list[dict[str, Any]]) -> str:
    """ONE lean prompt line: this speaker's charged stances toward who else is here."""
    bits = []
    for c in others:
        s = npc_stance(state, sp_id, c.get("id") or "")
        if s and c.get("name"):
            bits.append(f"你与{c['name']}：{s['label']}")
    return "；".join(bits)


def npc_ties_of(content: dict[str, Any], state: dict[str, Any], char_id: str) -> list[dict[str, Any]]:
    """The dossier view: this character's charged stances toward people the player has MET
    (unmet names never leak). [{name, stance, label}] sorted worst-first."""
    met = set(state.get("met_ids") or [])
    out = []
    for c in _characters(content):
        other = c.get("id")
        if not other or other == char_id or other not in met:
            continue
        s = npc_stance(state, char_id, other)
        if s:
            out.append({"name": c.get("name") or "", "stance": s["stance"], "label": s["label"]})
    return sorted(out, key=lambda x: x["stance"])


# ── 🤝 约定 (appointments) ──────────────────────────────────────────────────────
# The strongest come-back hook: a character sets a FUTURE meeting with the player
# (place + day + 时段, hung visibly in the top bar). Showing up = a dedicated scene
# and a relationship reward — a romance-tier appointment plays as a proper 约会名场面
# (恋与深空-style). Standing them up costs the relationship and they hold the grudge.
# Runs entirely off the diegetic clock; stories with the clock off never see it.
def _time_index(state: dict[str, Any]) -> int:
    clk = state.get("clock") or {}
    return int(clk.get("day", 1) or 1) * len(SLOTS) + int(clk.get("slot", 0) or 0) % len(SLOTS)


def _promise_index(pr: dict[str, Any]) -> int:
    slot = pr.get("slot")
    si = SLOTS.index(slot) if slot in SLOTS else 0
    return int(pr.get("day", 1) or 1) * len(SLOTS) + si


def promise_when_label(pr: dict[str, Any], state: dict[str, Any]) -> str:
    diff = int(pr.get("day", 1) or 1) - int((state.get("clock") or {}).get("day", 1) or 1)
    day = "今天" if diff <= 0 else "明天" if diff == 1 else "后天" if diff == 2 else f"第{pr.get('day')}天"
    return f"{day}{pr.get('slot', '')}"


def promises_view(content: dict[str, Any], state: dict[str, Any]) -> list[dict[str, Any]]:
    """Open appointments for the UI, soonest first: [{name, what, when, place, romantic}]."""
    out = []
    for pr in sorted((p for p in state.get("promises") or [] if p.get("status") == "open"),
                     key=_promise_index):
        loc = _location_by_id(content, pr.get("location_id")) if pr.get("location_id") else None
        out.append({"name": pr.get("char_name") or "", "what": pr.get("what") or "",
                    "when": promise_when_label(pr, state),
                    "place": (loc or {}).get("name") or "", "romantic": bool(pr.get("romantic"))})
    return out


def make_promise(content: dict[str, Any], state: dict[str, Any], char: dict[str, Any],
                 pm: dict[str, Any], tun: dict[str, int]) -> dict[str, Any] | None:
    """Record a judged appointment. Refuses: clock off, empty/overlong intent, bad slot,
    a time not in the future, a char who already has one open, or a full slate."""
    if tun["turns_per_slot"] <= 0:
        return None
    what = str(pm.get("what") or "").strip()[:40]
    slot = str(pm.get("slot") or "").strip()
    if not what or slot not in SLOTS:
        return None
    try:
        off = max(0, min(3, int(pm.get("day_offset", 0))))
    except (TypeError, ValueError):
        return None
    prs = list(state.get("promises") or [])
    cid = char.get("id")
    if sum(1 for p in prs if p.get("status") == "open") >= MAX_OPEN_PROMISES:
        return None
    if any(p.get("status") == "open" and p.get("char_id") == cid for p in prs):
        return None
    day = int((state.get("clock") or {}).get("day", 1) or 1) + off
    pr = {"char_id": cid, "char_name": char.get("name") or "", "what": what,
          "day": day, "slot": slot, "status": "open"}
    if _promise_index(pr) <= _time_index(state):
        return None  # the promised hour must lie ahead
    dest = resolve_location(content, str(pm.get("place") or "").strip())
    pr["location_id"] = dest.get("id") if dest else state.get("location_id")
    # a promise made at 暧昧/恋人 warmth is a DATE — the fulfillment scene plays as one
    scores = (state.get("rel") or {}).get(cid) or relationships.new_scores()
    pr["romantic"] = relationships.derive_mode(char, scores, tun) in ("flirt", "lover")
    prs.append(pr)
    state["promises"] = prs
    return pr


# ── 📱 小手机 (phase 1: 信息) ────────────────────────────────────────────────────
# Characters REACH OUT to the player between scenes — a promise reminder, a hurt text
# after being stood up, a can't-stop-thinking-of-you note after parting (恋与深空-style
# proactive contact). The player can text back from anywhere; the character answers in
# voice — or leaves them on read. Threads live in run state, separate from scene beats;
# a thread's tail is injected into that character's next scene prompt so the two worlds
# remember each other. Period stories rename the device (城寨 → 口信/字条).
PHONE_MAX_PER_TURN = 2   # incoming deliveries per turn, tops (no notification spam)


def phone_cfg(content: dict[str, Any]) -> dict[str, Any]:
    return (content.get("story") or {}).get("phone") or {}


def phone_enabled(content: dict[str, Any]) -> bool:
    return phone_cfg(content).get("enabled", True) is not False


def phone_device(content: dict[str, Any]) -> str:
    return (phone_cfg(content).get("device") or "").strip() or "手机"


def _thread(state: dict[str, Any], cid: str) -> dict[str, Any]:
    ph = state.setdefault("phone", {})
    return ph.setdefault("threads", {}).setdefault(cid, {"msgs": [], "unread": 0})


def _thread_tail(state: dict[str, Any], cid: str, n: int = 4) -> list[dict[str, Any]]:
    return list((((state.get("phone") or {}).get("threads") or {}).get(cid) or {}).get("msgs") or [])[-n:]


def sms_tail_line(state: dict[str, Any], cid: str) -> str:
    """ONE lean line of the recent exchange with this character, for scene continuity."""
    tail = _thread_tail(state, cid, 3)
    if not tail:
        return ""
    return "；".join(f"{'TA' if m.get('from') == 'me' else '你'}：{(m.get('text') or '')[:30]}"
                     for m in tail)


def phone_push(content: dict[str, Any], state: dict[str, Any], char: dict[str, Any],
               msgs: list[str], now_label: str) -> dict[str, Any]:
    """Deliver incoming message bubbles from a character. Returns the UI event payload."""
    th = _thread(state, char.get("id"))
    for m in msgs:
        th["msgs"].append({"from": "them", "text": m[:120], "at": now_label})
    th["msgs"] = th["msgs"][-60:]
    th["unread"] = int(th.get("unread", 0)) + len(msgs)
    return {"char_id": char.get("id"), "name": char.get("name") or "",
            "avatar_url": char.get("avatar_url"), "msgs": msgs,
            "device": phone_device(content)}


def compose_message(content: dict[str, Any], state: dict[str, Any], char: dict[str, Any],
                    reason: str, hint: str, fallback: str, llm: LLM) -> list[str]:
    """1~2 short in-voice bubbles for an occasion. LLM-written; deterministic fallback."""
    tun = tuning_for(content)
    scores = (state.get("rel") or {}).get(char.get("id")) or relationships.new_scores()
    try:
        out = llm.generate({"compose_msg": True, "device": phone_device(content),
                            "char": {"name": char.get("name"), "role": char.get("role") or "",
                                     "persona_text": (char.get("persona_text") or "")[:160],
                                     "eq_style": (char.get("eq_style") or "")[:120]},
                            "relation": relationships.name_of(
                                relationships.derive_mode(char, scores, tun)),
                            "reason": reason, "hint": hint,
                            "thread_tail": _thread_tail(state, char.get("id"))}) or {}
        msgs = [str(m).strip()[:120] for m in (out.get("msgs") or []) if str(m).strip()][:2]
    except Exception:
        msgs = []
    return msgs or [fallback]


def phone_deliveries(content: dict[str, Any], state: dict[str, Any], here_ids: set,
                     llm: LLM) -> list[dict[str, Any]]:
    """Turn-end scan: which ABSENT characters have a reason to reach out RIGHT NOW.
    Deterministic triggers (LLM only writes the words): ① a promise whose hour is next
    (reminder, once); ② just stood up (the hurt text, once); ③ a 暧昧/恋人 the player
    just parted from (the afterglow note, once per parting). Capped per turn."""
    if not phone_enabled(content):
        return []
    tun = tuning_for(content)
    now_idx = _time_index(state)
    now_label = (clock_view(content, state) or {}).get("label", "")
    dead = _dead_ids(state)
    met = set(state.get("met_ids") or [])
    out: list[dict[str, Any]] = []

    def absent(cid):
        return cid and cid in met and cid not in dead and cid not in here_ids

    # ① / ② promise-driven
    for pr in state.get("promises") or []:
        if len(out) >= PHONE_MAX_PER_TURN:
            break
        cid = pr.get("char_id")
        c = _char_by_id(content, cid)
        if not c or not absent(cid):
            continue
        when, what = promise_when_label(pr, state), pr.get("what") or ""
        if pr.get("status") == "open" and _promise_index(pr) == now_idx + 1 and not pr.get("reminded"):
            pr["reminded"] = True
            msgs = compose_message(content, state, c, "reminder",
                                   f"你们约好了{when}（{what}），时辰快到了，你捎话提醒TA，带上你自己的语气",
                                   f"别忘了{when}——{what}。我等你。", llm)
            out.append(phone_push(content, state, c, msgs, now_label))
        elif pr.get("status") in ("missed", "missed_noted") and not pr.get("texted"):
            pr["texted"] = True
            msgs = compose_message(content, state, c, "stood_up",
                                   f"TA爽约了你们约好的（{what}），你心里不好受，忍不住捎话给TA",
                                   "我等了你很久。你没来。", llm)
            out.append(phone_push(content, state, c, msgs, now_label))
    # ③ afterglow: a romance-tier character the player was JUST with, now apart
    seen = (state.get("phone") or {}).get("seen") or {}
    rels = state.get("rel") or {}
    for c in _characters(content):
        if len(out) >= PHONE_MAX_PER_TURN:
            break
        cid = c.get("id")
        if not absent(cid) or int(seen.get(cid, -99)) < now_idx - 1:
            continue
        if relationships.derive_mode(c, rels.get(cid) or relationships.new_scores(), tun) \
                not in ("flirt", "lover"):
            continue
        th = _thread(state, cid)
        if int(th.get("auto_idx", -1)) >= int(seen.get(cid, -99)):
            continue  # this parting already got its note
        th["auto_idx"] = int(seen.get(cid, -99))
        msgs = compose_message(content, state, c, "missing_you",
                               "TA刚离开你身边，你心里还想着TA，忍不住捎一句——短、软、像TA的性格",
                               "你刚走，我就开始想你了。", llm)
        out.append(phone_push(content, state, c, msgs, now_label))
    return out


def phone_threads_view(content: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    """The 信息 app's inbox: one row per thread, unread counts, newest first."""
    rows = []
    for cid, th in (((state.get("phone") or {}).get("threads")) or {}).items():
        c = _char_by_id(content, cid)
        msgs = th.get("msgs") or []
        if not c or not msgs:
            continue
        rows.append({"char_id": cid, "name": c.get("name") or "",
                     "avatar_url": c.get("avatar_url"), "dead": cid in _dead_ids(state),
                     "last": (msgs[-1].get("text") or "")[:40], "at": msgs[-1].get("at", ""),
                     "unread": int(th.get("unread", 0))})
    rows.reverse()
    rows.sort(key=lambda r: -r["unread"])
    return {"device": phone_device(content), "threads": rows,
            "unread": sum(r["unread"] for r in rows)}


def phone_thread(content: dict[str, Any], state: dict[str, Any], char_id: str,
                 mark_read: bool = True) -> dict[str, Any] | None:
    c = _char_by_id(content, char_id)
    if not c:
        return None
    th = _thread(state, char_id)
    if mark_read:
        th["unread"] = 0
    return {"char_id": char_id, "name": c.get("name") or "", "avatar_url": c.get("avatar_url"),
            "dead": char_id in _dead_ids(state), "device": phone_device(content),
            "msgs": list(th.get("msgs") or [])}


def phone_send(content: dict[str, Any], state: dict[str, Any], persona: dict[str, Any],
               char_id: str, text: str, llm: LLM | None = None) -> dict[str, Any]:
    """The player texts a character from anywhere. The character answers IN VOICE with
    their gated context (locked truths can't leak over text either) — or reads and says
    nothing (已读不回 is a statement too). Small relationship movement applies."""
    llm = llm or get_llm()
    if not phone_enabled(content):
        raise ValueError("这个故事里没有这种联系方式")
    c = _char_by_id(content, char_id)
    if not c:
        raise ValueError("没有这个人")
    if char_id in _dead_ids(state):
        raise ValueError("TA已不在人世——这条消息永远不会有回音了")
    if char_id == state.get("player_character_id"):
        raise ValueError("不能发给你自己")
    if char_id not in set(state.get("met_ids") or []):
        raise ValueError("你还不认识TA，没有TA的联系方式")
    text = (text or "").strip()
    if not text:
        raise ValueError("说点什么吧")
    tun = tuning_for(content)
    now_label = (clock_view(content, state) or {}).get("label", "")
    th = _thread(state, char_id)
    th["msgs"].append({"from": "me", "text": text[:200], "at": now_label})
    th["msgs"] = th["msgs"][-60:]
    scores = (state.get("rel") or {}).get(char_id) or relationships.new_scores()
    mode = relationships.derive_mode(c, scores, tun)
    ctx = gating.build_context(char_id, gating.iter_fragments(content), state, newly_ids=[])
    pcid = state.get("player_character_id")
    pc = _char_by_id(content, pcid) if pcid else None
    out = llm.generate({"phone_reply": True, "device": phone_device(content),
                        "char": {"name": c.get("name"), "role": c.get("role") or "",
                                 "persona_text": (c.get("persona_text") or "")[:200],
                                 "eq_style": (c.get("eq_style") or "")[:150],
                                 "agenda": (c.get("agenda") or "")[:100]},
                        "relation": relationships.name_of(mode),
                        "relationship_playbook": relationships.playbook_block(
                            mode, mature=bool(state.get("mature"))),
                        "context": ctx,
                        "player_name": (pc or {}).get("name") or (persona or {}).get("name") or "",
                        "memory": (state.get("memory_by_char", {}) or {}).get(char_id)
                        or state.get("memory", ""),
                        "thread_tail": _thread_tail(state, char_id, 8),
                        "text": text}) or {}
    msgs = [str(m).strip()[:120] for m in (out.get("msgs") or []) if str(m).strip()][:3]
    dc = int(out.get("closeness", 0) or 0)
    dr = int(out.get("romance", 0) or 0)
    if dc or dr:
        state.setdefault("rel", {})[char_id] = relationships.apply_deltas(scores, dc, dr, tun)
    if msgs:
        for m in msgs:
            th["msgs"].append({"from": "them", "text": m, "at": now_label})
        th["msgs"] = th["msgs"][-60:]
    th["unread"] = 0  # the player is looking at this thread right now
    view = phone_thread(content, state, char_id)
    view["replied"] = bool(msgs)
    return view


def rel_log(state: dict[str, Any], char_id: str | None, act: int, kind: str, text: str) -> None:
    """Append a moment to this character's 关系大事记 (capped)."""
    if not char_id or not (text or "").strip():
        return
    log = dict(state.get("rel_log") or {})
    entries = list(log.get(char_id) or [])
    entries.append({"act": int(act), "kind": kind, "text": text.strip()})
    log[char_id] = entries[-30:]
    state["rel_log"] = log


def _inv_find(items: list, name: str) -> int:
    """Index of an item matching `name` leniently, else -1."""
    n = (name or "").strip()
    for i, it in enumerate(items or []):
        inm = (it.get("name") or "").strip()
        if inm and (inm == n or inm in n or n in inm):
            return i
    return -1


def _inv_add(state: dict[str, Any], name: str, detail: str = "") -> bool:
    items = list(state.get("inventory") or [])
    if not (name or "").strip() or _inv_find(items, name) >= 0:
        return False
    items.append({"name": name.strip(), **({"detail": detail.strip()} if detail.strip() else {})})
    state["inventory"] = items
    return True


def _inv_remove(state: dict[str, Any], name: str) -> dict[str, Any] | None:
    items = list(state.get("inventory") or [])
    i = _inv_find(items, name)
    if i < 0:
        return None
    it = items.pop(i)
    state["inventory"] = items
    return it


def retrieve_stash(content: dict[str, Any], state: dict[str, Any],
                   player_input: str, channel: str = "say") -> list[dict[str, Any]]:
    """取回寄存: naming an item you stashed at THIS place (做/看 channel) puts it back in
    your pocket. Deterministic, mirrors search_props."""
    if channel not in ("do", "think"):
        return []
    loc = current_location(content, state)
    if not loc:
        return []
    lid = loc.get("id")
    stash = list((state.get("stashes") or {}).get(lid) or [])
    got = []
    for it in list(stash):
        if (it.get("name") or "") and _contains_any(player_input, [it["name"]]):
            stash.remove(it)
            _inv_add(state, it.get("name", ""), it.get("detail", ""))
            got.append(it)
    if got:
        stashes = dict(state.get("stashes") or {})
        if stash:
            stashes[lid] = stash
        else:
            stashes.pop(lid, None)
        state["stashes"] = stashes
    return got


def character_profile(content: dict[str, Any], state: dict[str, Any],
                      char_id: str) -> dict[str, Any] | None:
    """Everything the player may KNOW about one character, gathered for the 档案卡:
    public profile, relationship axes + next tier, their secrets' progress (titles only,
    and only once ≥1 layer is open), where they are, the shared 大事记 timeline, and the
    bio layers closeness has unlocked. Locked content never leaves the server."""
    c = _char_by_id(content, char_id)
    if not c:
        return None
    act = int(state.get("act", 1) or 1)
    tun = tuning_for(content)
    scores = (state.get("rel") or {}).get(char_id) or relationships.new_scores()
    rel = relationships.state_for(c, scores, tun)
    dead = char_id in _dead_ids(state)
    # their secrets: titles appear only after the first layer opened (journal's rule)
    unlocked = set(state.get("unlocked_fragment_ids") or [])
    secrets, hidden = [], 0
    for sec in content.get("secrets", []) or []:
        if sec.get("character_id") != char_id:
            continue
        frags = sec.get("fragments", []) or []
        got = sum(1 for f in frags if f.get("id") in unlocked)
        if got:
            secrets.append({"title": (sec.get("title") or "").strip(),
                            "unlocked": got, "total": len(frags)})
        else:
            hidden += 1
    # where they are right now (only if the place is discovered)
    home = char_home(c, act, active_slot(content, state))
    loc = _location_by_id(content, home) if (home and home != AWAY) else None
    where = (loc.get("name") if (loc and location_available(content, state, loc)) else None)
    if home == AWAY:
        where = "此刻不知去向"
    if char_id in set(state.get("following") or []):
        where = "与你同行"
    # 分层小传: closeness unlocks authored layers; the next locked bar is shown as a tease
    closeness = int(scores.get("closeness", 0))
    bio_open, bio_next = [], None
    for layer in sorted(c.get("bio_layers") or [], key=lambda x: int(x.get("closeness_min", 0))):
        need = int(layer.get("closeness_min", 0))
        if closeness >= need:
            bio_open.append(layer.get("text") or "")
        elif bio_next is None:
            bio_next = need
    return {
        "id": char_id, "name": c.get("name") or "", "role": c.get("role") or "",
        "persona_text": c.get("persona_text") or "", "avatar_url": c.get("avatar_url"),
        "is_lead": bool(c.get("is_lead")), "generated": bool(c.get("generated")),
        "dead": dead, "relation": rel,
        "following": char_id in set(state.get("following") or []),
        "can_follow": (not dead) and relationships.can_follow(c, scores, tun),
        "secrets": secrets, "secrets_hidden": hidden,
        "where": where,
        "ties": npc_ties_of(content, state, char_id),  # 🕸 TA与其他人 (met-only, no leaks)
        "log": list((state.get("rel_log") or {}).get(char_id) or []),
        "bio": [b for b in bio_open if b], "bio_next_at": bio_next,
        "closeness": closeness, "romance": int(scores.get("romance", 0)),
    }


def journal(content: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    """The player's reviewable dossier (线索档案 + 结局图鉴). Discovery made tangible:
    - secrets the player has STARTED uncovering, with their unlocked fragments' full text
      and a count of layers still locked (locked bodies never leave the server; untouched
      secrets aren't listed at all — only a global remaining count)
    - the ending gallery: achieved milestones by title, the rest as ？？？ slots
    - the key decisions already made."""
    unlocked = set(state.get("unlocked_fragment_ids") or [])
    story = content.get("story") or {}
    chars = {c.get("id"): c.get("name") for c in story.get("characters", []) or []}
    # 🃏 who can be confronted right now: the secret's owner, alive, standing in this scene
    here_ids = {c.get("id") for c in scene_characters(content, state)
                if c.get("id") != state.get("player_character_id")}
    secrets, untouched = [], 0
    for sec in content.get("secrets", []) or []:
        frags = sec.get("fragments", []) or []
        got = [f for f in frags if f.get("id") in unlocked]
        if not got:
            untouched += 1
            continue
        scid = sec.get("character_id")
        secrets.append({
            "title": (sec.get("title") or "").strip(),
            "character": chars.get(scid) or "",
            "character_id": scid,
            # 出示对峙 is offered only when there's still a layer to pry open
            "confrontable": bool(scid in here_ids and len(got) < len(frags)
                                 and (state.get("mode") or "character") != "god"),
            "unlocked": [(f.get("content") or "").strip() for f in got],
            "frags": [{"id": f.get("id"), "text": (f.get("content") or "").strip()} for f in got],
            "locked_count": len(frags) - len(got),
        })
    achieved = set(state.get("achieved_endings") or [])
    endings = [{"kind": e.get("kind", "normal"),
                "achieved": e.get("id") in achieved,
                "title": (e.get("title") or "") if e.get("id") in achieved else None}
               for e in story.get("endings", []) or []]
    loc_names = {l.get("id"): l.get("name") for l in _locations(content)}
    promises = [{"name": p.get("char_name") or "", "what": p.get("what") or "",
                 "when": promise_when_label(p, state), "status": p.get("status"),
                 "romantic": bool(p.get("romantic"))}
                for p in (state.get("promises") or [])]
    return {"secrets": secrets, "secrets_untouched": untouched, "endings": endings,
            "promises": promises,  # 🤝 约定史: open + kept + missed
            "choices": dict(state.get("choices") or {}),
            "identity": state.get("identity"),
            "identity_log": list(state.get("identity_log") or []),
            "inventory": list(state.get("inventory") or []),
            "stashes": [{"location": loc_names.get(lid, lid), "items": items}
                        for lid, items in (state.get("stashes") or {}).items() if items],
            "deaths": [c.get("name") for c in _characters(content)
                       if c.get("id") in _dead_ids(state) and c.get("name")]}


# ── 🌱 achievements & NG+ (二周目) ───────────────────────────────────────────────
# Story-AGNOSTIC milestones computed from the run state whenever an ending fires;
# they persist per (user, story) alongside the cross-run ending gallery. Perks are
# small NG+ start advantages a player earns by reaching any ending once.
PERKS = {
    "veteran": {"name": "故人", "desc": "似曾相识——开局便与每个人多几分亲近"},
    "instinct": {"name": "直觉", "desc": "冥冥之感——所有命运判定成功率 +10%"},
}
INSTINCT_BONUS = 10
VETERAN_CLOSENESS = 8


def compute_achievements(content: dict[str, Any], state: dict[str, Any]) -> list[dict[str, Any]]:
    """The achievements this run's CURRENT state has earned. Evaluated when an ending
    fires; the router merges them into the player's per-story meta. Pure & agnostic:
    only the abstract shape of the story is consulted, never any specific 剧本."""
    out: list[dict[str, Any]] = []
    achieved = list(state.get("achieved_endings") or [])
    if not achieved:
        return out
    story = content.get("story") or {}
    kinds = {e.get("id"): e.get("kind") for e in story.get("endings") or []}
    if any(kinds.get(eid) == "true" for eid in achieved):
        out.append({"id": "true_end", "name": "拨云见日", "desc": "达成真结局"})
    if _characters(content) and not state.get("dead_character_ids"):
        out.append({"id": "no_blood", "name": "一滴血都没流", "desc": "抵达结局时，无人死去"})
    all_frag_ids = {f.get("id") for f in gating.iter_fragments(content) if f.get("id")}
    if all_frag_ids and all_frag_ids <= set(state.get("unlocked_fragment_ids") or []):
        out.append({"id": "all_truths", "name": "无所不知", "desc": "揭开这个故事的全部真相"})
    tun = tuning_for(content)
    rel = state.get("rel") or {}
    if any(relationships.derive_mode(c, rel.get(c.get("id")) or relationships.new_scores(), tun)
           == "lover" for c in _characters(content)):
        out.append({"id": "heartbeat", "name": "心有所属", "desc": "有人真正为你心动"})
    if int(state.get("confronts_won") or 0) >= 3:
        out.append({"id": "interrogator", "name": "铁齿铜牙", "desc": "三次对质撬开真相"})
    if tun["turns_per_slot"] > 0 and int((state.get("clock") or {}).get("day", 1) or 1) <= 2:
        out.append({"id": "swift", "name": "雷厉风行", "desc": "两天之内便抵达结局"})
    return out


def _secret_has_newly(content: dict[str, Any], sid, newly) -> bool:
    """Did any of this secret's fragments unlock THIS turn?"""
    newset = set(newly or [])
    for s in content.get("secrets", []) or []:
        if s.get("id") == sid:
            return any(f.get("id") in newset for f in s.get("fragments", []) or [])
    return False


def build_parting_hook(content: dict[str, Any], state: dict[str, Any],
                       persona: dict[str, Any], llm: LLM | None = None) -> list[dict[str, Any]]:
    """悬念离场: ONE cliffhanger narration emitted when the player leaves mid-run — the last
    thing they see on return, pulling them back in. Spoiler-safe (topic labels only)."""
    llm = llm or get_llm()
    act = int(state.get("act", 1) or 1)
    topics = _pending_topics(act_progress(content, state, act))
    here = [c.get("name") for c in scene_characters(content, state) if c.get("name")]
    loc = current_location(content, state) or {}
    out = llm.generate({"parting": True, "persona": persona,
                        "place": loc.get("name") or "", "cast": here,
                        "topics": topics[:2], "scene": current_act(content, act)}) or {}
    beats = [b for b in (out.get("beats") or [])
             if b.get("type") == "description" and (b.get("text") or "").strip()]
    if not beats:
        hint = f"关于「{topics[0]}」的话" if topics else "有句话"
        beats = [{"type": "description", "speaker_name": None,
                  "text": f"（你起身离开。身后有人欲言又止——{hint}，似乎还没说完。）"}]
    return beats[:1]


def confront_stream(content: dict[str, Any], state: dict[str, Any], persona: dict[str, Any],
                    fragment_id: str, char_id: str,
                    llm: LLM | None = None, beat_log: list[dict[str, Any]] | None = None):
    """🃏 证据对峙: the player slams a truth they've UNLOCKED down in front of the character
    it belongs to. A visible opposed check decides the scene: success pries the secret's
    next layer open ON THE SPOT (evidence beats every unlock gate — but being cornered
    costs the relationship); failure hardens them, and a 大失败 hands them the round and
    feeds the story's pressure meter. Knowledge stops being a museum piece — it's a verb.

    Validates EAGERLY (raises ValueError with a player-readable reason), then returns a
    generator speaking the /play stream contract: ('dice',…) ('beat',…) ('final',…)."""
    llm = llm or get_llm()
    state = {**default_state(), **(state or {})}
    state["location_id"] = (current_location(content, state) or {}).get("id")
    if (state.get("mode") or "character") == "god":
        raise ValueError("旁观者不在故事里，无法与人对峙")
    target = _char_by_id(content, char_id)
    if not target:
        raise ValueError("没有这个人")
    if char_id in _dead_ids(state):
        raise ValueError("TA已不在人世")
    if char_id == state.get("player_character_id"):
        raise ValueError("不能对峙你自己")
    if not any(c.get("id") == char_id for c in scene_characters(content, state)):
        raise ValueError("TA不在这里——先找到TA再当面对质")
    secret = frag = None
    for sec in content.get("secrets") or []:
        for f in sec.get("fragments") or []:
            if f.get("id") == fragment_id:
                secret, frag = sec, f
                break
    if not frag:
        raise ValueError("没有这条线索")
    unlocked = set(state.get("unlocked_fragment_ids") or [])
    if fragment_id not in unlocked:
        raise ValueError("你还没真正掌握这条线索")
    if secret.get("character_id") != char_id:
        raise ValueError("这件事不在TA身上——证据要摆到当事人面前才有分量")
    next_locked = next((f for f in secret.get("fragments") or []
                        if f.get("id") not in unlocked), None)
    if next_locked is None:
        raise ValueError("关于这件事，TA已经没什么可瞒你的了")
    return _confront_gen(content, state, persona, secret, frag, next_locked, target, llm, beat_log)


def _confront_gen(content, state, persona, secret, frag, next_locked, target, llm, beat_log):
    tun = tuning_for(content)
    char_id = target.get("id")
    tname = target.get("name") or "TA"
    old_act = int(state.get("act", 1) or 1)
    rel_all = state.setdefault("rel", {})
    scores = rel_all.get(char_id) or relationships.new_scores()
    closeness = int(scores.get("closeness", 0))
    # the closer you are, the likelier they come clean when cornered
    chance = max(25, min(90, tun["confront_base"] + closeness // 2))
    if state.get("perk") == "instinct":   # 🌱 NG+ 直觉: every fate check runs warmer
        chance = min(95, chance + INSTINCT_BONUS)
    dice = _roll_check(chance)
    yield ("dice", dice)
    success = dice["outcome"] in ("success", "crit_success")
    if success:
        state["confronts_won"] = int(state.get("confronts_won") or 0) + 1
    forced_id = next_locked.get("id") if success else None
    if forced_id:
        state["unlocked_fragment_ids"] = sorted(set(state.get("unlocked_fragment_ids") or [])
                                                | {forced_id})
    # being cornered stings even when they yield; a 大成功 lands so true it costs nothing
    cost = tun["confront_cost"]
    dc = {"crit_success": 0, "success": -cost, "fail": -cost * 2, "crit_fail": -cost * 3}[dice["outcome"]]
    rel_deltas: dict[str, dict[str, int]] = {}
    if dc:
        rel_all[char_id] = relationships.apply_deltas(scores, dc, 0, tun)
        applied = int(rel_all[char_id].get("closeness", 0)) - closeness
        if applied:
            rel_deltas[char_id] = {"name": tname, "closeness": applied, "romance": 0}
    moments: list[dict[str, Any]] = [{"kind": "confront", "name": tname,
                                      "outcome": dice["outcome"]}]
    pcfg = pressure_cfg(content)
    if pcfg and dice["outcome"] == "crit_fail":
        # a blown confrontation makes noise. Capped at 99: only a full turn can blow the lid
        state["pressure"] = min(99, int(state.get("pressure", 0)) + 8)
        moments.append({"kind": "pressure", "note": "这场对质闹出了动静。",
                        "value": state["pressure"]})
    title = (secret.get("title") or "").strip() or "那件事"
    ev = (frag.get("content") or "").strip()
    beats_out: list[dict[str, Any]] = []

    def emit(b):
        beats_out.append(b)
        return ("beat", b)

    yield emit({"type": "description", "speaker_name": None,
                "text": f"（你直视着{tname}，把你已经知道的事一字一句摆到TA面前——{ev}）"})
    if forced_id:
        for t in _titles_for_fragments(content, [forced_id]):
            moments.append({"kind": "unlock", "title": t})
        rel_log(state, char_id, old_act, "confront",
                f"你当面摆出证据，TA终于松口——「{title}」又揭开一层。")
    else:
        rel_log(state, char_id, old_act, "confront",
                f"你拿「{title}」的证据当面对质，被TA挡了回来。")
    # the model PERFORMS the aftermath with the character's full normal context; the forced
    # fragment rides the standard new_reveal channel (【必须亲口说出来】 machinery)
    frags = gating.iter_fragments(content)
    ctx = gating.build_context(char_id, frags, state, newly_ids=[forced_id] if forced_id else [])
    pcid = state.get("player_character_id")
    player_char = _char_by_id(content, pcid) if pcid else None
    persona_for_prompt = persona or {}
    if player_char:
        persona_for_prompt = {**persona_for_prompt, "name": player_char.get("name"),
                              "background": player_char.get("background") or persona_for_prompt.get("background", "")}
    pl_name = persona_for_prompt.get("name") or "对方"
    sp_hist = history_for(beat_log, char_id) if beat_log is not None else []
    directed = llm.generate({
        "speaker_name": tname,
        "speaker_persona": target.get("persona_text", ""),
        "persona": persona_for_prompt,
        "player_input": f"（{pl_name}把关于「{title}」的证据摆在你面前，要你说清楚。）",
        "channel": "say",
        "context": ctx,
        "history": sp_hist,
        "memory": (state.get("memory_by_char", {}) or {}).get(char_id) or state.get("memory", ""),
        "world_facts": (content.get("story") or {}).get("world_facts") or "",
        "roster": _physical_roster(content, state, persona),
        "place": _physical_place(content, state),
        "eq_style": target.get("eq_style", ""),
        "agenda": target.get("agenda", ""),
        "relationship_playbook": relationships.playbook_block(
            relationships.derive_mode(target, rel_all.get(char_id) or scores, tun),
            mature=bool(state.get("mature"))),
        "knowledge": target.get("knowledge", ""),
        "mature": bool(state.get("mature")),
        "scene": current_act(content, old_act),
        "clock": (clock_view(content, state) or {}).get("label", ""),
        "confrontation": {"evidence": ev, "title": title, "outcome": dice["outcome"]},
    })
    for b in directed.get("beats", []):
        yield emit(b)
    # a successful confrontation may satisfy an act gate — let it open right here
    new_act = old_act
    max_act = _max_act_index(content)
    if act_has_gate(content, old_act) and max_act and can_advance(content, state, old_act):
        new_act = min(max_act, old_act + 1)
        state["act"], state["turns_in_act"] = new_act, 0
        nxt = current_act(content, new_act) or {}
        moments.append({"kind": "act", "index": new_act, "title": nxt.get("title", "")})
        yield emit({"type": "description", "speaker_name": None,
                    "text": f"—— 第{new_act}幕 · {nxt.get('title', '')} ——"})
        nc = choice_for_act(content, state, new_act)
        if nc:
            state["pending_choice"] = nc
    state["goal"] = current_goal(content, new_act)
    yield ("final", {
        "state": state,
        "newly_unlocked": [forced_id] if forced_id else [],
        "moments": moments,
        "rel_deltas": rel_deltas,
        "dice": dice,
        "goal": state["goal"],
        "progress": act_progress(content, state, new_act),
        "pending_choice": state.get("pending_choice"),
        "pressure_view": ({"name": pcfg.get("name"), "value": int(state.get("pressure", 0))}
                          if pcfg else None),
        "relations": relations_summary(content, state),
    })


def run_turn(
    content: dict[str, Any],
    state: dict[str, Any],
    persona: dict[str, Any],
    player_input: str,
    channel: str = "say",
    llm: LLM | None = None,
    history: list[dict[str, str]] | None = None,
    target_character_id: str | None = None,
) -> dict[str, Any]:
    """Advance one turn, returning the whole result at once (beats + state + extras).

    A thin wrapper over run_turn_stream — used by tests and the opening flow. The SSE
    endpoint uses run_turn_stream directly so each character's reply streams out as it's
    computed (first speaker in ~2-3s instead of waiting for the whole room)."""
    beats: list[dict[str, Any]] = []
    final: dict[str, Any] = {}
    for kind, payload in run_turn_stream(
        content, state, persona, player_input, channel, llm, history, target_character_id
    ):
        if kind == "beat":
            beats.append(payload)
        elif kind == "final":
            final = payload  # "dice" etc. ride inside the final payload for this wrapper
    final["beats"] = beats
    return final


def run_turn_stream(
    content: dict[str, Any],
    state: dict[str, Any],
    persona: dict[str, Any],
    player_input: str,
    channel: str = "say",
    llm: LLM | None = None,
    history: list[dict[str, str]] | None = None,
    target_character_id: str | None = None,
    beat_log: list[dict[str, Any]] | None = None,
    returning: bool = False,
):
    """Advance one turn as a GENERATOR. Yields ('beat', beat) for each beat the moment
    it's computed (so responders stream out one by one), then a final ('final', result)
    carrying state/scene/suggestions/ending/cast/goal. Pure w.r.t. DB."""
    llm = llm or get_llm()
    state = {**default_state(), **(state or {})}
    old_act = int(state.get("act", 1))
    # normalize the player's position to the EFFECTIVE location (unset → first authored)
    # so the location gating dimension always sees where they truly stand
    state["location_id"] = (current_location(content, state) or {}).get("id")
    tun = tuning_for(content)
    _ensure_npc_rel(content, state)  # 🕸 authored ties come alive on first touch
    # who stands in the scene as the turn OPENS — the closing diff narrates arrivals/exits
    here_before = {c.get("id") for c in scene_characters(content, state) if c.get("id")}
    emergent_ids: set = set()  # characters born THIS turn (their entrance is already scripted)
    all_beats: list[dict[str, Any]] = []  # accumulated for scene classification
    # snapshot which places are reachable BEFORE this turn, so we can announce any that
    # newly open up (so a new exit never just silently appears — "莫名其妙解锁" fix)
    locs_before = {l.get("id") for l in _locations(content) if location_available(content, state, l)}

    # 1. probing → asks counters (per secret); also note which characters are probed.
    #    Keyword hits are PROVISIONAL (they keep same-turn reveals working) — the primary
    #    director call judges what the player truly probed, and we reconcile after it.
    asks = dict(state.get("asks") or {})
    probed_secret_ids = _detect_asks(content, player_input)
    for sid in probed_secret_ids:
        asks[sid] = asks.get(sid, 0) + 1
    state["asks"] = asks
    provisional_asks = list(probed_secret_ids)
    sec_char = _secret_char_map(content)
    probed_char_ids = [sec_char.get(sid) for sid in probed_secret_ids if sec_char.get(sid)]

    _ev_before = set(state.get("triggered_event_ids") or [])
    _apply_event_triggers(content, state, player_input)
    provisional_events = set(state.get("triggered_event_ids") or []) - _ev_before

    # 1b. 现场搜查: naming a searchable prop at THIS place (做/看 channel) turns it over —
    #     physical evidence unlocks directly, its story event fires. Deterministic.
    found_props = search_props(content, state, player_input, channel)
    prop_frag_ids = [pf["fragment_id"] for pf in found_props if pf.get("fragment_id")]
    retrieved = retrieve_stash(content, state, player_input, channel)
    for pf in found_props:   # 🎒 a takeable prop goes straight into the pocket
        if pf.get("take"):
            _inv_add(state, pf.get("name", ""), pf.get("detail", ""))
    content_mutated = False  # set when this turn adds an emergent character

    # 1c. 🎲 fate check: a risky 做-action gets judged (tiny call) and ROLLED for real.
    #     The result is handed to the director, who must narrate accordingly — no fiat.
    dice = None
    if channel == "do" and tun["dice"] and (state.get("mode") or "character") != "god":
        rj = llm.generate({"risk_judge": True, "action": player_input,
                           "place": (current_location(content, state) or {}).get("name") or "",
                           "world_facts": (content.get("story") or {}).get("world_facts") or ""}) or {}
        try:
            risk = max(0, min(100, int(rj.get("risk", 100))))
        except (TypeError, ValueError):
            risk = 100
        if risk < 100:
            if state.get("perk") == "instinct":  # 🌱 NG+ 直觉: fate runs warmer
                risk = min(95, risk + INSTINCT_BONUS)
            dice = _roll_check(risk)
            yield ("dice", dice)

    # 2. gate on the CURRENT state (asks updated; affinity not yet changed this turn).
    #    asks-driven reveals surface THIS turn so the director can voice them; affinity-
    #    driven ones land NEXT turn (the warmth rose now, the confession follows) — that
    #    one-turn lag is intentional and reads naturally.
    frags = gating.iter_fragments(content)
    already0 = set(state.get("unlocked_fragment_ids") or [])
    newly = gating.evaluate_unlocks(state, frags)
    for fid in prop_frag_ids:  # physical evidence found by searching = direct unlock
        if fid not in already0 and fid not in newly:
            newly.append(fid)
    state["unlocked_fragment_ids"] = sorted(already0 | set(newly))

    # judgment candidates for the primary director call (titles/labels only, never bodies)
    probe_cands = _probe_candidates(content, state)
    event_cands = _event_candidates(content, state, old_act)

    # THRESHOLD MOMENTS (阈值时刻演出): structured events the UI celebrates — a truth
    # clicking into place, a relationship tier-up, a new act, an ending milestone.
    moments: list[dict[str, Any]] = []
    rel_deltas: dict[str, dict[str, int]] = {}   # per-char ♥ movement this turn (UI float)
    pressure_blown = False                       # ⚠️ meter hit 100 → forced terminal ending
    for t in _titles_for_fragments(content, newly):
        moments.append({"kind": "unlock", "title": t})
    if newly:
        newset = set(newly)
        logged = set()
        for sec in content.get("secrets", []) or []:
            scid = sec.get("character_id")
            title = (sec.get("title") or "").strip()
            if scid and title and sec.get("id") not in logged                     and any(f.get("id") in newset for f in sec.get("fragments", []) or []):
                logged.add(sec.get("id"))
                rel_log(state, scid, old_act, "reveal", f"关于「{title}」的真相，揭开了一层。")

    # responder selection. With an explicit @target → just that character. With NO target
    # (and not an inner thought) the player is addressing the WHOLE room — every present
    # character may answer, though some can choose to stay silent. Otherwise the router
    # picks the single most-relevant speaker.
    mode = state.get("mode") or "character"
    pcid = state.get("player_character_id")  # the character the player embodies (character mode)

    # only characters in the player's CURRENT scene take part (present this act AND here by
    # location/following). In CHARACTER mode the player IS pcid, so that character is not an
    # NPC responder. In GOD mode the player embodies no one.
    all_chars = [c for c in scene_characters(content, state) if c.get("id") != pcid]

    # 关系大事记: first time you lay eyes on someone, remember where it happened
    met = set(state.get("met_ids") or [])
    here_name = (current_location(content, state) or {}).get("name") or ""
    for c in all_chars:
        cid = c.get("id")
        if cid and cid not in met:
            met.add(cid)
            rel_log(state, cid, old_act, "meet",
                    f"初次见面{('，在' + here_name) if here_name else ''}。")
    state["met_ids"] = sorted(met)

    # 📱 remember WHEN the player was last face to face with each character — the
    # afterglow text trigger ("你刚走就想你了") keys off this parting moment
    ph_seen = state.setdefault("phone", {}).setdefault("seen", {})
    for c in all_chars:
        if c.get("id"):
            ph_seen[c["id"]] = _time_index(state)

    # 🤝 赴约: an open promise whose hour is NOW, its person standing right here, the
    # player at the promised place → this very scene is the appointment. Steer the
    # conversation to them; the relationship reward lands immediately (you SHOWED UP).
    promise_kept = None
    if mode != "god" and tun["turns_per_slot"] > 0 and channel != "think":
        now_idx = _time_index(state)
        here_ids = {c.get("id") for c in all_chars}
        for pr in state.get("promises") or []:
            if (pr.get("status") == "open" and _promise_index(pr) == now_idx
                    and pr.get("char_id") in here_ids
                    and ((not pr.get("location_id"))
                         or pr["location_id"] == state.get("location_id"))):
                promise_kept = pr
                break
        if promise_kept:
            promise_kept["status"] = "kept"
            if not target_character_id:
                target_character_id = promise_kept["char_id"]
            kc = promise_kept["char_id"]
            old_sc = (state.get("rel") or {}).get(kc) or relationships.new_scores()
            state.setdefault("rel", {})[kc] = relationships.apply_deltas(
                old_sc, tun["promise_keep_bonus"],
                tun["promise_keep_bonus"] if promise_kept.get("romantic") else 0, tun)
            got = state["rel"][kc]
            dcl = int(got.get("closeness", 0)) - int(old_sc.get("closeness", 0))
            drm = int(got.get("romance", 0)) - int(old_sc.get("romance", 0))
            if dcl or drm:
                rel_deltas[kc] = {"name": promise_kept.get("char_name"),
                                  "closeness": dcl, "romance": drm}
            moments.append({"kind": "promise", "status": "kept",
                            "name": promise_kept.get("char_name"),
                            "what": promise_kept.get("what"),
                            "romantic": bool(promise_kept.get("romantic"))})
            rel_log(state, kc, old_act, "promise",
                    f"你如约而至——{promise_kept.get('what','')}。")

    if mode == "god":
        # Invisible-observer mode: the player doesn't speak in-scene; the present cast
        # interact WITH EACH OTHER (the 旁观/CP mode). The player's input is a director
        # cue. Everyone present takes part; an explicit target spotlights one character.
        observer = True
        if target_character_id:
            spot = _char_by_id(content, target_character_id)
            primary = spot or (all_chars[0] if all_chars else None)
        else:
            primary = all_chars[0] if all_chars else None
        primary_id = primary.get("id") if primary else None
        broadcast = len(all_chars) > 1
        responders = [primary] if primary else []
    else:
        observer = False
        primary = pick_responder(content, state, player_input, target_character_id, probed_char_ids, all_chars)
        primary_id = primary.get("id") if primary else None
        broadcast = bool(primary) and channel != "think" and not target_character_id and len(all_chars) > 1
        if primary is None or channel == "think":
            # think = observe/examine (handled separately below), no NPC responds
            responders = []
        else:
            responders = [primary]
    # REAL conversations aren't a roll call: in a broadcast, the members who follow are
    # decided AFTER the primary speaks — by the primary's next_speakers judgment (who would
    # naturally chime in, 0~2, order = who jumps in first), plus deterministic must-speaks
    # (named in the player's line / owner of a probed secret). No judgment (mock/prose) →
    # legacy everyone-answers. See the extension inside the responder loop.
    member_pool = [c for c in all_chars if c.get("id") != primary_id] if broadcast else []
    pcfg = pressure_cfg(content)
    dead_names = [c.get("name") for c in _characters(content)
                  if c.get("id") in _dead_ids(state) and c.get("name")]
    gen_count = sum(1 for c in _characters(content) if c.get("generated"))
    if channel != "think":
        state["last_speaker_id"] = primary_id

    # In character mode the player speaks AS their chosen character — give the model that
    # identity instead of the generic persona name, so NPCs address the right person.
    player_char = _char_by_id(content, pcid) if (mode == "character" and pcid) else None
    persona_for_prompt = persona
    if player_char:
        persona_for_prompt = {**(persona or {}), "name": player_char.get("name"),
                              "background": player_char.get("background") or (persona or {}).get("background", "")}
    # 🎖 the player's EVOLVED identity overrides the authored one (升职/揭穿/新头衔) —
    # NPCs address and treat them by who they are NOW
    if state.get("identity"):
        persona_for_prompt = {**(persona_for_prompt or {}),
                              "background": ((persona_for_prompt or {}).get("background") or "")
                              + f"　【TA现在的身份：{state['identity']}——在场的人都知道并按此对待TA】"}

    # think only applies when the player actually embodies/voices someone (not in god mode)
    is_think = channel == "think" and not observer
    # the player spoke/acted but NOBODY is in this scene to answer (e.g. they walked into an
    # empty place) → narrate the place + their action instead of emitting silence.
    narrate_only = (not observer) and (channel != "think") and (not responders)

    # hard-gate guidance: is this act still locked, and what key info is still missing?
    # (unlocks for THIS turn already applied above, so this reflects the current truth.)
    progress0 = act_progress(content, state, old_act)
    needed_topics = _pending_topics(progress0)
    act_locked = act_has_gate(content, old_act) and not can_advance(content, state, old_act)

    # stuck-hint escalation: how many consecutive PRIOR turns the player has been on this
    # gated act without uncovering a new required clue. The longer they spin, the more
    # forthcoming the NPCs' guidance becomes (and at the top tier a narrator nudge fires).
    # Only meaningful while the act is locked and there's still something to find.
    stuck_in = int(state.get("stuck", 0) or 0) if (act_locked and needed_topics) else 0
    stuck_level = 1 if stuck_in >= tun["stuck_nudge"] else 0
    stuck_level = 2 if stuck_in >= tun["stuck_push"] else stuck_level

    # 3. the model is the DIRECTOR for each responder: per-speaker gated context (so a
    #    character can only ever voice what IT is allowed to know — no cross-leak). Each
    #    responder's beats are YIELDED the moment they're computed → they stream out.
    next_act = current_act(content, old_act + 1)
    place = _physical_place(content, state)   # concrete "you are here" anchor (empty if none)
    affinity_delta = 0
    advance = False
    model_ending = None
    primary_invite = None  # a character asked to LEAD the player elsewhere → confirm prompt
    time_skip = ""         # ⏳ the primary judged the scene skipped time (睡到天亮/等到入夜)

    # ⏳ the hour, for narration consistency + deadline awareness (one lean line)
    clock_line = ""
    cv0 = clock_view(content, state)
    if cv0:
        clock_line = cv0["label"]
        dl0 = cv0.get("deadline")
        if dl0 and dl0["days_left"] > 0:
            clock_line += f"。距离「{dl0['text']}」还有{dl0['days_left']}天"
        elif dl0 and dl0["days_left"] == 0:
            clock_line += f"。「{dl0['text']}」就在今天"

    def emit(b: dict[str, Any]):
        all_beats.append(b)
        return ("beat", b)

    # Group naturalness (SillyTavern-style): characters answer ONE AT A TIME and each later
    # speaker is shown what the others ALREADY said THIS turn, so they genuinely react to one
    # another (接话/附和/反驳) instead of being generated in parallel and talking past each
    # other / echoing the same opener.
    said_this_turn: list[dict[str, str]] = []
    responder_hist: dict[str, list[dict[str, str]]] = {}  # each responder's witnessed history

    rel_all = state.setdefault("rel", {})
    # relationship mode applies to character↔player only (not god/observer, not the
    # player's own embodied character)
    rel_active = (not observer)

    for it in retrieved:
        yield emit({"type": "description", "speaker_name": None,
                    "text": f"（你取回了之前放在这里的{it.get('name','')}。）"})

    # searching paid off → narrate the physical evidence BEFORE anyone reacts to it
    for pf in found_props:
        body = _fragment_content(content, pf.get("fragment_id"))
        if body:
            yield emit({"type": "description", "speaker_name": None,
                        "text": f"（你翻查{pf['name']}——{body}）"})
        elif pf.get("detail"):
            yield emit({"type": "description", "speaker_name": None,
                        "text": f"（你翻查{pf['name']}：{pf['detail']}）"})
        else:
            yield emit({"type": "description", "speaker_name": None,
                        "text": f"（你翻查了{pf['name']}，没有发现特别的东西。）"})

    for idx, sp in enumerate(responders):
        sp_id = sp.get("id")
        sp_name = sp.get("name") or "角色"
        ctx = gating.build_context(sp_id, frags, state, newly_ids=newly)
        rel_scores = rel_all.get(sp_id) or relationships.new_scores()
        rel_playbook = relationships.playbook_block(
            relationships.derive_mode(sp, rel_scores, tun), mature=bool(state.get("mature"))) if rel_active else ""
        others = [c.get("name") for c in all_chars if c.get("id") != sp_id and c.get("name")]
        is_primary = idx == 0
        # each character only recalls what THEY witnessed + their OWN private digest — no
        # silent cross-character/cross-scene info leak.
        sp_hist = history_for(beat_log, sp_id) if beat_log is not None else (history or [])
        responder_hist[sp_id] = sp_hist
        sp_mem = (state.get("memory_by_char", {}) or {}).get(sp_id) or state.get("memory", "")
        prompt = {
            "speaker_name": sp_name,
            "speaker_persona": sp.get("persona_text", ""),
            "persona": persona_for_prompt,
            "player_input": player_input,
            "channel": channel,
            "context": ctx,
            "history": sp_hist,
            "memory": sp_mem,   # THIS character's private rolling digest
            "world_facts": (content.get("story") or {}).get("world_facts") or "",
            "roster": _physical_roster(content, state, persona),  # deterministic headcount
            "place": place,                       # concrete current-location anchor (if authored)
            "eq_style": sp.get("eq_style", ""),   # how THIS character reads/expresses emotion
            "agenda": sp.get("agenda", ""),       # this character's OWN goal/will (autonomy)
            "relationship_playbook": rel_playbook,  # current relationship mode toward player
            "player_emotion": state.get("player_emotion", ""),  # prior emotional read (continuity)
            "knowledge": sp.get("knowledge", ""),  # 智能增强: this character's background lore
            "mature": bool(state.get("mature")),   # 18+ run → adult content permitted
            "scene": current_act(content, old_act),
            "next_act_title": (next_act or {}).get("title", "") if next_act else "",
            "clock": clock_line,                  # ⏳ 第几天·什么时段 (+ deadline countdown)
            # 🕸 this speaker's charged stances toward who else is in the scene
            "npc_stances": npc_stance_line(content, state, sp_id,
                                           [c for c in all_chars if c.get("id") != sp_id]),
            # 🤝 THIS scene is the appointment being honored (a romance one plays as a date)
            "appointment": ({"what": promise_kept.get("what", ""),
                             "romantic": bool(promise_kept.get("romantic"))}
                            if (promise_kept and sp_id == promise_kept.get("char_id")) else None),
            # 🤝 the player stood this speaker up — they hold it (voiced once, then let go)
            "broken_promise": next((p.get("what") for p in (state.get("promises") or [])
                                    if p.get("status") == "missed" and p.get("char_id") == sp_id), None),
            # 📱 what you two texted lately — the scene remembers the phone
            "sms_tail": sms_tail_line(state, sp_id),
            "cast": others,
            # in a broadcast, non-primary characters may stay silent and never narrate
            "group_mode": ("primary" if is_primary else "member") if broadcast else None,
            # god mode: characters interact with EACH OTHER; player is an unseen director
            "observer": observer,
            "director_note": player_input if observer else None,
            # hard-gate: act not yet cleared → don't resolve/jump; may steer toward these
            "act_locked": act_locked,
            "needed_topics": needed_topics,
            "stuck_level": stuck_level,
            # ask/event judgment: the primary states what the player truly probed and which
            # story events actually happened this turn (keyword hits above are provisional)
            "probe_candidates": probe_cands if is_primary else [],
            "event_candidates": event_cands if is_primary else [],
            # the player came back after a while away → greet them and pick up the thread
            "returning": bool(returning) if is_primary else False,
            # 🎲 the fate roll for this 做-action (director must narrate its outcome)
            "check": dice if is_primary else None,
            # ⚠️ the story's pressure meter (model judges this turn's delta)
            "pressure_cfg": ({**pcfg, "value": int(state.get("pressure", 0))}
                             if (pcfg and is_primary) else None),
            # ☠️/👋/🎖/🎒 dynamic-world context
            "deaths": dead_names,
            "player_items": ([i.get("name") for i in (state.get("inventory") or [])]
                             if is_primary else []),
            "can_new_char": (is_primary and gen_count < tun["max_new_characters"]),
            # what the others have ALREADY said this turn → react, don't echo
            "said_this_turn": list(said_this_turn),
        }
        directed = llm.generate(prompt)
        if prompt.get("broken_promise"):
            # the grudge got its scene — from here on it's history, not a broken record
            for p in (state.get("promises") or []):
                if p.get("status") == "missed" and p.get("char_id") == sp_id:
                    p["status"] = "missed_noted"
        # LOGIC BACKSTOP (primary/addressed character only): verify the turn against the live
        # scene before streaming it — no absent character walks in, no locked secret leaks.
        if is_primary and not observer and get_settings().logic_guard:
            directed = _logic_guard(llm, prompt, directed, content, state, frags)
        d_beats = directed.get("beats", [])
        if not is_primary:
            # members contribute dialogue only (one shared narration from the primary)
            d_beats = [b for b in d_beats if b.get("type") == "dialogue"]
            # ECHO GUARD: drop a member line that just parrots what someone already said this
            # turn (verbatim or near-verbatim) — better silence than two characters in unison.
            prior_said = {_norm_line(s.get("text", "")) for s in said_this_turn}
            d_beats = [b for b in d_beats if _norm_line(b.get("text", "")) not in prior_said
                       and not _too_similar(b.get("text", ""), said_this_turn)]
        for b in d_beats:
            said_this_turn.append({
                "speaker": b.get("speaker_name") or "旁白",
                "text": b.get("text", ""),
            })
            yield emit(b)
        this_delta = int(directed.get("affinity_delta", 0) or 0)
        affinity_delta += this_delta
        # per-character relationship FLOW: apply this speaker's own closeness (=好感) and
        # 心动 deltas to their relationship-toward-player scores; the derived mode shifts
        # gradually (clamped) so next turn this character treats the player accordingly.
        if rel_active and sp_id and sp_id != pcid:
            old_scores = rel_all.get(sp_id) or relationships.new_scores()
            mode_before = relationships.derive_mode(sp, old_scores, tun)
            rel_all[sp_id] = relationships.apply_deltas(
                old_scores, this_delta, int(directed.get("romance_delta", 0) or 0), tun,
            )
            mode_after = relationships.derive_mode(sp, rel_all[sp_id], tun)
            dc = int(rel_all[sp_id].get("closeness", 0)) - int(old_scores.get("closeness", 0))
            dr = int(rel_all[sp_id].get("romance", 0)) - int(old_scores.get("romance", 0))
            if dc or dr:
                rel_deltas[sp_id] = {"name": sp_name, "closeness": dc, "romance": dr}
            # CELEBRATE a tier-up (陌生→朋友→暧昧→恋人): the "高潮=阈值被跨过" moment, made
            # visible — a strong reward + come-back hook. Only on an UPGRADE, never a downgrade.
            if mode_after != mode_before and _RANK.get(mode_after, 0) > _RANK.get(mode_before, 0):
                moments.append({"kind": "rel_up", "character_id": sp_id, "name": sp_name,
                                "mode": mode_after,
                                "mode_name": relationships.name_of(mode_after)})
                rel_log(state, sp_id, old_act, "rel_up",
                        f"你们成了「{relationships.name_of(mode_after)}」。")
                yield emit({"type": "description", "speaker_name": None,
                            "text": f"💗（你感觉到，和{sp_name}的关系又近了一层——现在你们是"
                                    f"「{relationships.name_of(mode_after)}」了。）"})
        if directed.get("advance_act"):
            advance = True
        if is_primary:
            model_ending = directed.get("ending")  # only the addressed scene can end the run
            # a character may ASK to lead the player elsewhere — captured here, surfaced as a
            # confirm prompt (never auto-applied; the player relocates via /move on a yes).
            primary_invite = directed.get("move_invite")
            primary_name_for_invite = sp_name
            time_skip = (directed.get("time_skip") or "").strip()
            # 🤝 the speaker set a future appointment with the player (恋与深空-style
            # proactive 邀约 at romance tiers) — record it, announce it, hang it in the bar
            pm = directed.get("promise")
            if pm and not observer:
                made = make_promise(content, state, sp, pm, tun)
                if made:
                    loc_nm = (_location_by_id(content, made.get("location_id")) or {}).get("name") or "老地方"
                    when = promise_when_label(made, state)
                    moments.append({"kind": "promise", "status": "made",
                                    "name": sp_name, "what": made["what"], "when": when,
                                    "romantic": bool(made.get("romantic"))})
                    yield emit({"type": "description", "speaker_name": None,
                                "text": f"（约定立下了：{when}，{loc_nm}——{made['what']}。）"})
            emo = (directed.get("player_emotion") or "").strip()
            if emo:
                state["player_emotion"] = emo       # carry the emotional read into next turn
            # RECONCILE ask/event judgment (root fix for keyword-stuffing). When the model
            # supplies a judgment it becomes the truth: a provisional keyword ask it rejects
            # is rolled back (unless it already unlocked something — unlocks stay sticky),
            # and a genuine probe the keywords missed is counted (its reveal lands next
            # turn, same one-turn lag as affinity reveals). No judgment (mock/prose
            # fallback) → the keyword result stands, so tests stay deterministic.
            judged = directed.get("probed")
            if judged is not None:
                judged_ids = _match_candidates(probe_cands, judged, "title")
                for sid in provisional_asks:
                    if sid not in judged_ids and asks.get(sid, 0) > 0 \
                            and not _secret_has_newly(content, sid, newly):
                        asks[sid] -= 1
                for sid in judged_ids:
                    if sid not in provisional_asks:
                        asks[sid] = asks.get(sid, 0) + 1
                state["asks"] = asks
            occurred = directed.get("occurred")
            if occurred is not None:
                ev_ids = _match_candidates(event_cands, occurred, "label")
                trig = set(state.get("triggered_event_ids") or [])
                trig -= (provisional_events - ev_ids)  # roll back denied keyword guesses
                trig |= ev_ids
                state["triggered_event_ids"] = sorted(trig)
            # ⚠️ pressure: apply the judged delta, announce level crossings, remember a blowout
            if pcfg and directed.get("pressure_delta") is not None:
                p_old = int(state.get("pressure", 0))
                p_new = max(0, min(100, p_old + int(directed.get("pressure_delta") or 0)))
                state["pressure"] = p_new
                for lv in sorted(pcfg.get("levels") or [], key=lambda x: int(x.get("at", 0))):
                    at = int(lv.get("at", 0))
                    if p_old < at <= p_new and (lv.get("note") or "").strip():
                        yield emit({"type": "description", "speaker_name": None,
                                    "text": f"（{lv['note']}）"})
                        moments.append({"kind": "pressure", "note": lv["note"], "value": p_new})
                if p_new >= 100:
                    pressure_blown = True
            # ☠️ DEATH: a character died this turn — gone for good, remembered by everyone
            died_ref = (directed.get("died") or "").strip()
            if died_ref:
                victim = next((c for c in scene_characters(content, state)
                               if c.get("id") != pcid and (c.get("name") or "")
                               and ((c["name"] == died_ref) or (c["name"] in died_ref)
                                    or (died_ref in c["name"]))), None)
                if victim:
                    deads = _dead_ids(state)
                    deads.add(victim["id"])
                    state["dead_character_ids"] = sorted(deads)
                    state["following"] = [f for f in (state.get("following") or [])
                                          if f != victim["id"]]
                    dead_names.append(victim.get("name"))
                    moments.append({"kind": "death", "name": victim.get("name")})
                    rel_log(state, victim.get("id"), old_act, "death",
                            f"{victim.get('name')} 死了。")
            # 👋 EMERGENT CHARACTER: the story brought in a brand-new face — make them real
            nc_raw = (directed.get("new_char") or "").strip()
            if nc_raw and gen_count < tun["max_new_characters"]:
                import re as _re
                import uuid as _uuid
                parts = _re.split(r"[｜|：:，,]", nc_raw, maxsplit=1)
                nc_name = parts[0].strip().strip("「」\"'")[:12]
                nc_desc = (parts[1].strip() if len(parts) > 1 else "")[:120]
                exists = any((c.get("name") or "") == nc_name for c in _characters(content))
                if nc_name and not exists:
                    nc_id = f"gen_{_uuid.uuid4().hex[:8]}"
                    emergent_ids.add(nc_id)
                    (content.get("story") or {}).setdefault("characters", []).append({
                        "id": nc_id,
                        "name": nc_name,
                        "role": nc_desc[:24] or "新登场的人物",
                        "persona_text": nc_desc,
                        "relation_default": "stranger",
                        "home_location_id": state.get("location_id"),
                        "generated": True,
                    })
                    content_mutated = True
                    gen_count += 1
                    moments.append({"kind": "arrival", "name": nc_name})
            # 🕸 NPC↔NPC shifts: the scene moved two characters closer/apart (≤2 a turn,
            # both must be living and present, never the player — engine-enforced)
            for sh in (directed.get("npc_shifts") or [])[:2]:
                applied_sh = apply_npc_shift(content, state, sh.get("a"), sh.get("b"),
                                             sh.get("delta"), sh.get("why", ""), old_act)
                if applied_sh:
                    moments.append({"kind": "npc_rel", **applied_sh})
            # 🎖 IDENTITY: the player's role/standing changed for real
            idt = (directed.get("identity") or "").strip()
            if idt and not observer and idt != (state.get("identity") or ""):
                state["identity"] = idt
                log = list(state.get("identity_log") or [])
                log.append({"act": old_act, "text": idt})
                state["identity_log"] = log
                moments.append({"kind": "identity", "text": idt})
            # 🎒 ITEMS: gained / lost / stashed at the current place
            if not observer:
                g = (directed.get("gained") or "").strip()
                if g and _inv_add(state, g):
                    moments.append({"kind": "item", "verb": "gained", "name": g})
                l = (directed.get("lost") or "").strip()
                if l:
                    it = _inv_remove(state, l)
                    if it:
                        moments.append({"kind": "item", "verb": "lost", "name": it.get("name")})
                st_ref = (directed.get("stashed") or "").strip()
                if st_ref:
                    it = _inv_remove(state, st_ref)
                    if it and state.get("location_id"):
                        stashes = dict(state.get("stashes") or {})
                        stashes.setdefault(state["location_id"], []).append(it)
                        state["stashes"] = stashes
                        moments.append({"kind": "item", "verb": "stashed", "name": it.get("name")})
            # WHO ELSE speaks this turn: the primary judged who'd naturally chime in
            # (varies 0~2 by context/personality — not everyone, not a fixed order);
            # characters named by the player or whose secret was probed always get to
            # speak. Extending the list mid-iteration is safe (list iterator is indexed).
            if broadcast and member_pool:
                picked = directed.get("next_speakers")
                if picked is None:
                    chosen = list(member_pool)  # no judgment (mock/prose) → legacy: everyone
                else:
                    chosen = []
                    for nm in picked:
                        nm = str(nm).strip()
                        for c in member_pool:
                            cn = c.get("name") or ""
                            if nm and cn and (cn == nm or cn in nm or nm in cn) and c not in chosen:
                                chosen.append(c)
                    for c in member_pool:  # deterministic must-speaks
                        if c in chosen:
                            continue
                        cn = c.get("name") or ""
                        if (cn and cn in (player_input or "")) or c.get("id") in probed_char_ids:
                            chosen.append(c)
                    chosen = chosen[:3]
                responders.extend(chosen)

    # think = OBSERVE/EXAMINE. No target → look at the surroundings (where am I, what's
    # going on). With a target → examine that person: a brief intro + their CURRENT state
    # (expression / posture / appearance / mood). Narration only; no dialogue, no affinity;
    # secrets are never passed in, so observation can't leak locked truths.
    if is_think or narrate_only:
        observe_target = _char_by_id(content, target_character_id) if (is_think and target_character_id) else None
        directed = llm.generate({
            "observe": True,
            "observe_target": observe_target,
            "persona": persona_for_prompt,
            "player_input": player_input,
            "scene": current_act(content, old_act),
            "world": (content.get("story") or {}).get("world_long", "") or "",
            "world_facts": (content.get("story") or {}).get("world_facts") or "",
            "roster": _physical_roster(content, state, persona),
            "place": place,
            "knowledge": (observe_target or {}).get("knowledge", "") if observe_target else "",
            "mature": bool(state.get("mature")),
            # observe = the PLAYER looking around → the player's own full view (they witnessed
            # everything they did); their private digest.
            "history": (history_for(beat_log, pcid) if beat_log is not None else (history or [])),
            "memory": (state.get("memory_by_char", {}) or {}).get(pcid) or state.get("memory", ""),
            "cast": [c.get("name") for c in all_chars if c.get("name")],
        })
        obs = [b for b in directed.get("beats", []) if b.get("type") == "description"]
        if not obs:
            obs = [{"type": "description", "speaker_name": None,
                    "text": ((directed.get("beats") or [{}])[0].get("text", ""))}]
        for b in obs:
            yield emit(b)
        affinity_delta = 0

    # 🌊 the world moves by itself: after enough quiet turns, an authored event of the
    #    current act HAPPENS (its people must be in the player's scene) — the world stops
    #    waiting for the player to make everything occur. Feeds event-gated progress too.
    if not is_think and responders:
        trig_now = set(state.get("triggered_event_ids") or [])
        if trig_now - _ev_before:
            state["world_pulse"] = 0          # something already happened this turn
        else:
            state["world_pulse"] = int(state.get("world_pulse", 0) or 0) + 1
        wev = tun["world_event_every"]
        if wev > 0 and state["world_pulse"] >= wev:
            here_ids = {c.get("id") for c in scene_characters(content, state)}
            for ev in (current_act(content, old_act) or {}).get("events", []) or []:
                eid = ev.get("id")
                who = ev.get("who_character_ids") or []
                if eid and eid not in trig_now and (not who or set(who) <= here_ids)                         and (ev.get("what_happens") or "").strip():
                    trig_now.add(eid)
                    state["triggered_event_ids"] = sorted(trig_now)
                    yield emit({"type": "description", "speaker_name": None,
                                "text": f"就在这时——{ev['what_happens']}"})
                    moments.append({"kind": "event", "label": ev["what_happens"][:40]})
                    state["world_pulse"] = 0
                    break

    affinity_delta = 0 if is_think else max(tun["affinity_clamp_min"],
                                            min(tun["affinity_clamp_max"], affinity_delta))
    if affinity_delta > 0:
        # diminishing returns: the warmer things already are, the less another nice line moves
        scale = max(0.3, 1 - int(state.get("affinity", 0)) / max(1, tun["affinity_taper_den"]))
        affinity_delta = max(1, int(round(affinity_delta * scale)))

    # 4. apply affinity, then decide progression. HARD GATE: if this act authored advance
    #    conditions, it advances ONLY when can_advance() is satisfied (program-checked) —
    #    the model's 推进 and affinity backstop can no longer talk past it. Acts with NO
    #    authored conditions fall back to the old soft advance (model 推进 / affinity).
    state["affinity"] = max(0, int(state.get("affinity", 0)) + affinity_delta)
    if not is_think:
        state["turns_in_act"] = int(state.get("turns_in_act", 0) or 0) + 1
    max_act = _max_act_index(content)
    if act_has_gate(content, old_act):
        new_act = (min(max_act, old_act + 1)
                   if (max_act and can_advance(content, state, old_act)) else old_act)
    else:
        # a soft act needs REAL time in it before anything can advance it — the model's
        # eager 推进 and the affinity backstop both wait out min_turns_per_act, and a turn
        # moves at most ONE act (no affinity-fueled multi-act jumps).
        if int(state.get("turns_in_act", 0)) >= tun["min_turns_per_act"]:
            backstop = 1 + state["affinity"] // tun["act_backstop_div"]  # stall safety net
            target = max(old_act + (1 if advance else 0), backstop)
        else:
            target = old_act
        target = min(target, old_act + 1)
        new_act = min(max_act, target) if max_act else target
    if new_act > old_act:
        state["turns_in_act"] = 0
    state["act"] = new_act

    # 4a. (movement is player-driven only — see the /move endpoint. The model can no longer
    #     relocate the player, so there is no model-reported place to apply here.)

    # 4b. update the stuck counter for NEXT turn: did THIS turn make headway on the gate?
    #     Progress = the act advanced, or a clue this act requires was newly unlocked. If so,
    #     reset; otherwise (still locked, still missing clues) increment. At the top tier a
    #     narrator nudge fires this turn, openly pointing at one thing left to investigate
    #     (the topic label only — never the locked body).
    still_locked = act_has_gate(content, new_act) and not can_advance(content, state, new_act)
    if new_act == old_act and still_locked:
        req = set(_advance_cond(content, old_act).get("required_fragment_ids") or [])
        made_progress = bool(req & set(newly))
        state["stuck"] = 0 if made_progress else stuck_in + 1
    else:
        state["stuck"] = 0
    # stuck hint: surfaced as a PERSISTENT top-bar string (not a chat beat), so it doesn't
    # spam the conversation. Labels only — the locked bodies are never named.
    hint = ""
    if state["stuck"] >= tun["stuck_spell"] and needed_topics:
        todo = "、".join(f"「{t}」" for t in needed_topics)
        hint = f"还没弄明白的是：{todo}。别干等——主动开口去问，或动手查一查，这一章的结就卡在这上面。"
    elif state["stuck"] >= tun["stuck_push"] and needed_topics:
        hint = f"眼下最该弄清的，是「{needed_topics[0]}」。不妨直接追问，或留意周围相关的破绽。"

    # 5. act transition: a divider, then a narration that actually carries the plot into
    #    the new act (what's changed, the new situation, the new goal) — not just a title.
    if new_act > old_act:
        nxt = current_act(content, new_act) or {}
        moments.append({"kind": "act", "index": new_act, "title": nxt.get("title", "")})
        nc = choice_for_act(content, state, new_act)
        if nc:
            state["pending_choice"] = nc
        yield emit({"type": "description", "speaker_name": None,
                    "text": f"—— 第{new_act}幕 · {nxt.get('title', '')} ——"})
        for b in build_act_transition(content, state, old_act, new_act, persona, llm):
            yield emit(b)

    # 5b. announce any places that JUST became reachable this turn (so a new exit never just
    #     silently shows up — the player is told they've learned of a new place to go).
    locs_after = [l for l in _locations(content) if location_available(content, state, l)]
    new_places = [l.get("name") for l in locs_after
                  if l.get("id") not in locs_before and l.get("id") != state.get("location_id") and l.get("name")]
    if new_places:
        where = "、".join(f"「{n}」" for n in new_places)
        yield emit({"type": "description", "speaker_name": None,
                    "text": f"（你打听到城寨里还有去处：{where}——现在可以过去看看了。）"})

    # 5c. ⏳ time flows: turns spend the current 时段; enough of them — or the scene
    #     explicitly skipping time (睡到天亮/等到入夜) — roll it over. Characters keep
    #     their 作息: the roster the player sees next reflects the new hour. A pure
    #     look-around costs no time. Sleeping past an authored deadline ends the story.
    deadline_blown = False
    if tun["turns_per_slot"] > 0 and not is_think:
        clk = dict(state.get("clock") or {})
        clk.setdefault("day", 1); clk.setdefault("slot", 0); clk.setdefault("turns_in_slot", 0)
        day_before = int(clk["day"])
        skip = "" if time_skip in ("无", "没有", "none") else time_skip
        if skip:
            steps = (len(SLOTS) - int(clk["slot"])) if ("次日" in skip or "天亮" in skip) else 1
            clk["turns_in_slot"] = 0
        else:
            clk["turns_in_slot"] = int(clk["turns_in_slot"]) + 1
            steps = 1 if clk["turns_in_slot"] >= tun["turns_per_slot"] else 0
            if steps:
                clk["turns_in_slot"] = 0
        for _ in range(steps):
            clk["slot"] = int(clk["slot"]) + 1
            if clk["slot"] >= len(SLOTS):
                clk["slot"], clk["day"] = 0, int(clk["day"]) + 1
        state["clock"] = clk
        cv = clock_view(content, state)
        if steps and cv:
            yield emit({"type": "description", "speaker_name": None,
                        "text": _SLOT_NARR[cv["slot"]].format(day=cv["day"])})
            yield ("clock", cv)
        # authored deadline: crossing INTO the day warns loudly; letting it pass ends it
        dl = (cv or {}).get("deadline")
        if dl and dl["days_left"] == 0 and int(clk["day"]) > day_before:
            yield emit({"type": "description", "speaker_name": None,
                        "text": f"（已经是第{clk['day']}天——「{dl['text']}」，就在今天。）"})
            moments.append({"kind": "deadline", "text": dl["text"]})
        elif dl and dl["days_left"] < 0 and not state.get("ended"):
            deadline_blown = True
        # 🤝 爽约: time rolled past a promise the player never showed for. It stings —
        # and the stood-up character will bring it up next time they meet (once).
        now2 = _time_index(state)
        for pr in (state.get("promises") or []):
            if pr.get("status") == "open" and _promise_index(pr) < now2:
                pr["status"] = "missed"
                mc = pr.get("char_id")
                old_sc = (state.get("rel") or {}).get(mc) or relationships.new_scores()
                state.setdefault("rel", {})[mc] = relationships.apply_deltas(
                    old_sc, -tun["promise_break_cost"],
                    -tun["promise_break_cost"] if pr.get("romantic") else 0, tun)
                moments.append({"kind": "promise", "status": "missed",
                                "name": pr.get("char_name"), "what": pr.get("what")})
                rel_log(state, mc, old_act, "promise",
                        f"你爽约了——{pr.get('what','')}。")
                yield emit({"type": "description", "speaker_name": None,
                            "text": f"（你猛然想起——和{pr.get('char_name','')}约好的"
                                    f"（{pr.get('what','')}），已经过了时辰。）"})

    # 5d. people come and go with the hour and the act — never silently. Anyone the
    #     roster diff shows arriving gets a concrete line (looks + role); anyone leaving
    #     gets a farewell that says where they've gone when the作息 knows. The cast bar
    #     never just mutates behind the player's back.
    here_now = scene_characters(content, state)
    here_after = {c.get("id") for c in here_now if c.get("id")}
    dead_now = _dead_ids(state)
    for c in here_now:
        if c.get("id") in (here_after - here_before) and c.get("id") != pcid \
                and c.get("id") not in emergent_ids:
            yield emit(entrance_beat(content, state, c))
    farewell_budget = 2  # spoken goodbyes per turn; any further departures narrate only
    for cg in _characters(content):
        if cg.get("id") in (here_before - here_after) and cg.get("id") != pcid \
                and cg.get("id") not in dead_now:
            if farewell_budget > 0:
                farewell_budget -= 1
                for b in farewell_beats(content, state, cg, llm):
                    yield emit(b)
            else:
                yield emit(exit_beat(content, state, cg))

    # 5e. 📱 the world texts back: absent characters with a live reason (a promise whose
    #     hour is next / just stood up / a lover just parted from) reach out. Capped.
    if not observer and not is_think:
        for ev in phone_deliveries(content, state, here_after, llm):
            yield ("phone", ev)
            moments.append({"kind": "phone", "name": ev["name"], "device": ev["device"]})

    # 6. ending check. Authored endings are MILESTONES (true/normal/bad) — reaching one
    #    shows its narration but the open world keeps going, so the player can explore on
    #    and even upgrade to a higher-tier ending later. Only a fatal action (death) is
    #    terminal and locks the run. Each milestone announces once (tracked by id).
    if pressure_blown and pcfg:
        authored = _ending_by_id(content, pcfg.get("ending_id")) or {}
        model_ending = None
        candidate = {"id": authored.get("id") or "pressure",
                     "kind": authored.get("kind", "bad"),
                     "title": authored.get("title") or f"{pcfg.get('name','压力')}到达顶点",
                     "text": authored.get("text") or "",
                     "terminal": True}
    elif deadline_blown:
        ccfg = clock_cfg(content)
        authored = _ending_by_id(content, ccfg.get("deadline_ending_id")) or {}
        model_ending = None
        candidate = {"id": authored.get("id") or "deadline",
                     "kind": authored.get("kind", "bad"),
                     "title": authored.get("title")
                     or f"{(ccfg.get('deadline_text') or '大限').strip()}——为时已晚",
                     "text": authored.get("text") or "",
                     "terminal": True}
    else:
        candidate = evaluate_ending(content, state, model_ending)
    fired = None
    if candidate:
        achieved = set(state.get("achieved_endings") or [])
        eid = candidate.get("id")
        terminal = bool(candidate.get("terminal"))
        if terminal or eid not in achieved:
            fired = candidate
            kind = candidate.get("kind", "normal")
            if eid:
                achieved.add(eid)
            state["achieved_endings"] = sorted(x for x in achieved if x)
            state["ending"] = candidate  # last reached, for replay display
            if terminal:
                state["ended"] = True
            head = {
                "death": "—— 你死了 ——",
                "bad": "—— 坏结局 ——",
                "true": "—— 达成结局 · 真结局 ——",
                "normal": "—— 达成结局 ——",
            }.get(kind, "—— 达成结局 ——")
            title = candidate.get("title") or ""
            moments.append({"kind": "ending", "ending_kind": kind, "title": title,
                            "terminal": terminal})
            yield emit({"type": "description", "speaker_name": None,
                        "text": f"{head}  {title}".strip()})
            if candidate.get("text"):
                yield emit({"type": "description", "speaker_name": None, "text": candidate["text"]})
            if not terminal:
                yield emit({"type": "description", "speaker_name": None,
                            "text": "（你已抵达一种结局，但故事并未就此打住——你仍可以留在这个世界继续探索。）"})

    # 6b. roll older turns into the long-horizon digest (every ~MEMORY_BATCH turns). Done
    #     here — after the reply beats have already streamed — so it never delays what the
    #     player sees; the refreshed digest takes effect on the next turn.
    if beat_log is not None:
        # per-character: each responder folds THEIR OWN witnessed history into THEIR digest
        # (isolation holds long-term). Only present responders this turn need updating.
        for cid, ch in responder_hist.items():
            _update_memory_for(state, cid, ch, llm)
    else:
        _update_memory(state, history, llm)  # legacy/global (tests, opening)

    # 7. immersive scene (background / mood / sfx) from this turn's text
    scene = scene_mod.classify_scene(
        " ".join(b.get("text", "") for b in all_beats), default_bg=story_default_bg(content)
    )
    state["scene"] = scene
    state["goal"] = current_goal(content, state["act"])  # small objective for the current act
    progress = act_progress(content, state, state["act"])  # clue checklist for the (new) act
    location = location_view(content, state)  # current place w/ exits filtered to unlocked ones

    # a character asked to lead the player somewhere → surface a CONFIRM request (the player
    # must accept before moving). Only honor a real, connected, UNLOCKED destination; ignore
    # anything off-map, not reachable, or not yet discovered.
    move_request = None
    if primary_invite and not observer:
        dest = resolve_location(content, primary_invite)
        cur_id = (location or {}).get("id")
        exits = (location or {}).get("exits") or []
        if dest and dest.get("id") and dest.get("id") != cur_id \
                and location_available(content, state, dest) \
                and (not exits or dest.get("name") in exits or dest.get("id") in exits):
            move_request = {"to": dest["id"], "to_name": dest.get("name"),
                            "by_id": primary_id, "by_name": primary_name_for_invite}
        elif not dest and primary_invite.strip():
            # a place that ISN'T on the authored map — an emergent destination. Offer to
            # GENERATE it on accept (still gated behind the player's confirmation).
            move_request = {"to": None, "to_name": primary_invite.strip(), "generate": True,
                            "by_id": primary_id, "by_name": primary_name_for_invite}

    # suggestions steer toward what's close to unlocking for the primary speaker
    sugg_context = gating.build_context(primary_id, frags, state, newly_ids=newly) if primary else {}
    # context-aware "what could I do next" hints: ask the model to ground 3 hints in what JUST
    # happened + the current situation; fall back to the deterministic template if it can't.
    suggestions = []
    if not (fired and fired.get("terminal")):
        suggestions = _smart_suggestions(
            llm, all_beats, player_input, primary, content, state, location, needed_topics, observer
        ) or build_suggestions(sugg_context)

    yield ("final", {
        "state": state,
        "newly_unlocked": newly,
        # only suppress suggestions on a terminal (death) ending; milestones keep playing
        "suggestions": suggestions,
        "scene": scene,
        "ending": fired,
        # who's addressable now (a new act may have brought someone onstage); in character
        # mode the embodied character is not in the list (you don't address yourself)
        "cast": cast_for(content, state["act"], exclude_id=pcid if mode == "character" else None,
                         state=state),
        "here": scene_cast(content, state, exclude_id=pcid if mode == "character" else None),
        "following": list(state.get("following") or []),
        "goal": state["goal"],
        "progress": progress,  # {items:[{label,done}], done, total} — the clue checklist
        "hint": hint,          # persistent stuck-hint for the top bar ("" = not stuck / hide)
        "moments": moments,    # threshold moments this turn (UI celebration banners)
        "dice": dice,          # 🎲 this turn's fate roll (already streamed as its own event)
        "content_mutated": content_mutated,  # 👋 run grew a new character → persist pinned copy
        "pressure_view": ({"name": pcfg.get("name"), "value": int(state.get("pressure", 0))}
                          if pcfg else None),
        "clock_view": clock_view(content, state),  # ⏳ {day,slot,label,deadline?} or None
        "promises": promises_view(content, state),  # 🤝 open appointments, soonest first
        "phone_unread": phone_threads_view(content, state)["unread"],  # 📱 badge count

        "pending_choice": state.get("pending_choice"),  # unanswered key-moment decision
        "rel_deltas": rel_deltas,  # per-char ♥ movement this turn (UI floating chips)
        "location": location,  # {id,name,detail,exits} the player's current place (or None)
        "move_request": move_request,  # {to,to_name,by_id,by_name} a char wants to lead you there (confirm)
        "relations": relations_summary(content, state),  # {cid:{mode,mode_name,...}} toward player
    })


def scene_cast(content: dict[str, Any], state: dict[str, Any],
               exclude_id: str | None = None) -> list[dict[str, Any]]:
    """The characters in the player's CURRENT scene (light dicts for the UI), each flagged
    with whether they are currently following the player. This is "who is in the room with
    you right now" — drives the on-screen roster + follow buttons."""
    following = set(state.get("following") or [])
    rel_all = state.get("rel") or {}
    tun = tuning_for(content)
    out = []
    for c in scene_characters(content, state):
        if c.get("id") == exclude_id:
            continue
        scores = rel_all.get(c.get("id")) or relationships.new_scores()
        out.append({"id": c.get("id"), "name": c.get("name"),
                    "is_lead": c.get("is_lead", False), "avatar_url": c.get("avatar_url"),
                    "following": c.get("id") in following,
                    "can_follow": relationships.can_follow(c, scores, tun)})  # 好感够不够请动
    return out


def relations_summary(content: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    """Each in-scene character's CURRENT relationship mode toward the player (for the UI /
    API). Empty in god mode (no player participant). Player's own character excluded."""
    if (state.get("mode") or "character") == "god":
        return {}
    pcid = state.get("player_character_id")
    rel_all = state.get("rel") or {}
    tun = tuning_for(content)
    out: dict[str, Any] = {}
    for c in scene_characters(content, state):
        cid = c.get("id")
        if not cid or cid == pcid:
            continue
        out[cid] = relationships.state_for(c, rel_all.get(cid) or relationships.new_scores(), tun)
    return out


def story_default_bg(content: dict[str, Any]) -> str:
    """A sensible fallback background derived from the story's worldbuilding."""
    world = (content.get("story") or {}).get("world_long") or ""
    return scene_mod.classify_scene(world)["bg"]


def opening_scene(content: dict[str, Any]) -> dict[str, Any]:
    return scene_mod.classify_scene(opening_narration(content), default_bg=story_default_bg(content))
