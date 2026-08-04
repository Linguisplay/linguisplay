# -*- coding: utf-8 -*-
"""🔒 对话不许改地图 (Yi 2026-08-04 定)。

背景: 引擎原本有 8 条「模型/对话 → 地图」的写路径 (铸造新地点 6 条 + 旁白换场 +
模型请求挪 NPC), 各自的闸还不统一 —— 沙盒闸 3 条、自己的旗 2 条、剩下 3 条 (找人
铸去处 / 邀约提及即立档 / 无图剧本开场地点) 压根没有世界级闸, 任何剧本都会被 LLM
加地点。Yi 的裁定: **使用对话铸造新场景、用对话移动至场景、新场景, 都取消; 所有
剧本一律如此 (「都不开」)** —— 所以这里是模块级常量, 不是 tuning 键, 作者开不了。

保留的 (玩家自己驱动的那一半):
  · 地图面板照常出图, 玩家在图上点着走 (apply_move / player_move)
  · 作者作息表决定 NPC 在哪 (char_position 的第 7 级)
  · 🦇 猎手押送等系统机制 (不经对话)

验红方式: 默认就是锁死, 直接跑必绿 —— 所以每组都配一条【解锁后确实会造/会动】的
红样本, 证明断言真在守而不是在空转。
"""
import copy

import pytest

from app.engine import runtime


@pytest.fixture
def unlocked(monkeypatch):
    """把锁打开 —— 只给红样本用, 证明这些路径本来真的会动地图。"""
    monkeypatch.setattr(runtime, "LLM_MAP_WRITES", True)


SBOX = {
    "story": {"id": "s", "sandbox": {"enabled": True},
              "characters": [{"id": "a", "name": "甲", "is_lead": True},
                             {"id": "b", "name": "乙"}],
              "acts": [{"index": 1, "title": "一"}],
              "locations": [
                  {"id": "l1", "name": "旧巷", "detail": "x", "exits": ["老码头"]},
                  # ⚠️ 地名必须 ≥3 字: settle_prose_arrival 对 <3 字的地名不扫描
                  # (太短会在散文里乱命中)。写"码头"的话旁白那组红样本会静静空转。
                  {"id": "dock", "name": "老码头", "detail": "x", "exits": ["旧巷"]},
              ]},
}


class MintLLM:
    """直答编剧桩: describe_place 出干净地名, 主答可注入任意字段。"""

    def __init__(self, **fields):
        self.fields = fields

    def generate(self, prompt):
        if prompt.get("describe_place"):
            return {"name": self.fields.get("mint_name", "河堤"), "detail": "水汽扑面"}
        if prompt.get("risk_judge"):
            return {"risk": 100}
        if prompt.get("start_place"):
            return {"name": "无名渡口", "detail": "雾"}
        out = {"beats": [{"type": "dialogue", "speaker_name": "甲", "text": "走吧。"}],
               "affinity_delta": 0, "advance_act": False, "ending": None}
        if prompt.get("group_mode") in ("primary", None):
            out.update({k: v for k, v in self.fields.items() if k != "mint_name"})
        return out


def _c():
    return copy.deepcopy(SBOX)


def _st(loc="l1"):
    st = runtime.default_state()
    st["location_id"] = loc
    return st


def _n_locs(content):
    return len((content.get("story") or {}).get("locations") or [])


# ── 🧱 铸造新地点: 一条都不许 ────────────────────────────────────────────────
def test_generate_and_move_mints_nothing_when_locked():
    c, st = _c(), _st()
    before = _n_locs(c)
    got = runtime.generate_and_move(c, st, "河堤", llm=MintLLM(), move=False)
    assert got is None, "锁上了还铸出地点"
    assert _n_locs(c) == before, f"地图长出了新地点 ({before} → {_n_locs(c)})"


def test_generate_and_move_does_not_move_the_player_when_locked():
    c, st = _c(), _st()
    runtime.generate_and_move(c, st, "河堤", llm=MintLLM(), move=True)
    assert st["location_id"] == "l1", "锁上了还把玩家挪走了"


