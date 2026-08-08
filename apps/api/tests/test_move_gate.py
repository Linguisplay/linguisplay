# -*- coding: utf-8 -*-
"""🚪 移动写侧收口 (2026-08-03 地图深查): commit_move 唯一换场写入口 + AST 守卫。
读侧当年收口成 char_position 后同类 bug 绝迹; 写侧五次同型遗漏 (拔钉/锁定门/带路人)
证明靠人记不住 — 收成结构, 白名单外直写 = 红。"""
import ast
import copy
import pathlib

from app.engine import runtime

SBOX = {
    "story": {"id": "s", "sandbox": {"enabled": True},
              "characters": [{"id": "a", "name": "甲", "is_lead": True},
                             {"id": "b", "name": "乙"}],
              "acts": [{"index": 1, "title": "一"}],
              "locations": [
                  {"id": "l1", "name": "旧巷", "detail": "x", "exits": ["码头"]},
                  {"id": "dock", "name": "码头", "detail": "x", "exits": ["旧巷"]},
                  {"id": "locked", "name": "密库", "detail": "x", "exits": [],
                   "unlock": {"required_fragment_ids": ["f1"]}},
              ]},
    "secrets": [{"id": "s1", "character_id": "a", "title": "t",
                 "fragments": [{"id": "f1", "content": "x", "retrieval_key": "k",
                                "unlock": {"affinity_min": 999}}]}],
}


class MintLLM:
    """直答编剧桩: describe_place 出干净地名, 其余按主答老三样。"""
    def __init__(self, **fields):
        self.fields = fields

    def generate(self, prompt):
        if prompt.get("describe_place"):
            return {"name": self.fields.get("mint_name", "河堤"), "detail": "水汽扑面"}
        if prompt.get("risk_judge"):
            return {"risk": 100}
        if prompt.get("start_place"):
            return {}
        out = {"beats": [{"type": "dialogue", "speaker_name": "甲", "text": "走吧。"}],
               "affinity_delta": 0, "advance_act": False, "ending": None}
        if prompt.get("group_mode") in ("primary", None):
            out.update({k: v for k, v in self.fields.items() if k != "mint_name"})
        return out


def _st(pins=None):
    st = runtime.default_state()
    st["location_id"] = "l1"
    if pins:
        st["char_pins"] = dict(pins)
    return st


# ── 1+2. moved_to 生成路 = 真实换场: 拔旧钉 + 带路人一起走 (审查 P0) ────────────

def test_moved_to_generation_releases_pins_and_carries_the_guide(map_writes_on):
    content = copy.deepcopy(SBOX)
    st = _st(pins={"b": "l1"})            # 乙被访客/约见钉按在旧巷
    out = runtime.run_turn(content, st, {"name": "我"}, "走吧", channel="say",
                           llm=MintLLM(moved_to="河堤", next_speakers=[]))
    st2 = out["state"]
    new_id = st2["location_id"]
    assert new_id != "l1" and str(new_id).startswith("loc_gen_")   # 生成路真的移动了
    assert (st2.get("char_pins") or {}).get("b") != "l1"           # 旧地钉子已释放
    # 带路的主答者甲钉在新地点 — 「不然人留在原地话在新地」对生成路同样成立
    assert (st2.get("char_pins") or {}).get("a") == new_id


# ── 3. existing 捷径过锁定门: 撞名锁定地点不许传送、不许上确认条 ────────────────

def test_mint_shortcut_respects_the_lock_gate():
    content = copy.deepcopy(SBOX)
    st = _st()
    # 原始名直接命中锁定地点 (第一捷径)
    got = runtime.generate_and_move(content, st, "密库", llm=MintLLM())
    assert got is None and st["location_id"] == "l1"
    # LLM 提炼名命中锁定地点 (第二捷径)
    got2 = runtime.generate_and_move(content, st, "那间上锁的库房",
                                     llm=MintLLM(mint_name="密库"))
    assert got2 is None and st["location_id"] == "l1"
    # move=False (提及即立档) 同样驳回 — 锁定地点名不得漏进确认条
    got3 = runtime.generate_and_move(content, st, "密库", llm=MintLLM(), move=False)
    assert got3 is None


# ── 4. fate 生成分支同窄口 ─────────────────────────────────────────────────────

