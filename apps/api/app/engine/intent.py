# -*- coding: utf-8 -*-
"""玩家输入解析层 (input analysis).

Before the director runs, the ENGINE reads the player's raw line and decomposes it into
verified referents — who/where/what it mentions, each checked against live state — plus
a coarse verb classification. The result rides the prompt at depth-0 as a one-line
digest, so the model never has to guess whether 「短刃」 is in the player's pocket or
whether the person being addressed is even in the room.

Design rule: the digest only states what the engine can VERIFY (entity + its live
status + surface verb class). It never guesses intent or tone — a wrong guess would
mislead the model worse than no digest at all. Story-agnostic: everything is matched
against the run's own content/state.
"""
from __future__ import annotations

from typing import Any

# coarse verb taxonomy: surface classes only, high-precision keywords. Multiple may hit.
_VERB_CLASSES: list[tuple[str, str, tuple[str, ...]]] = [
    # (id, zh label, keywords)
    ("ask",      "询问/打听", ("问", "打听", "询问", "追问", "盘问", "why", "what", "how", "ask")),
    ("move",     "移动",      ("去", "回", "前往", "走到", "出发", "go to", "head to", "walk to")),
    ("seek",     "找人",      ("去找", "去见", "找", "见一见", "look for", "find ", "visit")),
    ("search",   "搜查",      ("翻", "搜", "查看", "检查", "翻查", "search", "examine", "inspect")),
    ("give",     "给予/出示",  ("给你", "递", "送", "拿给", "出示", "亮出", "give", "hand", "show")),
    ("trade",    "交易",      ("买", "卖", "换", "开个价", "多少钱", "buy", "sell", "trade")),
    ("attack",   "攻击/动手",  ("打", "揍", "砍", "劈", "踹", "动手", "攻击", "attack", "hit", "strike")),
    ("threaten", "威逼",      ("威胁", "吓唬", "警告你", "别怪我", "threaten", "warn you")),
    ("intimate", "亲近动作",   ("抱", "牵", "吻", "亲了", "摸了", "靠在", "hug", "kiss", "hold her", "hold him")),
    ("help",     "援手",      ("帮", "救", "扶", "包扎", "help", "save", "rescue")),
    ("flee",     "躲避/撤离",  ("逃", "跑路", "躲", "撤", "溜", "flee", "run away", "hide")),
    ("sneak",    "潜行/暗中",  ("偷偷", "悄悄", "潜", "暗中", "趁没人", "sneak", "quietly", "secretly")),
    ("promise",  "承诺/邀约",  ("我保证", "我答应", "约", "明天见", "改天", "promise", "i'll be there")),
]


def _match_name(name: str, text: str) -> bool:
    """A referent counts only on a real surface hit (full name, or 2+ char fragment)."""
    if not name:
        return False
    if name in text:
        return True
    low_n, low_t = name.lower(), text.lower()
    if low_n and low_n in low_t:
        return True
    # 中文名的后半截也算（「宁雪」→穆宁雪），太短的不算
    return len(name) >= 3 and name[1:] in text


def analyze(content: dict[str, Any], state: dict[str, Any], player_input: str,
            channel: str = "say") -> dict[str, Any]:
    """Decompose the player's line into engine-verified referents + verb classes.
    Imports runtime lazily (runtime imports us at module load)."""
    from . import runtime as rt

    text = (player_input or "").strip()
    out: dict[str, Any] = {"chars": [], "locations": [], "items": [],
                           "props": [], "verbs": [], "powers": [], "channel": channel}
    if not text:
        return out

    # ✨ 金手指 invocation: the declared power's NAME (the part before ：) shows up
    for p in state.get("powers") or []:
        nm = str(p).split("：", 1)[0].split(":", 1)[0].strip()
        if nm and nm in text:
            out["powers"].append({"name": nm})

    scene_ids = {c.get("id") for c in rt.scene_characters(content, state)}
    pcid = state.get("player_character_id")
    for c in rt._characters(content):
        if c.get("id") == pcid or not c.get("name"):
            continue
        if _match_name(c["name"], text):
            out["chars"].append({"name": c["name"], "present": c.get("id") in scene_ids,
                                 "dead": c.get("id") in rt._dead_ids(state)})

    cur = rt.current_location(content, state) or {}
    for loc in rt._locations(content):
        nm = loc.get("name") or ""
        if nm and nm != cur.get("name") and _match_name(nm, text):
            out["locations"].append({"name": nm,
                                     "known": rt.location_available(content, state, loc)})

    for it in state.get("inventory") or []:
        nm = it.get("name") or ""
        if nm and nm in text:
            out["items"].append({"name": nm, "held": True})

    for p in (cur.get("props") or []):
        nm = p.get("name") or ""
        if nm and nm in text:
            out["props"].append({"name": nm})

    low = text.lower()
    for vid, label, kws in _VERB_CLASSES:
        if any((k in text) if any("一" <= ch <= "鿿" for ch in k) else (k in low)
               for k in kws):
            out["verbs"].append(label)
    # combination rule: 「给/拿给 + 某个提到的人」 is giving/showing even without 给你
    if "给予/出示" not in out["verbs"] and out["chars"] \
            and any(f"给{c['name']}" in text or f"给 {c['name']}" in text
                    for c in out["chars"]):
        out["verbs"].append("给予/出示")
    return out


def digest(analysis: dict[str, Any], lang: str = "zh") -> str:
    """The one-line engine-verified digest that rides the prompt at depth-0.
    Empty when nothing was recognized (no noise for simple lines)."""
    a = analysis or {}
    bits: list[str] = []
    en = lang == "en"
    if a.get("chars"):
        ppl = "、".join(
            c["name"] + ("" if c.get("present") else ("(not here)" if en else "（不在场）"))
            + (("(dead)" if en else "（已死）") if c.get("dead") else "")
            for c in a["chars"][:3])
        bits.append(f"mentions: {ppl}" if en else f"提到的人：{ppl}")
    if a.get("locations"):
        locs = "、".join(
            l["name"] + ("" if l.get("known") else ("(unknown place)" if en else "（未知之地）"))
            for l in a["locations"][:2])
        bits.append(f"places: {locs}" if en else f"提到的地点：{locs}")
    if a.get("items"):
        its = "、".join(i["name"] for i in a["items"][:3])
        bits.append(f"carried items named: {its}" if en else f"提到的随身物（确在包里）：{its}")
    if a.get("props"):
        prs = "、".join(p["name"] for p in a["props"][:2])
        bits.append(f"fixtures here: {prs}" if en else f"提到的现场物件：{prs}")
    if a.get("powers"):
        pw = "、".join(p["name"] for p in a["powers"][:2])
        bits.append(f"INVOKES cheat power: {pw} — it MUST take full effect"
                    if en else f"动用金手指：{pw}——必须无条件完整生效")
    if a.get("verbs"):
        bits.append(("action type: " if en else "动作类别：") + "/".join(a["verbs"][:4]))
    if not bits:
        return ""
    head = ("[Player's line, engine-verified referents] "
            if en else "【玩家这句话的指涉·引擎已核实】")
    return head + ("; ".join(bits) if en else "；".join(bits))
