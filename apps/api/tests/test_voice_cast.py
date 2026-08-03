# -*- coding: utf-8 -*-
"""🎙 预置音色选角表 (Yi 2026-08-03:「人物的嗯哼哦哦之类的声音呢」)。

语气音精灵 —— 角色开口那一下的「嗯 / 哼 / 诶?!」—— 早就在跑了, 素材也排齐了。
缺的一直是编辑器里选音色的那个下拉: 之前只有"上传人声克隆"一条路, 服务器上现成
的预置音色反而选不着, 结果 147 个角色里只有 21 个有声音。

这张表的底线: 只列【精灵排齐了的】音色。列了没排齐的, 作者选完玩家听到的是静默。
"""
import pathlib

from app.engine.voice import SPRITES
from app.routers.stories import VOICE_CAST, voice_list

VOICE_DIR = pathlib.Path("app/static/scene/voice")
NEED = sum(len(v) for v in SPRITES["zh"].values())


def test_only_voices_with_a_complete_sprite_set_are_offered():
    """一个音色缺几段精灵就不该进下拉 —— 作者选了它, 那几种情绪就是哑的。"""
    for v in voice_list()["voices"]:
        n = len(list((VOICE_DIR / v["id"]).glob("*.mp3")))
        assert n >= NEED, f"{v['id']} 只有 {n} 段精灵, 不该出现在选角表里"


def test_a_voice_with_no_sprites_at_all_is_not_offered():
    got = {v["id"] for v in voice_list()["voices"]}
    for vid in VOICE_CAST:
        if not (VOICE_DIR / vid).is_dir():
            assert vid not in got, f"{vid} 磁盘上根本没有精灵目录, 却进了选角表"


def test_every_offered_voice_reads_like_a_person_not_an_id():
    """作者在下拉里读的是「热血磁性 · 男（像十二少）」, 不是 longfei_v3。"""
    for v in voice_list()["voices"]:
        assert v.get("label") and v.get("lang")
        assert v["label"] != v["id"]


def test_the_catalog_never_raises_when_the_voice_dir_is_missing():
    """本机 checkout 里没有音色素材 (真相在服务器) —— 工坊也不该整页崩。"""
    out = voice_list()
    assert isinstance(out["voices"], list) and out["speeds"]


def test_speeds_are_offered_and_centred_on_normal():
    speeds = voice_list()["speeds"]
    assert 1.0 in speeds and min(speeds) < 1.0 < max(speeds)


def test_the_hand_written_cast_table_stays_in_sync_with_gen_voice():
    """选角表和排精灵的脚本必须认同一批音色 —— 一边加了另一边没加, 就是
    「下拉里有但玩家听不到」或者「排了却选不着」。"""
    import re
    src = pathlib.Path("gen_voice.py").read_text(encoding="utf-8")
    body = src.split("VOICES: dict[str, str] = {", 1)[1].split("}", 1)[0]
    in_gen = set(re.findall(r'"([a-z0-9_]+)":', body))
    assert in_gen == set(VOICE_CAST), (
        f"只在 gen_voice: {in_gen - set(VOICE_CAST)}; 只在选角表: {set(VOICE_CAST) - in_gen}")
