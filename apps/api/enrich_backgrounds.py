"""Generate an AI background image for each LOCATION of a story (通义万相 / DashScope),
and cache it as a static file the play UI loads by location id.

One image per place (not per turn) → cheap, consistent, no in-play latency. Idempotent:
skips a location whose image already exists (so re-running / re-seeding won't clobber or
re-spend). Pass --force to regenerate.

Run ON THE SERVER (needs DASHSCOPE_API_KEY in .env, reachable from China):
    cd /opt/linguisplay/apps/api && set -a && . .env && set +a && \
        ./.venv/bin/python enrich_backgrounds.py "九龙城寨·龙头"

Output: app/static/scene/bg/<location_id>.jpg  →  served at /scene/bg/<location_id>.jpg
(location ids already carry their own prefix, e.g. loc_alley → loc_alley.jpg)
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./dev.db")
os.environ.setdefault("JWT_SECRET", "dev")

from app.db import SessionLocal  # noqa: E402
from app.engine.gal import is_anime_style  # noqa: E402
from app.engine.qwen import generate_image  # noqa: E402
from app.models import Story, StorySnapshot  # noqa: E402

BG_DIR = Path(__file__).parent / "app" / "static" / "scene" / "bg"

# 底模: Seedream (火山方舟) — 阿里欠费后万相全瘫 (2026-07-13); 横构图 2K 档
BG_MODEL = "doubao-seedream-4-0-250828"
BG_SIZE = "1664*928"


def build_prompt(loc: dict, world: str, art: str) -> str:
    """A people-free establishing shot of the place, grounded in its authored fixtures +
    the story's world/era. Style-aware (art bible doctrine): an anime story gets anime
    scenery in ITS bible's tokens — 日漫立绘配写实背景一眼割裂; 写实 stays the old cinematic
    look. The bible rides FIRST (style-first prompts) so the era text can't drag the
    image photoreal."""
    name = (loc.get("name") or "").strip()
    detail = (loc.get("detail") or "").strip()
    era = (world or "").strip().replace("\n", " ")[:140]
    if is_anime_style(art):
        return (
            f"{art[:220]}。动画背景美术，场景空镜：{name}。{detail} "
            f"世界背景：{era}。横构图宽幅，画面里没有任何人物，没有文字、字幕或水印。"
        )
    return (
        f"{era} 场景：{name}。{detail} "
        "电影感写实场景概念图，强烈氛围与光影，景深，潮湿质感，霓虹与暖黄灯光交织，"
        "电影级调色，横构图宽幅；空镜，画面里没有任何人物，没有文字、字幕或水印。"
    )


def bg_negative(art: str) -> str:
    """Anti-style-flip (portrait_negative 的场景版): forbid the NEIGHBORING camp."""
    if is_anime_style(art):
        return "写实照片,真人实拍,照片质感,3D渲染"
    return "动漫风格,卡通,二次元,插画"


def locations_of(db, title: str) -> tuple[list[dict], str, str]:
    story = db.query(Story).filter(Story.title == title).first()
    if not story:
        return [], "", ""
    snap = (
        db.query(StorySnapshot)
        .filter(StorySnapshot.story_id == story.id)
        .order_by(StorySnapshot.version.desc())
        .first()
    )
    content_story = (snap.content.get("story") if snap else None) or {}
    locs = content_story.get("locations") or story.locations or []
    world = content_story.get("world_long") or story.world_long or ""
    art = str(((content_story.get("tuning") or story.tuning or {}) or {})
              .get("art_style") or "")
    return locs, world, art


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    force = "--force" in sys.argv
    title = args[0] if args else "九龙城寨·龙头"

    db = SessionLocal()
    try:
        locs, world, art = locations_of(db, title)
        if not locs:
            print(f"no locations found for 《{title}》")
            return
        BG_DIR.mkdir(parents=True, exist_ok=True)
        camp = "anime" if is_anime_style(art) else "写实"
        print(f"《{title}》 has {len(locs)} locations → generating backgrounds… (style: {camp})")
        for loc in locs:
            lid = loc.get("id")
            if not lid:
                continue
            out = BG_DIR / f"{lid}.jpg"  # lid already carries its own prefix (e.g. loc_alley)
            if out.exists() and not force:
                print(f"  skip {lid} ({loc.get('name')}) — already exists")
                continue
            print(f"  generating {lid} ({loc.get('name')})… ", end="", flush=True)
            data = generate_image(build_prompt(loc, world, art), size=BG_SIZE,
                                  model=BG_MODEL, negative=bg_negative(art))
            if data:
                out.write_bytes(data)
                print(f"OK ({len(data)//1024} KB)")
            else:
                print("FAILED (no image returned)")
    finally:
        db.close()


if __name__ == "__main__":
    main()
