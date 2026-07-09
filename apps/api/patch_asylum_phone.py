# -*- coding: utf-8 -*-
"""One-shot hot-patch: turn the asylum's phone ON (Yi's call) WITHOUT re-seeding —
existing saves survive. The change is stitched through all three layers (Story row →
snapshots → every run's pinned copy), the same 打法 as the plan-render pilot. The
no-signal prose is harmonized too: 外线打不通（隔绝保住），楼内互发消息（管线打开）—
otherwise the director keeps narrating a dead phone the engine now answers on."""
from sqlalchemy.orm.attributes import flag_modified

from app.db import SessionLocal, init_db
from app.models import Run, Story, StorySnapshot

TITLE = "寂声疗养院"
SWAPS = [
    ("夜间断网无信号，全程没有手机可用。",
     "夜间全楼锁死。手机拨不出外线、报不了警——信号被群山困在院里；但楼内的人彼此发得出消息。"),
    ("防火门在身后自锁，手机没有信号。", "防火门在身后自锁，手机拨不出外线。"),
    ("现在门锁死了，手机没信号，这栋楼成了你的整个世界。",
     "现在门锁死了，外线打不通，这栋楼成了你的整个世界。"),
    ("手机没有信号。", "手机还亮着，信号格是满的——却拨不出这座山。"),
]


def _swap(s: str | None) -> str | None:
    for a, b in SWAPS:
        if s and a in s:
            s = s.replace(a, b)
    return s


def patch_story_dict(st: dict) -> None:
    st["phone"] = {"enabled": True}
    st["world_facts"] = _swap(st.get("world_facts"))
    st["synopsis"] = _swap(st.get("synopsis"))
    for c in st.get("characters") or []:
        if c.get("agenda"):
            c["agenda"] = _swap(c["agenda"])
    for a in st.get("acts") or []:
        for e in a.get("events") or []:
            if e.get("what_happens"):
                e["what_happens"] = _swap(e["what_happens"])


def main() -> None:
    init_db()
    db = SessionLocal()
    try:
        stories = db.query(Story).filter(Story.title == TITLE).all()
        for s in stories:
            s.phone = {"enabled": True}
            s.world_facts = _swap(s.world_facts)
            s.synopsis = _swap(s.synopsis)
            chars = list(s.characters or [])
            for c in chars:
                if c.get("agenda"):
                    c["agenda"] = _swap(c["agenda"])
            s.characters = chars
            acts = list(s.acts or [])
            for a in acts:
                for e in a.get("events") or []:
                    if e.get("what_happens"):
                        e["what_happens"] = _swap(e["what_happens"])
            s.acts = acts
            for col in ("characters", "acts", "phone"):
                flag_modified(s, col)
            n_snap = 0
            for snap in db.query(StorySnapshot).filter(StorySnapshot.story_id == s.id).all():
                if snap.content and snap.content.get("story"):
                    patch_story_dict(snap.content["story"])
                    flag_modified(snap, "content")
                    n_snap += 1
            n_run = 0
            for r in db.query(Run).filter(Run.story_id == s.id).all():
                if r.pinned_content and r.pinned_content.get("story"):
                    patch_story_dict(r.pinned_content["story"])
                    flag_modified(r, "pinned_content")
                    n_run += 1
            print(f"story {s.id[:8]}: patched, snapshots={n_snap}, runs={n_run}")
        db.commit()
        print("done" if stories else "story not found")
    finally:
        db.close()


if __name__ == "__main__":
    main()
