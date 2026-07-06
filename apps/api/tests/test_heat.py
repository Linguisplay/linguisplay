# -*- coding: utf-8 -*-
"""🔥 床戏进度追踪器: the ladder climbs, never slides, resets on scene change; the
anti-euphemism check catches the observed prod failures (那东西/scene reset/旁白变我)."""
from app.engine import heat


def _st(stage=0, at="L1"):
    return {"heat": {"stage": stage, "at": at}}


# ── ladder: climbs from the player's line, monotonic, resets on move/end ─────

def test_ladder_climbs_from_player_input():
    s = {}
    assert heat.advance(s, "吻她", "L1") == (0, 1)
    assert heat.advance(s, "快脱", "L1") == (1, 2)
    assert heat.advance(s, "插进去", "L1") == (2, 4)
    assert heat.advance(s, "高潮", "L1") == (4, 5)


def test_ladder_never_slides_back():
    s = _st(4)
    # a later undressing mention must NOT drop the stage back to 2
    assert heat.advance(s, "把她剩下的衣服也脱了", "L1") == (4, 4)


def test_location_change_resets_scene():
    s = _st(4, at="L1")
    old, new = heat.advance(s, "看看周围", "L2")
    assert (old, new) == (0, 0)         # new place, new scene
    assert s["heat"]["at"] == "L2"


def test_visible_wrapup_resets():
    s = _st(4)
    assert heat.advance(s, "穿好衣服，我们走", "L1") == (4, 0)


def test_everyday_verbs_do_not_climb():
    s = {}
    for line in ("你在干什么", "去操场跑两圈", "别插嘴", "亲自去一趟", "这事就干了吧"):
        heat.advance(s, line, "L1")
    assert heat.stage(s) == 0


def test_model_prose_uses_strict_set():
    s = {}
    # casual prose mentions must not climb…
    heat.advance(s, "她舔了舔嘴唇，把外套搭在椅背上", "L1", from_model=True)
    assert heat.stage(s) == 0
    # …but the model leading the scene forward registers
    heat.advance(s, "她沉腰坐下，两人彻底结合处再无缝隙", "L1", from_model=True)
    assert heat.stage(s) == 4


# ── anchor: the depth-0 scene sheet ──────────────────────────────────────────

def test_anchor_empty_when_cold():
    assert heat.anchor(_st(0)) == ""


def test_anchor_pins_clothing_and_vocab():
    a2 = heat.anchor(_st(2))
    assert "只进不退" in a2 and "脱外套" in a2
    a4 = heat.anchor(_st(4))
    assert "词汇授权" in a4 and "环境描写全轮最多一句" in a4 and "第二人称" in a4
    # vocabulary clearance only arrives at 前戏, not while flirting
    assert "词汇授权" not in heat.anchor(_st(1))


def test_anchor_english():
    a = heat.anchor(_st(4), lang="en")
    assert "second person" in a and "Vocabulary" in a


# ── broke: the fourth check ──────────────────────────────────────────────────

def _beats(*texts, type="description"):
    return [{"type": type, "text": t} for t in texts]


def test_dodge_is_a_break():
    s = _st(4)
    tame = _beats("她的影子在墙上拉长又缩短，烛火被气流扰动，她垂下眼帘不看你。")
    assert heat.broke(s, "插进去", tame) is True


def test_plain_writing_passes():
    s = _st(4)
    plain = _beats("她扶着你的阴茎沉下腰，抽插的节奏由你掌握，你能感到她体内深处的收缩。")
    assert heat.broke(s, "插进去", plain) is False


def test_no_explicit_ask_no_break():
    s = _st(4)
    tame = _beats("她垂下眼帘，呼吸乱了几拍。")
    assert heat.broke(s, "抱紧她", tame) is False


def test_pov_hijack_is_a_break():
    s = _st(4)
    pov = _beats("我咬住下唇，我数着尘埃，我控制不住地发抖。")
    assert heat.broke(s, "继续", pov) is True


def test_player_interiority_is_not_pov_break():
    s = _st(4)
    ok = _beats("你心里翻来覆去只有一个念头：我不能输，我不能先服软，我偏不。")
    assert heat.broke(s, "继续", ok) is False


def test_cold_scene_never_breaks():
    assert heat.broke(_st(0), "插进去", _beats("我我我")) is False
