# -*- coding: utf-8 -*-
"""🎬 换个地方 ≠ 开一场新戏 (Yi 报障 2026-08-06「切地图场景扰乱剧情」)。

Yi 勾了全部四条症状:
    ① 聊到一半的线断了      —— 刚才那人问你的话没人提了, 建议选项也全换掉
    ② 一大段景砸下来        —— 像插播广告, 把对话节奏硬切开
    ③ 在场的人像重新认识    —— 同行的人跟着你走过去, 到达旁白把 TA 从头介绍一遍
    ④ 剧情推进被打回去      —— 目标/正在做的事像被清零

08-06 已经修过一刀 (把 recent/style 喂进到达旁白), 文字层的"接着演"做得挺全,
但四条症状照旧 —— 因为病在【结构】: 移动这个动作把"同一场戏"当成了"新一场戏"。

四处结构修法, 一一对应:
    ① 建议不再整批覆盖 —— 还指着在场的人的那些留着
    ② 没有生面孔时, 到达旁白只写空间, 写短
    ③ 同行的人不进"介绍名单" —— 只写 TA 此刻在做什么
    ④ 目标随行 —— 把当前目标喂进去, 让它接着演而不是另起
"""
import copy

import pytest

from app.engine import runtime

CONTENT = {"story": {"id": "s",
                     "characters": [{"id": "pc", "name": "我", "is_lead": True},
                                    {"id": "b", "name": "蓝信一", "role": "龙城帮马仔",
                                     "persona_text": "懒洋洋的桃花眼。"},
                                    {"id": "z", "name": "阿珍", "role": "茶餐厅老板娘",
                                     "persona_text": "嗓门大。"}],
                     "acts": [{"index": 1, "title": "一"}],
                     "locations": [{"id": "l1", "name": "果栏", "detail": "水果箱堆到腰。",
                                    "exits": ["茶餐厅"]},
                                   {"id": "l2", "name": "茶餐厅", "detail": "卡座油亮。",
                                    "exits": ["果栏"]}]}}


def _c():
    return copy.deepcopy(CONTENT)


def _st(loc="l1", **kw):
    st = runtime.default_state()
    st["location_id"] = loc
    st["player_character_id"] = "pc"
    st["mode"] = "character"
    st.update(kw)
    return st


class Spy:
    def __init__(self):
        self.p = {}

    def generate(self, prompt):
        if prompt.get("arrive"):
            self.p = dict(prompt)
        return {}


# ── ③ 同行的人不许被重新介绍 ────────────────────────────────────────────
def test_a_companion_is_not_in_the_introduce_list():
    """TA 跟着你一路走过来的, 到达旁白却把长相身份从头写一遍 —— 像第一次见面。"""
    c, st = _c(), _st("l2", following=["b"])
    st["char_pins"] = {"z": "l2"}
    spy = Spy()
    runtime.arrival_narration(c, st, {"name": "我"}, llm=spy)
    people = spy.p.get("people") or []
    byname = {p["name"]: p for p in people}
    assert byname.get("蓝信一", {}).get("with_you") is True, \
        f"同行的人没被标出来: {people}"
    assert not byname.get("阿珍", {}).get("with_you"), "本来就在这儿的人被当成同行了"


def test_the_prompt_tells_the_model_not_to_reintroduce_companions():
    from app.engine.qwen import _arrive_people_block
    txt = _arrive_people_block([
        {"name": "蓝信一", "role": "马仔", "look": "桃花眼", "relation": "暧昧", "with_you": True},
        {"name": "阿珍", "role": "老板娘", "look": "嗓门大", "relation": "熟人"}])
    assert "蓝信一" in txt and "阿珍" in txt
    assert any(k in txt for k in ("跟你一起", "同行", "一路")), \
        f"没告诉模型谁是跟着来的:\n{txt}"


