# -*- coding: utf-8 -*-
"""🎬 规则导演 v1 — 引擎状态直接驱动演出 (零 LLM、零延迟).

分工: 剧情节奏归恐怖引擎的张弛导演 (pressure/dooms), 视听表达归这里 —
每拍注记 {sfx 音效插点 / fx 惊吓白闪 / expr 表情位}, 随 beat 直接下发;
每回合一张演出单 {bgm 选曲 / tint 色调}, 以 direct 事件收尾下发.

法度: 规则全部确定性; 素材缺失客户端静默降级; 一回合白闪至多一次,
同名音效不重复 (阈下适应 — 吓人的东西响两次就不吓人了)。
"""
from __future__ import annotations

import re
from typing import Any

from .scene import _SFX

# 惊吓语法: 突发副词 + 撞击/断灭动词, 或独立的高声压词 → 白闪
_FLASH_RE = re.compile(
    r"尖叫|惨叫|巨响|炸裂|轰然"
    r"|(猛地|猛然|骤然|突然|陡然|倏地)[^。！？\n]{0,12}(响|撞|砸|扑|抓|拽|拍|摔|碎|灭|熄|断|裂|窜|闪|亮)")
# 心理惊悚的底噪: 没有实体音效可插时, 心跳声顶上
_HEARTBEAT_RE = re.compile(r"心跳|心脏(狂|猛|骤)|窒息|屏住呼吸|汗毛|脊背发凉|寒意|冷汗")

# 🎵 BGM 曲库标签 (Yi: 先给所有 bgm 打上情绪标签再调用) — key = /scene/bgm/ 里的
# 文件名词干 (客户端 gal_{key}.mp3 优先、{key}.mp3 兜底)。energy 1安~4烈;
# 加新曲 = 加一行数据, 选曲逻辑不用动。
BGM_TRACKS: dict[str, dict] = {
    "daily":    {"tags": {"日常", "平静", "闲适"}, "energy": 1, "variants": 3},
    "warm":     {"tags": {"温馨", "治愈", "陪伴"}, "energy": 1, "variants": 2},
    "romantic": {"tags": {"浪漫", "心动", "暧昧", "亲密"}, "energy": 1, "variants": 1},
    "sad":      {"tags": {"悲伤", "失去", "离别"}, "energy": 1, "variants": 2},
    "lonely":   {"tags": {"孤独", "空寂", "夜"}, "energy": 1, "variants": 2},
    "mystery":  {"tags": {"悬疑", "调查", "线索"}, "energy": 2, "variants": 2},
    "eerie":    {"tags": {"诡异", "阴森", "不安", "夜"}, "energy": 2, "variants": 2},
    "ancient":  {"tags": {"古风", "修行", "宗门"}, "energy": 2, "variants": 1},
    "grimdark": {"tags": {"黑暗", "宏大", "压抑"}, "energy": 3, "variants": 1},
    "tense":    {"tags": {"紧张", "恐惧", "追逐", "危机"}, "energy": 3, "variants": 2},
    "battle":   {"tags": {"战斗", "厮杀", "激烈"}, "energy": 4, "variants": 2},
}


def pick_variant(key: str, salt: str) -> str:
    """🎵 同情绪多曲目轮换 (Yi: 别老是这一首): 换地方/过一天就换曲,
    同一场景内稳定不跳 — salt 定曲, 不靠随机 (随机=每回合乱切)."""
    n = int(BGM_TRACKS.get(key, {}).get("variants", 1) or 1)
    if n <= 1:
        return key
    import zlib
    i = zlib.crc32(f"{key}|{salt}".encode("utf-8")) % n
    return key if i == 0 else f"{key}{i + 1}"


def pick_bgm(mood: str, pressure: int = 0, hot: bool = False, night: bool = False,
             frail: bool = False, heat: int = 0) -> str:
    """按当前情绪选曲 (确定性): 亲密 > 危机 > 阴燃 > 理智/夜的底色 > 场景 mood.
    返回曲库 key; mood 不在库里就回 daily (缺曲客户端再静默降级)."""
    mood = mood if mood in BGM_TRACKS else "daily"
    if heat >= 2:
        return "romantic"                     # 床笫之间, 天塌下来也是浪漫曲
    if hot or pressure >= 70:
        # 危机: 但 battle/grimdark 本身能量 ≥3, 不夺它们的戏
        return mood if BGM_TRACKS[mood]["energy"] >= 3 else "tense"
    if 40 <= pressure < 70 and BGM_TRACKS[mood]["energy"] <= 2 \
            and mood not in ("romantic", "warm", "sad"):
        return "eerie"                        # 阴燃: 压着但还没炸
    if frail and BGM_TRACKS[mood]["energy"] <= 1:
        return "lonely"                       # 理智见底, 世界发空
    if night and mood == "daily":
        return "lonely"                       # 深夜无事, 也不该是白日曲
    return mood

