# -*- coding: utf-8 -*-
"""🗺 地名没有描述时，到达旁白不许现编出一个别的地方 (Yi 报障 2026-08-06)。

实况: 玩家移动到【油麻地】, 引擎的换场提示写「(你带着同行的人来到了 油麻地。)」,
紧接着的到达旁白却是「推开茶餐厅的玻璃门，日光灯嗡嗡低鸣……」—— 读起来就是被
传送进了一家餐厅。

复现出的根因不在移动, 在提示词:
    地点：油麻地（）          ← detail 为空, 只剩一对空括号
而系统规则那一句写的是「必须扣住给出的地点细节，不要泛泛」——细节是空的, 规则却
逼它写具体。模型只好现编; 而「油麻地」是个【街区名】(相当于"去布鲁克林"),
最省事的具体化就是编一个小场景出来。

狗笼那本 27 个地点里 19 个 detail 是空的, 且一个都没标 generated —— 都是作者
(或起草管线) 只填了名字。所以这不是孤例, 是那本书里每一次移动都可能中招。

两头都要治:
  · 提示词: 没有 detail 时换一套说法 —— 你只知道地名, 就按【这个名字本身的尺度】
    写, 不许把它替换成一个别的具名场所。
  · 剧本门: lint 要能报出"有名字没描述"的地点, 别再放它上线。
"""
import pathlib

import pytest

from app.engine import qwen


def _prompt_for(detail, place="油麻地", observer=False):
    """把 _arrive 真实发出去的两段抓回来 (只换掉 HTTP 那一层)。"""
    box = {}

    def fake(url, key, body, **k):
        box["sys"] = body["messages"][0]["content"]
        box["user"] = body["messages"][1]["content"]

        class R:
            def json(self):
                return {"choices": [{"message": {"content": "{}"}}]}
        return R()

    old = qwen._post_chat
    qwen._post_chat = fake
    try:
        q = qwen.QwenLLM.__new__(qwen.QwenLLM)
        q._url = q._key = q._model = "x"
        q._arrive({"arrive": True, "place": place, "detail": detail,
                   "slot": "第2天·夜", "observer": observer,
                   "people": [{"name": "蓝信一", "role": "龙城帮马仔",
                               "look": "懒洋洋", "relation": "暧昧"}],
                   "player_name": "蔡妍"})
    finally:
        qwen._post_chat = old
    return box


# ── 🚫 空描述: 不许再命令模型"扣住细节" ──────────────────────────────────
def test_a_blank_detail_does_not_ship_an_empty_paren():
    box = _prompt_for("")
    assert "（）" not in box["user"] and "()" not in box["user"], \
        f"还在发空括号: {box['user'].splitlines()[0]}"


def test_a_blank_detail_swaps_the_rule_instead_of_demanding_the_impossible():
    """「必须扣住给出的地点细节」在没有细节时是一条【做不到】的命令 —— 模型只能编。"""
    box = _prompt_for("")
    assert "扣住给出的地点细节" not in box["sys"], \
        "细节是空的, 却还在命令模型扣住细节 — 它只能现编"


def test_a_blank_detail_forbids_substituting_another_named_venue():
    """这一条才是真正治「油麻地 → 茶餐厅」的: 名字是什么尺度就写什么尺度。"""
    box = _prompt_for("")
    txt = box["sys"] + box["user"]
    assert "油麻地" in txt, "地名都没带上"
    assert any(k in txt for k in ("尺度", "不要把", "不许把", "换成别的")), \
        f"没有任何一句拦着它把大区替换成一个具名小场所:\n{box['sys'][:300]}"


def test_a_real_detail_keeps_the_old_strict_rule():
    """有描述的地点逐字不变 —— 那条严格规则本来就是对的, 别误伤。"""
    box = _prompt_for("巷子最深处的旧式理发店，几张红色皮转椅，镜子斑驳。")
    assert "扣住给出的地点细节" in box["sys"], "有细节的本子被改了规矩"
    assert "旧式理发店" in box["user"]


def test_the_observer_variant_gets_the_same_treatment():
    """上帝视角那一支是另写的一段 —— 两支都要治, 不然换个模式又编。"""
    box = _prompt_for("", observer=True)
    assert "（）" not in box["user"]
    assert "扣住给出的地点细节" not in box["sys"]


@pytest.mark.parametrize("blank", ["", "   ", "\n", None])
def test_all_the_ways_a_detail_can_be_blank(blank):
    box = _prompt_for(blank)
    assert "（）" not in box["user"], f"{blank!r} 没被当成空"


# ── 🧪 红样本自验 ─────────────────────────────────────────────────────────
def test_red_sample_the_old_prompt_really_shipped_an_empty_paren():
    """修复前那一行就是 f"地点：{place}（{detail}）" —— 细节空了就剩一对空括号。"""
    before = "地点：{}（{}）".format("油麻地", "")
    assert before == "地点：油麻地（）", before
    assert "（）" in before, "红样本本身就该踩中"


# ── 🚧 剧本门: 有名字没描述要报出来 ──────────────────────────────────────
def test_the_linter_flags_a_named_place_with_no_detail():
    """狗笼 27 个地点 19 个空 detail 就这么上线了 —— 门没拦。"""
    from app.engine import logic
    # ⚠️ lint_story 吃的是 {"story": {...}} 的【包装】形, 不是裸 story ——
    #    传裸的会先撞上"没有任何幕/角色"两条错, 我要的那条根本走不到 (夹具坑)。
    content = {"story": {
        "id": "s", "title": "t",
        "characters": [{"id": "a", "name": "甲", "is_lead": True}],
        "acts": [{"index": 1, "title": "一"}],
        "locations": [{"id": "l1", "name": "有描述的", "detail": "一间旧理发店。", "exits": []},
                      {"id": "l2", "name": "油麻地", "detail": "", "exits": []}]}}
    msgs = logic.lint_story(content)
    joined = " ".join(str(m) for m in msgs)
    assert "油麻地" in joined, f"没报出空描述的地点: {msgs}"
    assert "有描述的" not in joined, f"把有描述的也报了: {msgs}"
