# -*- coding: utf-8 -*-
"""🎭 沙盒表情差分管线 — gal 管线的正解移植: 差分不重画, 在常态底图上改脸.

底图优先级: /scene/sprite/{cid}.jpg (VN 立绘) → /scene/avatar/{cid}.jpg (头像).
差分落盘: /scene/sprite/{cid}_{expr}.jpg — 客户端 vnSprite 按 beat.expr 换脸,
文件缺失时静默回落到底图 (演出永不因缺素材而断).

法度: 编辑而非重生成 (身份/构图/光线像素级一致); 失败静默跳过, 可重跑补齐;
出生即瘦身 (小水管服务器)。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .gal import shrink_jpg
from .qwen import edit_image

_STATIC = Path(__file__).resolve().parents[1] / "static" / "scene"
SPRITE_DIR = _STATIC / "sprite"
AVATAR_DIR = _STATIC / "avatar"

_KEEP = ("。严格保持同一个人：发型、五官、服装、姿势、构图、光线、背景完全不变，"
         "只改变面部表情，保持写实照片质感")
EXPRS: dict[str, str] = {
    "喜": "把人物的表情改成克制的浅笑，嘴角微微上扬，眼神放松了一点" + _KEEP,
    "怒": "把人物的表情改成压着火的愠怒，眉头紧锁，眼神冷硬，嘴唇抿紧" + _KEEP,
    "哀": "把人物的表情改成黯然的难过，眉眼低垂，眼神失焦向下" + _KEEP,
    "惊": "把人物的表情改成受惊的紧张，双眼睁大，眉毛上挑，嘴唇微张" + _KEEP,
}


def base_of(cid: str) -> Path | None:
    """The character's best available base image (立绘优先, 头像兜底)."""
    for d in (SPRITE_DIR, AVATAR_DIR):
        p = d / f"{cid}.jpg"
        if p.exists():
            return p
    return None


def build_expr_pack(cids: list[str], exprs: list[str] | None = None,
                    force: bool = False) -> dict[str, Any]:
    """Edit-generate the expression diffs for these characters. Sequential and
    idempotent — rerun to backfill failures. Returns a per-file report."""
    todo = list(exprs or EXPRS.keys())
    report: dict[str, Any] = {"done": [], "skipped": [], "failed": [], "no_base": []}
    SPRITE_DIR.mkdir(parents=True, exist_ok=True)
    for cid in cids:
        base = base_of(cid)
        if base is None:
            report["no_base"].append(cid)
            continue
        raw = base.read_bytes()
        for expr in todo:
            if expr not in EXPRS:
                continue
            out_path = SPRITE_DIR / f"{cid}_{expr}.jpg"
            if out_path.exists() and not force:
                report["skipped"].append(out_path.name)
                continue
            img = edit_image(raw, EXPRS[expr], mime="image/jpeg")
            if not img:
                report["failed"].append(out_path.name)
                continue
            out_path.write_bytes(shrink_jpg(img, quality=82, max_side=1024))
            report["done"].append(out_path.name)
    return report
