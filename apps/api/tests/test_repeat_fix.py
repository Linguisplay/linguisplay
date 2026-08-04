# -*- coding: utf-8 -*-
"""🔁 旁白复读的两处修补 (Yi 2026-08-04 实弹: 狗笼一场戏里一根烟叼了十二拍,
📟 心情标签连着四回合一模一样)。

两处都【不是新功能】, 是把已经建好却空转的东西接通:

  ① 动作账 spent: schema→flags→_sl_settle→prompt 全链路早就在, 断在模型不填 ——
     原描述三处都写「默认空 / 没有就省略」, 它夹在九个可选申报里当然每个都省。
     16 个回合 0 条记录 = prompt 里那句「【本场已经演过】」从来没出现过。
  ② 心情 mood: 提示词写的是「上一场戏散场时…」, 但同场每一拍都讲一遍, 模型原样
     报回来又被存回去 —— 自己喂自己。只在换场时给。
"""
from app.engine import qwen, runtime


# ── ① spent 必须是必填, 不能再退回可选 ──────────────────────────────────
def _render_props(**kw):
    """取渲染拍的 JSON schema 属性表。"""
    sch = qwen._turn_schema(**kw) if hasattr(qwen, "_turn_schema") else None
    return sch


def test_spent_is_asked_for_as_required_not_optional():
    """这一条一旦退回「没有就省略」, 动作账立刻回到全空, 复读照旧。"""
    import inspect
    src = inspect.getsource(qwen)
    i = src.index('props["spent"]')
    desc = src[i:i + 900]
    assert "【必填】" in desc, "spent 的中文描述必须明说必填"
    assert "REQUIRED" in desc, "spent 的英文描述必须明说 REQUIRED"
    assert "没有就省略" not in desc, "「没有就省略」正是它十六个回合一条没填的原因"


def test_the_prompt_still_forbids_reskinned_replays():
    """复读是【换措辞】演同一个动作, 不是逐字重复 —— 这句话不许被删弱。"""
    import inspect
    src = inspect.getsource(qwen)
    assert "【本场已经演过】" in src
    assert "换个措辞也不行" in src, "去掉这半句, 守的就只剩逐字复读了"


# ── ② 心情不再自己喂自己 ────────────────────────────────────────────────
def _st(mood_text, scene_tag, ledger):
    return {"char_sim": {"c1": {"mood": {"text": mood_text, "at": 0, "scene": scene_tag}}},
            "clock": {"day": 1, "slot": 0}, "scene_ledger": ledger}


_LEDGER = {"open": True, "loc": "loc_a", "opened": {"day": 1, "slot": 0}}
_TAG = "loc_a|1|0"


def test_a_mood_born_in_this_scene_is_not_fed_back_into_this_scene():
    st = _st("心里发紧，面上不露", _TAG, _LEDGER)
    assert runtime._carried_mood(st, "c1") == "", \
        "同场回喂就是那个环: 模型读到它, 原样报回来, 再被存回去"


def test_a_mood_from_an_earlier_scene_still_carries():
    """这才是这个字段的本意 —— 上一场怎么散的, 下一场就怎么见面。别修过头。"""
    st = _st("心里发紧，面上不露", "loc_b|1|0", _LEDGER)
    assert runtime._carried_mood(st, "c1") == "心里发紧，面上不露"


def test_without_the_scene_ledger_the_old_behaviour_is_untouched():
    """场账本是灰度旗, 全站大多数剧本没开。没开的照旧按时段过期。"""
    st = _st("心里发紧，面上不露", "", None)
    assert runtime._carried_mood(st, "c1") == "心里发紧，面上不露"
    st2 = _st("心里发紧，面上不露", _TAG, {"open": False})
    assert runtime._carried_mood(st2, "c1") == "心里发紧，面上不露"


def test_a_day_later_it_still_dulls():
    st = _st("心里发紧，面上不露", "loc_b|1|0", _LEDGER)
    st["clock"] = {"day": 3, "slot": 0}
    assert runtime._carried_mood(st, "c1") == ""


def test_no_mood_no_crash():
    for junk in ({}, {"char_sim": {}}, {"char_sim": {"c1": {}}},
                 {"char_sim": {"c1": {"mood": {}}}}):
        junk.setdefault("clock", {"day": 1, "slot": 0})
        assert runtime._carried_mood(junk, "c1") == ""
        assert runtime._carried_mood(junk, None) == ""


# ── 场指纹本身 ──────────────────────────────────────────────────────────
def test_scene_tag_is_empty_when_no_scene_is_open():
    assert runtime._scene_tag({}) == ""
    assert runtime._scene_tag({"scene_ledger": None}) == ""
    assert runtime._scene_tag({"scene_ledger": {"open": False, "loc": "x"}}) == ""
    assert runtime._scene_tag({"scene_ledger": "垃圾"}) == ""


def test_scene_tag_changes_when_the_scene_does():
    a = runtime._scene_tag({"scene_ledger": _LEDGER})
    b = runtime._scene_tag({"scene_ledger": {**_LEDGER, "loc": "loc_b"}})
    c = runtime._scene_tag({"scene_ledger": {**_LEDGER, "opened": {"day": 2, "slot": 0}}})
    assert a and a != b and a != c
