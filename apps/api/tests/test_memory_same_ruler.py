# -*- coding: utf-8 -*-
"""🧠 摘要和窗口必须用同一把尺 (线上实测 2026-08-08)。

角色的记忆有两层: 近处是【逐字窗口】(qwen.history_window), 远处是【滚动摘要】
(_update_memory_for)。摘要该从窗口够不着的地方开始接手 —— 可这两层从前用的是两把尺:

  窗口: 按【玩家回合】切 (2026-08-04 改的, 因为旁白进记忆后一回合从 2 条变 3 条)
  摘要: 按【消息条数】切 (len(char_history) - MEMORY_WINDOW)

生产全量扫 48 个有摘要的角色:
  · 47 个【重复覆盖】—— 中位 21 条消息同时躺在窗口里和摘要里, 同一段话付两份钱
  · 1 个【真盲区】—— 漏了 95 条 (那是最长的一局, 141 个玩家回合)

两个症状一个根: 尺不一样。修法是让摘要去问窗口「你到底留了哪些」, 而不是自己另算一遍。
这跟 2026-08-08 关系判官那个 at 用 _time_index、判据用 turn_seq 是同一类错。
"""
from app.engine import qwen, runtime


def _hist(turns):
    """turns 个玩家回合, 每回合 1 条玩家 + 2 条角色 (旁白+台词)。"""
    out = []
    for i in range(turns):
        out.append({"role": "user", "content": f"玩家第{i}句"})
        out.append({"role": "assistant", "content": f"旁白{i}"})
        out.append({"role": "assistant", "content": f"甲：台词{i}"})
    return out


def test_the_cutoff_matches_what_the_window_actually_drops():
    """摘要的起点 = 窗口留下的那一段之前的所有东西。不多不少。"""
    h = _hist(40)
    shown = qwen.history_window(h, runtime.MEMORY_WINDOW)
    assert runtime.memory_cutoff(h) == len(h) - len(shown)


def test_short_history_needs_no_summary():
    h = _hist(3)
    assert runtime.memory_cutoff(h) == 0


def test_nothing_is_covered_twice():
    """⚠️ 47/48 的那个症状: 摘要盖过的还留在窗口里, 同一段话付两份钱。"""
    h = _hist(40)
    cut = runtime.memory_cutoff(h)
    shown = qwen.history_window(h, runtime.MEMORY_WINDOW)
    assert h[cut:] == shown, "摘要的结束点和窗口的开始点对不上"


def test_nothing_falls_between_them():
    """⚠️ 另一个症状: 长局里 95 条既没进摘要也不在窗口 —— 玩家眼里就是「突然失忆」。"""
    for turns in (10, 25, 40, 80, 141):
        h = _hist(turns)
        cut = runtime.memory_cutoff(h)
        shown = qwen.history_window(h, runtime.MEMORY_WINDOW)
        assert len(h) - len(shown) == cut, f"{turns} 个回合时两层之间有缝"


def test_the_digest_advances_with_the_same_ruler():
    """端到端: 真的用它记账, 不是算完扔掉。"""
    calls = []

    class _L:
        def generate(self, p):
            calls.append(p.get("new_lines") or [])
            return {"memory": "记住了"}

    st = runtime.default_state()
    h = _hist(60)
    runtime._update_memory_for(st, "a", h, _L())
    assert calls, "该压缩的时候没压缩"
    covered = (st.get("memcov_by_char") or {}).get("a")
    assert covered == runtime.memory_cutoff(h), "记的账跟尺子对不上"
    # 压缩喂进去的正是窗口够不着的那一段
    assert calls[0] == h[:covered]
