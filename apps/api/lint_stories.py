"""CLI logic linter — Layer 2 of app.engine.logic. Scans stories for structural logic holes
that would strand the player (unreachable act gates, secrets with no fragments, dangling
refs, unreachable places, invalid relation modes, no good ending, …).

Usage (from apps/api/):
    python lint_stories.py               # lint every story
    python lint_stories.py <story_id>    # lint one story
Exit code is non-zero if any ERROR (not warning) is found — handy in CI / pre-publish.
"""

import sys

from app.db import SessionLocal, init_db
from app.engine import logic
from app.models import Story as StoryModel
from app.routers.runs import _pin_content


def main() -> int:
    init_db()
    db = SessionLocal()
    try:
        q = db.query(StoryModel)
        if len(sys.argv) > 1:
            q = q.filter(StoryModel.id == sys.argv[1])
        stories = q.all()
        if not stories:
            print("没有找到剧本。")
            return 1
        total_errors = 0
        for story in stories:
            _, content = _pin_content(story, db)
            issues = logic.lint_story(content)
            errs = sum(1 for i in issues if i["severity"] == "error")
            total_errors += errs
            title = (content.get("story") or {}).get("title", story.id)
            print(f"\n=== 《{title}》 ({story.id}) ===")
            print(logic.format_issues(issues))

        # ── GLOBAL pass: character/location ids must be unique ACROSS stories ──
        # /scene/avatar/{char_id}.jpg and /scene/bg/{loc_id}.jpg are a SHARED namespace:
        # two stories using the same id show each other's art (陈妈 wearing 陈工's face).
        # Convention: prefix ids per story (mw_gu, kl_cyclone, …).
        all_stories = db.query(StoryModel).all()
        owners: dict[tuple, list[str]] = {}
        for s in all_stories:
            for c in s.characters or []:
                if c.get("id"):
                    owners.setdefault(("char", c["id"]), []).append(s.title or s.id)
            for l in s.locations or []:
                if l.get("id"):
                    owners.setdefault(("loc", l["id"]), []).append(s.title or s.id)
        clashes = {k: v for k, v in owners.items() if len(v) > 1}
        if clashes:
            print("\n=== 🌐 跨剧本 id 冲突（美术资源按 id 共享，会互相顶脸/顶背景）===")
            for (kind, cid), titles in sorted(clashes.items()):
                print(f"  ✗ [{'角色' if kind == 'char' else '地点'}:{cid}] "
                      f"被 {len(titles)} 个剧本共用：{'、'.join(f'《{t}》' for t in titles)}")
            total_errors += len(clashes)
        elif len(sys.argv) <= 1:
            print("\n🌐 跨剧本 id 检查：无冲突。")
        return 1 if total_errors else 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
