# -*- coding: utf-8 -*-
"""🧊 提示词前缀缓存 (2026-08-04 实弹):

DeepSeek/DashScope 的前缀缓存按【逐字相同的最长前缀】命中。生产遥测实测
hit=0 / miss=11513 —— 缓存彻底失效, 每回合把 16K system 整包按全价重传。

根因只有一句话: `_build_system` 第 88 字附近那句
    "用中文。" + pace.line
里的 pace.line【每回合都变】(节奏带按乐师账本查表)。它一变, 它【后面】那十几 K
逐字不变的表演宪章、人设、schema 全部作废 —— 一个字的变动毁掉整段前缀。

修法不是删掉它, 是把它挪到 system 的【末尾】: 稳定的排前面吃缓存, 逐次变的殿后。
实测收益: 每次调用省 ~734ms, 记忆的边际成本从 101ms/千字 降到 10ms/千字
(后面所有「让角色多记一点」的改动都靠这个前提)。

这条测试守的就是那个不变量: 只有 pace 变的两个回合, system 的公共前缀必须长到
把宪章都包进去 —— 而不是在第 88 字就分叉。
"""
from app.engine import qwen


def _base(**kw):
    p = {
        "speaker_name": "阿珍",
        "speaker_persona": "银彩发廊的洗头妹，嘴快心软。",
        "persona": {"name": "蔡妍", "background": "初来乍到的外来妹。"},
        "agenda": "想弄清这个新来的女人是谁。",
        "eq_style": "嘴快心软，损人不带脏字。",
        "channel": "say",
        "context": {},
    }
    p.update(kw)
    return p


def _common_prefix(a: str, b: str) -> int:
    n = min(len(a), len(b))
    i = 0
    while i < n and a[i] == b[i]:
        i += 1
    return i


def test_pace_line_does_not_split_the_prefix():
    """两个只有节奏带不同的回合, 公共前缀必须覆盖 system 的绝大部分。"""
    a = qwen._build_system(_base(pace={"line": "台词短促（1~2句）"}))
    b = qwen._build_system(_base(pace={"line": "台词舒展（3~5句）"}))
    assert a != b, "两个回合的 pace 不同, system 理应不同"
    shared = _common_prefix(a, b)
    ratio = shared / min(len(a), len(b))
    assert ratio > 0.9, (
        f"公共前缀只有 {shared} 字 / {min(len(a), len(b))} 字 ({ratio:.1%}) —— "
        "逐次变的东西排在了前面, 后面十几K的稳定内容全被它作废")


def test_the_charter_is_inside_the_shared_prefix():
    """表演宪章是全 prompt 最大的一块稳定内容, 必须落在公共前缀里。"""
    a = qwen._build_system(_base(pace={"line": "台词短促（1~2句）"}))
    b = qwen._build_system(_base(pace={"line": "台词舒展（3~5句）"}))
    shared = a[:_common_prefix(a, b)]
    assert "【表演宪章" in shared, "宪章掉出了公共前缀 —— 每回合按全价重传"


def test_pace_line_still_reaches_the_model():
    """挪位置不是删掉: 节奏带该说的话仍然要在 system 里。"""
    s = qwen._build_system(_base(pace={"line": "台词短促（1~2句）"}))
    assert "台词短促（1~2句）" in s


def test_pace_absent_falls_back():
    """没有节奏带时仍有默认口径, 不能空着。"""
    s = qwen._build_system(_base())
    assert "台词口语化" in s
