# -*- coding: utf-8 -*-
"""🎴 自动封面 — 每本剧本/沙盒都长一张 galgame 盒绘: 班底站中间, 版式带设计。

为什么是【合成】不是【再生一张图】(Yi 2026-08-01 提需求时当场定的):
  · 脸要对得上 —— 封面上的人必须就是游戏里那个人。重新 t2i 一张五人同框,
    模型既保不住同脸, 五个人还会画成六个半。我们手里已经有每个角色本人的
    透底立绘 (/scene/sprite/{cid}.webp, 抠好底裁好边), 直接摆上台。
  · 要能给玩家用 —— 玩家自己做的剧本也得有封面。生图要钱要排队要等,
    合成零成本毫秒级, 发布那一刻就有。
  · 要能自愈 —— 立绘是后来才陆续画出来的。封面按输入指纹判缺, 素材一变就重排,
    不需要谁记得去点一次"重新生成"。

两个尺寸出自同一次排版:
  · 海报 900×1200 (3:4) —— 真正的"盒绘", 标题烫在图上, 是个能单独拿出去的成品
  · 宽幅 1440×864 (16:9.6) —— 大厅 hero 卡的图床, 【不烫字】: 卡面的标题是
    HTML 排的 (任意 DPI 都锐、能跟着 UI 切语言), 烫上去只会撞成两个标题

不做的事: 不碰作者手填的 cover_url (那是作者的地盘, 自动封面永远排在它后面)。
"""
from __future__ import annotations

import hashlib
import io
import json
import math
from pathlib import Path
from typing import Any

_STATIC = Path(__file__).resolve().parents[1] / "static" / "scene"
SPRITE_DIR = _STATIC / "sprite"
AVATAR_DIR = _STATIC / "avatar"
BG_DIR = _STATIC / "bg"
COVER_DIR = _STATIC / "cover"

# 版式版本号: 改了排版/配色/字号就 +1 —— 指纹里带着它, 全站封面自动重排
ALGO = "d1"
# 三款版式。研究真封面 (Grisaia / 薄樱鬼 / Little Busters / Steins;Gate) 之后重做的 ——
# v1 那版是电影海报的做法 (标题在顶、班底站一排、整体压暗), Yi 一句「设计的不行」，对。
DEFAULT_STYLE = "gilt"        # Yi 2026-08-02 从三款里挑的

POSTER = (900, 1200)     # 3:4 盒绘
WIDE = (1440, 864)       # 16:9.6 —— 与 play.html .scard 的 aspect-ratio 对齐
MAX_CAST = 5


# ── 字体 ──────────────────────────────────────────────────────────────────
# 服务器上装 google-noto-serif-cjk-ttc-fonts 就有中文衬线; 本机开发用 Windows 自带。
# 一个都找不到时不是灾难 —— 海报退化成【无字版】(和宽幅同款), 图照出, 只是没标题。
_FONT_DIRS = [
    Path(__file__).resolve().parents[1] / "static" / "font",   # 仓库自带 (可选)
    Path("/usr/share/fonts"), Path("/usr/local/share/fonts"), Path.home() / ".fonts",
    Path("C:/Windows/Fonts"),
]
# 按偏好从前往后找; 每项 = (通配, 想要的 face 名关键词)
_DISPLAY_PATTERNS = [
    ("NotoSerifCJK*-Bold*", "SC"), ("NotoSerifCJKsc-Bold*", ""),
    ("SourceHanSerif*Bold*", "SC"), ("NotoSerifCJK*-SemiBold*", "SC"),
    ("STZHONGS.TTF", ""), ("simsun.ttc", ""), ("msyhbd.ttc", ""),
    ("NotoSerif-Bold.ttf", ""), ("DejaVuSerif-Bold.ttf", ""),
]
_BODY_PATTERNS = [
    ("NotoSansCJK*-Regular*", "SC"), ("NotoSansCJKsc-Regular*", ""),
    ("SourceHanSans*Regular*", "SC"), ("msyh.ttc", ""), ("Deng.ttf", ""),
    ("NotoSans-Regular.ttf", ""), ("DejaVuSans.ttf", ""),
]
_FONT_CACHE: dict = {}


def _find_font_file(patterns: list[tuple[str, str]]) -> tuple[str, str] | None:
    for pat, want in patterns:
        for root in _FONT_DIRS:
            if not root.exists():
                continue
            try:
                hits = sorted(root.rglob(pat))
            except OSError:
                continue
            if hits:
                return str(hits[0]), want
    return None


def _ttc_index(path: str, want: str) -> int:
    """.ttc 是字体集合 —— Noto CJK 一个文件里塞了 JP/KR/SC/TC 四张脸。挑简中那张;
    挑不出就用 0 (共享字形, 最多是异体字取了日文默认形, 不至于豆腐块)。"""
    if not want or not path.lower().endswith((".ttc", ".otc")):
        return 0
    from PIL import ImageFont
    for i in range(6):
        try:
            f = ImageFont.truetype(path, 20, index=i)
            if want.lower() in "".join(f.getname()).lower():
                return i
        except Exception:
            break
    return 0


def _font(kind: str, size: int):
    """kind: display(衬线粗) | body(黑体细)。找不到任何字体返回 None。"""
    key = (kind, size)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    from PIL import ImageFont
    found = _find_font_file(_DISPLAY_PATTERNS if kind == "display" else _BODY_PATTERNS)
    f = None
    if found:
        path, want = found
        try:
            f = ImageFont.truetype(path, size, index=_ttc_index(path, want))
        except Exception:
            f = None
    _FONT_CACHE[key] = f
    return f


def has_fonts() -> bool:
    return _font("display", 40) is not None


# ── 取图 ──────────────────────────────────────────────────────────────────
def _open_rgba(p: Path):
    from PIL import Image
    try:
        return Image.open(p).convert("RGBA")
    except Exception:
        return None


def figure_ready(cid: str) -> bool:
    """这个角色手上有没有能上封面的图 —— 只 stat 文件, 不抠底。
    工坊面板问的就是这一句; 用 _figure 去问会当场跑 rembg, 六个角色卡住请求十几秒。"""
    return any((SPRITE_DIR / f"{cid}.webp", COVER_DIR / f"_fig_{cid}.webp",
                SPRITE_DIR / f"{cid}_src.jpg", AVATAR_DIR / f"{cid}.jpg")[i].exists()
               for i in range(4))


def _figure(cid: str):
    """一个角色的"人形"。优先级 = 已抠好的立绘 → 立绘源图现抠 → 头像现抠。
    现抠的结果落盘缓存 (rembg 一次几秒, 一个角色这辈子只该抠一次)。"""
    from PIL import Image
    sp = SPRITE_DIR / f"{cid}.webp"
    if sp.exists() and cid != "_extra":
        im = _open_rgba(sp)
        if im is not None and im.getchannel("A").getbbox():
            return im
    cache = COVER_DIR / f"_fig_{cid}.webp"
    if cache.exists():
        return _open_rgba(cache)
    for src in (SPRITE_DIR / f"{cid}_src.jpg", AVATAR_DIR / f"{cid}.jpg"):
        if not src.exists():
            continue
        try:
            from .gal import debg, to_webp, trim_alpha
            cut = to_webp(trim_alpha(debg(src.read_bytes())))
            im = Image.open(io.BytesIO(cut)).convert("RGBA")
            if not im.getchannel("A").getbbox():
                continue
            COVER_DIR.mkdir(parents=True, exist_ok=True)
            cache.write_bytes(cut)
            return im
        except Exception:
            continue
    return None


