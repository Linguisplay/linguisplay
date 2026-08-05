# -*- coding: utf-8 -*-
"""🎬 旁白别复读 (Yi 2026-08-05, 生产实测促成)。

线上 2174 条旁白, 逐局数四字短语:
  九龙城寨·狗笼 59 条旁白里「桃花眼」8 次、「喉结上下滚动」6 次、「低头看你」6 次,
  「额头的汗顺着鬓角滑下来，滴在你军装肩章的铜扣上」一字不差出现两次。
  斗罗 178 条里「目光从你」16 次 —— 几乎成了旁白的开场公式。

根因有两条, 这里各修一条:
  ① narration 是 required 字段 —— 每一拍都【必须】写点什么。没新东西可写时, 模型
     只好去写永远安全的那几样(眼睛/喉结/汗/衬衫)。复读不是偷懒, 是被逼的。
  ② 已经写过的意象只喂给【事后】的守卫查复读, 从没在【动笔之前】告诉模型。

修法: 旁白可留空 + 把本场反复出现的意象在写之前摊给模型。
两条都是零成本 —— 不加 LLM 调用, 不改文风规则。
"""
from app.engine import runtime, qwen


def _sys(**kw):
    p = {"speaker_name": "阿彩", "speaker_persona": "洗头妹", "channel": "say",
         "persona": {"name": "蔡妍"}, "context": {}}
    p.update(kw)
    return qwen._build_system(p)


# ── ① 旁白可以留空 ──────────────────────────────────────────────────────────────

def test_narration_is_not_forced_every_beat():
    """一拍纯对白不是缺陷, 是节奏。逼着每拍必产旁白, 换来的就是复读。"""
    tool = qwen._render_tool({"channel": "say"}, "阿彩", False, None, "say", "")
    req = tool["function"]["parameters"]["required"]
    assert "narration" not in req, "旁白仍是必填 — 没新东西时模型只能去写眼睛和喉结"


def test_narration_field_still_exists():
    """可留空 ≠ 砍掉: 有东西可写时它照样是主力。"""
    tool = qwen._render_tool({"channel": "say"}, "阿彩", False, None, "say", "")
    props = tool["function"]["parameters"]["properties"]
    assert "narration" in props
    assert "留空" in props["narration"]["description"], "没告诉模型什么时候可以不写"


# ── ② 写之前就把复读过的意象摊出来 ──────────────────────────────────────────────

def test_motifs_finds_what_repeats():
    st = {"_recent_narr": [
        "他低头看你，喉结上下滚动，桃花眼里翻涌着暗色。",
        "他又低头看你，喉结上下滚动了两次，那双桃花眼红着。",
        "他低头看你，桃花眼眯起来。",
    ]}
    got = "".join(runtime.narration_motifs(st))
    assert "低头看你" in got, f"三拍写了三次的动作没被认出来: {got}"
    assert "桃花眼" in got or "喉结" in got, f"复读的意象没被认出来: {got}"


def test_motifs_ignores_one_offs():
    """只出现过一次的不算意象 —— 那是新东西, 不该被禁。"""
    st = {"_recent_narr": ["巷口的风卷起一张旧报纸。", "他低头看你。", "远处有人在唱粤曲。"]}
    got = "".join(runtime.narration_motifs(st))
    assert "旧报纸" not in got and "粤曲" not in got, f"把新意象也禁了: {got}"


def test_motifs_is_empty_on_a_fresh_run():
    assert runtime.narration_motifs({}) == []
    assert runtime.narration_motifs({"_recent_narr": ["只有一拍。"]}) == []


def test_motifs_are_capped():
    """给模型的清单不许无限长 —— 提示词是有预算的。"""
    st = {"_recent_narr": ["他低头看你，喉结滚动，桃花眼，薄汗，衬衫敞着，皮带挂腰间，指节泛白。"] * 4}
    assert len(runtime.narration_motifs(st)) <= 8


def test_motifs_reach_the_prompt():
    """摊出来还得真进提示词, 否则等于没做。"""
    s = _sys(narr_motifs=["低头看你", "桃花眼"])
    assert "低头看你" in s and "桃花眼" in s
    assert "换" in s or "别再" in s or "已经写过" in s, "只列了词却没说要拿它怎么办"


def test_no_motifs_no_block():
    """没有复读时不许平白多一段提示词 (每回合都在花 token)。"""
    s = _sys()
    assert "已经写过" not in s
