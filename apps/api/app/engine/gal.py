# -*- coding: utf-8 -*-
"""🎀 galgame 生成器 — the BUILD pipeline (docs/galgame-maker.md).

编译式播放: everything expensive happens HERE at build time; the player only turns
pages. This module owns build orchestration: 识别拍 (parse) → 编剧拍 (per-chapter
script compile, pacing contract lives in the qwen builder) → 美术拍 (每表情单张
肖像, 同角色固定 seed 保同脸, rembg 抠底; portrait scene backdrops, cover). LLM
contracts ride llm.generate({"gal_parse"|"gal_compile"|"gal_endings"}); MockLLM
has deterministic twins.

Schema (fields reserved NOW per blueprint §11 — voice/cg/fx/adult/pov — so nothing
comes back later as a migration):

  story.gal = {
    "status": "queued"|"parsing"|"compiling"|"art"|"ready"|"failed",
    "progress": str,                 # human-readable current step
    "source_text": str,
    "mature": bool,                  # 🔞 creator's adult toggle (P1)
    "protagonist_id": str,
    "characters": [{id,name,looks,personality,weight,route,voice}],
    "scenes": [{id,name,visual}],
    "chapters": [{i,summary}],
    "ch_summaries": [str,...],       # 编译记忆 chain: chapter N reads 1..N-1
    "script": {pov_char_id: {"chapters": [[beat|choice,...], ...]}},  # 多视角分层
    "values": {"routes":[cid], "max":{cid:n}, "threshold":{cid:n}, "target":cid},
    "endings": [{"id":"e1","title":str,"cond":{"char":cid,"gte":n}|{"default":True},
                 "beats":[beat,...]}],   # 真分歧只在结局 (伪分支 doctrine)
    "manifest": {"sprites": {cid:[expr,...]}, "bgs": [sid,...], "cover": bool,
                 "missing": [...]},  # failed renders — re-runnable (backfill doctrine)
  }
  beat = {"id":"c1b007", "who":cid|None, "text":str, "expr":"常态|喜|怒|哀",
          "scene":sid, "bgm":mood, "enter":[cid], "exit":[cid],
          "cg":False, "adult":False, "fx":"", "voice":None}
  choice = {"id":"c1q1", "type":"choice", "options":[
          {"text":str, "fx":{cid:±n}, "beats":[beat,...]}]}   # branch rejoins in-scene
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

EXPRESSIONS = ("常态", "喜", "怒", "哀")
GAL_DIR = Path(__file__).resolve().parents[1] / "static" / "scene" / "gal"

# P0 规格 (blueprint §1): keeps build cost and play length predictable
# (40k: 中篇经典整本可入 — 野菊の墓 34k; per-chapter slices keep compile prompts small)
MAX_SOURCE_CHARS = 40000
# 🖼 2026-07-13 Yi 定: 全站生图先用 Seedream (火山已充值; 阿里欠费 qwen-image/
# wanx 全瘫)。旧分工留档: qwen-image-plus 场景细节高一档但有手机壳陷阱(措辞
# 已避雷), wanx2.1-plus 立绘同脸 seed 体系——若阿里复活要回切, 只动这两行。
SCENE_MODEL = "doubao-seedream-4-0-250828"
FIGURE_MODEL = "doubao-seedream-4-0-250828"
_FRAME_NEG = ",手机,相框,画框,边框"   # qwen-image 的相框陷阱
TARGET_BEATS_PER_CHAPTER = (40, 60)


# ── normalization (the engine owns ids and shape; the model owns words) ──────────
def _norm_characters(raw: list, cap: int = 6) -> list[dict[str, Any]]:
    out = []
    for i, c in enumerate((raw or [])[:cap]):
        name = str(c.get("name") or "").strip()[:12]
        if not name:
            continue
        out.append({"id": f"c{i + 1}", "name": name,
                    "looks": str(c.get("looks") or "").strip()[:200],
                    "personality": str(c.get("personality") or "").strip()[:100],
                    "weight": max(1, min(5, int(c.get("weight") or 3))),
                    "route": bool(c.get("route")),   # 💘 可攻略 → the affinity ledger
                    "voice": None})   # 🔊 音色: reserved for the TTS build stage
    return out


def _norm_scenes(raw: list, cap: int = 8) -> list[dict[str, Any]]:
    out = []
    for i, s in enumerate((raw or [])[:cap]):
        name = str(s.get("name") or "").strip()[:16]
        if not name:
            continue
        out.append({"id": f"s{i + 1}", "name": name,
                    "visual": str(s.get("visual") or "").strip()[:220]})
    return out


def parse_story(llm, source: str, title: str) -> dict[str, Any]:
    """识别拍: characters (with looks for consistent art), scenes, protagonist,
    chapter skeleton. Raises ValueError on an unusable parse — the build FAILS
    loudly instead of compiling garbage."""
    out = llm.generate({"gal_parse": True, "source": source[:MAX_SOURCE_CHARS],
                        "title": title}) or {}
    chars = _norm_characters(out.get("characters") or [])
    scenes = _norm_scenes(out.get("scenes") or [])
    if not chars or not scenes:
        raise ValueError("识别失败：没有解析出角色或场景，换一段更具体的故事文本试试")
    by_name = {c["name"]: c["id"] for c in chars}
    protagonist = by_name.get(str(out.get("protagonist") or "").strip(), chars[0]["id"])
    chapters: list[dict] = []
    for ch in (out.get("chapters") or [])[:5]:
        if isinstance(ch, dict):
            summ = str(ch.get("summary") or "").strip()[:200]
            frm = str(ch.get("from") or "").strip()[:20]
        else:                                   # legacy string shape tolerated
            summ, frm = str(ch).strip()[:200], ""
        if summ:
            chapters.append({"i": len(chapters) + 1, "summary": summ, "from": frm})
    if not chapters:
        chapters = [{"i": 1, "summary": "故事的开端。", "from": ""}]
    return {"characters": chars, "scenes": scenes,
            "protagonist_id": protagonist, "chapters": chapters,
            # ✍️ 文风卡 (主线引擎移植: 每本书自带作者腔+忌清单, 文风问题调书不调引擎)
            "style": str(out.get("style") or "").strip()[:120]}


def needs_translation(text: str) -> bool:
    """外语底本检测: kana-heavy source must be normalized to Chinese BEFORE the
    pipeline (实弹《野菊之墓》: prompt rules + named retries couldn't stop the
    compiler from mirroring a Japanese slice — normalize at the boundary)."""
    kana = sum(1 for ch in text or "" if "぀" <= ch <= "ヿ")
    return kana > max(100, len(text or "") * 0.03)


def translate_source(llm, text: str) -> str:
    """转写拍: whole-book translation in paragraph-aligned chunks. A failed chunk
    falls back to its original text — the compile-side language guard will
    catch it loudly rather than silently shipping a mixed book."""
    chunks: list[str] = []
    buf = ""
    for para in (text or "").split("\n"):
        if len(buf) + len(para) > 3500 and buf:
            chunks.append(buf)
            buf = ""
        buf += para + "\n"
    if buf.strip():
        chunks.append(buf)
    out = []
    for c in chunks:
        r = llm.generate({"gal_translate": True, "text": c}) or {}
        out.append(str(r.get("text") or c))
    return "\n".join(s.strip("\n") for s in out)


def slice_source(source: str, chapters: list[dict]) -> list[str]:
    """物理切片: cut the source at the parse's from-quotes so the compiler can
    only SEE its own chapter's material — the definitive cure for greedy
    whole-book adaptation (实弹《余音》: every chapter compiled the entire arc
    to the finale; prompt rules and anchors alone did not hold). Falls back to
    an even split when the quotes don't locate."""
    n = len(chapters)
    if not n or not source:
        return [source] * n
    starts: list[int] = []
    pos = 0
    ok = True
    for ch in chapters:
        q = (ch.get("from") or "").strip()
        i = source.find(q[:12], pos) if q else -1
        if i < 0:
            ok = False
            break
        starts.append(i)
        pos = i + 1
    if not ok:
        step = max(1, len(source) // n)
        starts = [k * step for k in range(n)]
    starts[0] = 0
    return [source[starts[k]: (starts[k + 1] if k + 1 < n else len(source))]
            for k in range(n)]


def _norm_beat(b: dict, ch: int, idx: int, char_ids: set, scene_ids: set,
               last_scene: str) -> dict[str, Any] | None:
    text = str(b.get("text") or "").strip()[:120]
    if not text:
        return None
    who = str(b.get("who") or "").strip() or None
    if who not in char_ids:
        who = None                      # unknown speaker → narration (never invent)
    scene = str(b.get("scene") or "").strip()
    if scene not in scene_ids:
        scene = last_scene
    expr = str(b.get("expr") or "常态").strip()
    if expr not in EXPRESSIONS:
        expr = "常态"
    return {"id": f"c{ch}b{idx:03d}", "who": who, "text": text, "expr": expr,
            "scene": scene, "bgm": str(b.get("bgm") or "").strip()[:12],
            "date": str(b.get("date") or "").strip()[:16],   # 📅 时间跳跃戳
            "weather": str(b.get("weather") or "").strip()[:4],  # 🌦 天气层(雪|雨|樱|晴)
            "sfx": str(b.get("sfx") or "").strip()[:8],      # 🔉 拍级音效点
            "require": str(b.get("require") or "").strip()[:12],  # 🚩 flag 条件拍
            "enter": [], "exit": [],
            "cg": bool(b.get("cg")), "adult": bool(b.get("adult")),
            "fx": str(b.get("fx") or "").strip()[:12],       # 🎬 震动/白闪/黑闪
            "voice": None}              # 🔊 filled by the TTS build stage later


def _walk_beats(entries: list[dict]):
    """Every displayable beat, main line and branch alike (choice entries expand)."""
    for e in entries:
        if e.get("type") == "choice":
            for o in e["options"]:
                yield from o["beats"]
        else:
            yield e


def _fx_targets(gal: dict[str, Any]) -> list[str]:
    """Who may receive affinity points: 可攻略 characters; when the parse marked
    none, the heaviest non-protagonist characters stand in (the ledger must have
    someone to move for, or the ending fork is unreachable)."""
    pro = gal.get("protagonist_id")
    chars = [c for c in gal.get("characters") or [] if c["id"] != pro]
    routed = [c["id"] for c in chars if c.get("route")]
    if routed:
        return routed
    return [c["id"] for c in sorted(chars, key=lambda c: -c.get("weight", 3))][:3]


def _norm_choice(raw: dict, ch: int, q: int, char_ids: set, scene_ids: set,
                 last_scene: str, fx_targets: list[str]) -> dict[str, Any] | None:
    """选择点归一化: the engine owns ids, option count, fx bounds and the rejoin
    shape; the model owns the words. Unusable → None (the choice is dropped)."""
    opts: list[dict] = []
    for j, o in enumerate((raw.get("options") or [])[:3]):
        if not isinstance(o, dict):
            continue
        text = str(o.get("text") or "").strip()[:20]
        if not text:
            continue
        flag = str(o.get("flag") or "").strip()[:12]   # 🚩 该选项立下的事实标记
        fx: dict[str, int] = {}
        raw_fx = o.get("fx") if isinstance(o.get("fx"), dict) else {}
        for cid, d in raw_fx.items():
            if cid not in fx_targets:
                continue                # only ledgered characters take points
            try:
                fx[cid] = max(-2, min(3, int(d)))
            except (TypeError, ValueError):
                continue
        beats: list[dict] = []
        for i, rb in enumerate((o.get("beats") or [])[:6]):
            nb = _norm_beat(rb if isinstance(rb, dict) else {}, ch, 0, char_ids,
                            scene_ids, last_scene)
            if nb:
                nb["id"] = f"c{ch}q{q}o{len(opts) + 1}b{i + 1:02d}"
                beats.append(nb)
        opts.append({"text": text, "fx": fx, "flag": flag, "beats": beats})
    if len(opts) < 2:
        return None
    # 数值必须动: a choice where no option gains anyone would make every ending
    # threshold unreachable — the engine backfills a deterministic +1.
    if fx_targets and not any(v > 0 for o in opts for v in o["fx"].values()):
        for j, o in enumerate(opts):
            o["fx"] = {fx_targets[j % len(fx_targets)]: 1}
    return {"id": f"c{ch}q{q}", "type": "choice", "options": opts}


def _kana_heavy(text: str) -> bool:
    """外语守卫 (实弹《野菊之墓》: 日文底本让第1章整章写成了日文): kana in the
    prose means the compiler mirrored the source language instead of 转写中文."""
    return sum(1 for ch in text or "" if "぀" <= ch <= "ヿ") >= 3


def _echoes(opening: str, prior: str) -> bool:
    """开场回声检测 (实弹: 《余音》第2/5章从头重演贴告示初遇): does this chapter's
    first beat re-tell an earlier chapter's opening?"""
    import difflib
    a, b = (opening or "")[:40], (prior or "")[:40]
    if not a or not b:
        return False
    return a[:12] == b[:12] or difflib.SequenceMatcher(None, a, b).ratio() > 0.55


def compile_chapter(llm, gal: dict[str, Any], ch_index: int,
                    prior_summary: str = "",
                    mature: bool = False,
                    prev_tail: str = "",
                    prior_openings: list[str] | None = None) -> tuple[list[dict], str]:
    """编剧拍: one chapter → beats + choice points + a summary that feeds the NEXT
    chapter's 编译记忆 (so chapter N can never吃书 chapter N-1). 伪分支 doctrine:
    options move the affinity ledger, branch beats rejoin in-scene, the spine stays
    choice-agnostic — one compile serves every player. prev_tail is the previous
    chapter's closing prose — the concrete anchor that keeps chapter N from
    re-telling the book from the top (abstract rules alone didn't hold)."""
    chapter = gal["chapters"][ch_index - 1]
    total = len(gal["chapters"])
    char_ids = {c["id"] for c in gal["characters"]}
    scene_ids = {s["id"] for s in gal["scenes"]}
    targets = _fx_targets(gal)
    beats: list[dict] = []
    out: dict = {}
    n_beat = n_choice = 0
    # one measured retry with pointed reasons: field-tested — the model can return a
    # clean chapter with ZERO choices, or re-tell the opening; a named re-ask fixes it
    # 只给本章的原文切片 — the compiler cannot re-tell what it cannot see
    slices = slice_source((gal.get("source_text") or "")[:MAX_SOURCE_CHARS],
                          gal["chapters"])
    src = (slices[ch_index - 1] if ch_index <= len(slices) else "") \
        or (gal.get("source_text") or "")
    reasons: dict = {}
    for attempt in (0, 1):
        out = llm.generate({
            "gal_compile": True,
            "source": src[:MAX_SOURCE_CHARS],
            "chapter": chapter, "chapter_count": total,
            "chapters_all": gal["chapters"],   # 全书章节表: each chapter knows its slice
            "characters": gal["characters"], "scenes": gal["scenes"],
            "protagonist_id": gal["protagonist_id"],
            "prior_summary": prior_summary[:600],       # 编译记忆
            "prev_tail": prev_tail[-260:],               # 前章收尾锚 (depth anchor)
            "mature": mature,                            # 🔞 rides into the craft block
            "style": (gal.get("style") or "")[:120],     # ✍️ 文风卡贴住
            "knowledge": (gal.get("knowledge") or "")[:1800],  # 🔎 联网设定铁律
            "retry": reasons if attempt else {},         # 点名重打: 缺选择/回声
            "target_beats": TARGET_BEATS_PER_CHAPTER,
        }) or {}
        last_scene = gal["scenes"][0]["id"]
        beats, n_beat, n_choice = [], 0, 0
        for raw in out.get("beats") or []:
            if not isinstance(raw, dict):
                continue
            if raw.get("options"):       # inline choice shape — tolerated (belt)
                nc = _norm_choice(raw, ch_index, n_choice + 1, char_ids, scene_ids,
                                  last_scene, targets)
                if nc:
                    n_choice += 1
                    beats.append(nc)
                continue
            nb = _norm_beat(raw, ch_index, n_beat + 1, char_ids, scene_ids, last_scene)
            if nb:
                n_beat += 1
                last_scene = nb["scene"]
                beats.append(nb)
        # production contract shape: top-level "choices" with a TEXT anchor —
        # numeric beat indexes proved fragile (实弹《余音》: both ch2 choices'
        # numbers went stale after normalization and the 60% fallback dumped
        # 巧克力选项 onto 桐生凛进门). Text locates like slice_source does.
        used_pos: set = set()
        for raw in (out.get("choices") or [])[:2]:
            if not isinstance(raw, dict):
                continue
            normals = [e for e in beats if e.get("type") != "choice"]
            pos = 0
            key = str(raw.get("after_text") or "").strip()[:10]
            if key:
                for ordi, nb in enumerate(normals, 1):
                    if key in nb["text"]:
                        pos = ordi
                        break
            if not pos:
                try:
                    pos = int(raw.get("after"))
                except (TypeError, ValueError):
                    pos = 0
            if pos < 1 or pos > n_beat:
                slots = (0.55, 0.82, 0.3)           # spread stale anchors apart
                pos = max(1, round(n_beat * slots[min(n_choice, 2)]))
            if pos in used_pos:                     # never stack two choices
                pos = min(n_beat, pos + max(6, n_beat // 5))
            used_pos.add(pos)
            cnt, idx, scn = 0, len(beats), gal["scenes"][0]["id"]
            for i, e in enumerate(beats):
                if e.get("type") == "choice":
                    continue
                cnt += 1
                scn = e["scene"]
                if cnt == pos:
                    idx = i + 1
                    break
            nc = _norm_choice(raw, ch_index, n_choice + 1, char_ids, scene_ids,
                              scn, targets)
            if nc:
                n_choice += 1
                beats.insert(idx, nc)
        reasons = {}
        if n_choice == 0 and ch_index < total:
            # the final chapter may run straight into the endings fork; every other
            # chapter must offer the player a real hand on the wheel
            reasons["choices"] = True
        first = next((b["text"] for b in beats if b.get("type") != "choice"), "")
        if any(_echoes(first, po) for po in (prior_openings or [])):
            reasons["echo"] = True
        if sum(1 for b in _walk_beats(beats) if _kana_heavy(b["text"])) >= 3:
            reasons["lang"] = True
        if n_beat >= 8 and not reasons:
            break
    if n_beat < 8:
        raise ValueError(f"第{ch_index}章编译失败：只产出 {n_beat} 拍")
    if reasons.get("choices"):
        raise ValueError(f"第{ch_index}章编译失败：缺少选择点")
    if reasons.get("echo"):
        raise ValueError(f"第{ch_index}章编译失败：重述了前文的开场")
    if reasons.get("lang"):
        raise ValueError(f"第{ch_index}章编译失败：拍文字不是中文")
    for b in _walk_beats(beats):
        if not mature:      # 🔞防线在引擎不在模型: un-mature works carry no adult beat
            b["adult"] = False
        # 🎬 protagonist POV never shows the player's own sprite — the "你" has no face
        if b["who"] == gal["protagonist_id"]:
            b["who_face"] = None
    summary = (str(out.get("summary") or "").strip()[:200]
               or str(chapter.get("summary") or "")[:200])
    # 章题+过场引言 land on the chapter skeleton (the player's chapter card
    # reads them from there; build_work persists gal per chapter)
    chapter["title"] = str(out.get("title") or "").strip()[:12]
    chapter["lead"] = str(out.get("lead") or "").strip()[:40]
    chapter["date"] = str(out.get("date") or "").strip()[:16]   # 章节卡上的日期行
    return beats, summary


def values_meta(chapters: list[list[dict]], characters: list[dict],
                protagonist: str) -> dict[str, Any]:
    """数值账本元数据: per-character max attainable affinity across every choice,
    and the ending threshold at 60% of it — 真分歧只在结局, the threshold IS the
    fork. Recomputed from the compiled script, so it is always consistent."""
    mx: dict[str, int] = {}
    for ch in chapters:
        for e in ch:
            if e.get("type") != "choice":
                continue
            best: dict[str, int] = {}
            for o in e["options"]:
                for cid, d in (o.get("fx") or {}).items():
                    if d > 0:
                        best[cid] = max(best.get(cid, 0), d)
            for cid, d in best.items():
                mx[cid] = mx.get(cid, 0) + d
    weight = {c["id"]: c.get("weight", 3) for c in characters}
    routed = [c["id"] for c in characters
              if c.get("route") and c["id"] != protagonist and mx.get(c["id"], 0) > 0]
    cands = routed or [cid for cid in mx if cid != protagonist and mx[cid] > 0]
    cands.sort(key=lambda cid: (-mx.get(cid, 0), -weight.get(cid, 3)))
    return {"routes": cands, "max": {c: mx[c] for c in cands},
            "threshold": {c: max(1, round(mx[c] * 0.6)) for c in cands},
            "target": cands[0] if cands else None}


def compile_endings(llm, gal: dict[str, Any], full_summary: str = "",
                    mature: bool = False) -> list[dict]:
    """结局编译: the ONLY true fork (blueprint §3). The engine owns the structure —
    one good ending per route character (top 2 by attainable affinity) behind
    each threshold, plus the unconditional fallback; the model only writes."""
    vm = gal.get("values") or {}
    names = {c["id"]: c["name"] for c in gal["characters"]}
    targets = [cid for cid in (vm.get("routes") or [])
               if (vm.get("max") or {}).get(cid, 0) > 0][:2]
    out = llm.generate({
        "gal_endings": True,
        "source": (gal.get("source_text") or "")[:MAX_SOURCE_CHARS],
        "characters": gal["characters"], "scenes": gal["scenes"],
        "protagonist_id": gal["protagonist_id"],
        "targets": [{"id": t, "name": names.get(t, t)} for t in targets],
        "target": ({"id": targets[0], "name": names.get(targets[0])}
                   if targets else None),      # legacy single-target shape
        "summary": full_summary[:600],
        "style": (gal.get("style") or "")[:120],
        "knowledge": (gal.get("knowledge") or "")[:1800],
        "mature": mature,
    }) or {}
    char_ids = {c["id"] for c in gal["characters"]}
    scene_ids = {s["id"] for s in gal["scenes"]}
    routed: dict[str, dict] = {}
    fallback: dict | None = None
    for raw in (out.get("endings") or [])[:4]:
        if not isinstance(raw, dict):
            continue
        last_scene = gal["scenes"][0]["id"]
        k = len(routed) + (1 if fallback else 0)
        beats: list[dict] = []
        for rb in (raw.get("beats") or [])[:20]:
            nb = _norm_beat(rb if isinstance(rb, dict) else {}, 0, 0, char_ids,
                            scene_ids, last_scene)
            if nb:
                nb["id"] = f"e{k + 1}b{len(beats) + 1:03d}"
                if not mature:
                    nb["adult"] = False
                if nb["who"] == gal["protagonist_id"]:
                    nb["who_face"] = None
                last_scene = nb["scene"]
                beats.append(nb)
        if len(beats) < 6:
            continue
        e = {"id": f"e{k + 1}",
             "title": str(raw.get("title") or "").strip()[:12] or f"结局{k + 1}",
             "beats": beats}
        who = str(raw.get("char") or "").strip()
        if who in targets and who not in routed:
            routed[who] = e
        elif fallback is None:
            fallback = e
    endings: list[dict] = []
    thr = vm.get("threshold") or {}
    # 阈值高的线优先判定 (双线都达标时，走要求更高的那条)
    for cid in sorted(routed, key=lambda c: -thr.get(c, 0)):
        routed[cid]["cond"] = {"char": cid, "gte": thr.get(cid, 1)}
        endings.append(routed[cid])
    if fallback is not None:
        fallback["cond"] = {"default": True}
        endings.append(fallback)
    if len(endings) < 2 or not any((e["cond"] or {}).get("default") for e in endings):
        raise ValueError(f"结局编译失败：只产出 {len(endings)} 个可用结局")
    for i, e in enumerate(endings):        # ids follow final order
        e["id"] = f"e{i + 1}"
        for j, b in enumerate(e["beats"]):
            b["id"] = f"e{i + 1}b{j + 1:03d}"
    return endings


# ── 美术: 每表情单张肖像 (同角色固定 seed 保同脸) → rembg 抠底 ────────────────────
# 差分表已废: one-image-4-cells was a bet the image model kept losing — 海格 came
# back as a collage of overlapping heads, c3 as a bust dissolving into fog, and no
# cropping algorithm can fix a bad sheet. One portrait per expression, all four
# riding the SAME seed with a prompt that differs only in the expression phrase,
# keeps the face while making expression and framing per-image reliable.
_EXPR_FACE = {"常态": "平静自然的神情", "喜": "开心微笑的神情",
              "怒": "愤怒皱眉的神情", "哀": "悲伤低落的神情",
              # E-mote 丐版: 一张闭眼帧, 播放器随机切换 ≈ 眨眼 (立绘活的最大单点)
              "眨": "双眼轻轻闭合的瞬间的神情，除闭眼外与平静的神情完全一致"}
BLINK = "眨"
MOUTH = "口"        # 🗣 口パク: 说话时张嘴帧与常态交替
# 🎭 差分正解 (qwen-image-edit): 常态是唯一的 t2i 底图, 其余表情按指令改脸 —
# 独立重生成的"差分"连衣服都会换 (实弹: 老师的眨眼帧换了一套西装)
_EDIT_TAIL = ("。除面部表情之外，人物的姿势、服装、发型、身体、构图和画风"
              "必须保持与原图完全一致。")
_EDIT_FACE = {"喜": "把人物的表情改为开心微笑" + _EDIT_TAIL,
              "怒": "把人物的表情改为愤怒皱眉" + _EDIT_TAIL,
              "哀": "把人物的表情改为悲伤低落，眼神黯淡" + _EDIT_TAIL,
              "眨": "把人物的双眼改为完全闭合（自然眨眼的一瞬），眼睑合拢、"
                    "睫毛低垂" + _EDIT_TAIL,
              "口": "把人物的嘴改为说话时自然微张的口型（嘴唇张开一点，"
                    "像正在说话的一瞬）" + _EDIT_TAIL}


def portrait_prompt(char: dict, world: str, art: str, expr: str,
                    anon: bool = False) -> str:
    # style anchor rides FIRST — with seed held fixed, a trailing style hint was
    # weak enough that single portraits flipped photoreal↔anime between a
    # character's own expressions (实弹: 卢娜三张三个画风)
    lead = (art or "电影质感写实，真人照片般的质感")
    if expr == BLINK:
        # 实弹: 同 seed 的构图惯性会顶掉一句轻飘飘的表情短语——闭眼要前置重申
        face = ("闭着眼睛的人物：双眼完全闭合，眼睑合拢，长睫毛低垂，"
                "看不到任何瞳孔，像眨眼落下的那一瞬；除闭眼外与平静的神情完全一致")
    else:
        face = _EXPR_FACE.get(expr, _EXPR_FACE["常态"])
    # anon: 角色名撞知名 IP 会触发 IPInfringementSuspect (实弹: 「瑞克」被拒) —
    # 去名重试, 画像的主料本来就是外貌描述
    who = "" if anon else f"{char.get('name')}，"
    return (f"{lead}。单人半身立绘：{who}"
            f"{(char.get('looks') or '')[:160]}。"
            f"{face}。"
            "正面半身像，人物居中且完整（从头顶到腰部都在画面内，头顶上方留出空间），"
            f"画面里只有这一个人。世界背景：{world[:80]}。"
            "纯色极深背景（近黑），柔和主光，高细节，画面里没有任何文字或水印")


_QUALITY_NEG = "低质量,崩坏,变形,畸形,肢体错误,多余的手指,面部扭曲,画面模糊"


def portrait_negative(art: str) -> str:
    """Anti-style-flip + anti-崩坏: forbid the opposite style AND the classic
    generation failures (Yi 报障: 角色突然崩)."""
    if any(k in (art or "") for k in ("日漫", "动漫", "卡通", "二次元")):
        return "写实照片,真人实拍," + _QUALITY_NEG
    return "动漫风格,卡通,二次元,3D渲染,手办,塑料质感," + _QUALITY_NEG


ANIME_HINTS = ("动漫", "二次元", "赛璐璐", "水彩", "插画", "漫画", "国漫", "日漫", "卡通")


def is_anime_style(art: str) -> bool:
    """画风阵营判定的唯一词表 (审查实锤: 三处各一套且已分叉 = 同剧本两条管线反向)."""
    return any(k in (art or "") for k in ANIME_HINTS)


def safe_asset_key(key: str) -> str:
    """🔒 资产文件名消毒 (P0 路径穿越): 生成图落盘的 key/target_id 只许 中日文字、
    字母数字、下划线、连字符 — 挡掉 ../、斜杠、绝对路径。空/非法 → ValueError。
    (实弹审计: redraw/upload 用未消毒的 key 拼路径, 认证用户可删/覆盖他人的图,
    进程还跑在 root。) 保留中文因为表情后缀是「c2_喜」这种。"""
    import re
    k = str(key or "").strip()
    if not k or not re.fullmatch(r"[\w一-鿿-]+", k) or ".." in k:
        raise ValueError(f"非法资产名: {key!r}")
    return k


def char_seed(work_id: str, cid: str) -> int:
    """Stable per-character seed: same face across the four expression calls,
    different faces across characters and works."""
    import hashlib
    h = hashlib.md5(f"{work_id}:{cid}".encode()).digest()
    return int.from_bytes(h[:4], "big") % (2 ** 31 - 1)


def cg_prompt(gal: dict[str, Any], beat: dict, art: str) -> str:
    """CG 全屏插画 (blueprint §11🔴: the reward currency is the CG, not the
    sprite). 单人/空镜 doctrine: multi-person consistency is poor, so the CG
    frames the beat's speaker alone — or an atmosphere shot when the beat
    belongs to the narrator or the faceless protagonist."""
    scene = next((s for s in gal.get("scenes") or [] if s["id"] == beat.get("scene")), {})
    ch = next((c for c in gal.get("characters") or []
               if c["id"] == beat.get("who") and c["id"] != gal.get("protagonist_id")), None)
    subject = (f"画面主体：{ch['name']}，{(ch.get('looks') or '')[:100]}"
               if ch else "空镜或氛围构图，不出现清晰人脸")
    lead = (art or "电影质感写实，真人照片般的质感")
    return (f"{lead}。视觉小说全屏CG插画，竖构图，把这一刻的情绪拉满：{beat.get('text', '')[:80]}。"
            f"场景：{scene.get('name', '')}，{(scene.get('visual') or '')[:100]}。{subject}。"
            "电影感构图，强烈氛围光影，高细节，画面里没有任何文字或水印")


def cg_beats(gal: dict[str, Any]) -> list[dict]:
    """The CG ledger: FIRST cg-flagged main-line beat per chapter + per ending
    (每章≤1 is generation-side law — an over-tagging model costs nothing)."""
    pov = gal.get("protagonist_id")
    out: list[dict] = []
    for ch in ((gal.get("script") or {}).get(pov) or {}).get("chapters") or []:
        for b in ch:
            if b.get("type") != "choice" and b.get("cg"):
                out.append(b)
                break
    for e in gal.get("endings") or []:
        for b in e.get("beats") or []:
            if b.get("cg"):
                out.append(b)
                break
    return out


def edge_polish(png_bytes: bytes) -> bytes:
    """🪒 立牌边缘工艺 (Yi: 裁剪明显粗糙): rembg 的生边有 1px 光晕圈和锯齿 —
    alpha 收一圈 (MinFilter 3) 杀掉背景色镶边, 再轻羽化 (0.8px 高斯) 磨掉锯齿。
    Degrades to input on any failure."""
    import io as _io
    try:
        from PIL import Image, ImageFilter
        im = Image.open(_io.BytesIO(png_bytes))
        if im.mode != "RGBA":
            return png_bytes
        a = im.getchannel("A")
        a = a.filter(ImageFilter.MinFilter(3))
        a = a.filter(ImageFilter.GaussianBlur(0.8))
        im.putalpha(a)
        buf = _io.BytesIO()
        im.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return png_bytes


def debg(png_bytes: bytes) -> bytes:
    """rembg 抠底 → transparent PNG (边缘过一道 edge_polish 工艺).
    Degrades to the original on any failure — a sprite with a dark backdrop
    still masks acceptably client-side."""
    try:
        from rembg import remove
        return edge_polish(remove(png_bytes))
    except Exception:
        return png_bytes


# 图片必须瘦身 (实弹: 万相原图 0.9~1.7MB/张, 一本书 29MB, 跨洋一次换场 3MB+):
def trim_alpha(png_bytes: bytes, margin: float = 0.02) -> bytes:
    """裁掉透明边: 抠底后的立绘常常只占画面下 2/3, 上面一大块透明空白
    会让人物在台上显小。裁到 alpha 包围盒 (留一点呼吸边), 失败原样返回."""
    import io as _io

    from PIL import Image
    try:
        im = Image.open(_io.BytesIO(png_bytes))
        if im.mode != "RGBA":
            return png_bytes
        box = im.getchannel("A").getbbox()
        if not box:
            return png_bytes
        mx = int(im.width * margin)
        my = int(im.height * margin)
        box = (max(0, box[0] - mx), max(0, box[1] - my),
               min(im.width, box[2] + mx), min(im.height, box[3] + my))
        buf = _io.BytesIO()
        im.crop(box).save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return png_bytes


def shrink_jpg(data: bytes, quality: int = 82, max_side: int = 0) -> bytes:
    """Recompress a generated image to web weight; keeps the original if smaller.
    max_side>0 also downsamples the long edge — 手机 App 优先, 服务器出口带宽小,
    1.2MB 的沙盒背景在真机上实测要下载 36 秒。"""
    import io as _io

    from PIL import Image
    try:
        im = Image.open(_io.BytesIO(data))
        if im.mode in ("RGBA", "LA", "P"):   # 上传可能是 PNG/WebP — 平铺到白底
            im = im.convert("RGBA")
            base = Image.new("RGB", im.size, (255, 255, 255))
            base.paste(im, mask=im.split()[-1])
            im = base
        else:
            im = im.convert("RGB")
        resized = False
        if max_side and max(im.size) > max_side:
            im.thumbnail((max_side, max_side), Image.LANCZOS)
            resized = True
        buf = _io.BytesIO()
        im.save(buf, format="JPEG", quality=quality, optimize=True)
        out = buf.getvalue()
        return out if resized or len(out) < len(data) else data
    except Exception:
        return data


def to_webp(png: bytes, quality: int = 88) -> bytes:
    """Transparent sprite → WebP (photo-content PNG alpha ~1.6MB → ~0.2MB)."""
    import io as _io

    from PIL import Image
    try:
        im = Image.open(_io.BytesIO(png)).convert("RGBA")
        buf = _io.BytesIO()
        im.save(buf, format="WEBP", quality=quality, method=4)
        return buf.getvalue()
    except Exception:
        return png


def bg_prompt(scene: dict, world: str, art: str) -> str:
    # 画风统一实锤病根 (Yi 报障): 这里曾写死「电影感写实场景」而画风只在句尾——
    # 日漫立绘配写实背景一眼割裂。全部四类图统一: 画风引子第一句 + 反向提示词。
    lead = (art or "电影质感写实，强烈氛围与光影")
    return (f"{lead}。视觉小说场景背景插画，竖构图：{scene.get('name')}。"
            f"{(scene.get('visual') or '')[:180]} 世界背景：{world[:80]}。"
            "空镜，画面里没有任何人物也没有任何生物——人、兽、鸟、猫狗、龙、怪物"
            "一概不出现（这是等待角色登场的空舞台）；没有文字、字幕、水印或相框边框，"
            "景深，氛围光。")


def cover_prompt(gal: dict, title: str, world: str, art: str,
                 anon: bool = False) -> str:
    pro = next((c for c in gal["characters"] if c["id"] == gal["protagonist_id"]),
               gal["characters"][0])
    lead = (art or "电影质感，情绪张力")
    who = "" if anon else f"{pro.get('name')}"
    return (f"{lead}。视觉小说封面插画，竖构图：{who}"
            f"（{(pro.get('looks') or '')[:120]}）的半身像立于画面中心偏下，"
            f"上方留出标题空间。世界背景：{world[:80]}。"
            "高细节，画面里没有任何文字")


# ── ✍️ P2 创作者档位: B 智能拓写 / C 问卷 (blueprint §1) ─────────────────────────
def outline_story(llm, idea: str, n: int = 4) -> dict[str, Any]:
    """B档第一步: 梗概 → 章节大纲 (创作者确认/修改后才拓写 — 拓写跑偏整本报废,
    大纲层把关是蓝图定死的强制环节)."""
    out = llm.generate({"gal_outline": True, "idea": (idea or "")[:2000],
                        "n": max(2, min(6, n))}) or {}
    title = str(out.get("title") or "").strip()[:24]
    ol = [str(x).strip()[:200] for x in (out.get("outline") or [])[:6]
          if str(x).strip()]
    if len(ol) < 2:
        raise ValueError("大纲生成失败：换个更具体的想法试试")
    return {"title": title, "outline": ol}


def expand_work(story_id: str, session_factory) -> None:
    """B档第二步: 按确认过的大纲逐章拓写全文, 然后无缝进 A 档建造管线。
    拓写时每章的开头就是切片锚 (chapters_locked: parse 不再自行分章)."""
    from sqlalchemy.orm.attributes import flag_modified

    from ..models import Story
    from .llm import get_llm
    db = session_factory()
    db.expire_on_commit = False
    try:
        s = db.get(Story, story_id)
        if not s or not s.gal:
            return
        gal = s.gal
        llm = get_llm()
        idea = gal.get("idea") or ""
        outline = gal.get("outline") or []
        texts: list[str] = []
        chapters: list[dict] = []
        try:
            for i, summ in enumerate(outline, 1):
                gal["status"] = "expanding"
                gal["progress"] = f"正在拓写第 {i}/{len(outline)} 章…"
                s.gal = gal
                flag_modified(s, "gal")
                db.commit()
                out = llm.generate({"gal_expand": True, "idea": idea[:2000],
                                    "outline": outline, "index": i,
                                    "style": (gal.get("style") or "")[:120],
                                    "prior_tail": (texts[-1][-300:] if texts else "")}) or {}
                t = str(out.get("text") or "").strip()
                if len(t) < 200:
                    raise ValueError(f"第{i}章拓写失败（只有 {len(t)} 字）")
                texts.append(t)
                chapters.append({"i": i, "summary": str(summ)[:200], "from": t[:15]})
            gal["source_text"] = "\n\n".join(texts)[:MAX_SOURCE_CHARS]
            gal["chapters"] = chapters
            gal["chapters_locked"] = True    # parse 只补角色/场景, 分章以拓写为准
            gal["status"], gal["progress"] = "queued", "拓写完成，进入建造…"
        except Exception as e:
            gal["status"], gal["progress"] = "failed", f"拓写失败：{e}"
            s.gal = gal
            flag_modified(s, "gal")
            db.commit()
            return
        s.gal = gal
        flag_modified(s, "gal")
        db.commit()
    finally:
        db.close()
    build_work(story_id, session_factory)


def survey_idea(llm, answers: dict) -> str:
    """C档: 问卷 → 梗概 (并入 B 流程, 创作者可改梗概再生成大纲)."""
    out = llm.generate({"gal_survey": True, "answers": answers or {}}) or {}
    idea = str(out.get("idea") or "").strip()
    if len(idea) < 50:
        raise ValueError("梗概生成失败：问卷再填具体一点试试")
    return idea[:1200]


# ── 📋 剧本 linter: 机器能查的硬伤机器查 (零 LLM, 主线引擎逻辑严谨哲学的移植) ────
def gal_lint(gal: dict[str, Any]) -> list[dict]:
    """Static findings over the compiled book. warn = worth a look in 修订台;
    error = the book is broken for play (smoke gate fails on these)."""
    out: list[dict] = []
    pov = gal.get("protagonist_id")
    chs = ((gal.get("script") or {}).get(pov) or {}).get("chapters") or []
    sizes = [sum(1 for b in ch if b.get("type") != "choice") for ch in chs]
    if sizes:
        if min(sizes) < 12:
            out.append({"level": "warn",
                        "msg": f"第{sizes.index(min(sizes)) + 1}章太薄（{min(sizes)}拍），"
                               "可在修订台重编"})
        if max(sizes) > 3 * max(1, min(sizes)):
            out.append({"level": "warn",
                        "msg": f"章节篇幅失衡（{min(sizes)}~{max(sizes)}拍）"})
    for i, ch in enumerate(chs):
        last_expr: dict[str, str] = {}
        for b in ch:
            if b.get("type") == "choice":
                vals = [v for o in b["options"] for v in (o.get("fx") or {}).values()]
                if vals and (all(v > 0 for v in vals) or all(v <= 0 for v in vals)):
                    out.append({"level": "warn",
                                "msg": f"第{i + 1}章选择 {b['id']} 的选项好感全同向"
                                       "（假选择：选什么都一样）"})
                continue
            w = b.get("who")
            if w:
                prev = last_expr.get(w)
                pair = {prev, b.get("expr")}
                if prev and pair == {"怒", "喜"}:
                    out.append({"level": "warn",
                                "msg": f"第{i + 1}章 {b['id']}：角色表情怒↔喜直跳，"
                                       "情绪无过渡"})
                last_expr[w] = b.get("expr")
    vm = gal.get("values") or {}
    for e in gal.get("endings") or []:
        c = e.get("cond") or {}
        if c.get("char") and c.get("gte", 0) > (vm.get("max") or {}).get(c["char"], 0):
            out.append({"level": "error",
                        "msg": f"结局〈{e.get('title')}〉阈值 {c['gte']} 超过可得上限，"
                               "永远打不出来"})
    if gal.get("endings") and not any((e.get("cond") or {}).get("default")
                                      for e in gal["endings"]):
        out.append({"level": "error", "msg": "没有兜底结局：好感不达标时无路可走"})
    no_cg = [i + 1 for i, ch in enumerate(chs)
             if not any(b.get("cg") for b in ch if b.get("type") != "choice")]
    if no_cg:
        out.append({"level": "info", "msg": f"第{'、'.join(map(str, no_cg))}章没有CG拍"})
    # 🎙 人称守卫 (主线我-劫持检测的移植): 旁白应称主角为「你」
    import re as _re
    bad = sum(1 for ch in chs for b in ch
              if b.get("type") != "choice" and not b.get("who")
              and "我" in _re.sub(r"「[^」]*」|“[^”]*”", "", b.get("text") or ""))
    if bad >= 3:
        out.append({"level": "warn",
                    "msg": f"约 {bad} 个旁白拍疑似「我」视角——旁白应称主角为「你」，"
                           "可在修订台改字或重编"})
    return out


# ── 制作台修订 (blueprint §5: 修订能力是加速工具的灵魂) ──────────────────────────
def set_beat_text(gal: dict[str, Any], beat_id: str, text: str) -> bool:
    """改字零成本: locate a beat by id anywhere (main line, choice branches,
    endings) and replace its text. The script is data."""
    text = str(text or "").strip()[:120]
    if not text:
        return False
    pov = gal.get("protagonist_id")
    pools = [b for ch in ((gal.get("script") or {}).get(pov) or {}).get("chapters") or []
             for b in _walk_beats(ch)]
    pools += [b for e in gal.get("endings") or [] for b in e.get("beats") or []]
    for b in pools:
        if b.get("id") == beat_id:
            b["text"] = text
            return True
    return False


def rechapter_work(story_id: str, session_factory, index: int) -> None:
    """重编第 index 章 (1-based), keeping the confirmed skeleton: earlier chapters
    and endings stay, values + the ending threshold recompute, the CG ledger
    rebuilds (build_work backfills only what's missing on disk)."""
    from sqlalchemy.orm.attributes import flag_modified

    from ..models import Story
    from .llm import get_llm
    db = session_factory()
    db.expire_on_commit = False
    try:
        s = db.get(Story, story_id)
        if not s or not s.gal:
            return
        g = dict(s.gal)
        pov = g.get("protagonist_id")
        chs = ((g.get("script") or {}).get(pov) or {}).get("chapters") or []
        if not pov or not (1 <= index <= len(chs)):
            return
        g["status"], g["progress"] = "compiling", f"重编第 {index} 章…"
        s.gal = g
        flag_modified(s, "gal")
        db.commit()
        try:
            summaries = list(g.get("ch_summaries") or [])
            prior = "；".join(summaries[:index - 1])[-600:]
            tail, openings = "", []
            if index > 1:
                tail = "".join(b["text"] for b in chs[index - 2]
                               if b.get("type") != "choice")[-260:]
            openings = [next((b["text"] for b in ch if b.get("type") != "choice"), "")
                        for k, ch in enumerate(chs) if k != index - 1]
            beats, summ = compile_chapter(get_llm(), g, index, prior_summary=prior,
                                          mature=bool(g.get("mature")),
                                          prev_tail=tail, prior_openings=openings)
            chs[index - 1] = beats
            if index - 1 < len(summaries):
                summaries[index - 1] = summ
            g["script"][pov]["chapters"] = chs
            g["ch_summaries"] = summaries
            g["values"] = values_meta(chs, g["characters"], pov)
            t = g["values"].get("target")
            if g.get("endings") and t:
                g["endings"][0]["cond"] = {"char": t, "gte": g["values"]["threshold"][t]}
            g["manifest"]["cgs"] = []
            g["status"], g["progress"] = "art", "重建CG账本…"
        except Exception as e:
            g["status"], g["progress"] = "ready", f"重编失败，保留原章：{e}"
            s.gal = g
            flag_modified(s, "gal")
            db.commit()
            return
        s.gal = g
        flag_modified(s, "gal")
        db.commit()
    finally:
        db.close()
    build_work(story_id, session_factory)   # art untouched; new CG backfills


# ── build orchestration (runs on a background thread; commits progress per step) ──
def build_work(story_id: str, session_factory, render_art: bool = True) -> None:
    """The whole build. Each step persists gal.status/progress so the polling UI
    sees movement; art failures land in manifest.missing (re-runnable), never
    abort the build. A hard failure (parse/compile) marks status=failed."""
    from sqlalchemy.orm.attributes import flag_modified

    from ..models import Story
    from .llm import get_llm
    db = session_factory()
    db.expire_on_commit = False   # progress commits must not expire the live gal dict

    def _save(s):
        s.gal = gal
        flag_modified(s, "gal")
        db.commit()

    try:
        s = db.get(Story, story_id)
        if not s or not s.gal:
            return
        gal = s.gal
        llm = get_llm()
        art = ((s.tuning or {}).get("art_style") or "").strip()
        world = (gal.get("source_text") or "")[:200]
        try:
            # every step below is idempotent: a rebuild re-enters here and only the
            # missing pieces run (parse → chapters from where they stopped → endings)
            if not gal.get("protagonist_id"):
                # 0. 转写: foreign source → Chinese, once, before anything reads it
                if (needs_translation(gal.get("source_text") or "")
                        and not gal.get("source_original")):
                    gal["status"], gal["progress"] = "parsing", "正在把原文转写成中文…"
                    _save(s)
                    gal["source_original"] = gal["source_text"]
                    gal["source_text"] = translate_source(llm, gal["source_text"])
                    _save(s)
                # 1. 识别 (拓写档的分章以拓写为准, parse 只补角色/场景/主角)
                gal["status"], gal["progress"] = "parsing", "正在识别角色与场景…"
                _save(s)
                locked = gal.get("chapters") if gal.get("chapters_locked") else None
                preset_style = (gal.get("style") or "").strip()   # 拓写档创作者选的预设
                gal.update(parse_story(llm, gal.get("source_text") or "", s.title or ""))
                if locked:
                    gal["chapters"] = locked
                if preset_style:
                    gal["style"] = preset_style   # 创作者的选择优先于归纳
                # 🔎 智能搜索设定增强 (主线 generate_knowledge 移植, Tavily 打底):
                # 同人/IP 题材联网搜原作设定, 编译时立设定铁律
                if gal.get("enrich") and not gal.get("knowledge"):
                    gal["progress"] = "正在联网搜集背景设定…"
                    _save(s)
                    from .qwen import generate_knowledge
                    tops = sorted(
                        [c for c in gal["characters"] if c["id"] != gal["protagonist_id"]],
                        key=lambda c: (not c.get("route"), -c.get("weight", 3)))[:2]
                    parts = []
                    for c in tops:
                        k = generate_knowledge(
                            c["name"], f"{c.get('looks', '')} {c.get('personality', '')}",
                            (gal.get("source_text") or "")[:300])
                        if k:
                            parts.append(f"◆ {c['name']}\n{k}")
                    gal["knowledge"] = "\n\n".join(parts)[:1800]
            mature = bool(gal.get("mature"))
            pov = gal["protagonist_id"]
            # 2. 编译: all chapters, 编译记忆 chained through per-chapter summaries
            script = gal.get("script") or {pov: {"chapters": []}}
            chapters_done = script.get(pov, {}).get("chapters") or []
            summaries = list(gal.get("ch_summaries") or [])[:len(chapters_done)]
            total = len(gal["chapters"])
            for i in range(len(chapters_done) + 1, total + 1):
                gal["status"], gal["progress"] = "compiling", f"正在编写第 {i}/{total} 章…"
                _save(s)
                # anchors against the re-tell bug: every earlier opening (echo guard)
                # + the previous chapter's closing prose (the concrete handoff)
                openings = [next((b["text"] for b in ch if b.get("type") != "choice"), "")
                            for ch in chapters_done]
                tail = ""
                if chapters_done:
                    tail = "".join(b["text"] for b in chapters_done[-1]
                                   if b.get("type") != "choice")[-260:]
                beats, summ = compile_chapter(llm, gal, i,
                                              prior_summary="；".join(summaries)[-600:],
                                              mature=mature,
                                              prev_tail=tail,
                                              prior_openings=openings)
                chapters_done.append(beats)
                summaries.append(summ)
                script[pov] = {"chapters": chapters_done}
                gal["script"], gal["ch_summaries"] = script, summaries
                _save(s)   # per-chapter persist: a crash resumes, never restarts
            # 3. 数值账本 + 结局 (真分歧只在结局)
            gal["values"] = values_meta(chapters_done, gal["characters"], pov)
            if not gal.get("endings"):
                gal["status"], gal["progress"] = "compiling", "正在编写结局…"
                _save(s)
                gal["endings"] = compile_endings(llm, gal,
                                                 full_summary="；".join(summaries)[-600:],
                                                 mature=mature)
            # rebuild lands here directly: script kept, only missing art re-renders
            gal["manifest"] = gal.get("manifest") or {"sprites": {}, "bgs": [],
                                                      "cover": False, "missing": []}
            gal["manifest"]["missing"] = []
            gal["status"], gal["progress"] = "art", "正在绘制立绘与场景…"
            _save(s)
        except Exception as e:
            gal["status"], gal["progress"] = "failed", f"建造失败：{e}"
            _save(s)
            return
        # 3. 美术 (serial; failures recorded, never fatal)
        if render_art:
            from .qwen import generate_image
            wdir = GAL_DIR / story_id
            wdir.mkdir(parents=True, exist_ok=True)
            man = gal["manifest"]
            for ci, c in enumerate(gal["characters"]):
                if c["id"] == gal["protagonist_id"]:
                    continue   # 主角无立绘 — the "你" has no face on screen
                seed = char_seed(story_id, c["id"])
                base = wdir / f"{c['id']}_常态.webp"
                got: list[str] = []
                for expr in EXPRESSIONS + (BLINK, MOUTH):   # 常态 first — it is the base
                    p = wdir / f"{c['id']}_{expr}.webp"
                    if p.exists():
                        got.append(expr)
                        continue
                    gal["progress"] = (f"正在绘制立绘 {ci + 1}/{len(gal['characters'])}"
                                       f" · {expr}…")
                    _save(s)
                    from .qwen import edit_image
                    img = None
                    if expr != "常态" and base.exists():
                        # 差分=改脸不重画: body/framing stay pixel-consistent
                        img = edit_image(base.read_bytes(), _EDIT_FACE[expr])
                    if not img:                        # base 缺失/编辑失败 → t2i 兜底
                        neg = portrait_negative(art)
                        if expr == BLINK:
                            neg += ",睁开的眼睛,明亮的瞳孔,直视镜头的目光"
                        img = generate_image(portrait_prompt(c, world, art, expr),
                                             size="720*1280", seed=seed,
                                             model=FIGURE_MODEL, negative=neg)
                        if not img:   # 名字撞 IP 过滤 (IPInfringementSuspect) → 去名重试
                            img = generate_image(
                                portrait_prompt(c, world, art, expr, anon=True),
                                size="720*1280", seed=seed,
                                model=FIGURE_MODEL, negative=neg)
                    if img:
                        p.write_bytes(to_webp(debg(img)))
                        got.append(expr)
                    else:
                        man["missing"].append(f"sprite:{c['id']}:{expr}")
                man["sprites"][c["id"]] = got
            for si, sc in enumerate(gal["scenes"]):
                gal["progress"] = f"正在绘制场景 {si + 1}/{len(gal['scenes'])}…"
                _save(s)
                p = wdir / f"bg_{sc['id']}.jpg"
                if p.exists():
                    man["bgs"].append(sc["id"])
                    continue
                img = generate_image(bg_prompt(sc, world, art), size="720*1280",
                                     model=SCENE_MODEL,
                                     negative=portrait_negative(art) + _FRAME_NEG
                                     + "，人物，人影，动物，猫，狗，鸟，龙，兽，怪物，生物")
                if img:
                    p.write_bytes(shrink_jpg(img))
                    man["bgs"].append(sc["id"])
                else:
                    man["missing"].append(f"bg:{sc['id']}")
            cp = wdir / "cover.jpg"
            if not cp.exists():
                img = generate_image(cover_prompt(gal, s.title or "", world, art),
                                     size="720*1280", model=FIGURE_MODEL,
                                     negative=portrait_negative(art))
                if not img:   # IP 名过滤 → 去名重试
                    img = generate_image(cover_prompt(gal, s.title or "", world, art,
                                                      anon=True),
                                         size="720*1280", model=FIGURE_MODEL,
                                         negative=portrait_negative(art))
                if img:
                    cp.write_bytes(shrink_jpg(img))
            man["cover"] = cp.exists()
            # 4. CG 全屏插画 (奖励货币): first cg beat per chapter + per ending
            man["cgs"] = []
            todo = cg_beats(gal)
            for bi, b in enumerate(todo):
                p = wdir / f"cg_{b['id']}.jpg"
                if not p.exists():
                    gal["progress"] = f"正在绘制CG插画 {bi + 1}/{len(todo)}…"
                    _save(s)
                    img = generate_image(cg_prompt(gal, b, art), size="720*1280",
                                         model=SCENE_MODEL,
                                         negative=portrait_negative(art) + _FRAME_NEG)
                    if not img:   # IP 名过滤 → 去名(空镜)重试
                        anon_b = dict(b)
                        anon_b["who"] = None
                        img = generate_image(cg_prompt(gal, anon_b, art),
                                             size="720*1280", model=SCENE_MODEL,
                                             negative=portrait_negative(art) + _FRAME_NEG)
                    if img:
                        p.write_bytes(shrink_jpg(img))
                if p.exists():
                    man["cgs"].append(b["id"])
                else:
                    man["missing"].append(f"cg:{b['id']}")
        gal["lint"] = gal_lint(gal)     # 📋 体检报告挂在修订台
        gal["status"] = "ready"
        gal["progress"] = ("建造完成" if not (gal.get("manifest") or {}).get("missing")
                           else "建造完成（部分美术缺失，可重跑补齐）")
        _save(s)
    finally:
        db.close()
