"""Seed 《无界之地》 — the 🏖 endless SANDBOX shell.

One published story every account starts runs against. The player defines the worldview
at run creation (their run's private pinned copy takes it); the opening cast is conjured
from that worldview; time is synced to the REAL world; the plot never ends. The player
can die — death strips 说/做 and leaves them a watcher.

Run:  python seed_sandbox.py
Idempotent: wipes any prior copy (same title + demo owner) and its runs/snapshots,
then recreates and publishes it.
"""

import os

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./dev.db")
os.environ.setdefault("JWT_SECRET", "dev")

from datetime import datetime  # noqa: E402

from app.db import SessionLocal, init_db  # noqa: E402
from app.models import Persona, Run, Story, StorySnapshot, User  # noqa: E402
from app.routers.stories import _to_story  # noqa: E402
from app.security import hash_password  # noqa: E402

TITLE = "无界之地"
DEMO_EMAIL = "demo@linguisplay.app"
DEMO_PW = "demo12345"

# The default world, used when the player leaves the worldview blank at run start.
DEFAULT_WORLD = (
    "一座名为「无界」的滨海小城：老城区的巷子窄得两人错身要侧肩，新区的玻璃楼一到夜里亮得像另一个城市。"
    "港口每天有船进出，带来陌生的人和说不清来路的货。城里人人都有正经营生，也人人都有不愿说破的事。"
    "你是刚落脚的新面孔，没有人认识你——这既是麻烦，也是机会。"
)

ACTS = [
    {"id": "a1", "index": 1, "title": "无尽",
     "goal": "这个世界刚刚注意到你。去认识它，或者让它认识你。",
     "advance": {}, "events": []},
]


def get_or_create_demo_user(db) -> User:
    u = db.query(User).filter(User.email == DEMO_EMAIL).first()
    if u:
        return u
    u = User(
        email=DEMO_EMAIL,
        password_hash=hash_password(DEMO_PW),
        dob=datetime(1990, 1, 1),
        accepted_tos=True,
        display_name="Demo 作者",
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    db.add(Persona(owner_id=u.id, name="我", pronouns="they", is_default=True,
                   tagline="刚到这座城的人", background="没有来历，也没有归期。"))
    db.commit()
    return u


def wipe_existing(db, owner_id: str) -> None:
    for s in db.query(Story).filter(Story.owner_id == owner_id, Story.title == TITLE).all():
        db.query(Run).filter(Run.story_id == s.id).delete()
        db.query(StorySnapshot).filter(StorySnapshot.story_id == s.id).delete()
        db.delete(s)
    db.commit()


def main() -> None:
    init_db()
    db = SessionLocal()
    try:
        user = get_or_create_demo_user(db)
        wipe_existing(db, user.id)

        story = Story(
            owner_id=user.id,
            title=TITLE,
            one_liner="你来定义这个世界。时间与现实同步，剧情永不落幕——但你会死。",
            synopsis="一个无尽沙盒：开局写下你想要的世界观，世界就照它生长。人物、地点、事端都在你走动时"
            "生成；这里的一天就是现实的一天，夜里的约定要等到真正的明晚才作数。没有结局，没有存档点，"
            "只有一路发生并且不可撤销的事。你可能受伤、可能垂危、也可能死去——死者不能说话，不能动手，"
            "只能看着这个世界在没有你之后继续下去。",
            world_long=DEFAULT_WORLD,
            world_facts="这是一个由玩家在开局定义的世界；以运行时的【世界观/场景设定】为唯一事实基础。",
            relations_overview="所有人物都在你踏入这个世界之后才诞生，关系由你亲手织成。",
            trope_tags=["沙盒", "开放世界", "现实同步", "永不落幕"],
            characters=[],   # conjured per-run from the player's worldview
            acts=ACTS,
            endings=[],      # a sandbox has no exits
            locations=[],    # the start place is synthesized; the map grows emergently
            sandbox={"enabled": True, "real_time": True},
            # no authored world-events to fire; let emergent characters accumulate freely
            tuning={"world_event_every": 0, "max_new_characters": 12},
            visibility="public",
        )
        db.add(story)
        db.flush()
        db.refresh(story)

        content = {"story": _to_story(story).model_dump(), "secrets": []}
        content["story"]["version"] = 1
        db.add(StorySnapshot(story_id=story.id, version=1, content=content))
        story.version = 1
        story.status = "published"
        db.commit()

        print(f"✅ Seeded 《{TITLE}》  story_id={story.id}")
        print("   🏖 sandbox: real_time on, no endings, cast conjured per run.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
