# -*- coding: utf-8 -*-
"""🪃 回扣旧事/对等回礼的接线 (存量实弹 9c2cee0): 指令住 system, 落账字段住 tool。
曾经 _render_tool 里 lines.append 引用不存在的局部变量 → 回扣回合 NameError
静默掉回慢路径, 指令从没到过模型。"""
from app.engine import qwen

CB = {"callback": {"material": "那晚天台上的账本", "mode": "hard"},
      "channel": "say"}


def test_render_tool_callback_turn_does_not_crash():
    tool = qwen._render_tool(CB, "阿珍", False, None, "say", "x")
    props = tool["function"]["parameters"]["properties"]
    assert "callback_done" in props
    assert "callback_done" in tool["function"]["parameters"]["required"]


def test_callback_instruction_reaches_system():
    sys = qwen._build_system(CB)
    assert "【回扣旧事】" in sys and "那晚天台上的账本" in sys


def test_disclose_instruction_reaches_system():
    sys = qwen._build_system({"disclose": "你也说件自己的糗事", "channel": "say"})
    assert "【对等回礼】" in sys


def test_member_and_think_skip_the_blocks():
    assert "【回扣旧事】" not in qwen._build_system({**CB, "group_mode": "member"})
    assert "【回扣旧事】" not in qwen._build_system({**CB, "channel": "think"})


def test_plan_tool_callback_turn_does_not_crash():
    tool = qwen._plan_tool(CB, "阿珍", False, None, "say", "x")
    assert tool["function"]["name"] == "plan_turn"
    assert "callback_done" in tool["function"]["parameters"]["properties"]
