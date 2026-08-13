# -*- coding: utf-8 -*-
"""Backfill / re-render story art (portraits + location backdrops), SERIALLY
(DashScope drops concurrent image tasks).

What it covers:
- faceless characters → avatar_url convention stitched through Story row →
  snapshots → runs' pinned copies, then the portrait rendered;
- convention-URL characters whose FILE is missing (a failed render) → re-rendered;
- authored locations with no backdrop file → rendered with the story's own
  art direction (tuning.art_style rides every prompt).

Usage: python backfill_avatars.py [--dry] [--redo 剧本标题]
       --redo deletes that story's portrait + backdrop files first, so the whole
       book re-renders under its (new) art_style. Other stories are untouched.
"""
import argparse
from pathlib import Path

from sqlalchemy.orm.attributes import flag_modified

from app.db import SessionLocal, init_db
from app.engine import runtime
from app.models import Run, Story, StorySnapshot

_STATIC = Path(__file__).resolve().parent / "app" / "static" / "scene"
AV_DIR = _STATIC / "avatar"
BG_DIR = _STATIC / "bg"


def _fill(story_dict: dict) -> list[tuple[str, dict]]:
    """Point faceless chars at the convention path; return the (cid, char) changed."""
    changed = []
    for c in story_dict.get("characters") or []:
        cid, name = c.get("id"), c.get("name")
        if not cid or not name or (c.get("avatar_url") or "").strip():
            continue
        c["avatar_url"] = f"/scene/avatar/{cid}.jpg"
        changed.append((cid, c))
    return changed


def _portrait_prompt(c: dict, world: str, art: str) -> str:
    # same recipe as runs._ensure_char_avatars so all faces share one look
    bits = "，".join(b for b in (c.get("name"), c.get("role") or "",
                                 (c.get("persona_text") or "")[:160]) if b)
    return (f"{bits}。世界背景：{world}。电影质感人物肖像，胸像特写，正面微侧，"
            "目光看向镜头外，写实风格，柔和的侧光，背景虚化，情绪克制内敛，"
            "高细节，胶片颗粒感" + (f"。画面基调：{art}" if art else ""))


def _bg_prompt(loc: dict, world: str, art: str) -> str:
    # same recipe as runs._bg_prompt
    return (f"{world} 场景：{loc.get('name', '')}。{(loc.get('detail') or '')[:200]} "
            "电影感写实场景概念图，强烈氛围与光影，景深，电影级调色，横构图宽幅；"
            "空镜，画面里没有任何人物，没有文字、字幕或水印。"
            + (f"画面基调：{art}。" if art else ""))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="report only, change nothing")
    ap.add_argument("--redo", default="", help="story title whose art re-renders from scratch")
    # 🎯 只跑一本 (Yi 2026-08-12): 生图花真钱, 修一本不该顺手替另外十几本渲。
    ap.add_argument("--only", default="", help="只处理这一本剧本 (标题完整匹配)")
    args = ap.parse_args()
    init_db()
    db = SessionLocal()
    jobs: list[tuple[Path, str, str]] = []   # (path, prompt, size)
    try:
        for s in db.query(Story).filter(Story.status == "published").all():
            if args.only.strip() and s.title != args.only.strip():
                continue
            content = {"story": {"tuning": s.tuning or {}}}
            art = runtime.art_style_of(content)
            world = ((s.world_long or "").strip().replace("\n", " "))[:140]
            redo = bool(args.redo.strip()) and s.title == args.redo.strip()
            if redo and not args.dry:
                for c in s.characters or []:
                    (AV_DIR / f"{c.get('id')}.jpg").unlink(missing_ok=True)
                for l in s.locations or []:
                    (BG_DIR / f"{l.get('id')}.jpg").unlink(missing_ok=True)
                print(f"《{s.title}》: old art wiped for a fresh render")
            # — portraits: fill faceless urls across the three layers —
            chars = list(s.characters or [])
            row_changed = _fill({"characters": chars})
            if row_changed:
                s.characters = chars
                flag_modified(s, "characters")
                print(f"《{s.title}》: {len(row_changed)} faceless → "
                      + "、".join(c.get("name", "?") for _, c in row_changed))
            for snap in db.query(StorySnapshot).filter(StorySnapshot.story_id == s.id).all():
                if snap.content and snap.content.get("story"):
                    if _fill(snap.content["story"]):
                        flag_modified(snap, "content")
            for r in db.query(Run).filter(Run.story_id == s.id).all():
                if r.pinned_content and r.pinned_content.get("story"):
                    if _fill(r.pinned_content["story"]):
                        flag_modified(r, "pinned_content")
            # — render list: any convention-url portrait or authored backdrop missing on disk —
            for c in chars:
                cid = c.get("id")
                if cid and (c.get("avatar_url") or "") == f"/scene/avatar/{cid}.jpg" \
                        and not (AV_DIR / f"{cid}.jpg").exists():
                    jobs.append((AV_DIR / f"{cid}.jpg", _portrait_prompt(c, world, art), "768*768"))
            for l in s.locations or []:
                lid = l.get("id")
                if lid and not (BG_DIR / f"{lid}.jpg").exists():
                    jobs.append((BG_DIR / f"{lid}.jpg", _bg_prompt(l, world, art), "1280*720"))
        if args.dry:
            db.rollback()
            for p, _, size in jobs:
                print(f"  would render {p.name} ({size})")
            print(f"dry run — {len(jobs)} render job(s), nothing written")
            return
        db.commit()
        from app.engine.qwen import generate_image
        AV_DIR.mkdir(parents=True, exist_ok=True)
        BG_DIR.mkdir(parents=True, exist_ok=True)
        done = 0
        for p, prompt, size in jobs:
            if p.exists():
                done += 1
                continue
            img = generate_image(prompt, size=size)
            if img:
                p.write_bytes(img)
                done += 1
                print(f"  🖼 {p.name} rendered")
            else:
                print(f"  ⚠ {p.name} render failed — re-run to retry")
        print(f"art in place: {done}/{len(jobs)}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
