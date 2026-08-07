# -*- coding: utf-8 -*-
"""🗣 历史里的示范必须长得跟要求的输出一样 (Yi 报障 2026-08-07:「角色现在不能发言了」)。

生产实况: 8/6 角色台词占比 52%, 8/7 掉到 13%。查下来是个【自我强化的污染回路】:

  ① 某一拍模型忘了打行首前缀 → 分行器认不出台词, 整坨落成一条 description
  ② 那条【不带前缀】的 description 进了历史, 成了模型「我平时这么写」的示范
  ③ 下一拍更不打前缀 → 又落成 description → 回到 ①

根因在 history_for: dialogue 进历史时【贴了】说话人前缀 (「蓝信一：…」),
而 description 【不贴】。于是历史里正确示范与污染示范混在一起, 而输出协议
(_LineSegmenter) 要的是每一行都有前缀:「旁白：…」/「名字：…」。

2026-08-06 我把逐字窗口从 14 抬到 24, 等于把污染示范一次加了 70% —— 回路的增益
被我拧大了, 当天就跑飞。窗口本身没错, 错的是历史里的示范跟输出格式对不上。

修法: 旁白进历史时贴上协议自己的记号「旁白：」。原注释担心「贴了模型会学着把旁白
写成台词」—— 那说的是贴【角色名】; 「旁白」是 _LineSegmenter 保留的叙述者记号,
它会被映射回 narration, 不会串。
"""
from app.engine import qwen, runtime


BEATS = [
    {"author": "player", "type": "dialogue", "text": "你还好吗？", "present_ids": None},
    {"author": "engine", "type": "description", "present_ids": None,
     "text": "抹掉嘴角的血迹，歪头看你一眼。"},
    {"author": "engine", "type": "dialogue", "speaker_name": "蓝信一",
     "text": "小伤。蔡sir，这么晚还巡巷子？", "present_ids": None},
]


def _h():
    return runtime.history_for(BEATS, "a")


# ── 历史里的每一条都要能被输出协议认出来 ────────────────────────────────────────

def test_narration_carries_the_narrator_prefix():
    """不贴前缀的旁白就是污染示范 —— 模型照着它写, 台词也不打前缀了。"""
    narr = [m for m in runtime.history_for(BEATS, "a", tag_narration=True)
            if "抹掉嘴角" in m["content"]][0]
    assert narr["content"].startswith("旁白："), \
        f"旁白进历史时没贴协议记号: {narr['content'][:30]!r}"


def test_the_tag_is_off_unless_the_story_uses_the_line_protocol():
    """⚠️ 这一条是 2026-08-07 当天的教训: 无条件贴出了比原病更大的祸。

    行首前缀是 _LineSegmenter 的协议, 而它只活在 plan_and_render 的拍2 (还是 zh-only)。
    走 tool-call 的本子里 narration 与 speech 是两个独立 JSON 字段, 根本没有前缀这回事。
    给它们看「旁白：」的示范, 模型会把这六个字【写进正文】原样印给玩家, 逐拍叠加成
    「旁白：旁白：…」; 英文本还平白多两个汉字, 正好卡在 _lang_break 的 >=2 阈值上,
    每拍白白推倒重生一次。
    """
    narr = [m for m in _h() if "抹掉嘴角" in m["content"]][0]
    assert not narr["content"].startswith("旁白："), \
        "默认还在贴 —— tool-call 的本子会把这六个字印给玩家"


def test_a_tool_call_story_never_sees_the_tag():
    """真正的判据: 贴不贴要跟着 plan_render_on 走, 不是跟着心情走。"""
    import inspect
    src = inspect.getsource(runtime)
    assert "tag_narration=plan_render_on(content)" in src, \
        "主拍那两处没有把开关接到 plan_render_on 上"


def test_dialogue_still_carries_the_speaker():
    """这条本来就是对的, 别在修旁白时把它碰坏。"""
    d = [m for m in _h() if "小伤" in m["content"]][0]
    assert d["content"].startswith("蓝信一："), d["content"][:30]


def test_every_assistant_line_is_parseable_on_the_line_protocol():
    """真正的合同, 但【只在用行首前缀协议的那条路上成立】: 那条路上历史里每一条
    助手消息都要能被 _LineSegmenter 认出身份, 认不出的就是在教模型写出认不出的东西。

    走 tool-call 的本子不适用 —— 那边 narration 与 speech 本来就是两个独立字段,
    历史贴前缀反而会把记号印进正文 (见 test_the_tag_is_off_unless_...)。
    """
    pref = qwen._line_prefix_re()
    for m in runtime.history_for(BEATS, "a", tag_narration=True):
        if m["role"] != "assistant":
            continue
        assert pref.match(m["content"]), f"这条历史示范没有身份前缀: {m['content'][:36]!r}"


