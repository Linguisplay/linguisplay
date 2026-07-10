# -*- coding: utf-8 -*-
"""🎀 galgame 生成器 — the BUILD pipeline (docs/galgame-maker.md).

编译式播放: everything expensive happens HERE at build time; the player only turns
pages. This module owns build orchestration: 识别拍 (parse) → 编剧拍 (per-chapter
script compile, pacing contract lives in the qwen builder) → 美术拍 (四格差分表 →
crop → rembg 抠底, portrait scene backdrops, cover). LLM contracts ride
llm.generate({"gal_parse"|"gal_compile"}); MockLLM has deterministic twins.

Schema (fields reserved NOW per blueprint §11 — voice/cg/fx/adult/pov — so nothing
comes back later as a migration):

  story.gal = {
    "status": "queued"|"parsing"|"compiling"|"art"|"ready"|"failed",
    "progress": str,                 # human-readable current step
    "source_text": str,
    "protagonist_id": str,
    "characters": [{id,name,looks,personality,weight,voice}],
    "scenes": [{id,name,visual}],
    "chapters": [{i,summary}],
    "script": {pov_char_id: {"chapters": [[beat,...], ...]}},   # 多视角分层
    "manifest": {"sprites": {cid:[expr,...]}, "bgs": [sid,...], "cover": bool,
                 "missing": [...]},  # failed renders — re-runnable (backfill doctrine)
  }
  beat = {"id":"c1b007", "who":cid|None, "text":str, "expr":"常态|喜|怒|哀",
          "scene":sid, "bgm":mood, "enter":[cid], "exit":[cid],
          "cg":False, "adult":False, "fx":"", "voice":None}
"""
from __future__ import annotations

import io
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


def compile_chapter(llm, gal: dict[str, Any], ch_index: int,
                    prior_summary: str = "", choices: list | None = None) -> list[dict]:
    """编剧拍: one chapter → a beat sequence. 编译记忆 rides in (prior summary +
    choice history) so chapter N can never吃书 chapter N-1."""
    chapter = gal["chapters"][ch_index - 1]
    out = llm.generate({
        "gal_compile": True,
        "source": (gal.get("source_text") or "")[:MAX_SOURCE_CHARS],
        "chapter": chapter, "chapter_count": len(gal["chapters"]),
        "characters": gal["characters"], "scenes": gal["scenes"],
        "protagonist_id": gal["protagonist_id"],
        "prior_summary": prior_summary[:600],       # 编译记忆
        "choices": choices or [],                    # 选择史 (P1)
        "target_beats": TARGET_BEATS_PER_CHAPTER,
    }) or {}
    char_ids = {c["id"] for c in gal["characters"]}
    scene_ids = {s["id"] for s in gal["scenes"]}
    last_scene = gal["scenes"][0]["id"]
    beats: list[dict] = []
    for raw in out.get("beats") or []:
        nb = _norm_beat(raw if isinstance(raw, dict) else {}, ch_index,
                        len(beats) + 1, char_ids, scene_ids, last_scene)
        if nb:
            last_scene = nb["scene"]
            beats.append(nb)
    if len(beats) < 8:
        raise ValueError(f"第{ch_index}章编译失败：只产出 {len(beats)} 拍")
    # 🎬 protagonist POV never shows the player's own sprite — the "你" has no face
    for b in beats:
        if b["who"] == gal["protagonist_id"]:
            b["who_face"] = None
    return beats


# ── 美术: 一图四格差分表 → 裁切 → rembg 抠底 ─────────────────────────────────────
def sheet_prompt(char: dict, world: str, art: str) -> str:
    return (f"角色表情差分表：同一个人物在一张图里画四次，2x2 网格排列，四格分别是"
            f"【平静、微笑、愤怒、悲伤】四种表情，其余完全一致（同一张脸、同一发型、"
            f"同一服装、同一姿势的半身像）。人物：{char.get('name')}，"
            f"{(char.get('looks') or '')[:160]}。世界背景：{world[:80]}。"
            "每格人物完整不裁切，纯色极深背景（近黑），柔和主光，电影质感写实，高细节，"
            "画面里没有任何文字、编号或分隔线" + (f"。画面基调：{art}" if art else ""))


def crop_sheet(img_bytes: bytes) -> list[bytes]:
    """Split a 2×2 expression sheet into 4 PNGs (order: 常态/喜/怒/哀 = TL/TR/BL/BR)."""
    from PIL import Image
    im = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    w, h = im.size
    boxes = [(0, 0, w // 2, h // 2), (w // 2, 0, w, h // 2),
             (0, h // 2, w // 2, h), (w // 2, h // 2, w, h)]
    out = []
    for box in boxes:
        buf = io.BytesIO()
        im.crop(box).save(buf, format="PNG")
        out.append(buf.getvalue())
    return out


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
            if not (gal.get("script") or {}):
                # 1. 识别
                gal["status"], gal["progress"] = "parsing", "正在识别角色与场景…"
                _save(s)
                gal.update(parse_story(llm, gal.get("source_text") or "", s.title or ""))
                # 2. 编译 (P0: 第一章; later chapters compile after choices land)
                gal["status"], gal["progress"] = "compiling", "正在编写第一章…"
                _save(s)
                beats = compile_chapter(llm, gal, 1)
                gal["script"] = {gal["protagonist_id"]: {"chapters": [beats]}}
                gal["manifest"] = {"sprites": {}, "bgs": [], "cover": False, "missing": []}
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
                gal["progress"] = f"正在绘制立绘 {ci + 1}/{len(gal['characters'])}…"
                _save(s)
                if all((wdir / f"{c['id']}_{e}.png").exists() for e in EXPRESSIONS):
                    man["sprites"][c["id"]] = list(EXPRESSIONS)
                    continue
                img = generate_image(sheet_prompt(c, world, art), size="720*1280")
                if not img:
                    man["missing"].append(f"sprite:{c['id']}")
                    continue
                try:
                    pieces = crop_sheet(img)
                    for expr, piece in zip(EXPRESSIONS, pieces):
                        (wdir / f"{c['id']}_{expr}.png").write_bytes(debg(piece))
                    man["sprites"][c["id"]] = list(EXPRESSIONS)
                except Exception:
                    man["missing"].append(f"sprite:{c['id']}")
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
