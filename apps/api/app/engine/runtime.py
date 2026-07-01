"""Per-turn orchestration: glue between the player's input, the gate, and the LLM.

    detect probing → mutate run state → evaluate unlocks → assemble gated context
    → LLM → beats

The state-mutation heuristics (affinity nudge, act progression, event triggers)
are deliberately simple PLACEHOLDERS. In M3 these become model-driven (the LLM
proposes affinity deltas / flag changes as structured side-effects). The gate
(gating.py) and this pipeline's shape are the parts meant to be permanent.
"""

from __future__ import annotations

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


def present_characters(content: dict[str, Any], act: int) -> list[dict[str, Any]]:
    return [c for c in _characters(content) if _is_present(c, act)]


def _is_here(c: dict[str, Any], state: dict[str, Any], cur_loc_id: str | None) -> bool:
    """Is this character in the player's CURRENT scene? A character pinned to a home
    location is only here when the player is AT that location, OR when the character is
    currently following the player. A character with no home location is ubiquitous
    (present everywhere in their act — the backward-compatible old behavior for stories
    that don't pin characters to places)."""
    home = c.get("home_location_id")
    if not home:
        return True
    cid = c.get("id")
    if cid and cid in (state.get("following") or []):
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
    return [c for c in present_characters(content, act) if _is_here(c, state, cur_id)]


def playable_roles(content: dict[str, Any]) -> list[dict[str, Any]]:
    """Characters the player may EMBODY (character mode). Those explicitly flagged
    `playable` win; if a story flags none (legacy), fall back to every character present
    from the opening act — so old stories keep letting you pick any role."""
    chars = _characters(content)
    flagged = [c for c in chars if c.get("playable")]
    if flagged:
        return flagged
    return [c for c in chars if _is_present(c, 1)]


def cast_for(content: dict[str, Any], act: int, exclude_id: str | None = None) -> list[dict[str, Any]]:
    """The addressable cast at this act (offstage/not-yet-arrived excluded). In character
    mode `exclude_id` drops the character the player is embodying (you don't talk to self)."""
    return [
        {"id": c.get("id"), "name": c.get("name"),
         "is_lead": c.get("is_lead", False), "avatar_url": c.get("avatar_url")}
        for c in present_characters(content, act)
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
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for fid in adv.get("required_fragment_ids") or []:
        label = ftitles.get(fid, "线索")
        if label in seen:
            continue
        seen.add(label)
        items.append({"label": label, "done": fid in unlocked})
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
    return beats or [{"type": "description", "speaker_name": None, "text": opening_narration(content)}]


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
        else:
            final = payload
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

    # 2. gate on the CURRENT state (asks updated; affinity not yet changed this turn).
    #    asks-driven reveals surface THIS turn so the director can voice them; affinity-
    #    driven ones land NEXT turn (the warmth rose now, the confession follows) — that
    #    one-turn lag is intentional and reads naturally.
    frags = gating.iter_fragments(content)
    newly = gating.evaluate_unlocks(state, frags)
    state["unlocked_fragment_ids"] = sorted(
        set(state.get("unlocked_fragment_ids") or []) | set(newly)
    )

    # judgment candidates for the primary director call (titles/labels only, never bodies)
    probe_cands = _probe_candidates(content, state)
    event_cands = _event_candidates(content, state, old_act)

    # THRESHOLD MOMENTS (阈值时刻演出): structured events the UI celebrates — a truth
    # clicking into place, a relationship tier-up, a new act, an ending milestone.
    moments: list[dict[str, Any]] = []
    rel_deltas: dict[str, dict[str, int]] = {}   # per-char ♥ movement this turn (UI float)
    for t in _titles_for_fragments(content, newly):
        moments.append({"kind": "unlock", "title": t})

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

    if mode == "god":
        # Invisible-observer mode: the player doesn't speak in-scene; the present cast
        # interact WITH EACH OTHER (the 旁观/CP mode). The player's input is a director
        # cue. Everyone present takes part; an explicit target spotlights one character.
        observer = True
        if target_character_id:
            spot = _char_by_id(content, target_character_id)
            responders = [spot] + [c for c in all_chars if c.get("id") != target_character_id] if spot else list(all_chars)
        else:
            responders = list(all_chars)
        primary = responders[0] if responders else None
        primary_id = primary.get("id") if primary else None
        broadcast = len(responders) > 1
    else:
        observer = False
        primary = pick_responder(content, state, player_input, target_character_id, probed_char_ids, all_chars)
        primary_id = primary.get("id") if primary else None
        broadcast = bool(primary) and channel != "think" and not target_character_id and len(all_chars) > 1
        if primary is None or channel == "think":
            # think = observe/examine (handled separately below), no NPC responds
            responders = []
        elif broadcast:
            # primary first (it carries the narration), then the rest of the present cast
            responders = [primary] + [c for c in all_chars if c.get("id") != primary_id]
        else:
            responders = [primary]
    if channel != "think":
        state["last_speaker_id"] = primary_id

    # In character mode the player speaks AS their chosen character — give the model that
    # identity instead of the generic persona name, so NPCs address the right person.
    player_char = _char_by_id(content, pcid) if (mode == "character" and pcid) else None
    persona_for_prompt = persona
    if player_char:
        persona_for_prompt = {**(persona or {}), "name": player_char.get("name"),
                              "background": player_char.get("background") or (persona or {}).get("background", "")}

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
    tun = tuning_for(content)
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
            # what the others have ALREADY said this turn → react, don't echo
            "said_this_turn": list(said_this_turn),
        }
        directed = llm.generate(prompt)
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

    affinity_delta = 0 if is_think else max(tun["affinity_clamp_min"],
                                            min(tun["affinity_clamp_max"], affinity_delta))

    # 4. apply affinity, then decide progression. HARD GATE: if this act authored advance
    #    conditions, it advances ONLY when can_advance() is satisfied (program-checked) —
    #    the model's 推进 and affinity backstop can no longer talk past it. Acts with NO
    #    authored conditions fall back to the old soft advance (model 推进 / affinity).
    state["affinity"] = max(0, int(state.get("affinity", 0)) + affinity_delta)
    max_act = _max_act_index(content)
    if act_has_gate(content, old_act):
        new_act = (min(max_act, old_act + 1)
                   if (max_act and can_advance(content, state, old_act)) else old_act)
    else:
        backstop = 1 + state["affinity"] // tun["act_backstop_div"]  # soft-run stall safety net
        target = max(old_act + (1 if advance else 0), backstop)
        new_act = min(max_act, target) if max_act else target
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

    # 6. ending check. Authored endings are MILESTONES (true/normal/bad) — reaching one
    #    shows its narration but the open world keeps going, so the player can explore on
    #    and even upgrade to a higher-tier ending later. Only a fatal action (death) is
    #    terminal and locks the run. Each milestone announces once (tracked by id).
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
        "cast": cast_for(content, state["act"], exclude_id=pcid if mode == "character" else None),
        "here": scene_cast(content, state, exclude_id=pcid if mode == "character" else None),
        "following": list(state.get("following") or []),
        "goal": state["goal"],
        "progress": progress,  # {items:[{label,done}], done, total} — the clue checklist
        "hint": hint,          # persistent stuck-hint for the top bar ("" = not stuck / hide)
        "moments": moments,    # threshold moments this turn (UI celebration banners)
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
