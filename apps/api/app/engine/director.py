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
    # 🈳 这两格没有真曲 (曲库里只有 24 秒的老合成器片, 循环一整局很难听) ——
    # fallback 指到情绪最近的真曲上。作者在工坊里点了名的, 永远压过这条兜底。
    "ancient":  {"tags": {"古风", "修行", "宗门"}, "energy": 2, "variants": 1,
                 "fallback": "lonely"},
    "grimdark": {"tags": {"黑暗", "宏大", "压抑"}, "energy": 3, "variants": 1,
                 "fallback": "tense"},
    "tense":    {"tags": {"紧张", "恐惧", "追逐", "危机"}, "energy": 3, "variants": 2},
    "battle":   {"tags": {"战斗", "厮杀", "激烈"}, "energy": 4, "variants": 2},
}
MOOD_LABEL = {"daily": "日常", "warm": "温馨", "romantic": "浪漫", "sad": "悲伤",
              "lonely": "孤独", "mystery": "悬疑", "eerie": "诡异", "ancient": "古风",
              "grimdark": "黑暗", "tense": "紧张", "battle": "战斗"}

# 🎬 剧情节拍 (Yi 2026-08-02:「一段故事有不同的情绪…开场、日常感、危机、高潮、暧昧」)
#
# 上面那张 BGM_TRACKS 管的是【这一场是什么气氛】(诡异/孤独/古风) —— 抽象, 作者不好回答。
# 这一层管的是【故事走到哪一步】—— 写故事的人一想就知道该配什么。
# 作者主要配的是这一层; 气氛那层留给不想细配的人当兜底。
#
# 节拍从引擎【已经在算的状态】里认出来, 不新增字段、不问模型:
#   落幕=有结局 · 高潮=命运抉择当口 · 亲密=heat≥2 · 危机=威胁告警或压力≥70
#   暧昧=heat=1 或这一拍关系涨了一截 · 开场=这一档还没走满两回合 · 其余=日常
# 排在前面的先认 —— 结局那一拍不许被"危机"抢了曲子。
STORY_CUES: list[dict[str, Any]] = [
    {"key": "finale",   "label": "落幕", "when": "结局画面",           "mood": "sad"},
    {"key": "climax",   "label": "高潮", "when": "命运抉择当口",       "mood": "battle"},
    {"key": "intimate", "label": "亲密", "when": "床笫之间",           "mood": "romantic"},
    {"key": "crisis",   "label": "危机", "when": "威胁告警 / 压力拉满", "mood": "tense"},
    {"key": "flirt",    "label": "暧昧", "when": "心动、试探、关系升温", "mood": "romantic"},
    {"key": "opening",  "label": "开场", "when": "新档头两回合",       "mood": "warm"},
    {"key": "daily",    "label": "日常", "when": "其余时候（跟着场景气氛走）", "mood": ""},
]
CUE_KEYS = [c["key"] for c in STORY_CUES]


def cue_of(final: dict[str, Any] | None, state: dict[str, Any] | None = None) -> str:
    """这一拍故事走到哪一步。认不出就是"日常"(交给场景气氛那一层)。"""
    final = final or {}
    st = state if state is not None else (final.get("state") or {})
    if final.get("ending"):
        return "finale"
    if final.get("pending_choice"):
        return "climax"
    heat = 0
    if isinstance(st.get("heat"), dict):
        try:
            heat = int(st["heat"].get("stage") or 0)
        except (TypeError, ValueError):
            heat = 0
    if heat >= 2:
        return "intimate"
    tv = final.get("threat_view") or {}
    try:
        pressure = int((final.get("pressure_view") or {}).get("value") or 0)
    except (TypeError, ValueError):
        pressure = 0
    if tv.get("alert") or pressure >= 70:
        return "crisis"
    if heat >= 1:
        return "flirt"
    # 这一拍关系涨了一截 = 有人被打动了 —— 暧昧曲的正当理由
    try:
        if max([int(v) for v in (final.get("rel_deltas") or {}).values()] or [0]) >= 2:
            return "flirt"
    except (TypeError, ValueError):
        pass
    if str((final.get("scene") or {}).get("mood") or "") == "romantic":
        return "flirt"
    try:
        if int(st.get("turn_seq") or 0) <= 2:
            return "opening"
    except (TypeError, ValueError):
        pass
    return "daily"


