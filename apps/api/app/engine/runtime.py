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

from . import gating
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
MEMORY_WINDOW = 8   # dialogue turns shown verbatim — MUST match qwen.py's history[-8:]
MEMORY_BATCH = 6    # summarize only once this many turns have slid out of the window

# Stuck-hint escalation: consecutive locked-act turns with no new required clue. NUDGE =
# NPCs get noticeably more forthcoming; PUSH = a direct narrator hint pointing at one topic;
# SPELL = the narrator lays out the full remaining checklist + a concrete next step.
STUCK_NUDGE = 1
STUCK_PUSH = 2
STUCK_SPELL = 4


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
    present = present_characters(content, act)
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
    })
    beats = [b for b in directed.get("beats", []) if b.get("type") == "description"]
    return beats or [{"type": "description", "speaker_name": None, "text": opening_narration(content)}]


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
    """PLACEHOLDER: fire a story event when the player's words overlap its keywords."""
    triggered = set(state.get("triggered_event_ids") or [])
    for act in (content.get("story") or {}).get("acts", []) or []:
        for ev in act.get("events", []) or []:
            eid = ev.get("id")
            kws = [w for w in _keywords(ev.get("what_happens", "")) if len(w) >= 2]
            if eid and eid not in triggered and _contains_any(player_input, kws):
                triggered.add(eid)
    state["triggered_event_ids"] = sorted(triggered)


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
):
    """Advance one turn as a GENERATOR. Yields ('beat', beat) for each beat the moment
    it's computed (so responders stream out one by one), then a final ('final', result)
    carrying state/scene/suggestions/ending/cast/goal. Pure w.r.t. DB."""
    llm = llm or get_llm()
    state = {**default_state(), **(state or {})}
    old_act = int(state.get("act", 1))
    all_beats: list[dict[str, Any]] = []  # accumulated for scene classification

    # 1. probing → asks counters (per secret); also note which characters are probed
    asks = dict(state.get("asks") or {})
    probed_secret_ids = _detect_asks(content, player_input)
    for sid in probed_secret_ids:
        asks[sid] = asks.get(sid, 0) + 1
    state["asks"] = asks
    sec_char = _secret_char_map(content)
    probed_char_ids = [sec_char.get(sid) for sid in probed_secret_ids if sec_char.get(sid)]

    _apply_event_triggers(content, state, player_input)

    # 2. gate on the CURRENT state (asks updated; affinity not yet changed this turn).
    #    asks-driven reveals surface THIS turn so the director can voice them; affinity-
    #    driven ones land NEXT turn (the warmth rose now, the confession follows) — that
    #    one-turn lag is intentional and reads naturally.
    frags = gating.iter_fragments(content)
    newly = gating.evaluate_unlocks(state, frags)
    state["unlocked_fragment_ids"] = sorted(
        set(state.get("unlocked_fragment_ids") or []) | set(newly)
    )

    # responder selection. With an explicit @target → just that character. With NO target
    # (and not an inner thought) the player is addressing the WHOLE room — every present
    # character may answer, though some can choose to stay silent. Otherwise the router
    # picks the single most-relevant speaker.
    mode = state.get("mode") or "character"
    pcid = state.get("player_character_id")  # the character the player embodies (character mode)

    # only characters present THIS act take part. In CHARACTER mode the player IS pcid, so
    # that character is not an NPC responder. In GOD mode the player embodies no one.
    all_chars = [c for c in present_characters(content, old_act) if c.get("id") != pcid]

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
    stuck_level = 1 if stuck_in >= STUCK_NUDGE else 0
    stuck_level = 2 if stuck_in >= STUCK_PUSH else stuck_level

    # 3. the model is the DIRECTOR for each responder: per-speaker gated context (so a
    #    character can only ever voice what IT is allowed to know — no cross-leak). Each
    #    responder's beats are YIELDED the moment they're computed → they stream out.
    next_act = current_act(content, old_act + 1)
    place = _physical_place(content, state)   # concrete "you are here" anchor (empty if none)
    affinity_delta = 0
    advance = False
    model_ending = None
    model_move = None  # the primary speaker may report the player moved to another place

    def emit(b: dict[str, Any]):
        all_beats.append(b)
        return ("beat", b)

    for idx, sp in enumerate(responders):
        sp_id = sp.get("id")
        sp_name = sp.get("name") or "角色"
        ctx = gating.build_context(sp_id, frags, state, newly_ids=newly)
        others = [c.get("name") for c in all_chars if c.get("id") != sp_id and c.get("name")]
        is_primary = idx == 0
        prompt = {
            "speaker_name": sp_name,
            "speaker_persona": sp.get("persona_text", ""),
            "persona": persona_for_prompt,
            "player_input": player_input,
            "channel": channel,
            "context": ctx,
            "history": history or [],
            "memory": state.get("memory", ""),   # rolling digest of earlier acts
            "world_facts": (content.get("story") or {}).get("world_facts") or "",
            "roster": _physical_roster(content, state, persona),  # deterministic headcount
            "place": place,                       # concrete current-location anchor (if authored)
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
        }
        directed = llm.generate(prompt)
        d_beats = directed.get("beats", [])
        if not is_primary:
            # members contribute dialogue only (one shared narration from the primary)
            d_beats = [b for b in d_beats if b.get("type") == "dialogue"]
        for b in d_beats:
            yield emit(b)
        affinity_delta += int(directed.get("affinity_delta", 0) or 0)
        if directed.get("advance_act"):
            advance = True
        if is_primary:
            model_ending = directed.get("ending")  # only the addressed scene can end the run
            model_move = directed.get("location")   # and may report a place change

    # think = OBSERVE/EXAMINE. No target → look at the surroundings (where am I, what's
    # going on). With a target → examine that person: a brief intro + their CURRENT state
    # (expression / posture / appearance / mood). Narration only; no dialogue, no affinity;
    # secrets are never passed in, so observation can't leak locked truths.
    if is_think:
        observe_target = _char_by_id(content, target_character_id) if target_character_id else None
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
            "history": history or [],
            "memory": state.get("memory", ""),   # rolling digest of earlier acts
            "cast": [c.get("name") for c in all_chars if c.get("name")],
        })
        obs = [b for b in directed.get("beats", []) if b.get("type") == "description"]
        if not obs:
            obs = [{"type": "description", "speaker_name": None,
                    "text": ((directed.get("beats") or [{}])[0].get("text", ""))}]
        for b in obs:
            yield emit(b)
        affinity_delta = 0

    affinity_delta = 0 if is_think else max(-3, min(8, affinity_delta))

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
        backstop = 1 + state["affinity"] // 12  # safety net so a soft run never fully stalls
        target = max(old_act + (1 if advance else 0), backstop)
        new_act = min(max_act, target) if max_act else target
    state["act"] = new_act

    # 4a. apply a place change if the director reported the player moved (and we recognize
    #     the destination — an unknown place is ignored so the model can't invent rooms).
    if model_move:
        dest = resolve_location(content, model_move)
        if dest and dest.get("id"):
            state["location_id"] = dest["id"]

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
    if state["stuck"] >= STUCK_SPELL and needed_topics:
        # really stuck — stop being coy: lay out everything still left to uncover, plus a
        # concrete next move. Labels only; the locked bodies are never named.
        todo = "、".join(f"「{t}」" for t in needed_topics)
        yield emit({"type": "description", "speaker_name": None,
                    "text": f"（你定了定神，把已知的疑点在心里过了一遍。眼下还没弄明白的是：{todo}。"
                            f"与其干等，不如主动开口去问、或者动手查一查——这一章的结，就卡在这上面。）"})
    elif state["stuck"] >= STUCK_PUSH and needed_topics:
        yield emit({"type": "description", "speaker_name": None,
                    "text": f"（你停下来，理了理思路——眼下最该弄清的，是「{needed_topics[0]}」。"
                            f"不妨直接去追问，或者留意周围有没有相关的破绽。）"})

    # 5. act-transition divider (after the replies, transitioning into the new act)
    if new_act > old_act:
        nxt = current_act(content, new_act) or {}
        yield emit({"type": "description", "speaker_name": None,
                    "text": f"—— 第{new_act}幕 · {nxt.get('title', '')} ——"})

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
            yield emit({"type": "description", "speaker_name": None,
                        "text": f"{head}  {title}".strip()})
            if candidate.get("text"):
                yield emit({"type": "description", "speaker_name": None, "text": candidate["text"]})
            if not terminal:
                yield emit({"type": "description", "speaker_name": None,
                            "text": "（你已抵达一种结局，但故事并未就此打住——你仍可以留在这个世界继续探索。）"})

    # 6b. roll older turns into the long-horizon digest (every ~MEMORY_BATCH turns). Done
    #     here — after the reply beats have already streamed — so it never delays what the
    #     player sees; the refreshed digest takes effect on the next turn. history is the
    #     PRIOR conversation (this turn's beats aren't in it yet), matching qwen's window.
    _update_memory(state, history, llm)

    # 7. immersive scene (background / mood / sfx) from this turn's text
    scene = scene_mod.classify_scene(
        " ".join(b.get("text", "") for b in all_beats), default_bg=story_default_bg(content)
    )
    state["scene"] = scene
    state["goal"] = current_goal(content, state["act"])  # small objective for the current act
    progress = act_progress(content, state, state["act"])  # clue checklist for the (new) act
    location = current_location(content, state)  # where the player is now (None if no map)

    # suggestions steer toward what's close to unlocking for the primary speaker
    sugg_context = gating.build_context(primary_id, frags, state, newly_ids=newly) if primary else {}

    yield ("final", {
        "state": state,
        "newly_unlocked": newly,
        # only suppress suggestions on a terminal (death) ending; milestones keep playing
        "suggestions": [] if (fired and fired.get("terminal")) else build_suggestions(sugg_context),
        "scene": scene,
        "ending": fired,
        # who's addressable now (a new act may have brought someone onstage); in character
        # mode the embodied character is not in the list (you don't address yourself)
        "cast": cast_for(content, state["act"], exclude_id=pcid if mode == "character" else None),
        "goal": state["goal"],
        "progress": progress,  # {items:[{label,done}], done, total} — the clue checklist
        "location": location,  # {id,name,detail,exits} the player's current place (or None)
    })


def story_default_bg(content: dict[str, Any]) -> str:
    """A sensible fallback background derived from the story's worldbuilding."""
    world = (content.get("story") or {}).get("world_long") or ""
    return scene_mod.classify_scene(world)["bg"]


def opening_scene(content: dict[str, Any]) -> dict[str, Any]:
    return scene_mod.classify_scene(opening_narration(content), default_bg=story_default_bg(content))
