# -*- coding: utf-8 -*-
"""🧊 前缀缓存第二刀: 逐字近史的【块状滑窗】(2026-08-04)。

第一刀 (test_prompt_prefix_cache.py) 把 system 里每回合都变的那句挪到了末尾, 生产
命中率从 0 变成 17%。但最贵的 plan 那一路只有 14% —— 因为 system 之后还接着
`history[-14:]`, 而它【每回合往前滑一格】: 第 N 回合是 [3..16], 第 N+1 回合是
[4..17]。开头那条一掉, 整段消息序列的前缀就跟上一回合对不上了, 优惠又断一截。

修法: 窗口边界改成【每 _B 回合才挪一次】(块状), 中间那几回合的边界逐字不动 ——
于是连续几个回合的 messages 前缀完全相同, 缓存吃得满。代价是最多多带 _B 条历史
(上下文变多不变少, 方向是安全的)。
"""
from app.engine import qwen


def _hist(n):
    return [{"role": "user" if i % 2 == 0 else "assistant", "content": f"第{i}句"}
            for i in range(n)]


def _msgs(n):
    """取第 n 条历史长度下, 喂给模型的消息序列 (只看 system 之后的历史部分)。"""
    p = {"speaker_name": "阿珍", "speaker_persona": "洗头妹", "channel": "say",
         "persona": {"name": "蔡妍"}, "context": {}, "history": _hist(n),
         "player_input": "你好"}
    return qwen._turn_messages(p, "SYS", "阿珍")


def _prefix_len(a, b):
    """两个消息序列逐条比对, 返回完全相同的前缀条数。"""
    n = 0
    while n < min(len(a), len(b)) and a[n] == b[n]:
        n += 1
    return n


def test_window_edge_holds_still_between_blocks():
    """块内的连续回合: 历史窗口的【第一条】必须逐字不变, 否则前缀立刻断。"""
    a = _msgs(40)
    b = _msgs(41)
    # 找到两次调用里第一条历史消息 (system 之后)
    ha = [m for m in a if m.get("role") in ("user", "assistant")]
    hb = [m for m in b if m.get("role") in ("user", "assistant")]
    assert ha and hb
    assert ha[0] == hb[0], (
        f"窗口边界每回合都在挪: 上一回合从 {ha[0]['content']!r} 起, "
        f"这一回合从 {hb[0]['content']!r} 起 —— 前缀当场断掉")


def test_prefix_survives_several_turns_inside_one_block():
    """同一块内连打几个回合, 消息前缀应当越来越长而不是每回合归零。"""
    base = _msgs(40)
    for extra in (1, 2, 3):
        nxt = _msgs(40 + extra)
        shared = _prefix_len(base, nxt)
        assert shared >= 3, f"第 {extra} 个回合后公共前缀只剩 {shared} 条消息"


def test_block_edge_does_move_eventually():
    """但边界不能永远不动 —— 否则历史无限膨胀。跨过一个块之后必须前移。"""
    ha = [m for m in _msgs(40) if m.get("role") in ("user", "assistant")]
    hz = [m for m in _msgs(60) if m.get("role") in ("user", "assistant")]
    assert ha[0] != hz[0], "20 个回合过去了窗口还没挪 — 历史会无限涨"


def test_window_never_shrinks_below_the_contract():
    """窗口不许比 MEMORY_WINDOW 还小: 少给历史等于让角色更健忘。"""
    from app.engine import runtime
    for n in (20, 25, 31, 44):
        h = [m for m in _msgs(n) if m.get("role") in ("user", "assistant")]
        assert len(h) >= runtime.MEMORY_WINDOW, \
            f"历史 {n} 条时只喂了 {len(h)} 条, 少于合同 {runtime.MEMORY_WINDOW}"
