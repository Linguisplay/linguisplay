# -*- coding: utf-8 -*-
"""🎴 自动封面的守卫。四条底线:

  ① 封面是【合成】不是【生图】—— cover.py 在结构上碰不到生图/大模型。破了这条,
     发布链路上就多了一笔钱和几十秒等待, 而且脸对不上游戏里那个人。
  ② 出不来封面绝不能拖累别的事: 没角色、没美术、怪标题、疯立绘, 一律不许抛。
  ③ 素材换了封面要自己重排 (立绘是后来才陆续画出来的, 没人会记得回来点一次)。
  ④ 脸带量歪的立绘 (糊成一团的兽形废图) 不许上台 —— 归一化会把它撑成两倍屏高。
"""
import io
import os
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./test_cover.db")
os.environ.setdefault("JWT_SECRET", "test")

import pytest  # noqa: E402
from PIL import Image  # noqa: E402

from app.engine import cover  # noqa: E402

pytestmark = pytest.mark.filterwarnings("ignore")


def _story(sid: str, **kw) -> dict:
    base = {"id": sid, "title": "试排本", "one_liner": "一句引子",
            "language": "zh", "characters": [], "locations": [], "acts": [],
            "sandbox": {}, "tuning": {}}
    base.update(kw)
    return base


@pytest.fixture(autouse=True)
def _sandbox_dirs(tmp_path, monkeypatch):
    """所有落盘改到 tmp —— 测试绝不许碰 /scene 下的真美术。"""
    for name in ("COVER_DIR", "SPRITE_DIR", "AVATAR_DIR", "BG_DIR"):
        d = tmp_path / name.lower()
        d.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(cover, name, d)
    yield


