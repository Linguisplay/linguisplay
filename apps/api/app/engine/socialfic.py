# -*- coding: utf-8 -*-
"""🧩 局内社交拟真 (对齐包D, 设计稿 30-33/36-37/48/25/49-50/22/23b/38):
玩家发帖被角色看见 → 拉黑因果 + 非对称账本 → 世界论坛 / 按幕锁消息 / 浏览器历史。

家法三条:
· 认知边界: 帖子/记忆只进【met 过的角色】各自的账, 不开天眼。
· 剧透安全: 论坛/浏览器/草稿的素材只走账本人话 (npc_rel 演变/在办的事/约定/关系档),
  锁着的秘密正文一个字不许进素材 —— 措辞想泄密也无密可泄 (_peek_cache 同款家法)。
· 确定性兜底: 每条 LLM 生成路都要能在模型空手时 (Mock/{}) 落到确定性文案 —— 社交
  拟真是氛围件, 不许因为模型断供而整面塌掉。

引擎故事无关 (linguisplay-engine-story-agnostic): 频道/句式全部从剧本数据推导。
"""
from __future__ import annotations

import re
import uuid
import zlib
from typing import Any

# ⚠️ runtime 在模块顶自 import socialfic (薄钩子), 这里必须【函数内】懒引 runtime,
# 否则循环引用 (diary/profile 卫星模块同款处境, 家法一致)。


def _rt():
    from . import runtime
    return runtime


# ══════════════════════════════════════════════════════════
# 刀① 玩家发帖 → 角色看见 / 记忆 / 对白引用
# ══════════════════════════════════════════════════════════
_POST_CAP = 280
_LIKE_CLOSENESS = 30   # 亲密度到这档的自动点赞 (确定性, 不烧调用)


def player_post(content: dict[str, Any], state: dict[str, Any], text: str) -> dict[str, Any]:
    """玩家以局内身份发动态 (设计稿 31 ComposeStory: seen by characters in this world)。
    发出去的那一刻: ①进 social 账本 (与角色帖同一条流) ②met 角色各记一笔
    ③亲密度够的当场点赞 ④留一条「对白引用」echo 给主叙者 (下回合可自然提起)。"""
    rt = _rt()
    t = rt.dedash((text or "").strip())[:_POST_CAP]
    if len(t) < 2:
        raise ValueError("先写点什么——两个字也行")
    so = rt._social_state(state)
    dead = rt._dead_ids(state)
    pcid = state.get("player_character_id")
    likers = []
    for cid in state.get("met_ids") or []:
        if cid in dead or cid == pcid:
            continue
        lv = block_level(state, cid)
        if lv == "removed":
            continue          # 移出剧情的人不再看你的生活
        c = rt._char_by_id(content, cid)
        if not c:
            continue
        # 认知边界: 各记各的账, 只记「发过」这个事实和短摘 — 不替角色理解内容。
        # ⚠️ 人称家法 (复审抓的): memory_by_char 是【角色自己的账】—— 你=角色本人,
        # 对方=玩家 (bank_transfer/peek 同款口径), 写反了角色会把事栽给自己。
        mem = (state.get("memory_by_char", {}) or {}).get(cid) or ""
        state.setdefault("memory_by_char", {})[cid] = \
            (mem + rt._t(content, f"；对方公开发过一条动态：「{t[:40]}」",
                         f"; they posted publicly: \"{t[:40]}\"")).strip("；; ")
        scores = (state.get("rel") or {}).get(cid) or {}
        if lv != "block" and int(scores.get("closeness", 0) or 0) >= _LIKE_CLOSENESS:
            likers.append(c.get("name") or "")
    post = {"id": f"po_{uuid.uuid4().hex[:8]}", "cid": "_you", "mine": True,
            "name": rt._t(content, "你", "You"),
            "text": t, "label": (rt.clock_view(content, state) or {}).get("label", ""),
            "liked": False, "liked_by": [n for n in likers if n], "comments": []}
    so.setdefault("posts", []).append(post)
    so["posts"] = so["posts"][-12:]
    so["echo"] = {"post_id": post["id"], "text": t, "served": False}
    rt._audit(state, "social.post", True, "", t[:24])
    return post


