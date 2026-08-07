# -*- coding: utf-8 -*-
"""🧠 记住更多的聊天 (Yi 2026-08-06:「要存更多的聊天记录」)。

先查了四层闸, 只有一层在真咬人:

  存档     state JSON 中位 5KB、最大 48KB, 手机线程最大 2KB, DB 才 42MB
           → 存储【根本不是瓶颈】, 有的是余量
  手机线程 _thread_cap 封 60 条; 生产最长的线程 35 条 → 现在不咬, 但主动引擎一上就会
  数据库   beats 无上限 (5960 行) → 不咬
  提示词   逐字窗口 MEMORY_WINDOW=14 个【玩家回合】→ 就是它

生产实测 177 局: 玩家发言数 中位 2、p75 9、p90 19、最长 141。
按各档窗口算会丢东西的局数: 14轮→24局(13%)、20轮→14局、30轮→6局(3%)。

抬它要付延迟: 控制住缓存命中率之后, 提示词 14.5k→18.7k 字符, 中位耗时
5745→8545ms (+49%)。但【窗口是上限不是下限】—— 一局只有 5 个玩家回合时,
窗口 14 和 24 拿到的东西一模一样。所以这笔钱只花在超过 14 轮的那 13% 身上,
而那批恰恰是玩得最投入的人, 也正是「记得住」最值钱的地方。

再加一道字符预算兜底: 免得某个正文特别长的本子把提示词撑爆
(实测中位一条正文 62 字, 但 p90 的本子远不止)。
"""
from app.engine import qwen, runtime


def _hist(turns, chars=60):
    """造 n 个玩家回合的 history: 每回合 = 玩家一条 + 角色一条 + 旁白一条。"""
    out = []
    for i in range(turns):
        out.append({"role": "user", "content": f"玩家第{i}句" + "话" * (chars // 3)})
        out.append({"role": "assistant", "content": f"角色第{i}句" + "字" * (chars // 3)})
        out.append({"role": "assistant", "content": f"旁白第{i}段" + "景" * (chars // 3)})
    return out


def _msgs(history, **kw):
    p = {"speaker_name": "阿彩", "speaker_persona": "洗头妹", "channel": "say",
         "persona": {"name": "蔡妍"}, "context": {}, "history": history}
    p.update(kw)
    return qwen._build_messages(p) if hasattr(qwen, "_build_messages") else None


def _turns_kept(history, **kw):
    """真正进了消息序列的玩家回合数。"""
    got = qwen.history_window(history, **kw)
    return sum(1 for m in got if m.get("role") == "user")


# ── 窗口本身 ──────────────────────────────────────────────────────────────────

def test_the_window_is_bigger_than_it_was():
    """14 轮太小: 生产 13% 的局会被它切掉东西。"""
    assert runtime.MEMORY_WINDOW >= 24


def test_a_short_run_is_completely_unaffected():
    """这一刀对 87% 的局必须【零成本】—— 窗口是上限, 短局拿到的东西一个字不变。"""
    h = _hist(5)
    assert qwen.history_window(h) == h


def test_a_long_run_keeps_more_than_before():
    kept = _turns_kept(_hist(40))
    assert kept >= 24, f"长局只留下 {kept} 个玩家回合"


def test_it_still_drops_the_oldest_when_way_over():
    """不是无上限: 141 轮那种局不能整段塞进去。"""
    h = _hist(120)
    assert len(qwen.history_window(h)) < len(h)


# ── 块状滑窗还在 (前缀缓存的命根子, 别顺手拆了) ──────────────────────────────

def test_the_window_still_steps_in_blocks():
    """块内连续回合逐字相同, 缓存才吃得满。每回合挪一格 = 缓存当场断。

    实测过的账: 全站前缀缓存命中率 39%, 主拍那条路靠的就是这个块状边界。
    """
    base = _hist(40)
    a = qwen.history_window(base)
    b = qwen.history_window(base + _hist(1))          # 又过了一个回合
    assert a[0] == b[0], "边界每回合都在挪, 缓存断了"


def test_the_boundary_does_move_eventually():
    """只是挪得慢, 不是不挪 —— 不挪就等于没窗口。"""
    base = _hist(40)
    far = qwen.history_window(base + _hist(runtime.MEMORY_BATCH + 1))
    assert qwen.history_window(base)[0] != far[0]


def test_the_boundary_lands_on_a_player_turn():
    """口径是玩家回合不是消息条数: 旁白进记忆之后一个回合是 3 条消息,
    按条数切会让覆盖的回合数不升反降 (2026-08-04 踩过)。"""
    got = qwen.history_window(_hist(40))
    assert got[0].get("role") == "user", f"窗口从半截切进去了: {got[0]}"


# ── 字符预算兜底 ──────────────────────────────────────────────────────────────

def test_a_verbose_story_is_capped_by_chars():
    """正文特别长的本子不许把提示词撑爆 —— 实测提示词每多 4k 字符, 耗时 +49%。"""
    fat = _hist(40, chars=900)
    kept = qwen.history_window(fat)
    assert sum(len(m.get("content") or "") for m in kept) <= qwen.HISTORY_CHAR_BUDGET * 1.2


def test_the_budget_never_starves_the_recent_turns():
    """再肥也得留下最近几拍 —— 一拍都不给等于失忆。"""
    fat = _hist(40, chars=3000)
    kept = qwen.history_window(fat)
    assert sum(1 for m in kept if m.get("role") == "user") >= 3


def test_a_normal_story_never_hits_the_budget():
    """生产中位一条正文 62 字, 预算不该在正常本子上开枪。"""
    normal = _hist(runtime.MEMORY_WINDOW, chars=62)
    assert qwen.history_window(normal) == normal


# ── 手机线程: 存储不是瓶颈, 别拿 60 条卡人 ────────────────────────────────────

def test_the_phone_thread_holds_more():
    """生产最长线程 35 条、最大 2KB。主动引擎一上, 60 条很快就不够。"""
    assert runtime.THREAD_MSG_CAP >= 150


def test_capping_a_thread_keeps_the_digest_pointer_honest():
    """掐头会让下标整体前移 —— 指针不跟着减就会静静丢掉没折过的话。"""
    th = {"msgs": [{"from": "me", "text": str(i)} for i in range(runtime.THREAD_MSG_CAP + 25)],
          "digested_upto": 30}
    runtime._thread_cap(th)
    assert len(th["msgs"]) == runtime.THREAD_MSG_CAP
    assert th["digested_upto"] == 5, f"指针没跟着掐: {th['digested_upto']}"


def test_a_short_thread_is_untouched():
    th = {"msgs": [{"from": "me", "text": str(i)} for i in range(10)], "digested_upto": 3}
    runtime._thread_cap(th)
    assert len(th["msgs"]) == 10 and th["digested_upto"] == 3


# ── 两处常量不许各写各的 ──────────────────────────────────────────────────────

def test_the_window_has_one_source_of_truth():
    """qwen 里原本硬写 `_W, _B = 14, 6`, 注释写着「MUST match」——
    靠人记住就是迟早会飘。"""
    assert qwen.HISTORY_WINDOW_TURNS == runtime.MEMORY_WINDOW
    assert qwen.HISTORY_BLOCK_TURNS == runtime.MEMORY_BATCH
