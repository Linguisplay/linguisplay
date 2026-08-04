# -*- coding: utf-8 -*-
"""🧩 模型把 list 字段写成字符串时, 不许逐字符炸开。

Yi 报障 2026-08-04:「对【】"" 这种符号的截断有问题」, 附了一张建议选项的样子:

    我当是夸奖好了。      ← 这是正文
    [                     ← chip 1
    "                     ← chip 2

看着像"截断把成对符号切断了", 其实根本不是截断 —— 是【类型混淆】:

    directed["suggestions"] = '["我当是夸奖好了。", "我笑着摇头"]'   # 模型给了字符串
    [str(x).strip()[:48] for x in directed["suggestions"]]         # 逐字符迭代!
    → ['[', '"', '我', '当', '是', ...]   前两项就是那两个 chip

`(x or [])` 这个惯用法挡不住 —— 非空字符串是真值, 照样能迭代。全仓 26 处迭代模型
字段, 其中 9 处是 `str(x)` 形状 = 静默出垃圾 (另外那些迭代 dict 的会 AttributeError
炸出来, 至少不沉默)。手机短信 msgs 占了五处 —— 玩家会一个字收到一条短信。

收成一个 as_str_list(): 字符串当【一条】, 看着像 JSON 数组的先试着解开。
"""
import pytest

from app.engine import runtime


# ── 🧩 收口函数本身 ─────────────────────────────────────────────────────────
def test_a_plain_string_counts_as_one_item_not_a_pile_of_chars():
    assert runtime.as_str_list("我笑着摇头") == ["我笑着摇头"]


def test_a_json_array_string_gets_parsed_back_into_items():
    got = runtime.as_str_list('["我当是夸奖好了。", "我笑着摇头"]')
    assert got == ["我当是夸奖好了。", "我笑着摇头"], f"没解开 JSON: {got}"


def test_a_real_list_passes_through():
    assert runtime.as_str_list(["甲", "乙"]) == ["甲", "乙"]


def test_none_and_empty_are_empty():
    assert runtime.as_str_list(None) == []
    assert runtime.as_str_list("") == []
    assert runtime.as_str_list([]) == []
    assert runtime.as_str_list(["", "  "]) == []


def test_broken_json_array_is_kept_whole_not_shredded():
    """解不开就整条留着 —— 宁可给一条怪句子, 也不给一串标点。"""
    got = runtime.as_str_list('["没收尾的数组')
    assert got == ['["没收尾的数组'], got
    assert len(got) == 1


def test_numbers_and_odd_types_do_not_explode():
    assert runtime.as_str_list(42) == ["42"]
    assert runtime.as_str_list(("甲", "乙")) == ["甲", "乙"]


# ── 🧪 红样本自验: 旧写法确实会碎 ───────────────────────────────────────────
def test_red_sample_the_old_comprehension_really_shreds():
    raw = '["我当是夸奖好了。", "我笑着摇头"]'
    old = [str(x).strip()[:48] for x in raw if str(x).strip()]
    assert old[:2] == ["[", '"'], f"红样本没复现出 Yi 看到的那两个 chip: {old[:2]}"
    assert runtime.as_str_list(raw)[:2] != ["[", '"'], "修完还是碎的"


# ── 💬 建议 chips: Yi 实际看到的那一幕 ──────────────────────────────────────
SBOX = {"story": {"id": "s", "characters": [{"id": "a", "name": "甲", "is_lead": True}],
                  "acts": [{"index": 1, "title": "一"}], "locations": []}}


class StrSuggestLLM:
    """把 suggestions 写成字符串的模型 (线上真会这么干)。"""

    def __init__(self, payload):
        self.payload = payload

    def generate(self, prompt):
        if prompt.get("risk_judge"):
            return {"risk": 100}
        out = {"beats": [{"type": "dialogue", "speaker_name": "甲", "text": "我当是夸奖好了。"}],
               "affinity_delta": 0, "advance_act": False, "ending": None}
        if prompt.get("group_mode") in ("primary", None):
            out["suggestions"] = self.payload
        return out