def _person(w=300, h=900, skin=(226, 178, 148), head_frac=0.13):
    """一个假人形: 上面一颗肤色的头, 下面一段深色躯干, 四周透明。"""
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    hh = int(h * head_frac)
    hw = int(hh * 0.75)
    for y in range(hh):                       # 头
        for x in range((w - hw) // 2, (w + hw) // 2):
            im.putpixel((x, y), (*skin, 255))
    for y in range(hh, h):                    # 躯干
        for x in range(int(w * 0.12), int(w * 0.88)):
            im.putpixel((x, y), (54, 60, 92, 255))
    return im


def _put_sprite(cid: str, im: Image.Image):
    buf = io.BytesIO()
    im.save(buf, format="WEBP")
    (cover.SPRITE_DIR / f"{cid}.webp").write_bytes(buf.getvalue())


# ── ① 合成, 不生图 ────────────────────────────────────────────────────────
def test_cover_engine_cannot_reach_the_image_api():
    src = Path(cover.__file__).read_text(encoding="utf-8")
    for banned in ("generate_image", "edit_image", "get_llm", "_enqueue_image",
                   "qwen", "ARK_", "httpx", "requests"):
        assert banned not in src, (
            f"封面是合成不是生图: cover.py 里出现了 {banned!r}。"
            "一旦接上生图, 发布链路就要花钱等几十秒, 而且封面上的脸不再是游戏里那个人。")


# ── ② 什么都缺也要出图 ────────────────────────────────────────────────────
def test_builds_with_no_art_no_cast_at_all():
    out = cover.build(_story("s_empty"))
    p = cover.paths("s_empty")
    assert p["poster"].exists() and p["wide"].exists()
    assert out["cast"] == 0
    assert Image.open(p["poster"]).size == cover.POSTER
    assert Image.open(p["wide"]).size == cover.WIDE


def test_survives_hostile_authoring():
    """空标题 / 超长标题 / emoji / 纯符号 —— 排版一律不许炸。"""
    for i, t in enumerate(["", "　", "🎬🎬🎬", "《" + "长" * 90 + "》",
                           "A" * 200, "《聊斋·聂小倩》— the Ghost's Lantern"]):
        cover.build(_story(f"s_hostile{i}", title=t, one_liner="x" * 400))
        assert cover.paths(f"s_hostile{i}")["poster"].exists()


def test_a_broken_sprite_never_breaks_the_build():
    for cid, im in (("c_flat", Image.new("RGBA", (400, 400), (9, 9, 9, 255))),
                    ("c_clear", Image.new("RGBA", (400, 400), (0, 0, 0, 0))),
                    ("c_hair", Image.new("RGBA", (8, 4000), (200, 30, 30, 255)))):
        _put_sprite(cid, im)
    story = _story("s_broken", characters=[{"id": c, "name": c} for c in
                                           ("c_flat", "c_clear", "c_hair")])
    cover.build(story)
    assert cover.paths("s_broken")["poster"].exists()


def test_story_id_with_path_tricks_is_refused_not_written():
    with pytest.raises(ValueError):
        cover.paths("../../etc/passwd")
    assert cover.urls("../../etc/passwd") is None


# ── ③ 素材一变就重排 ──────────────────────────────────────────────────────
def test_new_sprite_makes_the_cover_stale():
    story = _story("s_fresh", characters=[{"id": "c1", "name": "甲"}])
    cover.build(story)
    assert not cover.is_stale(story)
    _put_sprite("c1", _person())                 # 美术后来才画出来
    assert cover.is_stale(story), "立绘落地后封面必须重排 —— 没人会记得回来手点一次"
    cover.build(story)
    assert not cover.is_stale(story)


def test_retitling_makes_the_cover_stale():
    story = _story("s_title")
    cover.build(story)
    assert not cover.is_stale(story)
    assert cover.is_stale(_story("s_title", title="改了名"))


def test_layout_version_bump_restales_every_cover():
    story = _story("s_algo")
    cover.build(story)
    assert not cover.is_stale(story)
    old = cover.ALGO
    try:
        cover.ALGO = old + "-next"
        assert cover.is_stale(story), "改了版式就该全站重排, 靠的就是指纹里带版本号"
    finally:
        cover.ALGO = old


def test_rebuild_is_skipped_when_nothing_changed():
    story = _story("s_idem", characters=[{"id": "c1", "name": "甲"}])
    _put_sprite("c1", _person())
    cover.build(story)
    assert cover.build(story).get("skipped") is True


# ── ④ 脸量得准, 量不准的不上台 ────────────────────────────────────────────
def test_faces_come_out_the_same_size_whatever_the_framing():
    """全身、及膝、半身三种构图, 归一之后脸必须一边大 —— 这是合影感的全部来源。"""
    full = _person(300, 900, head_frac=0.13)
    knee = full.crop((0, 0, 300, 620))
    bust = full.crop((0, 0, 300, 300))
    sizes = []
    for im in (full, knee, bust):
        face, _, ok = cover.head_metrics(im)
        assert ok, "画得清清楚楚的一张脸都量不出来"
        sizes.append(face)
    assert max(sizes) / min(sizes) < 1.25, f"同一颗头量出三个大小: {sizes}"


def test_hair_volume_does_not_shrink_anyone():
    """顶着一大坨头发的和贴头皮的, 脸得一样大 (量的是脸不是头顶到下巴)。"""
    plain = _person(300, 900, head_frac=0.13)
    tall = Image.new("RGBA", (300, 900), (0, 0, 0, 0))
    tall.alpha_composite(plain.crop((0, 0, 300, 780)), (0, 120))
    for x in range(130, 170):                    # 头顶一撮冲天辫
        for y in range(0, 120):
            tall.putpixel((x, y), (30, 22, 18, 255))
    a, b = cover.head_metrics(plain)[0], cover.head_metrics(tall)[0]
    assert max(a, b) / min(a, b) < 1.3, f"发型把脸的大小带跑了: {a} vs {b}"


def test_a_speck_of_a_person_in_a_huge_frame_is_rejected():
    """糊成一团的兽形废图里蹲着个小人 —— 按它归一会把整张图撑成两倍屏高。"""
    im = Image.new("RGBA", (1000, 1600), (18, 18, 20, 255))
    tiny = _person(60, 180)
    im.alpha_composite(tiny, (470, 1380))
    assert cover.head_metrics(im)[2] is False


def test_unmeasurable_figures_step_aside_when_the_cast_is_deep_enough():
    for i in range(3):
        _put_sprite(f"ok{i}", _person())
    _put_sprite("bad", Image.new("RGBA", (900, 1500), (18, 18, 20, 255)))
    story = _story("s_drop", characters=[{"id": c, "name": c} for c in
                                         ("ok0", "ok1", "ok2", "bad")])
    assert cover.build(story)["cast"] == 3, "量不准的废图该请下台, 不该顶着两倍屏高上封面"


def test_the_only_figure_we_have_is_used_even_if_unmeasurable():
    _put_sprite("solo", Image.new("RGBA", (900, 1500), (18, 18, 20, 255)))
    story = _story("s_solo", characters=[{"id": "solo", "name": "独"}])
    assert cover.build(story)["cast"] == 1, "只剩这一个还挑, 封面就空了 — 宁可用先验缩放"


def test_offstage_characters_stay_off_the_cover():
    _put_sprite("live", _person())
    _put_sprite("ghost", _person())
    story = _story("s_off", characters=[{"id": "live", "name": "在"},
                                        {"id": "ghost", "name": "幽", "presence": "offstage"}])
    assert cover.build(story)["cast"] == 1
