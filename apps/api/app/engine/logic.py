"""Logic-rigor toolkit — three story-AGNOSTIC layers that keep the AI (and the content it
runs on) internally consistent. This is FRAMEWORK: it must never encode any specific 剧本's
characters, props, or lines. It reasons only about the abstract shape of a story.

Layer 2 — lint_story():   author-time. Scans a story's structure for logical holes that
                          would strand the player (unreachable gates, secrets with no
                          fragments, dangling refs, unreachable places, bad relation modes).
Layer 1 — verify_turn():  play-time. After a turn is generated, a deterministic, zero-LLM
                          check that the text didn't (a) drag an absent character into the
                          scene, (b) leak a still-locked secret, or (c) whisk the player to
                          a place they haven't unlocked. Pairs with scrub_beats() to repair.
Layer 3 — the reasoning scaffold lives in qwen._render_tool (a private `inner_read` field
                          the model fills before speaking); this module holds the shared
                          text helpers it and the verifier both use.

Pure (no I/O, no DB) so it can be exhaustively unit-tested — the same discipline as gating.py.
"""

from __future__ import annotations

import re
from typing import Any

from . import gating, relationships

Issue = dict[str, Any]  # {severity: "error"|"warn", code, where, msg}


# ── shared accessors (tiny; duplicated from runtime to avoid an import cycle) ──────────────
def _story(content: dict[str, Any]) -> dict[str, Any]:
    return content.get("story") or {}


def _chars(content: dict[str, Any]) -> list[dict[str, Any]]:
    return _story(content).get("characters") or []


def _acts(content: dict[str, Any]) -> list[dict[str, Any]]:
    return _story(content).get("acts") or []


def _locations(content: dict[str, Any]) -> list[dict[str, Any]]:
    return _story(content).get("locations") or []


def _endings(content: dict[str, Any]) -> list[dict[str, Any]]:
    return _story(content).get("endings") or []


def _secrets(content: dict[str, Any]) -> list[dict[str, Any]]:
    return content.get("secrets") or []