def _head_band(im) -> tuple[float, float, float] | None:
    """🙂 按肤色把头脸那一段找出来, 返回 (顶, 底, 脸宽) — 都是原图像素。

    为什么不看轮廓: 第一版按 alpha 掩码"从头顶往下走, 宽度一跳就是肩膀"量头高,
    真数据上直接崩了 —— 同一批立绘量出 2.5 到 7.5 头不等 (长发盖住肩线、举手、
    半身构图各破一种)。缩放差三倍, 封面上就是"五个人里两个变小人"(实弹)。

    脸是块【连着的肤色】, 而且一定在人形的上半段。逐行数肤色占该行人形宽度的比例,
    第一段站得住的就是脸。戴面具/非人肤色的角色找不到 → 调用方回落。
    """
    try:
        import numpy as np
    except Exception:
        return None
    from PIL import Image
    w, h = im.size
    sw = 140
    sh = max(12, int(h * sw / max(1, w)))
    arr = np.asarray(im.resize((sw, sh), Image.BILINEAR).convert("RGBA")).astype(np.int16)
    r, g, b, al = arr[..., 0], arr[..., 1], arr[..., 2], arr[..., 3]
    mx = arr[..., :3].max(-1)
    mn = arr[..., :3].min(-1)
    body = al > 140
    # 肤色带: 红≥绿≥蓝、够亮、别太艳。饱和度下限压得很低 —— 二次元的白皙脸
    # 三通道能差不到 10 (实弹: 朱竹清的脸整片被判成非肤色, 头高量成 1/11 身)
    skin = (body & (r > 88) & (r >= g + 4) & (g + 8 >= b) & (mx - mn >= 6)
            & (mx - mn < mx * 0.70) & (mx > 92))
    bw = body.sum(1)
    rows = np.nonzero(bw > 1)[0]
    if rows.size < 10:
        return None
    y0, y1 = int(rows[0]), int(rows[-1])
    bh = y1 - y0

    # 每一行【最长的一段连续肤色】= 那一行的"肉宽"。用连续段而不是像素总数,
    # 举到脸边的手、露出的另一只胳膊都是各自独立的段, 自动不参与
    run = [0] * sh
    for y in range(y0, min(sh, y1 + 1)):
        cur = best = 0
        row = skin[y]
        for x in range(sw):
            if row[x]:
                cur += 1
                if cur > best:
                    best = cur
            else:
                cur = 0
        run[y] = best

    limit = y0 + max(4, int(bh * 0.62))            # 脸只可能在上 62%; 下面是手和腿
    top = None
    for y in range(y0, min(limit, sh)):
        if run[y] >= 3 and run[y] >= bw[y] * 0.18:
            if top is None:
                top = y
            elif y - top >= 2:
                break
        elif top is not None and y - top < 2:
            top = None                              # 只闪一两行的不算 (发饰/耳环)
    if top is None:
        return None

    # 脸最宽的那一行 = 颧骨; 从它往下, 肉宽收到六成以下的第一行 = 脖子。
    # ⚠️ 判据必须是【宽度】不是肤色像素数: 敞着衬衫的写实半身像, 胸口的肤色像素
    # 比脸还多, 按数量永远找不到脖子, 整个上半身被当成一张脸
    # (实弹: Golden Hour 五个人量出的"脸"有 900 像素高, 全被判废)
    win = min(sh, top + max(4, int(bh * 0.34)))
    peak_y = max(range(top, win), key=lambda y: run[y])
    fw = run[peak_y]
    if fw < 4:
        return None
    # 往下找脖子的窗口按【脸宽】开, 不按身高开 —— 半身像的身高就那么点, 按身高开的
    # 窗口够不到下巴 (实弹: 半身构图直接量不出脸)
    neck = None
    for y in range(peak_y + 1, min(sh, peak_y + max(6, int(fw * 2.2)))):
        if run[y] <= fw * 0.62:
            neck = y
            break
    if neck is None:                                   # 兜底也按脸宽估 (头高≈1.35×脸宽)
        neck = min(sh - 1, top + max(3, int(fw * 1.35)))
    if neck - top < 3:
        return None
    k = h / sh
    return (top * k, (neck + 1) * k, fw * (w / sw))


