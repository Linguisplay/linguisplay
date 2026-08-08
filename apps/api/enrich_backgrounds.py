"""Generate an AI background image for each LOCATION of a story,
and cache it as a static file the play UI loads by location id.

One image per place (not per turn) → cheap, consistent, no in-play latency. Idempotent:
skips a location whose image already exists (so re-running / re-seeding won't clobber or
re-spend). Pass --force to regenerate.

Prompts/negatives/seed come from the RUNTIME pipeline (runs._bg_prompt 一家): this
script used to keep its own weaker wording, and 樱见坂 2026-08-08 实弹证明了后果 —
没有空镜铁律压轴 + 负词不挡人物动物, 神社和游戏厅的背景里直接画进了一个女孩。
背景铁律的教训 (runs.py): 正向条款会被地点 detail 里的描写顶翻, 负词必须同时压阵。

Run ON THE SERVER (needs the image API key in .env, reachable from China):
    cd /opt/linguisplay/apps/api && set -a && . .env && set +a && \
        ./.venv/bin/python enrich_backgrounds.py "九龙城寨·龙头"

Output: app/static/scene/bg/<location_id>.jpg  →  served at /scene/bg/<location_id>.jpg
(location ids already carry their own prefix, e.g. loc_alley → loc_alley.jpg)
"""

import os
import sys

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./dev.db")
os.environ.setdefault("JWT_SECRET", "dev")

from app.db import SessionLocal  # noqa: E402
from app.engine.gal import shrink_jpg  # noqa: E402
from app.engine.qwen import generate_image  # noqa: E402
from app.models import Story, StorySnapshot  # noqa: E402

# 高清出生档 (运行时补图是 1280*720; 文件在则运行时永不覆写, 初生用 2K 档无碍)
BG_SIZE = "1664*928"


def content_of(db, title: str) -> dict:
    """story content dict, runtime-shaped: 快照优先, 表兜底 (同 locations_of 旧约)."""
    story = db.query(Story).filter(Story.title == title).first()
    if not story:
        return {}
    snap = (
        db.query(StorySnapshot)
        .filter(StorySnapshot.story_id == story.id)
        .order_by(StorySnapshot.version.desc())
        .first()
    )
    content_story = (snap.content.get("story") if snap else None) or {}
    return {"story": {
        "id": story.id, "title": story.title,
        "world_long": content_story.get("world_long") or story.world_long or "",
        "world_facts": content_story.get("world_facts") or story.world_facts or "",
        "tuning": content_story.get("tuning") or story.tuning or {},
        "locations": content_story.get("locations") or story.locations or [],
    }}


def main() -> None:
    from app.routers.runs import _BG_DIR, _bg_negative, _bg_prompt, _bg_seed

    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    force = "--force" in sys.argv
    title = args[0] if args else "九龙城寨·龙头"

    db = SessionLocal()
    try:
        content = content_of(db, title)
        locs = ((content.get("story") or {}).get("locations")) or []
        if not locs:
            print(f"no locations found for 《{title}》")
            return
        _BG_DIR.mkdir(parents=True, exist_ok=True)
        seed = _bg_seed(content)
        neg = _bg_negative(content)
        print(f"《{title}》 has {len(locs)} locations → generating backgrounds…")
        for loc in locs:
            lid = loc.get("id")
            if not lid:
                continue
            out = _BG_DIR / f"{lid}.jpg"  # lid already carries its own prefix (e.g. loc_alley)
            if out.exists() and not force:
                print(f"  skip {lid} ({loc.get('name')}) — already exists")
                continue
            print(f"  generating {lid} ({loc.get('name')})… ", end="", flush=True)
            data = generate_image(_bg_prompt(content, loc), size=BG_SIZE,
                                  negative=neg, seed=seed)
            if data:
                data = shrink_jpg(data, max_side=1600)   # 出生即瘦 (36s 加载实弹教训)
                out.write_bytes(data)
                print(f"OK ({len(data)//1024} KB)")
            else:
                print("FAILED (no image returned)")
    finally:
        db.close()


if __name__ == "__main__":
    main()
