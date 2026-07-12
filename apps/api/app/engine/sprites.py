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


def _tavily_images(query: str, cap: int = 6) -> list[str]:
    """Tavily 图搜: 返回候选图片 URL (无 key / 失败 = 空)."""
    import httpx

    from ..config import get_settings
    s = get_settings()
    if not s.tavily_api_key:
        return []
    try:
        r = httpx.post("https://api.tavily.com/search",
                       json={"api_key": s.tavily_api_key, "query": query,
                             "include_images": True, "max_results": 5},
                       timeout=25)
        return [u for u in (r.json().get("images") or []) if isinstance(u, str)][:cap]
    except Exception:
        return []


def _fetch_person_image(urls: list[str]) -> bytes | None:
    """候选里选第一张「站得住」的: 能下载、够大、rembg 能找出一个像样的人形."""
    import io as _io

    import httpx
    from PIL import Image

    from .gal import debg
    for u in urls:
        try:
            r = httpx.get(u, timeout=20, follow_redirects=True,
                          headers={"User-Agent": "Mozilla/5.0"})
            data = r.content
            if r.status_code != 200 or not data or len(data) > 8 * 1024 * 1024:
                continue
            im = Image.open(_io.BytesIO(data))
            if min(im.size) < 420:
                continue
            cut = Image.open(_io.BytesIO(debg(data)))
            if cut.mode != "RGBA":
                continue
            box = cut.getchannel("A").getbbox()
            if not box:
                continue
            bh, bw = box[3] - box[1], box[2] - box[0]
            if bh < im.height * 0.4 or bw < 60:   # 人形太小/太碎 = 海报文字或群像远景
                continue
            return data
        except Exception:
            continue
    return None


def smart_cast(content: dict[str, Any], cids: list[str] | None = None) -> dict[str, Any]:
    """🔍 主角智能搜图 (Yi: 主要角色都智能搜索一下): 每个角色按「故事名+角色名+剧照」
    搜真图 → 选图 → 按剧本画风改绘 (动漫店改绘成赛璐璐立绘, 写实店原样) →
    ingest 三件套。玩家亲选的脸 (generated=False) 不动。"""
    from .qwen import edit_image
    story = content.get("story") or {}
    title = (story.get("title") or "").strip()
    art = str((story.get("tuning") or {}).get("art_style") or "")
    anime = any(k in art for k in ("动漫", "二次元", "赛璐璐", "水彩", "插画", "漫画", "国漫"))
    report: dict[str, Any] = {"done": [], "no_image": [], "convert_failed": [], "skipped": []}
    for c in story.get("characters") or []:
        cid, name = c.get("id"), c.get("name")
        if not cid or not name or (cids and cid not in cids):
            continue
        if c.get("generated") is False:   # 玩家亲选的脸不动
            report["skipped"].append(cid)
            continue
        raw = _fetch_person_image(_tavily_images(f"{title} {name} 剧照 高清"))
        if raw is None:
            raw = _fetch_person_image(_tavily_images(f"{name} {title} still photo"))
        if raw is None:
            report["no_image"].append(cid)
            continue
        img = raw
        if anime:
            # 改绘吃剧本自己的美术圣经 — 全员一套 token, 不许各自发挥 (出戏元凶)
            img = edit_image(raw, f"把这张照片改绘成这种画风的游戏立绘：{art[:220]}。"
                                  "严格按这个画风执行，严格保持人物的发型、五官特征、"
                                  "服装和姿势完全一致，只改画风",
                             mime="image/jpeg") or None
            if not img:
                report["convert_failed"].append(cid)
                continue
        ingest_upload(cid, img)
        report["done"].append(cid)
    return report


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
