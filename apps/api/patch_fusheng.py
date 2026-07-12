# -*- coding: utf-8 -*-
"""One-off: promote the LIVE 《九龙城寨·浮生》 story row to the 最新版 authored form
(常驻班底/地点数据库/文风/vn_mode/画风圣经/成长阶梯) WITHOUT reseeding — the story id
survives, so links and existing runs keep working.

Single source of truth: the authored blocks live in seed_sandbox.py and are imported
here (never copy-pasted). Existing runs' pinned copies are deliberately NOT touched:
their conjured casts/emergent maps are their own worlds, and the vn flag is read from
the live story anyway (runs.py). Only NEW runs are born with the authored cast.

Run ON THE SERVER:
    cd /opt/linguisplay/apps/api && set -a && . .env && set +a && \
        ./.venv/bin/python patch_fusheng.py
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./dev.db")
os.environ.setdefault("JWT_SECRET", "dev")

from sqlalchemy.orm.attributes import flag_modified  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.models import Story, StorySnapshot  # noqa: E402
from app.routers.stories import _to_story  # noqa: E402
from seed_sandbox import SANDBOXES  # noqa: E402

TITLE = "九龙城寨·浮生"


def main() -> None:
    sb = next((x for x in SANDBOXES if x["title"] == TITLE), None)
    if not sb:
        raise SystemExit(f"seed_sandbox.py no longer defines {TITLE}")
    db = SessionLocal()
    try:
        s = db.query(Story).filter(Story.title == TITLE).first()
        if not s:
            raise SystemExit(f"story not found in DB: {TITLE}")

        # prose + authored world (full sync from the seed definition)
        s.one_liner = sb["one_liner"]
        s.synopsis = sb["synopsis"]
        s.world_long = sb["world_long"]
        s.world_facts = sb["world_facts"]
        s.relations_overview = sb["relations_overview"]
        s.trope_tags = sb["trope_tags"]
        s.style = sb.get("style")
        s.characters = sb.get("characters") or []
        s.locations = sb.get("locations") or []
        s.phone = sb.get("phone")

        # MERGE dicts so server-side patches already applied (e.g. plan_render) survive
        s.tuning = {**(s.tuning or {}), **sb["tuning"]}
        s.sandbox = {"enabled": True, "real_time": True,
                     **(s.sandbox or {}), **(sb.get("sandbox_extra") or {})}
        for col in ("characters", "locations", "tuning", "sandbox", "trope_tags", "phone"):
            flag_modified(s, col)
        db.flush()
        db.refresh(s)

        # publish a fresh snapshot so new runs pin the authored world
        last = (db.query(StorySnapshot).filter(StorySnapshot.story_id == s.id)
                .order_by(StorySnapshot.version.desc()).first())
        version = (last.version if last else 0) + 1
        content = {"story": _to_story(s).model_dump(), "secrets": []}
        content["story"]["version"] = version
        db.add(StorySnapshot(story_id=s.id, version=version, content=content))
        s.version = version
        s.status = "published"
        db.commit()
        print(f"✅ {TITLE} → v{version}  story_id={s.id}")
        print(f"   常驻 {len(s.characters)} 人 · 地点 {len(s.locations)} 处 · "
              f"vn_mode={s.tuning.get('vn_mode')} · progression={bool(s.sandbox.get('progression'))}")
        print("   （存量 run 的 pinned 世界未动；vn 旗按现行 story 生效）")
    finally:
        db.close()


if __name__ == "__main__":
    main()
