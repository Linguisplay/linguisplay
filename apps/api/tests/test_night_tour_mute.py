# -*- coding: utf-8 -*-
"""🌙③ 失守必响: 「被搭话零台词」必须是夜巡判官的红灯。

事故复盘 (2026-08-17): 哑巴疫情 08-13 就被夜巡录进 metrics.jsonl (mute=1),
录了四天没人读 —— 账本不是警报。判官的红灯会顶进 daily_check.log 的判卷行,
这才是每天真有人看的位置。判据与 runtime.speechless_turn 同一把尺:
只有玩家【开口说话】(player 拍 type=dialogue) 的回合算数, do/think 沉默合法。
"""
import qa_playtour


def _judge(beats):
    return qa_playtour._judge(
        story={}, beats=beats, turns_meta=[], state={},
        suggestions=["接着问"], phone={}, mapv={},
        feed={"posts": [{"welcome": True}]})


OPENING = [{"author": "engine", "type": "description", "text": f"旁白第{i}句。", "seq": i}
           for i in range(3)]


def test_a_say_turn_with_no_dialogue_is_a_red_light():
    beats = OPENING + [
        {"author": "player", "type": "dialogue", "speaker_name": "蔡妍",
         "text": "在吗", "seq": 3},
        {"author": "engine", "type": "description", "text": "他偏了偏头。", "seq": 4},
    ]
    errs, _ = _judge(beats)
    assert any("零台词" in e for e in errs), errs


def test_a_say_turn_with_a_reply_is_clean():
    beats = OPENING + [
        {"author": "player", "type": "dialogue", "speaker_name": "蔡妍",
         "text": "在吗", "seq": 3},
        {"author": "engine", "type": "description", "text": "他抬眼。", "seq": 4},
        {"author": "engine", "type": "dialogue", "speaker_name": "蓝信一",
         "text": "来了。", "seq": 5},
    ]
    errs, _ = _judge(beats)
    assert not any("零台词" in e for e in errs), errs


def test_silent_player_nights_never_false_positive():
    """沉默型画像全走 do (player 拍落库是 description) — 角色不吭声合法。"""
    beats = OPENING + [
        {"author": "player", "type": "description", "speaker_name": "蔡妍",
         "text": "我环顾四周。", "seq": 3},
        {"author": "engine", "type": "description", "text": "屋里只有风声。", "seq": 4},
    ]
    errs, _ = _judge(beats)
    assert not any("零台词" in e for e in errs), errs


def test_a_nameless_dialogue_still_counts_as_mute():
    """没有说话人的 dialogue 是解析失败的产物 — 判官不许拿它当「说话了」。"""
    beats = [
        {"author": "player", "type": "dialogue", "speaker_name": "蔡妍",
         "text": "在吗", "seq": 0},
        {"author": "engine", "type": "dialogue", "speaker_name": "",
         "text": "来了。", "seq": 1},
    ]
    errs, _ = _judge(beats)
    assert any("零台词" in e for e in errs), errs