def test_red_sample_unlocked_really_does_mint(unlocked):
    """红样本: 解锁后同一句调用确实会铸造 —— 上面两条不是空转。"""
    c, st = _c(), _st()
    before = _n_locs(c)
    got = runtime.generate_and_move(c, st, "河堤", llm=MintLLM(), move=False)
    assert got is not None and _n_locs(c) == before + 1, \
        "解锁后都不铸, 说明这组测试根本没测到铸造路径"


# ── 🚶 模型请求挪 NPC: 不许 ─────────────────────────────────────────────────
def test_apply_char_move_refused_when_locked():
    c, st = _c(), _st()
    assert runtime.apply_char_move(c, st, "乙", "老码头") is None, "锁上了还准了挪人请求"
    assert not ((st.get("char_sim") or {}).get("b") or {}).get("pos"), \
        "锁上了还把乙的位置写进了账本"


def test_red_sample_unlocked_really_moves_npc(unlocked):
    c, st = _c(), _st()
    assert runtime.apply_char_move(c, st, "乙", "老码头") is not None, \
        "解锁后也挪不动 —— 夹具没搭对, 上面那条是空转"


# ── 📜 旁白扫描收账 (settle_prose_arrival): 不许 ────────────────────────────
def test_prose_arrival_does_not_move_when_locked():
    c, st = _c(), _st()
    beats = [{"type": "description", "text": "我们一路走到了老码头边上。"}]
    moved = runtime.settle_prose_arrival(c, st, beats, "l1")
    assert moved is False, "锁上了旁白还能把人挪走"
    assert st["location_id"] == "l1"


def test_red_sample_unlocked_prose_arrival_moves(unlocked):
    c, st = _c(), _st()
    beats = [{"type": "description", "text": "我们一路走到了老码头边上。"}]
    runtime.settle_prose_arrival(c, st, beats, "l1")
    assert st["location_id"] == "dock", \
        "解锁后旁白也挪不动 —— 夹具没搭对, 上面那条是空转"


# ── 🎬 整回合: 模型申报 moved_to 到图外地点 ─────────────────────────────────
def test_full_turn_narrated_move_to_unknown_place_changes_nothing():
    c, st = _c(), _st()
    before = _n_locs(c)
    out = runtime.run_turn(c, st, {"name": "我"}, "我们走吧",
                           channel="say", llm=MintLLM(moved_to="河堤"))
    s2 = out["state"]
    assert _n_locs(c) == before, "整回合跑下来地图还是长了新地点"
    assert s2.get("location_id") == "l1", "整回合跑下来玩家被旁白挪走了"


def test_full_turn_offers_no_move_chip():
    """对话触发的「要不要跟我去X」确认条也算用对话移动至场景 —— 一并取消。"""
    c, st = _c(), _st()
    out = runtime.run_turn(c, st, {"name": "我"}, "带我去河堤看看",
                           channel="say", llm=MintLLM(moved_to="河堤"))
    assert not out.get("move_request"), \
        f"还在发移动确认条: {out.get('move_request')}"


# ── ✅ 玩家自己驱动的那一半必须活着 ─────────────────────────────────────────
def test_player_can_still_walk_the_authored_map():
    """玩家在地图上点着走 —— 这条不是对话驱动, 不许被这一刀误伤。"""
    c, st = _c(), _st()
    runtime.apply_move(c, st, "老码头")
    assert st["location_id"] == "dock", "玩家自己走已有地点都被挡了 — 误伤"


def test_player_move_to_unknown_place_is_refused_not_minted():
    """玩家点名一个图上没有的地方: 拒绝, 而不是当场造一个出来。"""
    c, st = _c(), _st()
    before = _n_locs(c)
    with pytest.raises(ValueError):
        runtime.apply_move(c, st, "从来没有过的地方")
    assert _n_locs(c) == before, "被拒绝了还是把地点铸出来了"


