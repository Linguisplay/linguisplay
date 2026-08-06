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


# ── 三个实测出来的洞 (2026-08-05 文风调研复核) ──────────────────────────────────

def test_english_length_clause_is_understood():
    """en 本子的作者闸从来没生效过。Golden Hour 的卡里明写着
    「Scenery is capped at two sentences for the whole turn」, 而正则只认中文限量词,
    实测抠出空串 —— 它一直在走引擎默认的 3~5 句。这是我建正则时留下的洞。"""
    for s in ("Scenery is capped at two sentences for the whole turn.",
              "Narration: at most three sentences per beat.",
              "Keep description to no more than forty words."):
        got = qwen._style_len_rule("Voice: dry, close third. " + s)
        assert got, f"英文长度条款抠不出来: {s}"
    out = qwen._defer_style({"style": "Voice: dry. Scenery is capped at two sentences."},
                            "请写 3~5 句。")
    assert "3~5" not in out


def test_english_hoist_ignores_unrelated_english_caps():
    s = "Voice: noir. At most three named characters per scene. Never use em dashes."
    assert "3~5 句" in qwen._defer_style({"style": s}, "请写 3~5 句。")


def test_more_than_two_clauses_survive():
    """作者写三四条闸就丢第三条 —— out[:2] 是我写的, 当时只见过最多两条的卡。
    新卡按四条设计 (旁白句数/台词字数/写景/身体反应各一条), 各管各的, 不是竞争的数字。"""
    s = ("作者腔：白描。经济律：旁白每拍最多三句；单句台词不超过二十五字；"
         "写景至多一句；身体反应至多一句。")
    got = qwen._style_len_rule(s)
    assert got.count("；") >= 2, f"三条以上的闸被截了: {got}"
    assert "身体反应" in got or "写景" in got


def test_units_beyond_sentence_and_char_are_accepted():
    """过滤器只认「句/字」, 作者用「段/词」写的闸被静默吃掉。
    但「个/次」不能收 —— 「最多出现三个人名」会被误捞, 见 test_hoist_does_not_grab_unrelated_caps。"""
    assert qwen._style_len_rule("经济律：全回合旁白最多四段。")
    assert qwen._style_len_rule("经济律：每拍不超过四十五词。")
    assert not qwen._style_len_rule("同一场最多出现三个人名。")


# ── 开场那一拍的文风卡被砍掉一半 ────────────────────────────────────────────────
# runtime.py:3068 写着 style[:160]，而忌用清单按惯例写在卡尾。实测生产 15 张卡:
# 7 张在开场那一拍【完全看不到自己的忌用清单】(斗罗/科瓦兹/不朽/猫铃堂/GH/寒山…),
# 1 张连长度闸都丢了。留存最贵的第一拍, 管得最松。

LONG_CARD = ("作者腔：清冷白描。情绪交给器物与节气，不交给形容词。" + "补白。" * 40 +
             "经济律：写景全回合合计不超过两句。"
             "忌用清单，一个都不许犯：绝美 / 俊美无俦 / 邪魅一笑 / 薄唇轻启")


def test_truncated_style_keeps_its_length_gate():
    head = qwen.style_head(LONG_CARD, 160)
    assert qwen._style_len_rule(head), "截断之后长度闸没了"


def test_truncated_style_keeps_its_ban_list():
    head = qwen.style_head(LONG_CARD, 160)
    assert "邪魅一笑" in head and "俊美无俦" in head, "截断之后忌用清单没了"


def test_truncated_style_keeps_the_opening_voice():
    """保尾巴不能把开头的作者腔丢掉 —— 那是这张卡的身份。"""
    assert "清冷白描" in qwen.style_head(LONG_CARD, 160)


def test_short_style_is_untouched():
    s = "作者腔：白描。经济律：写景不超过两句。忌：绝美 / 邪魅一笑"
    assert qwen.style_head(s, 160) == s


def test_style_head_stays_bounded():
    """保尾巴不等于放弃预算 —— 开场提示词还有别的东西要装。"""
    assert len(qwen.style_head("废话。" * 500, 160)) <= 400


def test_style_head_is_safe_on_junk():
    assert qwen.style_head("", 160) == ""
    assert qwen.style_head(None, 160) == ""


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
