# -*- coding: utf-8 -*-
"""🎴 全量补封面: 给每一本已发布的剧本/沙盒排一张盒绘 (班底站中间)。

合成不生图 —— 一本一两秒, 不花钱, 可以随便重跑。第一次跑会给没有透底立绘的角色
现抠一次底 (rembg, 每人几秒), 结果永久缓存在 /scene/cover/_fig_*.webp, 之后就快了。

    python backfill_covers.py            # 只补缺的/素材变过的
    python backfill_covers.py --force    # 全部重排 (改了版式之后用)
    python backfill_covers.py --title 浮生
"""
import sys
import time

from app.db import SessionLocal
from app.engine import cover
from app.models import Story
from app.routers.stories import _to_story

force = "--force" in sys.argv
want = ""
if "--title" in sys.argv:
    want = sys.argv[sys.argv.index("--title") + 1]

if not cover.has_fonts():
    print("⚠️  找不到可用字体 —— 海报会出成无字版。")
    print("   服务器上装一次: dnf install -y google-noto-serif-cjk-ttc-fonts "
          "google-noto-sans-cjk-ttc-fonts")

db = SessionLocal()
rows = [s for s in db.query(Story).filter(Story.status == "published").all()
        if not want or want in (s.title or "")]
done = skipped = failed = 0
for s in rows:
    story = _to_story(s).model_dump()
    if not force and not cover.is_stale(story):
        skipped += 1
        continue
    t0 = time.time()
    try:
        out = cover.build(story, force=force)
    except Exception as e:
        failed += 1
        print(f"  ✗ {s.title}: {type(e).__name__}: {e}")
        continue
    done += 1
    print(f"  ✓ {s.title}  班底{out.get('cast')}人 "
          f"{out.get('poster_bytes', 0) // 1024}+{out.get('wide_bytes', 0) // 1024}KB "
          f"{time.time() - t0:.1f}s")
db.close()
print(f"\n封面: 新排 {done} · 跳过 {skipped} · 失败 {failed} · 共 {len(rows)} 本")
