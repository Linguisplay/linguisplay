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
# ✍️ 人话修复指引 (创作 UX 首期, Yi 定: 手写模板不过 LLM — 错误类型是有限枚举,
# 确定性归代码)。发布硬门把它拼在原始 msg 后面, 作者照着点就能修好。
HUMAN_FIXES: dict[str, str] = {
    "no_acts": "到「幕」区块加至少一幕——没有幕，故事无法开演。",
    "no_chars": "到「角色」区块加至少一个角色（只有沙盒本可以空着让引擎现铸）。",
    "dup_id": "两个条目撞了同一个编号——删掉重复的那个，或让系统重新生成。",
    "dangling_frag": "某处的条件引用了已被删掉的碎片——去那里重选一个，或清掉这条条件。",
    "gate_deadlock": "这一幕的推进要求一个更晚才解锁的碎片，玩家会被永远卡死——"
                     "把该碎片的「解锁幕数」调早，或者换一个碎片做条件。",
    "frag_bad_event": "碎片的触发事件已不存在——到「秘密」区重选触发事件。",
    "dangling_event": "推进条件里的事件已被删掉——到「幕」区重选或清掉。",
    "dangling_exit": "地点的出口指向了不存在的地点——改成现有地点名或删掉这个出口。",
    "dangling_prop_frag": "物证指向的碎片已不存在——到「地点」区给它重选。",
    "dangling_prop_event": "物证指向的事件已不存在——到「地点」区给它重选。",
    "bad_schedule": "角色作息表里的地点不存在——用「地点」区里已有的名字。",
    "bad_slot": "作息时段只能是 晨/午/夜。",
    "bad_home": "角色的常驻地点不存在——重选一个已有地点。",
    "bad_faction": "角色标了所属阵营，但剧本的阵营表里没有这个阵营——补上阵营或改掉归属。",
    "bad_tie": "角色关系指向了不存在的角色——重选。",
    "bad_frag_location": "碎片解锁条件里的地点不存在——重选。",
    "peek_bad_char": "碎片标了「藏在TA设备里」，但那个角色不存在——重选 device_of。",
    "peek_no_device": "碎片藏在设备里，但剧本没有可翻的实体设备——开启通讯并换掉「口信」。",
    "peek_no_backup": "藏在设备里的碎片必须再留一条别的解锁路（追问/好感/地点/事件/物证）——"
                      "玩家偷看被抓会永久锁死设备，唯一通路等于把真相锁死。",
    "bad_deadline_ending": "时钟大限指向的结局不存在——到「结局」区确认后重选。",
    "bad_act_time": "幕的时间锚不合法（day 要正整数、时段 晨/午/夜）。",
    "act_time_backwards": "后一幕的时间锚比前一幕还早——把时间捋顺。",
    "bad_kill": "事件要杀的角色不存在——重选。",
    "verdict_no_answer": "指认选项里至少要有一个勾了「正确答案」。",
    "verdict_bad_options": "指认选项要有各自独立的编号——删掉重复项。",
    "verdict_bad_ending": "指认失败结局不存在——到「结局」区确认后重选。",
    "threat_bad_char": "猎手指向的角色不存在——重选。",
    "threat_bad_patrol": "猎手巡逻路线里有不存在的地点——重选。",
    "doom_bad_char": "厄运名单里的角色不存在——重选。",
    "doom_bad_day": "厄运的 day 要写正整数（第几天的夜里）。",
    "doom_bad_to": "厄运把人带去的地点不存在——重选。",
}


