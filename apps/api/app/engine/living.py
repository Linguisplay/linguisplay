# -*- coding: utf-8 -*-
"""🌍 活世界 P1: 世界心跳 + 缺席因果.

Yi 的产品法条 (2026-07-11): 世界有自己的钟, 角色有自己的记性 — 玩家不在,
剧情照样往前走. 这是长期留存战略的地基 (对标恋与深空的主动联系闭环).

每次心跳 (服务端定时器驱动, per-run 可调, 默认每现实日一次):
  ① 游戏内时钟前进一天 — 挂在钟上的一切 (约定/差事/作息) 真的「到点」
  ② 缺席因果: 玩家没赴的约当场落账 (状态翻转 + 关系掉分, 纯数学) —
     戏文与那条带刺的消息押成词债, 回归时才写
  ③ 世界心跳事件: 从最暖的关系里挑一人 (确定性选角), 邀约本体押成词债

⚖️ 无点击不推进 (Yi 2026-07-14 定): 心跳只攒不演 — 不产 run beats (没有观众的
戏不上台), 也不跑 LLM 不发短信. 心跳期间只做确定性状态数学 + 把「该演的」押进
living_news 的 pend 字段; 玩家亲手点开的下一回合由 settle_pending 一次补齐
(写缺席戏文/带刺短信/周年讯息/新邀约并送进小手机), 再经 serve_living_news 播报.
引擎法度照旧: 触发全部确定性, 模型只负责写词; 每样都有确定性兜底.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from . import profile as profile_mod
from . import taste as taste_mod
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


def defer_to_friendly_hour(state: dict[str, Any], tz: str = "", hour: int = 19) -> bool:
    """🔕 静默时段撞上心跳时, 把 last 重锚, 让【下一次】落在玩家本地的傍晚。

    不这么做的话推送会【永久】归零, 而不是"这次先不敲":
    心跳是 600 秒轮询 + 纯 UTC 差值判到期 (见 due), 所以它每天都落在几乎同一个
    钟点 (每天前漂 ≤10 分钟, 要 54 天才漂出一个 9 小时的静默窗)。一个存档的间隔
    一旦落进静默时段, 那个玩家就再也不会被叫回来 —— 消息照进小手机, 但没人知道。

    只动 living.last 一个字段, 不新增状态; 用玩家本地时间算目标点, 所以夏令时自愈。
    返回是否真的重锚了。"""
    c = cfg(state)
    if not c.get("on"):
        return False
    hours = max(1, int(c.get("hours") or DEFAULT_HOURS))
    now = datetime.now(timezone.utc)
    local = now
    if tz:
        try:
            from zoneinfo import ZoneInfo
            local = now.astimezone(ZoneInfo(tz))
        except Exception:
            local = now
    target = local.replace(hour=int(hour), minute=0, second=0, microsecond=0)
    if target <= local:
        target += timedelta(days=1)
    c["last"] = (target.astimezone(timezone.utc)
                 - timedelta(hours=hours)).isoformat(timespec="seconds")
    state["living"] = c
    return True


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


def _pick_invite_char(content, state) -> dict[str, Any] | None:
    """③ 世界主动提出的选角 (确定性, 心跳时跑): pick the warmest promise-free,
    contactable character. The invite itself is a word-debt — written at settle."""
    tun = runtime.tuning_for(content)
    if tun["turns_per_slot"] <= 0 or not runtime.phone_enabled(content):
        return None
    dead = runtime._dead_ids(state)
    met = set(state.get("met_ids") or [])
    open_ids = {p.get("char_id") for p in state.get("promises") or []
                if p.get("status") == "open"}
    from . import socialfic as _sf
    cands = [c for c in runtime._characters(content)
             if c.get("id") and c.get("id") in met and c.get("id") not in dead
             and c.get("id") not in open_ids
             and runtime.has_contact(state, c.get("id"))   # 📇 没交换过联系方式, TA联系不上你
             # 🧩 包D: 拉黑的人不选来发邀约 — 邀约会铸真实约定, 玩家赴不了还要吃爽约账
             and not _sf.holds_incoming(state, c.get("id"))
             and c.get("id") != state.get("player_character_id")]
    if not cands:
        return None
    cands.sort(key=lambda c: -_warmth(state, c.get("id")))
    return cands[0]


def _write_invite(content, state, char, llm: LLM) -> dict[str, Any] | None:
    """③ 邀约补演 (settle 时跑, LLM 在此): the model writes the intent + the invite;
    book it through make_promise (all its refusals — slate full, bad hour, 作息
    away — stand). Re-checks the staged pick: the world moved since the heartbeat."""
    if (not char or not runtime.phone_enabled(content)
            or char.get("id") in runtime._dead_ids(state)
            or not runtime.has_contact(state, char.get("id"))
            or any(p.get("char_id") == char.get("id") and p.get("status") == "open"
                   for p in state.get("promises") or [])):
        return None
    tun = runtime.tuning_for(content)
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
                            "player_taste": taste_mod.top(state),
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
    ev = runtime.phone_push(content, state, char, [invite], now_label)
    return {"char_id": char.get("id"), "name": char.get("name"),
            "what": what, "when": when, "invite": invite, "_phone": ev}


def world_tick(content: dict[str, Any], state: dict[str, Any],
               now: datetime | None = None) -> dict[str, Any]:
    """One heartbeat. Mutates state; returns a summary for the caller/audit.
    Safe to call on any run — refuses ended runs and clock-off stories.
    ⚖️ 无点击不推进: 签名里没有 llm — 心跳在结构上就写不了词, 只做状态数学 + 押词债."""
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
        # the sting (same ledger the in-play爽约 uses) — 纯数学, 心跳当场落账
        old_sc = (state.get("rel") or {}).get(cid) or relationships.new_scores()
        state.setdefault("rel", {})[cid] = relationships.apply_deltas(
            old_sc, -tun["promise_break_cost"],
            -tun["promise_break_cost"] if pr.get("romantic") else 0, tun)
        # ⚖️ 只攒不演: 戏文与带刺短信押成词债 (pend), settle_pending 回归补写 —
        # 心跳里一个 LLM 都不跑, 一条短信都不发 (无点击不推进)
        text_due = runtime.phone_enabled(content) and not pr.get("texted")
        if text_due:
            pr["texted"] = True   # staged: 这条短信 settle 时必补, 不重复押
        news.append({"day": day, "kind": "absent", "char_id": cid,
                     "name": char.get("name") or "", "text": "", "told": False,
                     "pend": {"what": pr.get("what") or "", "slot": pr.get("slot") or "",
                              "day": pr.get("day"), "romantic": bool(pr.get("romantic")),
                              "text_due": text_due}})
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
    # 🎂 判【跨越】不判精确等值 (2026-08-04 修): 原来是 `span % 30`, 一旦某次心跳
    # 覆盖了不止一天 (补算/长时间没来/时区抖动), 天数直接从 29 跳到 31, 那个满月就
    # 【永远】错过了。拨格前的 day 就在 clk 里, 拿它比一次商, 不用新增任何状态。
    _prev_day = int(clk.get("day", 1) or 1)
    for cid, d0 in sorted(annil.items()):
        span = day - int(d0 or day)
        prev_span = max(0, _prev_day - int(d0 or day))
        if span <= 0 or span // 30 <= prev_span // 30:
            continue
        char = runtime._char_by_id(content, cid)
        if not char or cid in dead or _warmth(state, cid) < 35:
            continue
        months = span // 30
        # ⚖️ 只攒不演: 那条亲笔讯息押成词债, settle 时才写才送 (播报文案本就是确定性的)
        news.append({"day": day, "kind": "anniv", "char_id": cid,
                     "name": char.get("name") or "",
                     "text": f"{char.get('name', '')}记得：今天是你们认识满{months}个月的日子。",
                     "told": False,
                     "pend": {"months": months,
                              "msg_due": bool(runtime.phone_enabled(content))}})
        out["anniv"] = {"char_id": cid, "name": char.get("name"), "months": months}
        break

    # ③ the world proposes something new (one per heartbeat, engine-picked at tick;
    #    the invite itself is model-worded at settle — 只攒不演)
    ev_char = None if out["anniv"] else _pick_invite_char(content, state)
    if ev_char is not None:
        out["event"] = {"char_id": ev_char.get("id"), "name": ev_char.get("name") or ""}
        news.append({"day": day, "kind": "invite", "char_id": ev_char.get("id"),
                     "name": ev_char.get("name") or "", "text": "", "told": False,
                     "pend": {"invite_due": True}})

    state["living_news"] = news[-NEWS_CAP:]
    lc = cfg(state)
    lc.update({"last": _now_iso()})
    state["living"] = lc
    runtime._audit(state, "living.tick", True,
                   f"day→{day} absent:{len(out['absent'])} event:{bool(out['event'])}")
    return out


SETTLE_CAP = 4   # 一次回归至多补演几件押后的词债 (其余留给下一拍, 别把回归变成放映厅)


def settle_pending(content: dict[str, Any], state: dict[str, Any],
                   llm: LLM) -> list[dict[str, Any]]:
    """⚖️ 回归结算 (无点击不推进的另一半): 心跳押下的词债, 在玩家亲手点开的回合里
    一次补齐 — 写缺席戏文入关系大事记、补带刺短信/周年讯息、把邀约写词并 make_promise
    正账落定. LLM 只在这里跑. 返回 phone UI 事件列表 (调用方逐个 yield ("phone", ev))."""
    events: list[dict[str, Any]] = []
    done = 0
    now_label = (runtime.clock_view(content, state) or {}).get("label", "")
    for nw in state.get("living_news") or []:
        pend = nw.get("pend")
        if not pend or nw.get("told"):
            continue
        if done >= SETTLE_CAP:
            break
        char = runtime._char_by_id(content, nw.get("char_id"))
        if not char:   # 角色没了 (回溯/改稿) — 这笔词债作废
            nw.pop("pend", None)
            nw["told"] = True
            continue
        cid = char.get("id")
        kind = nw.get("kind")
        if kind == "absent":
            pr = {"what": pend.get("what"), "slot": pend.get("slot"),
                  "day": pend.get("day"), "romantic": pend.get("romantic")}
            scene = _absent_scene(content, state, char, pr, llm)
            nw["text"] = scene
            runtime.rel_log(state, cid, int(state.get("act", 1) or 1), "promise",
                            runtime._t(content, f"你没来。{scene}", f"You never came. {scene}"))
            if pend.get("text_due") and runtime.phone_enabled(content):
                msgs = runtime.compose_message(
                    content, state, char, "stood_up",
                    f"TA爽约了你们约好的（{pend.get('what', '')}），你心里不好受，忍不住捎话给TA",
                    "我等了你很久。你没来。", llm)
                # 🧩 包D: 拉黑期 phone_push 返回 None (消息进暂扣账本) — None 不许
                # 进 events, 下游 _pev.get() 会当场 AttributeError 炸断回合流 (复审 high)
                _p = runtime.phone_push(content, state, char, msgs, now_label)
                if _p:
                    events.append(_p)
        elif kind == "anniv":
            months = int(pend.get("months") or 1)
            if pend.get("msg_due") and runtime.phone_enabled(content):
                msgs = runtime.compose_message(
                    content, state, char, "anniversary",
                    f"今天是你们认识满{months}个月的日子，TA记得，想对玩家说点什么"
                    "（贴人设，可以提一件你们共同经历的小事，别煽情过头）",
                    f"今天，是我们认识满{months}个月的日子。我记得。", llm)
                _p = runtime.phone_push(content, state, char, msgs, now_label)
                if _p:
                    events.append(_p)
        elif kind == "invite":
            ev = _write_invite(content, state, char, llm)
            if not ev:   # 订不上 (档满/作息/世道变了) — 邀约作废, 不硬凑
                nw.pop("pend", None)
                nw["told"] = True
                continue
            nw["text"] = f"{ev['name']}约了你{ev['when']}：{ev['what']}。"
            if ev.get("_phone"):   # 🧩 包D: 拉黑期邀约短信被暂扣 → 没有 UI 事件可发
                events.append(ev["_phone"])
        nw.pop("pend", None)
        done += 1
    return events


def serve_living_news(state: dict[str, Any], cap: int = 3) -> list[str]:
    """Untold heartbeat consequences, marked told — the comeback turn narrates these
    as beats (你不在的时候…). Separate from world_news's rumor mill on purpose.
    带 pend 的词债还没补演 (settle cap 溢出) — 跳过留给下一拍, 不许白丢."""
    out = []
    for nw in state.get("living_news") or []:
        if nw.get("told") or nw.get("pend"):
            continue
        if len(out) >= cap:
            break
        nw["told"] = True
        out.append(nw.get("text") or "")
    return [t for t in out if t]
