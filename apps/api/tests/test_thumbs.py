# -*- coding: utf-8 -*-
"""🖼 卡面缩略图 (2026-08-05 线上实测促成):

大厅一次冷开下 8 张原始背景图 = 1,727,144 字节, 而卡片槽位只有 430×237。
按出口 110KB/s 是 16.6 秒 —— 一个还没决定要不要玩的人先替你下 1.7MB。

这条测试守两件事: 压得动的要压小, 压不动的要【原样降级】(书架宁可慢, 不可空)。
"""
import pathlib

import pytest

from app.engine import thumbs

pytest.importorskip("PIL", reason="缩略图靠 Pillow; 没装就跳过(生产有装)")


@pytest.fixture()
def big_bg(tmp_path, monkeypatch):
    """造一张 1600×900 的假背景图, 并把静态根指过去。"""
    from PIL import Image
    static = tmp_path / "scene"
    (static / "bg").mkdir(parents=True)
    src = static / "bg" / "probe.jpg"
    Image.new("RGB", (1600, 900), (90, 70, 40)).save(src, "JPEG", quality=92)
    monkeypatch.setattr(thumbs, "_STATIC", static)
    monkeypatch.setattr(thumbs, "_THUMB_DIR", static / "thumb")
    return src


def test_it_actually_shrinks(big_bg):
    url = thumbs.thumb_url("/scene/bg/probe.jpg")
    assert url == "/scene/thumb/bg__probe.webp", url
    out = thumbs._THUMB_DIR / "bg__probe.webp"
    assert out.is_file()
    assert out.stat().st_size < big_bg.stat().st_size, "没压小 — 那还不如不压"
    from PIL import Image
    with Image.open(out) as im:
        assert im.width <= thumbs.THUMB_W


def test_second_call_reuses_the_file(big_bg):
    thumbs.thumb_url("/scene/bg/probe.jpg")
    out = thumbs._THUMB_DIR / "bg__probe.webp"
    first = out.stat().st_mtime_ns
    thumbs.thumb_url("/scene/bg/probe.jpg")
    assert out.stat().st_mtime_ns == first, "每次请求都重压 — 白烧 CPU"


def test_source_newer_than_thumb_rebuilds(big_bg):
    """换了底图就要重压 —— 不然玩家一直看旧封面。

    断言看的是「文件被重写了」(mtime 变了), 不是「比源图新」: 源图的时间被我们
    人为拨到了未来, 而重压出来的缩略图盖的是【当前】时间, 天然比它旧。"""
    import os
    thumbs.thumb_url("/scene/bg/probe.jpg")
    out = thumbs._THUMB_DIR / "bg__probe.webp"
    before = out.stat().st_mtime_ns
    future = out.stat().st_mtime + 10
    os.utime(big_bg, (future, future))
    thumbs.thumb_url("/scene/bg/probe.jpg")
    assert out.stat().st_mtime_ns != before, "换了图还在发旧缩略图"


def test_missing_file_degrades_to_original(big_bg):
    """压不出来时必须原样返回 —— 书架宁可慢, 不可空。"""
    assert thumbs.thumb_url("/scene/bg/nope.jpg") == "/scene/bg/nope.jpg"


def test_non_scene_urls_pass_through():
    assert thumbs.thumb_url(None) is None
    assert thumbs.thumb_url("https://x.com/a.jpg") == "https://x.com/a.jpg"
    assert thumbs.thumb_url("/other/a.jpg") == "/other/a.jpg"


def test_pillow_missing_degrades(big_bg, monkeypatch):
    """没有 Pillow 也不许把卡面搞没。"""
    monkeypatch.setattr(thumbs, "_build", lambda *a, **k: False)
    assert thumbs.thumb_url("/scene/bg/probe.jpg") == "/scene/bg/probe.jpg"
