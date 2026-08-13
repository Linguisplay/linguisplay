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

# 🧍 动作差分 (Yi 2026-07-21: 角色的动作可以增加, 但角色不能崩) — 同一条改图管线,
# 幅度铁律换成动作版: 脸和身份钉死, 只动手臂和上半身, 双脚不挪 (挪脚=重新构图=崩相)。
_KEEP_ACT = ("。铁律：这是同一张立绘的动作差分——严格保持同一个人：发型、五官、表情、"
             "服装、体型、站位、构图、光线、背景、画风完全不变，双脚位置不动，"
             "取景范围也不变（半身像仍是半身像，绝不把画面拉远画出全身或凭空补出腿脚），"
             "只按要求调整手臂与上半身，动作自然克制，像真人演员的小动作，不夸张不变形")
POSES: dict[str, str] = {
    "挥手": "让人物抬起一只手，在胸口到肩膀的高度轻轻挥手打招呼，另一只手自然下垂" + _KEEP_ACT,
    "抱臂": "让人物双臂在胸前交叉环抱，肩膀微微收紧，带一点防备的意味" + _KEEP_ACT,
    "低头": "让人物微微低下头，视线落向地面，肩膀轻轻垮下一点" + _KEEP_ACT,
    "伸手": "让人物向画面前方伸出一只手，掌心向上，像在递东西或发出邀请" + _KEEP_ACT,
}
DIFFS: dict[str, str] = {**EXPRS, **POSES}


def _intact(cut: bytes, cid: str) -> bool:
    """🩺 崩-gate: 差分上台前的确定性体检 — 抠完必须还有一个像样的人形, 且轮廓
    与常态底图的差距在动作幅度以内 (人没了/人缩了/画面炸了一票否)。脸崩这里
    测不出, 靠编辑铁律压着; 被否的差分不落盘, 客户端自然回落常态底 — 宁可不动,
    不可崩相。"""
    import io as _io

    from PIL import Image
    try:
        im = Image.open(_io.BytesIO(cut))
    except Exception:
        return False
    if im.mode == "RGBA" and not im.getchannel("A").getbbox():
        return False   # 全透明 = 人没了 (无 alpha 通道不算罪 — 宁可少限制)
    base = SPRITE_DIR / f"{cid}.webp"
    if not base.exists():
        return True
    try:
        bw, bh = Image.open(base).size
    except Exception:
        return True
    w, h = im.size   # 两边都过了 trim_alpha, 尺寸即人形轮廓
    if not bw or not bh:
        return True
    return 0.66 <= h / bh <= 1.4 and 0.5 <= w / bw <= 2.0


def base_of(cid: str) -> Path | None:
    """改脸差分的底图: 立绘源图 (带背景, 编辑器吃这个) → 旧版立绘 jpg → 头像."""
    for p in (SPRITE_DIR / f"{cid}_src.jpg", SPRITE_DIR / f"{cid}.jpg",
              AVATAR_DIR / f"{cid}.jpg"):
        if p.exists():
            return p
    return None


