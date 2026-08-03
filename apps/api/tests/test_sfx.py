# -*- coding: utf-8 -*-
"""🔊 本子自己的音效词表 (Yi 2026-08-03:「怎么在编辑剧本里面加音效」)。

内置那张 _SFX 是现代 / 恐怖向的 —— 仙侠本写「剑鸣」「拂尘」一个都不触发, 所以
那类本子一直是哑的。作者在工坊里补词, 存 tuning.sfx。

底线:
  ① 作者的词压过内置词 (同一句两边都命中时听作者的)
  ② 长词压过短词 (写了「刀剑相击」又写了「刀」, 具体的那条该赢)
  ③ 关得掉 (enabled=false 连心跳兜底一起停)
  ④ 手填字段什么形状都可能 —— 绝不炸回合
"""
from app.engine import director


def _c(sfx):
    return {"story": {"tuning": {"sfx": sfx}}}


# ── ① 作者的词压过内置 ────────────────────────────────────────────────────
def test_an_authors_word_fires():
    st = director.TurnStage(_c({"map": {"剑鸣": "clash"}}))
    assert st.beat_fx("山风里传来一声剑鸣。")["sfx"] == "clash"


def test_the_authors_word_beats_the_built_in_one():
    """同一句里「敲门」(内置→knock) 和作者的「拂尘」都在 —— 听作者的。"""
    st = director.TurnStage(_c({"map": {"拂尘": "creak"}}))
    assert st.beat_fx("他拂尘一扫，随后有人敲门。")["sfx"] == "creak"


def test_without_a_story_the_built_in_table_still_works():
    """绝大多数本子没配 —— 老行为一格都不许变。"""
    assert director.TurnStage().beat_fx("有人敲门。")["sfx"] == "knock"
    assert director.TurnStage(None).beat_fx("你屏住呼吸。")["sfx"] == "heartbeat"


# ── ② 长词赢 ──────────────────────────────────────────────────────────────
def test_the_more_specific_word_wins():
    st = director.TurnStage(_c({"map": {"刀": "sword", "刀剑相击": "clash"}}))
    assert st.beat_fx("刀剑相击，火星四溅。")["sfx"] == "clash"


# ── ③ 关得掉 ──────────────────────────────────────────────────────────────
def test_turning_sfx_off_silences_everything_including_the_heartbeat_fallback():
    st = director.TurnStage(_c({"enabled": False, "map": {"剑鸣": "clash"}}))
    assert "sfx" not in st.beat_fx("一声剑鸣。")
    assert "sfx" not in st.beat_fx("有人敲门。")
    assert "sfx" not in st.beat_fx("你屏住呼吸，脊背发凉。")


def test_turning_sfx_off_does_not_kill_the_visual_flash_or_the_expression():
    """关的是【音效】。白闪和表情是画面, 不该被一起关掉。"""
    st = director.TurnStage(_c({"enabled": False}))
    out = st.beat_fx("楼上传来一声尖叫。", mood="惊恐")
    assert out.get("fx") == "flash" and out.get("expr") == "惊"


def test_omitting_enabled_means_on():
    """老本子没有这个字段 —— 不该被当成关着。"""
    assert director.TurnStage(_c({"map": {}})).beat_fx("有人敲门。")["sfx"] == "knock"


# ── ④ 垃圾数据不炸回合 ────────────────────────────────────────────────────
def test_junk_shapes_never_raise():
    for junk in ("一句话", [], 7, None, {"map": "不是字典"}, {"map": {"": "x", "词": ""}},
                 {"map": {"词": "  "}}, {"enabled": "yes", "map": {1: 2}}):
        st = director.TurnStage(_c(junk))
        st.beat_fx("有人敲门，接着是脚步声。")   # 不许抛
    for junk in ({}, {"story": None}, {"story": {"tuning": "x"}}, None):
        director.TurnStage(junk).beat_fx("下雨了。")


def test_a_word_pointing_at_a_missing_file_still_does_not_break_the_turn():
    """作者打错音效名 → 客户端那边静默降级, 服务端这边照发不误。"""
    out = director.TurnStage(_c({"map": {"钟磬": "没这个文件"}})).beat_fx("钟磬齐鸣。")
    assert out["sfx"] == "没这个文件"


# ── 去重照旧 ──────────────────────────────────────────────────────────────
def test_dedupe_still_applies_to_the_authors_words():
    """吓人的东西响两次就不吓人了 —— 这条对作者的词一样管用。"""
    st = director.TurnStage(_c({"map": {"剑鸣": "clash"}}))
    assert st.beat_fx("一声剑鸣。")["sfx"] == "clash"
    assert "sfx" not in st.beat_fx("又是一声剑鸣。")


# ── 工坊面板读的那张表 ────────────────────────────────────────────────────
def test_the_studio_catalog_lists_only_files_that_really_exist():
    """手写清单迟早和 /scene/sfx 对不上 —— 作者点了名却没文件, 玩家听到的是静默。"""
    import pathlib

    from app.routers.stories import sfx_list
    d = pathlib.Path("app/static/scene/sfx")
    got = sfx_list()["sfx"]
    on_disk = {p.stem for p in d.glob("*.mp3")} if d.is_dir() else set()
    assert {x["name"] for x in got} == on_disk
    for x in got:
        assert x["label"] and "keywords" in x