def take_echo(content: dict[str, Any], state: dict[str, Any]) -> str | None:
    """主叙者的一次性引用素材 (设计稿 32 FeedbackLoop: 角色在对话里提起你的动态)。
    取一次即核销 —— 一条动态只被当面提起一回, 不许变成复读机。"""
    rt = _rt()
    so = (state.get("social") or {})
    echo = so.get("echo") or {}
    if not echo or echo.get("served") or not (echo.get("text") or "").strip():
        return None
    echo["served"] = True
    return rt._t(content,
                 f"你看到了对方公开发的动态：「{echo['text'][:60]}」",
                 f"You saw what they posted: \"{echo['text'][:60]}\"")


# ══════════════════════════════════════════════════════════
# 刀② 拉黑三档 + 非对称账本
# ══════════════════════════════════════════════════════════
_LEVELS = ("mute", "block", "removed")
_HELD_CAP = 12


def _blocks(state: dict[str, Any]) -> dict[str, Any]:
    return state.setdefault("blocks", {})


def block_level(state: dict[str, Any], cid: str) -> str | None:
    b = (state.get("blocks") or {}).get(cid) or {}
    return b.get("level") or None


def levels_view(state: dict[str, Any]) -> dict[str, str]:
    return {cid: b.get("level") for cid, b in (state.get("blocks") or {}).items()
            if isinstance(b, dict) and b.get("level")}


def muted_ids(state: dict[str, Any]) -> set:
    return {cid for cid, lv in levels_view(state).items() if lv == "mute"}


def holds_incoming(state: dict[str, Any], cid: str | None) -> bool:
    """block/removed 拦投递 (mute 只静音角标不拦信)。"""
    return block_level(state, cid or "") in ("block", "removed")


def hold_incoming(state: dict[str, Any], cid: str, msgs: list[str],
                  now_label: str, call: bool = False) -> None:
    """非对称账本 (设计稿 48): TA 视角这些【已发出】, 你的手机从没响过。
    原时序暂扣, 解除时逐条回放。封顶之外最老的顶掉 —— 顶掉的记条数 (dropped),
    「可撤销不删档」的诚实版本是: 最近 {_HELD_CAP} 条不删档, 更早的只剩个数。"""
    b = _blocks(state).setdefault(cid, {})
    held = b.setdefault("held", [])
    for m in msgs or []:
        held.append({"text": str(m)[:120], "at": now_label, "call": bool(call)})
    if len(held) > _HELD_CAP:
        b["dropped"] = int(b.get("dropped", 0) or 0) + (len(held) - _HELD_CAP)
        del held[:-_HELD_CAP]


def held_count(state: dict[str, Any], cid: str) -> int:
    b = (state.get("blocks") or {}).get(cid) or {}
    return len(b.get("held") or []) + int(b.get("dropped", 0) or 0)


def _replay_held(rt, state: dict[str, Any], cid: str, cur: dict[str, Any],
                 content: dict[str, Any]) -> int:
    """暂扣→线程回放 (解除拉黑 / 降到 mute 都要走): 原时序、未读亮起。"""
    held = list(cur.get("held") or [])
    if not held:
        return 0
    th = rt._thread(state, cid)
    dropped = int(cur.get("dropped", 0) or 0)
    if dropped:
        th["msgs"].append({"from": "them",
                           "text": rt._t(content, f"（更早还有{dropped}条，没能留下来）",
                                         f"({dropped} earlier messages didn't survive)"),
                           "at": (held[0] or {}).get("at", "")})
    for m in held:
        rec = {"from": "them", "text": m.get("text") or "", "at": m.get("at", "")}
        if m.get("call"):
            rec["call"] = True
        th["msgs"].append(rec)
    rt._thread_cap(th)
    th["unread"] = int(th.get("unread", 0)) + len(held)
    cur["held"] = []
    cur["dropped"] = 0
    return len(held)