def _head_window(w: int, h: int, cx: int | None = None) -> tuple[int, int, int]:
    """站姿立绘里的头胸方窗。

    ⚠️ 别用 side=min(w,h) (2026-08-13 实弹): 全身立绘框是 720×1280, 头只占
    高度的八分之一左右, 取 720×720 等于把「头+半身+一整片背景」当头像。
    0.42*h 才是头胸特写的量级。cx 为空时按水平居中。"""
    side = max(64, min(w, int(h * 0.42)))
    cx = w // 2 if cx is None else cx
    return max(0, min(cx - side // 2, w - side)), 0, side


def avatar_from_base(cid: str) -> bytes | None:
    """📇 头像同脸捷径 (Yi 2026-07-15: 手机头像也要形象稳定): 有立绘的角色, 头像
    直接从立绘裁 — 零成本且与立绘绝对同脸, 不再单独 t2i 一张新想象的脸。

    **优先吃透底 webp**, 不吃 _src.jpg: 人物已经被抠出来, 头的水平位置可以从
    alpha 量出来, 而且背景里的招牌/建筑不会被一起裁进头像。
    (旧写法要求 webp 与 _src 同尺寸才定位, 但 webp 出厂就被 trim_alpha 裁过,
     这条件实际上永远不成立 —— 于是一直在走那个错的回落分支。)
    两个源都没有则返回 None, 调用方回落 t2i。"""
    import io as _io

    from PIL import Image

    from .gal import shrink_jpg
    cut, src = SPRITE_DIR / f"{cid}.webp", SPRITE_DIR / f"{cid}_src.jpg"
    try:
        if cut.exists():
            ci = Image.open(cut)
            if ci.mode == "RGBA":
                a = ci.getchannel("A")
                w, h = ci.size
                # 头的水平中心: 只看最上面那道横条, 别被伸开的手臂/裙摆带偏
                strip = a.crop((0, 0, w, max(1, int(h * 0.18)))).getbbox()
                cx = (strip[0] + strip[2]) // 2 if strip else None
                left, top, side = _head_window(w, h, cx)
                # 透底 → 头像要落地成 jpg, 垫一层深底 (和暗色 UI 同调)
                flat = Image.new("RGB", (side, side), (26, 26, 28))
                win = ci.crop((left, top, left + side, top + side))
                flat.paste(win, (0, 0), win)
                buf = _io.BytesIO()
                flat.save(buf, format="JPEG", quality=88)
                return shrink_jpg(buf.getvalue(), quality=85, max_side=768)
    except Exception:
        pass
    if not src.exists():
        return None
    try:    # 没抠图: 只能按惯例居中取头胸窗
        im = Image.open(src).convert("RGB")
    except Exception:
        return None
    left, top, side = _head_window(im.width, im.height)
    buf = _io.BytesIO()
    im.crop((left, top, left + side, top + side)).save(buf, format="JPEG", quality=88)
    return shrink_jpg(buf.getvalue(), quality=85, max_side=768)


def ingest_upload(cid: str, data: bytes, keep_photo: bytes | None = None) -> dict[str, Any]:
    """🖼 玩家上传的人物图 → 智能裁剪三件套 (Yi 定):
    ① 透底立绘: rembg 找人抠底 + 裁 alpha 包围盒 → sprite/{cid}.webp
    ② 改脸源图: 原图瘦身留档 → sprite/{cid}_src.jpg (表情差分继续可做)
    ③ 方形头像: 以人形包围盒顶部为中心取方窗 (脸在人形上部) → avatar/{cid}.jpg
    旧表情差分随之作废删除 (那是旧脸)。rembg 失败自动退化为居中裁切。"""
    import io as _io

    from PIL import Image

    from .gal import shrink_jpg
    SPRITE_DIR.mkdir(parents=True, exist_ok=True)
    AVATAR_DIR.mkdir(parents=True, exist_ok=True)
    im = Image.open(_io.BytesIO(data)).convert("RGB")

    cut = debg(data)
    (SPRITE_DIR / f"{cid}.webp").write_bytes(to_webp(trim_alpha(cut)))
    (SPRITE_DIR / f"{cid}_src.jpg").write_bytes(shrink_jpg(data, quality=85, max_side=1280))
    if keep_photo:
        # 📷 原始照片永久留档: 换画风永远从真照片出发 — 在改绘结果上再改绘,
        # 三轮就面目全非 (实弹: 四仔被叠加改绘改到变性)
        (SPRITE_DIR / f"{cid}_photo.jpg").write_bytes(
            shrink_jpg(keep_photo, quality=85, max_side=1280))

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
    for e in DIFFS:
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


def look_bits(c: dict[str, Any]) -> str:
    """🚻 性别/年龄从卡上走 (角色卡 v2): 「武备官/佣兵」这类词会被生图模型脑补成
    男性 — 实弹: 女武备官的立绘画成了男骑士, 头像另一条提示词碰巧画对, 同脸法随之破。"""
    sp = (c.get("species") or "").strip()
    g = (c.get("gender") or "").strip()
    if sp and sp not in ("人", "人类"):
        # 🐱 非人角色: 性别词换物种语系, 并硬性排除人类身影
        g = {"男": "公", "女": "母"}.get(g, "")
        return f"{g}{sp}，画面中只有这只{sp}——绝不出现任何人类或人形身影"
    g = {"男": "男性", "女": "女性"}.get(g, g)
    return "，".join(x for x in (g, (c.get("age_band") or "").strip()) if x)


# 📐 取景语 —— 全站头像共用这一句。同人管线 (enrich_portraits) 正向条款不同,
# 但取景必须一致, 否则同一个人在不同入口画出来的构图对不上。
PORTRAIT_FRAME = ("人物肖像，胸像特写，正面微侧，目光看向镜头外，"
                  "柔和的侧光，背景虚化，情绪克制内敛")


def portrait_prompt(c: dict[str, Any], world: str, art: str) -> str:
    """🎨 头像提示词——**唯一**一份配方。

    ⚠️ 别再抄一份 (Yi 2026-08-13 报障):
    backfill_avatars.py 曾私藏一份注释写着「same recipe」的复制品, 但四道保护
    一个都没有, 于是十二少那张把整块数值卡当画面文字画进了图里
    (persona_text 开头就是「战力：8.5/10 / 颜值：7.5/10 / 身高：180cm…」)。
    四道保护缺一不可, 而且必须和调用方的 negative/seed 配套:
      ① art 压在最前 —— 画风定调, 不放句尾被人物描述盖过
      ② look_bits —— 性别/年龄/物种硬写, 不让模型按职业脑补
      ③ 调用方传 negative (末尾含「文字,水印」) —— 挡住数值卡被画成字
      ④ 调用方传 seed —— 同角色重画不换脸
    """
    bits = "，".join(b for b in (c.get("name"), look_bits(c), c.get("role") or "",
                                 (c.get("persona_text") or "")[:160]) if b)
    head = f"{art}。" if (art or "").strip() else ""      # 玩家人设没有剧本画风
    tail = f"。世界背景：{world}" if (world or "").strip() else ""
    return f"{head}{PORTRAIT_FRAME}：{bits}{tail}"


def char_importance(c: dict[str, Any]) -> int:
    """🏅 人物重要性 (Yi: 智能检索要给人物重要性排名): 主角位/恋爱位/有人生目标/
    有人物网/作者亲写的角色排前面 — 美术预算和生成顺序都按这个来, 限流时
    重要的脸先落地。分数越大越重要。"""
    score = 0
    if c.get("is_lead"):
        score += 4
    if c.get("love_style"):
        score += 2
    if (str((c.get("life_goal") or {}).get("text") or "") or c.get("wants")
            or c.get("agenda") or "").strip():
        score += 1
    score += min(2, len(c.get("ties") or []))
    if not c.get("generated"):
        score += 1
    return score


def rank_cast(chars: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Importance-ordered cast (stable within equal scores — authored order breaks ties)."""
    return sorted(chars, key=char_importance, reverse=True)


def smart_cast(content: dict[str, Any], cids: list[str] | None = None) -> dict[str, Any]:
    """🔍 主角智能搜图 (Yi: 主要角色都智能搜索一下): 每个角色按「故事名+角色名+剧照」
    搜真图 → 选图 → 按剧本画风改绘 (动漫店改绘成赛璐璐立绘, 写实店原样) →
    ingest 三件套。玩家亲选的脸 (generated=False) 不动。"""
    from .gal import is_anime_style
    from .qwen import edit_image
    story = content.get("story") or {}
    title = (story.get("title") or "").strip()
    art = str((story.get("tuning") or {}).get("art_style") or "")
    anime = is_anime_style(art)
    report: dict[str, Any] = {"done": [], "no_image": [], "convert_failed": [], "skipped": [],
                              # 🏅 重要性排名随报告下发: 谁先被检索/花预算一目了然
                              "ranking": [{"id": c.get("id"), "name": c.get("name"),
                                           "importance": char_importance(c)}
                                          for c in rank_cast(story.get("characters") or [])]}
    for c in rank_cast(story.get("characters") or []):
        cid, name = c.get("id"), c.get("name")
        if not cid or not name or (cids and cid not in cids):
            continue
        if c.get("generated") is False:   # 玩家亲选的脸不动
            report["skipped"].append(cid)
            continue
        # 换画风重刷优先用留档的原始照片, 没有才去搜
        photo_file = SPRITE_DIR / f"{cid}_photo.jpg"
        raw = photo_file.read_bytes() if photo_file.exists() else None
        if raw is None:
            raw = _fetch_person_image(_tavily_images(f"{title} {name} 剧照 高清"))
        if raw is None:
            raw = _fetch_person_image(_tavily_images(f"{name} {title} still photo"))
        if raw is None:
            report["no_image"].append(cid)
            continue
        img = raw
        if anime:
            # 改绘铁律 (实弹翻车教训): 保真条款放最前, 画风只给一句核心 —
            # 整部圣经塞进编辑指令会把「保持人物」冲掉 (性别都能改没)
            core = art.split("；")[0][:120]
            img = edit_image(raw, "严格保持照片中人物的性别、体格、发型、五官特征、"
                                  f"服装和姿势完全一致，只把画风改绘为：{core}。"
                                  "不改变人物的任何特征，只改画风",
                             mime="image/jpeg") or None
            if not img:
                report["convert_failed"].append(cid)
                continue
        ingest_upload(cid, img, keep_photo=raw)
        report["done"].append(cid)
    return report


def build_expr_pack(cids: list[str], exprs: list[str] | None = None,
                    force: bool = False,
                    no_pose_cids: set[str] | frozenset = frozenset()) -> dict[str, Any]:
    """Edit-generate the expression AND pose diffs for these characters. Sequential
    and idempotent — rerun to backfill failures. no_pose_cids: 非人形角色 (species)
    跳过人类肢体动作, 只做表情. Returns a per-file report."""
    todo = list(exprs or DIFFS.keys())
    report: dict[str, Any] = {"done": [], "skipped": [], "failed": [],
                              "no_base": [], "broken": []}
    SPRITE_DIR.mkdir(parents=True, exist_ok=True)
    for cid in cids:
        base = base_of(cid)
        if base is None:
            report["no_base"].append(cid)
            continue
        raw = base.read_bytes()
        for expr in todo:
            if expr not in DIFFS or (expr in POSES and cid in no_pose_cids):
                continue
            out_path = SPRITE_DIR / f"{cid}_{expr}.webp"
            if out_path.exists() and not force:
                report["skipped"].append(out_path.name)
                continue
            img = edit_image(raw, DIFFS[expr], mime="image/jpeg")
            if not img:
                report["failed"].append(out_path.name)
                continue
            # 🎭 差分同样上台前抠底+裁边 — 换表情不许换出背景板, 也不许缩一圈
            cut = to_webp(trim_alpha(debg(img)))
            if not _intact(cut, cid):   # 🩺 崩了不上台 (角色不能崩 — Yi 铁律)
                report["broken"].append(out_path.name)
                continue
            out_path.write_bytes(cut)
            report["done"].append(out_path.name)
    return report