def cue_menu() -> list[dict[str, Any]]:
    """工坊配乐面板的主栏。"""
    return [{**c, "default": default_track(c["mood"] or "daily")} for c in STORY_CUES]
# 🎵 曲名 (甘茶の音楽工房, 免费商用无需署名)。作者在工坊里挑的就是这张表;
# 表里没有的文件仍然能用, 只是显示成文件名。
TRACK_NAME = {
    "gal_daily": "放課後の夕空", "gal_daily2": "日常 · 其二", "gal_daily3": "日常 · 其三",
    "gal_warm": "小さな足あと", "gal_warm2": "温馨 · 其二",
    "gal_romantic": "月明かりの灯台",
    "gal_sad": "雨のプレリュード", "gal_sad2": "悲伤 · 其二",
    "gal_lonely": "午前2時の虚しさ", "gal_lonely2": "孤独 · 其二",
    "gal_mystery": "闇に沈む光", "gal_mystery2": "悬疑 · 其二",
    "gal_eerie2": "诡异 · 其二",
    "gal_tense": "深い闇の奥で", "gal_tense2": "紧张 · 其二",
    "gal_battle": "騎兵戦", "gal_battle2": "战斗 · 其二",
}


def bgm_dir():
    from pathlib import Path
    return Path(__file__).resolve().parents[1] / "static" / "scene" / "bgm"


def list_bgm() -> list[dict[str, Any]]:
    """曲库里【真的存在】的曲子 —— 工坊的下拉菜单吃这个, 不许列出点了没声的曲子。"""
    out = []
    try:
        files = sorted(p.stem for p in bgm_dir().glob("*.mp3"))
    except OSError:
        return out
    for stem in files:
        base = re.sub(r"\d+$", "", stem[4:] if stem.startswith("gal_") else stem)
        out.append({"file": stem, "name": TRACK_NAME.get(stem, stem),
                    "mood": base if base in BGM_TRACKS else "",
                    "real": stem.startswith("gal_")})
    return out


def mood_menu() -> list[dict[str, Any]]:
    """工坊配乐面板的左栏: 十一种情绪, 各自的默认曲与什么时候会响。"""
    return [{"key": k, "label": MOOD_LABEL.get(k, k), "energy": v["energy"],
             "tags": sorted(v["tags"]), "default": default_track(k)}
            for k, v in BGM_TRACKS.items()]


def default_track(key: str) -> str:
    """没有作者指定时这个情绪实际会响哪一首 (fallback 与"文件在不在"都算进去)。"""
    got = real_variants(key) or real_variants(BGM_TRACKS.get(key, {}).get("fallback") or "")
    return got[0] if got else f"gal_{key}"