def set_block(content: dict[str, Any], state: dict[str, Any], cid: str,
              level: str | None) -> dict[str, Any]:
    """三档状态机 (设计稿 36: This is a relationship state, not deletion)。
    level=None 解除: removed 的人回台, 暂扣的消息按原时序回放进线程。"""
    rt = _rt()
    level = (level or "").strip() or None   # 空白档位归一成解除, 别掉进影子分支
    c = rt._char_by_id(content, cid)
    if not c:
        raise ValueError("没有这个角色")
    if cid == state.get("player_character_id"):
        raise ValueError("拉黑自己没有意义")
    if level and level not in _LEVELS:
        raise ValueError("只有 mute / block / removed 三档")
    blocks = _blocks(state)
    cur = blocks.get(cid) or {}
    old = cur.get("level")
    if level == old or (level is None and not old):
        return {"level": level, "released": 0}   # 没拉黑过的「解除」是空操作, 不许假记账
    dev = rt.phone_device(content)
    released = 0
    if level:
        entry = {"level": level, "day": int((state.get("clock") or {}).get("day", 1) or 1),
                 "held": list(cur.get("held") or []),
                 "dropped": int(cur.get("dropped", 0) or 0),
                 "charged": bool(cur.get("charged"))}
        if "was_presence" in cur:
            entry["was_presence"] = cur["was_presence"]
        # removed = 下台, 走现成的 presence 机制 (地图/名册/对白/作息全部跟着走,
        # 不另起一套 present 过滤 —— 一处状态两处真相是穿帮之源)。
        # _removed_by_player 旗给 roster 提示词分流: 被移出的是活人, 不是镜中物。
        if level == "removed" and c.get("presence") != "offstage":
            entry["was_presence"] = c.get("presence") or "present"
            c["presence"] = "offstage"
            c["_removed_by_player"] = True
        if old == "removed" and level != "removed":
            if "was_presence" in cur:   # 作者本来就 offstage 的人不许被强行上台
                c["presence"] = cur["was_presence"]
            c.pop("_removed_by_player", None)
        # 降到 mute = 不再拦投递 → 之前暂扣的立刻回放 (不然积压永远出不来)
        if level == "mute" and old in ("block", "removed"):
            released = _replay_held(rt, state, cid, entry, content)
        blocks[cid] = entry
        # 结账只在【TA感知得到】的档位, 且一生一次: mute 是玩家单方面静音,
        # TA 无从知晓 → 不扣关系不写记忆 (复审抓的: mute 曾被记成拉黑还倒扣分)
        if level in ("block", "removed") and not entry.get("charged"):
            entry["charged"] = True
            scores = (state.get("rel") or {}).get(cid) or rt.relationships.new_scores()
            state.setdefault("rel", {})[cid] = rt.relationships.apply_deltas(
                scores, -4, -2, rt.tuning_for(content), trust_delta=-4)
            mem = (state.get("memory_by_char", {}) or {}).get(cid) or ""
            state.setdefault("memory_by_char", {})[cid] = \
                (mem + rt._t(content, f"；对方把你拉黑了（{dev}打不通，人也见不着）",
                             f"; they blocked you — your {dev} messages bounce")).strip("；; ")
        rt._audit(state, "social.block", True, c.get("name", ""), level)
    else:
        # 解除: 回台 + 回放暂扣
        if old == "removed":
            if "was_presence" in cur:
                c["presence"] = cur["was_presence"]
            c.pop("_removed_by_player", None)
        released = _replay_held(rt, state, cid, cur, content)
        blocks.pop(cid, None)
        if cur.get("charged"):   # TA 知道被拉黑过, 才谈得上「被放出来」
            mem = (state.get("memory_by_char", {}) or {}).get(cid) or ""
            state.setdefault("memory_by_char", {})[cid] = \
                (mem + rt._t(content, "；对方把你从黑名单里放了出来",
                             "; they unblocked you")).strip("；; ")
        rt._audit(state, "social.unblock", True, c.get("name", ""), f"released={released}")
    return {"level": level, "released": released}


def blocked_line(content: dict[str, Any], state: dict[str, Any],
                 cid: str | None) -> str | None:
    """演员提示词的一行事实 (拉黑要在戏里疼): TA 知道自己被拉黑了。
    mute 不注入 —— 静音是玩家单方面的, TA 无从知晓。"""
    rt = _rt()
    lv = block_level(state, cid or "")
    if lv not in ("block", "removed"):
        return None
    dev = rt.phone_device(content)
    n = held_count(state, cid)
    zh = (f"对方把你拉黑了：{dev}发不出去（你已经发了{n}条石沉大海），当面也吃了闭门羹。"
          if lv == "block" else
          f"对方把你彻底移出了TA的生活。你发的{n}条消息TA一条都收不到。")
    en = (f"They blocked you: your {dev} messages don't go through ({n} sent into silence)."
          if lv == "block" else
          f"They cut you out of their life entirely; none of your {n} messages arrived.")
    return rt._t(content, zh, en)