def test_the_narrator_token_maps_back_to_narration():
    """贴上去的记号必须被分行器认回旁白, 不能变成一个叫「旁白」的角色。"""
    seg = qwen._LineSegmenter("蓝信一")
    out = seg.feed("旁白：他退了半步。\n")
    kinds = {k for k, who, t in out if t.strip()}
    assert "narration" in kinds, out
    assert not any(who == "旁白" for k, who, t in out), f"「旁白」被当成角色了: {out}"


def test_player_lines_are_untouched():
    u = [m for m in _h() if m["role"] == "user"][0]
    assert u["content"] == "你还好吗？"


# ── 认知边界不许被这一刀碰松 ──────────────────────────────────────────────────

def test_the_witness_gate_still_holds():
    beats = [{"author": "engine", "type": "description", "text": "只有甲看见的雨",
              "present_ids": ["a"]}]
    assert runtime.history_for(beats, "a")
    assert not runtime.history_for(beats, "b"), "不在场的人拿到了不该有的旁白"


def test_blank_narration_is_dropped():
    beats = [{"author": "engine", "type": "description", "text": "   ", "present_ids": None}]
    assert runtime.history_for(beats, "a") == []


# ── 🔭 遥测: 这件事不许再无声烂掉 ──────────────────────────────────────────────

def test_a_speechless_turn_is_countable():
    """被直接搭话却一句台词都没有 —— 那正是这次报障的现场。
    没有读口就只能等玩家来骂, 而这次就是等来的。"""
    beats = [{"author": "engine", "type": "description", "text": "他看了你一眼。"}]
    assert runtime.speechless_turn(beats, channel="say") is True
    beats2 = beats + [{"author": "engine", "type": "dialogue",
                       "speaker_name": "蓝信一", "text": "嗯。"}]
    assert runtime.speechless_turn(beats2, channel="say") is False


def test_an_action_turn_is_allowed_to_be_silent():
    """玩家只是做了个动作, 角色不吭声是合法的, 不许误报。"""
    beats = [{"author": "engine", "type": "description", "text": "他看了你一眼。"}]
    assert runtime.speechless_turn(beats, channel="do") is False


def test_the_players_own_line_does_not_count_as_speech():
    """玩家自己那条 dialogue 不算角色开口 —— 算了就永远报不出哑巴。"""
    beats = [{"author": "player", "type": "dialogue", "speaker_name": "蔡妍", "text": "你还好吗"},
             {"author": "engine", "type": "description", "text": "他看了你一眼。"}]
    assert runtime.speechless_turn(beats, channel="say") is True


def test_a_nameless_dialogue_does_not_count_either():
    """没有说话人的 dialogue 正是解析失败的产物, 不能拿它当「说话了」。"""
    beats = [{"author": "engine", "type": "dialogue", "speaker_name": "", "text": "小伤。"}]
    assert runtime.speechless_turn(beats, channel="say") is True


# ── 冒烟门: 只断言「有 beats」是抓不住哑巴的 ──────────────────────────────────

def test_the_story_gate_checks_that_someone_speaks():
    """事故复盘: smoke_stories.py 只断言「no beats」—— 100% 全是旁白它也放行。
    这就是 1340 个单测 + 两道门全绿却漏掉「角色不能发言」的直接原因之一。

    (另一半原因是那道门跑的是 MockLLM, 桩永远按代码吐东西, 原理上抓不住
     「真模型不打前缀了」。那一类只有生产遥测能抓, 见 speechless_turn。)
    """
    import io
    src = io.open("smoke_stories.py", encoding="utf-8").read()
    assert "speechless" in src or "没人说话" in src, \
        "剧本冒烟门还是只看有没有 beats, 不看角色开没开口"


# ── 🏷 别给已经有身份的行再叠一层 (2026-08-07 查错; 这一条比今天老得多) ────────

def test_the_judges_do_not_double_label():
    """dialogue 进历史时一直带着「蓝信一：」, 而下游判官又一律前置「角色：」——
    喂进去的是「角色：蓝信一：小伤。」, 判官读到的说话人是错的。
    摘要与关系判断都建在这上面, 所以这条是双份的歪。"""
    L = [{"role": "user", "content": "你还好吗"},
         {"role": "assistant", "content": "蓝信一：小伤。"},
         {"role": "assistant", "content": "旁白：雨下得很大。"}]
    got = [qwen.QwenLLM._labelled(x, "角色：") for x in L]
    assert got == ["玩家：你还好吗", "蓝信一：小伤。", "旁白：雨下得很大。"], got


def test_a_bare_line_still_gets_labelled():
    """没有前缀的行仍要标上 —— 别把这一刀改成「一律不标」。"""
    assert qwen.QwenLLM._labelled({"role": "assistant", "content": "他抬起头。"},
                                  "角色：") == "角色：他抬起头。"