def resolve_bgm(content: dict[str, Any] | None, key: str, salt: str,
                cue: str = "") -> str:
    """选曲的四级优先, 从硬到软:

      ① 作者按【剧情节拍】点的名 (tuning.bgm["opening"/"climax"…]) —— 他最想管的就是这一层
      ② 作者按【场景气氛】点的名 (tuning.bgm["eerie"…]) —— 想细配的人才用
      ③ 引擎自己的选曲 (pick_bgm 已经算好, 见 key) + 变奏轮换

    作者点名的一律【不轮变奏】—— 点名就是点名, 换地方换天都不变。

    ⚠️ 节拍【不带默认覆盖】。第一版让节拍自带的气氛无条件压过引擎选曲, 当场压出两条回归:
    乐师读了正文判「孤独」被"开场"盖成温馨、战斗曲被"危机"盖成紧张曲 —— 而引擎里明写着
    「危机不夺 battle/grimdark 的戏」。那套硬状态规则是调过的, 新加一层默认就会把它压坏。
    所以节拍只做两件事: 给作者一个能点名的槽, 和把判到的那一步报出来。
    """
    tun = ((content or {}).get("story") or {}).get("tuning")
    custom = tun.get("bgm") if isinstance(tun, dict) else None
    # 作者手填的字段什么形状都可能 (实弹: 写成一个字符串) —— 不是字典就当没填, 绝不炸回合
    if not isinstance(custom, dict):
        custom = {}
    for k in (cue, key):
        pick = str(custom.get(k) or "").strip() if k else ""
        if pick:
            return pick
    # 这一格有真曲就用它的变奏; 一首都没有 (ancient/grimdark 这类空格) 才落 fallback
    if real_variants(key):
        return pick_variant(key, salt)
    alt = BGM_TRACKS.get(key, {}).get("fallback")
    return pick_variant(alt or key, salt)


_VAR_CACHE: dict[str, Any] = {"stamp": None, "map": {}}


def real_variants(key: str) -> tuple[str, ...]:
    """这个情绪【文件真的在】的真曲变奏, 形如 ("gal_daily", "gal_daily2", "gal_daily3")。

    ⚠️ 别再手写 variants 计数 —— 数字和磁盘一旦对不上, 玩家听到的就是那段 24 秒的
    老合成器片循环一整局 (实弹: eerie 写着 variants=2, 而磁盘上只有 gal_eerie2)。
    问磁盘, 不问表。目录改动时间变了才重扫。
    """
    d = bgm_dir()
    try:
        stamp = d.stat().st_mtime_ns
    except OSError:
        return ()
    if _VAR_CACHE["stamp"] != stamp:
        _VAR_CACHE["stamp"], _VAR_CACHE["map"] = stamp, {}
    if key not in _VAR_CACHE["map"]:
        _VAR_CACHE["map"][key] = tuple(
            f"gal_{s}" for s in [key] + [f"{key}{i}" for i in range(2, 7)]
            if (d / f"gal_{s}.mp3").exists())
    return _VAR_CACHE["map"][key]


def pick_variant(key: str, salt: str) -> str:
    """🎵 同情绪多曲目轮换 (Yi: 别老是这一首): 换地方/过一天就换曲,
    同一场景内稳定不跳 — salt 定曲, 不靠随机 (随机=每回合乱切)。
    只在【真的存在】的曲子之间轮; 一首真曲都没有就把 key 原样交出去 (调用方去找 fallback)."""
    import zlib
    got = real_variants(key)
    if not got:
        n = int(BGM_TRACKS.get(key, {}).get("variants", 1) or 1)
        if n <= 1:
            return key
        i = zlib.crc32(f"{key}|{salt}".encode("utf-8")) % n
        return key if i == 0 else f"{key}{i + 1}"
    return got[zlib.crc32(f"{key}|{salt}".encode("utf-8")) % len(got)]


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


# 🧍 动作位 (Yi 2026-07-21: 角色的动作可以增加): 帧表 self_position 是模型已在报的
# 肢体台账 — 从里面认出四个有差分素材的动作, 零新字段零新调用。认不出就不动 —
# 常态站姿比错误的动作好 (角色不能崩)。
POSE_ACTS = ("挥手", "抱臂", "低头", "伸手")
_POSE_MAP = [
    ("挥手", re.compile(r"挥手|招手|摆手|挥了挥")),
    ("抱臂", re.compile(r"抱臂|抱着双?臂|环抱双?臂|双臂交叉|抱着胳膊|环胸")),
    ("低头", re.compile(r"低头|垂着头|垂下头|垂首|埋着头|俯下头|俯首")),
    ("伸手", re.compile(r"伸出手|伸手|递过|递出|摊开手|探出手|掌心向上")),
]


def pose_of(position: str | None) -> str | None:
    if not position:
        return None
    for name, rx in _POSE_MAP:
        if rx.search(position):
            return name
    return None