def test_map_panel_still_works():
    """只关写权, 不关地图本身 —— 面板照常出图。"""
    c, st = _c(), _st()
    view = runtime.map_view(c, st)
    assert view["current"] == "l1"
    assert {n["id"] for n in view["nodes"]} == {"l1", "dock"}


def test_author_schedule_still_owns_positions():
    """作者作息表照旧说了算 —— char_position 的级联没被这一刀动到。"""
    c = _c()
    c["story"]["characters"][1]["schedule"] = [{"from_act": 1, "location_id": "dock"}]
    st = _st()
    lb = next(x for x in c["story"]["characters"] if x["id"] == "b")
    assert runtime.char_position(c, st, lb) == "dock"


# ── 🔒 开关本身 ─────────────────────────────────────────────────────────────
def test_lock_is_a_module_constant_not_a_story_flag():
    """Yi 定「都不开」: 作者不许在剧本里把它打开, 所以不能是 tuning 键。"""
    assert runtime.LLM_MAP_WRITES is False, "默认必须是关的"
    assert "llm_map" not in runtime.DEFAULT_TUNING, \
        "别做成 tuning 键 —— 那就等于给作者留了开关, 违背「都不开」"


# ── 📜 旁白把人挪到【已有】地点: 同样不许 ──────────────────────────────────
# (上面那条测的是"未知地点"—— 它是被铸造闸挡下的。已有地点走的是另一条分支:
#  director 的 moved_to 直接 commit_move, 不经铸造。两条分支要分开验, 不然会
#  以为堵上了其实只堵了一半。)
def test_full_turn_narrated_move_to_known_place_does_not_move():
    c, st = _c(), _st()
    out = runtime.run_turn(c, st, {"name": "我"}, "我们走吧",
                           channel="say", llm=MintLLM(moved_to="老码头"))
    assert out["state"].get("location_id") == "l1", \
        "模型一句 moved_to 就把玩家挪到了已有地点 — 对话移动没关干净"


def test_red_sample_unlocked_narrated_move_to_known_place_works(unlocked):
    c, st = _c(), _st()
    out = runtime.run_turn(c, st, {"name": "我"}, "我们走吧",
                           channel="say", llm=MintLLM(moved_to="老码头"))
    assert out["state"].get("location_id") == "dock", \
        "解锁后 moved_to 也挪不动 — 夹具没搭对, 上面那条是空转"


# ── 🌱 无图剧本的开场地点: 也是"新场景" ────────────────────────────────────
MAPLESS = {"story": {"id": "s2",
                     "characters": [{"id": "a", "name": "甲", "is_lead": True}],
                     "acts": [{"index": 1, "title": "一"}],
                     "locations": []}}


def test_mapless_story_gets_no_invented_opening_place():
    c = copy.deepcopy(MAPLESS)
    st = runtime.default_state()
    loc = runtime.ensure_start_location(c, st, llm=MintLLM())
    assert loc is None, f"给无图剧本凭空造了开场地点: {loc}"
    assert _n_locs(c) == 0, "无图剧本的地图长出了地点"
    assert not st.get("location_id"), "无图剧本被钉上了一个位置"


def test_red_sample_unlocked_mapless_story_does_invent(unlocked):
    c = copy.deepcopy(MAPLESS)
    st = runtime.default_state()
    runtime.ensure_start_location(c, st, llm=MintLLM())
    assert _n_locs(c) == 1, "解锁后也不造 — 夹具没搭对, 上面那条是空转"


def test_authored_map_story_still_gets_its_opening_place():
    """有地图的剧本照旧落在开场地点 —— 这一刀不许误伤作者写好的开局。"""
    c, st = _c(), runtime.default_state()
    loc = runtime.ensure_start_location(c, st, llm=MintLLM())
    assert loc and loc.get("id") == "l1"
    assert st["location_id"] == "l1"
