# -*- coding: utf-8 -*-
"""🎭 补掉舞台上的黑影 —— 给缺立绘/头像的角色重新排队生成。

背景 (Yi 2026-08-05:「火山续费了，重新生成一下人物和 npc 黑影」): 火山账户欠费期间
所有生图请求 403, 那阵子出生的涌现角色一张脸都没画出来。VN 模式的剧本里, 没有立绘的
说话者会落到兜底的 `_extra.webp` 黑灰人影 —— 那就是玩家看到的"黑影"。

覆盖两处角色:
  · 已发布剧本的班底 (Story.characters)
  · 存档私有副本里【涌现出生】的角色 (Run.pinned_content) —— 它们只活在那一局里,
    任何按剧本扫描的工具都碰不到

走的是运行时那条管线 (_ensure_char_avatars), 不另起炉灶:
  · 幂等 —— 文件在就跳过, 重复跑不花钱
  · 同种同画风 —— char_seed 定脸, _story_art 定风格, 补出来的脸跟以前一致
  · 立绘只给 VN 模式的本子 (非 VN 本压根不上立绘, 也就没有黑影问题)

用法:
    python backfill_sprites.py --dry            # 只盘点, 一分钱不花
    python backfill_sprites.py                  # 真补
    python backfill_sprites.py --story 狗笼      # 只补某一本 (标题子串)
    python backfill_sprites.py --limit 20       # 这一趟最多排多少张 (默认不限)
"""
import argparse
import sys
import time
from pathlib import Path

_STATIC = Path(__file__).resolve().parent / "app" / "static" / "scene"
SPRITE_DIR = _STATIC / "sprite"
AV_DIR = _STATIC / "avatar"


def _missing(chars: list[dict], vn: bool) -> list[tuple[str, str, str]]:
    """[(cid, name, 缺什么)] —— 缺什么 ∈ {avatar, sprite, both}"""
    out = []
    for c in chars or []:
        cid, name = c.get("id"), (c.get("name") or "").strip()
        if not cid or not name:
            continue
        no_av = not (AV_DIR / f"{cid}.jpg").exists()
        no_sp = vn and not (SPRITE_DIR / f"{cid}.webp").exists()
        if no_av or no_sp:
            out.append((cid, name, "both" if (no_av and no_sp) else
                        ("avatar" if no_av else "sprite")))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="只盘点不排队")
    ap.add_argument("--story", default="", help="只处理标题含该子串的剧本")
    ap.add_argument("--limit", type=int, default=0, help="这一趟最多排多少张 (0=不限)")
    args = ap.parse_args()

    from app.db import SessionLocal, init_db
    from app.models import Run, Story
    from app.routers.runs import _IMG_Q, _ensure_char_avatars

    init_db()
    db = SessionLocal()
    queued_before = _IMG_Q.qsize()
    rows: list[tuple[str, str, str, str]] = []   # (来源, cid, name, 缺什么)

    stories = db.query(Story).filter(Story.status == "published").all()
    if args.story:
        stories = [s for s in stories if args.story in (s.title or "")]
    print(f"扫 {len(stories)} 本已发布剧本")

    for s in stories:
        vn = bool((s.tuning or {}).get("vn_mode"))
        for cid, name, what in _missing(s.characters or [], vn):
            rows.append((f"剧本·{s.title[:14]}", cid, name, what))
        if not args.dry:
            content = {"story": {**{k: getattr(s, k) for k in
                                    ("id", "title", "world_long", "world_facts",
                                     "tuning", "characters", "locations")}}}
            try:
                _ensure_char_avatars(content, vn=vn)
            except Exception as e:
                print(f"  ⚠ {s.title[:14]}: {e}")

    # 🔑 存档私有副本: 涌现角色只活在这里, 按剧本扫描的工具永远碰不到它们
    runs = db.query(Run).all()
    print(f"扫 {len(runs)} 个存档的私有副本")
    seen_run_cids: set[str] = set()
    for r in runs:
        content = r.pinned_content or {}
        story = content.get("story") or {}
        srow = db.get(Story, r.story_id)
        if args.story and (not srow or args.story not in (srow.title or "")):
            continue
        vn = bool((story.get("tuning") or {}).get("vn_mode")
                  or ((srow.tuning if srow else {}) or {}).get("vn_mode"))
        gen = [c for c in (story.get("characters") or []) if c.get("generated")]
        hit = [x for x in _missing(gen, vn) if x[0] not in seen_run_cids]
        for cid, name, what in hit:
            seen_run_cids.add(cid)
            rows.append((f"涌现@{(srow.title[:12] if srow else r.story_id[:8])}",
                         cid, name, what))
        if hit and not args.dry:
            try:
                _ensure_char_avatars(content, vn=vn)
            except Exception as e:
                print(f"  ⚠ run {r.id[:8]}: {e}")

    print()
    if not rows:
        print("✅ 一个黑影都没有, 不用补")
        return
    print(f"缺图的角色 {len(rows)} 个:")
    for src, cid, name, what in rows[:40]:
        print(f"   {what:<7} {name:<10} {cid:<14} {src}")
    if len(rows) > 40:
        print(f"   … 还有 {len(rows) - 40} 个")

    if args.dry:
        print("\n(--dry: 一张都没排, 一分钱没花)")
        return

    q = _IMG_Q.qsize()
    print(f"\n已排进生图队列: {q - queued_before} 张 (队列现有 {q})")
    print("后台串行渲染中 —— 每张约十几秒, 可以走了。")
    # 队列是后台线程消费的; 脚本退出会带走进程, 所以等它排空
    last = q
    while _IMG_Q.qsize() > 0:
        time.sleep(5)
        now = _IMG_Q.qsize()
        if now != last:
            print(f"  剩 {now} 张…")
            last = now
    time.sleep(20)   # 最后一张还在渲染
    print("✅ 队列已清空")


if __name__ == "__main__":
    sys.exit(main())