# ── 🔊 本子自己的音效词表 (Yi 2026-08-03:「怎么在编辑剧本里面加音效」) ──────────
# 内置那张 _SFX 是现代 / 恐怖向的: 仙侠本里「剑鸣」「拂尘」「钟磬」一个都不触发,
# 所以那类本子基本是哑的。作者在工坊里补自己的词, 存 tuning.sfx:
#     {"enabled": true, "map": {"剑鸣": "clash", "拂尘": "creak"}}
# 作者的词【压过】内置词 —— 同一句里两边都命中时听他的。


def story_sfx(content: dict[str, Any] | None) -> tuple[bool, list[tuple[str, str]]]:
    """→ (音效开着吗, 作者的 [(关键词, 音效名)] 表)。手填字段什么形状都可能, 绝不炸回合。"""
    tun = ((content or {}).get("story") or {}).get("tuning")
    cfg = tun.get("sfx") if isinstance(tun, dict) else None
    if not isinstance(cfg, dict):
        return True, []
    on = cfg.get("enabled")
    m = cfg.get("map")
    pairs = [(str(k).strip(), str(v).strip())
             for k, v in m.items() if str(k).strip() and str(v).strip()] \
        if isinstance(m, dict) else []
    # 长词先匹配: 作者写了「刀剑相击」又写了「刀」时, 具体的那条该赢
    pairs.sort(key=lambda kv: -len(kv[0]))
    return (True if on is None else bool(on)), pairs


class TurnStage:
    """One turn's per-beat director memory: sfx dedupe + the single flash."""

    def __init__(self, content: dict[str, Any] | None = None) -> None:
        self.used: set[str] = set()
        self.flashed = False
        self.sfx_on, self.own_sfx = story_sfx(content)

    def beat_fx(self, text: str, mood: str | None = None,
                act: str | None = None) -> dict[str, Any]:
        """演出注记 — rides the streamed beat dict. Keys absent when nothing fires."""
        t = text or ""
        out: dict[str, Any] = {}
        for kw, name in (self.own_sfx + _SFX if self.sfx_on else []):
            if kw in t:
                if name not in self.used:
                    self.used.add(name)
                    out["sfx"] = name
                break
        if (self.sfx_on and "sfx" not in out and "heartbeat" not in self.used
                and _HEARTBEAT_RE.search(t)):
            self.used.add("heartbeat")
            out["sfx"] = "heartbeat"
        if not self.flashed and _FLASH_RE.search(t):
            self.flashed = True
            out["fx"] = "flash"
        # 🧍 明确的肢体动作压过表情 (动作更具体; 单差分位一次只能换一张);
        # 素材缺失客户端静默回落常态 — 全链条没有硬失败
        ex = (act if act in POSE_ACTS else None) or expr_of(mood)
        if ex:
            out["expr"] = ex   # 差分位: 客户端按 {cid}_{expr}.webp 换图, 缺素材回落常态
        return out


# ── 🔎 导演审稿 (Yi: 导演要确认逻辑无漏洞) ──────────────────────────────────
# 只查铁证不搞猜测 (误杀一段好戏比漏放一个破绽更贵); 查出即随逻辑护卫定向重写。
_SLOT_CONTRA = {   # 时段 → 旁白里不该出现的相反时辰铁证 (月光/星空这类两可词不算罪)
    "夜": re.compile(r"烈日|正午的太阳|晌午|艳阳高照|日头正|大中午"),
    "晨": re.compile(r"深夜|午夜|夜半|入夜|夜深了"),
    "午": re.compile(r"深夜|午夜|夜半|入夜|夜深了|天刚亮"),
}


_CJK_RE = re.compile(r"[一-鿿]")