def humanize_issue(issue: dict[str, Any]) -> str:
    """一条 lint 结果 → 「哪里出了什么事 → 怎么修」的人话。"""
    fix = HUMAN_FIXES.get(str(issue.get("code")), "照提示到对应区块修正。")
    return f"{issue.get('msg', '')}  👉 {fix}"


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
    _sandbox_on = bool(((content.get("story") or {}).get("sandbox") or {}).get("enabled"))
    if chars and not _sandbox_on and not any(c.get("playable") for c in chars):
        # 🏖 沙盒玩家扮演的是自己 (persona), 不点名 playable 是常态 — 不喊
        warn("no_playable", "characters",
             "没有任何角色标记 playable —— 引擎会回退到「任选在场角色」，可能让玩家扮演会破坏剧情的角色。")

    # — 🎭 班底多样性守卫 (角色卡 v2, Yi: 要注重多样性) — 只对 3 人以上的 authored 班底说话
    npc = [c for c in chars if not c.get("playable")]
    if len(npc) >= 3:
        no_gender = [c.get("name") for c in npc if not (c.get("gender") or "").strip()]
        if no_gender:
            warn("no_gender", "characters",
                 f"这些角色没有性别字段（称呼/代词会靠模型猜）：{'、'.join(str(n) for n in no_gender[:6])}")
        genders = {(c.get("gender") or "").strip() for c in npc if (c.get("gender") or "").strip()}
        if len(genders) == 1:
            warn("gender_uniform", "characters",
                 f"班底性别清一色（全是「{next(iter(genders))}」）——群像要有多样性。")
        bands = {(c.get("age_band") or "").strip() for c in npc if (c.get("age_band") or "").strip()}
        if bands and len(bands) == 1 and len(npc) >= 4:
            warn("age_uniform", "characters",
                 f"班底年龄段清一色（全是「{next(iter(bands))}」）——加一点年龄跨度（长辈位/少年位）。")
        no_goal = [c.get("name") for c in npc
                   if not (str((c.get('life_goal') or {}).get('text') or '')
                           or c.get("wants") or c.get("agenda") or "").strip()]
        if no_goal:
            warn("no_life_goal", "characters",
                 f"这些角色没有人生目标（wants/life_goal 都空，导演排不了冲突）："
                 f"{'、'.join(str(n) for n in no_goal[:6])}")

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
    # 🏛 阵营归属: 角色指向的阵营必须在阵营表里 (声望账本按 id 记账, 悬空=永不生效)
    fac_ids = {str(f.get("id") or "") for f
               in ((content.get("story") or {}).get("factions") or [])
               if isinstance(f, dict) and f.get("id")}
    for c in chars:
        fid = str(c.get("faction_id") or "").strip()
        if fid and fid not in fac_ids:
            err("bad_faction", f"char:{c.get('id')}",
                f"「{c.get('name', '')}」的阵营「{fid}」不在剧本的阵营表里")
    for l in locs:
        lid = l.get("id")
        where = f"loc:{lid}"
        # 🗺 有名字没描述 (Yi 报障 2026-08-06:「明明是油麻地但是传送到了餐厅」)。
        # 到达旁白拿不到 detail 时只能靠模型现编, 而地名越大越容易被现编成一个具名
        # 小场所 —— 玩家读到的就是"传送"。狗笼 27 个地点里 19 个空描述, 这道门从前
        # 一声不吭地放它们上线了。提示词侧已经加了兜底口径, 但根子还是把描述写上。
        if (l.get("name") or "").strip() and not (l.get("detail") or "").strip():
            warn("blank_place_detail", where,
                 f"「{l.get('name', '')}」只有名字没有描述 —— 到达旁白会现编一个"
                 f"场景出来（实弹: 走到「油麻地」, 旁白写成推开茶餐厅的门）")
        for ex in l.get("exits") or []:
            if ex not in loc_ids and ex not in loc_names:
                err("dangling_exit", where,
                    f"「{l.get('name', '')}」的出口指向不存在的地点：{ex}")
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
    if acts and not _endings(content) \
            and not ((_story(content).get("sandbox") or {}).get("enabled")):
        warn("no_endings", "story", "剧本没有定义任何结局。")  # 🏖 沙盒无结局是设计

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
        # 📱🔍 device_of (藏在TA设备里): 角色要存在、设备要可翻 (口信没有实体)、
        # 且必须有备用通路 — crit_fail 会永久锁设备, 唯一通路=运行时死锁
        dof = (f.get("unlock") or {}).get("device_of")
        if dof:
            char_ids_f = {c.get("id") for c in chars if c.get("id")}
            where_f = f"fragment[{f.get('id')}]"
            if dof not in char_ids_f:
                err("peek_bad_char", where_f, f"device_of 指向不存在的角色：{dof}")
            ph = _story(content).get("phone") or {}
            if ph.get("enabled") is False or "口信" in (ph.get("device") or ""):
                err("peek_no_device", where_f,
                    "碎片藏在设备里，但这个剧本没有可翻的实体设备（关了通讯或用的是口信）。")
            u = f.get("unlock") or {}
            prop_fids = {p.get("fragment_id")
                         for l in locs for p in (l.get("props") or [])}
            backup = (u.get("asks_min") is not None or u.get("affinity_min") is not None
                      or u.get("location_id") or (u.get("trigger_event_ids") or [])
                      or f.get("id") in prop_fids)
            if not backup:
                err("peek_no_backup", where_f,
                    f"碎片「{f.get('id')}」只有翻设备一条通路——玩家被抓包锁死设备后，"
                    "这条真相本局永远拿不到。")

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
    # lower(): 英文换个大小写就逃逸的检测不算检测 (泄密/复读两用)
    return re.sub(r"[\s，。、！？…—\-,.!?：:；;\"'「」『』（）()]+", "", s or "").lower()


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


