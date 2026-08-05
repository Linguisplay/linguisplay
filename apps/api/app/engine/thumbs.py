# -*- coding: utf-8 -*-
"""🖼 卡面缩略图: 把书架图从 1.65MB 压到几十 KB。

实弹 2026-08-05 (线上真机计量): 大厅一次冷开要下 8 张原始背景图 = 1,727,144 字节,
而卡片槽位只有 430×237 (DPR2 = 860×474)。逐张看: gh_basecamp 1024×1536 竖图 365KB
被裁成横缩略图、sk_shotengai 262KB、mh_hall 293KB…… 按出口实测 110KB/s 是 16.6 秒,
按中位吞吐 46.6KB/s 是 39 秒 —— 一个还没决定要不要玩的人, 得先替你下 1.7MB 美术。
而且这些图是 CSS background-image, 浏览器的 lazy 根本够不着, 8 张一起发。

为什么不用已有的自动封面 (engine/cover.py): 那套被 Yi 2026-08-02 关掉了
(ENABLED=False, 「看起来太糟糕了」—— 实看确实糟: 人物挤在右下角、左边三分之二空,
第三张人物还被下边缘切掉)。产品决定不翻, 换个不依赖它的解法。

做法: 按需生成、落盘、永久复用。第一次请求某张卡面时压一张 webp, 之后直接命中。
不改任何生图管线、不动作者的美术真相 —— 只是别把 4K 原图塞进 430px 的槽。
"""
from __future__ import annotations

import pathlib

# 卡片槽位 430×237, DPR2 → 860 宽足够; 再大肉眼看不出, 只是白付带宽
THUMB_W = 860
THUMB_Q = 72          # webp 质量: 72 在这种照片/插画上肉眼无损, 体积约为原图的 5~10%

_STATIC = pathlib.Path(__file__).resolve().parents[1] / "static" / "scene"
_THUMB_DIR = _STATIC / "thumb"


def thumb_url(rel: str | None) -> str | None:
    """把一个 /scene/... 图片地址换成它的缩略图地址 (压不出来就原样返回)。

    rel 形如 "/scene/bg/kf_tintoi.jpg"。返回 "/scene/thumb/bg__kf_tintoi.webp"。
    压缩失败 (缺 Pillow / 文件不在 / 格式怪) 一律降级回原图 —— 书架宁可慢, 不可空。
    """
    if not rel or not rel.startswith("/scene/"):
        return rel
    src_rel = rel.split("?", 1)[0][len("/scene/"):]
    src = _STATIC / src_rel
    if not src.is_file():
        return rel
    # 目录扁平化进文件名: bg/kf_tintoi.jpg → bg__kf_tintoi.webp
    stem = src_rel.rsplit(".", 1)[0].replace("/", "__").replace("\\", "__")
    out = _THUMB_DIR / f"{stem}.webp"
    try:
        if out.is_file() and out.stat().st_mtime >= src.stat().st_mtime:
            return f"/scene/thumb/{out.name}"
        if not _build(src, out):
            return rel
        return f"/scene/thumb/{out.name}"
    except OSError:
        return rel


def _build(src: pathlib.Path, out: pathlib.Path) -> bool:
    """压一张。失败返回 False, 调用方降级回原图 —— 绝不因为缩略图挂了就没有卡面。"""
    try:
        from PIL import Image
    except Exception:
        return False
    try:
        _THUMB_DIR.mkdir(parents=True, exist_ok=True)
        with Image.open(src) as im:
            im = im.convert("RGB")
            if im.width > THUMB_W:
                h = max(1, round(im.height * THUMB_W / im.width))
                im = im.resize((THUMB_W, h), Image.LANCZOS)
            tmp = out.with_suffix(".webp.part")
            im.save(tmp, "WEBP", quality=THUMB_Q, method=4)
        tmp.replace(out)      # 原子落盘: 半张图绝不占用正式名字
        return True
    except Exception:
        try:
            out.with_suffix(".webp.part").unlink(missing_ok=True)
        except OSError:
            pass
        return False