# ══════════════════════════════════════════════════════════
# 刀③ 世界论坛 + 按幕锁消息 + 浏览器历史 / TA 草稿
# ══════════════════════════════════════════════════════════
_FORUM_CAP = 18


def _forum(state: dict[str, Any]) -> dict[str, Any]:
    return state.setdefault("forum", {"mark": -1, "posts": []})


def _anon_handle(content: dict[str, Any], c: dict[str, Any]) -> str:
    """TA 的匿名马甲: 从名字稳定推导 (同一角色永远同一个马甲), 不露真名。"""
    rt = _rt()
    n = zlib.crc32((c.get("id") or c.get("name") or "").encode("utf-8"))
    zh = ["夜行人", "无名氏", "过路客", "守夜的", "旧屋檐", "闻风者", "廊下客", "背光者"]
    en = ["nightwalker", "no_name", "passerby", "lampkeeper", "old_eaves",
          "windhearer", "hallway_ghost", "backlit"]
    lang_en = ((content.get("story") or {}).get("language") or "zh") == "en"
    pool = en if lang_en else zh
    return f"{pool[n % len(pool)]}{n % 97}"


def forum_channels(content: dict[str, Any]) -> list[str]:
    """频道从剧本数据推导 (故事无关): 题材标签 + 起始地名 + 一个通用忏悔频道。"""
    rt = _rt()
    story = (content.get("story") or {})
    out = []
    for t in (story.get("trope_tags") or [])[:2]:
        t = str(t).strip()
        if t:
            out.append("#" + t[:12])
    locs = story.get("locations") or []
    if locs and (locs[0].get("name") or "").strip():
        out.append("#" + str(locs[0]["name"]).strip()[:12])
    out.append(rt._t(content, "#树洞", "#confessions"))
    seen, uniq = set(), []
    for ch in out:
        if ch not in seen:
            seen.add(ch)
            uniq.append(ch)
    return uniq[:4]


def _forum_material(content: dict[str, Any], state: dict[str, Any]) -> list[dict[str, Any]]:
    """发帖素材: 账本人话 only (npc_rel 演变/在办的事), 锁着的秘密无路可进。"""
    rt = _rt()
    dead = rt._dead_ids(state)
    pcid = state.get("player_character_id")
    met = set(state.get("met_ids") or [])
    act = int(state.get("act", 1) or 1)
    items = []
    for c in rt._characters(content):
        cid = c.get("id")
        # met 门与 social_feed 同款 (复审抓的: 信息不开天眼 —— 没见过的名字不许
        # 从论坛提前端给玩家); _is_present 挡 offstage/未登场的藏牌角色。
        if not cid or cid in dead or cid == pcid or cid not in met:
            continue
        if not rt._is_present(c, act) or block_level(state, cid) == "removed":
            continue
        hooks = []
        intent = ((state.get("char_sim") or {}).get(cid) or {}).get("intent")
        if intent:
            hooks.append(str(intent)[:40])
        for k, e in (state.get("npc_rel") or {}).items():
            if cid in k.split("|"):
                hooks += [str(l.get("why") or "")[:40] for l in (e.get("log") or [])[-1:]]
        # 自名洗涤 (复审抓的): npc_rel 的 why 是第三人称账本句, 常带发帖人自己的
        # 名字 —— 匿名帖里喊出自己的真名 = 马甲当场送人。改成第一人称。
        nm = (c.get("name") or "").strip()
        if nm:
            hooks = [h.replace(nm, rt._t(content, "我", "I")) for h in hooks]
        if hooks:
            items.append({"cid": cid, "name": c.get("name"), "lead": bool(c.get("is_lead")),
                          "hooks": [h for h in hooks if h][:2]})
    return items[:4]


