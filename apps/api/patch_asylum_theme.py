# -*- coding: utf-8 -*-
"""One-shot hot-patch: the horror THEME PACK lands in existing asylum saves —
🧠 sanity ledger + 📜 house rules + 🎬 unfightable hunter + the sanity-break
ending, stitched through all three layers (Story row → snapshots → runs' pinned
copies). Imports the seed's constants so the content lives in ONE place."""
from sqlalchemy.orm.attributes import flag_modified

from app.db import SessionLocal, init_db
from app.models import Run, Story, StorySnapshot
from seed_asylum import ENDINGS, RULES, SANITY, THREAT, TITLE


def patch_story_dict(st: dict) -> None:
    st["sanity"] = SANITY
    st["rules"] = RULES
    st["threat"] = THREAT
    have = {e.get("id") for e in st.get("endings") or []}
    ends = [e for e in st.get("endings") or []]
    for e in ENDINGS:
        if e.get("id") not in have:
            ends.append(e)
    st["endings"] = ends
    wf = st.get("world_facts") or ""
    if "【他打不过】" not in wf and "屡犯会死——这栋楼里的死亡是真实的。" in wf:
        st["world_facts"] = wf.replace(
            "屡犯会死——这栋楼里的死亡是真实的。",
            "屡犯会死——这栋楼里的死亡是真实的。【他打不过】：攻击他等于把自己递过去，"
            "你能做的只有跑、躲、绕。")


def main() -> None:
    init_db()
    db = SessionLocal()
    try:
        stories = db.query(Story).filter(Story.title == TITLE).all()
        for s in stories:
            fields = {"sanity": SANITY, "rules": RULES, "threat": THREAT}
            for k, v in fields.items():
                setattr(s, k, v)
                flag_modified(s, k)
            d = {"endings": list(s.endings or []), "world_facts": s.world_facts or ""}
            patch_story_dict(d)
            s.endings = d["endings"]
            s.world_facts = d["world_facts"]
            flag_modified(s, "endings")
            n_snap = n_run = 0
            for snap in db.query(StorySnapshot).filter(StorySnapshot.story_id == s.id).all():
                if snap.content and snap.content.get("story"):
                    patch_story_dict(snap.content["story"])
                    flag_modified(snap, "content")
                    n_snap += 1
            for r in db.query(Run).filter(Run.story_id == s.id).all():
                if r.pinned_content and r.pinned_content.get("story"):
                    patch_story_dict(r.pinned_content["story"])
                    flag_modified(r, "pinned_content")
                    n_run += 1
            print(f"story {s.id[:8]}: theme pack patched, snapshots={n_snap}, runs={n_run}")
        db.commit()
        print("done" if stories else "story not found")
    finally:
        db.close()


if __name__ == "__main__":
    main()
