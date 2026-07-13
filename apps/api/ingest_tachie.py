# -*- coding: utf-8 -*-
"""Ingest PRE-APPROVED sprite images for a story's characters (验收图直接上线).

enrich_tachie generates on the server and hopes; this takes images that were
already generated and eyeballed elsewhere (本地验收流程) and runs ONLY the
publishing half: ingest_upload (透底立绘 + 方形头像 + 改脸源图, 旧表情差分
作废) + avatar_url wiring into the Story row and its latest snapshot.
No LLM/image API calls — deterministic, costs nothing, ships exactly the
approved pixels.

    ingest_tachie.py "九龙城寨·浮生" kf_adai=/root/drop/adai.jpg kf_achoi=/root/drop/achoi.jpg
"""
import os
import sys

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./dev.db")
os.environ.setdefault("JWT_SECRET", "dev")

from sqlalchemy.orm.attributes import flag_modified  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.engine.sprites import ingest_upload  # noqa: E402
from app.models import Story, StorySnapshot  # noqa: E402


def main() -> None:
    args = sys.argv[1:]
    if len(args) < 2 or "=" not in args[1]:
        raise SystemExit(__doc__)
    title = args[0]
    pairs = [a.split("=", 1) for a in args[1:] if "=" in a]
    db = SessionLocal()
    try:
        s = db.query(Story).filter(Story.title == title).first()
        if not s:
            raise SystemExit(f"story not found: {title}")
        chars = list(s.characters or [])
        by_id = {c.get("id"): c for c in chars}
        changed = False
        for cid, path in pairs:
            if cid not in by_id:
                print(f"  skip {cid} — not in 《{title}》 cast")
                continue
            data = open(path, "rb").read()
            ingest_upload(cid, data)
            url = f"/scene/avatar/{cid}.jpg"
            if by_id[cid].get("avatar_url") != url:
                by_id[cid]["avatar_url"] = url
            changed = True
            print(f"  ingested {by_id[cid].get('name')} ({cid}) ← {path} ({len(data)//1024} KB)")
        if changed:
            s.characters = chars
            flag_modified(s, "characters")
            snap = (db.query(StorySnapshot).filter(StorySnapshot.story_id == s.id)
                    .order_by(StorySnapshot.version.desc()).first())
            if snap and snap.content:
                content = dict(snap.content)
                snap_chars = ((content.get("story") or {}).get("characters")) or []
                for sc in snap_chars:
                    src = by_id.get(sc.get("id"))
                    if src and src.get("avatar_url"):
                        sc["avatar_url"] = src["avatar_url"]
                snap.content = content
                flag_modified(snap, "content")
            db.commit()
            print("✅ sprites live + avatar_url wired into story + latest snapshot")
    finally:
        db.close()


if __name__ == "__main__":
    main()
