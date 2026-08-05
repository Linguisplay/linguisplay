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


# ── 窗口口径: 数【玩家回合】而不是数【消息条数】 (旁白进记忆之后的必修) ──────────

def _turn_hist(n_turns):
    """一个玩家回合 = 玩家拍 + 旁白 + 对白 三条消息 (旁白 2026-08-04 起也进记忆)。"""
    h = []
    for i in range(n_turns):
        h += [{"role": "user", "content": f"玩家第{i}句"},
              {"role": "assistant", "content": f"旁白第{i}段"},
              {"role": "assistant", "content": f"阿珍：台词第{i}句"}]
    return h


def _win(n_turns):
    p = {"speaker_name": "阿珍", "speaker_persona": "洗头妹", "channel": "say",
         "persona": {"name": "蔡妍"}, "context": {}, "history": _turn_hist(n_turns),
         "player_input": "你好"}
    m = qwen._turn_messages(p, "SYS", "阿珍")
    return [x for x in m if x.get("role") in ("user", "assistant")]


def _turns_covered(win):
    import re
    return len({re.search(r"玩家第(\d+)句", x["content"]).group(1)
                for x in win if x.get("role") == "user" and re.search(r"玩家第(\d+)句", x["content"])})


def test_window_counts_player_turns_not_messages():
    """旁白进记忆后, 按【条数】切窗会让覆盖的回合数掉一半 —— 改按玩家回合切。

    实弹 2026-08-04: 40 个回合的局, 按 14 条消息切只覆盖 6 个玩家回合
    (加旁白前是 7 个)。角色因此比以前更健忘, 这与「让它记得住」正好相反。"""
    covered = _turns_covered(_win(40))
    assert covered >= 12, f"窗口只覆盖 {covered} 个玩家回合 — 按条数切, 旁白把对白挤走了"


def test_window_still_blocks_for_the_cache():
    """按回合切之后, 块状滑窗那条不变量仍要成立 (缓存不许因此退化)。"""
    a, b = _win(40), _win(41)
    assert a[0] == b[0], "回合口径下窗口边界又开始逐回合挪了 — 缓存会断"
