# -*- coding: utf-8 -*-
"""🕸 NPC 边拆向 (合伙人⑤): 懒升级 / 按方向种 ties / 演化过的边不重种。"""
from app.engine import runtime


def _content():
    return {"story": {"characters": [
        {"id": "x", "name": "X", "ties": [{"char_id": "y", "stance": 2, "label": "师父"}]},
        {"id": "y", "name": "Y", "ties": [{"char_id": "x", "stance": 1, "label": "顽徒"}]},
        {"id": "z", "name": "Z", "ties": [{"char_id": "x", "stance": -2, "label": "死仇"}]},
    ]}}


def test_legacy_edge_lazy_upgrades_both_directions():
    st = {"npc_rel": {"a|b": {"stance": 2, "label": "旧盟", "log": []}}}
    sa = runtime.npc_stance(st, "a", "b")
    sb = runtime.npc_stance(st, "b", "a")
    assert sa and sb and sa["stance"] == sb["stance"] == 2
    assert sa["label"] == sb["label"] == "旧盟"   # 老档对称复制, 行为不变


def test_ties_seed_directionally_with_own_labels():
    st = {"npc_rel": {}}
    runtime._ensure_npc_rel(_content(), st)
    assert runtime.npc_stance(st, "x", "y")["label"] == "师父"   # x 眼中的 y
    assert runtime.npc_stance(st, "y", "x")["label"] == "顽徒"   # y 眼中的 x — 各归各
    assert runtime.npc_stance(st, "x", "y")["stance"] == 2
    assert runtime.npc_stance(st, "y", "x")["stance"] == 1


def test_one_sided_tie_mirrors_stance_without_label():
    st = {"npc_rel": {}}
    runtime._ensure_npc_rel(_content(), st)
    assert runtime.npc_stance(st, "z", "x")["label"] == "死仇"   # 作者写的方向
    mirror = runtime.npc_stance(st, "x", "z")
    assert mirror["stance"] == -2                                # 对向兜底同 stance
    assert mirror["label"] == runtime._STANCE_LABEL.get(-2, "")  # 无 label → 档位词


def test_rel_start_seeds_only_unbooked(monkeypatch):
    """💗🛡 关系起点: 作者写的开局好感/信任落初值; 已建账的关系绝不被覆盖。"""
    from app.engine import relationships as rel
    content = {"story": {"characters": [
        {"id": "u", "name": "U", "rel_start": {"closeness": 60, "trust": 3}},
        {"id": "v", "name": "V", "rel_start": {"closeness": 999, "trust": -5}},  # 越界要钳
        {"id": "w", "name": "W", "rel_start": {"trust": 90}},
    ]}}
    st = {"npc_rel": {}, "rel": {"w": {"closeness": 33, "romance": 1, "trust": 44}}}
    runtime._ensure_npc_rel(content, st)
    assert st["rel"]["u"] == {"closeness": 60, "romance": 0, "trust": 3}
    assert st["rel"]["v"]["closeness"] == rel.CLOSE_MAX and st["rel"]["v"]["trust"] == rel.TRUST_MIN
    assert st["rel"]["w"]["closeness"] == 33   # 处出来的关系不被起点覆盖


def test_evolved_edge_never_reseeded():
    st = {"npc_rel": {"x|y": {"ab": {"stance": -1, "label": None},
                              "ba": {"stance": -1, "label": None},
                              "log": [{"act": 1, "delta": -1, "why": "闹翻了"}]}}}
    runtime._ensure_npc_rel(_content(), st)
    assert runtime.npc_stance(st, "x", "y")["stance"] == -1      # ties 不许盖掉演化
    assert runtime.npc_stance(st, "x", "y")["label"] != "师父"