# ── ② 没有生面孔时, 别整段景砸下来 ──────────────────────────────────────
def test_moving_with_only_familiar_faces_asks_for_a_short_beat():
    """一屋子人都是跟你一起来的 → 没有"介绍"要做, 只用一句话交代换了地方。"""
    c, st = _c(), _st("l2", following=["b"])
    spy = Spy()
    runtime.arrival_narration(c, st, {"name": "我"}, llm=spy)
    assert spy.p.get("brief") is True, \
        "没有生面孔还要求写 2~4 句的运镜 — 那就是玩家说的「插播广告」"


def test_a_new_face_still_gets_the_full_pan():
    c, st = _c(), _st("l2")
    st["char_pins"] = {"z": "l2"}
    spy = Spy()
    runtime.arrival_narration(c, st, {"name": "我"}, llm=spy)
    assert not spy.p.get("brief"), "有生面孔时该好好写"


# ── ④ 目标随行 ──────────────────────────────────────────────────────────
def test_the_current_goal_rides_along():
    """不带目标, 到达旁白结构上就只能另起一段 —— 读着像剧情被清零。"""
    c, st = _c(), _st("l2")
    st["goal"] = "找到那本被撕掉一页的账簿"
    spy = Spy()
    runtime.arrival_narration(c, st, {"name": "我"}, llm=spy)
    assert "账簿" in str(spy.p.get("goal") or ""), f"目标没随行: {spy.p.get('goal')!r}"


# ── ① 建议不许整批覆盖 ──────────────────────────────────────────────────
def test_suggestions_pointing_at_people_still_here_survive_a_move():
    """聊到一半的线断了 —— 那几个指着在场的人的选项当场消失, 玩家找不回那条线。"""
    c, st = _c(), _st("l1")
    st["char_pins"] = {"b": "l1"}
    st["suggestions"] = ["我追问蓝信一那句话是什么意思", "我四下看看"]
    runtime.set_follow(c, st, "b", True)
    runtime.apply_move(c, st, "茶餐厅")
    kept = runtime.carry_suggestions(c, st, ["我打量这间茶餐厅"])
    assert any("蓝信一" in s for s in kept), \
        f"跟着你走的人, 那条线的选项却被丢了: {kept}"


def test_suggestions_about_people_left_behind_are_dropped():
    """反过来: 指着已经不在场的人的选项必须换掉 —— 不然玩家点了个空。"""
    c, st = _c(), _st("l1")
    st["char_pins"] = {"b": "l1"}
    st["suggestions"] = ["我追问蓝信一那句话是什么意思"]
    runtime.apply_move(c, st, "茶餐厅")          # 没带上他
    kept = runtime.carry_suggestions(c, st, ["我打量这间茶餐厅"])
    assert not any("蓝信一" in s for s in kept), \
        f"人都不在了还留着指着他的选项: {kept}"


def test_the_new_suggestions_are_always_there():
    c, st = _c(), _st("l2")
    st["suggestions"] = []
    kept = runtime.carry_suggestions(c, st, ["我打量这间茶餐厅"])
    assert kept, "新地方的建议一条都没有"


def test_carrying_does_not_pile_up_forever():
    c, st = _c(), _st("l1")
    st["char_pins"] = {"b": "l1"}
    st["suggestions"] = [f"我问蓝信一第{i}件事" for i in range(6)]
    runtime.set_follow(c, st, "b", True)
    runtime.apply_move(c, st, "茶餐厅")
    kept = runtime.carry_suggestions(c, st, ["我打量这间茶餐厅", "我坐下"])
    assert len(kept) <= 4, f"选项堆成了一屏: {kept}"


# ── 🧪 红样本自验 ───────────────────────────────────────────────────────
def test_red_sample_wholesale_replacement_loses_the_thread():
    """修复前是 st["suggestions"] = arrival_suggestions(...) —— 整批覆盖。"""
    old_thread = ["我追问蓝信一那句话是什么意思"]
    fresh = ["我打量这间茶餐厅"]
    replaced = list(fresh)                      # 旧写法
    assert not any("蓝信一" in s for s in replaced), "红样本本身就该把线弄丢"
