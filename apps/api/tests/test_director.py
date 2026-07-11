# -*- coding: utf-8 -*-
"""🎬 规则导演 v1 — per-beat 注记与回合演出单的确定性规则."""
from app.engine import director


def _stage():
    return director.TurnStage()


# ── beat_fx ──────────────────────────────────────────────


def test_sfx_from_keyword():
    fx = _stage().beat_fx("走廊尽头传来敲门声。")
    assert fx.get("sfx") == "knock"


def test_sfx_not_repeated_within_turn():
    st = _stage()
    assert st.beat_fx("有人敲门。").get("sfx") == "knock"
    assert "sfx" not in st.beat_fx("又是一阵敲门。")


def test_flash_on_sudden_scare_once():
    st = _stage()
    a = st.beat_fx("灯猛地熄灭了，整层楼陷进黑暗。")
    b = st.beat_fx("她突然撞上了玻璃。")
    assert a.get("fx") == "flash"
    assert "fx" not in b, "一回合至多白闪一次"


def test_flash_on_scream():
    assert _stage().beat_fx("楼上传来一声尖叫。").get("fx") == "flash"


def test_heartbeat_backstop_when_no_physical_sfx():
    fx = _stage().beat_fx("你屏住呼吸，脊背发凉。")
    assert fx.get("sfx") == "heartbeat"


def test_expr_classified_from_free_text_mood():
    assert _stage().beat_fx("她笑了。", mood="喜").get("expr") == "喜"
    assert _stage().beat_fx("他后退。", mood="警惕又紧张").get("expr") == "惊"
    assert _stage().beat_fx("他叹气。", mood="疲惫的失望").get("expr") == "哀"
    assert "expr" not in _stage().beat_fx("他点头。", mood="平静")


def test_calm_beat_yields_nothing():
    assert _stage().beat_fx("午后的阳光很好。") == {}


# ── stage_turn ───────────────────────────────────────────


def test_pressure_hot_overrides_bgm_and_tints_danger():
    d = director.stage_turn({"scene": {"mood": "daily", "night": False},
                             "pressure_view": {"name": "压力", "value": 82}})
    assert d["bgm"] == "tense"
    assert d["tint"] == "danger"


def test_hunter_alert_tints_danger():
    d = director.stage_turn({"scene": {"mood": "eerie", "night": True},
                             "threat_view": {"name": "它", "band": "近", "alert": True}})
    assert d["tint"] == "danger"


def test_battle_mood_keeps_its_own_bgm():
    d = director.stage_turn({"scene": {"mood": "battle"},
                             "pressure_view": {"value": 90}})
    assert "bgm" not in d


def test_low_sanity_tints_frail():
    d = director.stage_turn({"scene": {"mood": "eerie"},
                             "sanity_view": {"name": "理智", "value": 20, "max": 100}})
    assert d["tint"] == "frail"


def test_night_tint_and_calm_reset():
    assert director.stage_turn({"scene": {"night": True}})["tint"] == "night"
    assert director.stage_turn({"scene": {"night": False}})["tint"] == "none"
    assert director.stage_turn({})["tint"] == "none"
