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
MAX_SOURCE_CHARS = 20000
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
    chapters = [{"i": i + 1, "summary": str(ch).strip()[:200]}
                for i, ch in enumerate((out.get("chapters") or [])[:5]) if str(ch).strip()]
    if not chapters:
        chapters = [{"i": 1, "summary": "故事的开端。"}]
    return {"characters": chars, "scenes": scenes,
            "protagonist_id": protagonist, "chapters": chapters}


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
            "enter": [], "exit": [],
            "cg": bool(b.get("cg")), "adult": bool(b.get("adult")),
            "fx": str(b.get("fx") or "").strip()[:12],
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
        opts.append({"text": text, "fx": fx, "beats": beats})
    if len(opts) < 2:
        return None
    # 数值必须动: a choice where no option gains anyone would make every ending
    # threshold unreachable — the engine backfills a deterministic +1.
    if fx_targets and not any(v > 0 for o in opts for v in o["fx"].values()):
        for j, o in enumerate(opts):
            o["fx"] = {fx_targets[j % len(fx_targets)]: 1}
    return {"id": f"c{ch}q{q}", "type": "choice", "options": opts}


def compile_chapter(llm, gal: dict[str, Any], ch_index: int,
                    prior_summary: str = "",
                    mature: bool = False) -> tuple[list[dict], str]:
    """编剧拍: one chapter → beats + choice points + a summary that feeds the NEXT
    chapter's 编译记忆 (so chapter N can never吃书 chapter N-1). 伪分支 doctrine:
    options move the affinity ledger, branch beats rejoin in-scene, the spine stays
    choice-agnostic — one compile serves every player."""
    chapter = gal["chapters"][ch_index - 1]
    total = len(gal["chapters"])
    char_ids = {c["id"] for c in gal["characters"]}
    scene_ids = {s["id"] for s in gal["scenes"]}
    targets = _fx_targets(gal)
    beats: list[dict] = []
    out: dict = {}
    n_beat = n_choice = 0
    # one measured retry: field-tested (HP build, DeepSeek) — the model can return a
    # clean chapter with ZERO choices despite the contract; a sharpened re-ask fixes it
    for attempt in (0, 1):
        out = llm.generate({
            "gal_compile": True,
            "source": (gal.get("source_text") or "")[:MAX_SOURCE_CHARS],
            "chapter": chapter, "chapter_count": total,
            "chapters_all": gal["chapters"],   # 全书章节表: each chapter knows its slice
            "characters": gal["characters"], "scenes": gal["scenes"],
            "protagonist_id": gal["protagonist_id"],
            "prior_summary": prior_summary[:600],       # 编译记忆
            "mature": mature,                            # 🔞 rides into the craft block
            "choice_retry": attempt > 0,                 # 上一把忘了选择点 → 点名重打
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
        # production contract shape: top-level "choices" with an insertion point —
        # uniform beats + a separate required array is what models actually honor
        for raw in (out.get("choices") or [])[:2]:
            if not isinstance(raw, dict):
                continue
            try:
                pos = int(raw.get("after"))
            except (TypeError, ValueError):
                pos = 0
            if pos < 1 or pos > n_beat:
                pos = max(1, round(n_beat * 0.6))   # bad anchor → 60% into the chapter
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
        if n_beat >= 8 and (n_choice > 0 or ch_index >= total):
            break
    if n_beat < 8:
        raise ValueError(f"第{ch_index}章编译失败：只产出 {n_beat} 拍")
    if n_choice == 0 and ch_index < total:
        # the final chapter may run straight into the endings fork; every other
        # chapter must offer the player a real hand on the wheel
        raise ValueError(f"第{ch_index}章编译失败：缺少选择点")
    for b in _walk_beats(beats):
        if not mature:      # 🔞防线在引擎不在模型: un-mature works carry no adult beat
            b["adult"] = False
        # 🎬 protagonist POV never shows the player's own sprite — the "你" has no face
        if b["who"] == gal["protagonist_id"]:
            b["who_face"] = None
    summary = (str(out.get("summary") or "").strip()[:200]
               or str(chapter.get("summary") or "")[:200])
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
    ending #1 belongs to the target route character behind their affinity
    threshold, ending #2 is the unconditional fallback; the model only writes."""
    vm = gal.get("values") or {}
    target = vm.get("target")
    tchar = next((c for c in gal["characters"] if c["id"] == target), None)
    out = llm.generate({
        "gal_endings": True,
        "source": (gal.get("source_text") or "")[:MAX_SOURCE_CHARS],
        "characters": gal["characters"], "scenes": gal["scenes"],
        "protagonist_id": gal["protagonist_id"],
        "target": ({"id": tchar["id"], "name": tchar["name"]} if tchar else None),
        "summary": full_summary[:600],
        "mature": mature,
    }) or {}
    char_ids = {c["id"] for c in gal["characters"]}
    scene_ids = {s["id"] for s in gal["scenes"]}
    endings: list[dict] = []
    for k, raw in enumerate((out.get("endings") or [])[:3]):
        if not isinstance(raw, dict):
            continue
        last_scene = gal["scenes"][0]["id"]
        beats: list[dict] = []
        for rb in (raw.get("beats") or [])[:20]:
            nb = _norm_beat(rb if isinstance(rb, dict) else {}, 0, 0, char_ids,
                            scene_ids, last_scene)
            if nb:
                nb["id"] = f"e{len(endings) + 1}b{len(beats) + 1:03d}"
                if not mature:
                    nb["adult"] = False
                if nb["who"] == gal["protagonist_id"]:
                    nb["who_face"] = None
                last_scene = nb["scene"]
                beats.append(nb)
        if len(beats) >= 6:
            endings.append({"id": f"e{len(endings) + 1}",
                            "title": (str(raw.get("title") or "").strip()[:12]
                                      or f"结局{len(endings) + 1}"),
                            "beats": beats})
    if len(endings) < 2:
        raise ValueError(f"结局编译失败：只产出 {len(endings)} 个可用结局")
    thr = (vm.get("threshold") or {}).get(target)
    endings[0]["cond"] = ({"char": target, "gte": thr} if target and thr
                          else {"default": True})
    for e in endings[1:]:
        e["cond"] = {"default": True}
    return endings


# ── 美术: 每表情单张肖像 (同角色固定 seed 保同脸) → rembg 抠底 ────────────────────
# 差分表已废: one-image-4-cells was a bet the image model kept losing — 海格 came
# back as a collage of overlapping heads, c3 as a bust dissolving into fog, and no
# cropping algorithm can fix a bad sheet. One portrait per expression, all four
# riding the SAME seed with a prompt that differs only in the expression phrase,
# keeps the face while making expression and framing per-image reliable.
_EXPR_FACE = {"常态": "平静自然的神情", "喜": "开心微笑的神情",
              "怒": "愤怒皱眉的神情", "哀": "悲伤低落的神情"}


def portrait_prompt(char: dict, world: str, art: str, expr: str) -> str:
    # style anchor rides FIRST — with seed held fixed, a trailing style hint was
    # weak enough that single portraits flipped photoreal↔anime between a
    # character's own expressions (实弹: 卢娜三张三个画风)
    lead = (art or "电影质感写实，真人照片般的质感")
    return (f"{lead}。单人半身立绘：{char.get('name')}，"
            f"{(char.get('looks') or '')[:160]}。"
            f"{_EXPR_FACE.get(expr, _EXPR_FACE['常态'])}。"
            "正面半身像，人物居中且完整（从头顶到腰部都在画面内，头顶上方留出空间），"
            f"画面里只有这一个人。世界背景：{world[:80]}。"
            "纯色极深背景（近黑），柔和主光，高细节，画面里没有任何文字或水印")


def portrait_negative(art: str) -> str:
    """Anti-style-flip: unless the work's art style asks for anime, forbid the
    styles the model kept drifting into mid-set."""
    if any(k in (art or "") for k in ("日漫", "动漫", "卡通", "二次元")):
        return "写实照片,真人实拍"
    return "动漫风格,卡通,二次元,3D渲染,手办,塑料质感"


def char_seed(work_id: str, cid: str) -> int:
    """Stable per-character seed: same face across the four expression calls,
    different faces across characters and works."""
    import hashlib
    h = hashlib.md5(f"{work_id}:{cid}".encode()).digest()
    return int.from_bytes(h[:4], "big") % (2 ** 31 - 1)


def debg(png_bytes: bytes) -> bytes:
    """rembg 抠底 → transparent PNG. Degrades to the original on any failure —
    a sprite with a dark backdrop still masks acceptably client-side."""
    try:
        from rembg import remove
        return remove(png_bytes)
    except Exception:
        return png_bytes


def bg_prompt(scene: dict, world: str, art: str) -> str:
    return (f"{world[:100]} 场景：{scene.get('name')}。{(scene.get('visual') or '')[:180]} "
            "手机竖屏视觉小说背景图，竖构图，电影感写实场景，强烈氛围与光影，景深；"
            "空镜，画面里没有任何人物，没有文字、字幕或水印。"
            + (f"画面基调：{art}。" if art else ""))


def cover_prompt(gal: dict, title: str, world: str, art: str) -> str:
    pro = next((c for c in gal["characters"] if c["id"] == gal["protagonist_id"]),
               gal["characters"][0])
    return (f"视觉小说封面插画，竖构图：{pro.get('name')}（{(pro.get('looks') or '')[:120]}）"
            f"的半身像立于画面中心偏下，上方留出标题空间。世界背景：{world[:80]}。"
            "电影质感，情绪张力，高细节，画面里没有任何文字"
            + (f"。画面基调：{art}" if art else ""))


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
                # 1. 识别
                gal["status"], gal["progress"] = "parsing", "正在识别角色与场景…"
                _save(s)
                gal.update(parse_story(llm, gal.get("source_text") or "", s.title or ""))
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
                beats, summ = compile_chapter(llm, gal, i,
                                              prior_summary="；".join(summaries)[-600:],
                                              mature=mature)
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
                got: list[str] = []
                for expr in EXPRESSIONS:
                    p = wdir / f"{c['id']}_{expr}.png"
                    if p.exists():
                        got.append(expr)
                        continue
                    gal["progress"] = (f"正在绘制立绘 {ci + 1}/{len(gal['characters'])}"
                                       f" · {expr}…")
                    _save(s)
                    img = generate_image(portrait_prompt(c, world, art, expr),
                                         size="720*1280", seed=seed,
                                         negative=portrait_negative(art))
                    if img:
                        p.write_bytes(debg(img))
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
                img = generate_image(bg_prompt(sc, world, art), size="720*1280")
                if img:
                    p.write_bytes(img)
                    man["bgs"].append(sc["id"])
                else:
                    man["missing"].append(f"bg:{sc['id']}")
            cp = wdir / "cover.jpg"
            if not cp.exists():
                img = generate_image(cover_prompt(gal, s.title or "", world, art),
                                     size="720*1280")
                if img:
                    cp.write_bytes(img)
            man["cover"] = cp.exists()
        gal["status"] = "ready"
        gal["progress"] = ("建造完成" if not (gal.get("manifest") or {}).get("missing")
                           else "建造完成（部分美术缺失，可重跑补齐）")
        _save(s)
    finally:
        db.close()
