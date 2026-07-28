# -*- coding: utf-8 -*-
"""🎭 基调锚 (Yi 2026-07-28 实弹: 暧昧戏里撒娇式的「错过今天就没机会了」被读成威胁,
角色回了一句地盘警告当场翻脸 — 字面狠词压过了语境基调)。"""
from app.engine import qwen, runtime


def _st(track, held, mood=""):
    s = runtime.default_state()
    s["bgm_led"] = {"track": track, "held": held}
    if mood:
        s["scene"] = {"mood": mood}
    return s


def test_soft_tone_held_emits_anchor():
    a = runtime.tone_anchor(_st("romantic", 3))
    assert "暧昧" in a and "连着3拍" in a
    assert "撒娇" in a and "别当真翻脸" in a


def test_hard_tone_stays_literal():
    """紧张/战斗/诡异下狠话就该按字面读, 不许也当撒娇。"""
    for k in ("tense", "battle", "eerie", "mystery"):
        assert runtime.tone_anchor(_st(k, 5)) == ""


def test_fresh_tone_not_yet_established():
    """刚起头的软基调还不算「已建立的基调」, 不发。"""
    assert runtime.tone_anchor(_st("romantic", 1)) == ""


def test_variant_track_names_normalize():
    """曲库轮换名 romantic2/warm3 要归一到同一个基调。"""
    assert "暧昧" in runtime.tone_anchor(_st("romantic2", 4))
    assert "温情" in runtime.tone_anchor(_st("warm3", 2))


def test_anchor_rides_depth_zero():
    """必须贴在生成点 — 埋 system 正文的那份(台词形状)已被实弹证明压不住。"""
    a = qwen._depth_anchor({"speaker_name": "蓝信一", "persona": {"name": "蔡妍"},
                            "tone": runtime.tone_anchor(_st("romantic", 3)),
                            "channel": "say", "context": {}})
    assert "暧昧" in a and "别当真翻脸" in a


def test_en_variant():
    a = runtime.tone_anchor(_st("romantic", 3), zh=False)
    assert "romantic" in a and "teasing" in a