@pytest.mark.parametrize("payload", [
    '["我当是夸奖好了。", "我笑着摇头"]',      # JSON 数组字符串
    "我笑着摇头",                              # 光杆一句
    "【我笑着摇头】",                          # 【】包住 — Yi 点名的符号
    '"我笑着摇头"',                            # 全角引号包住
])
def test_suggestion_chips_are_never_lone_punctuation(payload):
    import copy
    c, st = copy.deepcopy(SBOX), runtime.default_state()
    out = runtime.run_turn(c, st, {"name": "我"}, "你好",
                           channel="say", llm=StrSuggestLLM(payload))
    chips = out.get("suggestions") or []
    for ch in chips:
        assert len(ch.strip()) > 1, f"出了个光杆符号 chip: {ch!r} (payload={payload!r})"
        assert ch.strip() not in ("[", "]", '"', "'", "【", "】", "「", "」", "“", "”"), \
            f"chip 是个孤零零的标点: {ch!r}"


# ── 🔖 成对符号别留半边 (Yi 点名的【】"") ───────────────────────────────────
def test_wrapping_brackets_are_unwrapped_not_left_half_open():
    got = runtime.set_suggestions({}, ["【我笑着摇头】", "“我点点头”"])
    assert got == ["我笑着摇头", "我点点头"], f"包裹符号没脱干净: {got}"


def test_an_unbalanced_leftover_bracket_gets_trimmed():
    """掐长之后常留下没闭合的半边 —— 那是真的"截断把符号切断了"。"""
    got = runtime.set_suggestions({}, ["我笑着摇头【"])
    assert got == ["我笑着摇头"], f"留了半边括号: {got}"


def test_brackets_in_the_middle_are_left_alone():
    """只脱最外层的包裹, 句子中间的符号是内容, 不许乱动。"""
    got = runtime.set_suggestions({}, ["我说【别急】然后坐下"])
    assert got == ["我说【别急】然后坐下"], got


# ── 🔒 守卫: 这一族别再长回来 ───────────────────────────────────────────────
# 一次修九处只是止血; 下次谁再写一行 `for m in (out.get("msgs") or [])` 就又破了。
# 收成源码扫描: 这些【模型给的字符串列表】字段, 只许经 as_str_list 取用。
STRING_LIST_FIELDS = ("suggestions", "msgs", "facts", "ranks",
                      "contradictions", "outline")


def _engine_sources():
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1] / "app"
    return [p for p in root.rglob("*.py") if "__pycache__" not in str(p)]


def test_model_string_lists_are_never_iterated_raw():
    """只盯【模型响应】那几个变量名。

    头一版把所有 `.get("msgs")` 都算进来, 于是把「读我们自己存的会话线程」也报成了
    违规 —— 那些是引擎自己写进去的 list, 本来就安全。守卫抓得太宽会被人当噪音关掉,
    所以收窄到模型响应的惯用变量名 (out/directed/d/res/dp/j/data/raw)。
    """
    import re
    MODEL_VARS = r"(?:out|directed|d|res|dp|j|data|raw)"
    pat = [re.compile(r"for\s+\w+\s+in\s+\(?%s(?:\.get\(\s*[\"']%s[\"']|\[\s*[\"']%s[\"'])"
                      % (MODEL_VARS, f, f)) for f in STRING_LIST_FIELDS]
    bad = []
    for p in _engine_sources():
        indoc = False
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            # docstring 里的示例代码不算数 (本文件的 as_str_list 就自带一段反面教材)
            if line.count('\"\"\"') % 2:
                indoc = not indoc
                continue
            if indoc or "as_str_list" in line:
                continue
            if any(rx.search(line) for rx in pat):
                bad.append(f"{p.name}:{i}  {line.strip()[:100]}")
    assert not bad, (
        "这些地方直接迭代了模型给的字符串列表字段 —— 模型写成字符串时会逐字符炸开"
        "(chips 变成方括号和引号), 请改走 runtime.as_str_list:\n  " + "\n  ".join(bad))


def test_red_sample_the_guard_would_catch_the_old_line():
    """红样本: 修复前那一行确实会被这条守卫抓住。"""
    import re
    before = '_sg_items = [str(x).strip()[:48] for x in directed["suggestions"] if str(x).strip()]'
    assert "as_str_list" not in before
    assert re.search(r"for\s+\w+\s+in\s+.*[\"']suggestions[\"']", before), \
        "守卫的正则抓不住旧写法 — 那它就是摆设"