_WORD_RE = re.compile(r"[a-z0-9']+")


def _open_words(opening_text: str) -> str:
    """英文开场白的词序列 (空格哨兵包边, 短语查找不许跨词半截命中)。"""
    ws = _WORD_RE.findall((opening_text or "").lower())
    return (" " + " ".join(ws) + " ") if ws else ""


def _echoes_opening(text: str, opening_norm: str, opening_words: str = "",
                    min_run: int = 14) -> bool:
    """True if `text` reproduces the authored opening verbatim. 中文: ≥min_run 归一化
    连字, 或 ≥8 字整段照搬。英文按字符算密度低 (14 字符 ≈ 2 个单词, 惯用短语必误伤),
    改用词级: 5 连词命中, 或 ≥3 词的碎片整串照搬。跟演是接着往下演, 复读是再念
    一遍 — 只有后者算数。"""
    hay = _norm(text)
    if not hay:
        return False
    if sum(c.isascii() for c in hay) > len(hay) * 0.7:   # 英文/拉丁为主的拍
        if not opening_words:
            return False
        ws = _WORD_RE.findall(text.lower())
        if len(ws) < 5:
            return len(ws) >= 3 and (" " + " ".join(ws) + " ") in opening_words
        return any((" " + " ".join(ws[i: i + 5]) + " ") in opening_words
                   for i in range(len(ws) - 4))
    if len(opening_norm) < 8 or len(hay) < 8:
        return False
    if len(hay) < min_run:
        return hay in opening_norm
    for i in range(0, len(hay) - min_run + 1):
        if hay[i: i + min_run] in opening_norm:
            return True
    return False


def _segment_echoes(seg: str, opening_norm: str, opening_words: str = "") -> bool:
    """句级复读判定: 整句连串命中, 或任一逗号级碎片整段照搬 (模型爱把开场白两句
    用逗号重组着念 — 连串窗口跨不过重组缝, 碎片包含才抓得住)。"""
    if _echoes_opening(seg, opening_norm, opening_words):
        return True
    return any(_echoes_opening(fr, opening_norm, opening_words)
               for fr in re.split(r"[，、；,;]", seg) if fr.strip())


def verify_turn(beats: list[dict[str, Any]], *, absent_names: list[str],
                locked_location_names: list[str], locked_fragment_texts: list[str],
                present_names: list[str] | None = None,
                opening_text: str = "") -> dict[str, Any]:
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

    # 🔁 开场白复读 (实弹: 锚块每回合都在, 模型把「向它看齐」听成「把它再念一遍」):
    # 任何一拍逐字重现开场白 (≥14 连字, 或按句拆后整句照搬 — 模型爱把开场白拆两句
    # 重组着念) → 硬伤重演。开场那一拍是引擎拍, 不过此检。
    op = _norm(opening_text or "")
    opw = _open_words(opening_text or "")
    if op:
        for b in beats:
            txt = b.get("text", "")
            if _echoes_opening(txt, op, opw) or any(
                    _segment_echoes(seg, op, opw)
                    for seg in re.split(r"(?<=[。！？…\n.!?])", txt)):
                hard.append("复读了作者开场白的原文（玩家早已读过，戏要往下演）")
                break

    return {"hard": hard, "soft": soft}


def scrub_beats(beats: list[dict[str, Any]], absent_names: list[str],
                opening_text: str = "") -> list[dict[str, Any]]:
    """Last-resort deterministic repair when a regeneration still intrudes: drop the sentences
    in narration that put an absent character on stage — and, in ANY beat, the sentences that
    parrot the authored opening; drop a beat that empties out."""
    op = _norm(opening_text or "")
    opw = _open_words(opening_text or "")
    if not absent_names and not op:
        return beats
    out: list[dict[str, Any]] = []
    for b in beats:
        segs = None
        if b.get("type") == "description" and absent_names:
            segs = [seg for seg in re.split(r"(?<=[。！？…\n.!?])", b.get("text", ""))
                    if not any(_intrudes(seg, n) for n in absent_names)]
        if op:
            segs = [seg for seg in (segs if segs is not None
                                    else re.split(r"(?<=[。！？…\n.!?])", b.get("text", "")))
                    if not _segment_echoes(seg, op, opw)]
        if segs is None:
            out.append(b)
            continue
        text = "".join(segs).strip()
        if text:
            out.append({**b, "text": text})
    return out
