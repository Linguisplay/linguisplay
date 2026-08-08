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
        elif act < 0.94:                            # ⏭ 换幕 + 对时 (作息表跟着幕走)
            nxt = max(1, min(9, int(state.get("act") or 1) + rnd.choice([-1, 1])))
            state["act"] = nxt
            runtime.align_clock_to_act(content, state, nxt)
            trail.append(f"幕→{nxt}")
        elif act < 0.97:                            # ➕ 玩家自己加一个地方 (局内编辑地图)
            got = runtime.add_place(content, state, f"临时去处{rnd.randint(1, 999)}")
            trail.append("加地点" + ("✓" if got else "✗"))
        elif act < 0.99 and cast and ids:           # 🚶 带路人换场 (commit_move 的 lead_id)
            c = rnd.choice(cast)
            dest = next((l for l in content["story"]["locations"]
                         if l.get("id") == rnd.choice(ids)), None)
            if dest:
                runtime.commit_move(content, state, dest, lead_id=c.get("id"))
                trail.append(f"带{c.get('name')}→{dest.get('id')}")
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


# ── 🧪 红样本自验: 这套不变量不许是空转的 ────────────────────────────────────────
# 生产 22 本 × 7 种子 × 800 步 = 12.3 万步全绿。一个从来不红的 fuzz 最可疑的
# 就是它压根没在测, 所以两条各配一个红样本, 打掉能力必须当场开枪。

def test_red_sample_the_pin_check_really_fires(monkeypatch):
    """打掉「离开即拔钉」→ ⑦ 必须红。"""
    monkeypatch.setattr(runtime, "_drop_pins_on_leave", lambda *a, **k: None)
    title, content = STORIES[0]
    with pytest.raises(AssertionError):
        test_leaving_drops_the_pins_behind(title, content)


def test_red_sample_the_map_check_really_fires(monkeypatch):
    """把地图上的人挪到别的节点 → ⑤ 必须红 (两个读口对不上正是最难自查的那类)。

    ⚠️ 红样本本身也得跟数据形状无关: 第一版靠「找两个都有人的节点」来制造矛盾,
    而本机夹具只有一个节点有人, 于是红样本静静空转 —— 一个不会红的红样本
    比没有红样本更坏。改成硬塞一个必然错位的名字。
    """
    orig = runtime.map_view
    title, content = STORIES[0]
    who = next((c.get("name") for c in runtime._characters(content) if c.get("name")), None)
    if not who:
        pytest.skip("这本没有具名角色")

    def bad(c, st):
        mv = orig(c, st)
        pos = runtime.char_position(c, st, runtime._char_by_id(c, next(
            x["id"] for x in runtime._characters(c) if x.get("name") == who)))
        for n in (mv.get("nodes") or []):
            if n.get("id") != pos:                 # 挂到一个【肯定不是他】的节点上
                n["chars"] = list(n.get("chars") or []) + [who]
                break
        return mv

    monkeypatch.setattr(runtime, "map_view", bad)
    with pytest.raises(AssertionError):
        test_map_random_walk(title, content, 1)


# ── 🔭 旁白把人写去了别处, 而位置纹丝没动 (Yi 报障 2026-08-08) ──────────────────
#
# 生产实测: 8 例「正文点名了别的在册地点、而 location_id 全程不变」。最典型的一例
# 连着三拍把人从巷口 → 龙津道 → 街角 → 糖水店一路写过去, 状态一动没动。
#
# 根因不在提示词缺规则 —— 规则在, 而且写得很明白 (「这一拍的戏必须仍然发生在此地」)。
# 根因是【玩家亲口说了要走, 而引擎没有任何办法兑现】: 2026-08-06 三把锁把移动收成
# 只剩点地图之后, 玩家打「跟他走」时系统无路可走, 模型只好用文字兑现。
# 那一例的上一拍正是: 蔡妍「（反手扣紧他的手，跟他走）好啊」。
#
# 光加狠话不解决问题 (今天已经栽过两次)。先做一个【能量的】检测器: 正文里点名了
# 别的在册地点 = 一次候选的文与实分家。有了数才谈得上「改了有没有用」。

def _named_elsewhere(content, state, texts):
    return runtime.prose_moved_elsewhere(content, state, texts)


def test_it_catches_prose_that_walks_you_out():
    """生产实弹原文。"""
    content = {"story": {"locations": [
        {"id": "kc", "name": "九龙城区"}, {"id": "gg", "name": "佳佳糖水店"}]}}
    st = {"location_id": "kc"}
    assert _named_elsewhere(content, st, [
        "蓝信一推开佳佳糖水店的玻璃门，门楣上的风铃叮铃铃响了一串。"]) == ["佳佳糖水店"]


def test_moving_around_inside_the_place_is_fine():
    """场内走动是合法的 —— 误报会把这个读口变成噪音, 那就没人看了。"""
    content = {"story": {"locations": [
        {"id": "f", "name": "训练场"}, {"id": "g", "name": "学院前院"}]}}
    st = {"location_id": "f"}
    assert _named_elsewhere(content, st, [
        "你走到训练场角落的木桩前，开始活动手腕和脚踝。"]) == []


def test_merely_mentioning_a_place_is_not_moving():
    """嘴上提一句别处不算把人写过去 —— 要有移动动词才算。"""
    content = {"story": {"locations": [
        {"id": "kc", "name": "九龙城区"}, {"id": "gg", "name": "佳佳糖水店"}]}}
    st = {"location_id": "kc"}
    assert _named_elsewhere(content, st, ["他说佳佳糖水店的杏仁茶最好。"]) == []


def test_the_current_place_never_counts():
    content = {"story": {"locations": [{"id": "kc", "name": "九龙城区"}]}}
    assert _named_elsewhere(content, {"location_id": "kc"},
                            ["你走进九龙城区深处。"]) == []


def test_one_char_names_are_ignored():
    """一个字的地名会到处误命中 (「街」「巷」)。"""
    content = {"story": {"locations": [
        {"id": "a", "name": "巷"}, {"id": "b", "name": "面档"}]}}
    assert _named_elsewhere(content, {"location_id": "b"}, ["你走出巷口。"]) == []


def test_it_is_quiet_on_a_normal_beat():
    content = {"story": {"locations": [
        {"id": "kc", "name": "九龙城区"}, {"id": "gg", "name": "佳佳糖水店"}]}}
    assert _named_elsewhere(content, {"location_id": "kc"},
                            ["他把蝴蝶刀收进腰间，歪头看你一眼。"]) == []
