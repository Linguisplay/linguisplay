# -*- coding: utf-8 -*-
"""Backfill portraits for AUTHORED characters: the runtime ensurer only covered
generated cast, so an all-authored story (寂声疗养院) played faceless. For every
published story, any character with NO avatar_url gets the /scene/avatar/{cid}.jpg
convention stitched through all three layers (Story row → snapshots → runs' pinned
copies), then every missing file is rendered here, SERIALLY (DashScope drops
concurrent image tasks).

Usage: python backfill_avatars.py [--dry]
"""
import argparse
from pathlib import Path

from sqlalchemy.orm.attributes import flag_modified

from app.db import SessionLocal, init_db
from app.models import Run, Story, StorySnapshot

AV_DIR = Path(__file__).resolve().parent / "app" / "static" / "scene" / "avatar"


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


def _portrait_prompt(c: dict, world: str) -> str:
    # same recipe as runs._ensure_char_avatars so all faces share one look
    bits = "，".join(b for b in (c.get("name"), c.get("role") or "",
                                 (c.get("persona_text") or "")[:160]) if b)
    return (f"{bits}。世界背景：{world}。电影质感人物肖像，胸像特写，正面微侧，"
            "目光看向镜头外，写实风格，柔和的侧光，背景虚化，情绪克制内敛，"
            "高细节，胶片颗粒感")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="report only, change nothing")
    args = ap.parse_args()
    init_db()
    db = SessionLocal()
    to_render: dict[str, str] = {}   # cid → prompt, deduped across layers
    try:
        for s in db.query(Story).filter(Story.status == "published").all():
            world = ((s.world_long or "").strip().replace("\n", " "))[:120]
            chars = list(s.characters or [])
            row_changed = _fill({"characters": chars})
            if row_changed:
                s.characters = chars
                flag_modified(s, "characters")
                for cid, c in row_changed:
                    to_render[cid] = _portrait_prompt(c, world)
                print(f"《{s.title}》: {len(row_changed)} faceless → "
                      + "、".join(c.get("name", "?") for _, c in row_changed))
            for snap in db.query(StorySnapshot).filter(StorySnapshot.story_id == s.id).all():
                if snap.content and snap.content.get("story"):
                    got = _fill(snap.content["story"])
                    if got:
                        flag_modified(snap, "content")
                        for cid, c in got:
                            to_render.setdefault(cid, _portrait_prompt(c, world))
            for r in db.query(Run).filter(Run.story_id == s.id).all():
                if r.pinned_content and r.pinned_content.get("story"):
                    if _fill(r.pinned_content["story"]):
                        flag_modified(r, "pinned_content")
        if args.dry:
            db.rollback()
            print(f"dry run — would render {len(to_render)} portrait(s), nothing written")
            return
        db.commit()
        from app.engine.qwen import generate_image
        AV_DIR.mkdir(parents=True, exist_ok=True)
        done = 0
        for cid, prompt in to_render.items():
            p = AV_DIR / f"{cid}.jpg"
            if p.exists():
                done += 1
                continue
            img = generate_image(prompt, size="768*768")
            if img:
                p.write_bytes(img)
                done += 1
                print(f"  🖼 {cid}.jpg rendered")
            else:
                print(f"  ⚠ {cid} render failed — re-run to retry")
        print(f"portraits in place: {done}/{len(to_render)}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