# ═══════════════════════════════════════════════════════════════════════════════════════
# Layer 2 — STORY LINTER (author-time structural consistency)
# ═══════════════════════════════════════════════════════════════════════════════════════
def lint_story(content: dict[str, Any]) -> list[Issue]:
    """Return every structural logic problem in a story. `error` = the run can dead-end or
    a reference is dangling; `warn` = a smell that probably isn't intended. Empty list = clean."""
    issues: list[Issue] = []

    def err(code: str, where: str, msg: str) -> None:
        issues.append({"severity": "error", "code": code, "where": where, "msg": msg})

    def warn(code: str, where: str, msg: str) -> None:
        issues.append({"severity": "warn", "code": code, "where": where, "msg": msg})

    chars = _chars(content)
    acts = _acts(content)
    locs = _locations(content)
    secrets = _secrets(content)
    frags = gating.iter_fragments(content)

    char_ids = {c.get("id") for c in chars if c.get("id")}
    char_names = {c.get("name") for c in chars if c.get("name")}
    loc_ids = {l.get("id") for l in locs if l.get("id")}
    loc_names = {l.get("name") for l in locs if l.get("name")}
    frag_ids = {f.get("id") for f in frags if f.get("id")}
    event_ids = {ev.get("id") for a in acts for ev in (a.get("events") or []) if ev.get("id")}
    frag_by_id = {f["id"]: f for f in frags if f.get("id")}
    max_act = max((int(a.get("index", 0)) for a in acts), default=0)

    # — basic population —
    if not acts:
        err("no_acts", "story", "剧本没有任何幕（acts），无法进行。")
    if not chars:
        err("no_chars", "story", "剧本没有任何角色。")
    if chars and not any(c.get("playable") for c in chars):
        warn("no_playable", "characters",
             "没有任何角色标记 playable —— 引擎会回退到「任选在场角色」，可能让玩家扮演会破坏剧情的角色。")

    # — duplicate ids (would make refs ambiguous) —
    for label, ids in (("character", [c.get("id") for c in chars]),
                       ("location", [l.get("id") for l in locs]),
                       ("fragment", [f.get("id") for f in frags]),
                       ("act", [a.get("index") for a in acts])):
        seen: set = set()
        for i in ids:
            if i in seen:
                err("dup_id", label, f"{label} id 重复：{i}")
            seen.add(i)

    # — acts contiguous 1..N —
    idxs = sorted(int(a.get("index", 0)) for a in acts)
    for want, got in zip(range(1, len(idxs) + 1), idxs):
        if want != got:
            warn("act_gap", "acts", f"幕的 index 不连续：期望 {want}，实际 {got}。")
            break

    # — secrets & fragments —
    for s in secrets:
        sid = s.get("id")
        if not (s.get("fragments") or []):
            warn("empty_secret", f"secret:{sid}", f"秘密「{s.get('title','')}」没有任何 fragment，永远不会揭示。")
        scid = s.get("character_id")
        if scid and scid not in char_ids:
            warn("secret_bad_owner", f"secret:{sid}", f"秘密「{s.get('title','')}」的 character_id={scid} 不是已知角色。")
    for f in frags:
        kb = f.get("known_by_character_ids") or []
        bad = [k for k in kb if k not in char_ids]
        if bad:
            warn("frag_bad_knower", f"frag:{f.get('id')}",
                 f"fragment {f.get('id')} 的 known_by_character_ids 含未知角色：{bad}")
        # a fragment whose unlock needs a trigger event that doesn't exist can never unlock
        for ev in (f.get("unlock") or {}).get("trigger_event_ids") or []:
            if ev not in event_ids:
                err("frag_bad_event", f"frag:{f.get('id')}",
                    f"fragment {f.get('id')} 需要触发事件 {ev}，但没有任何幕定义了这个事件 —— 永远解不开。")

    def _check_frag_refs(ids: list[str], where: str, gate_act: int | None) -> None:
        """Every referenced fragment must exist AND (if this is an act's advance gate) be
        unlockable BEFORE you're required to leave that act."""
        for fid in ids or []:
            if fid not in frag_ids:
                err("dangling_frag", where, f"引用了不存在的 fragment：{fid}")
                continue
            if gate_act is not None:
                fa = int((frag_by_id[fid].get("unlock") or {}).get("act_min") or 0)
                if fa > gate_act:
                    err("gate_deadlock", where,
                        f"第{gate_act}幕要求解锁 {fid} 才能推进，但该 fragment 的 act_min={fa} 只在更晚的幕才可能解锁 —— 卡死。")

    # — act advance gates —
    for a in acts:
        ai = int(a.get("index", 0))
        adv = a.get("advance") or {}
        where = f"act:{ai}"
        _check_frag_refs(adv.get("required_fragment_ids") or [], where, ai)
        for ev in adv.get("required_event_ids") or []:
            if ev not in event_ids:
                err("dangling_event", where, f"推进条件引用了不存在的事件：{ev}")

    # — locations —
    start_id = locs[0].get("id") if locs else None
    for l in locs:
        lid = l.get("id")
        where = f"loc:{lid}"
        for ex in l.get("exits") or []:
            if ex not in loc_ids and ex not in loc_names:
                err("dangling_exit", where, f"出口指向不存在的地点：{ex}")
        frag_ids_all = {f.get("id") for f in frags if f.get("id")}
        event_ids_all = {ev.get("id") for a in acts for ev in (a.get("events") or []) if ev.get("id")}
        for p in (l.get("props") or []):
            pwhere = f"{where}.props[{p.get('name','')}]"
            if p.get("fragment_id") and p["fragment_id"] not in frag_ids_all:
                err("dangling_prop_frag", pwhere, f"物证指向不存在的 fragment：{p['fragment_id']}")
            if p.get("event_id") and p["event_id"] not in event_ids_all:
                err("dangling_prop_event", pwhere, f"物证指向不存在的事件：{p['event_id']}")
        _check_frag_refs((l.get("unlock") or {}).get("required_fragment_ids") or [], where, None)
    # inbound reachability: a non-start location with no exit pointing at it is unreachable
    if locs:
        pointed: set = set()
        for l in locs:
            for ex in l.get("exits") or []:
                dest = next((x for x in locs if x.get("id") == ex or x.get("name") == ex), None)
                if dest:
                    pointed.add(dest.get("id"))
        for l in locs:
            if l.get("id") != start_id and l.get("id") not in pointed:
                warn("unreachable_loc", f"loc:{l.get('id')}",
                     f"地点「{l.get('name','')}」没有任何其它地点的出口通向它 —— 玩家可能永远到不了。")

    # — characters: home / entrance / relation modes —
    for c in chars:
        cid = c.get("id")
        where = f"char:{cid}"
        for e in (c.get("schedule") or []):
            slid = (e.get("location_id") or "").strip()
            if slid and slid not in loc_ids:
                err("bad_schedule", where,
                    f"角色「{c.get('name','')}」的作息表指向不存在的地点：{slid}")
        home = c.get("home_location_id")
        if home and home not in loc_ids:
            err("bad_home", where, f"角色「{c.get('name','')}」的 home_location_id={home} 不是已知地点。")
        af = int(c.get("appears_from_act") or 0)
        if af > max_act:
            warn("never_appears", where,
                 f"角色「{c.get('name','')}」appears_from_act={af} 超过最后一幕({max_act})，永远不会登场。")
        for ref in ([c.get("relation_default")] if c.get("relation_default") else []) + list(c.get("relation_allowed") or []):
            if relationships.resolve(ref) is None:
                warn("bad_relation", where,
                     f"角色「{c.get('name','')}」的关系模式「{ref}」不是已知原型（见 relationships.ARCHETYPES）。")

    # — endings —
    if acts and not _endings(content):
        warn("no_endings", "story", "剧本没有定义任何结局。")
    good = 0
    for e in _endings(content):
        where = f"ending:{e.get('id')}"
        cond = e.get("condition") or {}
        _check_frag_refs(cond.get("required_fragment_ids") or [], where, None)
        if e.get("kind") in ("true", "normal"):
            good += 1
    if _endings(content) and good == 0:
        warn("no_good_ending", "endings", "没有任何 true/normal 结局 —— 玩家无论怎么玩都只能走向坏结局/死亡。")

    for f in frags:
        lid = (f.get("unlock") or {}).get("location_id")
        if lid and lid not in loc_ids:
            err("bad_frag_location", f"fragment[{f.get('id')}]",
                f"解锁条件指向不存在的地点：{lid}")
    return issues


