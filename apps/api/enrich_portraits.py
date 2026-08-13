"""Generate an AI portrait for each CHARACTER of a story (通义万相 / DashScope) and
wire it into `avatar_url`, so the cast bar and 档案卡 show a face instead of a letter.

One portrait per character, unified art direction. Idempotent: skips characters whose
image file already exists (--force regenerates). Updates the story AND its latest
published snapshot so live runs pick the urls up on their next pin.

Run ON THE SERVER (needs DASHSCOPE_API_KEY in .env):
    cd /opt/linguisplay/apps/api && set -a && . .env && set +a && \
        ./.venv/bin/python enrich_portraits.py "九龙城寨·龙头"

Output: app/static/scene/avatar/<char_id>.jpg → served at /scene/avatar/<char_id>.jpg
NOTE: files are keyed by character id (stable across re-seeds, same convention as
location backgrounds) — id collisions across stories would overwrite; keep seed ids unique.
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./dev.db")
os.environ.setdefault("JWT_SECRET", "dev")

from sqlalchemy.orm.attributes import flag_modified  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.engine.qwen import generate_image  # noqa: E402
from app.models import Story, StorySnapshot  # noqa: E402

from app.engine import ipface  # noqa: E402

AV_DIR = Path(__file__).parent / "app" / "static" / "scene" / "avatar"

from app.engine.sprites import PORTRAIT_FRAME  # noqa: E402

# 同人管线的正向条款和运行时不同 (先钉「这是谁」, 见 build_prompt), 但**取景共用**
# 那一句 —— 否则同一个人在不同入口画出来构图对不上 (2026-08-13 配方漂移教训)
STYLE = f"电影质感{PORTRAIT_FRAME}，写实风格，高细节，胶片颗粒感"


def build_prompt(c: dict, world: str, ip: str = "") -> str:
    # 🎭 同人角色先钉「这是谁」(经典形象), 再让性格描述补细节 —— 否则画出来
    # 是个泛泛的少年, 玩家一眼认不出是唐三还是别人 (Yi 2026-07-28)
    canon = ipface.canon_clause(ip, c.get("name") or "", c.get("knowledge"))
    look = (c.get("looks") or "").strip()      # 搜来的经典外貌优先
    bits = [c.get("name") or "", c.get("role") or "",
            look or (c.get("persona_text") or "")[:160]]
    who = "，".join(b for b in bits if b)
    return f"{canon}{who}。世界背景：{(world or '')[:120]}。{STYLE}"


def main() -> None:
    title = next((a for a in sys.argv[1:] if not a.startswith("-")), None)
    force = "--force" in sys.argv
    if not title:
        print("usage: python enrich_portraits.py <story title> [--force]")
        sys.exit(1)
    AV_DIR.mkdir(parents=True, exist_ok=True)
    db = SessionLocal()
    try:
        s = db.query(Story).filter(Story.title == title).first()
        if not s:
            print(f"story not found: {title}")
            sys.exit(1)
        story_ip = ipface.ip_of(s)   # 🎭 同人本 → 画经典形象
        if story_ip:
            print(f"  🎭 同人剧本，角色按《{story_ip}》的经典形象画")
        chars = list(s.characters or [])
        changed = False
        for c in chars:
            cid, name = c.get("id"), c.get("name")
            if not cid or not name:
                continue
            out = AV_DIR / f"{cid}.jpg"
            url = f"/scene/avatar/{cid}.jpg"
            if out.exists() and not force:
                if c.get("avatar_url") != url:
                    c["avatar_url"] = url
                    changed = True
                print(f"  skip {name} ({cid}) — image exists")
                continue
            print(f"  generating {name} ({cid})…", end=" ", flush=True)
            img = generate_image(build_prompt(c, s.world_long or "", story_ip), size="768*768")
            if not img:
                print("FAILED")
                continue
            out.write_bytes(img)
            c["avatar_url"] = url
            changed = True
            print(f"OK ({len(img)//1024} KB)")
        if changed:
            s.characters = chars
            flag_modified(s, "characters")
            snap = (db.query(StorySnapshot).filter(StorySnapshot.story_id == s.id)
                    .order_by(StorySnapshot.version.desc()).first())
            if snap and (snap.content or {}).get("story"):
                by_id = {c.get("id"): c for c in chars}
                for sc in snap.content["story"].get("characters", []):
                    if sc.get("id") in by_id:
                        sc["avatar_url"] = by_id[sc["id"]].get("avatar_url")
                flag_modified(snap, "content")
            db.commit()
            print("story + latest snapshot updated with avatar urls")
    finally:
        db.close()


if __name__ == "__main__":
    main()
