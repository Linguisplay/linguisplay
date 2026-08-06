# -*- coding: utf-8 -*-
"""✍️ 文风的方向盘归剧本 (Yi 2026-08-05: 文风问题调剧本不调引擎)。

实弹: 引擎在提示词第 83 字说「旁白【更长】、有文学性且具体、详尽、可感」, 而八本
上架剧本里有六本的文风卡在第 1000+ 字说「写景全回合合计不超过两句」「绝不原地渲染
气氛」「忌大段抒情」。两句直接对撞, 而引擎那句排在前面、说得更绝对 —— 实测战锤那局
旁白均长 183 字, 两句写景写不出 183 字。引擎赢了, 作者输了。

而且引擎那句的理由「玩家看不到任何画面」只在纯文字时代成立 —— 现在有立绘、有背景图、
有场景切换, 玩家看得到画面。那句话是老环境的遗物, 环境变了它没跟着变。

改法不是把它写得更好, 是把长短的决定权交出去: 引擎只管【旁白该写什么】,
长短与腔调交给剧本的文风卡; 没写文风的剧本才吃一个温和的默认。
"""
from app.engine import qwen


ECONOMY = ("作者腔：清冷白描。情绪交给器物与节气，不交给形容词。"
           "经济律（最高优先）：每回合必须发生一件具体的事。写景全回合合计不超过两句。")

# 有腔调、但作者没写长度条款 (生产 15 本里有 6 本是这样: 寂声/狗笼/樱见坂/Golden Hour…)
NO_LEN = "贴身的恐怖：恐惧来自声音与光，不来自血浆。短句，多留白，能不解释就不解释。忌形容词堆叠。"


# ── 长度条款要被【捞出来】, 不能指望模型自己去 1000 字外的文风卡里翻 ────────────────
# 实测 A/B (deepseek-v4-flash, 寂声, 环视路, n=5): 只把引擎的「3~5 句」换成「听文风
# 那一段」, 均长 173→209 字、句数 6.2→9.2 —— 反而更长了。文风卡的「不超过两句」埋在
# 长文里, 模型压根没捞出来; 我拆掉的是当时唯一真在起作用的那个闸。
# 所以规则是三档, 不是两档:
#   ① 作者写了长度条款 → 把【作者的原话】搬到闸的位置 (作者赢)
#   ② 有文风卡但没写长度 → 保留引擎默认的闸 (没人说, 就别放手)
#   ③ 没有文风卡         → 保留引擎默认的闸

def test_author_length_rule_is_hoisted_to_where_a_cap_works():
    assert "不超过两句" in qwen._defer_style({"style": ECONOMY}, "请写 3~5 句。")


def test_hoisted_rule_replaces_the_engine_cap():
    """两个数字不能同时在场 —— 「3~5 句」和「不超过两句」并列, 等于没说。"""
    out = qwen._defer_style({"style": ECONOMY}, "请写 3~5 句。")
    assert "3~5" not in out


def test_style_without_a_length_rule_keeps_the_engine_cap():
    """作者没写长度就别放手 —— 拆掉唯一的闸, 实测句数从 6.2 涨到 9.2。"""
    assert "3~5 句" in qwen._defer_style({"style": NO_LEN}, "请写 3~5 句。")


def test_no_style_keeps_the_engine_cap():
    assert "3~5 句" in qwen._defer_style({}, "请写 3~5 句。")
    assert "3~5 句" in qwen._defer_style(None, "请写 3~5 句。")


def test_hoist_survives_the_shapes_authors_actually_write():
    """生产 15 本里 9 本写了长度条款, 形状就这几种。"""
    for s in ("环境与外貌描写全轮合计不超过两句。",
              "写景全回合合计不超过两句。",
              "环境描写全轮合计不超过两句；对白优先。",
              "一句话最多两个短句。"):
        out = qwen._defer_style({"style": "作者腔：白描。" + s}, "请写 3~5 句。")
        assert "3~5" not in out, f"没捞出来: {s}"
        assert "两" in out, f"捞出来了但把数字丢了: {out}"


def test_hoist_does_not_grab_unrelated_caps():
    """文风卡里也有跟旁白长短无关的数量词, 别乱捞。"""
    s = "作者腔：黑帮片。同一场最多出现三个人名。忌粤语字词。"
    assert "3~5 句" in qwen._defer_style({"style": s}, "请写 3~5 句。")


def _sys(**kw):
    p = {"speaker_name": "裴无咎", "speaker_persona": "松雪宗执剑", "channel": "say",
         "persona": {"name": "我"}, "context": {}}
    p.update(kw)
    return qwen._build_system(p)