def format_issues(issues: list[Issue]) -> str:
    """Human-readable report for the CLI linter."""
    if not issues:
        return "✓ 逻辑自检通过，没有发现结构性问题。"
    errs = [i for i in issues if i["severity"] == "error"]
    warns = [i for i in issues if i["severity"] == "warn"]
    lines = [f"发现 {len(errs)} 个错误、{len(warns)} 个警告：\n"]
    for i in errs:
        lines.append(f"  ✗ [{i['code']}] {i['where']}: {i['msg']}")
    for i in warns:
        lines.append(f"  ⚠ [{i['code']}] {i['where']}: {i['msg']}")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════════════
# Layer 1 — RUNTIME TURN VERIFIER (deterministic, zero-LLM post-generation guard)
# ═══════════════════════════════════════════════════════════════════════════════════════
# A character who is NOT in the scene must not be shown arriving, standing there, or speaking.
# We only flag a name when a PRESENCE/SPEAK verb sits right after it (subject-of-action), and
# NOT when a reference marker sits right before it — so "十二少倚在门口" trips, "听说十二少很横"
# does not. Story-agnostic: the name list is supplied by the caller from the live scene state.
_PRESENCE_VERBS = ("走进", "走近", "走来", "走过来", "走上前", "进来", "进门", "推门", "推开门",
                   "闯进", "踏进", "跨进", "出现", "现身", "露面", "冒出来", "凑过来", "凑近",
                   "站在", "站起", "坐在", "坐下", "靠在", "倚在", "蹲在", "探出", "走了进来")
