# -*- coding: utf-8 -*-
"""🏛 故事年代 (Yi 2026-08-04:「让玩家选故事背景的时间，但是这个时间不过是给 AI
角色和世界观的补全，不管是星期还是日期都按照玩家的时区走」)。

所以年代与日历【彻底分家, 一个字段都不共用】:
  · 日历 = 玩家自己的真实日历 (state["tz"], 见 test_tz.py)
  · 年代 = 一段世界观文字, 绝不进任何日期公式

准入只有一条: 玩家【亲手写了世界观】才收年代。剧本自带的设定里常常写死了年代
(「深夜加班后那对刺眼的车灯」「新区的玻璃楼」), 硬加一句 1899 会让同一份文本自相
矛盾 —— 而开局班底与修为阶梯正是拿它去生成的, 生成完改不回来。
"""
from app.engine import qwen, runtime


def _content(era=""):
    sb = {"enabled": True}
    if era:
        sb["era"] = era
    return {"story": {"id": "s", "sandbox": sb,
                      "phone": {"device": "传讯符"},
                      "tuning": {"turns_per_slot": 6},
                      "characters": [{"id": "a", "name": "甲", "is_lead": True}],
                      "acts": [{"index": 1, "title": "一"}]},
            "secrets": []}


# ── 读取口 ────────────────────────────────────────────────────────────────
def test_era_reads_back_and_defaults_to_empty():
    assert runtime.era_of(_content("1899年，清末")) == "1899年，清末"
    assert runtime.era_of(_content()) == ""
    for junk in ({}, {"story": None}, {"story": {"sandbox": "x"}}, {"story": {}}):
        assert runtime.era_of(junk) == ""


def test_era_never_touches_the_calendar():
    """年代进了日期公式就是设计事故。开着年代跑一次对钟, clock 必须与没年代时一样。"""
    st_a, st_b = runtime.default_state(), runtime.default_state()
    base = _content()
    base["story"]["tuning"]["real_clock"] = 1
    withera = _content("三千年后")
    withera["story"]["tuning"]["real_clock"] = 1
    runtime.sync_real_clock(base, st_a)
    runtime.sync_real_clock(withera, st_b)
    assert st_a["clock"] == st_b["clock"], "年代影响了日历"


# ── 提示词里的年代块 ──────────────────────────────────────────────────────
def test_the_era_rule_is_empty_without_an_era():
    """没设定年代的本子, 提示词必须逐字不变 (全站绝大多数是这一类)。"""
    assert qwen._era_rule({}) == ""
    assert qwen._era_rule({"era": "  ", "device": "手机"}) == ""


def test_the_era_rule_carries_the_era_and_forbids_announcing_it():
    r = qwen._era_rule({"era": "1899年，清末", "device": "传讯符"})
    assert "1899年，清末" in r
    assert "不主动报年号" in r, "少了这句, 角色会变成报时机器人的年代版"


def test_the_phone_is_exempt_inside_the_same_clause():
    """⚠️ 豁免必须与「越出年代就是穿帮」在【同一段】。另起一块会被前面那句压过,
    模型在 1899 档收到短信就拒答「这是什么妖术」—— Yi 明令小手机任何年代全开,
    图标亮着不算交付, 功能通了才算。"""
    r = qwen._era_rule({"era": "1899年", "device": "传讯符"})
    assert "传讯符" in r, "豁免子句没带上这个世界的设备名"
    assert "绝不许因为年代而拒绝使用它" in r
    assert r.count("【年代】") == 1, "年代被拆成了两块, 后一块会被前一块压过"


def test_a_world_with_no_named_device_still_gets_an_exemption():
    r = qwen._era_rule({"era": "盛唐"})
    assert "随身通讯之物" in r and "拒绝使用它" in r


# ── 主叙事的年代块 ────────────────────────────────────────────────────────
def _sys(era, device="传讯符"):
    out = qwen._build_system({
        "speaker_name": "甲", "world": "一座运河小镇", "era": era, "device": device,
        "persona": {"name": "我"}, "language": "zh"})
    return out if isinstance(out, str) else "\n".join(out)


def test_the_main_prompt_gains_an_era_block_only_when_there_is_an_era():
    assert "【年代】" not in _sys("")
    got = _sys("1899年，清末")
    assert "【年代】" in got and "1899年，清末" in got
    assert "绝不许因为年代而拒绝使用它" in got, "主叙事的年代块少了手机豁免"


# ── 生图: 不改一行代码, 靠前缀白拿 ────────────────────────────────────────
def test_the_background_prompt_picks_the_era_up_for_free():
    """背景图那个槽读的就是 world_long 的前 140 字。年代前缀放在开头, 它自动就进去了 ——
    这一步【一行代码都不用改】。同时空镜铁律必须仍然在【句尾】: 它是「背景就是背景」
    的唯一执行点, 被挤出截断窗口就是静默失败。"""
    from app.routers.runs import _bg_prompt
    c = _content("1899年，清末")
    c["story"]["world_long"] = "【年代】1899年，清末。一座运河小镇，码头上堆着待运的茶箱。"
    p = _bg_prompt(c, {"id": "l1", "name": "码头", "detail": "青石阶一直铺到水里"})
    assert "1899年，清末" in p, "年代没进生图提示词"
    assert p.rstrip().endswith("没有文字、字幕或水印"), "空镜铁律被挤出了句尾"
    assert "铁律：空镜" in p


def test_a_very_long_era_cannot_push_the_scene_out_of_the_window():
    """年代前缀吃的是那 140 字的窄槽 —— 长年代不许把地点描述整段挤掉。"""
    from app.routers.runs import _bg_prompt
    c = _content("x")
    c["story"]["world_long"] = "【年代】" + "清" * 200 + "。运河小镇"
    p = _bg_prompt(c, {"id": "l1", "name": "码头", "detail": "青石阶"})
    assert "场景：码头" in p and "青石阶" in p, "地点描述被年代挤没了"