def _repeat_motifs(beats: list[dict[str, Any]], recent_texts: list[str]) -> list[str]:
    """④ 招牌动作/景物复读 (实弹: 蝴蝶刀每拍转一圈、同一段晨光描写反复出现)。
    铁证标准 (宁漏勿误杀): 本拍旁白与最近一拍存在 ≥8 字逐字重合, 且该片段在更早的
    近拍里也出现过 — 三次落地才算刷屏; 台词不查 (口头禅是人设不是破绽)。"""
    narr = " ".join((b.get("text") or "") for b in beats
                    if b.get("type") == "description")[:1200]
    rs = [(t or "")[:1200] for t in (recent_texts or []) if t]
    if len(narr) < 24 or not rs:
        return []
    import difflib

    def _core_in(s: str, older: str) -> str:
        """s 与更早拍的 ≥8 字逐字重合核 (复读常连上下文一起抄, 整块子串查找会漏 —
        审查实弹: 块被周边共同措辞撑长后 `s in older` 失配; 改为块内再配一次)。"""
        for b2 in difflib.SequenceMatcher(None, s, older).get_matching_blocks():
            if b2.size >= 8:
                core = s[b2.a: b2.a + b2.size].strip("，。！？、 \n「」…—")
                if len(core) >= 8 and len(_CJK_RE.findall(core)) >= 6:
                    return core
        return ""

    hits: list[str] = []
    sm = difflib.SequenceMatcher(None, rs[0], narr)
    for blk in sm.get_matching_blocks():
        if blk.size < 8:
            continue
        s = rs[0][blk.a: blk.a + blk.size].strip("，。！？、 \n「」…—")
        if len(s) < 8 or len(_CJK_RE.findall(s)) < 6:
            continue
        core = next((c for c in (_core_in(s, older) for older in rs[1:]) if c), "")
        if core:   # 三次落地 (本拍+上拍+更早)
            hits.append(core[:20])
        if len(hits) >= 2:
            break
    return hits


def logic_audit(beats: list[dict[str, Any]], *, slot: str | None = None,
                dead_names: tuple | list = (), prev_text: str = "",
                recent_texts: list[str] | None = None) -> list[str]:
    """确定性审稿: 返回破绽清单 (空 = 无漏洞)。
    ① 死者开口 ② 昼夜矛盾 (只查旁白) ③ 整回合复读上一回合 (模型卡拍)
    ④ 招牌动作/景物三拍复读 (需 recent_texts 近拍档)."""
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
    prev = (prev_text or "")[:1600]
    # 快筛先行: 长度差超 15% 不可能 ≥0.92 相似 — 别让 O(n·m) 的 difflib 上每回合的热路径
    if prev and len(joined) > 60 and abs(len(prev) - len(joined)) < len(joined) * 0.15:
        import difflib
        if difflib.SequenceMatcher(None, prev, joined).ratio() >= 0.92:
            finds.append("这一回合几乎在逐字复读上一回合")
    for m in _repeat_motifs(beats, recent_texts or []):
        finds.append(f"「{m}」这一动作/画面已连着好几拍反复出现，换新的表现方式，"
                     "同一个招牌动作、同一段景物不许再原样重演")
    return finds


def stage_turn(final: dict[str, Any], content: dict[str, Any] | None = None) -> dict[str, Any]:
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
    # 🎼 乐师判词 (读了实际剧情文字的高精度判断) 压过九宫格粗规则;
    # 硬状态仍归引擎: 床笫的浪漫曲、危机的紧张曲不容乐师改判
    judged = str(((final.get("music") or {}).get("track")) or "")
    if judged and judged in BGM_TRACKS and heat < 2 and not hot:
        base = judged
    salt = f"{st.get('location_id') or ''}|{(st.get('clock') or {}).get('day', 0)}"
    cue = cue_of(final, st)
    out["bgm"] = resolve_bgm(content, base, salt, cue)
    # 作者调试用: 这一拍判到的是哪一步 / 哪种气氛
    out["cue"], out["mood"] = cue, base
    if hot:
        out["tint"] = "danger"
    elif frail:
        out["tint"] = "frail"
    elif scene.get("night"):
        out["tint"] = "night"
    else:
        out["tint"] = "none"
    return out