def _upper_width(im) -> float:
    """人形上四分之一的典型宽度 —— 给头高当量纲兜底 (人再怪, 头也不会比自己的
    肩背宽出一倍)。立绘偶尔是废图 (糊成一团黑的兽形), 靠这条把疯掉的缩放夹住。"""
    from PIL import Image
    a = im.getchannel("A")
    w, h = a.size
    sw = 96
    sh = max(8, int(h * sw / max(1, w)))
    a = a.resize((sw, sh), Image.BILINEAR)
    px = a.load()
    spans = []
    for y in range(0, max(2, sh // 4)):
        lo = hi = -1
        for x in range(sw):
            if px[x, y] > 48:
                if lo < 0:
                    lo = x
                hi = x
        if lo >= 0:
            spans.append(hi - lo + 1)
    if not spans:
        return w * 0.5
    return sorted(spans)[len(spans) // 2] * w / sw


def head_metrics(im) -> tuple[float, float, bool]:
    """📏 (脸带高, 脸带顶在第几行, 是不是真量着了)。全班同脸大小、同高就靠它。

    立绘的构图是不齐的: 有全身、有及膝、有半身 (出图提示词写的就是"全身或及膝"),
    发型体积更是从贴头皮到顶着一对猫耳都有。所以两件事都不按图框算:
      · 大小按【脸带高】归一 —— 不是身高 (半身像的脸会大一圈), 也不是头高
        (蓬发的人会被硬生生压小)
      · 高低按【脸带顶】对齐 —— 头发爱冒多高冒多高, 五张脸永远排在同一条线上
    量不着的 (戴面具/非人/废图) 落回 6.4 头身先验, 再用肩背宽夹一道。
    """
    h = im.size[1]
    band = _head_band(im)
    uw = _upper_width(im)
    ok = band is not None
    if band:
        raw = band[1] - band[0]
        # 主用脸宽 ×1.28 (人头的高宽比, 二次元也差不多), 量出的带高只当上下夹子
        fh = max(raw * 0.60, min(raw * 2.0, band[2] * 1.28))
        ftop = band[0]
        # 一张"人只占画面一角"的图 (糊成一团的兽形立绘里蹲着个小人) 量出来的脸
        # 小得离谱, 归一化会把整张图撑成两倍屏高。判它不合格, 让调用方请它下台。
        ok = h * 0.05 <= fh <= h * 0.42
    else:
        # 只有量不着脸时才用肩背宽度当量纲 —— 真量着了就别再夹它:
        # 顶着一根冲天辫的角色, "上四分之一"量到的是那根辫子, 会把脸硬压掉一半 (实弹)
        fh, ftop = max(uw * 0.34, min(uw * 1.30, h / 6.4)), h * 0.02
    fh = max(h * 0.045, min(h * 0.38, fh))
    return fh, ftop, ok


def _ramp(n: int, gamma: float = 1.6) -> list[int]:
    return [int(255 * (1 - i / n) ** gamma) for i in range(n)]


def _fade_bottom(im, frac: float = 0.15):
    """脚下没到画面底的人形, 底边化开一段 —— 不然半身像就是"悬在半空的一截"。
    这是海报的老手艺, 也顺手把立绘裁边的硬茬盖掉。"""
    from PIL import Image, ImageChops
    w, h = im.size
    n = max(1, int(h * frac))
    strip = Image.new("L", (1, n))
    mp = strip.load()
    for i, v in enumerate(_ramp(n)):
        mp[0, i] = v
    ramp = Image.new("L", (w, h), 255)
    ramp.paste(strip.resize((w, n), Image.BILINEAR), (0, h - n))
    out = im.copy()
    out.putalpha(ImageChops.multiply(im.getchannel("A"), ramp))
    return out


def _feather_cropped(im):
    """✂️ 被自己画框切开的边, 一律化开。

    半身立绘的肩膀是顶到左右边、腰是顶到下边的 —— 抠底抠得再干净, 摆到封面上
    也是三块硬邦邦的长方形 (实弹: Golden Hour 五个男人像三张贴纸)。哪条边上还压着
    人, 就把那条边渐隐进底子, 半身像立刻变成"雾里走出来的人"而不是剪贴画。
    头顶那条不动 —— 化开就把脸吃掉了。
    """
    from PIL import Image, ImageChops
    import numpy as np
    a = im.getchannel("A")
    w, h = a.size
    try:
        arr = np.asarray(a)
    except Exception:
        return im
    edges = {"left": arr[:, :3].mean(), "right": arr[:, -3:].mean(),
             "bottom": arr[-3:, :].mean()}
    if max(edges.values()) < 40:
        return im
    ramp = Image.new("L", (w, h), 255)
    if edges["bottom"] >= 40:
        n = max(2, int(h * 0.16))
        s = Image.new("L", (1, n))
        for i, v in enumerate(_ramp(n, 1.9)):
            s.putpixel((0, i), v)
        ramp.paste(ImageChops.multiply(ramp.crop((0, h - n, w, h)),
                                       s.resize((w, n), Image.BILINEAR)), (0, h - n))
    for side in ("left", "right"):
        if edges[side] < 40:
            continue
        n = max(2, int(w * 0.13))
        s = Image.new("L", (n, 1))
        for i, v in enumerate(_ramp(n, 1.9)):
            s.putpixel((i, 0), v)
        s = s.resize((n, h), Image.BILINEAR)
        if side == "left":
            s = s.transpose(Image.FLIP_LEFT_RIGHT)
            ramp.paste(ImageChops.multiply(ramp.crop((0, 0, n, h)), s), (0, 0))
        else:
            ramp.paste(ImageChops.multiply(ramp.crop((w - n, 0, w, h)), s), (w - n, 0))
    out = im.copy()
    out.putalpha(ImageChops.multiply(a, ramp))
    return out


# ── 配色 ──────────────────────────────────────────────────────────────────
def _cool(pal: dict) -> dict:
    """🎨 冷暖对冲 —— 让画面"被调过色"而不是"糊成一坨"的唯一一招。

    从本子的美术里取色, 取回来的常常是【同一个色相】的一堆 (港片场景整片褐、
    雪原整片青)。全篇一个色相 = 泥。所以把主光留在原色相当暖光, 另造一支
    补色当阴影: 暖的地方更暖、暗的地方偏冷, 眼睛立刻读成"打过光的场"。
    """
    import colorsys
    a = pal["accent"]
    h, s, v = colorsys.rgb_to_hsv(*[c / 255 for c in a])
    ch, cs, cv = (h + 0.47) % 1.0, min(0.62, max(0.28, s * 0.9)), 0.30
    pal["cool"] = tuple(int(c * 255) for c in colorsys.hsv_to_rgb(ch, cs, cv))
    return pal


def _palette(src) -> dict[str, tuple[int, int, int]]:
    """从本子自己的美术里取色 —— 每本封面的颜色都长在它自己的画上, 不是套模板。
    取不到就落到影棚黑金 (与 App 主色同源)。"""
    fallback = _cool({"deep": (22, 19, 14), "mid": (58, 48, 35), "accent": (214, 174, 108)})
    if src is None:
        return fallback
    from PIL import Image
    try:
        sm = src.convert("RGB").resize((72, 72), Image.BILINEAR)
        q = sm.quantize(colors=8, method=Image.MEDIANCUT).convert("RGB")
        cols = [c for _, c in sorted(q.getcolors(4096) or [], reverse=True)]
    except Exception:
        return fallback
    if not cols:
        return fallback

    def lum(c):
        return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]

    def sat(c):
        return (max(c) - min(c)) / max(1, max(c))

    deep = min(cols, key=lum)
    # 强调色: 够艳且不死黑不死白的那一支; 全是灰调就回落金色
    cand = [c for c in cols if 40 < lum(c) < 215 and sat(c) > 0.22]
    accent = max(cand, key=lambda c: sat(c) * (1 - abs(lum(c) - 140) / 255)) \
        if cand else fallback["accent"]
    mid = sorted(cols, key=lum)[len(cols) // 2]
    deep = tuple(max(7, min(40, int(v * 0.48))) for v in deep)
    # 强调色要真的亮得起来 —— 实弹第一版整张封面糊成一坨褐色, 病根就是它也被压暗了,
    # 于是底子、辉光、细线全是同一种泥。这里把它往鲜亮里推一把。
    accent = tuple(max(88, min(252, int(v * 1.22 + 16))) for v in accent)
    lift = max(1.0, 150 / max(1.0, 0.299 * accent[0] + 0.587 * accent[1] + 0.114 * accent[2]))
    accent = tuple(min(252, int(v * lift)) for v in accent)
    return _cool({"deep": deep, "mid": mid, "accent": accent})


# ── 底子 ──────────────────────────────────────────────────────────────────
def _keylight(size) -> "Any":
    """顶光的形状 (灰度图): 中上方一枚大椭圆。地面和人物【共用同一枚】——
    合成封面最容易露馅的地方就是"每个人自带一套光", 共用一次光就压成一张照片。"""
    from PIL import Image, ImageChops
    W, H = size
    m = Image.new("L", (W, H), 0)
    # ⚠️ 贴图必须【盖满整张画布】。第一版只贴到 1.25H 高、又往上偏了 0.48H,
    # 于是 0.77H 处横着一条渐变到头的硬边 —— 海报和大厅卡上各挂了一道横线 (实弹)
    rad = ImageChops.invert(Image.radial_gradient("L")).resize(
        (int(W * 2.0), int(H * 2.45)), Image.BILINEAR)
    m.paste(rad, (int(-W * 0.5), int(-H * 1.18)))
    return m


def _bg_plate(size, bg, blur: float, color: float, bright: float):
    """地点背景铺满画布并【打散成氛围】—— 不虚化它就跟人抢戏, 变成"人站在照片前面"。"""
    from PIL import Image, ImageEnhance, ImageFilter
    W, H = size
    bw, bh = bg.size
    s = max(W / bw, H / bh)
    b = bg.convert("RGB").resize((max(1, int(bw * s)), max(1, int(bh * s))), Image.LANCZOS)
    b = b.crop(((b.width - W) // 2, (b.height - H) // 3,
                (b.width - W) // 2 + W, (b.height - H) // 3 + H))
    if blur > 0:
        b = b.filter(ImageFilter.GaussianBlur(max(2, H * blur)))
    b = ImageEnhance.Color(b).enhance(color)
    return ImageEnhance.Brightness(b).enhance(bright)


def _scrim(img, top_frac: float = 0.0, bot_frac: float = 0.0, strength: int = 168,
           rgb=(0, 0, 0)):
    """压字的那条带子。留白那一款底子是纸, 压黑就脏了 —— 它压的是【白】。"""
    from PIL import Image, ImageDraw
    W, H = img.size
    sc = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(sc)
    for frac, at_top in ((top_frac, True), (bot_frac, False)):
        n = int(H * frac)
        for i in range(n):
            a = int(strength * (1 - i / n) ** 1.5)
            d.line(((0, i), (W, i)) if at_top else ((0, H - 1 - i), (W, H - 1 - i)),
                   fill=(*rgb, a))
    return Image.alpha_composite(img.convert("RGBA"), sc).convert("RGB")


def _ground(size, pal, bg, style: str, seed: int):
    """三种底子。研究了一圈真封面 (Grisaia / 薄樱鬼 / Steins;Gate) 之后定的三条路:

      · crowd 群像 —— 地点背景当实景, 人压满画面。亮、实、挤。
      · void  留白 —— 纸白(或墨黑)空场 + 一枚淡色晕, 人像悬在里面边缘化开。
                      Steins;Gate 那一路, 最"设计"的一款。
      · gilt  烫金 —— 暖调渐变 + 光束 + 花瓣 + 光斑, 乙女向包装那一路。
    """
    from PIL import Image, ImageChops
    W, H = size
    deep, mid, accent, cool = pal["deep"], pal["mid"], pal["accent"], pal["cool"]
    grad = Image.linear_gradient("L").resize((W, H), Image.BILINEAR)

    if style == "void":
        # 纸: 强调色掺进白里, 底部略沉。不铺地点背景 —— 空场就是这一款的主张
        paper = tuple(min(252, int(238 + c * 0.06)) for c in accent)
        floor = tuple(min(250, int(214 + c * 0.10)) for c in cool)
        base = Image.composite(Image.new("RGB", (W, H), floor),
                               Image.new("RGB", (W, H), paper), grad)
        halo = Image.new("RGB", (W, H), tuple(min(255, int(c * 0.35 + 168)) for c in accent))
        base = Image.composite(halo, base, _keylight(size).point(lambda v: int(v * 0.55)))
        if bg is not None:      # 地点只留一层几乎看不见的影子, 给纸一点内容
            base = Image.blend(base, ImageChops.lighter(
                base, _bg_plate(size, bg, 0.035, 0.25, 1.35)), 0.30)
        return base

    top = tuple(min(255, int(d * 0.7 + a * 0.34)) for d, a in zip(deep, accent))
    bot = tuple(min(255, int(d * 0.45 + c * 0.42)) for d, c in zip(deep, cool))
    if style == "gilt":         # 暖调: 上暖下沉, 不走冷补色
        top = tuple(min(255, int(a * 0.72 + 60)) for a in accent)
        bot = tuple(min(255, int(d * 0.8 + a * 0.16)) for d, a in zip(deep, accent))
    base = Image.composite(Image.new("RGB", (W, H), bot),
                           Image.new("RGB", (W, H), top), grad)

    if bg is not None:
        # 群像那一款要"实景": 少虚化、提亮; 烫金那一款背景只当氛围
        b = _bg_plate(size, bg, 0.011 if style == "crowd" else 0.030,
                      0.80 if style == "crowd" else 0.55,
                      0.92 if style == "crowd" else 0.85)
        base = Image.blend(base, b, 0.74 if style == "crowd" else 0.52)
        if style == "crowd":    # 冷阴影: 暗部往补色推, 一冷一暖才立体
            dark = base.convert("L").point(lambda v: 255 - v)
            base = Image.composite(Image.blend(base, ImageChops.multiply(
                base, Image.new("RGB", (W, H), tuple(min(255, c + 96) for c in cool))), 0.75),
                base, dark.point(lambda v: int(v * 0.45)))

    base = Image.composite(Image.new("RGB", (W, H), tuple(min(255, int(c * 0.62 + m * 0.55))
                                                          for c, m in zip(accent, mid))),
                           base, _keylight(size).point(lambda v: int(v * 0.34)))
    return base


# ── 装饰件 (真封面上"看着像个包装"的那些东西) ──────────────────────────────
def _rng(seed: int):
    import random
    return random.Random(seed)


def _bokeh(img, pal, seed: int, n: int = 26, alpha: int = 42):
    """光斑: 大小不一的柔圆。空气里有东西, 画面就不是一块死板。"""
    from PIL import Image, ImageDraw, ImageFilter
    W, H = img.size
    r = _rng(seed)
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    tint = tuple(min(255, int(c * 0.4 + 150)) for c in pal["accent"])
    for _ in range(n):
        x, y = r.uniform(-0.05, 1.05) * W, r.uniform(-0.05, 0.95) * H
        rad = r.uniform(0.008, 0.055) * H
        a = int(alpha * r.uniform(0.35, 1.0))
        d.ellipse((x - rad, y - rad, x + rad, y + rad), fill=(*tint, a))
    lay = lay.filter(ImageFilter.GaussianBlur(H * 0.006))
    return Image.alpha_composite(img.convert("RGBA"), lay)


def _petals(img, pal, seed: int, n: int = 34):
    """花瓣: 乙女向包装的标配 (薄樱鬼满屏落樱)。旋转的小水滴形, 近大远小。"""
    from PIL import Image, ImageDraw, ImageFilter
    W, H = img.size
    r = _rng(seed + 7)
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    warm = tuple(min(255, int(c * 0.55 + 128)) for c in pal["accent"])
    for _ in range(n):
        x, y = r.uniform(-0.04, 1.02), r.uniform(-0.03, 1.0)
        # 🚫 不许落在脸区。第一版满屏乱撒, 几片正好糊在主角脸上, 看着像头皮屑 (实弹)
        if 0.22 < x < 0.88 and 0.28 < y < 0.68:
            continue
        s = r.uniform(0.006, 0.017) * H
        cell = Image.new("RGBA", (int(s * 3.0), int(s * 3.0)), (0, 0, 0, 0))
        cd = ImageDraw.Draw(cell)
        cd.ellipse((s * 0.3, s * 1.0, s * 2.7, s * 2.0),      # 细长的一瓣, 不是圆点
                   fill=(*warm, int(r.uniform(34, 96))))
        cell = cell.rotate(r.uniform(0, 360), resample=Image.BICUBIC, expand=True)
        cell = cell.filter(ImageFilter.GaussianBlur(max(1.0, s * 0.16)))
        lay.alpha_composite(cell, (int(x * W), int(y * H)))
    return Image.alpha_composite(img.convert("RGBA"), lay)


def _rays(img, pal, seed: int):
    """顶上斜下来的几束光。给平的渐变一个方向感。"""
    from PIL import Image, ImageDraw, ImageFilter
    W, H = img.size
    r = _rng(seed + 3)
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    tint = tuple(min(255, int(c * 0.35 + 168)) for c in pal["accent"])
    ox, oy = W * r.uniform(0.55, 0.8), -H * 0.15
    for _ in range(5):
        w0 = r.uniform(0.02, 0.09) * W
        dx = r.uniform(-0.9, 0.15) * W
        d.polygon([(ox, oy), (ox + dx - w0, H * 1.1), (ox + dx + w0 * 2.4, H * 1.1)],
                  fill=(*tint, int(r.uniform(16, 34))))
    return Image.alpha_composite(img.convert("RGBA"),
                                 lay.filter(ImageFilter.GaussianBlur(H * 0.02)))


def _frame(img, pal, ink, inset: float = 0.035):
    """内框: 双细线 + 四角短记号。廉价装饰的反面 —— 只用直线, 不画藤蔓。"""
    from PIL import Image, ImageDraw
    W, H = img.size
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    m = int(min(W, H) * inset)
    d.rectangle((m, m, W - m - 1, H - m - 1), outline=(*ink, 120), width=1)
    m2 = m + max(3, int(min(W, H) * 0.008))
    seg = int(min(W, H) * 0.06)
    for (x0, y0, x1, y1) in ((m2, m2, m2 + seg, m2), (m2, m2, m2, m2 + seg),
                             (W - m2 - seg, m2, W - m2, m2), (W - m2, m2, W - m2, m2 + seg),
                             (m2, H - m2, m2 + seg, H - m2), (m2, H - m2 - seg, m2, H - m2),
                             (W - m2 - seg, H - m2, W - m2, H - m2),
                             (W - m2, H - m2 - seg, W - m2, H - m2)):
        d.line((x0, y0, x1, y1), fill=(*pal["accent"], 190), width=2)
    return Image.alpha_composite(img.convert("RGBA"), lay)


def _seal(img, pal, text: str, ink):
    """右上角的小印: 一枚旋一点角度的圆角方章。就这一件, 整张图立刻像"件商品"。"""
    if not text:
        return img
    from PIL import Image, ImageDraw
    W, H = img.size
    f = _font("display", int(H * 0.026))
    if f is None:
        return img
    s = int(H * 0.072)
    cell = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    cd = ImageDraw.Draw(cell)
    cd.rounded_rectangle((0, 0, s - 1, s - 1), radius=int(s * 0.22),
                         fill=(*pal["accent"], 232))
    lines = text.split("\n")[:2]
    lh = int(H * 0.030)
    y = s // 2 - lh * len(lines) // 2
    for ln in lines:
        cd.text((s // 2, y), ln, font=f, fill=(*ink, 255), anchor="ma")
        y += lh
    cell = cell.rotate(-7, resample=Image.BICUBIC, expand=True)
    out = img.convert("RGBA")
    out.alpha_composite(cell, (W - cell.width - int(W * 0.055), int(H * 0.045)))
    return out


def _grade(img, pal, style: str = "crowd"):
    """收尾统一调色: 大气罩(人和地共用的那束顶光罩在最上层) → 暗角 → 提一点浓度
    → 胶片颗粒。五个角色的立绘来自不同批次不同光线, 全靠最后这一道压成同一张照片 ——
    少了它就是拼贴感的正主。留白那一款底子是纸, 暗角要极轻, 否则纸变成脏抹布。"""
    from PIL import Image, ImageChops, ImageEnhance
    W, H = img.size
    rgb = img.convert("RGB")
    haze = Image.new("RGB", (W, H), tuple(min(255, int(c * 0.5 + 70)) for c in pal["accent"]))
    rgb = Image.composite(ImageChops.screen(rgb, haze), rgb,
                          _keylight((W, H)).point(lambda v: int(v * (0.10 if style == "void"
                                                                     else 0.22))))
    vig = Image.radial_gradient("L").resize((W, H), Image.BILINEAR)
    depth = {"void": 26, "gilt": 96, "crowd": 120}[style]
    vig = vig.point(lambda v: 255 - int((v / 255) ** 1.8 * depth))
    rgb = ImageChops.multiply(rgb, Image.merge("RGB", (vig, vig, vig)))
    rgb = ImageEnhance.Color(rgb).enhance(1.14 if style == "gilt" else 1.08)
    rgb = ImageEnhance.Contrast(rgb).enhance(1.06)
    try:
        noise = Image.effect_noise((W, H), 22).convert("L")
        rgb = Image.blend(rgb, ImageChops.overlay(rgb, Image.merge("RGB", (noise,) * 3)),
                          0.05 if style == "void" else 0.07)
    except Exception:
        pass
    return rgb


# ── 版式 ──────────────────────────────────────────────────────────────────
# 避头尾: 行首不许出现的收尾标点 / 行末不许出现的起首标点。少了这一条, 中文换行会
# 出现「，挖出真相」这种以逗号开头的行 (实弹, 寂声疗养院的引子)
_NO_LINE_START = "、。，．：；？！）」』】》〉”’…—·%"
_NO_LINE_END = "（「『【《〈“‘"


def _wrap(draw, text: str, font, max_w: int, max_lines: int) -> list[str]:
    """中文按字断 (带避头尾), 西文按词断。超出行数就在末行收 …"""
    if not text:
        return []
    cjk = sum(ord(c) < 128 for c in text) <= len(text) * 0.6
    words = list(text) if cjk else text.split(" ")
    join = "" if cjk else " "
    lines, cur = [], ""
    for w in words:
        t = (cur + join + w) if cur else w
        if draw.textlength(t, font=font) <= max_w or not cur:
            cur = t
        else:
            if cjk:
                # 标点被挤到下一行行首 → 让它跟着上一行走 (哪怕这一行稍微超一点点)
                while w and w[0] in _NO_LINE_START:
                    cur, w = cur + w[0], w[1:]
                    if not w:
                        break
                while cur and cur[-1] in _NO_LINE_END:
                    w, cur = cur[-1] + w, cur[:-1]
            lines.append(cur)
            cur = w
            if len(lines) == max_lines:
                break
    if cur and len(lines) < max_lines:
        lines.append(cur)
    if len(lines) == max_lines and cur and lines[-1] != cur:
        lines[-1] = lines[-1][:-1] + "…"
    return lines


def _clip(s: str, n: int) -> str:
    """引子截断: 西文退到词边界, 中文退到最近的标点, 截了就补省略号。
    硬截会把一个词腰斩 (实弹: 封面上印着 "…nobody remembers hir")。"""
    t = " ".join((s or "").split())
    if len(t) <= n:
        return t
    cut = t[:n]
    at = max((cut.rfind(c) for c in " ,;—、，。；：!?！？"), default=-1)
    if at >= n * 0.55:
        cut = cut[:at]
    return cut.rstrip(" ,、，；;:—") + "…"


def _fit(draw, title: str, maxw: int, hi: int, lo: int):
    """标题自动缩到放得下。一行永远比两行像 logo —— 所以一路缩到 lo 都要争取单行,
    实在放不下才折两行 (v2 实弹: 「…学院（旧」/「版）」这种断法丑到出戏)。"""
    size, lines = hi, []
    while True:
        f = _font("display", size)
        if f is None:
            return None, [], size
        lines = _wrap(draw, title, f, maxw, 2)
        if len(lines) <= 1 or size <= lo:
            break
        size -= max(2, hi // 26)
    return _font("display", size), lines, size


def _logotype(img, pal, title: str, eyebrow: str, tease: str, style: str):
    """标题块 —— 这是 v1 最大的病灶所在。

    v1 把标题当【编辑排版】处理: 眉标 + 左对齐大标题 + 引子, 全压在顶部。那是电影
    海报/流媒体卡的做法。翻了一圈真封面 (Grisaia / 薄樱鬼 / Little Busters /
    Steins;Gate) 才看明白, galgame 封面的共同法则是反的:

      · 标题在【底部】, 而且是【logo】不是排版字 —— 描边、副行、细线、小印章
      · art 占满整张, 标题压在画上, 不给它单开一块空地

    所以这里: 副行(疏排小字) 在上 → 标题带描边居中 → 细线 → 引子小字。
    三款各有各的墨色: 群像白字黑边、留白墨字白边、烫金金字褐边。
    """
    from PIL import Image, ImageDraw, ImageFilter
    W, H = img.size
    ink, stroke = {
        "crowd": ((250, 246, 238), (14, 12, 10)),
        "void": (tuple(int(c * 0.55) for c in pal["deep"]), (255, 255, 255)),
        "gilt": ((255, 246, 224), tuple(int(c * 0.45) for c in pal["deep"])),
    }[style]
    maxw = int(W * 0.84)
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    cx = W // 2

    ft, lines, size = _fit(d, title, maxw, int(H * 0.078), int(H * 0.032))
    tl = int(size * 1.16)
    fe = _font("body", int(H * 0.0165))
    fb = _font("body", int(H * 0.0195))
    tease_lines = _wrap(d, tease, fb, int(maxw * 0.90), 2) if (tease and fb) else []

    # 📐 整块字从【底边】倒着排。v2 是从标题往上塞眉标, 标题一折两行, 眉标就被顶到
    # 人脸上去了 (实弹: ENDLESS SANDBOX 横在主角胸口)。倒排之后, 不管标题几行,
    # 这一块永远贴着下沿、永远落在压暗的那条带子里。
    eb_h = int(H * 0.030) if (eyebrow and fe) else 0
    ti_h = tl * max(1, len(lines)) + int(H * 0.026) if (ft and lines) else 0
    te_h = int(H * 0.0275) * len(tease_lines)
    y = int(H * 0.955) - (eb_h + ti_h + te_h)

    if eyebrow and fe:
        gap = int(H * 0.0062)
        wid = sum(d.textlength(c, font=fe) + gap for c in eyebrow.upper()) - gap
        x = cx - wid / 2
        for ch in eyebrow.upper():
            d.text((x, y), ch, font=fe, fill=(*pal["accent"], 240))
            x += d.textlength(ch, font=fe) + gap
        y += eb_h

    if ft and lines:
        sw = max(2, int(size * 0.075))
        # 先垫一层模糊的暗影托住, 再描边 —— 亮背景上也压得住
        sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        sd = ImageDraw.Draw(sh)
        yy = y
        for ln in lines:
            sd.text((cx, yy), ln, font=ft, fill=(*stroke, 150), anchor="ma")
            yy += tl
        lay = Image.alpha_composite(lay, sh.filter(ImageFilter.GaussianBlur(int(H * 0.012))))
        d = ImageDraw.Draw(lay)
        for ln in lines:
            d.text((cx, y), ln, font=ft, fill=(*ink, 255),
                   stroke_width=sw, stroke_fill=(*stroke, 235), anchor="ma")
            y += tl
        y += int(H * 0.010)
        half = int(maxw * 0.30)
        d.line((cx - half, y, cx + half, y), fill=(*pal["accent"], 215), width=2)
        y += int(H * 0.016)

    if tease_lines:
        sub = (*ink, 225) if style != "void" else (*ink, 205)
        for ln in tease_lines:
            d.text((cx + 1, y + 1), ln, font=fb, fill=(*stroke, 175), anchor="ma")
            d.text((cx, y), ln, font=fb, fill=sub, anchor="ma")
            y += int(H * 0.0275)
    return Image.alpha_composite(img.convert("RGBA"), lay)


# 每一档: 脸带高占画面高的比例 / 脸顶落在哪条视平线 / 左右站位。
# v1 的班底是"规规矩矩站一排、四周留空", 真封面全是【压满画面、互相压、被画框切掉】——
# 所以这里的脸比 v1 大了三成, 站位也往两侧顶出去。
_LAYOUT = {
    "crowd": {
        "poster": {"face": [0.112, 0.101, 0.101, 0.089, 0.089],
                   "eye": [0.285, 0.330, 0.330, 0.372, 0.372],
                   "xs": [0.50, 0.225, 0.775, 0.035, 0.965]},
        "wide": {"face": [0.132, 0.118, 0.118, 0.104, 0.104],
                 "eye": [0.180, 0.228, 0.228, 0.272, 0.272],
                 "xs": [0.625, 0.400, 0.845, 0.225, 0.975]},
    },
    # 留白: 人小一点、聚成一簇悬在纸中央, 底下留给 logo。松是这一款的主张
    "void": {
        "poster": {"face": [0.082, 0.074, 0.074, 0.066, 0.066],
                   "eye": [0.215, 0.252, 0.252, 0.288, 0.288],
                   "xs": [0.50, 0.290, 0.710, 0.140, 0.860]},
        "wide": {"face": [0.100, 0.090, 0.090, 0.080, 0.080],
                 "eye": [0.150, 0.192, 0.192, 0.232, 0.232],
                 "xs": [0.620, 0.430, 0.810, 0.275, 0.945]},
    },
    "gilt": {
        "poster": {"face": [0.104, 0.094, 0.094, 0.083, 0.083],
                   "eye": [0.245, 0.292, 0.292, 0.334, 0.334],
                   "xs": [0.50, 0.245, 0.755, 0.070, 0.930]},
        "wide": {"face": [0.124, 0.111, 0.111, 0.098, 0.098],
                 "eye": [0.165, 0.212, 0.212, 0.256, 0.256],
                 "xs": [0.620, 0.410, 0.835, 0.240, 0.970]},
    },
}
# 景深: 越往后越暗越灰。手别重 —— 曾压到 0.76 亮度, 后排的人直接掉进背景里没了
_DIM = [(1.0, 1.02), (0.94, 0.96), (0.94, 0.96), (0.88, 0.90), (0.88, 0.90)]
# 留白那一款的底子是纸不是夜, 后排要往【亮】里退才是空气透视, 往暗里退就成了污渍
_DIM_LIGHT = [(1.0, 0.98), (1.06, 0.86), (1.06, 0.86), (1.12, 0.74), (1.12, 0.74)]


FACE_TOP_MIN, FACE_TOP_MAX = 0.085, 0.62


def place_top(H: int, eye: float, rank: int, nh: int, face_off: float,
              bust: bool) -> tuple[int, bool]:
    """这个人形的上沿落在第几行 + 底边要不要化开。

    两种摆法: 全身班底按【视平线】对脸 (顶着猫耳的和贴头皮的才排得齐), 半身班底
    按【齐底】—— 一排人从下沿长出来, 不然下面空一大块。

    最后压一道死规矩: 脸必须留在画面里。齐底摆法碰上一个特别高的人形, 底边一钉,
    脑袋就顶出上沿, 封面上只剩一双手 (实弹: The Lighthouse at Gull Point)。
    宁可让身子多出画一点, 绝不让脸出画。
    """
    fade = False
    if bust:
        top = int(H * (1.035 - 0.022 * min(rank, 4))) - nh
    else:
        top = int(H * eye - face_off)
        bottom = top + nh
        # ✂️ 脚踝切口是海报的低级事故 (实弹第一版三个人全切在脚踝上)。
        # 差一点点就出画的, 索性推下去让它切在小腿。
        if H * 0.90 < bottom < H * 1.06:
            top += int(H * 1.09) - bottom
        elif bottom < H * 0.86:
            top += min(int(H * 0.14), int(H * 0.92) - bottom)
            fade = True
    fy = top + face_off
    top += int(max(H * FACE_TOP_MIN - fy, 0) - max(fy - H * FACE_TOP_MAX, 0))
    return top, fade


def _dissolve(im, pal, style: str):
    """留白那一款: 人形四周整体化开、往纸色里褪。Steins;Gate 封面的招牌手法 ——
    人不是"贴"在纸上, 是从纸里显出来的。"""
    if style != "void":
        return im
    from PIL import Image, ImageChops, ImageFilter
    w, h = im.size
    mask = Image.new("L", (w, h), 0)
    from PIL import ImageDraw
    ImageDraw.Draw(mask).ellipse((-w * 0.22, -h * 0.10, w * 1.22, h * 1.02), fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(max(6, h * 0.06)))
    out = im.copy()
    out.putalpha(ImageChops.multiply(im.getchannel("A"), mask))
    return out


def _cast_layer(size, figs, kind, pal, style: str):
    from PIL import Image, ImageEnhance, ImageFilter
    W, H = size
    cfg = _LAYOUT[style][kind]
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    n = len(figs)
    # 站位按【人数】整套换, 不是把五人位切一段用 —— 切一段就会在少人时留出一大块空地
    # (v2 实弹: 四个人的封面中间左侧空一片, 因为第五个位置在画外)
    slots = {
        "poster": {1: [0.50], 2: [0.355, 0.645], 3: [0.50, 0.215, 0.785],
                   4: [0.44, 0.735, 0.155, 0.945], 5: cfg["xs"]},
        "wide": {1: [0.66], 2: [0.545, 0.815], 3: [0.625, 0.390, 0.865],
                 4: [0.60, 0.815, 0.395, 0.975], 5: cfg["xs"]},
    }[kind]
    xs = slots.get(n, cfg["xs"])[:n] if n <= 5 else cfg["xs"][:n]
    # 先量后摆: 一整台班底是【全身立绘】还是【半身像】, 决定两种完全不同的摆法。
    # 半身像按视平线挂着, 下面就空一大块 (实弹: Golden Hour 五个男人吊在上半张,
    # 底下三分之一是空的)。半身班底改成【齐底】—— 一排人从画面下沿长出来, 版面才满。
    plan = []
    for i in range(n):
        face, ftop, _ = head_metrics(figs[i])
        sc = (H * cfg["face"][min(i, 4)]) / max(1e-6, face)
        plan.append([sc, ftop])
    hs = [figs[i].height * plan[i][0] for i in range(n)]
    med = sorted(hs)[n // 2]
    # 🩺 拔尖的往回收: 谁归一后比全班中位高出六成, 多半是脸量小了。同台的人身量
    # 不该差出两倍 —— 不收, 封面上就是"一个巨人 + 几个被挤到画外的零件"(实弹)
    if n >= 3:
        for i in range(n):
            if hs[i] > med * 1.6:
                plan[i][0] *= med * 1.6 / hs[i]
    bust = med < H * 0.60
    if bust:                                    # 半身: 放大到能撑住版面, 但别撑爆
        k = max(1.0, min(1.7, H * 0.62 / max(1.0, med)))
        for p in plan:
            p[0] *= k

    order = sorted(range(n), key=lambda i: -i)   # 后排先画, 主角压在最上面
    for i in order:
        im = figs[i]
        sc, ftop = plan[i]
        nw, nh = max(2, int(im.width * sc)), max(2, int(im.height * sc))
        if nh > H * 2.2:                       # 病态输入 (量歪了) 的止损
            sc = H * 2.2 / im.height
            nw, nh = max(2, int(im.width * sc)), max(2, int(im.height * sc))
        f = _feather_cropped(im.resize((nw, nh), Image.LANCZOS))

        bright, satu = (_DIM_LIGHT if style == "void" else _DIM)[min(i, 4)]
        f = ImageEnhance.Brightness(f).enhance(bright)
        f = ImageEnhance.Color(f).enhance(satu)
        if i >= 3:
            f = f.filter(ImageFilter.GaussianBlur(1.1))   # 空气透视: 最后一排微微发虚
        f = _dissolve(f, pal, style)

        top, faded = place_top(H, cfg["eye"][min(i, 4)], i, nh, ftop * sc, bust)
        if faded:
            f = _fade_bottom(f, 0.20)
        left = int(W * xs[i] - nw / 2)

        alpha = f.getchannel("A")
        if style == "void":
            # 纸上不打影子也不镶边 —— 只在人脚下垫一层极淡的灰, 免得完全飘着
            soft = Image.new("RGBA", (nw, nh), (0, 0, 0, 0))
            soft.putalpha(alpha.point(lambda v: int(v * 0.16)))
            lay.alpha_composite(soft.filter(ImageFilter.GaussianBlur(max(8, nh // 26))),
                                (left, top + max(6, nh // 55)))
        else:
            # 底影 + 轮廓辉光: 前者把人按在地上, 后者把人从背景里剥出来
            shadow = Image.new("RGBA", (nw, nh), (0, 0, 0, 0))
            shadow.putalpha(alpha.point(lambda v: int(v * 0.55)))
            shadow = shadow.filter(ImageFilter.GaussianBlur(max(4, nh // 48)))
            lay.alpha_composite(shadow, (left + max(3, nw // 55), top + max(6, nh // 60)))
            rim = Image.new("RGBA", (nw, nh), (0, 0, 0, 0))
            # 轮廓光用【提亮过的】强调色 —— 直接用原色等于给人镶一圈泥
            glow = tuple(min(255, int(c * 0.55 + 128)) for c in pal["accent"])
            rim.paste(Image.new("RGBA", (nw, nh), (*glow, 255)), mask=alpha)
            rim.putalpha(alpha.point(lambda v: int(v * (0.34 if style == "gilt" else 0.26))))
            lay.alpha_composite(rim.filter(ImageFilter.GaussianBlur(max(5, nh // 42))),
                                (left, top))
        lay.alpha_composite(f, (left, top))
    return lay


# ── 装配 ──────────────────────────────────────────────────────────────────
def _pick_bg(story: dict) -> Path | None:
    """挑一张地点背景当氛围底。开场那一幕的地点优先 —— 封面该是这本书的第一印象。"""
    locs = [l for l in (story.get("locations") or []) if (l or {}).get("id")]
    order = []
    start = str((story.get("sandbox") or {}).get("start_location") or "")
    if start:
        order += [l for l in locs if l["id"] == start]
    order += locs
    for l in order:
        p = BG_DIR / f"{l['id']}.jpg"
        if p.exists():
            return p
    return None


def _cast_ids(story: dict) -> list[str]:
    from .sprites import rank_cast
    out = []
    for c in rank_cast(story.get("characters") or []):
        cid = (c or {}).get("id")
        if not cid or (c.get("presence") or "present") == "offstage":
            continue
        out.append(str(cid))
    return out


def _eyebrow(story: dict) -> str:
    en = (story.get("language") or "zh") == "en"
    if (story.get("sandbox") or {}).get("enabled"):
        return "ENDLESS SANDBOX" if en else "无 尽 沙 盒"
    n = len(story.get("acts") or [])
    if en:
        return f"{n} ACTS" if n else "A STORY"
    return f"{n} 幕 主 线" if n else "剧 本"


def _badge(story: dict) -> str:
    """右上角小印上的两个字。沙盒就是「沙盒」, 剧情本报幕数。"""
    en = (story.get("language") or "zh") == "en"
    if (story.get("sandbox") or {}).get("enabled"):
        return "SAND\nBOX" if en else "无尽\n沙盒"
    n = len(story.get("acts") or [])
    if not n:
        return ""
    return f"{n}\nACTS" if en else f"{n}\n幕"


def _fingerprint(story: dict, cast: list[str], bg: Path | None, style: str = "") -> str:
    """输入指纹: 素材(立绘/头像/背景 的路径+改动时间+大小) + 文案 + 版式版本。
    立绘后来才画出来 —— 指纹一变封面自动重排, 不靠谁记得手点。"""
    bits: list[Any] = [ALGO, style, story.get("title"), story.get("one_liner"),
                       story.get("language"), _eyebrow(story), cast]
    for cid in cast:
        for p in (SPRITE_DIR / f"{cid}.webp", COVER_DIR / f"_fig_{cid}.webp",
                  SPRITE_DIR / f"{cid}_src.jpg", AVATAR_DIR / f"{cid}.jpg"):
            try:
                st = p.stat()
                bits.append([p.name, st.st_mtime_ns, st.st_size])
                break
            except OSError:
                continue
    if bg:
        try:
            st = bg.stat()
            bits.append([bg.name, st.st_mtime_ns, st.st_size])
        except OSError:
            pass
    bits.append(has_fonts())
    return hashlib.sha1(json.dumps(bits, ensure_ascii=False,
                                   default=str).encode()).hexdigest()[:16]


def paths(story_id: str) -> dict[str, Path]:
    from .gal import safe_asset_key
    sid = safe_asset_key(story_id)
    return {"poster": COVER_DIR / f"{sid}.webp",
            "wide": COVER_DIR / f"{sid}_wide.webp",
            "stamp": COVER_DIR / f"{sid}.json"}


def urls(story_id: str) -> dict[str, str] | None:
    """已经出好的封面地址 (没出过返回 None) —— 书架/工坊只问这一句。"""
    try:
        p = paths(story_id)
    except ValueError:
        return None
    if not p["poster"].exists():
        return None
    v = ""
    try:
        v = "?v=" + str(int(p["poster"].stat().st_mtime))
    except OSError:
        pass
    return {"poster": f"/scene/cover/{p['poster'].name}{v}",
            "wide": (f"/scene/cover/{p['wide'].name}{v}" if p["wide"].exists()
                     else f"/scene/cover/{p['poster'].name}{v}")}


def is_stale(story: dict) -> bool:
    try:
        p = paths(str(story.get("id") or ""))
    except ValueError:
        return False
    if not (p["poster"].exists() and p["wide"].exists()):
        return True
    try:
        got = json.loads(p["stamp"].read_text(encoding="utf-8")).get("fp")
    except Exception:
        return True
    return got != _fingerprint(story, _cast_ids(story)[:MAX_CAST], _pick_bg(story),
                               style_of(story))


def style_of(story: dict) -> str:
    """这本走哪一款版式。作者可在 tuning.cover_style 里钉死; 缺省走全站默认。"""
    s = str((story.get("tuning") or {}).get("cover_style") or "").strip()
    return s if s in _LAYOUT else DEFAULT_STYLE


def build(story: dict, force: bool = False, style: str | None = None) -> dict[str, Any]:
    """把一本剧本排成封面。story = _to_story(...).model_dump() 那个形状。
    没有任何立绘也照出图 (背景+版式的纯设计封面) —— 玩家刚建的本子当场就有脸。"""
    from PIL import Image
    sid = str(story.get("id") or "")
    p = paths(sid)
    cast = _cast_ids(story)[:MAX_CAST]
    bgp = _pick_bg(story)
    st = style if style in _LAYOUT else style_of(story)
    fp = _fingerprint(story, cast, bgp, st)
    if not force and p["poster"].exists() and p["wide"].exists():
        try:
            if json.loads(p["stamp"].read_text(encoding="utf-8")).get("fp") == fp:
                return {"skipped": True, "fp": fp, **(urls(sid) or {})}
        except Exception:
            pass

    # 🩺 找不着脸的那些多半是废图 (糊成一团的兽形立绘、抠崩的底), 缩放只能靠先验,
    # 摆上去就是一个歪个子。手里够三张认得出脸的, 就把它们请下台 —— 封面宁缺勿滥。
    got = [(cid, im, head_metrics(im)[2]) for cid in cast
           if (im := _figure(cid)) is not None]
    figs = [im for _, im, ok in got if ok] if sum(1 for *_, ok in got if ok) >= 3 \
        else [im for _, im, _ in got]
    bg = _open_rgba(bgp) if bgp else None
    pal = _palette(bg if bg is not None else (figs[0] if figs else None))
    title = str(story.get("title") or "").strip()
    tease = _clip(str(story.get("one_liner") or story.get("synopsis") or ""), 82)

    seed = int(hashlib.md5(sid.encode()).hexdigest()[:8], 16)
    ink = tuple(int(c * 0.4) for c in pal["deep"])
    COVER_DIR.mkdir(parents=True, exist_ok=True)
    out: dict[str, Any] = {"cast": len(figs), "fp": fp, "fonts": has_fonts(), "style": st}
    for kind, size, dst in (("poster", POSTER, p["poster"]), ("wide", WIDE, p["wide"])):
        img = _ground(size, pal, bg, st, seed)
        if st == "gilt":
            img = _rays(img, pal, seed)
        if st != "void":
            img = _bokeh(img, pal, seed, 22, 38)
        if figs:
            img = Image.alpha_composite(img.convert("RGBA"),
                                        _cast_layer(size, figs, kind, pal, st))
        if st == "gilt":
            img = _petals(img, pal, seed, 30)     # 花瓣落在人【前面】才有前后景
        # 大厅卡的标题/引子/徽章是 HTML 压在左下角的 —— 给它压一层暗场, 别烫字。
        # 留白那一款压的是白: 纸底压黑就成了脏抹布 (v2 实弹, 引子直接看不清)
        if st == "void":
            img = _scrim(img, bot_frac=0.34 if kind == "poster" else 0.42,
                         strength=205, rgb=(252, 251, 248))
        else:
            img = _scrim(img, bot_frac=0.42 if kind == "wide" else 0.32,
                         strength=150 if kind == "wide" else 126)
        img = _grade(img, pal, st)
        if st in ("void", "gilt"):
            img = _frame(img, pal, ink if st == "void" else (245, 236, 214))
        if kind == "poster":
            # 字只烫在海报上: 大厅卡的标题是 HTML 排的, 烫上去就是两个标题打架
            img = _logotype(img, pal, title, _eyebrow(story), tease, st)
            img = _seal(img, pal, _badge(story), ink).convert("RGB")
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="WEBP", quality=84, method=4)
        dst.write_bytes(buf.getvalue())
        out[kind + "_bytes"] = len(buf.getvalue())
    p["stamp"].write_text(json.dumps({"fp": fp, "cast": cast, "algo": ALGO, "style": st},
                                     ensure_ascii=False), encoding="utf-8")
    out.update(urls(sid) or {})
    return out


# ── 后台队列 ──────────────────────────────────────────────────────────────
# 触发点有三个 (发布 / 书架懒补 / 作者手点), 谁也不许把请求卡在排版上。
# 单线程串行 + 去重: 小水管服务器上 rembg 抢 CPU 会拖慢正在玩的人。
import queue as _q          # noqa: E402
import threading as _th     # noqa: E402

_Q: "_q.Queue" = _q.Queue()
_PENDING: set = set()
_LOCK = _th.Lock()
_WORKER: list = []


def _worker():
    while True:
        story, force = _Q.get()
        try:
            build(story, force=force)
        except Exception as e:      # 封面出不来绝不能影响发布/开档
            print(f"[cover] {story.get('id')}: {type(e).__name__}: {e}")
        finally:
            with _LOCK:
                _PENDING.discard(str(story.get("id")))
            _Q.task_done()


def enqueue(story: dict, force: bool = False) -> bool:
    sid = str(story.get("id") or "")
    if not sid:
        return False
    with _LOCK:
        if sid in _PENDING:
            return False
        _PENDING.add(sid)
        if not _WORKER:
            t = _th.Thread(target=_worker, daemon=True)
            _WORKER.append(t)
            t.start()
    _Q.put((story, force))
    return True
