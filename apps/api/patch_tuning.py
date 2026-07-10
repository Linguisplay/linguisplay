# -*- coding: utf-8 -*-
"""Set ONE tuning knob through all three layers (Story row → snapshots → runs'
pinned copies) for a story by title — the standard 试点打法, generalized so每次
开关不用再写一个专用脚本.

Usage: python patch_tuning.py <剧本标题> <key> <value>
       python patch_tuning.py 末班车上的陌生人 vn_mode 1
"""
import sys

from sqlalchemy.orm.attributes import flag_modified

from app.db import SessionLocal, init_db
from app.models import Run, Story, StorySnapshot


def main() -> None:
    if len(sys.argv) != 4:
        print(__doc__)
        sys.exit(1)
    title, key, raw = sys.argv[1], sys.argv[2], sys.argv[3]
    try:
        value: object = int(raw)
    except ValueError:
        value = raw
    init_db()
    db = SessionLocal()
    try:
        stories = db.query(Story).filter(Story.title == title).all()
        for s in stories:
            tun = dict(s.tuning or {})
            tun[key] = value
            s.tuning = tun
            flag_modified(s, "tuning")
            n_snap = n_run = 0
            for snap in db.query(StorySnapshot).filter(StorySnapshot.story_id == s.id).all():
                st = (snap.content or {}).get("story")
                if st is not None:
                    st.setdefault("tuning", {})[key] = value
                    flag_modified(snap, "content")
                    n_snap += 1
            for r in db.query(Run).filter(Run.story_id == s.id).all():
                st = (r.pinned_content or {}).get("story")
                if st is not None:
                    st.setdefault("tuning", {})[key] = value
                    flag_modified(r, "pinned_content")
                    n_run += 1
            print(f"story {s.id[:8]}: tuning.{key}={value!r}, snapshots={n_snap}, runs={n_run}")
        db.commit()
        print("done" if stories else "story not found")
    finally:
        db.close()


if __name__ == "__main__":
    main()
