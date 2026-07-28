# -*- coding: utf-8 -*-
"""🎭 IP 经典形象 (Yi 2026-07-28): 同人剧本的角色, 生图时要画成大家认得的那张脸。

病: 生图提示词只喂 name + role + persona_text，从没告诉过画图模型这是谁家的角色。
于是同人本里的知名角色画出来是个泛泛的路人 —— 玩家一眼认不出来。
而引擎里其实早有联网检索 (qwen.generate_knowledge 会判 is_ip / ip_name 并把外貌
写进【人物设定】)，只是那份产出只进角色的 knowledge 字段，从没接到画笔上。

做法两层，都不额外花钱:
  ① 确定性识别 —— 同人剧本在 trope_tags 里自带 IP 名 (第一个标签) + 同人标记;
  ② 若角色已有 knowledge (联网检索过)，从中抠出外貌段一并喂给画图模型。
再拼一句「经典形象」条款，让画图模型调用它自己认识的那张脸。
"""
from __future__ import annotations

import re
from typing import Any

# 同人标记: 命中任一即认为这本是同人/致敬作, 此时 trope_tags[0] 视作 IP 名
_FAN_MARKS = ("同人", "致敬", "二创", "fan", "fanwork", "homage")

# knowledge 块里外貌所在的段落头 (generate_knowledge 的固定结构)
_LOOK_SEC = re.compile(r"【人物设定】(.{0,400}?)(?:【|$)", re.S)
_LOOK_HINT = re.compile(r"[^。；\n]*(外貌|长相|发|瞳|眼|穿|衣|袍|装|服|身形|个子|体格)[^。；\n]*[。；]?")


def ip_of(story: Any) -> str:
    """这本剧本的 IP 名 (空 = 原创, 不加经典形象条款)。

    story 可以是 ORM 对象或 dict。判据: trope_tags 里有同人标记, 则第一个标签是 IP 名。
    """
    tags = story.get("trope_tags") if isinstance(story, dict) else getattr(story, "trope_tags", None)
    tags = [str(t).strip() for t in (tags or []) if str(t).strip()]
    if not tags:
        return ""
    if not any(m in t.lower() for t in tags for m in _FAN_MARKS):
        return ""
    head = tags[0]
    # 第一个标签本身就是同人标记时, 往后再找一个
    if any(m in head.lower() for m in _FAN_MARKS):
        head = next((t for t in tags[1:] if not any(m in t.lower() for m in _FAN_MARKS)), "")
    return head


def looks_from_knowledge(knowledge: str | None) -> str:
    """从联网检索的产出里抠出外貌那几句 (没有就返回空)。"""
    kn = (knowledge or "").strip()
    if not kn:
        return ""
    m = _LOOK_SEC.search(kn)
    body = m.group(1) if m else kn[:400]
    hits = [h.group(0).strip() for h in _LOOK_HINT.finditer(body)]
    return "，".join(dict.fromkeys(h for h in hits if h))[:180]


def canon_clause(ip: str, name: str, knowledge: str | None = None) -> str:
    """经典形象条款 (空 = 不是同人角色, 调用方照旧走原创描述)。

    放在生图提示词的最前面 —— 画风圣经之后、人物描述之前: 先钉住"这是谁"，
    再让后面的性格描述去补细节, 而不是反过来被泛泛描述带跑。
    """
    if not ip or not name:
        return ""
    extra = looks_from_knowledge(knowledge)
    s = (f"《{ip}》中的角色「{name}」，请采用该角色广为人知的经典形象："
         "发型、发色、瞳色、标志性服饰与配饰都照原作通行设定来画，"
         "让熟悉这部作品的人一眼认得出是谁。")
    if extra:
        s += f"外貌要点：{extra}。"
    return s