def test_fate_move_generation_path_releases_pins(map_writes_on, monkeypatch):
    content = copy.deepcopy(SBOX)
    st = _st(pins={"b": "l1"})
    st["pending_choice"] = {"key": "fate1", "kind": "fate",
                            "options": [{"id": "f1", "label": "去河堤"}]}
    st["fate_effects"] = {"f1": {"kind": "move", "target": "河堤", "mandate": "x"}}
    monkeypatch.setattr(runtime, "get_llm", lambda: MintLLM())
    res = runtime._apply_fate(content, st, "f1")
    assert res.get("moved_to") == "河堤"
    assert str(st["location_id"]).startswith("loc_gen_")
    assert (st.get("char_pins") or {}).get("b") != "l1"            # 命运换场也要拔钉


# ── 5. 铸造不是移动: mint_sought_character 不动位置、不误伤现场钉 ──────────────

def test_mint_sought_character_leaves_position_and_pins_alone(mints_on):
    content = copy.deepcopy(SBOX)
    st = _st(pins={"b": "l1"})
    got = runtime.mint_sought_character(content, st, "陈四",
                                        {"where": "堤下棚屋", "who": "线人"},
                                        MintLLM(mint_name="堤下棚屋"))
    assert got and got.get("loc")
    assert st["location_id"] == "l1"                    # 确认片才移动, 铸造不移动
    assert (st.get("char_pins") or {}).get("b") == "l1"  # 现场钉不许被铸造误伤


# ── 6. 明确落账的 npc 离场压过陈钉 (审查: 审计记✓人不动) ───────────────────────

def test_booked_npc_move_beats_a_stale_pin(map_writes_on):
    content = copy.deepcopy(SBOX)
    st = _st(pins={"b": "l1"})            # 场钉把乙按在现场
    moved = runtime.apply_char_move(content, st, "乙", "码头")
    assert moved and moved.get("to_name") == "码头"
    assert runtime.char_position(content, st, {"id": "b"}) == "dock"   # 钉子不许压申报


# ── 7. 原地"移动"不是换场: 不拔钉不收场 ───────────────────────────────────────

def test_moving_in_place_does_not_shed_pins():
    content = copy.deepcopy(SBOX)
    st = _st(pins={"b": "l1"})
    runtime.apply_move(content, st, "旧巷")
    assert st["location_id"] == "l1"
    assert (st.get("char_pins") or {}).get("b") == "l1"


# ── 8. AST 守卫: 换场写入只许出现在白名单函数 ─────────────────────────────────

_LOC_OK = {
    "commit_move",            # 唯一换场写入口
    "ensure_start_location",  # 开局锚定 (不是移动)
    "build_opening",          # 开局锚定
    "discover_on_arrival",    # 自愈重锚 (= current_location, 同值)
    "confront_stream",        # 自愈重锚
    "run_turn_stream",        # 自愈重锚 (9103); 猎手押送必须已改走 commit_move
}
_PINS_WRITE_OK = {
    "commit_move", "_drop_pins_on_leave", "_sl_open", "_sl_close",
    "build_opening",           # 访客钉
    "_apply_phone_judgments",  # 电话钉
    "_settle_prose_exits", "_heal_away_pins",
    "apply_char_move",         # 落账弹钉
    "run_turn_stream",         # 寻人钉
}


def _write_sites():
    src = pathlib.Path(runtime.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    funcs = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            funcs.append((node.lineno, node.end_lineno, node.name))

    def owner(line):
        hits = sorted((f for f in funcs if f[0] <= line <= f[1]),
                      key=lambda f: f[1] - f[0])
        return hits[0][2] if hits else "<module>"

    loc_writers, pin_writers = set(), set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for tgt in node.targets:
            t = ast.unparse(tgt)
            base = t.split(".")[0].split("[")[0]
            if "'location_id'" in t and base in ("state", "st"):
                loc_writers.add(owner(node.lineno))
            if "'char_pins'" in t:
                pin_writers.add(owner(node.lineno))
    return loc_writers, pin_writers


def test_location_writes_only_in_whitelisted_functions():
    loc_writers, _ = _write_sites()
    stray = loc_writers - _LOC_OK
    assert not stray, f"location_id 在白名单外被直写: {sorted(stray)} — 换场必须走 commit_move"


def test_pin_writes_only_in_whitelisted_functions():
    _, pin_writers = _write_sites()
    stray = pin_writers - _PINS_WRITE_OK
    assert not stray, f"char_pins 在白名单外被直写: {sorted(stray)}"
