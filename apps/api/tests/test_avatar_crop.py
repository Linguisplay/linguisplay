# -*- coding: utf-8 -*-
"""📇 头像从立绘裁 —— 2026-08-13 实弹回归。

出事经过: avatar_from_base 只在「透底 webp 与 _src.jpg 同尺寸」时才按人形定位,
可 webp 出厂就过了 trim_alpha, 尺寸永远不等 —— 于是那条分支实际上是死的, 每次
都走回落: 在 720×1280 的全身立绘上取 720×720 顶部方窗。全身立绘里头只占高度的
八分之一, 那个方窗裁出来是「小小的头 + 半身 + 一整片背景」, 当头像看就是一团乱。
"""
import io

from PIL import Image

from app.engine import sprites
from app.engine.sprites import _head_window, avatar_from_base


def test_head_window_is_a_head_not_the_whole_frame():
    """全身立绘框: 方窗得是头胸的量级, 不是 min(w,h)。"""
    # 720×1280 里头宽约 110px
    left, top, side = _head_window(720, 1280, (0, 0, 720, 1280), (300, 410))
    assert side < 720, "又取了整幅宽 —— 那是半身照不是头像"
    assert 0 <= left <= 720 - side and 0 <= top <= 1280 - side


def test_head_window_follows_the_head_not_the_center():
    """人偏在画面一侧时, 方窗跟着头走。"""
    bb = (0, 0, 800, 1400)
    l_left, _, side = _head_window(800, 1400, bb, (70, 170))
    l_mid, _, _ = _head_window(800, 1400, bb, (350, 450))
    assert l_left < l_mid
    assert l_left >= 0 and l_mid + side <= 800


def test_landscape_source_still_gets_a_real_window():
    """横版素材 (上传的剧照就是这样): 窗口按头宽走, 不能被画幅高压成一条缝。

    实弹: 旧写法 side=0.42*h, 1052×608 的剧照只剩 255px 窗 —— 裁出来是块空底。
    """
    _, _, side = _head_window(1052, 608, (0, 0, 1052, 608), (500, 640))
    assert side >= 300, f"横版窗口塌成 {side}px —— 又按画幅高算了"
    assert side <= 608


def test_crops_from_the_trimmed_cutout(tmp_path, monkeypatch):
    """抠好的透底立绘是**唯一**该吃的源 —— 尺寸和 _src 对不上也照样定位。

    造一张 300×900 的透底立绘: 头是左上角一块不透明色块, 其余全透明。
    裁出来的头像必须以那块色块为主, 而不是一片垫底色。
    """
    monkeypatch.setattr(sprites, "SPRITE_DIR", tmp_path)
    im = Image.new("RGBA", (300, 900), (0, 0, 0, 0))
    # 头: 左侧 x∈[40,140), 顶部 y∈[0,150) 的红块
    for x in range(40, 140):
        for y in range(150):
            im.putpixel((x, y), (220, 40, 40, 255))
    im.save(tmp_path / "hero.webp")
    # 同名 _src 故意给个**不同尺寸**的干扰图 (旧代码就是被这个尺寸差绊住的)
    Image.new("RGB", (720, 1280), (10, 200, 10)).save(tmp_path / "hero_src.jpg")

    out = avatar_from_base("hero")
    assert out, "有透底立绘却没裁出头像"
    av = Image.open(io.BytesIO(out)).convert("RGB")
    assert av.width == av.height, "头像必须是方的"
    px = av.load()
    red = sum(1 for x in range(0, av.width, 4) for y in range(0, av.height, 4)
              if px[x, y][0] > 150 and px[x, y][1] < 110)
    total = len(range(0, av.width, 4)) * len(range(0, av.height, 4))
    assert red / total > 0.15, f"头只占 {red / total:.0%} —— 方窗没对准人"
    green = sum(1 for x in range(0, av.width, 4) for y in range(0, av.height, 4)
                if px[x, y][1] > 150 and px[x, y][0] < 110)
    assert green == 0, "吃到 _src.jpg 了 —— 该吃的是抠好的透底立绘"


def test_no_sources_means_fall_back_to_t2i(tmp_path, monkeypatch):
    """两个源都没有 → None, 让调用方去 t2i (别返回一张垫底色)。"""
    monkeypatch.setattr(sprites, "SPRITE_DIR", tmp_path)
    assert avatar_from_base("nobody") is None
