# -*- coding: utf-8 -*-
"""🗺 地图随机游走 fuzz (Yi 2026-08-07:「反复测试一下地图这方面的bug」)。

单点用例只测得到想得到的那几种情况。地图的坏法多半来自【状态之间对不上】:
走了但钉没拔、跟着的人没跟上、两个读口说的位置不一样、地图上画的人跟引擎认的不一致。
这类只有【走很多步、每步都验一组不变量】才撞得出来。

每一步随机做一件事: 走到某个可达地点 / 让某人跟上 / 让某人别跟了 / 原地不动。
每步之后验九条:
  ① 玩家所在地必须是真实存在的地点
  ② 任何人的位置解析结果都必须是真实存在的地点 (或明确的 AWAY)
  ③ 同行的人必须跟玩家同地 (说好了跟, 就不许人在别处)
  ④ 在场名单里的人, 位置必须真的等于玩家所在地
  ⑤ 地图上画的人, 必须跟引擎认的位置一致 (两个读口不许对不上)
  ⑥ 没人能同时出现在两个地点
  ⑦ 离开之后, 旧地点上的钉必须拔干净 (不许把人钉在你已经离开的地方)
  ⑧ 玩家自己的角色永远在玩家所在地 (附身模式)
  ⑨ state 永远可 JSON 序列化 (存档不许被走坏)

种子固定 → 同一次失败永远可复现; 失败时把走过的每一步打出来。
"""
import json
import os
import random

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./dev.db")
os.environ.setdefault("JWT_SECRET", "dev")

from app.db import SessionLocal  # noqa: E402
from app.engine import runtime  # noqa: E402
from app.models import Story, StorySnapshot  # noqa: E402

STEPS = int(os.environ.get("MAP_FUZZ_STEPS", "120"))
SEEDS = [1, 2, 3]


def _published():
    db = SessionLocal()
    try:
        out = []
        for s in db.query(Story).filter(Story.status == "published").all():
            snap = (db.query(StorySnapshot).filter(StorySnapshot.story_id == s.id)
                    .order_by(StorySnapshot.version.desc()).first())
            if snap and snap.content:
                c = json.loads(json.dumps(snap.content))
                if (c.get("story") or {}).get("locations"):
                    out.append((s.title, c))
        return out
    finally:
        db.close()


STORIES = _published()
if not STORIES:                                    # 空库时别红成一片, 明说跳过
    pytest.skip("dev.db 里没有已发布且带地图的剧本", allow_module_level=True)


def _loc_ids(content):
    return {l.get("id") for l in (content.get("story") or {}).get("locations") or [] if l.get("id")}


def _check(content, state, trail, story):
    """九条不变量。任何一条破了都把走过的路一起报出来 —— 不然没法复现。"""
    def bad(msg):
        raise AssertionError(f"《{story}》{msg}\n走过的路: " + " → ".join(trail[-14:]))

    ids = _loc_ids(content)
    here = state.get("location_id")
    if here not in ids:
        bad(f"① 玩家在一个不存在的地点 {here!r}")

    pcid = state.get("player_character_id")
    seen = {}
    for ch in runtime._characters(content):
        cid = ch.get("id")
        if not cid:
            continue
        pos = runtime.char_position(content, state, ch)
        if pos and pos != runtime.AWAY and pos not in ids:
            bad(f"② {ch.get('name')} 被解析到一个不存在的地点 {pos!r}")
        if pos and pos != runtime.AWAY:
            if cid in seen and seen[cid] != pos:
                bad(f"⑥ {ch.get('name')} 同时在两处")
            seen[cid] = pos

    for cid in state.get("following") or []:
        ch = runtime._char_by_id(content, cid)
        if not ch:
            continue
        pos = runtime.char_position(content, state, ch)
        if pos != here:
            bad(f"③ {ch.get('name')} 说好了同行, 却在 {pos!r} 而玩家在 {here!r}")

    for ch in runtime.scene_characters(content, state):
        cid = ch.get("id")
        if cid == pcid:
            continue
        pos = runtime.char_position(content, state, ch)
        if pos != here:
            bad(f"④ {ch.get('name')} 在「在场」名单里, 位置却是 {pos!r}")

    for node in (runtime.map_view(content, state).get("nodes") or []):
        for nm in node.get("chars") or []:
            ch = next((x for x in runtime._characters(content) if x.get("name") == nm), None)
            if not ch:
                continue
            pos = runtime.char_position(content, state, ch)
            if pos != node.get("id"):
                bad(f"⑤ 地图把 {nm} 画在「{node.get('name')}」, 引擎认的是 {pos!r}")

    for lid, pinned in (state.get("char_pins") or {}).items():
        pass   # 钉本身合法; ⑦ 由下面的「离开即拔钉」单独验

    if pcid and (state.get("mode") or "character") == "character":
        pc = runtime._char_by_id(content, pcid)
        if pc and runtime.char_position(content, state, pc) != here:
            bad("⑧ 玩家自己的角色不在玩家所在地")

    try:
        json.dumps(state, ensure_ascii=False)
    except (TypeError, ValueError) as e:
        bad(f"⑨ state 走坏了, 存不下去: {e!r}")


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("title,content", STORIES, ids=[t for t, _ in STORIES])
def test_map_random_walk(title, content, seed):
    rnd = random.Random(seed)
    state = runtime.default_state()
    runtime.ensure_start_location(content, state)
    ids = sorted(_loc_ids(content))
    cast = [c for c in runtime._characters(content) if c.get("id")]
    trail = [f"起点={state.get('location_id')}"]
    _check(content, state, trail, title)

    for _ in range(STEPS):
        act = rnd.random()
        if act < 0.55 and ids:                      # 走
            dest = rnd.choice(ids)
            try:
                runtime.apply_move(content, state, dest)
                trail.append(f"走→{dest}")
            except ValueError:
                trail.append(f"走✗{dest}")          # 走不到是合法的, 不算 bug
        elif act < 0.75 and cast:                   # 让某人跟上
            c = rnd.choice(cast)
            try:
                runtime.set_follow(content, state, c["id"], True)
                trail.append(f"跟+{c.get('name')}")
            except ValueError:
                trail.append(f"跟✗{c.get('name')}")
        elif act < 0.9 and cast:                    # 让某人别跟了
            c = rnd.choice(cast)
            try:
                runtime.set_follow(content, state, c["id"], False)
                trail.append(f"跟-{c.get('name')}")
            except ValueError:
                pass
        else:
            trail.append("原地")
        _check(content, state, trail, title)


@pytest.mark.parametrize("title,content", STORIES, ids=[t for t, _ in STORIES])
def test_leaving_drops_the_pins_behind(title, content):
    """⑦ 离开即拔钉: 不许把人钉在你已经离开的地方 —— 那正是「他明明不在却出现」的温床。"""
    state = runtime.default_state()
    runtime.ensure_start_location(content, state)
    start = state.get("location_id")
    cast = [c for c in runtime._characters(content) if c.get("id")]
    if not cast:
        pytest.skip("这本没有角色")
    state.setdefault("char_pins", {})[cast[0]["id"]] = start
    dest = next((i for i in sorted(_loc_ids(content)) if i != start), None)
    if not dest:
        pytest.skip("这本只有一个地点")
    try:
        runtime.apply_move(content, state, dest)
    except ValueError:
        pytest.skip("这本从起点走不到别处")
    left = (state.get("char_pins") or {}).get(cast[0]["id"])
    assert left != start, f"离开 {start} 之后, {cast[0].get('name')} 的钉还留在那儿"
