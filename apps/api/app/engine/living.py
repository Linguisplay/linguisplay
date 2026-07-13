# -*- coding: utf-8 -*-
"""🌍 活世界 P1: 世界心跳 + 缺席因果.

Yi 的产品法条 (2026-07-11): 世界有自己的钟, 角色有自己的记性 — 玩家不在,
剧情照样往前走. 这是长期留存战略的地基 (对标恋与深空的主动联系闭环).

每次心跳 (服务端定时器驱动, per-run 可调, 默认每现实日一次):
  ① 游戏内时钟前进一天 — 挂在钟上的一切 (约定/差事/作息) 真的「到点」
  ② 缺席因果: 玩家没赴的约, 引擎写下「没有你的那场戏」并真落账 —
     关系掉分、关系大事记、TA 手机里那条带刺的消息、living_news 回归播报
  ③ 世界心跳事件: 从最暖的关系里挑一人, 生成一条新的带时限邀约
     (走 make_promise 正账 + 角色亲笔的邀约短信) — 世界会主动提出, 不只回应

引擎法度照旧: 触发全部确定性, 模型只负责写词; 每样都有确定性兜底;
心跳不产 run beats (没有观众的戏不上台), 后果经 serve_living_news 回归时播报.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from . import profile as profile_mod
from . import relationships
from . import runtime
from .llm import LLM

TICK_ABSENT_CAP = 2     # 一次心跳最多结算几场缺席戏 (别把回归变成刑场)
NEWS_CAP = 12           # living_news 账本上限
DEFAULT_HOURS = 24      # 默认心跳间隔 (现实小时)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def cfg(state: dict[str, Any]) -> dict[str, Any]:
    return dict(state.get("living") or {})


def is_on(state: dict[str, Any]) -> bool:
    return bool(cfg(state).get("on"))


def set_living(state: dict[str, Any], on: bool, hours: int | None = None) -> dict[str, Any]:
    """Flip the living-world switch. Turning it on stamps `last` so the first
    heartbeat lands a full interval later, not the next scheduler pass."""
    if on:
        state["living"] = {"on": True,
                           "hours": max(1, min(24 * 7, int(hours or DEFAULT_HOURS))),
                           "last": _now_iso()}
    else:
        state["living"] = {"on": False}
    return state["living"]


def due(state: dict[str, Any], now: datetime | None = None) -> bool:
    c = cfg(state)
    if not c.get("on") or state.get("ended"):
        return False
    now = now or datetime.now(timezone.utc)
    try:
        last = datetime.fromisoformat(str(c.get("last")))
    except (TypeError, ValueError):
        return True
    return (now - last).total_seconds() >= int(c.get("hours") or DEFAULT_HOURS) * 3600


def _warmth(state: dict[str, Any], cid: str) -> int:
    sc = (state.get("rel") or {}).get(cid) or relationships.new_scores()
    return int(sc.get("closeness", 0) or 0) + int(sc.get("romance", 0) or 0)


def _absent_scene(content, state, char, pr, llm: LLM) -> str:
    """「没有你的那场戏」— the model writes it, a deterministic line backstops it."""
    when = runtime.promise_when_label(content, pr, state)
    tun = runtime.tuning_for(content)
    scores = (state.get("rel") or {}).get(char.get("id")) or relationships.new_scores()
    try:
        out = llm.generate({"absent_scene": True,
                            "char": {"name": char.get("name"), "role": char.get("role") or "",
                                     "persona_text": (char.get("persona_text") or "")[:160]},
                            "relation": relationships.name_of(
                                relationships.derive_mode(char, scores, tun)),
                            "what": pr.get("what") or "", "when": when,
                            "world": ((content.get("story") or {}).get("world_long")
                                      or "")[:300]}) or {}
    except Exception:
        out = {}
    txt = runtime.dedash(str(out.get("scene") or "").strip())[:110]
    return txt or (f"{char.get('name','')}如约到了地方，等到{pr.get('slot','')}尽了也没等到你，"
                   f"一个人把（{pr.get('what','')}）的位置坐冷了。")


def _heartbeat_event(content, state, llm: LLM) -> dict[str, Any] | None:
    """③ 世界主动提出: pick the warmest promise-free character (deterministic),
    let the model write the intent + the invite; book it through make_promise
    (all its refusals — slate full, bad hour, 作息 away — stand)."""
    tun = runtime.tuning_for(content)
    if tun["turns_per_slot"] <= 0 or not runtime.phone_enabled(content):
        return None
    dead = runtime._dead_ids(state)
    met = set(state.get("met_ids") or [])
    open_ids = {p.get("char_id") for p in state.get("promises") or []
                if p.get("status") == "open"}
    cands = [c for c in runtime._characters(content)
             if c.get("id") and c.get("id") in met and c.get("id") not in dead
             and c.get("id") not in open_ids
             and runtime.has_contact(state, c.get("id"))   # 📇 没交换过联系方式, TA联系不上你
             and c.get("id") != state.get("player_character_id")]
    if not cands:
        return None
    cands.sort(key=lambda c: -_warmth(state, c.get("id")))
    char = cands[0]
    scores = (state.get("rel") or {}).get(char.get("id")) or relationships.new_scores()
    try:
        out = llm.generate({"living_event": True,
                            "char": {"name": char.get("name"), "role": char.get("role") or "",
                                     "persona_text": (char.get("persona_text") or "")[:160]},
                            "relation": relationships.name_of(
                                relationships.derive_mode(char, scores, tun)),
                            # 🪞 P2 个性化: TA 按自己对你的了解来约, 不发通用邀请
                            "impression": profile_mod.impression_of(state, char.get("id")),
                            "player_facts": profile_mod.facts_of(state)[:4],
                            "worldview": ((content.get("story") or {}).get("world_long")
                                          or "")[:400],
                            "recent_news": [n.get("text") for n in
                                            (state.get("living_news") or [])[-3:]]}) or {}
    except Exception:
        out = {}
    what = runtime.dedash(str(out.get("what") or "").strip())[:40] or "见一面，有话想当面说"
    slot = str(out.get("slot") or "").strip()
    if slot not in runtime.SLOTS:
        slot = "夜"
    try:
        off = max(1, min(2, int(out.get("day_offset", 1))))
    except (TypeError, ValueError):
        off = 1
    pr = runtime.make_promise(content, state, char,
                              {"what": what, "slot": slot, "day_offset": off}, tun)
    if not pr:
        return None
    when = runtime.promise_when_label(content, pr, state)
    invite = runtime.dedash(str(out.get("invite") or "").strip())[:120] \
        or f"{when}有空吗？{what}。你来。"
    now_label = (runtime.clock_view(content, state) or {}).get("label", "")
    msgs = [invite]
    runtime.phone_push(content, state, char, msgs, now_label)
    return {"char_id": char.get("id"), "name": char.get("name"),
            "what": what, "when": when, "invite": invite}


def world_tick(content: dict[str, Any], state: dict[str, Any],
               llm: LLM, now: datetime | None = None) -> dict[str, Any]:
    """One heartbeat. Mutates state; returns a summary for the caller/audit.
    Safe to call on any run — refuses ended runs and clock-off stories."""
    out: dict[str, Any] = {"advanced": False, "absent": [], "event": None}
    tun = runtime.tuning_for(content)
    if state.get("ended") or tun["turns_per_slot"] <= 0:
        return out

    # ① the world's day turns over. Real-time stories: the real clock IS the world's
    # clock — the tick only re-syncs it (a forced +1 would fight the in-play sync and
    # yo-yo the calendar); expiry lands when the real hour truly passes. Others: one
    # heartbeat = one diegetic day.
    clk = dict(state.get("clock") or {"day": 1, "slot": 0, "turns_in_slot": 0})
    if runtime.real_time_on(content):
        runtime.sync_real_clock(content, state)
    else:
        state["clock"] = {**clk, "day": int(clk.get("day", 1) or 1) + 1, "turns_in_slot": 0}
    out["advanced"] = True

    # ② 缺席因果: promises the turned day rolled past — the scene happens WITHOUT you
    now_idx = runtime._time_index(state)
    news = list(state.get("living_news") or [])
    day = int((state.get("clock") or {}).get("day", 1) or 1)
    now_label = (runtime.clock_view(content, state) or {}).get("label", "")
    for pr in (state.get("promises") or []):
        if len(out["absent"]) >= TICK_ABSENT_CAP:
            break
        if pr.get("status") != "open" or runtime._promise_index(pr) >= now_idx:
            continue
        char = runtime._char_by_id(content, pr.get("char_id"))
        pr["status"] = "missed"
        if not char:
            continue
        cid = char.get("id")
        # the sting (same ledger the in-play爽约 uses)
        old_sc = (state.get("rel") or {}).get(cid) or relationships.new_scores()
        state.setdefault("rel", {})[cid] = relationships.apply_deltas(
            old_sc, -tun["promise_break_cost"],
            -tun["promise_break_cost"] if pr.get("romantic") else 0, tun)
        # the scene, committed as world truth
        scene = _absent_scene(content, state, char, pr, llm)
        runtime.rel_log(state, cid, int(state.get("act", 1) or 1), "promise",
                        f"你没来。{scene}")
        news.append({"day": day, "kind": "absent", "char_id": cid,
                     "name": char.get("name") or "", "text": scene, "told": False})
        # the hurt text lands in the 小手机 NOW, not when the player next shows up
        if runtime.phone_enabled(content) and not pr.get("texted"):
            pr["texted"] = True
            msgs = runtime.compose_message(
                content, state, char, "stood_up",
                f"TA爽约了你们约好的（{pr.get('what','')}），你心里不好受，忍不住捎话给TA",
                "我等了你很久。你没来。", llm)
            runtime.phone_push(content, state, char, msgs, now_label)
        out["absent"].append({"char_id": cid, "name": char.get("name"),
                              "what": pr.get("what")})

    # ②.5 纪念日 (P4): 认识满月的日子, 温度够的角色会记得 — 一次心跳至多过一个,
    # 过纪念日的当天不再发普通邀约 (这一天的心意只有一种)
    annil = dict(state.get("anniv_met") or {})
    for cid in set(state.get("met_ids") or []):
        if cid not in annil:
            annil[cid] = day   # 老档近似: 从今天起算; 新识的人下次心跳落账 (≤1天误差)
    state["anniv_met"] = annil
    out["anniv"] = None
    dead = runtime._dead_ids(state)
    for cid, d0 in sorted(annil.items()):
        span = day - int(d0 or day)
        if span <= 0 or span % 30:
            continue
        char = runtime._char_by_id(content, cid)
        if not char or cid in dead or _warmth(state, cid) < 35:
            continue
        months = span // 30
        if runtime.phone_enabled(content):
            msgs = runtime.compose_message(
                content, state, char, "anniversary",
                f"今天是你们认识满{months}个月的日子，TA记得，想对玩家说点什么"
                "（贴人设，可以提一件你们共同经历的小事，别煽情过头）",
                f"今天，是我们认识满{months}个月的日子。我记得。", llm)
            runtime.phone_push(content, state, char, msgs, now_label)
        news.append({"day": day, "kind": "anniv", "char_id": cid,
                     "name": char.get("name") or "",
                     "text": f"{char.get('name', '')}记得：今天是你们认识满{months}个月的日子。",
                     "told": False})
        out["anniv"] = {"char_id": cid, "name": char.get("name"), "months": months}
        break

    # ③ the world proposes something new (one per heartbeat, engine-picked, model-worded)
    out["event"] = None if out["anniv"] else _heartbeat_event(content, state, llm)
    if out["event"]:
        news.append({"day": day, "kind": "invite", "char_id": out["event"]["char_id"],
                     "name": out["event"]["name"],
                     "text": f"{out['event']['name']}约了你{out['event']['when']}："
                             f"{out['event']['what']}。", "told": False})

    state["living_news"] = news[-NEWS_CAP:]
    lc = cfg(state)
    lc.update({"last": _now_iso()})
    state["living"] = lc
    runtime._audit(state, "living.tick", True,
                   f"day→{day} absent:{len(out['absent'])} event:{bool(out['event'])}")
    return out


def serve_living_news(state: dict[str, Any], cap: int = 3) -> list[str]:
    """Untold heartbeat consequences, marked told — the comeback turn narrates these
    as beats (你不在的时候…). Separate from world_news's rumor mill on purpose."""
    out = []
    for nw in state.get("living_news") or []:
        if nw.get("told"):
            continue
        if len(out) >= cap:
            break
        nw["told"] = True
        out.append(nw.get("text") or "")
    return [t for t in out if t]
