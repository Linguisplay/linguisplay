# -*- coding: utf-8 -*-
"""🧭 口味罗盘 (Yi 2026-07-22: 「了解玩家的喜好非常重要，这方面一定要很强」).

三层学习, 全部确定性 (零 LLM 调用):
  ① 档内账本 state.taste — 每回合从引擎已知的硬信号记账 (追问了=探查, 掷骰拼命=冒险,
     真被撩动=心动, 走了新路=探索, 纯聊=闲话), 指数衰减让近期行为更重;
  ② 建议点击归因 — 玩家点了 chips 等于亲手投票, 该回合的口味命中加倍;
  ③ 账号级沉淀 users.taste — 每回合慢混入账号 (只学风格, 不带任何剧情内容),
     新档开局以账号口味做温启动先验 — 换个本子, 世界依然「莫名懂你」。

消费口: 主拍提示【玩家的口味】(样本够了才注入 — 保守默认, 不够不猜) + 活世界事件个性化。
铁律: 倾斜不是转向 — 提示词只许「多倾斜半分」, 绝不许硬掰剧情。
"""
from __future__ import annotations

import re
from typing import Any

# 好奇心识别 (探查口味的通用信号): 沙盒本没有 authored 秘密, 只靠秘密关键词
# 探查永远打不出来 (实弹: 「说说最近的怪事」被记成闲话)
_CURIOUS_RE = re.compile(
    r"打听|说说|讲讲|告诉我|听说|怎么回事|什么来头|内情|底细|查一?查|盘一?盘"
    r"|为什么|是谁|真相|怪事|秘密|瞒着|有什么故事|什么情况")


def curious(text: str | None) -> bool:
    return bool(_CURIOUS_RE.search(text or ""))

CLASSES = ("探查", "心动", "冒险", "探索", "闲话")
DECAY = 0.97          # 每回合全类衰减: 三十回合前的口味只剩四成话语权
CLICK_MULT = 2.0      # 点击建议 = 亲手投票, 当回合命中加倍
MIN_TOTAL = 8.0       # 样本门槛: 总权重不够不注入提示 (宁可不猜)
TOP_GAP = 0.24        # 第二名占比达标才双口味 (避免硬凑)
SEED_WEIGHT = 4.0     # 新档温启动: 账号口味折算的先验权重
BLEND = 0.03          # 账号沉淀速率 (每回合)


def _book(state: dict[str, Any]) -> dict[str, float]:
    t = state.get("taste")
    if not isinstance(t, dict):
        t = {}
        state["taste"] = t
    return t


def note(state: dict[str, Any], hits: list[str], clicked: bool = False) -> None:
    """回合末记账: 先全类衰减, 再给这一回合的命中加分 (点击建议加倍)。"""
    book = _book(state)
    for k in list(book):
        book[k] = round(book[k] * DECAY, 4)
        if book[k] < 0.01:
            del book[k]
    w = CLICK_MULT if clicked else 1.0
    for h in hits:
        if h in CLASSES:
            book[h] = round(book.get(h, 0.0) + w, 4)


def top(state: dict[str, Any], n: int = 2) -> list[str]:
    """置信的头部口味 (样本不够 = 空, 保守默认)。"""
    book = _book(state)
    total = sum(book.values())
    if total < MIN_TOTAL:
        return []
    ranked = sorted(book.items(), key=lambda kv: -kv[1])
    out = [ranked[0][0]]
    if n > 1 and len(ranked) > 1 and ranked[1][1] / total >= TOP_GAP:
        out.append(ranked[1][0])
    return out


def view(state: dict[str, Any]) -> list[dict[str, Any]]:
    """UI/验证面: 归一化的口味分布 (全量, 含权重)。"""
    book = _book(state)
    total = sum(book.values()) or 1.0
    return [{"k": k, "w": round(v / total, 3)}
            for k, v in sorted(book.items(), key=lambda kv: -kv[1])]


def prompt_line(state: dict[str, Any], zh: bool = True) -> str:
    """主拍注入行: 倾斜不转向。"""
    t = top(state)
    if not t:
        return ""
    if zh:
        return ("【玩家的口味】这位玩家的行为一贯显示TA吃这一口：" + "、".join(t)
                + "。把场面往TA爱的方向多倾斜半分（给这类内容多一点戏份和钩子）——"
                "但绝不生硬转向、绝不无中生有。")
    return ("[Player taste] This player's behavior leans toward: " + ", ".join(t)
            + ". Tilt the scene slightly toward what they enjoy; never force it.")


# ── 账号级沉淀 (跨档: 只学风格, 不带剧情) ──────────────────────────────────
def blend_account(account: dict[str, Any], run_taste: dict[str, Any]) -> dict[str, float]:
    """每回合把档内分布慢混进账号: account = (1-BLEND)*account + BLEND*run归一化。"""
    total = sum(v for v in run_taste.values() if isinstance(v, (int, float))) or 0.0
    out = {k: round(float(account.get(k, 0.0)) * (1 - BLEND), 4) for k in CLASSES
           if float(account.get(k, 0.0)) > 0.001 or k in run_taste}
    if total > 0:
        for k in CLASSES:
            share = float(run_taste.get(k, 0.0)) / total
            if share > 0:
                out[k] = round(out.get(k, 0.0) + BLEND * share, 4)
    return {k: v for k, v in out.items() if v > 0.001}


def seed_from_account(account: dict[str, Any] | None) -> dict[str, float]:
    """新档温启动: 账号口味按 SEED_WEIGHT 折算成先验 — 早期回合有底色,
    十来个回合后被本档真实行为自然盖过。"""
    if not isinstance(account, dict):
        return {}
    total = sum(v for v in account.values() if isinstance(v, (int, float))) or 0.0
    if total <= 0:
        return {}
    return {k: round(float(v) / total * SEED_WEIGHT, 4)
            for k, v in account.items() if k in CLASSES and float(v) > 0}
