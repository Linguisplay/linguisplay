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
    assert d["bgm"].rstrip("0123456789") == "tense"   # 变奏键 tense/tense2 都算
    assert d["tint"] == "danger"


def test_hunter_alert_tints_danger():
    d = director.stage_turn({"scene": {"mood": "eerie", "night": True},
                             "threat_view": {"name": "它", "band": "近", "alert": True}})
    assert d["tint"] == "danger"


def test_battle_mood_keeps_its_own_bgm():
    d = director.stage_turn({"scene": {"mood": "battle"},
                             "pressure_view": {"value": 90}})
    assert d["bgm"].rstrip("0123456789") == "battle"


# ── pick_bgm (曲库标签选曲) ──────────────────────────────


def test_bgm_intimacy_beats_everything():
    assert director.pick_bgm("tense", pressure=90, hot=True, heat=2) == "romantic"


def test_bgm_simmer_band_goes_eerie():
    assert director.pick_bgm("daily", pressure=50) == "eerie"
    assert director.pick_bgm("romantic", pressure=50) == "romantic", "阴燃不夺浪漫"


def test_bgm_night_and_frailty_recolor_daily():
    assert director.pick_bgm("daily", night=True) == "lonely"
    assert director.pick_bgm("daily", frail=True) == "lonely"
    assert director.pick_bgm("warm", night=True) == "warm", "夜里陪伴还是陪伴"


def test_bgm_unknown_mood_falls_to_daily():
    assert director.pick_bgm("弹幕未来贝斯") == "daily"


def test_bgm_variants_rotate_by_place_and_day():
    a = director.pick_variant("daily", "loc_alley|1")
    b = director.pick_variant("daily", "loc_alley|1")
    assert a == b, "同场景同一天曲目稳定"
    picks = {director.pick_variant("daily", f"loc{i}|{i}") for i in range(12)}
    assert len(picks) >= 2, "换地方/过天要能换到别的曲子"
    for p in picks:
        assert p in ("daily", "daily2", "daily3")
    assert director.pick_variant("romantic", "x|1") == "romantic", "单曲情绪不变奏"


# ── logic_audit (导演审稿: 确认逻辑无漏洞) ──────────────────


def test_audit_dead_speaker_is_a_hole():
    beats = [{"type": "dialogue", "speaker_name": "老陈", "text": "我没死。"}]
    finds = director.logic_audit(beats, dead_names=["老陈"])
    assert any("老陈" in f for f in finds)


def test_audit_day_night_contradiction_narration_only():
    night = [{"type": "description", "speaker_name": None, "text": "晌午的日头正毒。"}]
    assert director.logic_audit(night, slot="夜"), "夜里写晌午 = 漏洞"
    moon = [{"type": "description", "speaker_name": None, "text": "月光漫进走廊。"}]
    assert director.logic_audit(moon, slot="夜") == [], "夜里写月光天经地义"
    quoted = [{"type": "dialogue", "speaker_name": "甲", "text": "那天晌午的日头正毒。"}]
    assert director.logic_audit(quoted, slot="夜") == [], "台词里回忆白天不算罪"


def test_audit_echo_repeat():
    text = "他把病历翻到最后一页，指腹停在一行褪色的签名上，很久没有说话。" * 3
    beats = [{"type": "description", "speaker_name": None, "text": text}]
    assert director.logic_audit(beats, prev_text=text), "整局复读要抓"
    assert director.logic_audit(beats, prev_text="完全不同的一段前情。") == []


def test_audit_clean_turn_is_silent():
    beats = [{"type": "dialogue", "speaker_name": "甲", "text": "跟我来。"},
             {"type": "description", "speaker_name": None, "text": "夜风掠过走廊。"}]
    assert director.logic_audit(beats, slot="夜", dead_names=["乙"],
                                prev_text="上一回合的另一段。") == []


def test_low_sanity_tints_frail():
    d = director.stage_turn({"scene": {"mood": "eerie"},
                             "sanity_view": {"name": "理智", "value": 20, "max": 100}})
    assert d["tint"] == "frail"


def test_night_tint_and_calm_reset():
    assert director.stage_turn({"scene": {"night": True}})["tint"] == "night"
    assert director.stage_turn({"scene": {"night": False}})["tint"] == "none"
    assert director.stage_turn({})["tint"] == "none"


# ── 今日心气 (relationships.day_mood / temper) ───────────


def test_day_mood_stable_within_day_flips_across_days():
    from app.engine import relationships as rel
    assert rel.day_mood("a", 3) == rel.day_mood("a", 3), "当天稳定"
    moods = {rel.day_mood("a", d) for d in range(1, 30)}
    assert len(moods) >= 2, "跨天要翻面"
    assert all(m in (-1, 0, 1) for m in moods)


def test_temper_colors_deltas():
    from app.engine import relationships as rel
    assert rel.temper(4, 2, -1) == (2, 1), "心气差: 好话打折"
    assert rel.temper(-2, 0, -1)[0] == -3, "心气差: 坏话加倍"
    assert rel.temper(2, 1, 1) == (3, 2), "心气好: 好话添一分"
    assert rel.temper(-2, -2, 1) == (-1, -1), "心气好: 坏话减半"
    assert rel.temper(3, 1, 0) == (3, 1), "平常日不上色"
