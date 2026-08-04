# -*- coding: utf-8 -*-
"""🚬 全剧本冒烟: drive a scripted mini-playthrough through EVERY published story so
prompt/pipeline changes never ship blind. Two modes:

OFFLINE (default, MockLLM, seconds, no keys):
    python smoke_stories.py
  For each story: lint → build_opening → a fixed turn script exercising the
  deterministic spine (dialogue, observe, hard move to a known exit, pose twin) with
  invariant checks (beats produced, state JSON-serializable, location really moved,
  pose really booked, audit sheet sane). Exit 1 on any failure → pre-deploy gate.

LIVE (real model, for eyeballing PROMPT changes; needs .env keys, run on the server):
    set -a && . .env && set +a && python smoke_stories.py --live "斗罗大陆·史莱克学院" 4
  Runs N live turns on that story and prints the beats — the human check that a
  prompt change still sounds right in-world.
"""
import json
import os
import sys

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./dev.db")
os.environ.setdefault("JWT_SECRET", "dev")

from app.db import SessionLocal  # noqa: E402
from app.engine import logic, runtime  # noqa: E402
from app.engine.llm import MockLLM  # noqa: E402
from app.models import Story, StorySnapshot  # noqa: E402

PERSONA = {"name": "我", "pronouns": "they", "tagline": "冒烟测试员"}


def load_contents(db) -> list[tuple[str, dict]]:
    out = []
    for s in db.query(Story).filter(Story.status == "published").all():
        snap = (db.query(StorySnapshot).filter(StorySnapshot.story_id == s.id)
                .order_by(StorySnapshot.version.desc()).first())
        if snap and snap.content:
            out.append((s.title, json.loads(json.dumps(snap.content))))
    return out


def second_location(content: dict, state: dict) -> dict | None:
    """A location reachable from the start (exit-connected), for the hard-move check."""
    cur = runtime.current_location(content, state)
    for ref in (cur or {}).get("exits") or []:
        d = runtime.resolve_location(content, ref)
        if d and d.get("id") and d["id"] != (cur or {}).get("id") \
                and runtime.location_available(content, state, d):
            return d
    return None


def smoke_one(title: str, content: dict) -> list[str]:
    """Returns a list of failure strings (empty = clean)."""
    fails: list[str] = []
    llm = MockLLM()
    lang = runtime.lang_of(content)
    zh = lang != "en"

    # 1. lint: structural logic holes are a fail (warnings are fine)
    issues = logic.lint_story(content) or []
    errs = [i for i in issues
            if isinstance(i, dict) and i.get("severity") == "error"]
    if errs:
        fails.append(f"lint: {len(errs)} error(s): "
                     + "; ".join(str(e.get("code")) for e in errs[:3]))

    # 2. opening
    state = runtime.default_state()
    try:
        opening = runtime.build_opening(content, state, llm=llm)
        if not opening:
            fails.append("opening: no beats")
    except Exception as e:
        fails.append(f"opening crashed: {e!r}")
        return fails

    # 3. scripted turns over the deterministic spine
    say = "你们好，我刚到这里。" if zh else "Hello, I just arrived."
    look = "我看看四周。" if zh else "I look around."
    pose = "我坐在角落里。" if zh else "I sit down in the corner."
    script: list[tuple[str, str, str]] = [
        ("say", say, "dialogue turn"),
        ("think", look, "observe turn"),
        ("do", pose, "pose twin"),
    ]
    dest = second_location(content, state)

    for channel, text, label in script:
        try:
            out = runtime.run_turn(content, state, PERSONA, text, channel=channel, llm=llm)
        except Exception as e:
            fails.append(f"{label} crashed: {e!r}")
            return fails
        if not out.get("beats"):
            fails.append(f"{label}: no beats")
        state = out.get("state") or state
        try:
            json.dumps(state, ensure_ascii=False)
        except (TypeError, ValueError) as e:
            fails.append(f"{label}: state not JSON-serializable: {e!r}")
        if not isinstance(state.get("last_audit"), list):
            fails.append(f"{label}: audit sheet missing")

    # invariant: the pose twin actually booked (zh only — the twin is zh-regex)
    if zh:
        pp = state.get("player_pos")
        if not (isinstance(pp, dict) and (pp.get("text") or "").strip()):
            fails.append("pose twin: player_pos not booked")
    # invariant: 换场真的把人挪过去了。
    # 🗺 走地图面板那条路 (runtime.apply_move —— /runs/{id}/move 端点调的同一个),
    # 不再用「在输入框打『去某地』」: TYPED_MOVE 2026-08-04 关掉之后那是被取消的功能,
    # 拿它当断言等于让冒烟门守一个产品已经不做的行为 (实弹: 5/5 掉到 3/5, 而代码是对的)。
    if dest and zh:
        try:
            runtime.apply_move(content, state, dest["id"])
        except Exception as e:
            fails.append(f"map move crashed: {e!r}")
        if state.get("location_id") != dest["id"]:
            fails.append(f"map move: expected {dest['id']}, at {state.get('location_id')}")
    # invariant: goal resolves
    if not isinstance(runtime.goal_for(content, state), str):
        fails.append("goal_for: not a string")
    return fails


def live(title_filter: str, n_turns: int) -> None:
    from app.engine.llm import get_llm
    db = SessionLocal()
    try:
        pairs = [(t, c) for t, c in load_contents(db) if title_filter in t]
    finally:
        db.close()
    if not pairs:
        sys.exit(f"no published story matching 「{title_filter}」")
    title, content = pairs[0]
    llm = get_llm()
    if isinstance(llm, MockLLM):
        sys.exit("live mode needs real model keys in the environment (.env)")
    print(f"🎬 LIVE smoke on 《{title}》 ({n_turns} turns)")
    state = runtime.default_state()
    for b in runtime.build_opening(content, state, llm=llm):
        print(f"  [开场] {b.get('text', '')[:160]}")
    script = ["你们好，我刚到这里，这是什么地方？", "我看看四周。",
              "我坐下来，观察在场的人。", "最近有什么新鲜事？",
              "我想到处走走。", "跟我说说你自己吧。"]
    for text in script[:n_turns]:
        print(f"\n>> {text}")
        out = runtime.run_turn(content, state, PERSONA, text,
                               channel="do" if "坐" in text or "走" in text else "say", llm=llm)
        for b in out.get("beats") or []:
            tag = b.get("speaker_name") or "旁白"
            print(f"  [{tag}] {(b.get('text') or '')[:200]}")
        state = out.get("state") or state
        au = state.get("last_audit") or []
        if au:
            print(f"  📋 audit: {json.dumps(au, ensure_ascii=False)[:200]}")


def main() -> None:
    if "--live" in sys.argv:
        i = sys.argv.index("--live")
        title = sys.argv[i + 1] if len(sys.argv) > i + 1 else ""
        n = int(sys.argv[i + 2]) if len(sys.argv) > i + 2 else 4
        live(title, n)
        return
    db = SessionLocal()
    try:
        pairs = load_contents(db)
    finally:
        db.close()
    if not pairs:
        sys.exit("no published stories in the DB — run the seeds first")
    bad = 0
    for title, content in pairs:
        fails = smoke_one(title, content)
        if fails:
            bad += 1
            print(f"✗ {title}")
            for f in fails:
                print(f"    - {f}")
        else:
            print(f"✓ {title}")
    print(f"\n{len(pairs) - bad}/{len(pairs)} stories clean")
    if bad:
        sys.exit(1)


if __name__ == "__main__":
    main()