def forum_feed(content: dict[str, Any], state: dict[str, Any], llm) -> dict[str, Any]:
    """世界内论坛 (设计稿 25/49/50): 账本指纹驱动铸帖 (social_feed 同款节流),
    一次生成永久缓存。含: 具名 NPC 帖、TA 的匿名帖、无名路人的风闻帖。
    玩家的帖有人接话: 指纹变了且有未回应的玩家帖 → 铸一条回复。"""
    rt = _rt()
    fo = _forum(state)
    mark = rt._social_mark(content, state)
    if mark != fo.get("mark"):
        fo["mark"] = mark
        label = (rt.clock_view(content, state) or {}).get("label", "")
        chans = forum_channels(content)
        material = _forum_material(content, state)
        new_posts: list[dict[str, Any]] = []
        try:
            out = llm.generate({"forum_posts": True, "items": material,
                                "channels": chans,
                                "era": rt.era_of(content),
                                "device": rt.phone_device(content)}) or {}
            new_posts = [p for p in (out.get("posts") or []) if isinstance(p, dict)]
        except Exception:
            new_posts = []
        by_name = {i["name"]: i for i in material}
        minted = []
        for p in new_posts[:3]:
            nm = str(p.get("name") or "").strip()
            it = by_name.get(nm)
            txt = rt.dedash(str(p.get("text") or "").strip()[:120])
            if not it or not txt:
                continue
            c = rt._char_by_id(content, it["cid"]) or {}
            anon = bool(it.get("lead"))   # 主角帖走匿名马甲 (设计稿: he_lurks_here)
            minted.append({"id": f"fo_{uuid.uuid4().hex[:8]}", "cid": it["cid"],
                           "author": _anon_handle(content, c) if anon else nm,
                           "anon": anon, "channel": chans[-1] if anon else chans[0],
                           "text": txt, "label": label, "likes": 0, "replies": []})
        if not minted and material:
            # 确定性兜底: 模型空手时, 账本人话直接上墙 (风闻体)
            for it in material[:2]:
                c = rt._char_by_id(content, it["cid"]) or {}
                anon = bool(it.get("lead"))
                hook = (it.get("hooks") or [rt._t(content, "最近夜里睡不安稳",
                                                 "sleep comes hard lately")])[0]
                txt = rt._t(content, f"{hook}。有人懂这种感觉吗？",
                            f"{hook}. Anyone else know the feeling?")
                minted.append({"id": f"fo_{uuid.uuid4().hex[:8]}", "cid": it["cid"],
                               "author": _anon_handle(content, c) if anon else it["name"],
                               "anon": anon, "channel": chans[-1] if anon else chans[0],
                               "text": txt, "label": label, "likes": 0, "replies": []})
        # 无名路人的风闻帖 (龙套层: 不占人数不知内幕, 说的是"这地方"不是秘密)
        locs = (content.get("story") or {}).get("locations") or []
        if locs and not any(p.get("passerby") for p in fo.get("posts") or []):
            ln = str((locs[0].get("name") or "")).strip()
            if ln:
                minted.append({"id": f"fo_{uuid.uuid4().hex[:8]}", "cid": None,
                               "author": _anon_handle(content, {"id": "_walker"}),
                               "anon": True, "passerby": True,
                               "channel": chans[min(1, len(chans) - 1)],
                               "text": rt._t(content,
                                             f"夜里路过{ln}，总觉得那儿的灯比别处亮得晚。",
                                             f"Passed {ln} at night. The lights there stay on later than they should."),
                               "label": label, "likes": 0, "replies": []})
        fo.setdefault("posts", []).extend(minted)
        fo["posts"] = fo["posts"][-_FORUM_CAP:]
    # 玩家的帖有人接话 (一次一条, 不吵) — 站在指纹分支【外面】: 指纹没变不该等于
    # 楼主永远没人理 (测试当场抓的)。已有回复的帖不再补, 每帖至多铸一次。
    mine = next((p for p in reversed(fo.get("posts") or [])
                 if p.get("author") == "you" and not p.get("replies")), None)
    material_now = _forum_material(content, state)
    if mine and material_now:
        it = material_now[0]
        reply_txt = None
        try:
            out = llm.generate({"forum_reply": True, "post": mine.get("text"),
                                "name": it["name"],
                                "persona": (rt._char_by_id(content, it["cid"]) or {}).get("persona_text", "")[:60]}) or {}
            reply_txt = rt.dedash(str(out.get("reply") or "").strip()[:80]) or None
        except Exception:
            reply_txt = None
        mine.setdefault("replies", []).append({
            "author": it["name"],
            "text": reply_txt or rt._t(content, "楼主说到点子上了。", "You said it.")})
    # 出参消毒 (复审抓的): 匿名帖的真实 cid 不许出 API —— 马甲不是展示层魔术,
    # devtools 一眼看穿等于没有。账本里保留 cid (引擎侧要用), 只在视图上剥。
    out_posts = [({**p, "cid": None} if p.get("anon") else p)
                 for p in reversed(fo.get("posts") or [])]
    return {"channels": forum_channels(content), "posts": out_posts}