_SPEAK_VERBS = ("说道", "说：", "说:", "道：", "道:", "笑道", "冷笑", "喊道", "叫道", "低声",
                "开口", "嘟囔", "插嘴", "接话", "应道", "答道", "问道", "喃喃")
_REF_BEFORE = ("提到", "提起", "说起", "说到", "说过", "讲起", "讲到", "听说", "传闻", "据说",
               "关于", "想起", "想到", "记得", "认识", "找", "问过", "叫", "名叫", "打听",
               "念叨", "口中", "嘴里", "眼中的", "心里")


def _norm(s: str) -> str:
    return re.sub(r"[\s，。、！？…—\-,.!?：:；;\"'「」『』（）()]+", "", s or "")


def _intrudes(text: str, name: str) -> bool:
    """True if `name` is depicted as acting/present in `text` (not merely referenced)."""
    if not name or name not in text:
        return False
    verbs = _PRESENCE_VERBS + _SPEAK_VERBS
    for m in re.finditer(re.escape(name), text):
        after = text[m.end(): m.end() + 6]
        before = text[max(0, m.start() - 6): m.start()]
        if any(v in after for v in verbs) and not any(r in before for r in _REF_BEFORE):
            return True
    return False


def _leaks_secret(speech: str, locked_texts: list[str], min_run: int = 14) -> bool:
    """True if the spoken text reproduces a long verbatim run of any still-locked secret body."""
    hay = _norm(speech)
    if len(hay) < min_run:
        return False
    for body in locked_texts:
        nb = _norm(body)
        for i in range(0, len(nb) - min_run + 1):
            if nb[i: i + min_run] in hay:
                return True
    return False


def verify_turn(beats: list[dict[str, Any]], *, absent_names: list[str],
                locked_location_names: list[str], locked_fragment_texts: list[str],
                present_names: list[str] | None = None) -> dict[str, Any]:
    """Deterministic post-generation check. Returns {hard: [...], soft: [...]}: `hard` issues
    are logic breaks worth regenerating for; `soft` are logged nudges. Never raises."""
    hard: list[str] = []
    soft: list[str] = []
    narration = " ".join(b.get("text", "") for b in beats if b.get("type") == "description")
    speech = " ".join(b.get("text", "") for b in beats if b.get("type") == "dialogue")
    full = narration + " " + speech

    for name in absent_names or []:
        if _intrudes(full, name):
            hard.append(f"把不在场的「{name}」写成在场/发声了")

    if _leaks_secret(speech, locked_fragment_texts or []):
        hard.append("台词里疑似泄露了尚未解锁的秘密")

    for loc in locked_location_names or []:
        if loc and loc in full and re.search(rf"(去|前往|来到|到了|进了|带你(?:去|到)|走向)\s*{re.escape(loc)}", full):
            soft.append(f"疑似把玩家带往尚未解锁的地点「{loc}」")

    return {"hard": hard, "soft": soft}


def scrub_beats(beats: list[dict[str, Any]], absent_names: list[str]) -> list[dict[str, Any]]:
    """Last-resort deterministic repair when a regeneration still intrudes: drop the sentences
    in narration that put an absent character on stage; drop a description that empties out."""
    if not absent_names:
        return beats
    out: list[dict[str, Any]] = []
    for b in beats:
        if b.get("type") != "description":
            out.append(b)
            continue
        kept = [seg for seg in re.split(r"(?<=[。！？…\n])", b.get("text", ""))
                if not any(_intrudes(seg, n) for n in absent_names)]
        text = "".join(kept).strip()
        if text:
            out.append({**b, "text": text})
    return out
