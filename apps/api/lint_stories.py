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
        return 1 if total_errors else 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