def test_engine_stops_demanding_longer_narration():
    """引擎不许再要求「更长」—— 那是作者的决定, 不是引擎的。"""
    s = _sys(style=ECONOMY)
    assert "旁白更长" not in s, "引擎还在跟剧本抢方向盘"


def test_engine_still_says_what_narration_is_for():
    """交出长短 ≠ 什么都不说: 旁白【写什么】仍归引擎管。"""
    s = _sys(style=ECONOMY)
    assert "旁白" in s


def test_style_card_is_the_authority():
    s = _sys(style=ECONOMY)
    assert "不超过两句" in s
    i_style, i_default = s.find("文风·必须贴住"), s.find("旁白")
    assert i_style > 0
    # 文风卡里那句「优先级高于任何通用文风习惯」必须在
    assert "优先级高于" in s


def test_storyless_run_still_gets_a_gentle_default():
    """没写文风的剧本 (31 本里有 16 本) 不能没人管 —— 但默认要温和, 不是强指令。"""
    s = _sys()
    assert "旁白" in s
    assert "更长" not in s and "详尽" not in s, "默认仍然是那句强指令"


def test_default_does_not_leak_into_styled_runs():
    """有文风卡时, 通用默认不许再重复一遍长短要求 (两个声音只留一个)。"""
    s = _sys(style=ECONOMY)
    assert s.count("有文学性") == 0


# ── 另外六处偷偷规定长短的地方 ──────────────────────────────────────────────────
# 扫出来的实弹: 引擎在 narration 字段说明、群戏说明、独白拍、打量/环视、开场、
# 幕间六条路上, 分别用「铺陈」「细腻」「富有文学性」「3~5句」「详尽」下了同样的令。
# 「铺陈」和「细腻」尤其毒 —— 经济律禁的正是这两件事(原地渲染气氛、堆叠形容词),
# 而引擎却把它们写进了字段说明, 每一拍都在念。

_BANNED = ("铺陈", "细腻", "文学性", "详尽")


def test_narration_field_description_does_not_impose_a_voice():
    """字段说明只许讲【写什么】, 不许讲【写多美】。"""
    for ch, obs in (("think", False), ("do", False), ("say", True), ("say", False)):
        tool = qwen._render_tool({"channel": ch, "style": ECONOMY}, "裴无咎", obs, None, ch, "")
        nd = tool["function"]["parameters"]["properties"]["narration"]["description"]
        hit = [w for w in _BANNED if w in nd]
        assert not hit, f"channel={ch} observer={obs} 的字段说明仍在规定文风: {hit}"


def test_group_mode_narration_is_not_told_to_pile_it_on():
    s = _sys(style=ECONOMY, group_mode="primary", others=["十二少"])
    assert "铺陈" not in s


def test_line_mode_defers_sentence_count_to_the_style_card():
    """逐行兜底路: 硬写死「共3~5句」直接压过作者的「不超过两句」。"""
    d = qwen._render_directive({"channel": "think", "style": ECONOMY,
                                "persona": {"name": "我"}}, "裴无咎", [])
    assert "3~5句" not in d, "文风卡说不超过两句, 引擎还在要 3~5 句"
    assert not [w for w in _BANNED if w in d], f"逐行兜底路仍在规定文风: {d[:120]}"


def test_line_mode_keeps_its_default_without_a_style_card():
    d = qwen._render_directive({"channel": "think", "persona": {"name": "我"}}, "裴无咎", [])
    assert "旁白" in d


def test_observe_defers_to_the_style_card():
    """打量与环视整拍都是写景 —— 作者说写景不超过两句, 就该是两句。"""
    for p in ({"style": ECONOMY, "target": {"name": "裴无咎", "role": "执剑"}},
              {"style": ECONOMY}):
        s = qwen._build_observe_system(p)
        assert "3~5 句" not in s, "文风卡说不超过两句, 环视还在要 3~5 句"
        assert not [w for w in _BANNED if w in s], f"环视仍在规定文风: {[w for w in _BANNED if w in s]}"


def test_observe_keeps_its_default_without_a_style_card():
    s = qwen._build_observe_system({})
    assert "句" in s, "没文风卡时连个长短参照都没有了"


def test_intro_and_transition_defer_to_the_style_card():
    """开场与幕间是玩家读到的第一段字 —— 文风在这里就得立住。"""
    for fn in (qwen._build_intro_system, qwen._build_transition_system):
        s = fn({"style": ECONOMY, "act": {}, "world": "松雪宗"})
        hit = [w for w in _BANNED if w in s]
        assert not hit, f"{fn.__name__} 仍在规定文风: {hit}"
        assert "文风·必须贴住" in s


def test_intro_keeps_its_default_without_a_style_card():
    s = qwen._build_intro_system({"act": {}, "world": "松雪宗"})
    assert "具体" in s, "没文风卡时开场连「要具体」都没人说了"