# 心象仪 mood (自由文本, ≤12字) → 表情差分四分类; 恐怖游戏里「惊」最常见, 先判
_EXPR_MAP = [
    ("惊", re.compile(r"惊|骇|怕|恐|悚|紧张|警惕|戒备|不安|慌|发毛|发凉")),
    ("怒", re.compile(r"怒|恼|烦躁|火|不满|愠|敌意|冷硬|厌|狠")),
    ("哀", re.compile(r"哀|悲|伤|失落|沮丧|愧|疲惫|苦涩|难过|失望|黯然")),
    ("喜", re.compile(r"喜|笑|高兴|开心|愉|轻松|得意|温暖|放松|安心|雀跃")),
]


def expr_of(mood: str | None) -> str | None:
    """分不出就不给 — 常态脸比错误的脸好."""
    if not mood:
        return None
    for name, rx in _EXPR_MAP:
        if rx.search(mood):
            return name
    return None


class TurnStage:
    """One turn's per-beat director memory: sfx dedupe + the single flash."""

    def __init__(self) -> None:
        self.used: set[str] = set()
        self.flashed = False

    def beat_fx(self, text: str, mood: str | None = None) -> dict[str, Any]:
        """演出注记 — rides the streamed beat dict. Keys absent when nothing fires."""
        t = text or ""
        out: dict[str, Any] = {}
        for kw, name in _SFX:
            if kw in t:
                if name not in self.used:
                    self.used.add(name)
                    out["sfx"] = name
                break
        if "sfx" not in out and "heartbeat" not in self.used and _HEARTBEAT_RE.search(t):
            self.used.add("heartbeat")
            out["sfx"] = "heartbeat"
        if not self.flashed and _FLASH_RE.search(t):
            self.flashed = True
            out["fx"] = "flash"
        ex = expr_of(mood)
        if ex:
            out["expr"] = ex   # 表情差分位: 客户端按 {cid}_{expr}.jpg 换脸, 缺素材回落常态
        return out


# ── 🔎 导演审稿 (Yi: 导演要确认逻辑无漏洞) ──────────────────────────────────
# 只查铁证不搞猜测 (误杀一段好戏比漏放一个破绽更贵); 查出即随逻辑护卫定向重写。
_SLOT_CONTRA = {   # 时段 → 旁白里不该出现的相反时辰铁证 (月光/星空这类两可词不算罪)
    "夜": re.compile(r"烈日|正午的太阳|晌午|艳阳高照|日头正|大中午"),
    "晨": re.compile(r"深夜|午夜|夜半|入夜|夜深了"),
    "午": re.compile(r"深夜|午夜|夜半|入夜|夜深了|天刚亮"),
}


def logic_audit(beats: list[dict[str, Any]], *, slot: str | None = None,
                dead_names: tuple | list = (), prev_text: str = "") -> list[str]:
    """确定性审稿: 返回破绽清单 (空 = 无漏洞)。
    ① 死者开口 ② 昼夜矛盾 (只查旁白) ③ 整回合复读上一回合 (模型卡拍)."""
    finds: list[str] = []
    dead = {str(n) for n in dead_names if n}
    for b in beats:
        sp = (b.get("speaker_name") or "").strip()
        if b.get("type") == "dialogue" and sp in dead:
            finds.append(f"死者「{sp}」开口说话了")
            break
    rx = _SLOT_CONTRA.get(slot or "")
    if rx:
        for b in beats:
            if b.get("type") == "description" and rx.search(b.get("text") or ""):
                finds.append(f"此刻时段是「{slot}」，旁白却写出了相反的时辰景象")
                break
    joined = " ".join((b.get("text") or "") for b in beats)[:1600]
    if prev_text and len(joined) > 60:
        import difflib
        if difflib.SequenceMatcher(None, prev_text[:1600], joined).ratio() >= 0.92:
            finds.append("这一回合几乎在逐字复读上一回合")
    return finds


def stage_turn(final: dict[str, Any]) -> dict[str, Any]:
    """回合演出单 {bgm, tint} from the turn's final meta. 都总是给:
    bgm 走标签选曲 (导演每回合选, 客户端同曲不切), tint 阶梯 danger>frail>night>none."""
    out: dict[str, Any] = {}
    scene = final.get("scene") or {}
    mood = str(scene.get("mood") or "daily")
    pv = final.get("pressure_view") or {}
    tv = final.get("threat_view") or {}
    sv = final.get("sanity_view") or {}
    st = final.get("state") or {}
    try:
        pressure = int(pv.get("value") or 0)
    except (TypeError, ValueError):
        pressure = 0
    hot = bool(tv.get("alert")) or pressure >= 70
    frail = False
    try:
        if sv:
            frail = int(sv.get("value", 999)) <= int(sv.get("max", 100)) * 3 // 10
    except (TypeError, ValueError):
        pass
    heat = 0
    if isinstance(st.get("heat"), dict):
        try:
            heat = int(st["heat"].get("stage") or 0)
        except (TypeError, ValueError):
            pass
    base = pick_bgm(mood, pressure=pressure, hot=hot,
                    night=bool(scene.get("night")), frail=frail, heat=heat)
    salt = f"{st.get('location_id') or ''}|{(st.get('clock') or {}).get('day', 0)}"
    out["bgm"] = pick_variant(base, salt)
    if hot:
        out["tint"] = "danger"
    elif frail:
        out["tint"] = "frail"
    elif scene.get("night"):
        out["tint"] = "night"
    else:
        out["tint"] = "none"
    return out
