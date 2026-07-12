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

from .gal import debg, to_webp, trim_alpha
from .qwen import edit_image

_STATIC = Path(__file__).resolve().parents[1] / "static" / "scene"
SPRITE_DIR = _STATIC / "sprite"
AVATAR_DIR = _STATIC / "avatar"

_KEEP = ("。铁律：变化幅度必须很小，是电影演员的微表情，不是漫画式夸张——"
         "不瞪眼、不呲牙、不张大嘴、五官不变形。严格保持同一个人：发型、五官、"
         "服装、姿势、构图、光线、背景完全不变，只做面部肌肉的细微调整，"
         "画风质感与原图完全一致")
EXPRS: dict[str, str] = {
    "喜": "让人物的嘴角极轻微地上扬，眼神柔和一分，像忍着没说出口的愉快" + _KEEP,
    "怒": "让人物的眉头微微收紧，眼神冷下来一分，嘴唇轻轻抿住，像压着火没发作" + _KEEP,
    "哀": "让人物的眼神黯淡失焦一分，眉梢微垂，嘴角轻轻向下，像心里沉了一块石头" + _KEEP,
    "惊": "让人物的眼睛稍稍睁大一点，眉梢微挑，嘴唇微启，像刚听见不该听见的话" + _KEEP,
}


def base_of(cid: str) -> Path | None:
    """改脸差分的底图: 立绘源图 (带背景, 编辑器吃这个) → 旧版立绘 jpg → 头像."""
    for p in (SPRITE_DIR / f"{cid}_src.jpg", SPRITE_DIR / f"{cid}.jpg",
              AVATAR_DIR / f"{cid}.jpg"):
        if p.exists():
            return p
    return None


def ingest_upload(cid: str, data: bytes) -> dict[str, Any]:
    """🖼 玩家上传的人物图 → 智能裁剪三件套 (Yi 定):
    ① 透底立绘: rembg 找人抠底 + 裁 alpha 包围盒 → sprite/{cid}.webp
    ② 改脸源图: 原图瘦身留档 → sprite/{cid}_src.jpg (表情差分继续可做)
    ③ 方形头像: 以人形包围盒顶部为中心取方窗 (脸在人形上部) → avatar/{cid}.jpg
    旧表情差分随之作废删除 (那是旧脸)。rembg 失败自动退化为居中裁切。"""
    import io as _io

    from PIL import Image

    from .gal import debg, shrink_jpg, to_webp, trim_alpha
    SPRITE_DIR.mkdir(parents=True, exist_ok=True)
    AVATAR_DIR.mkdir(parents=True, exist_ok=True)
    im = Image.open(_io.BytesIO(data)).convert("RGB")

    cut = debg(data)
    (SPRITE_DIR / f"{cid}.webp").write_bytes(to_webp(trim_alpha(cut)))
    (SPRITE_DIR / f"{cid}_src.jpg").write_bytes(shrink_jpg(data, quality=85, max_side=1280))

    box = None
    try:
        ci = Image.open(_io.BytesIO(cut))
        if ci.mode == "RGBA" and ci.size == im.size:
            box = ci.getchannel("A").getbbox()
    except Exception:
        pass
    if box and box[2] > box[0]:
        side = max(64, min(int((box[2] - box[0]) * 1.25), im.width, im.height))
        cx = (box[0] + box[2]) // 2
        left = max(0, min(cx - side // 2, im.width - side))
        top = max(0, min(box[1] - side // 12, im.height - side))
    else:   # 没抠出人 → 居中方裁兜底
        side = min(im.size)
        left, top = (im.width - side) // 2, max(0, (im.height - side) // 4)
        top = min(top, im.height - side)
    av = im.crop((left, top, left + side, top + side))
    buf = _io.BytesIO()
    av.save(buf, format="JPEG", quality=88)
    (AVATAR_DIR / f"{cid}.jpg").write_bytes(shrink_jpg(buf.getvalue(), quality=85, max_side=768))

    removed = 0
    for e in EXPRS:
        for suffix in (".webp", ".jpg"):
            p = SPRITE_DIR / f"{cid}_{e}{suffix}"
            if p.exists():
                p.unlink()
                removed += 1
    return {"sprite": f"/scene/sprite/{cid}.webp",
            "avatar": f"/scene/avatar/{cid}.jpg",
            "smart": bool(box), "stale_exprs_removed": removed}


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
            out_path = SPRITE_DIR / f"{cid}_{expr}.webp"
            if out_path.exists() and not force:
                report["skipped"].append(out_path.name)
                continue
            img = edit_image(raw, EXPRS[expr], mime="image/jpeg")
            if not img:
                report["failed"].append(out_path.name)
                continue
            # 🎭 差分同样上台前抠底+裁边 — 换表情不许换出背景板, 也不许缩一圈
            out_path.write_bytes(to_webp(trim_alpha(debg(img))))
            report["done"].append(out_path.name)
    return report