def forum_player_post(content: dict[str, Any], state: dict[str, Any],
                      text: str, channel: str = "") -> dict[str, Any]:
    rt = _rt()
    t = rt.dedash((text or "").strip())[:200]
    if len(t) < 2:
        raise ValueError("先写点什么——两个字也行")
    fo = _forum(state)
    chans = forum_channels(content)
    post = {"id": f"fo_{uuid.uuid4().hex[:8]}", "cid": None, "author": "you",
            "anon": False, "channel": (channel if channel in chans else chans[0]),
            "text": t, "label": (rt.clock_view(content, state) or {}).get("label", ""),
            "likes": 0, "replies": []}
    fo.setdefault("posts", []).append(post)
    fo["posts"] = fo["posts"][-_FORUM_CAP:]
    rt._audit(state, "forum.post", True, "", t[:24])
    return post


# ── 按幕锁消息 (设计稿 23b「3 more messages tonight. Reach Act III.」) ──────────
def filter_device_peek(c: dict[str, Any], act: int) -> tuple[list, int, int | None]:
    """作者素材按幕位过滤: (可见条目, 锁住数, 最近解锁幕)。act_min 缺省 = 一直可见。"""
    vis, locked = [], []
    for e in (c.get("device_peek") or []):
        if int(e.get("act_min") or 0) <= act:
            vis.append(e)
        else:
            locked.append(int(e.get("act_min") or 0))
    return vis, len(locked), (min(locked) if locked else None)


# ── 浏览器历史 + TA 的未发送草稿 (深翻附带, _peek_cache 家法: 一次生成永久一致) ──
def device_extras(content: dict[str, Any], state: dict[str, Any],
                  c: dict[str, Any], llm) -> dict[str, Any]:
    rt = _rt()
    cid = c.get("id")
    pk = rt._peek_state(state, cid)
    if pk.get("extras"):
        return pk["extras"]
    scores = (state.get("rel") or {}).get(cid) or rt.relationships.new_scores()
    intent = str(((state.get("char_sim") or {}).get(cid) or {}).get("intent") or "")[:40]
    romance = int(scores.get("romance", 0) or 0)
    close = int(scores.get("closeness", 0) or 0)
    whys = []
    for k, e in (state.get("npc_rel") or {}).items():
        if cid and cid in k.split("|"):
            whys += [str(l.get("why") or "")[:36] for l in (e.get("log") or [])[-2:]]
    browser: list[dict[str, Any]] = []
    drafts: list[str] = []
    try:
        out = llm.generate({"peek_browser": True,
                            "owner": {"name": c.get("name"),
                                      "persona": (c.get("persona_text") or "")[:80]},
                            "intent": intent, "whys": whys[:3],
                            "closeness": close, "romance": romance,
                            "era": rt.era_of(content)}) or {}
        browser = [{"q": rt.dedash(str(x)[:48]), "at": ""}
                   for x in rt.as_str_list(out.get("searches"))][:6]
        drafts = [rt.dedash(str(x)[:80]) for x in rt.as_str_list(out.get("drafts"))][:3]
    except Exception:
        pass
    if not browser:
        # 确定性兜底: 素材本身就是人话, 搜索框化即可
        seeds = ([intent] if intent else []) + whys[:2]
        browser = [{"q": rt._t(content, f"{s}，怎么办", f"what to do about {s}"), "at": ""}
                   for s in seeds if s][:4] or \
                  [{"q": rt._t(content, "睡不着的时候人在想什么", "why can't I sleep"), "at": ""}]
    if not drafts and (romance >= 20 or close >= 40):
        drafts = [rt._t(content, "有句话打了又删。算了，见面再说。",
                        "Typed it, deleted it. Some things want saying face to face.")]
    pk["extras"] = {"browser": browser, "drafts": drafts}
    return pk["extras"]
