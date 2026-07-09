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


# ⏳ must mirror runtime.SLOTS (duplicated, same reason as the accessors above)
_SLOTS = ("晨", "午", "夜")


def _clock_on(content: dict[str, Any]) -> bool:
    """Does this story run the clock? Mirrors runtime.tuning_for's turns_per_slot logic
    (default must match runtime.DEFAULT_TUNING["turns_per_slot"])."""
    try:
        return int((_story(content).get("tuning") or {}).get("turns_per_slot", 6)) > 0
    except (TypeError, ValueError):
        return True


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
        # 🏖 a pure sandbox conjures its cast from the player's worldview at run start —
        # an empty authored cast is the designed path there, not a structural hole
        sb = (content.get("story") or {}).get("sandbox")
        if isinstance(sb, dict) and sb.get("enabled"):
            warn("no_chars", "story", "沙盒无 authored 角色：开局将从世界观召唤卡司（设计如此）。")
        else:
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
            e_slots = [s for s in (e.get("slots") or []) if s]
            for sl in e_slots:
                if sl not in _SLOTS:
                    err("bad_slot", where,
                        f"角色「{c.get('name','')}」的作息表用了未知时段「{sl}」（可用：{'、'.join(_SLOTS)}）")
            if e_slots and not _clock_on(content):
                warn("slots_no_clock", where,
                     f"角色「{c.get('name','')}」的作息表按时段排班，但本剧关闭了时钟"
                     "(tuning.turns_per_slot=0) —— 该角色将永远停在「晨」的班上。")
        home = c.get("home_location_id")
        if home and home not in loc_ids:
            err("bad_home", where, f"角色「{c.get('name','')}」的 home_location_id={home} 不是已知地点。")
        char_ids_all = {x.get("id") for x in chars if x.get("id")}
        for t in (c.get("ties") or []):
            if t.get("char_id") not in char_ids_all:
                err("bad_tie", where,
                    f"角色「{c.get('name','')}」的 ties 指向不存在的角色：{t.get('char_id')}")
            elif t.get("char_id") == cid:
                warn("self_tie", where, f"角色「{c.get('name','')}」和自己有 tie——会被忽略。")
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

    # — ⏳ clock / deadline —
    ck = _story(content).get("clock") or {}
    if ck:
        try:
            dd = int(ck.get("deadline_day") or 0)
        except (TypeError, ValueError):
            dd = 0
        ending_ids = {e.get("id") for e in _endings(content) if e.get("id")}
        eid = ck.get("deadline_ending_id")
        if eid and eid not in ending_ids:
            err("bad_deadline_ending", "clock", f"deadline_ending_id={eid} 不是已知结局。")
        if dd and not _clock_on(content):
            warn("deadline_no_clock", "clock",
                 "设了 deadline_day 但时钟已关闭 (tuning.turns_per_slot=0) —— 大限永远不会到。")

    # — 🏖 sandbox —
    if (_story(content).get("sandbox") or {}).get("enabled"):
        if _endings(content):
            warn("sandbox_endings", "sandbox",
                 "沙盒永不结束：authored endings 不会触发（玩家死亡是状态，不是结局）。")
        if _story(content).get("verdict"):
            warn("sandbox_verdict", "sandbox", "沙盒不跑指认结案，verdict 配置会被闲置。")
        if (_story(content).get("clock") or {}).get("deadline_day"):
            warn("sandbox_deadline", "sandbox",
                 "沙盒与现实同步、永不结束，deadline_day 不会生效。")
        if len(acts) > 1:
            warn("sandbox_acts", "sandbox", "沙盒只有无尽的一幕，多余的幕不会被推进。")

    # — ⏳ act time anchors —
    try:
        _ddl = int((_story(content).get("clock") or {}).get("deadline_day") or 0)
    except (TypeError, ValueError):
        _ddl = 0
    last_day = 0
    for a in acts:
        at = a.get("time") or {}
        if not at:
            continue
        where = f"act:{a.get('index')}"
        sl = (at.get("slot") or "").strip()
        try:
            day = int(at.get("day") or 0)
        except (TypeError, ValueError):
            day = -1
        if (sl and sl not in _SLOTS) or day < 0:
            err("bad_act_time", where,
                f"第{a.get('index')}幕的时间锚点不合法（slot 可用：{'、'.join(_SLOTS)}；day 需为正整数）。")
            continue
        if not _clock_on(content):
            warn("act_time_no_clock", where,
                 f"第{a.get('index')}幕设了时间锚点，但本剧关闭了时钟"
                 "(tuning.turns_per_slot=0) —— 锚点不会生效。")
        if day:
            if day < last_day:
                err("act_time_backwards", where,
                    f"第{a.get('index')}幕锚在第{day}天，早于前面某幕的第{last_day}天。时间只能向前。")
            last_day = max(last_day, day)
            if _ddl and day > _ddl:
                warn("act_time_past_deadline", where,
                     f"第{a.get('index')}幕锚在第{day}天，已越过大限（第{_ddl}天）。进幕即触发时限结局。")

    # — events that kill —
    char_ids_l = {c.get("id") for c in chars if c.get("id")}
    for a in acts:
        for ev in a.get("events") or []:
            for kid in ev.get("kills_character_ids") or []:
                if kid not in char_ids_l:
                    err("bad_kill", f"event:{ev.get('id')}",
                        f"kills_character_ids 指向不存在的角色：{kid}")

    # — 🔍 verdict —
    vd = _story(content).get("verdict") or {}
    if vd:
        opts = vd.get("options") or []
        if not any(o.get("correct") for o in opts):
            err("verdict_no_answer", "verdict", "指认选项里没有任何 correct=true 的正确答案。")
        ids = [o.get("id") for o in opts if o.get("id")]
        if len(ids) != len(set(ids)) or len(ids) != len(opts):
            err("verdict_bad_options", "verdict", "指认选项的 id 缺失或重复。")
        ending_ids = {e.get("id") for e in _endings(content) if e.get("id")}
        feid = vd.get("fail_ending_id")
        if feid and feid not in ending_ids:
            err("verdict_bad_ending", "verdict", f"fail_ending_id={feid} 不是已知结局。")
        gated = any((e.get("condition") or {}).get("required_flags", {}).get("verdict_solved")
                    for e in _endings(content))
        if not gated:
            warn("verdict_ungated", "verdict",
                 "没有任何结局以 verdict_solved 为条件——指认对了也换不来更好的结局。")

    # — 🦇 threat (a broken hunter config silently no-ops; say so at author time) —
    loc_ids_l = {l.get("id") for l in locs if l.get("id")}
    thr = _story(content).get("threat") or {}
    if thr:
        if thr.get("char_id") not in char_ids_l:
            err("threat_bad_char", "threat", f"threat.char_id={thr.get('char_id')} 不是已知角色。")
        bad_patrol = [p for p in (thr.get("patrol") or []) if p not in loc_ids_l]
        if bad_patrol or not (thr.get("patrol") or []):
            err("threat_bad_patrol", "threat",
                f"threat.patrol 为空或含未知地点：{bad_patrol}——猎手系统将整体失效。")
        for fld in ("cannot_enter",):
            bad = [p for p in (thr.get(fld) or []) if p not in loc_ids_l]
            if bad:
                warn("threat_bad_loc", "threat", f"threat.{fld} 含未知地点：{bad}（会被忽略）。")
        rt = (thr.get("return_to") or "").strip()
        if rt and rt not in loc_ids_l:
            warn("threat_bad_return", "threat",
                 f"threat.return_to={rt} 不是已知地点——将回退到 patrol 首站。")

    # — 🚪 dooms (a dangling doom either never fires or strands its victim) —
    frag_ids_l = {f.get("id") for f in gating.iter_fragments(content) if f.get("id")}
    for dm in _story(content).get("dooms") or []:
        where = f"doom:{dm.get('id') or dm.get('char_id')}"
        if dm.get("char_id") not in char_ids_l:
            err("doom_bad_char", where, f"char_id={dm.get('char_id')} 不是已知角色。")
        if int(dm.get("day") or 0) <= 0:
            err("doom_bad_day", where, "day 必须是正整数（第几天的夜里）。")
        to = (dm.get("to") or "").strip()
        if to and to not in loc_ids_l:
            err("doom_bad_to", where, f"to={to} 不是已知地点——被带走的人将无处可寻。")
        bad_fr = [f for f in ((dm.get("prevent") or {}).get("fragment_ids") or [])
                  if f not in frag_ids_l]
        if bad_fr:
            err("doom_bad_prevent", where,
                f"prevent.fragment_ids 含未知碎片：{bad_fr}——命运将永远无法被阻止。")
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
