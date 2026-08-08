"""Per-turn orchestration: glue between the player's input, the gate, and the LLM.

    detect probing → mutate run state → evaluate unlocks → assemble gated context
    → LLM → beats

The state-mutation heuristics (affinity nudge, act progression, event triggers)
are deliberately simple PLACEHOLDERS. In M3 these become model-driven (the LLM
proposes affinity deltas / flag changes as structured side-effects). The gate
(gating.py) and this pipeline's shape are the parts meant to be permanent.
"""

from __future__ import annotations

import inspect as _inspect
import random

import re
from typing import Any

from ..config import get_settings
from . import actions as actions_mod
from . import factions as factions_mod
from . import growth as growth_mod
from . import taste as taste_mod
from . import gating
from . import heat as heat_mod
from . import intent as intent_mod
from . import items as items_mod
from . import logic
from . import profile as profile_mod
from . import relationships
from . import sanity as sanity_mod
from . import scene as scene_mod
from . import threat as threat_mod
from .llm import LLM, get_llm

# Split on whitespace + CJK/ASCII punctuation into keyword phrases. Crucially this
# keeps CJK phrases intact (the old [a-z0-9]+ tokenizer dropped all Chinese, so
# probing in Chinese never registered an "ask").
_SPLIT = re.compile(r"[\s,，。、!！?？:：;；.…·\"'“”‘’()（）\[\]【】]+")

# Friendly cues nudge affinity (placeholder for M3 model-driven deltas). Bilingual.
_FRIENDLY = (
    "like", "love", "thanks", "thank", "care", "trust", "happy", "miss", "sorry",
    "谢谢", "喜欢", "相信", "信任", "别怕", "没事", "我在", "陪", "帮", "求你", "拜托",
)


def _keywords(text: str) -> list[str]:
    return [w for w in _SPLIT.split((text or "").lower()) if w]


def _contains_any(haystack: str, needles) -> bool:
    h = (haystack or "").lower()
    return any(n and n.lower() in h for n in needles)


# ── punctuation guard (user rule: 破折号能不用就不用，提示词管不住就硬管) ─────────────
_CLOSE_QUOTES = "」”』\"'"
_PUNCT_AFTER = "，。！？；：、）」”…,.!?;:)"
_PUNCT_BEFORE = "，。！？；：、（「“…,.!?;:("
_CJK_RE = re.compile(r"[一-鿿㐀-䶿]")


def has_cjk(text: str) -> bool:
    return bool(_CJK_RE.search(text or ""))


def _style_head_for_intro(style: "str | None", cap: int) -> str:
    """✍️ 开场那一拍的文风卡要保头保尾地截 (作者腔在卡头, 经济律与忌用清单在卡尾)。

    薄壳一层, 真活在 qwen.style_head; 走惰性导入跟本文件其余处一致。
    """
    try:
        from . import qwen as _q
        return _q.style_head(style, cap)
    except Exception:               # 文风截断绝不该拦住开场
        return (style or "")[:cap]


def dedash(text: str) -> str:
    """Deterministically rewrite em-dash runs in GENERATED text: a run that ends the
    line or sits right before a closing quote is a dramatic interruption and survives;
    every other one becomes a comma (or vanishes when it would double punctuation).
    Models ignore the style instruction often enough that this is enforced in code.
    Punctuation follows the text itself: Latin-only text gets ", " and a single "—",
    CJK text keeps 全角 "，" and "——"."""
    if not text or "—" not in text:
        return text
    latin = not has_cjk(text)
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch != "—":
            out.append(ch)
            i += 1
            continue
        j = i
        while j < n and text[j] == "—":
            j += 1
        nxt = text[j] if j < n else ""
        if latin:
            while out and out[-1] == " ":
                out.pop()
        prev = out[-1] if out else ""
        if j >= n or nxt in _CLOSE_QUOTES:
            out.append("—" if latin else "——")  # cut-off mid-sentence: keep the drama
        elif prev in _PUNCT_BEFORE or nxt in _PUNCT_AFTER or not prev:
            pass                                 # glued to punctuation / leading: drop
        elif latin:
            out.append("," if nxt == " " else ", ")
        else:
            out.append("，")
        i = j
    return "".join(out)


def dedash_beat(b: dict[str, Any]) -> dict[str, Any]:
    if b.get("text"):
        b["text"] = dedash(b["text"])
    return b


def default_state() -> dict[str, Any]:
    return {
        "act": 1,
        "affinity": 0,
        "flags": {},
        "choices": {},                  # answered key-moment decisions: {key: option_id}
        "searched_prop_ids": [],        # props already turned over (现场搜查, once each)
        "pressure": 0,                  # ⚠️ story pressure meter (暴露值/灵异度), 0~100
        "world_pulse": 0,               # 🌊 quiet turns since the world last moved by itself
        "turns_in_act": 0,              # pacing: turns spent in the current act
        "dead_character_ids": [],       # ☠️ killed characters: never appear again, remembered
        "identity": None,               # 🎖 the player's CURRENT 身份/职务 (None = as authored)
        "identity_log": [],             # [{act, text}] — how the identity evolved
        "inventory": [],                # 🎒 pocket: [{name, detail?, tid, qty|iid+indiv}] (items.py)
        "stashes": {},                  # {location_id: [{name,...}]} items left somewhere
        "item_templates": {},           # 🎒 物性卡快照 {tid: card} — 判定唯一读取源 (items.py)
        "item_quarantine": [],          # 🎒 未申报实体隔离区 [{name,src,day,hits}]
        "scene_items": {},              # 🎒 场景在册物 {location_id: [rows]} — 特写过的才在册
        # ⚠️ schema_version 不放这里: default 合并会把旧档也标成新纪元, 迁移永不触发
        # (items.migrate_state 自己盖章)
        "place_facts": {},              # 🌍 {location_id: [{text,label}]} lasting physical changes
        "money": None,                  # 💰 cash balance (None = economy off for this run)
        "money_log": [],                # 💰 [{delta, why, label}] the last 20 bookings
        "quests": [],                   # 📋 [{id,title,reward,deadline_day,giver,status}]
        "world_news": [],               # 🌊 [{day,text,heard}] what the world did on its own
        "past_lives": [],               # 🔄 archived lives (sandbox rebirth)
        "met_ids": [],                  # characters the player has already met (首次见面 log)
        "rel_log": {},                  # 关系大事记: {char_id: [{act, kind, text}]}
        "pending_choice": None,         # an authored decision awaiting the player's pick
        "unlocked_fragment_ids": [],
        "asks": {},
        "triggered_event_ids": [],
        "achieved_endings": [],
        "mode": "character",            # "character" | "god" (invisible observer)
        "player_character_id": None,    # which character the player embodies (character mode)
        "memory": "",                   # rolling story digest (long-horizon memory, see below)
        "stuck": 0,                     # consecutive locked-act turns w/o new clue (hint escalation)
        "memory_covered": 0,            # how many history turns are already folded into `memory`
        "location_id": None,            # the physical place the player is currently in (if authored)
        "player_emotion": "",           # last read of the player's underlying emotion (EQ continuity)
        "mature": False,                # 18+ run: engine may permit explicit adult content
        "rel": {},                      # per-character relationship toward player {cid:{closeness,romance}}
        "following": [],                # character ids currently traveling WITH the player
        "clock": {"day": 1, "slot": 0, "turns_in_slot": 0},  # ⏳ diegetic time (slot → SLOTS)
        "npc_rel": {},                  # 🕸 NPC↔NPC stances {"a|b": {stance,-2..2, label?, log:[]}}
        "promises": [],                 # 🤝 约定 [{char_id,char_name,what,day,slot,location_id?,romantic,status}]
        "phone": {"threads": {}},       # 📱 小手机: {threads: {cid: {msgs:[{from,text,at}], unread}}, mail: [...]}
        "album": [],                    # 💞 名场面收藏 [{kind,title,text,char_id,name,at,act}]
        "golden_cd": 0,                 # ✨ turns until the next 稀有奇遇 may fire (cooldown)
    }


# ── Long-horizon memory ──────────────────────────────────────────────────────
# The model is only shown the last MEMORY_WINDOW dialogue turns verbatim (qwen.py
# slices history[-8:]). In a long, player-uploaded script that window forgets act 1
# by act 5. So we keep a rolling digest: once enough turns have slid PAST the window,
# they're compressed into `state["memory"]` (injected into the system prompt as stable
# context). Net effect for long runs: recent turns in full + the whole arc in summary,
# with per-turn tokens staying roughly constant instead of growing without bound.
#
# SECURITY: the digest is built only from `history` (player inputs + spoken dialogue),
# which by construction contains only what characters have ALREADY revealed. Locked
# fragment bodies never enter history, so they never enter the digest — the gate holds.
# relationship-tier ordering, for detecting an UPGRADE (to celebrate) vs a downgrade.
_RANK = {"enemy": -1, "stranger": 0, "junior": 1, "elder": 1, "peer": 1,
         "friend": 2, "flirt": 3, "lover": 4}

# 🧠 逐字窗口 = 多少个【玩家回合】原样进提示词 (Yi 2026-08-06:「要存更多的聊天记录」)。
# 14 太小: 生产 177 局里 24 局 (13%) 会被它切掉东西。抬到 24 之后只剩 ~8 局。
# 敢抬是因为【窗口是上限不是下限】—— 玩家发言数中位只有 2, 短局拿到的东西
# 一个字不变, 这一刀对 87% 的局零成本; 延迟只由超窗的那 13% 承担, 而那批
# 恰恰是玩得最投入的人。真正的切分逻辑在 qwen.history_window (那边是唯一实现)。
MEMORY_WINDOW = 24
MEMORY_BATCH = 6    # summarize only once this many turns have slid out of the window

# Stuck-hint escalation: consecutive locked-act turns with no new required clue. NUDGE =
# NPCs get noticeably more forthcoming; PUSH = a direct narrator hint pointing at one topic;
# SPELL = the narrator lays out the full remaining checklist + a concrete next step.
STUCK_NUDGE = 1
STUCK_PUSH = 2
STUCK_SPELL = 4

# Every pacing/balance knob, overridable PER STORY via story.tuning (a horror script and a
# romance script want different rhythms). Values here are the engine defaults — the module
# constants above stay the single source for them. See docs/tuning.md for the knob table.
DEFAULT_TUNING = {
    "peek_drop_chance": 18,     # 📱🔍 TA离场时遗落设备的概率% (0=关闭偷看玩法)
    # 💘 心动过此线角色开始主动追玩家 (0=关闭)。4 = 玩家明确撩过一次 (「心动」事件 +4)。
    # 曾经是 15 —— 而生产 162 局实测心动天花板只有 6~8 (只「心动」「和好」两种事件产
    # romance, 且心动带 8 回合冷却), 那条线【物理上到不了】, 追求系统等于焊死。
    # Yi 2026-08-04 定: 玩家没那么多时间堆好感, 直接把最好的陪伴给他; 稀缺性靠【单追求者锁】
    # 守 (同时只有一位), 不靠让玩家熬。
    "pursue_threshold": 4,
    # 💘 两拍主动之间至少隔几个回合 (与「一游戏日一拍」谁先到算谁)。
    # 只按游戏日排的话, real_clock 默认开 = 一个现实日一拍 = 六阶要走六个现实日,
    # 而中位一局只有 4 拍 —— 玩家的时间货币是【一次长坐】不是【一个现实日】。慢热本调大。
    "pursue_gap_turns": 4,
    "affinity_clamp_min": -3,   # per-turn floor on summed 好感 delta
    "affinity_clamp_max": 8,    # per-turn ceiling on summed 好感 delta
    "act_backstop_div": 12,     # soft acts: act floor = 1 + affinity // this
    "stuck_nudge": STUCK_NUDGE,
    "stuck_push": STUCK_PUSH,
    "stuck_spell": STUCK_SPELL,
    # relationship thresholds (see engine/relationships.py)
    "friend_t": 40, "enemy_t": -15, "flirt_t": 25, "lover_t": 60, "lover_close_min": 35,
    "follow_min_closeness": 0,   # 🚶 邀人同行: 0 = 一开始就能邀, 只有敌对拒绝
    # 📇 联系方式 (Yi 2026-08-04: 陪伴链的第一环不该是道熬出来的门)
    "contact_on_meet": 1,        # 照面即入通讯录 (0 = 关, 悬疑/恐怖本要的封闭感)
    "contact_ask_t": 0,          # 开口要号需要的交情 (0 = 一律肯给)
    "close_step_min": -6, "close_step_max": 8, "rom_step_min": -4, "rom_step_max": 6,
    # hours away after which the next turn counts as a RETURN (角色接起上次的话头)
    "return_gap_hours": 6,
    "dice": 1,                  # 🎲 risky 做-actions get a visible fate roll (0 = off)
    # pacing brakes (推进太快 fix): gains taper as scores climb; a soft act needs real time
    "affinity_taper_den": 100,  # positive 好感 gain scales by (1 - affinity/this), floor 0.3
    "close_taper_den": 130,     # per-char 亲近 gain taper denominator (relationships.py)
    "rom_taper_den": 110,       # per-char 心动 gain taper denominator
    "min_turns_per_act": 6,     # soft acts: no advance (model OR backstop) before this many turns
    "max_new_characters": 4,    # 👋 emergent mid-story characters a run may accumulate
    "callback_every": 10,       # 🪃 记忆回调周期 (Spec E; 暧昧节拍下加急到 3)
    "pushpull_give": 3,         # 🔥 推拉: 给糖连续轮数 (Spec F)
    "pushpull_hold": 1,         # 🔥 推拉: 收着连续轮数
    "initiate_cooldown": 1,     # 🎰 主动发起: 单角色冷却天数 (Spec H)
    # 🌱 growth_every: 生长预算周期 (回合)。缺省: 沙盒 8, 授权本 0 (关) — 见 growth.period_of;
    # 这里不给键, 让「作者显式设置」与「缺省」可区分
    "key_choice_min": 0,        # ⚖️ 命运抉择 window: fires at a RANDOM turn count in
    "key_choice_max": 12,       #    [min, max] (min 0 = off; Yi 2026-07-21 定: 默认关, 剧本级可开)
    "fate_auto_resolve": 0,     # ⚖️ 宽限耗尽引擎替玩家落子 (0 = off; Yi 2026-07-14 定:
                                #    无点击不推进 — 玩家没点的选择不许系统代点, 剧本级可开)
    "world_event_every": 0,     # 🌊 after this many quiet turns an authored act event fires
                                #    itself (0 = off; Yi 2026-07-14 定: 默认不自燃, 剧本级可开)
    "turns_per_slot": 6,        # ⏳ turns per 时段 (晨/午/夜); a day = 3 slots. 0 = clock off
    "troupe": 1,                # 🎬 剧组 (导演场次单+编剧扩展): 2026-07-26 升格全舰默认 (Yi 情商军令①:
                                #    戏眼/每人心事进场 = 情商的原材料; 后台线程零首字代价, 剧本可关)
    "confront_base": 55,        # 🃏 evidence-confrontation base success %, + closeness//2
    "confront_cost": 3,         # 🃏 closeness cost of a successful confrontation (fail ×2, 大失败 ×3)
    "mind_reader": 1,           # 📟 心象仪: characters' true inner state shown on bubbles (0 = off)
    "scene_ledger": 0,          # 🎬 场账本 (docs/scene-ledger.md, 2026-08-01 中切): 作息离场须走戏
                                #    /时钟场内缓拨/已演已问入账。0 = off, 剧本级开 (狗笼试点)
    "promise_keep_bonus": 6,    # 🤝 closeness for showing up to a promise (romantic: 心动 too)
    "promise_break_cost": 4,    # 🤝 closeness lost for standing someone up
    # ✨ 稀有奇遇的【自动摇骰】。Yi 2026-08-04 关掉: 每回合白摇一次, 而喂给模型的
    # 上下文只有本回合最后四句 —— 写出来的东西没读懂最近的戏, 又贵又空。改成玩家
    # 自己挑时机点 (POST /runs/{id}/golden → golden_moment_now), 那一次喂足几十拍。
    # 留着这个键是为了可逆 (剧本级设 >0 就恢复自动摇), 不是为了用。
    "golden_chance": 0,         # ✨ 稀有奇遇: % chance per eligible turn (0 = off)
    "golden_cooldown": 10,      # ✨ turns between two golden moments, minimum
    "snap_chance": 12,          # 📷 随手拍: % chance a character's text carries a photo (0 = off)
    "vn_mode": 0,               # 🎀 galgame 演出: VN window + choice-driven turns (授权本用)
    "letter_away_hours": 48,    # 📮 away at least this long → the warmest heart writes a LETTER
    "opening_player_first": 0,  # 🎤 开场由玩家先发言: 开场只亮相不开口, 第一句对话必须来自
                                #    玩家; 观剧拍同样不许抢 (0 = off; 剧本级可开, studio 开场白卡)
    "real_clock": 1,            # ⏰ 现实对齐 (Yi 2026-07-26 升格全舰默认): 故事时间=真实
                                #    时间, 角色与你同一条时间线 (0 = 退回虚构时钟, 剧本级可关)
    "rel_events": 1,            # 💞 好感事件记账制 (Yi 2026-07-25 定: 不许每句话打分, 关系由
                                #    事写成): 模型只申报关系事件+文据, 分值/冷却引擎说了算
                                #    (1 = on; 剧本级可关回旧每句判)
    "physics_guard": 1,         # 🧊 物理连续性哨兵 (Yi 2026-07-27: 治道具/伤势穿模——裤兜掏
                                #    瓶装汽水、断肋骨扛货): 仅当这拍有动作/道具/伤势字眼才用 flash
                                #    快审, 探到硬物理矛盾→当场重生一次。纯聊天回合跳过=零延迟。1=on
    "fallible": 1,              # 🎭 会露怯 (Yi 2026-07-26: 治「角色永远占上风=下头」): 宪章常驻
                                #    反完美话术锚 + 引擎每 4 拍给主答者一记 off_balance 放大 (处下风/
                                #    被将住/语塞/让玩家赢一手)。1=on; 需要角色始终碾压的本可关
    "pursue_player": 0,         # 💘 全员追玩家 (Yi 2026-07-26 定: 所有角色主动追你, 反向后宫):
                                #    行为层, 不碰 voice_print — 各角色【透过自己人设】吊系地追
                                #    (冷的人冷着追/傲的人嘴硬身诚实), 欲擒故纵不倒贴。默认 0,
                                #    剧本级开 (恋爱本开, 恐怖/战争本别开; 观剧/成员拍不注入)
}

# 💞 关系事件分类表 (事件记账制的引擎法条, 故事无关):
# kind: (亲近Δ, 心动Δ, 正面冷却回合, 是否要求角色可恋)。负面事件零冷却 — 伤害不限流;
# 正面事件带冷却 — 同一角色同类事件冷却内再申报按刷分驳回。日常寒暄不是事件。
# 五元组: (亲近Δ, 心动Δ, 冷却, 恋爱门, 信任Δ) — 🛡 信任轴 (合伙人 2026-08-02):
# 交心/帮衬/和好也在攒可靠感; 冒犯/越界同时在塌信任 (慢建快塌在 apply_deltas 管)
_REL_EVENTS = {
    "交心": (4, 0, 8, False, 3),    # 说出真心话/交换了真实的自己
    "帮衬": (5, 0, 6, False, 2),    # 实质帮TA办成/扛下了一件事
    "心动": (2, 4, 8, True, 0),     # TA被这一拍真正打动
    "和好": (3, 1, 10, False, 2),   # 冲突后的修复
    "冒犯": (-5, 0, 0, False, -2),  # 踩雷/羞辱/背弃
    "争执": (-3, 0, 0, False, -1),  # 正面冲突撕破脸
    "越界": (0, -3, 0, True, -3),   # 油腻/廉价/冒进
}

MAX_OPEN_PROMISES = 3  # 🤝 open appointments a run may hold at once (per char: one)

# ⏳ the diegetic clock: three slots make a day. Slot-restricted schedule entries and
# story deadlines (story.clock) hang off this. Story-agnostic — the names are the frame,
# not any script's content.
SLOTS = ("晨", "午", "夜")
_SLOT_EN = {"晨": "Morning", "午": "Noon", "夜": "Night"}  # display names for en stories
AWAY = "__away__"  # a scheduled character whose no entry covers this hour: off somewhere, unreachable

# 🗺 谁在哪, 模型说了算 (Yi 2026-08-08:「模型决定」)。2026-08-04 关, 08-08 开回来。
#
# 【为什么当初关】引擎原本有八条「模型/对话 → 地图」的写路径, 闸还不统一, 任何剧本都
# 会被 LLM 加地点、挪位置。Yi 的裁定是全部取消, 换场只认玩家自己点。
#
# 【为什么开回来】两场实弹, 拿线上真实存档 + 线上模型跑的:
#   实验一 有回执 vs 无回执, 各 5 轮 —— 【一样】2/5 把人写到了别处。
#   实验二 只剪掉一条通路, 回执明说「从此地去不了那里」—— A 3/5 到达、B 3/5 到达,
#          而且五次【一次都没提过】去不了。
# 第二场是关键: 那个剧本里两个地点走三分钟就到, 角色的开场台词就是相邀去那儿,
# 是我人为剪了那条边。【模型是对的, 地图是错的】。
#
# 作者写的 exits 只是对相邻关系的一次猜测, 而故事知道得更准。引擎拿一张不完整的
# 邻接表去否决故事, 输的永远是引擎 —— 模型照样把人写过去, 只是账本不跟, 于是文与实
# 分家。所以引擎的活从【否决】改成【跟上】。
#
# 【没有一起交出去的两样】
#   · 铸造新地点 —— 归 LLM_MINTS_PLACES, 那条有造出「个地方」这种垃圾地名的前科
#   · 解锁闸 (location_available) —— 哪一幕能去哪, 是作者的剧作结构, 不是地理
#
# 玩家自己驱动的那条路照常: 地图面板点节点 (apply_move)、作者作息表、猎手押送。
# 守卫: tests/test_model_decides_place.py
LLM_MAP_WRITES = True

# 🏗 但【有哪些地方】还不归模型 (Yi 2026-08-08 只交出了「谁在哪」)。
#
# 从前这两件事共用一把锁。它们其实是两个问题: 「他们走到码头了」是叙事事实, 模型最清楚;
# 「这个世界有没有一个叫 X 的地方」是世界设定, 而模型在这上面有前科 —— 2026-07-22 实弹
# 把「换个地方聊」铸成了一个叫「个地方」的地点并上了地图。
#
# 铸造那条路上有判官 (generate_and_move 的 describe_place + _bad_place_name 预筛),
# 但判官的效果还没有像这次移动这样被实弹验过。等有数据再谈。
LLM_MINTS_PLACES = False

# 🗺 地图是独立于 LLM 的功能 (Yi 2026-08-04 第二刀): 换场只走地图面板 —— 玩家点节点,
# 客户端发 POST /runs/{id}/move。输入框里写「我去码头」不再算数。
#
# 为什么它跟 LLM_MAP_WRITES 分开: 打字移动是正则嗅探, 根本不经模型 —— 但它同样让
# 「说一句话」等于「改了位置」, 正是 Yi 要拆开的那层耦合。两把锁管两件事:
#   LLM_MAP_WRITES —— 模型/旁白不许改地图
#   TYPED_MOVE     —— 散文里的移动意图不许改地图
# 都关上之后, 地图这个功能只剩两个输入: 作者写的地点/作息, 和玩家在图上点的那一下。
TYPED_MOVE = False

# 🎟 邀约确认条: 2026-08-06 关, 2026-08-08 开回来 (两次都是 Yi 拍的, 原委都记在这)。
#
# 【为什么当初关】前两把锁关掉之后, 从文字里长出来的移动只剩这一条还活着, Yi 的裁定
# 是「不通过文字控制！」—— 移动只剩点界面, 角色照样能嘴上邀你, 但要走得自己点地图。
#
# 【为什么开回来】线上实弹: 角色开口邀玩家去某处, 玩家开口答应, 而系统【没有任何办法
# 兑现】。那一拍当天新上的三道东西全部正常工作 (意图认出来了、toast 弹了、压模型的
# 规则也下了), 模型照样把两个人写去了别处, location_id 一动没动。
#
# 根因不是提示词不够狠, 是【把出口堵死了只留一条禁令】: 模型手上有戏要演, 就翻墙。
# 这类洞补不完 —— 只要角色还能开口邀约, 每一次玩家答应都在重开这个坑。
#
# 【开回来的是什么】一个玩家必须【亲手点】的按钮, 所以「移动只剩点界面」这条没破:
#   角色申报 move_invite → 引擎验目的地在册/已解锁/走得到 → 弹「跟 TA 去 / 留下」
#   → 玩家点了才真的走。玩家不点, 位置一动不动。
# 另外两把锁一动没动: 散文不许改地图 (LLM_MAP_WRITES), 打字不许改地图 (TYPED_MOVE)。
# 铸地那半边也照旧堵着 (generate_and_move 在锁下返回 None), 所以确认条只可能指向
# 作者写好的地点 —— 模型不能靠邀约凭空长出一个新场景。
#
# ⚠️ 一起回来的还有「打听到人在哪 → 去找 TA」那张条 (同一口闸, 见 seek 那一段)。
# 守卫: tests/test_invite_move_back.py (下半截专门守另外两把锁没被顺手松掉)。
INVITE_MOVE = True

# 🔎 找人不再自动造真 (Yi 2026-08-05)。
#
# 原来: 玩家提到册子上没有的名字 → 引擎额外调一次 scout_char 判官问「这名字属不属于
# 本世界观」→ 判官点头就【当场造真】(角色入册 + 铸地 + 钉行踪), 整个回合短路成一张
# 「TA此刻在 X，去吗？」的确认片。
#
# 问题在判断权: 那个判官只看到名字和世界观梗概, 看不见这一场的戏、看不见玩家为什么
# 提这个名字 —— 玩家随口一句就凭空多出一个人。而导演本来就握着 new_character 字段,
# 它读得到整场上下文, 才是该拍板的那个。
#
# 关掉之后: 名字原样递给导演 (prompt.seek_unknown), 由它判断该不该有这号人 ——
# 该有就 new_character 让 TA 真登场, 不该有就在世界观内如实否认并指条路。
# 顺带省掉那一次判官调用。
SEEK_AUTO_MINT = False

_SLOT_NARR = {
    "晨": "（长夜过去，第{day}天的晨光透了进来，街面上有了新的动静。）",
    "午": "（不知不觉，日头已经爬到头顶。）",
    "夜": "（天色沉了下来，夜幕罩住了这一带。）",
}
_SLOT_NARR_EN = {
    "晨": "(The long night passes. The morning light of day {day} seeps in, and the streets stir awake.)",
    "午": "(Before you know it, the sun has climbed overhead.)",
    "夜": "(The light fades. Night settles over this place.)",
}


def _slot_narr(content: dict[str, Any], slot: str, day) -> str:
    table = _SLOT_NARR_EN if lang_of(content) == "en" else _SLOT_NARR
    return table[slot].format(day=day)


def art_style_of(content: dict[str, Any]) -> str:
    """🎨 每剧本自带画风 (story.tuning.art_style, free text — tuning_for only carries
    numeric knobs): appended to EVERY image prompt this story mints (scene bg /
    portrait / 随手拍), so a horror world looks like one and a campus romance doesn't.
    Same doctrine as the prose style field: tone lives in the 剧本, not the engine."""
    return str(((content.get("story") or {}).get("tuning") or {})
               .get("art_style") or "").strip()[:200]


def tuning_for(content: dict[str, Any]) -> dict[str, int]:
    """The effective knob set for this story: engine defaults overlaid with the story's
    authored `tuning` overrides (unknown keys and non-numeric values are ignored)."""
    t = dict(DEFAULT_TUNING)
    for k, v in ((content.get("story") or {}).get("tuning") or {}).items():
        if k in t:
            try:
                t[k] = int(v)
            except (TypeError, ValueError):
                pass
    return t


# ── 🌐 story language ────────────────────────────────────────────────────────────
# A story authors its performance language (story.language: "zh" | "en"). One wrapper
# stamps it onto EVERY prompt the engine sends (so qwen.py can direct the model's
# output language), and _t() picks the localized variant of the engine's own
# deterministic narration. zh stays byte-identical to before.
def lang_of(content: dict[str, Any]) -> str:
    return ((content.get("story") or {}).get("language") or "zh").strip() or "zh"


class _LangLLM:
    """Stamps {"language": lang} onto every prompt dict on its way to the real LLM."""

    def __init__(self, inner: LLM, lang: str):
        self._inner, self._lang = inner, lang

    def generate(self, prompt: dict[str, Any]) -> dict[str, Any]:
        if isinstance(prompt, dict) and "language" not in prompt:
            prompt = {**prompt, "language": self._lang}
        return self._inner.generate(prompt)

    def plan_and_render(self, prompt: dict[str, Any], settle=None):
        if not hasattr(self._inner, "plan_and_render"):
            yield ("final", self.generate(prompt))
            return
        if isinstance(prompt, dict) and "language" not in prompt:
            prompt = {**prompt, "language": self._lang}
        yield from plan_render_call(self._inner, prompt, settle)

    def narrate_stream(self, prompt: dict[str, Any]):
        if not hasattr(self._inner, "narrate_stream"):
            yield ("final", self.generate(prompt))
            return
        if isinstance(prompt, dict) and "language" not in prompt:
            prompt = {**prompt, "language": self._lang}
        yield from self._inner.narrate_stream(prompt)


def lang_llm(llm: LLM, content: dict[str, Any]) -> LLM:
    lang = lang_of(content)
    if lang == "zh" or isinstance(llm, _LangLLM):
        return llm
    return _LangLLM(llm, lang)


def plan_render_on(content: dict[str, Any]) -> bool:
    """plan/render 双拍合同 (docs/plan-render.md): engine default from settings, story
    tuning overrides either way (the single-story pilot switch). zh only for now — the
    render beat's speech splitter is 「」-shaped."""
    t = (content.get("story") or {}).get("tuning") or {}
    on = bool(t["plan_render"]) if isinstance(t, dict) and "plan_render" in t \
        else bool(get_settings().plan_render)
    return on and lang_of(content) == "zh"


def _t(content: dict[str, Any], zh: str, en: str) -> str:
    """The engine's own narration in the story's language (deterministic beats)."""
    return en if lang_of(content) == "en" else zh


# 🗣 叙述者记号。必须跟 qwen._LineSegmenter 认的那个一致 —— 历史里的示范长什么样,
# 模型就照着写什么样。见 history_for 里的原委 (2026-08-07 的「不能发言」就是它)。
NARRATOR_TAG = "旁白："


# 🚶 玩家【自己说要走】的说法 (Yi 2026-08-08 拍板 A)。三把锁之后换场只剩点地图,
# 所以这一句必须被认出来 —— 否则玩家说了、引擎没反应、模型只好用文字兑现,
# 那正是「旁白把人写去别处而位置没动」的形状。
# 只认【离开此地】: 场内走动 (「我走到窗边」) 不算 —— 误报比漏报更坏, 每句话都弹
# 「点地图」等于把玩家赶走。所以「走」单独出现不算, 要么带人, 要么带地名。
_WANT_MOVE = re.compile(
    r"跟(着)?(他|她|你|TA|你们|他们)(一起)?(走|去|回)"
    r"|(和|跟)(他|她|你|TA)(一起)?(去|走)"
    r"|一起(去|走)"
    r"|带我(去|走)"
    r"|我(也)?(跟|随)(你|他|她|TA)"
    r"|(我们|咱们)(去|回)[^。！？，、]{1,10}"
    # 第一人称单数「我去天台」。要带个真去处 (≥2 字), 「我去看看」「我去死」进不来;
    # 前面有「不」「别」「想」的一律不算 (「我不想去」)。
    r"|(?<![不别想])我(去|回)(?!看看|试试|问问|找)[^。！？，、]{2,8}$"
    # 无主语的「去庙街看看」「回警署吧」: 句首起、带个去处收尾;
    # 前面有「不」「别」的进不来 (「我不想去」)。
    r"|^(?<!不)(?<!别)(去|回)[^。！？，、]{2,8}(吧|看看|一趟|一下|$)")


def player_wants_to_move(text: str | None, channel: str = "say") -> bool:
    """🚶 玩家这一拍是不是【亲口说了要离开此地】。

    Yi 2026-08-08 拍板 A: 引擎明说「想去哪点地图」, 把摩擦摆到明处 —— 宁可生硬,
    不许撒谎。从前玩家打「跟他走」时系统无路可走 (三把锁把换场收成只剩点地图),
    模型只好用文字兑现, 于是正文一路走到别处而 location_id 一动没动。
    """
    t = (text or "").strip()
    if not t:
        return False
    from . import growth as _g
    return bool(_WANT_MOVE.search(t) or _g.explore_intent(t))


def map_move_hint() -> dict[str, Any]:
    """🗺 给玩家的那条提示。走 moments→toast 那条管道, 【不进正文】——
    引擎硬写的旁白不过文风, 而且会进历史污染示范 (2026-08-07 的教训)。"""
    return {"kind": "map_move", "text": "想去别处？点右上角的地图选地点"}


# 🚶 把人写去别处的动词。要有【动作】才算 —— 嘴上提一句别处不算。
_PROSE_GO = re.compile(
    r"(走[出进向到过]|来到|去了|穿过|拐[进过]|迈[进出]|踏[进入]|抵达|带[你我]|领着|牵着[你我]|"
    r"推开.{0,12}(门|帘)|进了|下了车|上了车)")


def prose_moved_elsewhere(content: dict[str, Any], state: dict[str, Any],
                          texts: list[str] | None) -> list[str]:
    """🔭 这一拍的正文有没有【把人写去了别的在册地点】(而位置其实没动)。

    Yi 报障 2026-08-08:「在1场景旁白文字会移动到别的地方，但是玩家和 AI 角色一直在1场景」。
    生产实测 8 例, 最典型的一例连着三拍把人从巷口 → 龙津道 → 街角 → 糖水店一路写过去,
    location_id 一动没动。

    根因不是提示词缺规则 —— 规则在, 而且写得很明白 (「这一拍的戏必须仍然发生在此地」)。
    根因是【玩家亲口说了要走, 而引擎没有办法兑现】: 2026-08-06 三把锁把移动收成只剩
    点地图之后, 玩家打「跟他走」时系统无路可走, 模型只好用文字兑现。那一例的上一拍
    正是「（反手扣紧他的手，跟他走）好啊」。

    这里只做【计数】不做拦截: 事后重打的代价在逐拍流式下太大 (守卫一响就是玩家眼前的
    字被撕掉)。先有数, 才谈得上「改了有没有用」—— 今天两次都是没有数, 只能等玩家来骂。
    场内走动 (「走到训练场角落的木桩前」) 不算, 否则这个读口全是噪音, 就没人看了。
    """
    here = state.get("location_id")
    hit: list[str] = []
    for loc in ((content.get("story") or {}).get("locations") or []):
        nm = (loc.get("name") or "").strip()
        if not nm or len(nm) < 2 or loc.get("id") == here:
            continue          # 一个字的地名 (「巷」「街」) 到处误命中
        for t in (texts or []):
            if nm in (t or "") and _PROSE_GO.search(t or "") and nm not in hit:
                hit.append(nm)
    return hit


def _loc_aliases(name: str) -> set[str]:
    """一个在册地点在正文/姿位里可能被写成的短名。

    剧本爱把地点注册成复合名 (「甲·乙」「甲与乙」), 而模型只写其中一截 —— 只认全名的
    读口对真实文字是瞎的。一个字的地名不要 (「巷」「街」到处误命中)。
    """
    out = {name}
    for part in re.split(r"[·・\-—/／、,，(（]|与|和", name or ""):
        part = part.strip()
        if len(part) >= 2:
            out.add(part)
    return {a for a in out if len(a) >= 2}


def position_names_elsewhere(content: dict[str, Any], state: dict[str, Any],
                             text: str | None) -> str:
    """🧍 这条姿位文本有没有点到【别的在册地点】。命中就返回那个地点的全名。

    线上实弹 2026-08-08: 审计单上并排躺着「你:跟在她身后往X走」和「at=此地」——
    一条记录里文说在往 X 走, 实说人在此地。姿位会回喂给下一拍当锚, 收下一条假的
    等于让这次幻觉自己给自己续命, 位置永远追不上。

    ⚠️ 别名撞车就不算数: 同一个剧本里「甲·前厅」「甲·后院」都会缩成「甲」, 拿它去
    判谁都不对。线上扫过一遍, 误报几乎全是这个形状 —— 所以只认【全剧本唯一】的别名,
    而且此地自己占着的别名一律让开。
    """
    text = str(text or "").strip()
    if not text:
        return ""
    here = state.get("location_id")
    locs = (content.get("story") or {}).get("locations") or []
    owners: dict[str, set] = {}
    for loc in locs:
        for a in _loc_aliases((loc.get("name") or "").strip()):
            owners.setdefault(a, set()).add(loc.get("id"))
    mine = {a for a, ids in owners.items() if here in ids}
    for loc in locs:
        if loc.get("id") == here:
            continue
        nm = (loc.get("name") or "").strip()
        for a in sorted(_loc_aliases(nm), key=len, reverse=True):
            if a in mine or len(owners.get(a) or ()) != 1:
                continue          # 此地也叫这个 / 好几个地点都叫这个 → 判不了
            if a in text:
                return nm
    return ""


INVITE_TTL = 2          # 邀约挂几拍作废 (隔太久的「走吧」多半说的不是那件事)

# 🙅 明确回绝。挂着不销账, 玩家下一句随口一个「走吧」就被搬走了。
_DECLINE = re.compile(r"^(不去|不了|算了|不用了)|不想去|不去了|下次吧|改天吧|待会|等一下再|先不")


def note_invite(state: dict[str, Any], chip: dict[str, Any] | None) -> None:
    """🤝 记下这一拍角色发出的邀约, 等玩家下一句答不答应。

    只留一张 —— 两张没兑现的邀请同时挂着, 玩家一句「好啊」谁也说不清答的是哪个。
    """
    if not chip or not chip.get("to"):
        return
    state["pending_invite"] = {"to": chip["to"], "to_name": chip.get("to_name"),
                              "by_name": chip.get("by_name"),
                              "at": int(state.get("turn_seq") or 0)}


def take_invite(content: dict[str, Any], state: dict[str, Any],
                player_input: str | None, channel: str = "say") -> dict[str, Any] | None:
    """🤝 两步握手 = 真移动 (Yi 2026-08-08, P0 实验的负结果逼出来的)。

    上一拍角色邀约了一个在册可达的地方, 这一拍玩家答应 ⇒ 现在就走过去, 然后让这一拍
    的戏【放心到达】。

    【为什么改成这样】原本的做法是弹确认条, 并告诉模型「只演到起身相邀为止, 别写已经
    到了」。拿真实存档跑了 5 轮 A/B: 有回执和没回执【一样】2/5 把人写到了别处。
    复盘结论是那条指令本身违反戏理 —— 角色刚说完「要不要跟我去」, 玩家刚答「好」,
    这时候不许到达是引擎在跟故事较劲, 而拦住的理由只是想让玩家再点一次按钮。
    可玩家已经用嘴同意过了, 而且【角色提议 + 玩家答应】比点一下图标的同意更强。

    三把锁的边界没破: 目的地仍由引擎验、仍只能是作者写好的地点、模型仍然搬不动人。
    变的只是【玩家的同意可以用说的, 不是只能用点的】。

    ⚠️ 兑现时必须【再验一次】可达性 —— 记下来之后地图可能变了 (通路上锁/地点没解锁)。
    ⚠️ 无论走没走成, 只要玩家表了态就销账: 拒绝之后还挂着, 下一句随口的「走吧」会
       把人搬到一个他早就说过不去的地方。
    """
    pend = state.get("pending_invite")
    if not isinstance(pend, dict) or not pend.get("to"):
        return None
    if (state.get("mode") or "character") == "god":
        return None            # 上帝视角没有脚
    if int(state.get("turn_seq") or 0) - int(pend.get("at") or 0) > INVITE_TTL:
        state.pop("pending_invite", None)
        return None
    text = str(player_input or "")
    if _DECLINE.search(text):
        state.pop("pending_invite", None)
        _audit(state, "invite.decline", True, pend.get("to_name") or "")
        return None
    if not player_wants_to_move(text, channel):
        return None
    state.pop("pending_invite", None)   # 表了态就销账, 走没走成都不再挂着
    dest = _location_by_id(content, pend["to"])
    if not dest or not location_available(content, state, dest):
        _audit(state, "invite.take", False, pend.get("to_name") or "", "此刻已不可达")
        return None
    cur = location_view(content, state) or {}
    _ex = cur.get("exits") or []
    if _ex and dest.get("name") not in _ex and dest.get("id") not in _ex:
        _audit(state, "invite.take", False, dest.get("name") or "", "此地走不到")
        return None
    try:
        apply_move(content, state, dest["id"])
    except ValueError as e:
        _audit(state, "invite.take", False, dest.get("name") or "", str(e)[:20])
        return None
    _audit(state, "invite.take", True, dest.get("name") or "",
           f"{pend.get('by_name') or '对方'}相邀，玩家答应")
    return dest


def plan_render_call(llm: Any, prompt: dict[str, Any], settle=None):
    """🧾 双拍调用的唯一入口 (整改 P0)。老签名的后端照旧能跑。

    ⚠️ 这里【不许】用 `try: inner(prompt, settle=...) except TypeError: inner(prompt)` ——
    生成器体内部任何一个 TypeError 都会被误判成「签名不对」而整拍重跑一遍: 两次计费、
    两份散文、两套裁决。签名要在调用【之前】问清楚, 不能拿异常当判据。
    """
    fn = getattr(llm, "plan_and_render", None)
    if fn is None:
        yield ("final", llm.generate(prompt))
        return
    try:
        takes = "settle" in _inspect.signature(fn).parameters
    except (TypeError, ValueError):
        takes = False
    yield from (fn(prompt, settle=settle) if takes else fn(prompt))


def plan_receipt(content: dict[str, Any], state: dict[str, Any],
                 plan: dict[str, Any] | None, player_name: str = "") -> str:
    """🧾 计划拍与渲染拍之间的【回执】: 引擎先判, 再把结果告诉模型, 模型照结果写。

    双拍是两次独立调用, 中间那道缝一直空着 —— 模型在计划拍申报了动作, 引擎却要等散文
    流完才结算, 于是驳回永远来得太晚, 字已经在玩家眼前了。这个函数站在那道缝里。

    【P0 只接一条路】只处理带路申报, 其余申报字段一个不碰 —— 先验假设, 再谈铺开。

    【驳回必须带出路】只写禁令就退化成又一条「绝不许」, 那正是要拆掉的东西。
    模型手上有戏要演, 你不给它路它就自己找路 —— 线上已经验过一次了。

    🔒 两条硬约束, 都有测试守着:
      · 零模型调用 —— 这一步在首字之前, 混进一次调用 TTFT 当场崩
      · 不动状态 —— 真正落账在结算级联里, 这里改就是双重记账
    """
    where = str(((plan or {}).get("move_invite") or "")).strip()
    if not where:
        return ""
    you = player_name or "玩家"
    chip = invite_chip(content, state, where, "_probe", None) if INVITE_MOVE else None
    if chip:
        return (f"【系统回执】你申报要带{you}去「{chip.get('to_name') or where}」，这条路走得通。"
                f"系统会当场问{you}去不去，{you}点头才真的过去。"
                f"所以这一拍只演到你起身、相邀、把话说出口为止——"
                f"别替{you}答应，也别写{you}已经动身或已经到了那里。")
    return (f"【系统回执】你申报要带{you}去「{where}」，但从此地【去不了】那里"
            f"（没有通路，或者那地方还不在这张地图上）。别把它说成马上就能到。"
            f"你可以：改约下次、指条路让{you}自己去、或者换一个此地走得到的地方相邀。"
            f"这一拍的戏仍然发生在此地。")


def book_position(content: dict[str, Any], state: dict[str, Any],
                  char_id: str | None, text: str | None) -> bool:
    """🧍 姿位入账的唯一口子 (char_id 为空 = 玩家自己)。拦下来的那次要留痕 ——
    不留痕就永远量不出「文与实长在同一行上打架」发生过多少回。"""
    text = str(text or "").strip()
    if not text:
        return False
    bad = position_names_elsewhere(content, state, text)
    if bad:
        _audit(state, "pos.refuse", False, text[:16], f"点了别处：{bad}")
        try:
            from .. import metrics as _pm
            _pm.log("pos", ev="refuse", to=bad)
        except Exception:
            pass
        return False
    rec = {"text": text, "at": state.get("location_id")}
    if char_id:
        _sim(state, char_id)["pos"] = rec
    else:
        state["player_pos"] = rec
    return True


def speechless_turn(beats: list[dict[str, Any]] | None, channel: str = "say",
                    present: bool = True) -> bool:
    """🔭 这一拍【被直接搭话却一句台词都没有】吗。

    2026-08-07 的报障就是这个形状: 模型内容对、但行首前缀没了, 台词整坨落进旁白,
    角色看起来彻底哑了。当时没有任何读口能看出来, 只能等玩家来骂 —— 而这次就是
    等来的。所以补一个能数的口子, 别让同类问题再无声烂掉。

    三个前提, 缺一就不算哑:
      · 只在【玩家开口说话】那一路算数 —— 玩家做动作 (do) 时角色不吭声是合法的
      · 场上得【有人】—— 这一条是这道闸自己上线当天就抓到的误报: 无界之地与
        后宫物语开场一个人都不在场, 引擎正确地退回「你环顾四周」, 不是哑巴
      · 玩家自己那条 dialogue、以及没有说话人的 dialogue (解析失败的产物) 都不算开口
    """
    if channel != "say" or not present:
        return False
    for b in beats or []:
        if b.get("type") == "dialogue" and b.get("author") != "player" \
                and str(b.get("speaker_name") or "").strip():
            return False
    return True


def history_for(beat_log: list[dict[str, Any]] | None, char_id: str | None,
                tag_narration: bool = False) -> list[dict[str, str]]:
    """A character's PERSONAL view of the conversation: only the beats they witnessed (were
    present for). Legacy beats (present_ids None) are witnessed by everyone. This is what
    stops info silently leaking between characters/scenes — each one only recalls what it saw."""
    out: list[dict[str, str]] = []
    for b in beat_log or []:
        pres = b.get("present_ids")
        if not (pres is None or (char_id and char_id in pres)):
            continue
        if b.get("author") == "player":
            out.append({"role": "user", "content": b.get("text", "")})
        elif b.get("type") == "dialogue":
            # prefix the speaker so a character can tell who said what in a group scene
            sp = b.get("speaker_name")
            out.append({"role": "assistant", "content": (f"{sp}：" if sp else "") + b.get("text", "")})
        elif b.get("type") == "description" and (b.get("text") or "").strip():
            # 🎬 旁白也进记忆 (2026-08-04)。此前这一类整个丢弃, 而生产实测
            # 252717/327791 = 77.1% 的正文是旁白 —— 玩家读到的四分之三内容在回合
            # 结束的一刻就永久蒸发: 玩家记得你们一起淋了那场雨, 角色只记得当时说的
            # 三句台词。这是「记不住」的头号根因, 而且补这一处等于修两层
            # (逐字近史窗与滚动摘要共用这个入口)。
            # 认知边界照旧走上面的 present_ids 闸 —— 我不在场的那场雨我不该记得。
            #
            # 🗣 贴「旁白：」这个协议记号 (Yi 报障 2026-08-07:「角色现在不能发言了」)。
            # 从前这里【不贴任何前缀】, 理由写的是「贴了模型会学着把旁白写成台词」——
            # 那说的是贴【角色名】。而输出协议 (_LineSegmenter) 要求每一行都有身份前缀:
            # 「旁白：」或「名字：」, 没前缀的行一律降级成旁白。
            #
            # 于是形成一个自我强化的污染回路: 某一拍模型忘了打前缀 → 整坨落成一条
            # description → 那条【不带前缀】的东西进历史成了「我平时这么写」的示范 →
            # 下一拍更不打前缀。生产实测 8/6 角色台词占比 52%, 8/7 掉到 13%。
            # 2026-08-06 逐字窗口 14→24 把污染示范一次加了 70%, 回路当天跑飞。
            # 窗口本身没错 —— 错的是历史里的示范跟要求的输出格式对不上。
            # ⚠️ 只在【真的用行首前缀协议】的那条路上贴 (2026-08-07 当天的教训:
            # 无条件贴出了更大的祸)。行首前缀是 _LineSegmenter 的协议, 而它只活在
            # plan_and_render 的拍2; 那条路还是 zh-only。走 tool-call 的本子里
            # narration 与 speech 是两个独立 JSON 字段, 根本没有前缀这回事 ——
            # 给它们看「旁白：」的示范, 模型会把这六个字【写进正文】原样印给玩家,
            # 而且逐拍叠加成「旁白：旁白：…」。英文本更惨: 平白多两个汉字,
            # 正好卡在 _lang_break 的 >=2 阈值上, 每拍白白推倒重生一次。
            out.append({"role": "assistant",
                        "content": (NARRATOR_TAG if tag_narration else "")
                        + (b.get("text") or "").strip()})
    return out


def _update_memory_for(state: dict[str, Any], char_id: str, char_history: list[dict[str, str]],
                       llm: LLM) -> None:
    """Per-CHARACTER rolling digest: fold this character's own witnessed turns that slid out
    of the window into their private memory. Keeps isolation intact for long runs."""
    membyc = state.setdefault("memory_by_char", {})
    memcov = state.setdefault("memcov_by_char", {})
    covered = int(memcov.get(char_id, 0))
    cutoff = max(0, len(char_history) - MEMORY_WINDOW)
    if cutoff - covered < MEMORY_BATCH:
        return
    prior = membyc.get(char_id, "")
    try:
        out = llm.generate({"summarize": True, "prior_memory": prior,
                            "new_lines": char_history[covered:cutoff]})
        digest = (out or {}).get("memory")
    except Exception:
        digest = None
    if digest:
        membyc[char_id] = digest
        memcov[char_id] = cutoff


_FOLD_PENDING: dict = {}   # 一次性票据 → {char_id: (digest, cutoff)} (后台折叠的成品架)
_FOLD_CAP = 30


def _folds_async(state: dict[str, Any], folds: list[tuple[str, list]], llm: LLM) -> None:
    """⚡ 记忆折叠出关键路径 (4秒军令: 折叠回合曾 join 1.5~2s 拖住收尾/建议/落库):
    备料全在主线程 (窗口裁剪+prior 快照), 模型调用在后台线程, 成品下一回合
    apply_pending_folds 合账 — 与 profile 蒸馏同一家法, 线程绝不碰 state。
    票据丢失无害: 覆盖游标 memcov 只在合账时前移, 丢单只是下次重折同一段。"""
    membyc = state.setdefault("memory_by_char", {})
    memcov = state.setdefault("memcov_by_char", {})
    jobs = []
    for cid, ch in folds:
        covered = int(memcov.get(cid, 0))
        cutoff = max(0, len(ch) - MEMORY_WINDOW)
        if cutoff - covered < MEMORY_BATCH:
            continue
        jobs.append((cid, membyc.get(cid, ""), list(ch[covered:cutoff]), cutoff))
    if not jobs:
        return
    import threading
    import uuid
    tok = uuid.uuid4().hex[:12]
    state["folds_pending"] = tok

    def _work():
        got = {}
        for cid, prior, lines, cutoff in jobs:
            try:
                out = llm.generate({"summarize": True, "prior_memory": prior,
                                    "new_lines": lines})
                digest = (out or {}).get("memory")
            except Exception:
                digest = None
            if digest:
                got[cid] = (digest, cutoff, prior)
        while len(_FOLD_PENDING) >= _FOLD_CAP:
            _FOLD_PENDING.pop(next(iter(_FOLD_PENDING)), None)
        _FOLD_PENDING[tok] = got   # 空成品也上架 — 让票据能被销掉, 不留死票

    threading.Thread(target=_work, daemon=True).start()


def apply_pending_folds(state: dict[str, Any]) -> bool:
    """回合开演前把后台折好的记忆合进账 (主线程)。三道闸 (审查实锤):
    ① 没折完票不烧 (profile 家法) — 快节奏连打不白折;
    ② prior 等值守卫 — 回合间 bank/手机/定情往 memory_by_char 追的账, 绝不被
      旧底折出的成品无声覆盖 (文与实不许分家); 底变了就弃单, 游标不动, 重折自愈;
    ③ 覆盖游标单调不回退。转生清空记忆后, 旧票据也被 ② 自然挡下。"""
    tok = state.get("folds_pending")
    if not tok:
        return False
    got = _FOLD_PENDING.pop(tok, None)
    if got is None:
        return False               # 后台还没折完: 票留着, 下回合再收
    state.pop("folds_pending", None)
    membyc = state.setdefault("memory_by_char", {})
    memcov = state.setdefault("memcov_by_char", {})
    landed = False
    for cid, (digest, cutoff, prior) in got.items():
        if membyc.get(cid, "") != prior:
            continue               # 底被人动过 (追账/转生/换底): 本单作废
        if cutoff > int(memcov.get(cid, 0)):
            membyc[cid] = digest
            memcov[cid] = cutoff
            landed = True
    return landed


def _update_memory(state: dict[str, Any], history: list[dict[str, str]] | None, llm: LLM) -> None:
    """Fold turns that have slid out of the verbatim window into the rolling digest.

    Cheap, and only fires every ~MEMORY_BATCH turns (not every turn). Mutates state in
    place; degrades to leaving `memory` unchanged on any model failure."""
    history = history or []
    covered = int(state.get("memory_covered") or 0)
    cutoff = max(0, len(history) - MEMORY_WINDOW)   # everything older than the window
    if cutoff - covered < MEMORY_BATCH:
        return                                       # not enough new material yet
    new_lines = history[covered:cutoff]
    prior = state.get("memory") or ""
    try:
        out = llm.generate({"summarize": True, "prior_memory": prior, "new_lines": new_lines})
        digest = (out or {}).get("memory")
    except Exception:
        digest = None
    if digest:
        state["memory"] = digest
        state["memory_covered"] = cutoff


def _characters(content: dict[str, Any]) -> list[dict[str, Any]]:
    return (content.get("story") or {}).get("characters") or []


def lead_speaker(content: dict[str, Any]) -> dict[str, Any] | None:
    chars = _characters(content)
    if not chars:
        return None
    for c in chars:
        if c.get("is_lead"):
            return c
    return chars[0]


def _is_present(c: dict[str, Any], act: int) -> bool:
    """A character is a live participant only if present (not offstage/ghost) AND has
    already made their entrance (current act >= appears_from_act)."""
    if (c.get("presence") or "present") == "offstage":
        return False
    return int(act) >= int(c.get("appears_from_act") or 0)


def present_characters(content: dict[str, Any], act: int,
                       dead: set | None = None) -> list[dict[str, Any]]:
    dead = dead or set()
    return [c for c in _characters(content) if _is_present(c, act) and c.get("id") not in dead]


def _dead_ids(state: dict[str, Any]) -> set:
    return set(state.get("dead_character_ids") or [])


def clock_cfg(content: dict[str, Any]) -> dict[str, Any]:
    """The story's authored clock config (story.clock): optionally a hard deadline —
    {deadline_day, deadline_text, deadline_ending_id}. Empty dict when none authored."""
    return (content.get("story") or {}).get("clock") or {}


def active_slot(content: dict[str, Any], state: dict[str, Any]) -> str | None:
    """The current 时段 name, or None when this story runs no clock (slot-restricted
    schedule entries then apply at all hours — legacy behavior)."""
    if tuning_for(content)["turns_per_slot"] <= 0:
        return None
    clk = state.get("clock") or {}
    return SLOTS[int(clk.get("slot", 0) or 0) % len(SLOTS)]


def real_now_line(content: dict[str, Any], state: dict[str, Any]) -> str:
    """⏰ 【现实时刻】提示词行 (Yi: 角色也得知道才行): 日期·星期·钟点·季节。
    只在现实对齐的故事里发; 字段缺失 (老档未过 sync) 就先不发, 下一回合自然补齐。"""
    if not real_time_on(content):
        return ""
    c = state.get("clock") or {}
    if not c.get("real"):
        return ""
    line = f"{c.get('date', '')} {c.get('wd', '')} {c.get('real', '')} · {c.get('season', '')}"
    if lang_of(content) == "en":
        # 🌐 少喂中文质量 (GH 实弹: 英文主拍里中文元数据越多, 结构化字段越容易被带偏)
        for a, b in (("星期日", "Sun"), ("星期一", "Mon"), ("星期二", "Tue"), ("星期三", "Wed"),
                     ("星期四", "Thu"), ("星期五", "Fri"), ("星期六", "Sat"),
                     ("春季", "Spring"), ("夏季", "Summer"), ("秋季", "Autumn"), ("冬季", "Winter"),
                     ("月", "/"), ("日", "")):
            line = line.replace(a, b)
    return line


def clock_view(content: dict[str, Any], state: dict[str, Any]) -> dict[str, Any] | None:
    """What the UI shows on the 🕐 chip: day/slot label + the authored deadline countdown.
    None = this story runs no clock."""
    slot = active_slot(content, state)
    if slot is None:
        return None
    day = int((state.get("clock") or {}).get("day", 1) or 1)
    en = lang_of(content) == "en"
    slot_disp = _SLOT_EN.get(slot, slot) if en else slot
    view: dict[str, Any] = {"day": day, "slot": slot,
                            "label": f"Day {day} · {slot_disp}" if en else f"第{day}天·{slot}"}
    if real_time_on(content):
        # ⏰ 与 sync_real_clock 同一口径。只改这里不改那里 = 顶栏时间牌和喂给 AI 的
        # 【现实时刻】差几个钟头, 玩家抓到过一次 (runs.py 的「挂着错牌」注释)。
        now = _now_for(state)
        view["real"] = True
        view["hhmm"] = f"{now.hour:02d}:{now.minute:02d}"
        view["label"] = (f"Day {day} · {slot_disp} {view['hhmm']}" if en
                         else f"第{day}天·{slot} {view['hhmm']}")
    ccfg = clock_cfg(content)
    try:
        dd = int(ccfg.get("deadline_day") or 0)
    except (TypeError, ValueError):
        dd = 0
    if dd:
        view["deadline"] = {"text": (ccfg.get("deadline_text") or "").strip() or "大限",
                            "days_left": dd - day}
    return view


def era_of(content: dict[str, Any]) -> str:
    """🏛 这个故事的年代 (「1899年，清末」「三千年后」), 没设定就是空。

    ⚠️ 这是【世界观文字】, 不是时间。它绝不参与任何日期计算 —— 日历一律走玩家自己
    的真实日历 (见 _now_for / state["tz"])。它的活儿只有一件: 让角色、世界观补全、
    生图知道自己身处哪个年代。
    只在玩家开档时亲手写了世界观才会被写进来 (见 routers/runs.py 的准入)。
    """
    story = (content or {}).get("story")
    sb = story.get("sandbox") if isinstance(story, dict) else None
    # 手填/老档里 sandbox 什么形状都可能 (实弹: 是个字符串) —— 不是字典就当没设定,
    # 绝不炸回合。一个读取口不该有能力让整局挂掉。
    return str(sb.get("era") or "").strip() if isinstance(sb, dict) else ""


def sandbox_on(content: dict[str, Any]) -> bool:
    """🏖 无尽沙盒: the player defines the WORLD at run start, the plot generates
    forever (no endings), and the player's own body can break — the dead lose 说/做."""
    return bool(((content.get("story") or {}).get("sandbox") or {}).get("enabled"))


def real_time_on(content: dict[str, Any]) -> bool:
    """⏰ 现实同步 (Yi 2026-07-26 升格全舰默认): 故事时间就是真实时间, 角色与玩家
    活在同一条时间线上。剧本级 tuning.real_clock:0 退回虚构时钟; 沙盒老开关
    sandbox.real_time:False 仍受尊重。前提: 这个故事开着时钟 (turns_per_slot>0)。"""
    sb = (content.get("story") or {}).get("sandbox") or {}
    if sb.get("real_time") is False:
        return False
    if sb.get("enabled"):
        return True          # 沙盒老合同原样: 开着就是现实同步 (除非显式 False)
    t = tuning_for(content)
    return bool(t.get("real_clock", 1)) and t["turns_per_slot"] > 0


def currency_of(content: dict[str, Any]) -> str:
    """💰 what money is CALLED in this world (sandbox.currency; 元 by default)."""
    sb = (content.get("story") or {}).get("sandbox") or {}
    return (sb.get("currency") or "").strip() or "元"


def economy_on(state: dict[str, Any]) -> bool:
    return state.get("money") is not None


# ── 🎯 数值账本 (Yi: 要有更具体的数值) ──────────────────────────────────────────
ATTRS = ("力量", "敏捷", "体质", "心思", "气运")


def _player_strength(state: dict[str, Any]) -> int:
    """🎒 物品判定用的力量读数 (1~10, 5=常人; 无五维档按常人算 — 保守默认)。"""
    try:
        return int((state.get("attrs") or {}).get("力量", 5) or 5)
    except (TypeError, ValueError):
        return 5


def _item_known_anywhere(state: dict[str, Any], name: str) -> bool:
    """🎒 防复活查重全集 (P3 §5): inventory ∪ stashes ∪ char_items —
    灯笼收进柜子 ≠ 灯笼可以被导演重报出场。"""
    if _inv_find(state.get("inventory") or [], name) >= 0:
        return True
    for rows in (state.get("stashes") or {}).values():
        if _inv_find(rows or [], name) >= 0:
            return True
    for sim in (state.get("char_sim") or {}).values():
        if _inv_find((sim or {}).get("items") or [], name) >= 0:
            return True
    return False


_HP_UP = {"dying": "hurt", "hurt": "healthy"}   # 血条阶梯的向上一档


def _apply_item_effect(content: dict[str, Any], state: dict[str, Any],
                       eff: dict[str, Any], target_name: str, item_name: str,
                       moments: list) -> str:
    """P3 §2.2 效果确定性落账 — 从卡读档位写对应账本, 模型说了不算。
    返回点名肇因的叙事句 (效果孪生拍); no_op 也要点明白费并记账。
    枚举铁律: 这里每个分支都对应一个真实存在的账本。"""
    t = str(eff.get("type"))
    mag = max(1, min(3, int(eff.get("magnitude", 1) or 1)))
    if t == "heal":
        if target_name not in ("", "self", "自己"):
            ch = next((c for c in scene_characters(content, state)
                       if (c.get("name") or "") == target_name), None)
            if ch is None:
                _audit(state, "item.effect", False, item_name, f"{target_name}不在跟前")
                return ""
            sim = _sim(state, ch.get("id"))
            steps = 0
            for _ in range(mag):
                nxt = _HP_UP.get(sim.get("hp") or "healthy")
                if nxt:
                    sim["hp"] = nxt
                    steps += 1
            if not steps:
                _audit(state, "item.effect", True, f"{item_name} no_op", "对方本就无伤")
                return f"（你给{target_name}用了{item_name}——TA本就没有伤，白费了。）"
            _audit(state, "item.effect", True, f"heal→{target_name}")
            return f"（{item_name}起了效：{target_name}的伤势见好。）"
        steps = 0
        for _ in range(mag):
            nxt = _HP_UP.get(state.get("player_hp") or "healthy")
            if nxt:
                state["player_hp"] = nxt
                steps += 1
        if not steps:
            _audit(state, "item.effect", True, f"{item_name} no_op", "本就无伤")
            return f"（你用了{item_name}——可你本就没有伤，白费了。）"
        moments.append({"kind": "player_hp", "hp": state["player_hp"]})
        _audit(state, "item.effect", True, "heal→self")
        return f"（{item_name}起了效：伤口不再渗血，伤势见好。）"
    if t == "light":
        lid = state.get("location_id")
        if not lid:
            return ""
        # 落 place_facts (地点持久物理事实 — 提示词在读的真账本, 见 P3 实现偏差②)
        pf = dict(state.get("place_facts") or {})
        lst = list(pf.get(lid) or [])
        wf = f"这里被{item_name}照亮了"
        if all(logic._norm(x.get("text", "")) != logic._norm(wf) for x in lst):
            lst.append({"text": wf,
                        "label": (clock_view(content, state) or {}).get("label", "")})
            pf[lid] = lst[-6:]
            state["place_facts"] = pf
        _audit(state, "item.effect", True, "light")
        return f"（你点起{item_name}，暗处亮起来了。）"
    # reserved 类 (cure 等): 账本未立, live_effects 已在上游滤掉 — 到这里是防御
    _audit(state, "item.effect", False, item_name, f"{t}账本未立")
    return ""


def ensure_player_attrs(content: dict[str, Any], state: dict[str, Any],
                        persona: dict[str, Any] | None, llm: LLM | None = None) -> dict | None:
    """玩家五维 (1~10, 5=常人): judged ONCE from who the player is in this world, then
    it's law — actions.classify folds them into the dice DC (stats with teeth)."""
    if state.get("attrs") or (state.get("mode") or "character") == "god":
        return state.get("attrs")
    llm = lang_llm(llm or get_llm(), content)
    pcid = state.get("player_character_id")
    pc = _char_by_id(content, pcid) if pcid else None
    who = ((pc or {}).get("persona_text") or (pc or {}).get("role")
           or (persona or {}).get("background") or (persona or {}).get("name") or "")
    try:
        out = llm.generate({"gen_attrs": True, "who": str(who)[:300],
                            "powers": list(state.get("powers") or []),
                            "language": lang_of(content)}) or {}
    except Exception:
        out = {}
    attrs = out.get("attrs") or {}
    if not all(k in attrs for k in ATTRS):
        attrs = {k: 5 for k in ATTRS}
    state["attrs"] = {k: max(1, min(10, int(attrs[k]))) for k in ATTRS}
    _audit(state, "attrs.set", True,
           " ".join(f"{k}{v}" for k, v in state["attrs"].items()))
    return state["attrs"]


def ensure_npc_rank(content: dict[str, Any], state: dict[str, Any], char: dict[str, Any],
                    llm: LLM) -> dict[str, Any]:
    """⚡ 我是魂士的话别人是什么 (Yi): every character sits SOMEWHERE on the story's own
    ladder, judged once and cached in state.npc_cult — and carries money like a real
    person (sim sheet). The prompt anchors both, so 境界差距 and 买卖 stay consistent."""
    cid = char.get("id")
    if not cid:
        return {}
    cached = (state.get("npc_cult") or {}).get(cid)
    if cached is not None:
        return cached
    sb = (content.get("story") or {}).get("sandbox") or {}
    ranks = [str(r) for r in ((sb.get("progression") or {}).get("ranks") or [])]
    entry: dict[str, Any] = {}
    if ranks:
        pcid = state.get("player_character_id")
        known = [c.get("name") for c in _characters(content)
                 if c.get("name") and c.get("id") not in (cid, pcid)][:8]
        pname = _char_name(content, pcid) if pcid else None
        if pname:
            known.append(pname)
        try:
            out = llm.generate({"rank_judge": True, "ranks": ranks,
                                "char": {"name": char.get("name"), "role": char.get("role"),
                                         "persona_text": char.get("persona_text")},
                                "known_names": known,
                                "currency": currency_of(content),
                                "base_money": int(sb.get("start_money") or 50),
                                "language": lang_of(content)}) or {}
        except Exception:
            out = {}
        if out.get("rank_i") is not None:
            i = max(0, min(len(ranks) - 1, int(out["rank_i"])))
            entry["rank_i"], entry["rank"] = i, ranks[i]
        if out.get("money") is not None:
            _sim(state, cid)["money"] = max(0, int(out["money"]))
        # 🕶 暗线 (Yi: 表层关系之下才是重要的): a secret stance nobody knows — stored
        # per character, fed ONLY into their own prompt (不开天眼 by construction),
        # coloring behavior until the story pries it open.
        if out.get("secret"):
            entry["secret"] = str(out["secret"])[:60]
    state.setdefault("npc_cult", {})[cid] = entry
    if entry.get("rank"):
        _audit(state, "npc.rank", True, f"{char.get('name', '')}:{entry['rank']}")
    return entry


def _own_rank_line(content: dict[str, Any], state: dict[str, Any], char: dict[str, Any],
                   llm: LLM) -> str:
    """Depth-0 anchor for a speaker: their OWN ladder rank vs the player's, plus their
    pocket money — so power gaps and haggling stay consistent with the ledger."""
    if not sandbox_on(content):
        return ""
    e = ensure_npc_rank(content, state, char, llm)
    en = lang_of(content) == "en"
    bits = []
    if e.get("rank"):
        if en:
            line = f"Your own rank on the ladder is [{e['rank']}]"
            pv = cult_view(content, state)
            if pv and pv.get("rank"):
                line += (f"; the player's rank is [{pv['rank']}]. The rank gap IS the power "
                         "gap; carry it in every word and move")
        else:
            line = f"你「{char.get('name', '')}」自己的境界是【{e['rank']}】"
            pv = cult_view(content, state)
            if pv and pv.get("rank"):
                line += f"；对面玩家的境界是【{pv['rank']}】。境界差距就是实力差距，言行要贴住这一点"
        bits.append(line + ("." if en else "。"))
    money = (((state.get("char_sim") or {}).get(char.get("id")) or {}).get("money"))
    if money is not None:
        bits.append(f"You carry about {int(money)} {currency_of(content)}; deals and loans come out of it."
                    if en else f"你身上约有{int(money)}{currency_of(content)}，买卖赊借都从这里出。")
    if e.get("secret"):
        bits.append((f"You harbor one thing NOBODY knows: {e['secret']}. It colors your eyes, "
                     "distance and choices, but you never let it slip unless the story forces it.")
                    if en else
                    f"你心里还藏着一桩【没人知道】的事：{e['secret']}。"
                    "它一直影响你的眼神、分寸与选择，但你绝不轻易说破——"
                    "除非剧情把你逼到那一步。")
    return "".join(bits)


def as_str_list(v: Any) -> list[str]:
    """把模型返回的「本该是 list[str]」的字段收成真正的 list[str]。

    ⚠️ 这是一族 bug 的收口 (Yi 报障 2026-08-04)。模型偶尔把 list 字段写成一个字符串,
    而 `for x in v` 对字符串是【逐字符】迭代 —— 于是建议 chips 变成了:

        directed["suggestions"] = '["我当是夸奖好了。", "我笑着摇头"]'
        [str(x).strip()[:48] for x in directed["suggestions"]]
        → ['[', '"', '我', '当', ...]      前两项就是玩家看到的那两个 chip

    Yi 报的是「【】"" 的截断有问题」—— 看着像截断切断了成对符号, 其实那两个符号是
    字符串的头两个字符。`(v or [])` 挡不住: 非空字符串是真值, 照样迭代。

    规矩: 字符串当【一条】, 不是一串字符。看着像 JSON 数组的先试着解开 (模型最常见的
    违约形态就是把数组序列化成了字符串); 解不开就整条留着 —— 宁可给一条怪句子, 也不
    给一串标点。
    """
    if v is None:
        return []
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return []
        if s.startswith("[") and s.endswith("]"):
            try:
                import json as _json
                parsed = _json.loads(s)
                if isinstance(parsed, list):
                    return [str(x).strip() for x in parsed if str(x).strip()]
            except Exception:
                pass    # 解不开 = 它本来就是一句带方括号的话, 别拆
        return [s]
    if isinstance(v, (list, tuple, set)):
        return [str(x).strip() for x in v if str(x).strip()]
    s = str(v).strip()
    return [s] if s else []


# 成对的包裹符号: 掐长之后常留下没闭合的半边 (那才是真的「截断把符号切断了」)
_WRAP_PAIRS = {"【": "】", "「": "」", "『": "』", "“": "”", "‘": "’",
               "《": "》", "(": ")", "（": "）", "[": "]", "\"": "\"", "'": "'"}


def unwrap_pairs(s: str) -> str:
    """脱掉最外层的包裹符号, 并抹掉截断留下的半边。

    只动【最外层】—— 句子中间的符号是内容 (「我说【别急】然后坐下」不许被动)。
    """
    t = (s or "").strip()
    for _ in range(3):          # 允许套娃 (「“…”」), 但别无限转
        if len(t) >= 2 and _WRAP_PAIRS.get(t[0]) == t[-1]:
            t = t[1:-1].strip()
            continue
        break
    # 半边: 开头一个没闭合的左符 / 结尾一个没配对的左符 或 多余的右符
    if t[:1] in _WRAP_PAIRS and _WRAP_PAIRS[t[:1]] not in t[1:]:
        t = t[1:].strip()
    if t[-1:] in _WRAP_PAIRS and t[-1:] not in ("”", "’"):   # 结尾是【左】符 = 被切了
        t = t[:-1].strip()
    if t[-1:] in _WRAP_PAIRS.values() and not any(
            k for k, v in _WRAP_PAIRS.items() if v == t[-1:] and k in t[:-1]):
        t = t[:-1].strip()
    return t


def clip_sentence(s: str, n: int) -> str:
    """Cut at the last COMPLETE sentence within n chars — a bio must end like a sentence,
    never trail off mid-word or with an ellipsis (Yi: 简介以…结束)."""
    s = (s or "").strip().rstrip("…·.")
    if len(s) <= n:
        return s
    cut = s[:n]
    best = max(cut.rfind(p) for p in "。！？!?；;")
    if best >= n // 3:
        return cut[:best + 1]
    i = max(cut.rfind("，"), cut.rfind(","))
    return (cut[:i] + "。") if i >= n // 3 else cut


# 🥊 竞技合同 (Yi): an agreed contest + the player's start signal = the dice decide NOW
_CONTEST_RE = re.compile(
    r"(开始吧|开始了|来吧|放马过来|出招|开打|动手吧|上吧|见真章|分个高下|比试|切磋|较量"
    r"|一决胜负|开赛|预备.{0,2}开始|^开始$)")


def contest_signal(text: str) -> bool:
    t = (text or "").strip()
    if not t or len(t) > 40:
        return False
    if any(n in t for n in ("别开始", "先别", "不比", "不打", "等等")):
        return False
    return bool(_CONTEST_RE.search(t))


def _contest_opponent(content: dict[str, Any], state: dict[str, Any],
                      target_character_id: str | None) -> dict[str, Any] | None:
    """Who is the player squaring off against: the addressed character if present,
    else the only other person here, else the present lead. None = no opponent."""
    pcid = state.get("player_character_id")
    here = [c for c in scene_characters(content, state) if c.get("id") != pcid]
    if not here:
        return None
    if target_character_id:
        hit = next((c for c in here if c.get("id") == target_character_id), None)
        if hit:
            return hit
    if len(here) == 1:
        return here[0]
    return next((c for c in here if c.get("is_lead")), here[0])


def _rank_gap(content: dict[str, Any], state: dict[str, Any], opp: dict[str, Any],
              llm: LLM) -> int:
    """Opponent's ladder index minus the player's — the mechanical 碾压 in a contest."""
    cfg = cult_cfg(content)
    if not cfg:
        return 0
    ranks = [str(r) for r in (cfg.get("ranks") or [])]
    e = ensure_npc_rank(content, state, opp, llm)
    try:
        mine = ranks.index((cult_view(content, state) or {}).get("rank"))
    except (ValueError, TypeError):
        return 0
    if e.get("rank_i") is None:
        return 0
    return int(e["rank_i"]) - mine


def market_view(content: dict[str, Any], state: dict[str, Any],
                llm: LLM | None = None) -> dict[str, Any]:
    """🛒 今日集市 (Yi: 要有商城): 6 world-true goods, re-stocked each in-story day.
    Raises player-readable when this story runs no economy."""
    if not economy_on(state):
        raise ValueError("这个故事里没有通行的市面")
    llm = lang_llm(llm or get_llm(), content)
    day = int(((state.get("clock") or {}).get("day")) or 1)
    mk = state.get("market")
    if not (isinstance(mk, dict) and mk.get("day") == day and mk.get("items")):
        story = content.get("story") or {}
        try:
            out = llm.generate({"gen_market": True,
                                "world": story.get("world_facts") or story.get("world_long") or "",
                                "currency": currency_of(content),
                                "base_money": int((story.get("sandbox") or {}).get("start_money") or 50),
                                "language": lang_of(content)}) or {}
        except Exception:
            out = {}
        items = [dict(it) for it in (out.get("items") or []) if it.get("name")]
        for i, it in enumerate(items):
            it["id"] = f"mk{day}_{i}"
            # 🎒 上架即入籍 (实体化 P2): 集市是 new_template 最高频来源 —
            # 货一亮相物性卡就快照进档 (detail 上收 desc), 配图管线按 tid 直接可用
            it["tid"] = items_mod.ensure_template(
                state, it["name"], {**items_mod.rule_card(it["name"]),
                                    "desc": str(it.get("detail") or "")[:60]})
        mk = {"day": day, "items": items}
        state["market"] = mk
    return {"day": day, "currency": currency_of(content),
            "money": int(state.get("money") or 0), "items": list(mk.get("items") or [])}


def market_buy(content: dict[str, Any], state: dict[str, Any], item_id: str,
               llm: LLM | None = None) -> dict[str, Any]:
    """Buying is a LEDGER op: money down, item into the pocket, one audit line."""
    view = market_view(content, state, llm)
    it = next((x for x in view["items"] if x.get("id") == item_id), None)
    if not it:
        raise ValueError("这件货已经不在摊上了")
    price = int(it.get("price") or 0)
    have = int(state.get("money") or 0)
    if have < price:
        raise ValueError(f"钱不够：这要{price}{view['currency']}，你身上只有{have}")
    state["money"] = have - price
    log = list(state.get("money_log") or [])   # 🏦 银行流水: 买东西也是账
    log.append({"delta": -price, "why": f"买{it.get('name', '')}"[:30],
                "label": (clock_view(content, state) or {}).get("label", "")})
    state["money_log"] = log[-20:]
    # 🎒 市集入库走堆叠 (add_stock 粒度): 买第二份同名货是 qty+1, 不是被防重复吞掉
    items_mod.add_stack(state, it.get("name", ""), 1, it.get("detail", ""))
    _audit(state, "market.buy", True, f"{it.get('name', '')} -{price}")
    view["money"] = state["money"]
    view["bought"] = it.get("name")
    return view


def _to_int(s, lo: int = -999999, hi: int = 999999) -> int:
    try:
        digits = "".join(ch for ch in str(s) if ch.isdigit())
        v = int(digits) if digits else 0
        if "-" in str(s):
            v = -v
        return max(lo, min(hi, v))
    except (TypeError, ValueError):
        return 0


def book_money(content: dict[str, Any], state: dict[str, Any], delta: int,
               why: str) -> int:
    """💰 hard-ledger a payment/earning. Spending clamps at the balance (you cannot pay
    what you don't have). Returns the APPLIED delta (0 = nothing happened)."""
    if not economy_on(state):
        return 0
    delta = max(-9999, min(9999, int(delta)))
    if delta < 0:
        delta = -min(-delta, int(state.get("money") or 0))
    if not delta:
        return 0
    state["money"] = int(state.get("money") or 0) + delta
    log = list(state.get("money_log") or [])
    log.append({"delta": delta, "why": (why or "").strip()[:30],
                "label": (clock_view(content, state) or {}).get("label", "")})
    state["money_log"] = log[-20:]
    return delta


def serve_news(state: dict[str, Any]) -> str:
    """🌊 the next untold piece of world news (told exactly once, like rumors)."""
    for nw in state.get("world_news") or []:
        if not nw.get("heard"):
            nw["heard"] = True
            return nw.get("text") or ""
    return ""


def mint_world_news(content: dict[str, Any], state: dict[str, Any], llm: LLM,
                    days_gone: int) -> None:
    """🌊 世界自转: for each real day the player was away (capped at 2), the sandbox
    world makes one piece of its own news — grounded in the worldview, the cast and
    the standing place facts, served to the player once through whoever tells it."""
    story = content.get("story") or {}
    names = [c.get("name") for c in _characters(content) if c.get("name")][:6]
    facts: list[str] = []
    for lst in (state.get("place_facts") or {}).values():
        facts += [f.get("text") for f in lst if f.get("text")]
    news = list(state.get("world_news") or [])
    day = int((state.get("clock") or {}).get("day", 1) or 1)
    for _ in range(max(0, min(2, int(days_gone)))):
        try:
            out = llm.generate({"world_news": True,
                                "worldview": (story.get("world_long") or "")[:600],
                                "cast": names, "facts": facts[-6:],
                                "recent": [x.get("text") for x in news[-3:]]}) or {}
        except Exception:
            out = {}
        txt = dedash(str(out.get("text") or "").strip())[:80]
        if txt:
            news.append({"day": day, "text": txt, "heard": False})
    state["world_news"] = news[-10:]


def reincarnate(content: dict[str, Any], state: dict[str, Any]) -> list[dict[str, Any]]:
    """🔄 沙盒转生: the dead player returns as a NEW face in the SAME world. Everything
    the world lived through stays (facts, news, people and their lives, deaths); the
    player's own side is reborn: body, pockets, money, name, every relationship. The
    former life becomes a rumor the world may pass around."""
    sb = (content.get("story") or {}).get("sandbox") or {}
    ident = (state.get("identity") or "").strip()
    lives = list(state.get("past_lives") or [])
    lives.append({"identity": ident,
                  "day": int((state.get("clock") or {}).get("day", 1) or 1),
                  "affinity": int(state.get("affinity") or 0)})
    state["past_lives"] = lives[-5:]
    who = ident or "一个外来的面孔"
    rumors = list(state.get("rumors") or [])
    rumors.append({"text": f"听说前阵子{who}没了。人没了，事还挂在人们嘴上。", "heard": False})
    state["rumors"] = rumors[-6:]
    # body-side reset — the world's ledgers (place_facts / world_news / npc_rel /
    # char_sim / dead_character_ids) all survive untouched
    state["player_hp"] = "healthy"
    state["inventory"] = []
    state["identity"] = None
    state["identity_log"] = []
    state["affinity"] = 0
    state["rel"] = {}
    state["rel_log"] = {}
    state["met_ids"] = []
    state["following"] = []
    state["promises"] = []
    state["quests"] = []
    state["phone"] = {"threads": {}}
    state["memory"] = ""
    state["memory_by_char"] = {}
    # 🔄 折叠账本随记忆一起清: 票据不清会把前世 digest 复活塞回来 (审查实锤,
    # prior 守卫是第二道闸); 游标不清则新生的折叠永远够不到批量线, 再也不折
    state["memcov_by_char"] = {}
    state.pop("folds_pending", None)
    if economy_on(state):
        state["money"] = _to_int(sb.get("start_money"), 0, 99999) or 100
        state["money_log"] = []
    return [dedash_beat({"type": "description", "speaker_name": None, "text": "✦ 转生 ✦"}),
            dedash_beat({"type": "description", "speaker_name": None,
                         "text": "（黑暗褪去。你在一具陌生的身体里睁开眼：这个世界一切如旧，"
                                 "只是再没有人认得现在的你。"
                                 + (f"关于{who}的传闻，还在街上飘着。" if ident else "")
                                 + "）"})]


def _now():
    """Wall clock (北京时间), injectable for tests.

    ⚠️ 保持【零参】: tests/test_sandbox.py 与 tests/test_economy.py 把它 monkeypatch
    成零参 lambda。要换时区请用 _now_for(state), 别给这个函数加参数。"""
    from datetime import datetime, timedelta, timezone
    return datetime.now(timezone(timedelta(hours=8)))


def _now_for(state: dict[str, Any] | None = None):
    """⏰ 墙钟, 换算到【这个存档的玩家】所在的时区 (Yi 2026-08-04:「要对齐时区」)。

    只用于【日历口径】—— 今天几号、星期几、落在哪个时段。任何测量【时长】的地方
    (living.due 的心跳到期、away_hours 的离开多久) 继续用 UTC: 时长与时区无关,
    顺手换过去会让心跳周期随玩家时区漂移。

    state["tz"] 是 IANA 名 (如 "America/New_York"), 由客户端上报账号级 User.tz、
    建档时镜像进来。缺失或解析不了 → 原样退回 _now() (服务器 +8), 老档逐位不变。
    ⚠️ 绝不退回"冻结的分钟偏移": 那种做法一遇夏令时就错整整半年, 而且 JS 的
    getTimezoneOffset() 符号是反的, 迟早有人写反 —— 协议里根本不存在偏移数字。
    """
    from datetime import timedelta, timezone
    now = _now()
    if now.tzinfo is None:      # monkeypatch 可能给的是 naive datetime
        now = now.replace(tzinfo=timezone(timedelta(hours=8)))
    name = str((state or {}).get("tz") or "").strip()
    if not name:
        return now
    try:
        from zoneinfo import ZoneInfo
        return now.astimezone(ZoneInfo(name))
    except Exception:
        if isinstance(state, dict):
            state["tz_bad"] = name[:64]   # 留痕: 静默漂移比报错更难查
        return now


def sync_real_clock(content: dict[str, Any], state: dict[str, Any]) -> dict[str, Any] | None:
    """⏰ Mirror the real world into the story clock: day = real days since the run began
    (day 1 = the day it started), slot = 晨 05~11 / 午 12~17 / 夜 18~04. Everything
    downstream (作息, promises, moods, phone labels) reads the synced clock unchanged, so
    a promise for 明晚 literally means: come back tomorrow evening."""
    from datetime import date
    now = _now_for(state)      # ⏰ 玩家的日历, 不是服务器的 (缺 tz 时与从前逐位相同)
    try:
        d0 = date.fromisoformat(state.get("real_epoch") or "")
    except (TypeError, ValueError):
        d0 = now.date()
        state["real_epoch"] = d0.isoformat()
    day = max(1, (now.date() - d0).days + 1)
    # ⏱ 单调护栏: 玩家改了时区、或跨时区旅行, day 有可能算出比上一次小。
    # 账本不许倒流 —— _time_index = day*3+slot 是全船约定/心事/court 的时间轴,
    # 一倒退, 已经到期的约定会在 open↔missed 之间来回翻面, 纪念日会二次触发。
    # 最坏只是"停一天", 比倒流便宜得多。
    _prev = int((state.get("clock") or {}).get("day", 0) or 0)
    if _prev and day < _prev:
        day = _prev
    slot = 0 if 5 <= now.hour < 12 else (1 if 12 <= now.hour < 18 else 2)
    if lang_of(content) == "en":
        # 🌐 en 剧本时间四件在源头就写英文 (GH 清剿: state 里不留中文, 免下游各自转换)
        _wd_en = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")[now.weekday()]
        _season_en = ("Winter", "Winter", "Spring", "Spring", "Spring", "Summer", "Summer",
                      "Summer", "Autumn", "Autumn", "Autumn", "Winter")[now.month - 1]
        state["clock"] = {"day": day, "slot": slot, "turns_in_slot": 0,
                          "real": f"{now.hour:02d}:{now.minute:02d}",
                          "wd": _wd_en, "date": f"{now.month}/{now.day}",
                          "season": _season_en}
        return clock_view(content, state)
    _wd = "一二三四五六日"[now.weekday()]
    _season = ("冬", "冬", "春", "春", "春", "夏", "夏", "夏", "秋", "秋", "秋", "冬")[now.month - 1]
    state["clock"] = {"day": day, "slot": slot, "turns_in_slot": 0,
                      # ⏰ 真实时刻四件 (Yi: 角色也得知道才行) — 提示词的时间常识素材
                      "real": f"{now.hour:02d}:{now.minute:02d}",
                      "wd": f"星期{_wd}", "date": f"{now.month}月{now.day}日",
                      "season": f"{_season}季"}
    return clock_view(content, state)


# 🪪 名字守卫: the directed channel occasionally leaks a prose fragment into the
# name slot (实弹: an NPC named「谁看见」). Interrogatives, pronouns and deictic
# openers are dead giveaways. Conservative on purpose — 宁可放过, 不可错杀真名.
_NAME_BAD_FULL = {"你", "我", "他", "她", "它", "咱", "大家", "众人", "别人",
                  "对方", "自己", "有人", "某人", "路人"}
_NAME_BAD_START = ("谁", "什么", "怎么", "哪个", "哪里", "哪儿", "哪位", "那个",
                   "这个", "有人", "某个", "某人", "一个", "一位", "此人",
                   "这人", "那人", "路人")


def npc_name_ok(nm: str) -> bool:
    """A name must LOOK like a name — reject sentence fragments before they become people."""
    nm = (nm or "").strip()
    if not nm or len(nm) > 12:
        return False
    if nm in _NAME_BAD_FULL or any(nm.startswith(p) for p in _NAME_BAD_START):
        return False
    return not any(ch in nm for ch in "，。！？；：、,.!?;: \n\t")


def place_name_ok(nm: str) -> bool:
    """地名口径 (rename/铸造校验) — 别复用 npc_name_ok: 它禁空格, EN 地名多词是常态
    ("Old Docks" 曾必 400)。zh 沿人名尺 (短、无空格标点); EN 走 _bad_place_name 的
    词数尺, 允许空格/撇号/连字符, 仍禁标点。"""
    nm = (nm or "").strip()
    if not nm:
        return False
    if _CJK_ANY.search(nm):
        return npc_name_ok(nm)
    if _bad_place_name(nm):
        return False
    return not any(ch in nm for ch in "，。！？；：、,.!?;:\n\t")


def seed_sandbox_cast(content: dict[str, Any], llm: LLM | None = None,
                      mature: bool = False) -> None:
    """🏖 the sandbox opens ALIVE: conjure a small starting cast from the player's
    worldview (this run's private copy owns them; more will be born in play).
    Deterministic fallback guarantees at least one person to meet."""
    story = content.get("story") or {}
    if story.get("characters"):
        return
    llm = lang_llm(llm or get_llm(), content)
    try:
        out = llm.generate({"sandbox_cast": True, "mature": bool(mature),
                            "worldview": (story.get("world_long") or "")[:1200]}) or {}
    except Exception:
        out = {}
    import uuid as _uuid
    chars: list[dict[str, Any]] = []
    for c in (out.get("characters") or [])[:4]:
        nm = str(c.get("name") or "").strip().strip("「」\"'")[:12]
        if not nm or not npc_name_ok(nm) or any(nm == x.get("name") for x in chars):
            continue
        # 🎒 conjured people carry real things: gift-able, trade-able, snatch-able
        items = []
        for raw in (c.get("items") or [])[:2]:
            if isinstance(raw, dict):
                inm, idt = str(raw.get("name") or "").strip(), str(raw.get("detail") or "").strip()
            else:
                inm, _, idt = str(raw).partition("|")
                inm, idt = inm.strip(), idt.strip()
            if inm:
                items.append({"name": inm[:16], "detail": idt[:60]})
        chars.append({"id": f"gen_{_uuid.uuid4().hex[:8]}", "name": nm,
                      "role": str(c.get("role") or "").strip()[:24],
                      "persona_text": str(c.get("persona") or "").strip()[:240],
                      # 🗣 指纹自动出生: 沙盒班底出生就带说话规律 (speaker prompt 直接吃)
                      "voice_print": str(c.get("voice") or c.get("voice_print") or "").strip()[:60],
                      "items": items,
                      "relation_default": "stranger", "generated": True,
                      "is_lead": not chars})
    if not chars:
        chars = [{"id": f"gen_{_uuid.uuid4().hex[:8]}", "name": "迎面而来的陌生人",
                  "role": "这个世界最先注意到你的人",
                  "persona_text": "对生面孔有超出寻常的兴趣，话不多，但每一句都像已经认识你很久。",
                  "relation_default": "stranger", "generated": True, "is_lead": True}]
    story.setdefault("characters", []).extend(chars)


def anchor_homeless_cast(content: dict[str, Any], location_id: str) -> None:
    """🏖 sandbox spatial rigor: conjured characters live SOMEWHERE. Anyone generated
    without a home is anchored to the given place (the start location), so presence
    obeys the map instead of everyone being everywhere. Later arrivals get their home
    where they were born (see the new_character block); npc_moves relocate for real."""
    for c in (content.get("story") or {}).get("characters") or []:
        if c.get("generated") and not c.get("home_location_id"):
            c["home_location_id"] = location_id


def align_clock_to_act(content: dict[str, Any], state: dict[str, Any],
                       act_index: int) -> dict[str, Any] | None:
    """⏳ 幕锚定时间 (act.time = {day?, slot?}): entering an act snaps the clock FORWARD
    to where the script says this scene happens — never backward. 剧本写「第3天夜里」，
    进幕就真的是第3天夜里：🕐 时辰、人物作息、旁白口径从此对得上。A bare slot means
    「这场戏发生在下一个这样的时辰」(same day if still ahead, else the next one).
    Returns the fresh clock_view when the snap actually moved time; None otherwise."""
    if tuning_for(content)["turns_per_slot"] <= 0:
        return None
    anchor = (current_act(content, act_index) or {}).get("time") or {}
    want_slot = (anchor.get("slot") or "").strip()
    try:
        want_day = int(anchor.get("day") or 0)
    except (TypeError, ValueError):
        want_day = 0
    target = SLOTS.index(want_slot) if want_slot in SLOTS else None
    if not want_day and target is None:
        return None
    clk = dict(state.get("clock") or {})
    clk.setdefault("day", 1); clk.setdefault("slot", 0); clk.setdefault("turns_in_slot", 0)
    before = (int(clk["day"]), int(clk["slot"]))
    if want_day > int(clk["day"]):
        clk["day"], clk["slot"] = want_day, (target if target is not None else 0)
    elif target is not None:
        while int(clk["slot"]) != target:
            clk["slot"] = int(clk["slot"]) + 1
            if int(clk["slot"]) >= len(SLOTS):
                clk["slot"], clk["day"] = 0, int(clk["day"]) + 1
    if (int(clk["day"]), int(clk["slot"])) == before:
        return None
    clk["turns_in_slot"] = 0
    state["clock"] = clk
    return clock_view(content, state)


def _char_home(c: dict[str, Any], act: int, slot: str | None = None) -> str | None:
    """作息表说这个角色在哪 (ONE RUNG of char_position, never the answer by itself).

    Among schedule entries with from_act <= act that cover the given 时段 (an entry may
    carry slots: ["夜"] — no slots = all hours), the highest from_act wins; slot-specific
    beats generic on a tie. A scheduled character whom no entry covers this hour is AWAY
    (off somewhere, unreachable) — home_location_id only backs up characters with no
    reached schedule. None = ubiquitous (legacy stories that don't pin characters).

    🔒 PRIVATE — "谁此刻在哪" 的唯一出口是 char_position(). 作息只是它的第 7 级, 上面
    还压着 同行/濒死/威胁/被掳/约定/钉子 六级。绕过 char_position 直接问作息 = 表现层
    各说各话 (实弹 2026-07-30: 打电话独走这条路, 于是角色被钉在码头时全场显示"在场",
    电话里却是"无人接听, TA此刻不知在何处")。合法调用者只有三个, 各有各的理由:
      · char_position   — 它就是第 7 级本身
      · apply_char_move — 问的是【所有权】: 作息管着这双脚吗? 不是问人在哪
      · make_promise    — 问的是【未来某时段】TA会在哪; char_position 只懂"现在", 答不了
    新增第四个调用者前先问自己: 我问的是"现在谁在哪"吗? 是 → 用 char_position。
    tests/test_position_single_source.py 会替你把关。"""
    best = (-1, -1)
    best_loc = None
    reached = False
    for e in (c.get("schedule") or []):
        try:
            fa = int(e.get("from_act") or 0)
        except (TypeError, ValueError):
            continue
        lid = (e.get("location_id") or "").strip()
        if not lid or fa > int(act):
            continue
        reached = True
        entry_slots = [s for s in (e.get("slots") or []) if s]
        if entry_slots and slot is not None and slot not in entry_slots:
            continue
        key = (fa, 1 if entry_slots else 0)
        if key > best:
            best, best_loc = key, lid
    if best_loc:
        return best_loc
    if reached and slot is not None:
        return AWAY
    return c.get("home_location_id")


# ── character simulation sheet (程序层的角色细节) ────────────────────────────────
# Per-character DETERMINISTIC state the engine owns: an actual tracked position, a
# graded life state, a persisted intent. The model narrates and REQUESTS changes; the
# engine validates and books them. This kills the "characters feel random" problem:
# nobody is everywhere, nobody dies in one breath, nobody forgets their own plan.
def _sim(state: dict[str, Any], cid: str) -> dict[str, Any]:
    return state.setdefault("char_sim", {}).setdefault(cid, {})


def _sim_pos_loc(v: Any) -> str | None:
    """char_sim[cid]['pos'] is DUAL-WRITTEN: booked location ids (moves, dying pins)
    AND 场记 pose frames {'text','at',...}. Read as a LOCATION, a frame means "where
    it was recorded" — its 'at'. Never let the frame dict leak out as a place (it
    crashed /map with unhashable-dict for a playable char with no home_location_id)."""
    if isinstance(v, dict):
        v = v.get("at")
    return v if isinstance(v, str) and v.strip() else None


def _promise_loc_now(state: dict[str, Any], cid: str | None) -> str | None:
    """该角色此刻有开着的约定、钟点正是现在 → 约定地点。这是无作息角色守约的腿。"""
    if not cid:
        return None
    now = _time_index(state)
    for pr in state.get("promises") or []:
        if (pr.get("status") == "open" and pr.get("char_id") == cid
                and pr.get("location_id") and _promise_index(pr) == now):
            return pr["location_id"]
    return None


def char_position(content: dict[str, Any], state: dict[str, Any],
                  c: dict[str, Any]) -> str | None:
    """The character's ACTUAL current location id. Resolution order: following the
    player → the player's spot; an authored 作息 for this act+slot → that place (the
    author is boss; AWAY = unreachable this hour); a tracked sim position (a validated,
    booked move) → there; otherwise the story's OPENING location — in a story with a
    map, nobody is 'everywhere' anymore. None = mapless story (legacy behavior)."""
    locs = _locations(content)
    if not locs:
        return None
    cid = c.get("id")
    # 0️⃣ 玩家自己那具身体 —— 这九级里【最确定】的一件事, 所以排第一。
    #
    # 从前一级都没有: 附身模式下玩家自己的角色被作息表/sim/兜底算到别处, 而玩家的
    # 真实位置一直老老实实记在 state["location_id"] 里。实弹 (2026-08-06 Yi 报障):
    # 玩家人在【西九龙警署总部】, char_position 却说他在【九龙城区】→ scene_characters
    # 返回空 → 到达旁白那一拍 present_ids=[] → 那一拍对任何人都不可见 → 模型永远不
    # 知道他已经到了 → 下一回合把"赶去警署"整段重演一遍 (离开蓝信一、穿过两条街、
    # 拐过菠萝冰摊、推开玻璃门 —— 而他三秒前刚推开那扇门)。
    #
    # 只在【附身模式】成立: 上帝视角下没人在操纵那具身体, 它就是个普通 NPC, 照常走
    # 下面的级联 (与 map_view / scene_cast 排除 pcid 的条件同一口径)。
    if cid and cid == state.get("player_character_id") \
            and (state.get("mode") or "character") == "character":
        return state.get("location_id") or (locs[0] or {}).get("id")
    if cid and cid in (state.get("following") or []):
        return state.get("location_id") or (locs[0] or {}).get("id")
    sim0 = (state.get("char_sim") or {}).get(cid) or {}
    if sim0.get("hp") == "dying" and _sim_pos_loc(sim0.get("pos")):
        return _sim_pos_loc(sim0.get("pos"))  # the dying lie where they fell
    _tc = threat_mod.cfg(content)
    if _tc and cid == _tc["char_id"] and (state.get("threat") or {}).get("pos"):
        return state["threat"]["pos"]  # 🦇 the hunter's feet belong to the threat ledger
    if cid in (state.get("taken") or {}):
        return (state.get("taken") or {})[cid]  # 🚪 预定命运: they were carried off
    # 🤝 约定的钟点到了: TA如约而至。实弹: 无作息角色的约定没人赴, 玩家还吃爽约扣分
    # (台账 ⬜)。排在 pin 之前 (审查实锤): 离场散文的 AWAY pin 永不释放、seek pin
    # 跨时段存活 — 长寿钉不许把守约打穿; 也压过作息 = 换幕后班表改了也守约。
    prloc = _promise_loc_now(state, cid)
    if prloc:
        return prloc
    pin = (state.get("char_pins") or {}).get(cid)
    if pin:
        return pin  # 🔎 the engine told the player "TA在那儿" — so they ARE there, waiting
    sched = _char_home(c, int(state.get("act", 1) or 1), active_slot(content, state))
    if sched:
        return sched  # includes AWAY
    pos = _sim_pos_loc(((state.get("char_sim") or {}).get(cid) or {}).get("pos"))
    if pos:
        return pos
    return (locs[0] or {}).get("id")


def _schedule_says_away(content: dict[str, Any], state: dict[str, Any],
                        c: dict[str, Any]) -> bool:
    """作者的班表有没有把【这个钟点】写成"找不到人"。

    问的是作者意图, 不是"人在哪" —— 所以合法直读作息表 (见 _char_home 的豁免名单)。
    为什么要把这一问单独拎出来: char_position 报 AWAY 有两个出处, 后果天差地别 ——
      · 作息 AWAY —— 作者写的班表, 下一个时段自动恢复;
      · 钉子 AWAY —— 「TA走出了这一场, 引擎不知道去了哪」, 而这颗钉子【永不释放】
        (_drop_pins_on_leave 只摘等于旧地点的钉子; 自愈只认台上台词, 可离场的人根本不上台)。
    把后者也当成"关机", 角色说一句「我先走了」就此电话永久打不通 (2026-07-30 评审实跑抓到)。
    """
    return _char_home(c, int(state.get("act", 1) or 1),
                      active_slot(content, state)) == AWAY


def apply_char_move(content: dict[str, Any], state: dict[str, Any], name_ref: str,
                    dest_ref: str) -> dict[str, Any] | None:
    """Book a model-requested NPC move. The mover must be a LIVING character standing in
    the player's scene (the model just narrated them setting off), not following, and
    not owned by an authored 作息 for this hour; the destination must be a real authored
    place. Returns {name, to_name} or None when refused."""
    # 🔒 模型不许靠一句旁白把 NPC 挪走 (LLM_MAP_WRITES)。谁在哪, 交回作者作息表 +
    # char_position 的级联去答。
    if not LLM_MAP_WRITES:
        return None
    name_ref = (name_ref or "").strip()
    if not name_ref:
        return None
    mover = next((c for c in scene_characters(content, state)
                  if c.get("id") != state.get("player_character_id") and c.get("name")
                  and (c["name"] == name_ref or c["name"] in name_ref or name_ref in c["name"])),
                 None)
    if not mover or mover.get("id") in (state.get("following") or []):
        return None
    # 🔒 作息【所有权】问句, 不是"人在哪" — 故意直读 _char_home (见其 docstring 豁免名单)
    if _char_home(mover, int(state.get("act", 1) or 1), active_slot(content, state)):
        return None  # the author's schedule owns this character's feet
    dest = resolve_location(content, dest_ref)
    if not dest or not dest.get("id") or dest["id"] == state.get("location_id"):
        return None
    _sim(state, mover["id"])["pos"] = dest["id"]
    # 🎬 明确落账的离场压过陈钉 (审查实锤: 场账本开场把全 cast 钉在场址, npc_moves
    # booked 后审计记✓、三面人却纹丝不动 — 钉子在 char_position 里排 sim 之前)。
    # 场账本合同本就写明「剧情走戏不受限」— booked 即拔钉, cast 同步摘人。
    pins = state.get("char_pins") or {}
    if mover["id"] in pins:
        pins = dict(pins)
        pins.pop(mover["id"])
        state["char_pins"] = pins
    sl = _sl(state)
    if sl:
        sl["cast"] = [c for c in (sl.get("cast") or []) if c != mover["id"]]
    return {"id": mover.get("id"), "name": mover.get("name"), "to_name": dest.get("name")}


# graded life state: absent = healthy; "hurt" walks and talks; "dying" is one breath
# from the ledger — and the ONLY state a death can strike from (two-stage deaths).
_HP_LABEL = {"hurt": "带着伤", "dying": "重伤濒死"}


def char_hp(state: dict[str, Any], cid: str | None) -> str:
    if cid in _dead_ids(state):
        return "dead"
    return ((state.get("char_sim") or {}).get(cid) or {}).get("hp") or "healthy"


def char_items(content: dict[str, Any], state: dict[str, Any], cid: str) -> list[dict[str, Any]]:
    """A character's CURRENT possessions (lazily seeded from their authored items).
    These are real objects in the world: they can be gifted, snatched, or traded."""
    sim = _sim(state, cid)
    if "items" not in sim:
        c = _char_by_id(content, cid)
        sim["items"] = [dict(i) for i in ((c or {}).get("items") or []) if i.get("name")]
    return sim["items"]


def _scene_tag(state: dict[str, Any]) -> str:
    """当前这场戏的指纹 (没开场就是空)。用来分辨「上一场」与「这一场」。"""
    sl = state.get("scene_ledger")
    if not isinstance(sl, dict) or not sl.get("open"):
        return ""
    o = sl.get("opened") or {}
    return f"{sl.get('loc') or ''}|{o.get('day')}|{o.get('slot')}"


def _carried_mood(state: dict[str, Any], cid: str | None) -> str:
    """🎭 the emotional state the LAST scene left this character in — carried into the
    next one unless a full day has passed (time cools most things).

    ⚠️ 只在【换场】时给 (Yi 2026-08-04 实弹: 📟 连着四个回合一模一样)。收下这条的
    提示词写的是「上一场戏散场时，你心里是X——这股情绪还没散」; 同一场戏里每一拍都
    这么说一遍, 模型就把 X 原样报回来, 再被存回去 —— 一个自己喂自己的环。
    同场之内本来也不需要: 这一场发生了什么, 模型的上下文里就摆着。
    """
    m = ((state.get("char_sim") or {}).get(cid) or {}).get("mood") or {}
    if not m.get("text"):
        return ""
    if _time_index(state) - int(m.get("at", 0)) > len(SLOTS):
        return ""  # a day later, the edge has dulled
    cur = _scene_tag(state)
    if cur and m.get("scene") == cur:
        return ""  # 这股情绪就是【本场】刚生出来的, 别再讲给它自己听
    return m["text"]


def set_char_hp(state: dict[str, Any], cid: str, hp: str | None) -> None:
    sim = _sim(state, cid)
    if hp:
        sim["hp"] = hp
    else:
        sim.pop("hp", None)


def char_agenda(content: dict[str, Any], state: dict[str, Any],
                c: dict[str, Any]) -> dict[str, Any]:
    """🎯 the character's ENGINE-OWNED living goal ledger (角色卡 v2): what they're
    trying to get done (`goal`, seeded from authored life_goal/wants), which `stage`
    of it they're at, the current `obstacle`, the latest `step`, and a short `log` of
    stage turns. The world runs on rules, not vibes: an NPC's life between scenes is
    this record, not a fresh dice roll. 「人生当前目标」是活的 — stage 会走, 目标会办成."""
    sim = _sim(state, c.get("id"))
    ag = sim.get("agenda")
    if not isinstance(ag, dict):
        lg = c.get("life_goal") if isinstance(c.get("life_goal"), dict) else {}
        ag = {"goal": str(lg.get("text") or c.get("wants") or c.get("agenda") or "").strip(),
              "stage": str(lg.get("stage") or "").strip(),
              "obstacle": str(lg.get("obstacle") or "").strip(),
              "step": "", "log": []}
        sim["agenda"] = ag
    ag.setdefault("stage", "")
    ag.setdefault("obstacle", "")
    ag.setdefault("log", [])
    return ag


def agenda_advance(state: dict[str, Any], c: dict[str, Any],
                   stage: str = "", obstacle: str = "", step: str = "") -> None:
    """Book progress on a character's life goal (模型申报/心跳推进 → 引擎落账).
    A changed stage lands in the log — 办成一件事是这个世界真发生过的历史."""
    ag = char_agenda({}, state, c)
    ti = _time_index(state)
    if step:
        ag["step"], ag["at"] = str(step)[:60], ti
    if obstacle:
        ag["obstacle"] = str(obstacle)[:40]
    ns = str(stage or "").strip()[:40]
    if ns and ns != ag.get("stage"):
        log = list(ag.get("log") or [])
        log.append({"t": ti, "stage": ns})
        ag["stage"], ag["log"] = ns, log[-8:]
        _audit(state, "agenda.stage", True, f"{c.get('name','')}→{ns[:20]}")


def _agenda_prompt(content: dict[str, Any], state: dict[str, Any], c: dict[str, Any]) -> str:
    """The agenda as one prompt line: goal + stage + obstacle + the latest step."""
    ag = char_agenda(content, state, c)
    bits = []
    if ag.get("goal"):
        bits.append(ag["goal"])
    if ag.get("stage"):
        bits.append(f"进行到：{ag['stage']}")
    if ag.get("obstacle"):
        bits.append(f"卡在：{ag['obstacle']}")
    if ag.get("step"):
        bits.append(f"最近的动静：{ag['step']}")
    return "；".join(bits)


def _is_here(c: dict[str, Any], state: dict[str, Any], cur_loc_id: str | None,
             content: dict[str, Any] | None = None) -> bool:
    """Is this character in the player's CURRENT scene? Their tracked position must BE
    this place. Mapless stories keep the legacy everyone-everywhere behavior."""
    cid = c.get("id")
    if cid and cid in (state.get("following") or []):
        return True
    pos = char_position(content or {}, state, c)
    if pos is None:
        return True
    if pos == AWAY:
        return False
    return cur_loc_id == pos


def scene_characters(content: dict[str, Any], state: dict[str, Any]) -> list[dict[str, Any]]:
    """Present (entered this act, not offstage) AND in the player's current scene
    (at their location or following). This is "who the player can actually interact with
    right now" — the explore→encounter spine."""
    act = int(state.get("act", 1))
    # resolve the effective location (None → the opening/first place, as current_location does)
    cur = current_location(content, state)
    cur_id = cur.get("id") if cur else state.get("location_id")
    return [c for c in present_characters(content, act, _dead_ids(state))
            if _is_here(c, state, cur_id, content)]


def playable_roles(content: dict[str, Any]) -> list[dict[str, Any]]:
    """Characters the player may EMBODY (character mode). Those explicitly flagged
    `playable` win; if a story flags none (legacy), fall back to every character present
    from the opening act — so old stories keep letting you pick any role."""
    chars = _characters(content)
    flagged = [c for c in chars if c.get("playable")]
    if flagged:
        return flagged
    return [c for c in chars if _is_present(c, 1)]


def cast_for(content: dict[str, Any], act: int, exclude_id: str | None = None,
             state: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """The addressable cast at this act (offstage/not-yet-arrived/dead excluded). In
    character mode `exclude_id` drops the embodied character (you don't talk to self)."""
    return [
        {"id": c.get("id"), "name": c.get("name"), "role": c.get("role") or "",
         "is_lead": c.get("is_lead", False), "avatar_url": c.get("avatar_url")}
        for c in present_characters(content, act, _dead_ids(state or {}))
        if c.get("id") != exclude_id
    ]


def _physical_roster(content: dict[str, Any], state: dict[str, Any], persona: dict[str, Any]) -> str:
    """Deterministic 'who is physically present right now', so the model never miscounts
    nor writes the player out of the scene. General: derived purely from the roster +
    presence flags, works for any story. Offstage/supernatural characters are listed
    separately as NOT counted among the living."""
    act = int(state.get("act", 1))
    mode = state.get("mode") or "character"
    en = lang_of(content) == "en"
    pcid = state.get("player_character_id")
    present = scene_characters(content, state)  # only who is in THIS scene right now
    hp_label = ({"hurt": "wounded", "dying": "gravely wounded"} if en else _HP_LABEL)
    living = []
    for c in present:
        if not c.get("name") or c.get("id") == pcid:
            continue
        tag = hp_label.get(char_hp(state, c.get("id")))
        # 🎭 卡 v2: 性别随名单走 — 他/她、哥/姐从卡上来, 不再让模型从名字猜
        g = (c.get("gender") or "").strip()
        living.append(c["name"] + (f"（{g}）" if g and not en else "")
                      + ((f" ({tag})" if en else f"（{tag}）") if tag else ""))
    # the player is a body in the scene (except in god/observer mode)
    if mode == "god":
        player_label = None
    else:
        pc = _char_by_id(content, pcid) if pcid else None
        player_label = (pc.get("name") if pc else (persona or {}).get("name")) or ("you" if en else "你")
    names = (([f"{player_label} (you)"] if en else [f"{player_label}（你）"]) if player_label else []) + living
    offstage = [c.get("name") for c in _characters(content)
                if (c.get("presence") or "present") == "offstage" and c.get("name")]
    lines: list[str] = []
    sep = ", " if en else "、"
    # 🧍 姿位: engine-tracked pose + spot inside THIS room (fresh entries only — an entry
    # booked in another location is stale and ignored). Rides the SAME first line as the
    # headcount, because the depth-0 anchor keeps only the roster's first line.
    lid = state.get("location_id")
    pose_bits: list[str] = []
    if mode != "god":
        pp = state.get("player_pos")
        if isinstance(pp, dict) and pp.get("at") == lid and ((pp.get("text") or "").strip() or pp.get("wear")):
            _pt = (pp.get("text") or "").strip() + (f"·着{pp['wear']}" if pp.get("wear") else "")
            pose_bits.append(("you: " if en else "你：") + _pt)
    for c in present:
        if not c.get("name") or c.get("id") == pcid:
            continue
        p = (state.get("char_sim", {}) or {}).get(c.get("id"), {}).get("pos")
        if isinstance(p, dict) and p.get("at") == lid and ((p.get("text") or "").strip() or p.get("wear")):
            _pt = (p.get("text") or "").strip() + (f"·着{p['wear']}" if p.get("wear") else "")
            pose_bits.append(f"{c['name']}: {_pt}" if en else f"{c['name']}：{_pt}")
    pose_line = ""
    if pose_bits:
        pose_line = (
            f" Bodies in the room right now: {'; '.join(pose_bits)}. Frames are "
            "continuous: whoever isn't stated as changing stays exactly where and how they "
            "were, doing what they were doing; nobody teleports, shifts posture, or swaps "
            "activity unwritten. Whether the player asks, looks or acts, this sheet is the "
            "single truth."
            if en else
            f"　此刻各自的姿位与手上的事：{'；'.join(pose_bits)}。姿位有连续性："
            "上面没写变化的人保持原姿势原位置、继续做原来的事；人不会凭空换姿势、"
            "瞬移，也不会凭空换一件事做。无论玩家是问、是看还是做，这份现场状态都是同一份事实。")
    if names:
        lines.append(
            (f"Physically present in this scene right now: {sep.join(names)}. That's "
             f"{len(names)} in total. This number is exact: never miscount, never recount, "
             "and never write the player out of the scene."
             if en else
             f"此刻这个场景里实际在场的人：{'、'.join(names)}——共 {len(names)} 人。"
             "这个数字是确定的：不要数错、不要重算，也绝不要把“你”（玩家）自己漏掉或排除在外。")
            + pose_line
        )
    if offstage:
        lines.append(
            f"The following are NOT living people in the scene. They appear only in mirrors, "
            f"shadows, or rumor. Never count them among those present, and never let them "
            f"join a conversation like a normal person: {sep.join(offstage)}."
            if en else
            f"以下并不是在场的活人，只会出现在镜中、暗处或传闻里——永远不要把 TA 算进在场人数，"
            f"也不要让 TA 像普通人一样正常参与对话：{'、'.join(offstage)}。"
        )
    if names:
        # 🎭 the headcount pins NAMED cast only — it must not sterilize the scene of the
        # nameless extras a real place would have (waiters, guards, passers-by)
        lines.append(
            "That headcount covers NAMED characters only. The nameless extras this place "
            "would naturally have (a waiter, guards, passers-by) do exist as scenery and "
            "may act in narration."
            if en else
            "上面的人数只统计有名有姓的角色。这个地方按常理该有的无名之辈"
            "（伙计、卫兵、路人、杂兵）是存在的，可以作为布景在旁白里活动。"
        )
    return "\n".join(lines)


# ── Physical place (spatial anchor) ──────────────────────────────────────────
# Stories MAY author a list of concrete locations. When they do, we track which place the
# player is currently in and inject its concrete fixtures + exits into every prompt, so the
# narration stays grounded ("you are in X, you can see/reach Y, you can go to Z") instead of
# drifting through vague atmosphere or teleporting people around. Stories with no authored
# locations keep the looser world_facts-only behavior (place block is simply omitted).
def _locations(content: dict[str, Any]) -> list[dict[str, Any]]:
    return (content.get("story") or {}).get("locations") or []


def _location_by_id(content: dict[str, Any], lid: str | None) -> dict[str, Any] | None:
    if not lid:
        return None
    for loc in _locations(content):
        if loc.get("id") == lid:
            return loc
    return None


def resolve_location(content: dict[str, Any], ref: str | None) -> dict[str, Any] | None:
    """Match a free-text reference (an id, an exact name, or a name the model wrote) to an
    authored location. Used to apply the director's 地点 movement marker safely — an
    unrecognized place is ignored, so the model can never invent a room out of nowhere."""
    if not ref:
        return None
    ref = ref.strip()
    locs = _locations(content)
    for loc in locs:  # exact id or name first
        if loc.get("id") == ref or loc.get("name") == ref:
            return loc
    for loc in locs:  # then a lenient containment match on the name
        name = loc.get("name") or ""
        if name and (name in ref or ref in name):
            return loc
    return None


def _lcs_len(a: str, b: str) -> int:
    """Longest common substring length (short CJK names — O(n·m) is nothing)."""
    if not a or not b:
        return 0
    best = 0
    for i in range(len(a)):
        j = i + best + 1
        while j <= len(a) and a[i:j] in b:
            best = j - i
            j += 1
    return best


_EN_STOP = {"the", "a", "an", "of", "at", "to", "in", "on", "and", "or", "by",
            "for", "with", "my", "our", "your", "their", "his", "her", "its",
            "old", "new", "little", "quiet"}


def _en_words(s: str) -> list[str]:
    """英文地名的实词 (去冠词/介词/常见修饰) — 词级亲缘判定用。"""
    return [w for w in re.findall(r"[a-z']+", (s or "").lower()) if w not in _EN_STOP]


def near_location(content: dict[str, Any], ref: str | None) -> dict[str, Any] | None:
    """近亲地点: 只用在「要不要造新地点」的判定上 — 玩家口头的简称对全名时精确/包含
    匹配都会漏, 差点铸出重复的幽灵地点; 硬移动仍走严格 resolve_location:
    宁可改道给玩家确认真名, 不可默默把人带错地方。
    尺按语言分 (第二刀实测: 字符级 LCS≥2 对 CJK 是信号, 对英文全是噪音 — Golden Hour
    12 组邀约 0 正确, "Elias's trailer" 被认成 Taverna 的亲戚):
      zh = 连续 ≥2 字重合;  en = 共享 ≥1 个实词 (大小写归一, 冠词修饰不算)。"""
    ref = (ref or "").strip()
    if len(ref) < 2:
        return None
    if lang_of(content) == "en":
        rw = set(_en_words(ref))
        if not rw:
            return None
        best, best_n = None, 0
        for loc in _locations(content):
            n = len(rw & set(_en_words(loc.get("name") or "")))
            if n > best_n:
                best, best_n = loc, n
        return best if best_n >= 1 else None
    best, best_n = None, 1
    for loc in _locations(content):
        n = _lcs_len(ref, loc.get("name") or "")
        if n > best_n:
            best, best_n = loc, n
    return best if best_n >= 2 else None


def current_location(content: dict[str, Any], state: dict[str, Any]) -> dict[str, Any] | None:
    """Where the player is now. Defaults to the first authored location if unset."""
    locs = _locations(content)
    if not locs:
        return None
    return _location_by_id(content, state.get("location_id")) or locs[0]


def location_available(content: dict[str, Any], state: dict[str, Any], loc: dict[str, Any] | None) -> bool:
    """Is this place reachable yet? A location stays hidden until its unlock conditions are
    met (act reached, affinity floor, required info uncovered) — so exits only appear once the
    player has learned the place exists THIS act. Empty unlock = always available."""
    if not loc:
        return False
    u = loc.get("unlock") or {}
    if int(state.get("act", 1)) < int(u.get("act_min") or 0):
        return False
    if int(state.get("affinity", 0)) < int(u.get("affinity_min") or 0):
        return False
    if not set(u.get("required_fragment_ids") or []) <= set(state.get("unlocked_fragment_ids") or []):
        return False
    return True


def location_view(content: dict[str, Any], state: dict[str, Any]) -> dict[str, Any] | None:
    """The current place for the UI, with its exits filtered to only the destinations that
    are currently UNLOCKED — locked places simply don't appear as options yet."""
    loc = current_location(content, state)
    if not loc:
        return None
    avail = []
    for name in (loc.get("exits") or []):
        dest = resolve_location(content, name)
        if dest and location_available(content, state, dest):
            avail.append(name)
    return {**loc, "exits": avail}


def _finish_audit(state: dict[str, Any], moments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Close the turn's audit sheet: accepted events are derived from `moments` (they are
    the accept-log already), appended after the inline rejections. Returns the full sheet."""
    log = list(state.get("last_audit") or [])
    seen = {(e.get("e"), e.get("data")) for e in log}
    for m in moments or []:
        kind = m.get("kind", "")
        data = str(m.get("name") or m.get("text") or m.get("title") or m.get("what") or "")[:60]
        if m.get("verb"):
            kind = f"{kind}.{m['verb']}"
        if (kind, data) not in seen:
            log.append({"e": kind, "ok": True, **({"data": data} if data else {})})
    state["last_audit"] = log[-40:]
    return state["last_audit"]


def _audit(state: dict[str, Any], kind: str, ok: bool, data: str = "", why: str = "") -> None:
    """📋 per-turn event audit: every model-reported or engine-detected event lands here as
    accepted or REJECTED (with the reason). Accepted entries are also derived from `moments`
    at turn end; this call is mainly for rejections — the silent drops playtesters used to
    puzzle over ("我明明收下了短刃"). Kept small: last 40 entries of the current turn."""
    log = state.setdefault("last_audit", [])
    log.append({"e": kind, "ok": bool(ok),
                **({"data": str(data)[:60]} if data else {}),
                **({"why": str(why)[:60]} if why else {})})
    del log[:-40]


def _drop_pins_on_leave(state: dict[str, Any], old_lid: str | None) -> None:
    """🔎 a pinned meeting is honored until the player LEAVES that place — walking away
    releases the character back to their own schedule."""
    pins = state.get("char_pins") or {}
    if old_lid and pins:
        kept = {k: v for k, v in pins.items() if v != old_lid}
        if len(kept) != len(pins):
            state["char_pins"] = kept
    _sl_close(state)   # 🎬 真实换场 = 收场 (本函数是全引擎移动成立的公共窄口)


# ── 🎬 场账本 (docs/scene-ledger.md, Yi 2026-08-01 拍板「中切」) ──────────────
# 「场」= 一段连续虚构时间 + 固定参与者 + 一件正在进行的事。此前引擎只有世界层
# (时钟/作息/压力) 和回合层 (beats), 虚构连续性只活在上下文里 — 显式状态永远赢过
# 隐式虚构, 漏出三怪相: 邀约中被作息蒸发/语义重演/长谈跨时段。两本账两个寿命:
# 动作账 spent 跟场走 (收场即弃), 问答账 asked_log 跟天走 (换了地方也不许再问)。
# 让位规则 a 用现成钉子实现: 开场把 cast 钉在场址 — 钉子在 char_position 判定链里
# 天然压过作息, 又天然被 濒死/威胁/被掳 压过, 危机泄压阀是位置链白送的。

def _sl(state: dict[str, Any]) -> dict[str, Any] | None:
    sl = state.get("scene_ledger")
    return sl if isinstance(sl, dict) and sl.get("open") else None


def _sl_open(state: dict[str, Any], loc_id: str | None,
             cast_ids: list[str], clk: dict[str, Any]) -> None:
    pins = state.setdefault("char_pins", {})
    mine = [cid for cid in cast_ids if cid and cid not in pins]
    for cid in mine:
        pins[cid] = loc_id   # 「正在陪你」落成显式状态 — 作息从此拉不走TA
    state["scene_ledger"] = {
        "open": True, "loc": loc_id, "cast": [c for c in cast_ids if c],
        "opened": {"day": int(clk.get("day", 1) or 1), "slot": int(clk.get("slot", 0) or 0)},
        "spent": [], "ticks": 0, "turns": 0, "pins": mine}


def _sl_close(state: dict[str, Any]) -> None:
    sl = _sl(state)
    if not sl:
        return
    pins = state.get("char_pins") or {}
    for cid in sl.get("pins") or []:
        if pins.get(cid) == sl.get("loc"):
            pins.pop(cid, None)   # 只拔自己钉的钉 — 约定钟点的钉不归场管
    # ⏳ 时钟补拨: 场内凝滞吸掉的格一次性还上 (世界不欠账; real_time 从不欠)
    for _ in range(int(sl.get("ticks") or 0)):
        clk = dict(state.get("clock") or {})
        clk.setdefault("day", 1)
        clk.setdefault("slot", 0)
        clk["slot"] = int(clk["slot"]) + 1
        if clk["slot"] >= len(SLOTS):
            clk["slot"], clk["day"] = 0, int(clk["day"]) + 1
        clk["turns_in_slot"] = 0
        state["clock"] = clk
    state["scene_ledger"] = None


def _asked_view(state: dict[str, Any]) -> dict[str, Any] | None:
    """问答账的提示词切片: 已答的不许换措辞再问, 未答的可追但别抛新钩。"""
    log = state.get("asked_log") or []
    if not log:
        return None
    return {"answered": [{"q": a.get("q"), "a": a.get("a")} for a in log if a.get("a")][-4:],
            "open": [a.get("q") for a in log if not a.get("a")][-3:]}


def _sl_settle(content: dict[str, Any], state: dict[str, Any], tun: dict[str, Any],
               all_beats: list[dict[str, Any]], player_input: str, flags: dict[str, Any],
               channel: str, pcid: str | None) -> None:
    """回合落账: 申报优先 (编剧 plan 的 spent/asked/answered), 确定性兜底; 零 LLM。
    旗关着时只负责把残留的场收干净 (中途关旗不留永生账)。"""
    if not tun.get("scene_ledger"):
        if _sl(state):
            _sl_close(state)
        return
    day_now = int((state.get("clock") or {}).get("day", 1) or 1)
    # 问答账 (跟天走): 过期先清 (day+2)
    log = [a for a in (state.get("asked_log") or [])
           if isinstance(a, dict) and int(a.get("day") or 0) + 2 >= day_now]
    pin_txt = (player_input or "").strip()
    if pin_txt and channel in ("say", "do"):
        # answered: 申报能对上就结申报那条; 否则最旧未答者结在玩家原话上
        ans = str(flags.get("scene_answered") or "").strip()
        tgt = None
        if ans:
            tgt = next((a for a in log if not a.get("a")
                        and (ans[:4] in str(a.get("q") or "") or str(a.get("q") or "")[:4] in ans)), None)
        if tgt is None:
            tgt = next((a for a in log if not a.get("a")), None)
        if tgt is not None:
            tgt["a"] = (ans or pin_txt)[:12]
    q = str(flags.get("scene_asked") or "").strip()
    # 申报要对得上正文 (实操实弹 2026-08-01: plan 先于散文申报「问什么」, 渲染拍改道后
    # 账本记下一个从没问出口的问题) — 台词里找不着就驳回, 走兜底; 兜底也没有就宁漏。
    if q:
        _dlg = " ".join((b.get("text") or "") for b in all_beats
                        if b.get("type") == "dialogue")
        if q[:4] not in _dlg and q.rstrip("？?吗呢")[:4] not in _dlg:
            q = ""
    if not q:   # 兜底: 主答台词以问号收尾 → 取末句提炼
        for b in reversed(all_beats):
            if b.get("type") == "dialogue" and (b.get("text") or "").rstrip().endswith(("？", "?")):
                t = (b.get("text") or "").rstrip("？? ")
                q = t.replace("\n", "").split("。")[-1].split("，")[-1][-12:]
                break
    if q and all(q != str(a.get("q") or "") for a in log):
        log.append({"q": q[:12], "a": None, "day": day_now})
    state["asked_log"] = log[-12:]
    # 场: 开 / 更新 / 收
    sl = _sl(state)
    if sl:
        sl["turns"] = int(sl.get("turns") or 0) + 1
        here_ids = {c.get("id") for c in scene_characters(content, state) if c.get("id")}
        sl["cast"] = [c for c in (sl.get("cast") or []) if c in here_ids]
        spent = str(flags.get("scene_spent") or "").strip()
        if spent and spent not in (sl.get("spent") or []):
            sl.setdefault("spent", []).append(spent[:12])
            sl["spent"] = sl["spent"][-10:]
        # 收场条件: 人走净 / 场龄超限 (防永生) / 地点已变 (移动窄口没兜住的兜底)
        if not sl["cast"] or sl["turns"] > 24 or state.get("location_id") != sl.get("loc"):
            _sl_close(state)
    elif pin_txt and channel in ("say", "do") \
            and any(b.get("type") == "dialogue" for b in all_beats):
        cast = [c.get("id") for c in scene_characters(content, state)
                if c.get("id") and c.get("id") != pcid]
        if cast:
            _sl_open(state, state.get("location_id"), cast, state.get("clock") or {})


def commit_move(content: dict[str, Any], state: dict[str, Any], dest: dict[str, Any],
                lead_id: str | None = None) -> dict[str, Any]:
    """🚪 全引擎【玩家真实换场】唯一写入口 (2026-08-03 地图深查后写侧收口)。
    原子做三件事: 拔旧钉+收场账本 → 写位置 → 钉带路人 (内部挡玩家自己)。
    原地不算换场 — 不拔钉不收场 (没换场就没收场)。
    读侧当年收口成 char_position 后同类 bug 绝迹; 写侧五次同型遗漏 (generate_and_move
    三处/fate 生成/猎手押送 忘拔钉, moved_to 生成路丢带路人) 证明配套动作靠人记不住。
    守卫: test_move_gate 用 AST 禁止白名单外直写 location_id/char_pins。"""
    old = state.get("location_id")
    did = dest.get("id")
    if did and did != old:
        _drop_pins_on_leave(state, old)
        state["location_id"] = did
        if lead_id and lead_id != state.get("player_character_id"):
            # 带路的人一起走 (pin, 玩家离开自动释放) — 不然人留在原地话在新地
            state.setdefault("char_pins", {})[lead_id] = did
    return dest


def settle_prose_arrival(content: dict[str, Any], state: dict[str, Any],
                         all_beats: list[dict[str, Any]], loc0_id: str | None,
                         sp_id: str | None = None) -> bool:
    """🧭 文实合一的确定性兜底 (实弹: 细辉带你下楼进了祥记, 旁白全写完了,
    位置账本却钉在天台): 模型忘了申报 moved_to, 但旁白把人写到了另一处【已知】
    地点门口 — 回合末扫描收账。规矩: 只认唯一命中 + 落地动词 + 可达路线;
    歧义/不可达只记审计不动账。带路的说话者一起挪 (pin, 玩家离开自动释放)。"""
    import re as _re
    # 🔒 旁白也算对话 (LLM_MAP_WRITES): 模型把人"写"到了别处不作数, 换场只认玩家自己走。
    if not LLM_MAP_WRITES:
        return False
    if not loc0_id or state.get("location_id") != loc0_id:
        return False       # 本回合已有真移动 (硬移动/moved_to), 不重复记账
    txt = "。".join((b.get("text") or "") for b in all_beats
                    if b.get("type") == "description")
    if not txt:
        return False
    hits = []
    for loc in _locations(content):
        nm = (loc.get("name") or "").strip()
        if len(nm) < 3 or loc.get("id") == loc0_id or nm not in txt:
            continue
        i = txt.find(nm)
        around = txt[max(0, i - 10): i + len(nm) + 10]
        if _re.search(r"(到了|来到|进了|走进|踏进|拐进|停在|刹住|站定)", around)                 or _re.search(_re.escape(nm) + r"(门前|门口|档口|里|内)", around):
            hits.append(loc)
    if len(hits) != 1:
        if hits:
            _audit(state, "move.prose", False, "多地点歧义")
        return False
    dest = hits[0]
    if not (location_available(content, state, dest)
            and _route_exists(content, state, loc0_id, dest.get("id"))):
        _audit(state, "move.prose", False, str(dest.get("name")), "不可达或未解锁")
        return False
    commit_move(content, state, dest, lead_id=sp_id)   # 带路的人不能留在原地
    _audit(state, "move.prose", True, str(dest.get("name")))
    return True


def apply_move(content: dict[str, Any], state: dict[str, Any], dest_ref: str) -> dict[str, Any]:
    """Move the player to an authored location reachable from where they are — directly
    connected, or a few hops away through unlocked exits (the walk is implied). Characters
    currently following the player come along automatically (they stay in `following`, so
    they're still 'here' at the new place). Returns the new location dict.
    Raises ValueError if the destination is unknown or not connected to the current place."""
    dest = resolve_location(content, dest_ref)
    if not dest or not dest.get("id"):
        raise ValueError("unknown location")
    if not location_available(content, state, dest):
        raise ValueError("not yet available")  # place not discovered/unlocked yet
    cur = current_location(content, state)
    exits = (cur or {}).get("exits") or []
    # if exits are authored, enforce connectivity (multi-hop through unlocked exits is
    # fine); an isolated/exitless map allows free travel
    if exits and dest.get("name") not in exits and dest.get("id") not in exits \
            and dest.get("id") != (cur or {}).get("id") \
            and not _route_exists(content, state, (cur or {}).get("id"), dest["id"]):
        raise ValueError("not reachable from here")
    return commit_move(content, state, dest)


def ensure_start_location(content: dict[str, Any], state: dict[str, Any],
                          llm: LLM | None = None) -> dict[str, Any] | None:
    """ARCHITECTURAL INVARIANT: every run has a 'current location', so the whole spatial system
    (place anchor, movement, EMERGENT locations) works for EVERY story — not only the ones that
    authored a map. If the story authored no locations, synthesize a starting one from its
    opening setting and pin the player there. Mutates content + state (caller persists content).
    Called at run creation (policy layer); the engine itself stays location-agnostic so a raw
    run_turn_stream on a map-less story still behaves as before."""
    if _locations(content):
        loc = current_location(content, state)
        if loc and loc.get("id"):
            state["location_id"] = loc["id"]
        return loc
    # 🔒 无图剧本不再凭空造开场地点 (LLM_MINTS_PLACES) —— 那是"有哪些地方", 不是"谁在哪"。
    # 退回 char_position 早就支持的无地图模式: 没有地点概念, 谁也不"在哪",
    # 纯对话推进 (legacy behavior, 不是新分支)。
    if not LLM_MINTS_PLACES:
        return None
    story = content.get("story") or {}
    world = story.get("world_facts") or story.get("world_long") or ""
    act1 = current_act(content, 1) or {}
    setting = " ".join([act1.get("title", "")]
                       + [e.get("what_happens", "") for e in (act1.get("events") or [])]).strip()
    out: dict[str, Any] = {}
    try:
        # 🌐 语言戳必须裹上 (第二刀实锤: 没裹 lang_llm, EN 无图剧本开局必产中文地名)
        out = lang_llm(llm or get_llm(), content).generate(
            {"start_place": True, "world": world, "setting": setting}) or {}
    except Exception:
        out = {}
    name = (out.get("name") or "").strip() \
        or ("here" if lang_of(content) == "en" else "此处")
    detail = (out.get("detail") or "").strip()
    import uuid as _uuid
    # unique per run: generated places get their own AI background image cached by id,
    # so two different worlds must never share a "loc_start" face
    lid = "loc_start_" + _uuid.uuid4().hex[:8]
    loc = {"id": lid, "name": name, "detail": detail, "exits": [], "unlock": {}, "generated": True}
    story.setdefault("locations", []).append(loc)
    content["story"] = story
    state["location_id"] = lid
    return loc


def _music_worker(llm: LLM, payload: dict[str, Any], box: dict[str, Any]) -> None:
    try:
        box["out"] = llm.generate(payload) or {}
    except Exception:
        box["out"] = {}


def settle_music(state: dict[str, Any], mj: dict[str, Any] | None) -> dict[str, Any]:
    """🎼 乐师收卷 (Yi 2026-07-22: 高精度观察情绪切 BGM): 报审入账 —
    曲名过白名单; 迟滞防抽风: 无转折 (pivot 0) 至少稳两回合才许换曲,
    明显转折 (pivot≥1) 立刻切。返回 {track, feel} 给 direct 装配用。"""
    from .director import BGM_TRACKS
    led = state.setdefault("bgm_led", {"track": "", "held": 0})
    track = str((mj or {}).get("track") or "").strip()
    try:
        pivot = max(0, min(2, int((mj or {}).get("pivot") or 0)))
    except (TypeError, ValueError):
        pivot = 0
    if track and track in BGM_TRACKS and track != led.get("track"):
        # 空账必收 (首拍没有可延续的曲目); 之后无转折至少稳两回合
        if not led.get("track") or pivot >= 1 or int(led.get("held", 0)) >= 2:
            led["track"], led["held"] = track, 0
    led["held"] = int(led.get("held", 0)) + 1
    return {"track": str(led.get("track") or ""), "feel": str((mj or {}).get("feel") or "")[:8]}


# 🎭 基调锚 (Yi 2026-07-28 实弹: 暧昧戏里玩家撒娇「错过今天就没机会了，蓝少」，模型被
# 「错过/机会/跨过线」的字面狠劲带偏，回了一句地盘警告，当场从调情翻成翻脸)。
# 根因与声纹/背包同族: 基调引擎早就算准了 (乐师判词带迟滞, 已反哺台词形状), 但那句话
# 埋在系统提示词第 400 行, 隔着上万字符; 且它写的是【句子形状】不是【情绪立场】。
# 做法: 把基调连同已持续拍数当【事实】贴到生成点, 只在软基调下附一句延续默认值 —
# 紧张/战斗/诡异下狠话就该按字面读, 不许也当撒娇。
_SOFT_TONES = {"romantic": "暧昧", "warm": "温情", "daily": "轻松日常",
               "lonely": "静", "sad": "低落"}


def tone_anchor(state: dict[str, Any], zh: bool = True) -> str:
    """本轮基调事实 (空 = 硬基调或还没稳住, 不发)。"""
    led = state.get("bgm_led") or {}
    key = str(led.get("track") or ((state.get("scene") or {}).get("mood") or "")).rstrip("23456789")
    label = _SOFT_TONES.get(key)
    held = int(led.get("held", 0) or 0)
    if not label or held < 2:
        return ""       # 硬基调按字面读; 刚起头的软基调还没成"已建立的基调"
    if not zh:
        return (f"[Scene register: {key}, held for {held} beats. Read a menacing-sounding "
                f"line from them as teasing or testing first, not a real turn — unless "
                f"they actually strike or plainly break it off.]")
    return (f"此刻这场戏的基调是【{label}】，已经连着{held}拍。对方话里若冒出狠话、最后通牒、"
            f"划线一类的字面措辞，先按这个基调读（多半是撒娇、玩笑或试探），别当真翻脸——"
            f"除非TA真动了手或明说要断。")


def _generic_place(nm: str) -> bool:
    """「个地方」「别处」这类泛指碎片 — 不是地名, 不许上地图 (实弹: 「换个地方聊」
    被铸成地点「个地方」)。"""
    nm = (nm or "").strip()
    core = nm.strip("一那这某换找个再的 ")
    return (not nm or nm in _DEICTIC or core in _DEICTIC or core == ""
            or nm.endswith(("地方", "地儿", "去处")))   # 中文地名不会以量词短语结尾


def generate_and_move(content: dict[str, Any], state: dict[str, Any], place_name: str,
                      persona: dict[str, Any] | None = None, llm: LLM | None = None,
                      move: bool = True, invent: bool = False,
                      lead_id: str | None = None) -> dict[str, Any] | None:
    """EMERGENT LOCATION: the player agreed to go somewhere that isn't on the authored map.
    Create that place for real — the model writes a concrete, people-free description grounded
    in the world + where you're coming from — wire it two-way to the current place, append it
    into the run's content (so it's a first-class location from now on), and move the player
    there. Mutates `content` (caller must persist it). Returns the new location dict.

    Idempotent-ish: if the name actually matches a place that already exists, just go there."""
    # 🔒 对话不许铸新场景 (LLM_MINTS_PLACES)。这是全部六条铸造路的共同咽喉 —— 卡在这里
    # 一刀断干净, 不用去八个调用点各补一道闸 (那正是当初闸不统一的由来)。
    if not LLM_MINTS_PLACES:
        _audit(state, "loc.mint", False, (place_name or "")[:12], "对话改地图已关闭")
        return None
    place_name = (place_name or "").strip()
    if not place_name:
        raise ValueError("unknown location")
    existing = resolve_location(content, place_name)
    if existing and existing.get("id"):
        # 🔒 撞名锁定地点 = 驳回 (审查实锤: 免检传送越过解锁门; 提及即立档同样不许
        # 把锁定地点名漏进确认条 — 宁漏勿误杀的对偶: 这里是不许误放)
        if not location_available(content, state, existing):
            _audit(state, "loc.mint", False, place_name[:12], "撞名未解锁地点，驳回")
            return None
        if move:
            commit_move(content, state, existing, lead_id=lead_id)
        return existing
    # 🚧 泛指预筛 (Yi 2026-07-22: 「个地方」上了地图, 这部分走 LLM): 指示代词/泛指
    # 碎片不进 LLM 直接驳回; invent=True (给涌现人物安家) 例外 — 交给模型发明去处
    if _generic_place(place_name) and not invent:
        _audit(state, "loc.mint", False, place_name[:12], "泛指不是去处，驳回")
        return None
    llm = lang_llm(llm or get_llm(), content)
    cur = current_location(content, state)
    story = content.get("story") or {}
    world = story.get("world_facts") or story.get("world_long") or ""
    detail, clean = "", ""
    try:
        dp = llm.generate({"describe_place": True, "place_name": place_name, "world": world,
                           "from_place": (cur or {}).get("name", ""),
                           "invent": bool(invent),
                           "mature": bool(state.get("mature"))}) or {}
        detail = dp.get("detail") or ""
        clean = (dp.get("name") or "").strip()
    except Exception:
        detail = ""
    # 🧑‍⚖️ LLM 是铸造判官 (地名提炼): 原话可能是整句意图（「去河堤上透透气」→「河堤」）,
    # 也可能根本不含具体去处（模型答「无」）。提炼不出干净地名 = 不铸造 —
    # 宁可这回合没有确认条, 不许垃圾上地图。
    if not clean or len(clean) < 2 or _generic_place(clean):
        _audit(state, "loc.mint", False, place_name[:12], "提炼不出具体去处，驳回")
        return None
    final_name = clean
    if clean and clean != place_name:
        existing = resolve_location(content, clean)
        if existing and existing.get("id"):
            if not location_available(content, state, existing):   # 🔒 提炼名同门
                _audit(state, "loc.mint", False, clean[:12], "撞名未解锁地点，驳回")
                return None
            if move:
                commit_move(content, state, existing, lead_id=lead_id)
            return existing
    import uuid
    lid = "loc_gen_" + uuid.uuid4().hex[:8]
    back = [(cur or {}).get("name")] if cur and cur.get("name") else []
    new_loc = {"id": lid, "name": final_name, "detail": detail.strip(),
               "exits": back, "unlock": {}, "generated": True}
    story.setdefault("locations", []).append(new_loc)
    content["story"] = story
    # link current place → new place so the exit shows up (and you can walk back and forth)
    if cur is not None:
        exits = cur.setdefault("exits", [])
        if final_name not in exits:
            exits.append(final_name)
    if move:
        commit_move(content, state, new_loc, lead_id=lead_id)
    return new_loc


def accept_companion(content: dict[str, Any], state: dict[str, Any],
                     name: str) -> dict[str, Any] | None:
    """🚶 对话意向自动同行 (文实不分家): a character verbally agreed IN DIALOGUE to travel
    with the player, so honor it — TA joins `following`, and any later move carries TA
    along. Leniency vs the cold UI invite: the dialogue IS the earning, so we only block
    an ENEMY (a hostility the model shouldn't have had agree). Must be present. Idempotent.
    Returns {name} on a fresh join, None if not applicable (unknown/absent/enemy/already)."""
    nm = (name or "").strip()
    if not nm:
        return None
    char = next((c for c in scene_characters(content, state)
                 if (c.get("name") or "").strip() == nm), None)
    if not char:
        _audit(state, "companion.join", False, nm, "不在场，答应同行不作数")
        return None
    cid = char.get("id")
    if cid in (state.get("following") or []):
        return None
    scores = (state.get("rel") or {}).get(cid) or relationships.new_scores()
    if relationships.derive_mode(char, scores, tuning_for(content)) == "enemy":
        _audit(state, "companion.join", False, nm, "对你满是戒备，不会真跟你走")
        return None
    state["following"] = list(state.get("following") or []) + [cid]
    rel_log(state, cid, int(state.get("act", 1) or 1), "follow",
            _t(content, f"{nm} 答应与你同行。", f"{nm} agreed to come along."))
    _audit(state, "companion.join", True, nm)
    return {"name": nm, "id": cid}


def set_follow(content: dict[str, Any], state: dict[str, Any],
               char_id: str, follow: bool) -> dict[str, Any]:
    """Toggle whether a character travels WITH the player. The character must currently be in
    the player's scene to invite/dismiss, AND (to invite) like the player enough — following
    is EARNED with 好感, not free for a stranger. Returns {ok, following, reason, name}."""
    char = _char_by_id(content, char_id)
    if not char:
        raise ValueError("unknown character")
    here_ids = {c.get("id") for c in scene_characters(content, state)}
    if char_id not in here_ids:
        raise ValueError("character not here")
    following = [c for c in (state.get("following") or []) if c != char_id]
    name = char.get("name") or "对方"
    if follow:
        rel_all = state.get("rel") or {}
        scores = rel_all.get(char_id) or relationships.new_scores()
        tun = tuning_for(content)
        if not relationships.can_follow(char, scores, tun):
            state["following"] = following
            mode = relationships.derive_mode(char, scores, tun)
            reason = _t(content,
                        f"{name}对你满是戒备，不会跟你走。" if mode == "enemy"
                        else f"你和{name}还没熟到那份上。先多聊聊、把关系处近点，TA 才愿意跟你走。",
                        f"{name} doesn't trust you enough to go anywhere with you." if mode == "enemy"
                        else f"You and {name} aren't close enough yet. Talk more, get closer, then ask.")
            return {"ok": False, "following": following, "name": name, "reason": reason}
        following.append(char_id)
        rel_log(state, char_id, int(state.get("act", 1) or 1), "follow",
                _t(content, f"{name} 答应与你同行。", f"{name} agreed to come along."))
    state["following"] = following
    return {"ok": True, "following": following, "name": name, "reason": ""}


def _physical_place(content: dict[str, Any], state: dict[str, Any]) -> str:
    """The 'you are here' block: this place's concrete fixtures + where you can go. Empty
    when the story authored no locations."""
    loc = current_location(content, state)
    if not loc:
        return ""
    en = lang_of(content) == "en"
    name = loc.get("name") or ("here" if en else "此处")
    exits = [e for e in (loc.get("exits") or []) if e]
    props = [p.get("name") for p in (loc.get("props") or []) if p.get("name")]
    stash = [(i.get("name") or "") for i in (state.get("stashes") or {}).get(loc.get("id"), []) if i.get("name")]
    # 🌍 场面事实账本: the world REMEMBERS physical changes booked here (smashed doors
    # stay smashed) — served back so prose can never quietly reset the place
    facts = [(f.get("text") or "")
             for f in (state.get("place_facts") or {}).get(loc.get("id"), []) if f.get("text")]
    # line 1 = the concrete locator (place + fixtures + exits) — this is what the depth
    # anchor reuses, so keep it self-contained and grounded. line 2 = the meta-instruction.
    if en:
        concrete = f"The player is currently at [{name}]."
        if loc.get("detail"):
            concrete += f" Here: {loc['detail']}"
        if exits:
            concrete += f" From here you can go to: {', '.join(exits)}."
        if props:
            concrete += f" Searchable here: {', '.join(props)}."
        if stash:
            concrete += f" Items the player left here earlier: {', '.join(stash)}."
        if facts:
            concrete += f" Changes that already happened here and still hold: {'; '.join(facts)}."
        # 🔒 锁下别再教模型叙写赶路 (半吊子锁收尾, 2026-08-06 实弹): 换场只发生在玩家
        #    点地图之后, 散文写了"到达"引擎也不认, 只会文实分家
        instruction = (
            "Narrate only what actually exists in this place; never invent fixtures from "
            "elsewhere. Changes that already happened are permanent facts and can never be "
            "written back to how they were (a smashed door does not mend itself). "
            + ("To move elsewhere the player must use the listed exits, and the movement "
               "itself must be narrated — no teleporting."
               if LLM_MAP_WRITES else
               "The scene changes only when the player picks a place on the map themselves — "
               "never write the player setting off, travelling, or arriving elsewhere; the "
               "scene stays here until the location actually changes.")
        )
    else:
        concrete = f"此刻玩家所在的地点是【{name}】。"
        if loc.get("detail"):
            concrete += f"这里有：{loc['detail']}"
        if exits:
            concrete += f"　从这里可以去：{'、'.join(exits)}。"
        if props:
            concrete += f"　这里可以翻查：{'、'.join(props)}。"
        if stash:
            concrete += f"　玩家之前存放在这里的东西：{'、'.join(stash)}。"
        if facts:
            concrete += f"　这里已经发生过、至今仍然作数的改变：{'；'.join(facts)}。"
        instruction = (
            "旁白只能描写这个地点里实际存在的东西，不要凭空添置别处的陈设；"
            "已经发生过的改变是既成事实，绝不能写回原样（砸开的门不会自己完好如初）；"
            + ("玩家要移动到别处，必须经由上面列出的通路，且要把移动过程写出来，不能瞬移。"
               if LLM_MAP_WRITES else
               "换场景只由玩家自己在地图上点选——旁白绝不要写玩家启程、赶路或已经到了别处，"
               "地点没变之前，戏始终留在这里写。")
        )
    return concrete + "\n" + instruction


def _char_by_id(content: dict[str, Any], cid: str | None) -> dict[str, Any] | None:
    if not cid:
        return None
    for c in _characters(content):
        if c.get("id") == cid:
            return c
    return None


def _char_name(content: dict[str, Any], cid: str | None) -> str | None:
    c = _char_by_id(content, cid)
    return c.get("name") if c else None


def _secret_char_map(content: dict[str, Any]) -> dict[str, str]:
    return {s.get("id"): s.get("character_id") for s in (content.get("secrets") or [])}


def pick_responder(
    content: dict[str, Any],
    state: dict[str, Any],
    player_input: str,
    target_id: str | None,
    probed_char_ids: list[str],
    chars: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Choose which character answers this turn (the '两者结合' router).

    Priority: explicit @target → a character named in the input → the character
    whose secret is being probed → whoever spoke last → the lead. Keeps per-character
    gating clean (we only ever build context for ONE chosen speaker). `chars` limits the
    candidates to who's actually present this turn (offstage/ghosts excluded)."""
    chars = chars if chars is not None else _characters(content)
    if not chars:
        return None
    by_id = {c.get("id"): c for c in chars}
    # 1. explicit tap / @ (only honoured if that character is present)
    if target_id in by_id:
        return by_id[target_id]
    # 2. a character's name appears in what the player said
    for c in chars:
        name = c.get("name") or ""
        if name and name in (player_input or ""):
            return c
    # 3. the character whose secret the player is probing
    for cid in probed_char_ids:
        if cid in by_id:
            return by_id[cid]
    # 4. continue with whoever spoke last
    if state.get("last_speaker_id") in by_id:
        return by_id[state["last_speaker_id"]]
    # 5. default: the present lead (else the first present character)
    for c in chars:
        if c.get("is_lead"):
            return c
    return chars[0]


def current_act(content: dict[str, Any], act_index: int) -> dict[str, Any] | None:
    for act in (content.get("story") or {}).get("acts", []) or []:
        if int(act.get("index", 0)) == act_index:
            return act
    return None


def _max_act_index(content: dict[str, Any]) -> int:
    acts = (content.get("story") or {}).get("acts", []) or []
    return max((int(a.get("index", 0)) for a in acts), default=0)


def current_goal(content: dict[str, Any], act_index: int) -> str:
    """The player's small objective for this act (authored 🎯 guidance)."""
    a = current_act(content, act_index)
    return (a or {}).get("goal", "") if a else ""


def goal_for(content: dict[str, Any], state: dict[str, Any],
             act_index: int | None = None) -> str:
    """The goal re-centered on WHO the player is. Embodying an authored character with
    their own `wants` shows THEIR agenda (陈妈's goal is not 林晚's; 扮演谁，立场和目标
    就是谁的); everyone else gets the act's authored objective."""
    pc = _char_by_id(content, state.get("player_character_id"))
    if pc and (pc.get("wants") or "").strip():
        return str(pc["wants"]).strip()
    return current_goal(content, act_index if act_index is not None
                        else int(state.get("act", 1) or 1))


# ── 🎯 目标栈 (剧组重建 P0, 治「goal 单槽四写手」) ────────────────────────────
# 幕目标/差事/玩家自立目标各归各层, UI 目标条读栈顶; state["goal"] 只是栈顶镜像
# (客户端零改动)。差事两天不办自动过期 (免得目标条钉着一件旧事)。
_GOAL_RANK = {"player": 4, "errand": 3, "self": 2, "act": 1}  # player=玩家亲手定的, 压过一切
_ERRAND_TTL = 6            # time_index 单位 (一天 3 时段 → 两天)


def player_card(content: dict[str, Any], state: dict[str, Any],
                persona: dict[str, Any] | None) -> dict[str, Any]:
    """🪪 玩家也是一张卡 (剧组 P0, 治「玩家四散」): persona + 五维 + 金手指 +
    档案 facts + 目标栈, 一处归拢 — 导演读玩家和读 NPC 同一姿势。"""
    pc = _char_by_id(content, state.get("player_character_id"))
    return {
        "name": (pc or {}).get("name") or (persona or {}).get("name") or "玩家",
        "gender": (pc or {}).get("gender") or "",
        "persona": ((pc or {}).get("persona_text")
                    or (persona or {}).get("background") or "")[:160],
        "attrs": dict(state.get("attrs") or {}),
        "powers": list(state.get("powers") or [])[:3],
        "facts": profile_mod.facts_of(state),
        "goals": [{"kind": g.get("kind"), "text": g.get("text")}
                  for g in goals_of(state) if g.get("status") == "open"][:3],
        "hp": state.get("player_hp") or "healthy",
    }


# ── 🎬 导演层 (剧组重建 P1): 冲突矩阵 + 场次单 ────────────────────────────────
# 导演每「场」(地点×时段×在场名单) 开一次工, 结果缓存; 引擎备料 (冲突矩阵是
# ties×人生目标的确定性交叉), 模型只做戏剧判断; 没有场次单 = 今天的行为原样。
def conflict_pairs(content: dict[str, Any], state: dict[str, Any]) -> list[dict[str, Any]]:
    """带电的关系 × 双方的人生目标 = 可上演的摩擦/共谋清单 (确定性, 引擎算)。"""
    chars = {c.get("id"): c for c in _characters(content) if c.get("id")}
    dead = _dead_ids(state)
    out = []
    for key, e in (state.get("npc_rel") or {}).items():
        try:
            a_id, b_id = key.split("|", 1)
        except ValueError:
            continue
        if a_id in dead or b_id in dead or a_id not in chars or b_id not in chars:
            continue
        ev = _npc_dirs(e)
        s_ab = int((ev.get("ab") or {}).get("stance") or 0)
        s_ba = int((ev.get("ba") or {}).get("stance") or 0)
        if not (s_ab or s_ba or (ev.get("ab") or {}).get("label")
                or (ev.get("ba") or {}).get("label")):
            continue
        a, b = chars[a_id], chars[b_id]
        ga = char_agenda(content, state, a).get("goal") or ""
        gb = char_agenda(content, state, b).get("goal") or ""
        if not (ga and gb):
            continue
        out.append({"a": a.get("name"), "b": b.get("name"),
                    "a_id": a_id, "b_id": b_id,
                    "label": (ev.get("ab") or {}).get("label")
                    or (ev.get("ba") or {}).get("label") or "",
                    "stance": s_ab if abs(s_ab) >= abs(s_ba) else s_ba,
                    "a_goal": ga[:30], "b_goal": gb[:30]})
    out.sort(key=lambda p: -abs(p["stance"]))
    return out


_BRIEF_CACHE: dict = {}      # 场次键 → brief (主线程读+写入 state; 后台线程只写这里)
_BRIEF_INFLIGHT: set = set()
_BRIEF_CAP = 60


def ensure_scene_brief(content: dict[str, Any], state: dict[str, Any],
                       persona: dict[str, Any], llm: LLM) -> dict[str, Any]:
    """场次单: 每场一次 (缓存按 剧本|地点|时段|在场 键), 导演读全部卡 (含玩家卡) 给出
    {戏眼, 每人心事, 主动权, 暗流}。⚡ 不占关键路径 (实弹: 换场回合 12s 顶在首字前):
    主线程只备料 + 查缓存, 模型调用在后台线程, 算好了下一回合才用。降级为空 = 一切照旧。"""
    roster = [c for c in scene_characters(content, state)
              if c.get("id") and c.get("id") != state.get("player_character_id")
              and c.get("name")]
    if not roster:
        state.pop("scene_brief", None)
        return {}
    # 🔑 场次键必须认「这一局」: 缓存是进程全局的, 同剧本同地点同时段同班底的两局
    # 会撞键 → A 局的戏眼/心事指挥 B 局 (串账, 台账 P1)。state 里发一次性命名空间,
    # 随存档持久 — 命中只在本局之内。
    ns = state.get("brief_ns")
    if not ns:
        import uuid as _uuid
        ns = state["brief_ns"] = _uuid.uuid4().hex[:8]
    key = "|".join([ns,
                    str(((content.get("story") or {}).get("id")) or ""),
                    str(state.get("location_id") or ""),
                    active_slot(content, state) or "",
                    ",".join(sorted(c["id"] for c in roster))])
    sb = state.get("scene_brief")
    if isinstance(sb, dict) and sb.get("key") == key:
        return sb
    state.pop("scene_brief", None)   # 旧场的单子不许指挥新场
    hit = _BRIEF_CACHE.get(key)
    if isinstance(hit, dict):
        state["scene_brief"] = dict(hit)
        _audit(state, "director.brief", bool(hit.get("crux")),
               (hit.get("crux") or "degrade")[:24])
        return hit
    if key in _BRIEF_INFLIGHT:
        return {}
    # ── 备料全在主线程 (线程碰 state 会脏账本: char_agenda 会写 char_sim) ──
    names = {c.get("name") for c in roster}
    ids_here = {c["id"] for c in roster}
    spark = next((p for p in conflict_pairs(content, state)
                  if p["a_id"] in ids_here or p["b_id"] in ids_here), None)
    payload = {"director_brief": True,
               "place": (current_location(content, state) or {}).get("name") or "",
               "slot": (clock_view(content, state) or {}).get("label", ""),
               "cast": [{"name": c.get("name"), "gender": c.get("gender") or "",
                         "traits": c.get("traits") or {},
                         "persona": (c.get("persona_text") or "")[:80],
                         "goal": _agenda_prompt(content, state, c)[:80]}
                        for c in roster[:4]],
               "player": player_card(content, state, persona),
               "spark": (f"{spark['a']}×{spark['b']}（{spark['label']}）："
                         f"{spark['a_goal']} 撞上 {spark['b_goal']}" if spark else ""),
               "setups": [s.get("text") for s in (state.get("setups") or [])
                          if not s.get("paid")][:2]}
    _BRIEF_INFLIGHT.add(key)

    def _work():
        try:
            try:
                out = llm.generate(payload) or {}
            except Exception:
                out = {}
            minds = out.get("minds") if isinstance(out.get("minds"), dict) else {}
            brief = {"key": key,
                     "crux": dedash(str(out.get("crux") or "").strip())[:30],
                     "minds": {n: dedash(str(t).strip())[:24]
                               for n, t in minds.items() if n in names and str(t).strip()},
                     "initiative": (str(out.get("initiative") or "").strip()
                                    if str(out.get("initiative") or "").strip() in names else ""),
                     "spark": dedash(str(out.get("spark") or "").strip())[:36]}
            # 空单不入缓存 (模型失手/超时的降级结果缓存住 = 这一场永远没导演),
            # 放过它让下一回合重试; brief 本就不在关键路径, 重试不伤首字
            if brief.get("crux") or brief.get("minds") or brief.get("initiative"):
                while len(_BRIEF_CACHE) >= _BRIEF_CAP:
                    _BRIEF_CACHE.pop(next(iter(_BRIEF_CACHE)), None)
                _BRIEF_CACHE[key] = brief
        finally:
            # finally 清 inflight (台账实弹: 中途炸了这一场永远挂着「在做」, 再也不试)
            _BRIEF_INFLIGHT.discard(key)

    import threading
    threading.Thread(target=_work, daemon=True).start()
    return {}


def set_suggestions(state: dict[str, Any], items: list[str],
                    content: dict[str, Any] | None = None) -> list[str]:
    """建议的单一落账口 (治「七个产地各写各的规矩」): 所有产地必须走这里 —
    去破折号、去重、掐长、限两条 (Yi 定: 选项两个, 少即是多)。措辞规矩改这里 = 改所有产地。"""
    out: list[str] = []
    # 🧩 模型可能把 suggestions 写成字符串 —— 直接迭代会逐字符炸开, chips 变成
    #    '[' 和 '"' (Yi 实弹 2026-08-04)。所有产地都从这道口进, 收在这里最省。
    for s in as_str_list(items):
        # 🔖 脱掉【】「」“” 这类包裹, 并抹掉掐长留下的半边 (Yi 点名的那个症状)
        t = unwrap_pairs(dedash(str(s or "").strip()))
        # 🎭 视角守卫 (Yi 实弹 2026-08-02 二犯): 建议是【玩家】的下一步, 「你…」开头
        # 的是角色在劝玩家 — 视角串了, 整条丢, 缺口由 ensure_three_suggestions 垫底。
        # (玩家第一人称的合法开头是 我…/动词…, 不会以「你/You」起手。)
        if re.match(r"^(你|請你|请你|You\b|Your\b)", t, re.IGNORECASE):
            continue
        if t and t not in out:
            out.append(t[:60])
        if len(out) >= 2:
            break
    state["suggestions"] = out
    return out


def goals_of(state: dict[str, Any]) -> list[dict[str, Any]]:
    g = state.get("goals")
    if not isinstance(g, list):
        g = []
        state["goals"] = g
    return g


def _trim_ledger(rows: list[dict[str, Any]], cap: int = 8) -> list[dict[str, Any]]:
    """账本裁剪家法: open 条目永不静默消失 — 超额时先裁最老的非 open 历史
    (裸 [-cap:] 会把早年 open 的自立目标/任务冲掉, 无 audit 无痕)。"""
    extra = len(rows) - cap
    if extra <= 0:
        return rows
    out: list[dict[str, Any]] = []
    for r in rows:
        if extra > 0 and r.get("status") != "open":
            extra -= 1
            continue
        out.append(r)
    return out


def goal_push(state: dict[str, Any], kind: str, text: str, src: str = "") -> None:
    """Book a goal onto its layer. Same-layer open goal is REPLACED (一层只挂一件事);
    the retired one lands in the audit, never silently vanishes."""
    text = dedash(str(text or "").strip())[:40]
    if not text or kind not in _GOAL_RANK:
        return
    gs = goals_of(state)
    for g in gs:
        if g.get("kind") == kind and g.get("status") == "open":
            if g.get("text") == text:
                return
            g["status"] = "replaced"
    gs.append({"kind": kind, "text": text, "from": str(src)[:20],
               "status": "open", "at": _time_index(state)})
    gs[:] = _trim_ledger(gs)
    _audit(state, f"goal.{kind}", True, text[:24])


def goal_settle(state: dict[str, Any], kind: str, status: str = "done") -> None:
    for g in goals_of(state):
        if g.get("kind") == kind and g.get("status") == "open":
            g["status"] = status
            _audit(state, f"goal.{status}", True, str(g.get('text'))[:24])


def goal_top(content: dict[str, Any], state: dict[str, Any]) -> str:
    """The goal bar's text: highest-rank OPEN goal; act layer derives live (幕目标
    不落栈, 它由幕推导, 永远兜底)。顺手清过期差事。"""
    ti = _time_index(state)
    best_rank, best_text = 0, ""
    for g in goals_of(state):
        if g.get("status") != "open":
            continue
        if g.get("kind") == "errand" and ti - int(g.get("at") or 0) > _ERRAND_TTL:
            g["status"] = "expired"
            _audit(state, "goal.expired", True, str(g.get('text'))[:24])
            continue
        r = _GOAL_RANK.get(g.get("kind") or "", 0)
        if r > best_rank:
            best_rank, best_text = r, str(g.get("text") or "")
    return best_text or goal_for(content, state)


def player_goal_set(content: dict[str, Any], state: dict[str, Any], text: str) -> str:
    """🎯 沙盒: 玩家亲手定当前目标 (player 层, 压过差事)。空文本 = 撤下玩家目标。"""
    text = dedash(str(text or "").strip())[:40]
    if text:
        goal_push(state, "player", text, src="player")
    else:
        goal_settle(state, "player", "dropped")
    state["goal"] = goal_top(content, state)
    return state["goal"]


def player_goal_suggest(content: dict[str, Any], state: dict[str, Any]) -> str:
    """🎲 随机推荐一个目标: 确定性产地, 从活世界的真实账本里长出来 (不花 LLM)。"""
    pcid = state.get("player_character_id")
    met = set(state.get("met_ids") or [])
    dead = _dead_ids(state)
    pool: list[str] = []
    for l in _locations(content):
        if l.get("name") and location_available(content, state, l) \
                and l.get("id") != state.get("location_id"):
            pool.append(f"去{l.get('name')}走一趟，看看那边的光景")
    warm = sorted(((c, (state.get("rel") or {}).get(c.get("id")) or {})
                   for c in _characters(content)
                   if c.get("id") in met and c.get("id") not in dead and c.get("id") != pcid),
                  key=lambda x: int(x[1].get("closeness", 0) or 0), reverse=True)
    if warm:
        pool.append(f"跟{warm[0][0].get('name')}把关系处得更近一步")
        if len(warm) > 1:
            pool.append(f"弄清楚{warm[-1][0].get('name')}最近在忙什么")
    for q in (state.get("quests") or []):
        if q.get("status") == "open" and q.get("title"):
            pool.append(f"把「{q.get('title')}」办妥")
    cult = state.get("cultivation") or {}
    if cult.get("ready"):
        pool.append("闭关一场，冲一冲下一个境界")
    if economy_on(state):
        pool.append("想个来钱的路子，攒一笔身家")
    pool.append("找个没去过的角落，看看这世界还藏着什么")
    cur = goal_top(content, state)
    picks = [p for p in pool if p != cur] or pool
    return dedash(random.choice(picks))[:40]


def _frag_title_map(content: dict[str, Any]) -> dict[str, str]:
    """fragment_id → its secret's title (a sanitized topic label, never the body)."""
    out: dict[str, str] = {}
    for secret in content.get("secrets", []) or []:
        title = secret.get("title", "")
        for f in secret.get("fragments", []) or []:
            if f.get("id"):
                out[f["id"]] = title
    return out


def _frag_location_map(content: dict[str, Any]) -> dict[str, str]:
    """fragment id → the location_id its unlock requires the player to be at (if any)."""
    out: dict[str, str] = {}
    for sec in content.get("secrets", []) or []:
        for f in sec.get("fragments", []) or []:
            lid = (f.get("unlock") or {}).get("location_id")
            if f.get("id") and lid:
                out[f.get("id")] = lid
    return out


def _event_label_map(content: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for act in (content.get("story") or {}).get("acts", []) or []:
        for ev in act.get("events", []) or []:
            if ev.get("id"):
                out[ev["id"]] = ev.get("what_happens", "")
    return out


def _advance_cond(content: dict[str, Any], act_index: int) -> dict[str, Any]:
    return (current_act(content, act_index) or {}).get("advance") or {}


def act_has_gate(content: dict[str, Any], act_index: int) -> bool:
    """True if this act authored any hard advance condition (else soft-advance fallback)."""
    adv = _advance_cond(content, act_index)
    return bool(adv.get("required_fragment_ids") or adv.get("required_event_ids")
                or int(adv.get("affinity_min") or 0) > 0)


def can_advance(content: dict[str, Any], state: dict[str, Any], act_index: int) -> bool:
    """HARD gate (pure, program-checked): are ALL of this act's advance conditions met?

    Required fragments must be unlocked (= the player actually dug that info out), required
    events triggered, affinity at/above the floor. This is the security/structure twin of
    gating.py — progression can't be talked past, only earned by discovery."""
    adv = _advance_cond(content, act_index)
    unlocked = set(state.get("unlocked_fragment_ids") or [])
    triggered = set(state.get("triggered_event_ids") or [])
    if not set(adv.get("required_fragment_ids") or []) <= unlocked:
        return False
    if not set(adv.get("required_event_ids") or []) <= triggered:
        return False
    if int(state.get("affinity", 0)) < int(adv.get("affinity_min") or 0):
        return False
    return True


def act_progress(content: dict[str, Any], state: dict[str, Any], act_index: int) -> dict[str, Any]:
    """A guidance checklist for the current act: which required clues are found (✓) vs
    still missing (○). Labels are sanitized secret titles / authored event text — never
    fragment bodies. Empty when the act has no hard gate."""
    adv = _advance_cond(content, act_index)
    unlocked = set(state.get("unlocked_fragment_ids") or [])
    triggered = set(state.get("triggered_event_ids") or [])
    ftitles = _frag_title_map(content)
    elabels = _event_label_map(content)
    floc = _frag_location_map(content)
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for fid in adv.get("required_fragment_ids") or []:
        label = ftitles.get(fid, "线索")
        if label in seen:
            continue
        seen.add(label)
        done = fid in unlocked
        # a location-gated clue guides the player TO the place ("去X看看") once the
        # place itself is discoverable — turning the checklist into a travel plan
        if not done:
            lid = floc.get(fid)
            loc = _location_by_id(content, lid) if lid else None
            if loc and location_available(content, state, loc):
                label = (f"{label} (worth a look: {loc.get('name','')})"
                         if lang_of(content) == "en"
                         else f"{label}（去「{loc.get('name','')}」看看）")
        items.append({"label": label, "done": done})
    for eid in adv.get("required_event_ids") or []:
        items.append({"label": elabels.get(eid, "关键进展"), "done": eid in triggered})
    done = sum(1 for it in items if it["done"])
    return {"items": items, "done": done, "total": len(items)}


def _pending_topics(progress: dict[str, Any]) -> list[str]:
    """Titles of still-missing required clues (for steering the player / characters)."""
    return [it["label"] for it in progress.get("items", []) if not it["done"]]


def build_opening(content: dict[str, Any], state: dict[str, Any], llm: LLM | None = None) -> list[dict[str, Any]]:
    """A detailed, literary opening that INTRODUCES the player: who you are, where/when
    you are, what's happening, who's around — ending with your first small goal. One LLM
    call at run start (degrades to assembled narration). Secrets are never passed in."""
    llm = lang_llm(llm or get_llm(), content)
    mode = state.get("mode") or "character"
    pcid = state.get("player_character_id")
    act1 = current_act(content, 1) or {}
    player_char = _char_by_id(content, pcid) if (mode == "character" and pcid) else None
    # pin the starting place so the player has a concrete spatial anchor from turn 1.
    # 🏖 sandbox + embodied character: open on THEIR home turf (playing 萧炎 starts at
    # the tower, not the plaza) — a different character IS a different opening. Authored
    # stories keep their staged opening place (act-1 events live there).
    start = None
    if sandbox_on(content) and player_char:
        start = _location_by_id(content, player_char.get("home_location_id"))
    start = start or current_location(content, state)
    if start and start.get("id"):
        state["location_id"] = start["id"]
    # ⏳ the story opens at ITS hour, not at a default 晨 (夜戏 opens at night)
    align_clock_to_act(content, state, 1)
    # WHO IS ACTUALLY HERE: the scene roster at the pinned opening place — never the
    # whole act-1 cast (writing absent people into the opening was turn-zero 文与实分家)
    present_chars = [c for c in scene_characters(content, state)
                     if c.get("name") and c.get("id") != pcid][:4]
    is_god = mode == "god"
    # 🚪 起点无人的沙盒开场: 生地方不配空开场 — 关系档位最热的街坊亲自上门打照面。
    # 这是真移动 (sim 位置改到起点), 文与实同拍; relation_default 就是「谁会来串门」
    # 的作者信号 (peer=自来熟 > stranger)。授权剧本不碰: 空场可能是导演故意的 (恐怖片)。
    if not present_chars and sandbox_on(content) and not is_god:
        _rank = {"friend": 4, "peer": 3, "junior": 2, "elder": 1}
        # 🎬 作者点名优先 (sandbox.opening_visitor = 角色id或名字): 「这个故事围绕谁」
        # 只有作者知道 — 档位启发式会抓来跑龙套的 (实弹: 男主标 stranger 永远轮不到,
        # 开场被 peer 档的配角抢走)。点名无效/已死才回落档位排序。
        _ov = str(((content.get("story") or {}).get("sandbox") or {})
                  .get("opening_visitor") or "").strip()
        caller = None
        if _ov:
            _ovc = _char_by_id(content, _ov) or next(
                (c for c in _characters(content) if c.get("name") == _ov), None)
            if _ovc and _ovc.get("id") != pcid and _ovc.get("id") not in _dead_ids(state):
                caller = _ovc
        caller = caller or max(
            (c for c in present_characters(content, 1, _dead_ids(state))
             if c.get("id") and c.get("id") != pcid and c.get("name")),
            key=lambda c: _rank.get(c.get("relation_default") or "", 0),
            default=None)
        if caller and start and start.get("id"):
            # 用 char_pins 落位 (不是 sim pos): 作息表的优先级压过 sim, 排了班的访客
            # 会被自己的班表瞬移走; pin 压过作息, 且玩家一离开就自动放人回作息
            state.setdefault("char_pins", {})[caller["id"]] = start["id"]
            caller = {**caller, "visiting": True}
            present_chars = [caller]
            _audit(state, "opening.visitor", True, str(caller.get("name"))[:12])
    present = [c.get("name") for c in present_chars]
    # 🎤 开场玩家先发言 (作者开关 tuning.opening_player_first): 开场演出只让角色亮相,
    # 不许任何人先对玩家开口 — 第一句对话留给玩家。god 位玩家本就不被搭话, 不适用。
    player_first = bool(tuning_for(content).get("opening_player_first")) and not is_god
    # ✨ 首局魔法时刻的由头: 主角位那位有话没说 (只给秘密标题, 绝不点破内容)
    lead = next((c for c in present_chars if c.get("is_lead")),
                present_chars[0] if present_chars else None)
    tease = None
    if lead and not is_god:
        tease = next((s.get("title") for s in content.get("secrets") or []
                      if (s.get("title") or "").strip()
                      and s.get("character_id") == lead.get("id")), None) \
            or next((s.get("title") for s in content.get("secrets") or []
                     if (s.get("title") or "").strip()), None)
    # 🎬 galgame 开场 (Yi: 字太多 → 简短环境交代 + 每个角色一段小剧情):
    # 一拍 ≤80 字的环境, 然后在场每人「你第一眼看到TA在干嘛」+「TA的第一句话」
    # 🎯 钩子分道预判 (Yi: 不同初始关系用不同手段): 追求线的主角位留口实不派差事
    _hook_court = bool(lead) and relationships.initial_mode(lead) in ("stranger", "peer") \
        and relationships._romance_capable(lead)
    out = {}
    # 🎬 作者亲笔开场白: 提前算好 — 既要一字不落上台, 也要喂给开场生成
    # (Yi 实弹: 只上台不喂生成 → 旁白在演暴雨夜, 角色却像没读过剧本)
    # dedash 留给逐拍的 dedash_beat: 整串跑会把段末破折号改成逗号, 破坏一字不落 (审计实弹)
    _auth_open = str((content.get("story") or {}).get("opening") or "").strip()[:10000]
    try:
        out = llm.generate({
            "intro_vignettes": True,
            "auth_opening": _auth_open[:2000],
            "player_first": player_first,
            "hook_court": _hook_court,
            "clock": (clock_view(content, state) or {}).get("label", ""),
            "real_now": real_now_line(content, state),
            "player": {"name": (player_char or {}).get("name") or "你",
                       "role": (player_char or {}).get("role") or "刚来到这里的人"},
            "world": ((content.get("story") or {}).get("world_long") or "")[:300],
            # ✍️ 保头保尾地截, 别用 [:160] 从头切 —— 作者腔写在卡头, 经济律与忌用清单
            # 写在卡尾。实测 15 张生产卡: 直切会让 7 张在【开场那一拍】完全看不到自己的
            # 忌用清单。玩家读到的第一段字, 留存最贵, 原本管得最松。
            "style": _style_head_for_intro((content.get("story") or {}).get("style"), 160),
            "goal": act1.get("goal", ""),
            "place": _physical_place(content, state),
            "chars": [{"name": c.get("name"), "role": c.get("role") or "",
                       "persona_text": (c.get("persona_text") or "")[:120],
                       "is_lead": bool(c.get("is_lead")),
                       **({"visiting": True} if c.get("visiting") else {}),
                       **({"opening_line": str(c.get("opening_line") or "")[:80]}
                          if str(c.get("opening_line") or "").strip() else {}),
                       "examples": [str(x)[:40] for x in (c.get("examples") or [])][:2]}
                      for c in present_chars],
            "tease": tease or "",
            "god": is_god,
            "mature": bool(state.get("mature")),
        }) or {}
    except Exception:
        out = {}
    beats: list[dict[str, Any]] = []
    # 【一字不落】上台: 长文按段落拆拍念完, 不截断不改写 (上限与 studio maxlength 同步 1 万)
    if _auth_open:
        for _para in [p.strip() for p in _auth_open.splitlines() if p.strip()]:
            beats.append({"type": "description", "speaker_name": None, "text": _para})
    else:
        scene_txt = dedash(str(out.get("scene") or "").strip())[:110] \
            or opening_narration(content)[:110]
        beats.append({"type": "description", "speaker_name": None, "text": scene_txt})
    by_name = {c.get("name"): c for c in present_chars}
    seen = set()
    for v in (out.get("cast") or []):
        nm = str(v.get("name") or "").strip()
        if nm not in by_name or nm in seen:   # 越界/重复的直接丢 — 名单引擎说了算
            continue
        seen.add(nm)
        # ≤80/60 的预算是中文体量 — 英文走 cap_prose 双倍且不劈单词 (straig 实弹)
        act_txt = cap_prose(dedash(str(v.get("action") or "").strip()), 80, content)
        line_txt = cap_prose(dedash(str(v.get("line") or "").strip().strip("「」\"'")), 60, content)
        # 🎙 作者写定的开场白原样上台 — 模型的即兴让位, 只保留它写的动作
        _auth = cap_prose(dedash(str(by_name[nm].get("opening_line") or "").strip().strip("「」\"'")), 80, content)
        if _auth:
            line_txt = _auth
        if act_txt:
            beats.append({"type": "description", "speaker_name": None, "text": act_txt})
        if line_txt and not player_first:
            beats.append({"type": "dialogue", "speaker_name": nm, "text": line_txt})
    # 确定性兜底: 模型没交齐的人, 用人设和台词范例立住 (范例本来就是这张嘴);
    # 主角位带欲言又止的裂缝 (只提秘密标题); 上帝位无人对玩家开口
    for c in present_chars:
        nm = c.get("name")
        if nm in seen:
            continue
        if c is lead and tease:
            beats.append({"type": "description", "speaker_name": None,
                          "text": f"{nm}的目光在你身上多停了一瞬，像有什么关于"
                                  f"「{tease}」的话到了嘴边，被咽了回去。"})
        elif c.get("visiting"):
            beats.append({"type": "description", "speaker_name": None,
                          "text": f"{nm}不知什么时候到了这儿，显然是特意来看看你这张新面孔。"})
        else:
            beats.append({"type": "description", "speaker_name": None,
                          "text": f"{nm}就在不远处，正忙着{(c.get('role') or '自己')[:12]}的事，"
                                  "注意到了你。"})
        if not is_god and not player_first:
            _auth = dedash(str(c.get("opening_line") or "").strip().strip("「」\"'"))[:80]
            ex = [str(x) for x in (c.get("examples") or []) if str(x).strip()]
            beats.append({"type": "dialogue", "speaker_name": nm,
                          "text": (_auth or (ex[0][:60] if ex else "新来的？"))})
    # 🎤 玩家先发言: 差事由头也不派 — 没人开过口, 凭空落账就是幻影差事 (文与实分家)。
    # 建议改发两句「怎么开这个口」的方向, 走单一落账口。
    if player_first:
        # 空场开场 (授权本的恐怖片留白等) 没人可打招呼 — 建议跟着实况走, 不许文实分家
        if present_chars:
            _sg = (["Walk over and say hello", "Take a quiet look around first"]
                   if lang_of(content) == "en" else
                   ["上前打个招呼，自报家门", "先不作声，四下打量一番"])
        else:
            _sg = (["Take a look around", "Call out and see if anyone answers"]
                   if lang_of(content) == "en" else
                   ["四下看看，摸摸这里的底细", "出声试探一句，看有没有人应"])
        set_suggestions(state, _sg, content)
        _audit(state, "opening.player_first", True,
               ",".join(n for n in present if n)[:24])
        return [dedash_beat(b) for b in beats]
    # 🎯 开局由头 (Yi: 一开始要给玩家一件具体的事): 主角位亲口交代第一件差事
    # (最好把玩家引向不在场的角色/地点 = 探索钩子); 目标条与首批建议都指向它
    hk = out.get("hook") or {}
    task = dedash(str(hk.get("task") or "").strip())[:30]
    hline = dedash(str(hk.get("line") or "").strip().strip("「」\"'"))[:70]
    # 🎯 钩子分道 (Yi: 干活维持剧情太扁平): 追求线的访客不派差事 — 留口实;
    # 上下级/长辈才吩咐办事。引擎选战术, 措辞交给确定性模板或模型。
    _court = _hook_court
    if not task and lead and not is_god and _court:
        task = f"看清{lead.get('name')}葫芦里卖的什么药"[:30]
        _ex = [str(x) for x in (lead.get("examples") or []) if str(x).strip()]
        hline = (_ex[1][:70] if len(_ex) > 1 else
                 "顺路多买了一份，尝尝？就当认识一场。")
    if not task and lead and not is_god:
        _pids = {x.get("id") for x in present_chars}
        other = next((c for c in _characters(content)
                      if c.get("id") and c.get("id") not in _pids
                      and c.get("id") != pcid and c.get("name")), None)
        if other:
            _w = (_location_by_id(content, other.get("home_location_id")) or {}) \
                .get("name") or "TA常待的地方"
            task = f"替{lead.get('name')}给{other.get('name')}捎样东西"[:30]
            hline = (f"对了，帮我把这个捎给{other.get('name')}，TA这会儿多半在{_w}。"
                     "就当认认路了。")
    if task and lead and not is_god:
        if hline:
            beats.append({"type": "dialogue", "speaker_name": lead.get("name"),
                          "text": hline})
        # 🎯 目标栈: 由头压差事层 (幕目标兜底不受扰); 镜像给 UI
        goal_push(state, "errand", task, src="opening")
        state["goal"] = goal_top(content, state)
        set_suggestions(state, (["接过来，道声谢", "不动声色，先看看TA想干什么"]
                                if _court else
                                [f"答应下来：{task}", "婉拒，想先自己四处转转"]), content)
        _audit(state, "opening.hook", True, task[:24])
    # 📇 开场就把在场的人写进通讯录 —— 玩家开局第一件事往往是点开手机, 那时还没走过
    # 任何一个回合, 不在这儿给就会看到一本空通讯录 (而屏幕上写着「在场 2 人」)。
    grant_contact_on_meet(content, state)
    return [dedash_beat(b) for b in beats]


def opening_hook_beats(content: dict[str, Any], state: dict[str, Any],
                       player_char: dict[str, Any] | None, llm: LLM) -> list[dict[str, Any]]:
    """The hook: the lead notices the player personally AND visibly swallows something
    unsaid (keyed to a secret's TITLE only — spoiler-safe by the same rule as hints).
    LLM writes both strokes; deterministic fallback keeps the withheld-crack narration."""
    if (state.get("mode") or "character") == "god":
        return []
    pcid = state.get("player_character_id")
    host = next((c for c in scene_characters(content, state)
                 if c.get("id") != pcid and c.get("is_lead")), None) \
        or next((c for c in scene_characters(content, state) if c.get("id") != pcid), None)
    if not host:
        return []
    tease = next((s.get("title") for s in content.get("secrets") or []
                  if (s.get("title") or "").strip()
                  and (s.get("character_id") == host.get("id"))), None) \
        or next((s.get("title") for s in content.get("secrets") or []
                 if (s.get("title") or "").strip()), None)
    narration = line = ""
    try:
        out = llm.generate({"opening_hook": True,
                            "char": {"name": host.get("name"), "role": host.get("role") or "",
                                     "persona_text": (host.get("persona_text") or "")[:200],
                                     "eq_style": (host.get("eq_style") or "")[:100]},
                            "player_name": (player_char or {}).get("name") or "你",
                            "player_role": (player_char or {}).get("role") or "",
                            "place": (current_location(content, state) or {}).get("name") or "",
                            "tease": tease or ""}) or {}
        narration = str(out.get("narration") or "").strip()
        # 上台的台词 — 英文双倍预算且不劈单词 (straig 同族)
        line = cap_prose(str(out.get("line") or "").strip().strip("「」\"'"), 80, content)
    except Exception:
        pass
    if not narration and tease:
        narration = (f"（{host.get('name')}的目光落在你身上，多停了一瞬，像在掂量你，"
                     f"又像有什么关于「{tease}」的话到了嘴边，被咽了回去。）")
    beats: list[dict[str, Any]] = []
    if narration:
        beats.append({"type": "description", "speaker_name": None, "text": narration})
    if line:
        beats.append({"type": "dialogue", "speaker_name": host.get("name"), "text": line})
    return beats


def build_act_transition(content: dict[str, Any], state: dict[str, Any], old_act: int,
                          new_act: int, persona: dict[str, Any] | None = None,
                          llm: LLM | None = None) -> list[dict[str, Any]]:
    """Narration that carries the plot INTO a new act: the shift, the new situation, the
    new goal. One LLM call (degrades to the act's authored events). Spoiler-safe."""
    llm = lang_llm(llm or get_llm(), content)
    mode = state.get("mode") or "character"
    pcid = state.get("player_character_id")
    act = current_act(content, new_act) or {}
    player_char = _char_by_id(content, pcid) if (mode == "character" and pcid) else None
    # only who's ACTUALLY at the player's current location — NOT every character who has
    # arrived by this act. A distant act-event (e.g. 王九 at 巷口) must reach the player as
    # news/sound, not teleport a crowd into the room the player is standing in.
    present = [c.get("name") for c in scene_characters(content, state)
               if c.get("name") and c.get("id") != pcid]
    prev = current_act(content, old_act) or {}
    prompt = {
        "transition": True,
        "clock": (clock_view(content, state) or {}).get("label", ""),
            "real_now": real_now_line(content, state),
        "mode": mode,
        "player_char": player_char,
        "world": (content.get("story") or {}).get("world_long", "") or "",
        "style": (content.get("story") or {}).get("style") or "",  # ✍️ 文风
        "act": act,
        "prev_title": prev.get("title", ""),
        "goal": act.get("goal", ""),
        "cast": present,
        "place": _physical_place(content, state),
        "memory": state.get("memory", ""),
        "mature": bool(state.get("mature")),
    }
    directed = _lang_guard(llm, prompt, llm.generate(prompt), content)
    beats = [b for b in directed.get("beats", []) if b.get("type") == "description"]
    # fallback: at least state the new act's events so the transition still carries info
    if not beats:
        ev = " ".join(e.get("what_happens", "") for e in (act.get("events") or []))
        if ev:
            beats = [{"type": "description", "speaker_name": None, "text": ev}]
    return [dedash_beat(b) for b in beats]


_ENDING_PRIORITY = {"true": 3, "normal": 2, "bad": 1, "death": 0}
_DEFAULT_ENDING_TITLE = {"death": "你死了", "bad": "坏结局", "normal": "结局", "true": "真结局"}


def evaluate_ending(
    content: dict[str, Any], state: dict[str, Any], model_ending: dict | None
) -> dict[str, Any] | None:
    """Decide whether the run concludes this turn.

    Two sources:
    1. The director declared a fatal/terminal player action (death/bad) → fires NOW,
       regardless of act. The consequence is already in the turn's narration.
    2. Authored endings whose conditions are all met. By default an authored ending is
       only eligible at the final act (so the player isn't yanked to an ending early);
       set its act_min to make it eligible sooner. Among eligible matches we pick the
       best (true > normal > bad), so reaching the true ending's bar beats the default.
    """
    if model_ending and model_ending.get("kind") in ("death", "bad"):
        kind = model_ending["kind"]
        # A fatal action is genuinely terminal — you can't keep exploring as a corpse.
        return {
            "id": "director",
            "kind": kind,
            "title": _DEFAULT_ENDING_TITLE[kind],
            "text": model_ending.get("reason") or "",
            "terminal": kind == "death",
        }

    endings = (content.get("story") or {}).get("endings") or []
    if not endings:
        return None
    max_act = _max_act_index(content)
    act = int(state.get("act", 1))
    aff = int(state.get("affinity", 0))
    unlocked = set(state.get("unlocked_fragment_ids") or [])
    flags = state.get("flags") or {}

    matches = []
    for e in endings:
        if e.get("trigger"):
            continue  # mechanism-invoked (e.g. pressure blowout) — never a normal match
        cond = e.get("condition") or {}
        gate_act = int(cond.get("act_min") or 0) or max_act  # 0 ⇒ only at the final act
        if act < gate_act:
            continue
        if aff < int(cond.get("affinity_min") or 0):
            continue
        if not set(cond.get("required_fragment_ids") or []) <= unlocked:
            continue
        rflags = cond.get("required_flags") or {}
        if any(flags.get(k) != v for k, v in rflags.items()):
            continue
        matches.append(e)
    if not matches:
        return None
    best = max(matches, key=lambda e: _ENDING_PRIORITY.get(e.get("kind", "normal"), 2))
    kind = best.get("kind", "normal")
    # Authored endings are MILESTONES in an open world — reaching one doesn't end the
    # run; the player keeps exploring (and may later reach a higher-tier ending).
    return {
        "id": best.get("id"),
        "kind": kind,
        "title": best.get("title") or _DEFAULT_ENDING_TITLE.get(kind, "结局"),
        "text": best.get("text", ""),
        "terminal": False,
    }


def _act_opening(act: dict[str, Any]) -> str:
    """Narration played when the run crosses into a new act — pushes the scene forward."""
    title = act.get("title", "")
    events = " ".join(e.get("what_happens", "") for e in (act.get("events") or []))
    head = f"〔第{act.get('index', '')}幕 · {title}〕"
    return (head + "  " + events).strip()


def opening_narration(content: dict[str, Any]) -> str:
    """Atmospheric scene-set for a brand-new run: worldbuilding + act-1 opening."""
    story = content.get("story") or {}
    parts: list[str] = []
    if story.get("world_long"):
        parts.append(story["world_long"])
    act1 = current_act(content, 1)
    if act1:
        ev = " ".join(e.get("what_happens", "") for e in (act1.get("events") or []))
        if ev:
            parts.append(ev)
    return "  ".join(parts) or "故事，就这样开始了。"


def _norm_line(s: str) -> str:
    """Normalize a line for echo comparison: drop whitespace + punctuation."""
    import re
    return re.sub(r"[\s，。、！？…—\-,.!?\"'「」（）()]+", "", s or "")


NARR_LEDGER = 8      # 近拍旁白留档数 (查意象复读用; 喂守卫的仍只取最近 2 拍)
_MOTIF_MIN_RUNS = 2  # 跨几拍出现过才算「意象」—— 只出现一次的是新东西, 不该被禁


def narration_motifs(state: dict[str, Any], cap: int = 6) -> list[str]:
    """本场旁白里已经【反复】出现的意象 —— 动笔之前摊给模型, 让它换一个。

    生产实测 (2174 条旁白): 狗笼 59 条里「桃花眼」8 次、「喉结上下滚动」6 次、
    「低头看你」6 次; 斗罗 178 条里「目光从你」16 次, 几乎成了旁白的开场公式。
    此前这些只喂给【事后】的复读守卫 —— 而守卫一响就是一次整包重生, 又慢又贵,
    且模型压根不知道自己刚写过什么。写之前告诉它, 比写完了罚它便宜得多。

    判据故意做成【自校准】: 跨拍重复出现的才算意象, 不认任何硬编码词表 ——
    引擎不许知道某个剧本里有「桃花眼」这种东西 (engine-agnostic 家规)。
    """
    texts = [str(t) for t in (state.get("_recent_narr") or []) if str(t or "").strip()]
    if len(texts) < _MOTIF_MIN_RUNS:
        return []
    # 每一拍先各自去重, 再数「出现在几拍里」—— 同一拍里重复不算 tic, 跨拍才算
    seen_in: dict[str, int] = {}
    for t in texts:
        zh = re.sub(r"[^一-龥]", "", t)
        # 三字也要数: 中文里最烦人的那些意象常常只有三个字 (实弹「桃花眼」在 59 条
        # 旁白里出现 8 次, 而只开四字窗口会整个漏掉它)。碎片由下面的合并收拾。
        grams = {zh[i:i + 3] for i in range(len(zh) - 2)}
        grams |= {zh[i:i + 4] for i in range(len(zh) - 3)}
        # 英文本按词组
        en = re.findall(r"[A-Za-z']+", t.lower())
        grams |= {" ".join(en[i:i + 3]) for i in range(len(en) - 2)}
        for g in grams:
            seen_in[g] = seen_in.get(g, 0) + 1
    hits = [g for g, n in seen_in.items() if n >= _MOTIF_MIN_RUNS]
    if not hits:
        return []
    # 先把滑窗切出来的碎片长回去: 「他低头看」「低头看你」是同一个动作的两刀,
    # 「锁骨上的」「骨上的薄」「上的薄汗」是同一处细节的三刀。不合并的话, 名额会被
    # 同一个概念的碎片占满, 而真正最烦人的那个反倒挤不进去 (实弹: 五个名额里三个是
    # 「低头看」和「锁骨薄汗」的碎片, 「桃花眼」没进去)。
    hits.sort(key=lambda g: (-seen_in[g], -len(g), g))
    merged: list[str] = []
    for g in hits:
        joined = False
        for i, m in enumerate(merged):
            if g in m:                      # 已被更长的那条包住
                joined = True
                break
            if m in g:                      # 自己更长, 顶替它
                merged[i] = g
                joined = True
                break
            # 首尾相接就拼起来 (滑窗相邻的两刀)
            for k in range(min(len(g), len(m)) - 1, 1, -1):
                if m.endswith(g[:k]):
                    merged[i] = m + g[k:]
                    joined = True
                    break
                if g.endswith(m[:k]):
                    merged[i] = g + m[k:]
                    joined = True
                    break
            if joined:
                break
        if not joined:
            merged.append(g)
    # 合并会让长条互相包含, 再收一次
    merged.sort(key=len, reverse=True)
    out: list[str] = []
    for m in merged:
        if any(m in kept for kept in out):
            continue
        out.append(m)
        if len(out) >= cap:
            break
    return out


def _too_similar(text: str, said: list[dict[str, str]]) -> bool:
    """True if `text` is near-verbatim of something already said this turn (long shared
    prefix or near-equal length+overlap) — catches echoes that aren't byte-identical."""
    a = _norm_line(text)
    if len(a) < 6:
        return False
    for s in said:
        b = _norm_line(s.get("text", ""))
        if len(b) < 6:
            continue
        # long common prefix relative to the shorter line → it's parroting the opener
        n = min(len(a), len(b))
        common = 0
        while common < n and a[common] == b[common]:
            common += 1
        if common >= max(8, int(0.7 * n)):
            return True
    return False


_LANG_CORRECTION = (
    "CRITICAL: your previous version slipped into Chinese. This story is played in ENGLISH. "
    "Rewrite the ENTIRE turn in natural, fluent English — every line of narration and "
    "dialogue. Keep proper nouns as authored. Do not translate word-for-word; perform the "
    "turn natively in English.")


# ✨ 金手指 enforcement: the world may react, never nullify
_POWER_BREAK_RE = re.compile(
    r"失灵|无效|不起作用|被压制|压制住|免疫|减半|削弱了|封印了|抵消|毫无效果"
    r"|fizzle|no effect|nullif|suppress|immune to|resisted the")
_POWER_CORRECTION = (
    "上一版违反了金手指规则：玩家声明的能力是这个世界的更高法则，绝不允许失灵、被压制、"
    "被免疫或效果打折。重写这一轮：让能力【无条件完整生效】，写得痛快、有画面；"
    "世界的回应只能是震惊、忌惮、觊觎或后续麻烦，不能是抵消。")


def _power_named(state: dict[str, Any], text: str) -> str:
    """The first declared 金手指 whose NAME the player's line mentions, else ""."""
    for p in state.get("powers") or []:
        nm = str(p).split("：", 1)[0].split(":", 1)[0].strip()
        if nm and nm in (text or ""):
            return nm
    return ""


def _power_break(prompt: dict[str, Any], directed: dict[str, Any],
                 state: dict[str, Any]) -> bool:
    """True when the player invoked a declared power this turn and the beats tried to
    suppress/nullify it — the 全员爆衣 failure mode, now a regeneratable violation."""
    if not _power_named(state, prompt.get("player_input") or ""):
        return False
    txt = " ".join(b.get("text", "") for b in directed.get("beats", []))
    return bool(_POWER_BREAK_RE.search(txt))


def _lang_break(prompt: dict[str, Any], directed: dict[str, Any],
                content: dict[str, Any]) -> bool:
    """True when an EN story's beats came back in Chinese. If the PLAYER wrote Chinese this
    turn, mixing is their choice — never flag it."""
    if lang_of(content) != "en":
        return False
    if has_cjk(prompt.get("player_input") or ""):
        return False
    txt = " ".join(b.get("text", "") for b in directed.get("beats", []))
    return len(_CJK_RE.findall(txt)) >= 2


def _lang_guard(llm, prompt: dict[str, Any], directed: dict[str, Any],
                content: dict[str, Any]) -> dict[str, Any]:
    """Language-only backstop for turns that skip the full logic guard (group members).
    One retry with a hard English directive; best effort — never scrubs."""
    if not _lang_break(prompt, directed, content):
        return directed
    retry = llm.generate({**prompt, "logic_correction": _LANG_CORRECTION})
    return retry if retry.get("beats") else directed


import re as _re_phys
# 🧊 物理穿模预筛: 只有这拍出现动作/道具/伤势/位置字眼才值得跑 flash 检测 (纯聊天跳过=零延迟)
_PHYS_TRIGGER = _re_phys.compile(
    "掏|抽出|拿出|取出|摸出|扛|背起|抱起|拎|举起|跑|冲过|跳|翻身|翻过|"
    "伤|断|骨|血|疼|痛|拳|刀|枪|打|踢|摔|扑|冰|烫|递|塞给|口袋|裤兜|兜里")


def _physics_audit(llm, directed: dict[str, Any], state: dict[str, Any]) -> list[str]:
    """🧊 物理连续性哨兵 (Yi: 道具/伤势穿模): 只在有动作/道具/伤势字眼时, 用 flash 快审这一拍
    正文的【硬物理矛盾】——凭空冒出且现实不可能的道具(裤兜掏瓶装汽水)、违反刚发生的明显伤势的
    行为(断肋骨扛货)、无过渡的位置穿越。只报硬矛盾。降级返回 []（绝不阻断; Mock/无 key 也跳过）。"""
    beats = directed.get("beats") or []
    txt = " ".join((b.get("text") or "") for b in beats
                   if b.get("type") in ("dialogue", "description"))[:900]
    if not txt.strip() or not _PHYS_TRIGGER.search(txt) or not getattr(llm, "_url", None):
        return []
    prev = str(state.get("_last_text") or "")[:400]
    import json as _json
    sys_p = ("你是剧本的物理连续性审校。只挑【硬物理矛盾】，不挑文笔、不挑情节：①凭空冒出且现实"
             "不可能的道具（如从裤兜掏出整瓶玻璃瓶汽水、场景里根本没有的东西突然出现）；②违反刚"
             "发生的明显伤势的行为（如刚被打断肋骨却马上扛重物、健步如飞）；③无过渡的位置穿越。"
             '只输出JSON：{"breaks":["≤20字 一条硬矛盾"]}。没有就空数组。宁可放过，别误伤合理描写。')
    u = _json.dumps({"上一拍": prev, "这一拍正文": txt}, ensure_ascii=False)
    try:
        from . import qwen as _q
        resp = _q._post_chat(llm._url, llm._key,
                             {"model": "deepseek-v4-flash", "thinking": {"type": "disabled"},
                              "messages": [{"role": "system", "content": sys_p},
                                           {"role": "user", "content": u}],
                              "max_tokens": 220, "temperature": 0.2,
                              "response_format": {"type": "json_object"}},
                             timeout=15, kind="physics")
        d = _json.loads(resp.json()["choices"][0]["message"]["content"] or "{}")
        return [str(x).strip()[:30] for x in (d.get("breaks") or []) if str(x).strip()][:3]
    except Exception:
        return []


def _logic_guard(llm, prompt: dict[str, Any], directed: dict[str, Any], content: dict[str, Any],
                 state: dict[str, Any], frags: list[dict[str, Any]]) -> dict[str, Any]:
    """Post-generation logic backstop for the addressed (primary) character. Deterministically
    checks this turn's beats against the LIVE scene state — no character who isn't here may be
    shown arriving/speaking, no still-locked secret may surface. On a hard break: regenerate
    ONCE with a targeted correction; if it still breaks, scrub the offending sentences. At most
    one extra LLM call, and only when something is actually wrong (clean turns cost nothing)."""
    pcid = state.get("player_character_id")
    here = scene_characters(content, state)
    here_ids = {c.get("id") for c in here}
    present_names = [c.get("name") for c in here if c.get("name")]
    absent_names = [c.get("name") for c in _characters(content)
                    if c.get("name") and c.get("id") not in here_ids and c.get("id") != pcid]
    locked_locs = [l.get("name") for l in _locations(content)
                   if l.get("name") and not location_available(content, state, l)]
    locked_texts = [f.get("content", "") for f in frags
                    if f.get("content") and gating.classify_guard(f, state) != "reveal"]
    # 🔁 开场白复读检测 (实弹: 锚块每回合在场, 角色不停把开场白再念一遍)
    _opening = str((content.get("story") or {}).get("opening") or "")

    def _check(d):
        return logic.verify_turn(d.get("beats", []), absent_names=absent_names,
                                 locked_location_names=locked_locs,
                                 locked_fragment_texts=locked_texts, present_names=present_names,
                                 opening_text=_opening)

    verdict = _check(directed)
    lang_broke = _lang_break(prompt, directed, content)
    power_broke = _power_break(prompt, directed, state)
    # 🔥 fourth check: at 交合+ the player named the act plainly but the reply dodged
    # (euphemism / camera fled to the scenery / narrator became 「我」) → rewrite once
    heat_broke = (bool(state.get("mature"))
                  and heat_mod.broke(state, prompt.get("player_input") or "",
                                     directed.get("beats", [])))
    # 🎙 fifth check: narration hijacked into a character's first person (旁白人称乱)
    _pcn = _char_name(content, state.get("player_character_id")) or ""
    pov_broke = _pov_break(directed, _pcn)
    # 🔎 sixth check: 导演审稿 (Yi: 导演要确认逻辑无漏洞) — 死者开口/昼夜矛盾/整局复读
    from . import director as director_mod
    _dead_nm = [c.get("name") for c in _characters(content)
                if c.get("id") in _dead_ids(state) and c.get("name")]
    dir_finds = director_mod.logic_audit(
        directed.get("beats", []), slot=active_slot(content, state),
        dead_names=_dead_nm, prev_text=str(state.get("_last_text") or ""),
        recent_texts=[t for t in (state.get("_recent_narr") or []) if t])
    # 🧊 物理穿模哨兵 (道具/伤势/位置): 有动作字眼才 flash 快审, 探到硬矛盾→重生
    phys_finds = (_physics_audit(llm, directed, state)
                  if tuning_for(content).get("physics_guard", 1) else [])
    if not verdict["hard"] and not lang_broke and not power_broke and not heat_broke \
            and not pov_broke and not dir_finds and not phys_finds:
        return directed
    # regenerate once, telling the model exactly what broke (labels only — never the secret body)
    corr_parts: list[str] = []
    if verdict["hard"]:
        corr_parts.append(
            "上一版出现了逻辑错误：" + "；".join(verdict["hard"]) +
            "。请重写这一轮：严格只写此刻在场的人（" + ("、".join(present_names) or "只有你和玩家") +
            "），绝不要让任何不在场的人出场、开口或走进来；也绝不要说出你此刻并不知道、尚未挑明的内情。")
    if lang_broke:
        corr_parts.append(_LANG_CORRECTION)
    if power_broke:
        corr_parts.append(_POWER_CORRECTION)
        _audit(state, "power.enforced", True, _power_named(state, prompt.get("player_input") or ""),
               "上一版试图压制金手指，已强制重写")
    if heat_broke:
        corr_parts.append(heat_mod.correction(lang_of(content)))
        _audit(state, "heat.enforced", True, prompt.get("speaker_name") or "",
               "上一版回避了正面描写，已强制重写")
    if pov_broke:
        corr_parts.append(_POV_CORRECTION)
        _audit(state, "pov.enforced", True, prompt.get("speaker_name") or "",
               "旁白滑成角色第一人称，已强制重写")
    if dir_finds:
        corr_parts.append("导演审稿发现漏洞：" + "；".join(dir_finds) +
                          "。请重写这一轮，把这些破绽全部修掉：死了的人不能出声，"
                          "时辰景象要贴合当前时段，不许复读上一轮的内容。")
        _audit(state, "director.audit", True, "；".join(dir_finds)[:60], "已强制重写")
    if any("开场白" in h for h in verdict["hard"]):
        corr_parts.append("你在复读作者开场白。玩家早已读过那段话，戏也从那一刻往前走了："
                          "绝不逐句重复、引用或改写开场白里的句子，只写此刻正在发生的新内容。")
        _audit(state, "opening.echo", True, prompt.get("speaker_name") or "",
               "复读开场白，已强制重写")
    if phys_finds:
        corr_parts.append("物理连续性出错：" + "；".join(phys_finds) +
                          "。请重写这一轮：去掉现实不可能存在的道具（别为了戏剧效果凭空造物件），"
                          "让每个人的行为符合他此刻的伤势和体力，位置转换要有交代。")
        _audit(state, "physics.enforced", True, "；".join(phys_finds)[:60], "物理穿模，已强制重写")
    retry = llm.generate({**prompt, "logic_correction": "\n".join(corr_parts)})
    if not _check(retry)["hard"]:
        return retry  # a lingering language slip is tolerable; a logic break is not
    # still broken → deterministically neutralize the intrusion so it never reaches the player
    retry["beats"] = logic.scrub_beats(retry.get("beats", []), absent_names,
                                       opening_text=_opening)
    return retry


def ensure_three_suggestions(primary: list[str], backup: list[str],
                             content: dict[str, Any]) -> list[str]:
    """The chip row must ALWAYS hold exactly 2 (Yi 定; 名字里的 three 是历史)。
    重做后的极简契约 (Yi 2026-07-20: 旧四层瀑布太差太杂, 删了重做):
    导演随主拍写的两条 = 唯一智能来源; 不足则用固定的玩家口吻垫底句补齐。"""
    en = lang_of(content) == "en"
    pads = (["I take a careful look around.",
             "I steer the talk toward what I care about.",
             "I get up and move somewhere else."] if en else
            ["我环顾四周，看有什么值得留意的", "我把话题引向我最关心的事", "我起身，去别处走走"])
    out: list[str] = []
    seen: set[str] = set()
    for x in list(primary or []) + list(backup or []) + pads:
        x = dedash((x or "").strip())
        if x and x not in seen:
            seen.add(x)
            out.append(x)
        if len(out) == 2:
            break
    return out


# ── entrances & exits: people never just pop in/out of the cast bar ─────────────
# Slot flavor prefixes for deterministic entrance lines (keyed by SLOTS names).
_SLOT_FLAVOR = {"晨": "晨光里", "午": "日头底下", "夜": "夜色里"}
_SLOT_FLAVOR_EN = {"晨": "In the morning light", "午": "Under the midday sun", "夜": "Out of the dark"}


def cap_prose(s: str, n: int, content: dict[str, Any]) -> str:
    """生成文的硬截, 中西分刀 (预算都是按中文体量定的): 中文原样 [:n] 字节不变;
    英文同信息量要双倍字符, 且绝不从单词中间劈 (访客开场实弹 2026-08-01:
    [:80] 把 straightens 劈成 straig 存进了库, 玩家满屏看半个词)。"""
    s = (s or "").strip()
    if lang_of(content) != "en":
        return s[:n]
    m = n * 2
    if len(s) <= m:
        return s
    cut = s.rfind(" ", 0, m)
    return (s[:cut] if cut > m // 2 else s[:m]).rstrip(" ,;:-")


def _first_sentence(s: str, cap: int = 48) -> str:
    """第一句, 中西通吃: 旧版只认「。」, 英文卡整段落进 [:cap] 从单词中间劈断
    (Golden Hour 进场旁白实弹)。西文句尾 = .!? 后接空白; 超长截断退到空格。"""
    s = (s or "").strip().replace("\n", " ")
    s = re.split(r"。|(?<=[.!?])\s+", s, 1)[0].strip()
    if len(s) > cap:
        cut = s.rfind(" ", 0, cap)
        s = s[:cut if cut > cap // 2 else cap].rstrip()
    # 「。」在 split 时就丢了; 西文句点对齐同一行为 (调用方模板自己补标点, 不对齐会出 "..)")
    return s.rstrip(".!?")


def entrance_beat(content: dict[str, Any], state: dict[str, Any], c: dict[str, Any]) -> dict[str, Any]:
    """A CONCRETE arrival line for a character who just walked into the scene (the hour
    rolled / a new act brought them on): looks + role, not a bare name in the cast bar."""
    slot = active_slot(content, state)
    en = lang_of(content) == "en"
    flavor = (_SLOT_FLAVOR_EN if en else _SLOT_FLAVOR).get(slot or "", "")
    look = _first_sentence(c.get("persona_text") or "")
    role = (c.get("role") or "").strip()
    if en:
        bits = "; ".join(b for b in (role, look) if b)
        lead = f"{flavor}, " if flavor else ""
        # 冒号不用破折号 (Yi 忌清单: 少用破折号, game prose 含引擎模板)
        return {"type": "description", "speaker_name": None,
                "text": f"({lead}{c.get('name')} arrives{(': ' + bits) if bits else ''}.)"}
    bits = "，".join(b for b in (role, look) if b)
    lead = f"{flavor}，" if flavor else ""
    return {"type": "description", "speaker_name": None,
            "text": f"（{lead}{c.get('name')}来了{('，' + bits) if bits else ''}。）"}


def _exit_dest(content: dict[str, Any], state: dict[str, Any],
               c: dict[str, Any]) -> tuple[str | None, str]:
    """Where a departing character is headed: (speakable destination name or None,
    narration tail). A discovered place gets named (探索钩子); an UNDISCOVERED one is
    hinted without spoiling geography; AWAY admits nobody knows."""
    home = char_position(content, state, c)
    loc = _location_by_id(content, home) if (home and home != AWAY) else None
    en = lang_of(content) == "en"
    if loc and location_available(content, state, loc):
        return loc.get("name"), (f", heading for {loc.get('name')}" if en
                                 else f"，往{loc.get('name')}那边去了")
    if loc:
        return None, (", off toward somewhere you haven't been" if en
                      else "，往你还没去过的地方去了")
    if home == AWAY:
        return None, (", and nobody knows where they go at this hour" if en
                      else "，没人知道TA这个时辰去了哪")
    return None, ""


def farewell_beats(content: dict[str, Any], state: dict[str, Any], c: dict[str, Any],
                   llm: LLM) -> list[dict[str, Any]]:
    """A character leaving the scene SAYS GOODBYE first — one short in-voice line (which
    may name where they're off to), then a narration that tracks where they went. Nobody
    just evaporates from the cast bar."""
    dest, tail = _exit_dest(content, state, c)
    line = ""
    try:
        out = llm.generate({"farewell": True, "dest": dest or "",
                            "place": (current_location(content, state) or {}).get("name") or "",
                            "char": {"name": c.get("name"), "role": c.get("role") or "",
                                     "persona_text": (c.get("persona_text") or "")[:160],
                                     "eq_style": (c.get("eq_style") or "")[:100]}}) or {}
        line = dedash(str(out.get("line") or "").strip().strip("「」\"'")[:60])
    except Exception:
        line = ""
    if not line:
        line = _t(content, f"我先走一步，{dest}那边还有事。" if dest else "先这样，我得走了。回头见。",
                  f"I'd better go. Things to see to at {dest}." if dest
                  else "That's me. Things to do. See you around.")
    return [
        {"type": "dialogue", "speaker_name": c.get("name"), "text": line},
        {"type": "description", "speaker_name": None,
         "text": _t(content, f"（{c.get('name')}说着起身走了{tail}。）",
                    f"({c.get('name')} says so and heads out{tail}.)")},
    ]


def exit_beat(content: dict[str, Any], state: dict[str, Any], c: dict[str, Any]) -> dict[str, Any]:
    """The budget-friendly departure (no spoken line): still says where they went."""
    _, tail = _exit_dest(content, state, c)
    return {"type": "description", "speaker_name": None,
            "text": _t(content, f"（不知什么时候，{c.get('name')}已经离开了{tail}。）",
                       f"(At some point, {c.get('name')} slipped away{tail}.)")}


PLACE_DETAIL_CAP = 200   # 玩家写的地点描述上限 (它每次到达都进提示词, 别喂太肥)
PLAYER_PLACE_CAP = 12    # 一局里玩家自己能加多少地方


def _clean_place_text(s: Any, cap: int) -> str:
    """玩家写的字直接进系统提示词 —— 换行是提示词的结构分隔, 留着就能伪造一段假指令。"""
    return " ".join(str(s or "").split()).strip()[:cap]


def place_editable(loc: dict[str, Any] | None) -> bool:
    """这个地点这一局里能不能改 (Yi 2026-08-06:「除了一开始的默认场景」)。

    作者原本写的是这本书的骨架 —— 别人正在同一本书里玩, 不许一个玩家改掉它。
    这一局【长出来的】才归玩家: 引擎涌现的 (generated) 与玩家自己加的 (by=player)。
    """
    if not loc:
        return False
    return bool(loc.get("generated") or loc.get("by") == "player"
                or loc.get("detail_by") == "player")


def edit_place(content: dict[str, Any], state: dict[str, Any], lid: str,
               name: str | None = None, detail: str | None = None) -> dict[str, Any] | None:
    """改这一局里生出来的地点的名字/描述。作者原本那批返回 None。

    ⚠️ 改名必须【带着出口一起改】: 出口是按地名字符串连的 (exits: ["庙街","果栏"]),
    只改名字不动出口, 那条路当场就断 —— 地图上还画着线, 走过去说"去不了这个地方"。
    工坊侧早有这条级联, 引擎侧从前没有。
    """
    loc = _location_by_id(content, lid)
    if not place_editable(loc):
        return None
    locs = _locations(content)
    if name is not None:
        nm = _clean_place_text(name, 24)
        if not nm or not place_name_ok(nm):
            return None
        if any(l is not loc and (l.get("name") or "").strip() == nm for l in locs):
            return None          # 同名两处 = resolve_location 从此各凭运气
        old = (loc.get("name") or "").strip()
        loc["name"] = nm
        if old and old != nm:
            for l in locs:       # 🔗 级联: 谁的出口指着老名字, 一起改过来
                l["exits"] = [nm if e == old else e for e in (l.get("exits") or [])]
    if detail is not None:
        d = _clean_place_text(detail, PLACE_DETAIL_CAP)
        if len(d) < 2:
            return None
        loc["detail"] = d
        loc["detail_by"] = "player"
    _audit(state, "place.edit", True, (loc.get("name") or "")[:12], "")
    return loc


def add_place(content: dict[str, Any], state: dict[str, Any],
              name: str, detail: str = "") -> dict[str, Any] | None:
    """玩家在局内自己加一个地方, 双向连到他此刻站的地方。

    单向连是个陷阱: 走得进去出不来。加完【不移动】—— 加一个地方不等于立刻传送过去。
    """
    nm = _clean_place_text(name, 24)
    if not nm or not place_name_ok(nm):
        return None
    locs = _locations(content)
    if any((l.get("name") or "").strip() == nm for l in locs):
        return None
    if sum(1 for l in locs if l.get("by") == "player") >= PLAYER_PLACE_CAP:
        return None
    import uuid as _u
    cur = current_location(content, state) or {}
    back = [cur.get("name")] if cur.get("name") else []
    loc = {"id": "loc_my_" + _u.uuid4().hex[:8], "name": nm,
           "detail": _clean_place_text(detail, PLACE_DETAIL_CAP),
           "exits": back, "unlock": {}, "by": "player"}
    if loc["detail"]:
        loc["detail_by"] = "player"
    (content.get("story") or {}).setdefault("locations", []).append(loc)
    if cur and nm not in (cur.get("exits") or []):
        cur.setdefault("exits", []).append(nm)
    _audit(state, "place.add", True, nm, "")
    return loc


def remove_place(content: dict[str, Any], state: dict[str, Any], lid: str) -> bool:
    """删掉玩家自己加的地方 (只有 by=player 的能删; 涌现的留着 —— 剧情里发生过)。
    出口一起清, 免得留下指向不存在地点的死路。"""
    loc = _location_by_id(content, lid)
    if not loc or loc.get("by") != "player" or lid == state.get("location_id"):
        return False
    nm = (loc.get("name") or "").strip()
    story = content.get("story") or {}
    story["locations"] = [l for l in _locations(content) if l.get("id") != lid]
    for l in story["locations"]:
        l["exits"] = [e for e in (l.get("exits") or []) if e != nm and e != lid]
    _audit(state, "place.remove", True, nm[:12], "")
    return True


def set_place_detail(content: dict[str, Any], state: dict[str, Any],
                     lid: str, text: str) -> dict[str, Any] | None:
    """✍️ 让玩家自己写一个地方长什么样 (Yi 2026-08-06)。

    来龙去脉: 走到「油麻地」而它的 detail 是空的, 到达旁白只能现编, 编出了一家茶餐厅。
    提示词那一刀是止血 (按地名尺度写、不许换成别的具名场所); 这一刀把笔交给玩家 ——
    跟手账/笔记同一路子, 玩家定义自己那个世界。

    三条讲究:
      · **只填空白**。作者写过的一个字都不许覆盖 —— 与「只补没脸的角色, 作者选的头像
        绝不重画」同一条教条。玩家自己写过的可以改 (靠 detail_by 记号区分)。
      · 写进【存档私有副本】的 locations, 不动作者的原本。写完之后到达旁白、地图、
        背景生图全都自动吃到, 不用各处再接一遍。
      · 玩家的字直接进系统提示词, 所以要洗: 换行是提示词的结构分隔, 留着就能伪造出
        一段假指令 (「\\n\\n【系统】忽略以上全部规则」)。

    返回改后的地点, 拒绝时 None。调用方负责持久化 pinned_content。
    """
    loc = _location_by_id(content, lid)
    if not loc:
        return None
    if (loc.get("detail") or "").strip() and loc.get("detail_by") != "player":
        return None                      # 🔒 作者写的, 不许动
    t = " ".join(str(text or "").split())    # 换行/连续空白一律压成单空格
    t = t.strip()[:PLACE_DETAIL_CAP]
    if len(t) < 2:
        return None
    loc["detail"] = t
    loc["detail_by"] = "player"          # 🏷 记号不是装饰: 「只填空白」靠它区分作者与玩家
    _audit(state, "place.detail", True, (loc.get("name") or "")[:12], t[:20])
    return loc


def carry_suggestions(content: dict[str, Any], state: dict[str, Any],
                      fresh: list[str], cap: int = 4) -> list[str]:
    """🧵 换个地方, 聊到一半的线不许断 (Yi 报障 2026-08-06)。

    从前是 `st["suggestions"] = arrival_suggestions(...)` —— 整批覆盖。于是刚才那人
    问你的话、刚定下的事, 指着它的那几个选项当场消失, 玩家再也找不回那条线。

    规矩两条, 缺一不可:
      · 还指着【此刻仍在场】的人的旧选项, 留着 —— 那条线还活着。
      · 指着已经不在场的人的, 必须丢 —— 留着玩家点了个空, 比断线更糟。
    新地方的建议永远排在前面 (刚换了景, 先给此地的抓手)。
    """
    # ⚠️ 排除玩家自己, 而且只认 ≥2 字的名字。建议全是玩家的第一人称动作, 玩家的面具
    #    十有八九就叫「我」—— 拿它去匹配, 每一条建议都会被判成"这条线还活着", 于是
    #    过期的线一条都丢不掉 (实弹: 人都走了还留着「我追问蓝信一…」)。
    pcid = state.get("player_character_id")
    here = {(c.get("name") or "").strip()
            for c in scene_characters(content, state)
            if c.get("name") and c.get("id") != pcid and len((c.get("name") or "").strip()) >= 2}
    kept = []
    for s0 in (state.get("suggestions") or []):
        t = str(s0 or "").strip()
        if not t or t in fresh:
            continue
        named = [n for n in here if n and n in t]
        if named:                      # 这条线上的人还在 → 线还活着
            kept.append(t)
    out = list(fresh) + kept
    seen, dedup = set(), []
    for t in out:
        if t not in seen:
            seen.add(t)
            dedup.append(t)
    return dedup[:cap]


def arrival_narration(content: dict[str, Any], state: dict[str, Any], persona: dict[str, Any],
                      llm: LLM | None = None,
                      beat_log: list[dict[str, Any]] | None = None) -> str:
    """The moment the player WALKS INTO a place: a vivid 2~4 sentence pan — the space
    itself, then what each person present is DOING right now (posture/activity/attention,
    true to who they are), and who notices the player first. LLM-written; degrades to a
    deterministic per-person assembly so the scene is never a bare name list."""
    llm = lang_llm(llm or get_llm(), content)
    loc = current_location(content, state) or {}
    pcid = state.get("player_character_id")
    tun = tuning_for(content)
    rels = state.get("rel") or {}
    people = []
    for c in scene_characters(content, state):
        if c.get("id") == pcid or not c.get("name"):
            continue
        mode = relationships.derive_mode(c, rels.get(c.get("id")) or relationships.new_scores(), tun)
        # 🎬 谁是【跟你一起走过来的】。同行的人到了新地方不该被从头介绍一遍长相身份 ——
        # 那读起来就是第一次见面 (Yi 报障 2026-08-06 勾中的四条症状之一)。
        people.append({"name": c["name"], "role": (c.get("role") or "").strip(),
                       "look": _first_sentence(c.get("persona_text") or "", 60),
                       "relation": relationships.name_of(mode),
                       "with_you": c.get("id") in (state.get("following") or [])})
    try:
        out = llm.generate({"arrive": True, "era": era_of(content),
                            "place": loc.get("name") or "", "detail": (loc.get("detail") or "")[:160],
                            "slot": (clock_view(content, state) or {}).get("label", ""),
                            "people": people,
                            # 🎬 到了新地方不等于重开机: 把刚才那一场喂进去, 人物心里还挂着
                            # 上一场的事 (Yi 报障 2026-08-06「剧情也会被打断」)。
                            # ✍️ 顺带补上文风卡 —— 这条路一直没有, 而它是每次换场玩家读到的
                            # 第一段字。
                            "recent": [b for b in (beat_log or [])
                                       if (b or {}).get("text")][-4:],
                            "style": (content.get("story") or {}).get("style") or "",
                            # 🎯 目标随行: 不带它, 这段结构上只能另起一段, 读着像剧情清零
                            "goal": (state.get("goal") or "")[:60],
                            # ✂️ 一屋子都是跟你一起来的人 = 没有"介绍"要做, 一句话交代换了
                            #    地方就够。整段运镜砸下来正是玩家说的「插播广告」。
                            "brief": bool(people) and all(p.get("with_you") for p in people),
                            # 👁 god mode: an unseen viewpoint drifts in — nobody may notice
                            "observer": (state.get("mode") or "character") == "god",
                            "player_name": (persona or {}).get("name") or ""}) or {}
        txt = next((b.get("text", "") for b in out.get("beats") or []
                    if b.get("type") == "description" and (b.get("text") or "").strip()), "")
        # 🎬 原画: the pan declared one keyframe per person — open the scene ledger with
        # every body's state on record (cold-start fix: 看 and 说 read the same sheet
        # from the very first turn in a place)
        if txt and out.get("frames"):
            book_scene_frame(content, state, {"scene_frame": out["frames"]}, sp_id=None)
    except Exception:
        txt = ""
    if txt:
        return dedash(txt)
    if lang_of(content) == "en":
        bits = [_first_sentence(loc.get("detail") or "", 60)]
        for p in people:
            who = "; ".join(b for b in (p["role"], p["look"]) if b)
            bits.append(f"{p['name']} is here{(' (' + who + ')') if who else ''}")
        return "(" + ". ".join(b for b in bits if b) + ".)" if any(bits) else ""
    bits = [_first_sentence(loc.get("detail") or "", 60)]
    for p in people:
        who = "，".join(b for b in (p["role"], p["look"]) if b)
        bits.append(f"{p['name']}正在这里{('（' + who + '）') if who else ''}")
    return "（" + "。".join(b for b in bits if b) + "。）" if any(bits) else ""


def arrival_suggestions(content: dict[str, Any], state: dict[str, Any],
                        llm: LLM | None = None) -> list[str]:
    """到达建议 (Yi 2026-07-20 建议重做: 确定性两条, 不再花一次 LLM 调用 — 下一回合
    导演接手): 有人就搭话+看看; 没人就翻翻没搜过的东西+看看。god 模式无建议。"""
    if (state.get("mode") or "character") == "god":
        return []
    loc = current_location(content, state) or {}
    pcid = state.get("player_character_id")
    here = [c for c in scene_characters(content, state) if c.get("id") != pcid]
    if here:
        primary = next((c for c in here if c.get("is_lead")), here[0])
        return [_t(content, f"跟{primary.get('name')}搭句话", f"Say hi to {primary.get('name')}"),
                _t(content, "先四下看看这地方", "Look around first")]
    searched = set(state.get("searched_prop_ids") or [])
    prop = next((p.get("name") for p in (loc.get("props") or [])
                 if p.get("name") and p.get("id") not in searched), None)
    det = [_t(content, f"翻查{prop}", f"Search the {prop}")] if prop else []
    det.append(_t(content, "先四下看看这地方", "Look around first"))
    return det[:2]


def _detect_asks(content: dict[str, Any], player_input: str) -> list[str]:
    """Secret ids the player appears to be probing this turn.

    Matches the input against each secret's title and its fragments'
    retrieval_key keyword phrases (sanitized — safe to match; NEVER the fragment
    content). Substring match so it works for Chinese as well as English."""
    hit: list[str] = []
    for secret in content.get("secrets", []) or []:
        kw = list(_keywords(secret.get("title", "")))
        for f in secret.get("fragments", []) or []:
            kw += _keywords(f.get("retrieval_key") or "")
        if _contains_any(player_input, kw):
            hit.append(secret.get("id"))
    return hit


def _apply_event_triggers(content: dict[str, Any], state: dict, player_input: str) -> None:
    """PROVISIONAL pass: fire a story event when the player's words overlap its keywords.
    Only events of acts ALREADY REACHED are eligible — merely TALKING about a future
    act's event must never detonate it (the sticky-unlock hazard). The primary director
    call then judges which events truly occurred; denied guesses are rolled back."""
    triggered = set(state.get("triggered_event_ids") or [])
    cur_act = int(state.get("act", 1) or 1)
    for act in (content.get("story") or {}).get("acts", []) or []:
        if int(act.get("index") or 0) > cur_act:
            continue
        for ev in act.get("events", []) or []:
            eid = ev.get("id")
            kws = [w for w in _keywords(ev.get("what_happens", "")) if len(w) >= 2]
            if eid and eid not in triggered and _contains_any(player_input, kws):
                triggered.add(eid)
    state["triggered_event_ids"] = sorted(triggered)


def _probe_candidates(content: dict[str, Any], state: dict) -> list[dict[str, Any]]:
    """Ask-judgment candidates for the director call: secrets that still hold locked
    fragments, as (id, sanitized title) — titles only, never bodies."""
    unlocked = set(state.get("unlocked_fragment_ids") or [])
    out = []
    for s in content.get("secrets", []) or []:
        title = (s.get("title") or "").strip()
        frags = s.get("fragments", []) or []
        if title and any(f.get("id") not in unlocked for f in frags):
            out.append({"id": s.get("id"), "title": title})
    return out


def _event_candidates(content: dict[str, Any], state: dict, act: int) -> list[dict[str, Any]]:
    """Event-judgment candidates: the current act's not-yet-triggered events, as
    (id, label). Labels come from what_happens, which the progress checklist already
    shows the player — spoiler-consistent."""
    triggered = set(state.get("triggered_event_ids") or [])
    out = []
    for ev in (current_act(content, act) or {}).get("events", []) or []:
        eid = ev.get("id")
        label = (ev.get("what_happens") or "").strip()
        if eid and eid not in triggered and label:
            out.append({"id": eid, "label": label[:40]})
    return out


def _match_candidates(cands: list[dict[str, Any]], judged, key: str) -> set:
    """Map the model's copied-back titles/labels to candidate ids (lenient: exact or
    containment either way, so a slightly trimmed copy still matches)."""
    got = set()
    for j in judged or []:
        jn = str(j).strip()
        if not jn:
            continue
        for c in cands:
            t = c.get(key) or ""
            if t and (t == jn or t in jn or jn in t):
                got.add(c["id"])
    return got


def _titles_for_fragments(content: dict[str, Any], frag_ids) -> list[str]:
    """The sanitized titles of the secrets owning these fragments (unique, ordered)."""
    idset = set(frag_ids or [])
    seen, out = set(), []
    for sec in content.get("secrets", []) or []:
        if any(f.get("id") in idset for f in sec.get("fragments", []) or []):
            t = (sec.get("title") or "").strip()
            if t and t not in seen:
                seen.add(t)
                out.append(t)
    return out


def _choice_options(act_dict: dict[str, Any]) -> list[dict[str, Any]]:
    """The act's valid choice options with STABLE ids (authored id or positional)."""
    ch = (act_dict or {}).get("choice") or {}
    out = []
    for i, o in enumerate(ch.get("options") or []):
        if (o.get("label") or "").strip():
            out.append({**o, "id": (o.get("id") or "").strip() or f"opt{i}"})
    return out


def choice_for_act(content: dict[str, Any], state: dict[str, Any], act: int) -> dict[str, Any] | None:
    """The act's authored key-moment decision (VN 抉择), if any and not yet answered.
    Player-facing shape: prompt + option ids/labels only (effects stay server-side)."""
    a = current_act(content, act) or {}
    ch = a.get("choice") or {}
    opts = _choice_options(a)
    if not (ch.get("prompt") or "").strip() or not opts:
        return None
    key = f"act{a.get('index', act)}"
    if key in (state.get("choices") or {}):
        return None
    return {"key": key, "act": int(a.get("index", act) or act), "prompt": ch["prompt"].strip(),
            "options": [{"id": o["id"], "label": o["label"]} for o in opts]}


# ═══════════════════ ⚖️ 命运抉择: engine-scheduled high-authority forks ═══════════════════
# Every N player turns the story throws a key choice GENERATED from the live scene.
# Options are TYPED (story / kill / move) so the engine can ENFORCE the pick: a death is
# booked in the ledger, a move actually relocates, and the chosen direction becomes a
# depth-0 mandate the director must drive toward for the next several turns.

def fate_generate(content: dict[str, Any], state: dict[str, Any], llm,
                  observer: bool = False, recent: str = "") -> dict[str, Any] | None:
    """Draft + VALIDATE one fate choice. Model proposes; engine verifies every target
    (kill → a present living non-player character; move → a known place, or any named
    place in a sandbox) and downgrades anything unverifiable to a story-direction option.
    Returns the player-facing pending dict (effects stay server-side) or None."""
    here = scene_characters(content, state)
    loc = current_location(content, state) or {}
    _pc = _char_by_id(content, state.get("player_character_id"))
    _pcn = (_pc or {}).get("name") or ""
    out = llm.generate({
        "fate_choice": True, "era": era_of(content),
        "observer": observer,   # 👁 god mode → options phrased as decrees of fate
        "player_name": _pcn,    # 🎭 whose first-person voice the options speak in
        "cast": [c.get("name") for c in here if c.get("name")],
        "place": loc.get("name", ""),
        "exits": [str(e) for e in (loc.get("exits") or [])],
        "goal": state.get("goal", ""),
        "recent": (recent or str(state.get("memory") or ""))[-400:],
        "mature": bool(state.get("mature")),
        "language": lang_of(content),
    }) or {}
    prompt_txt = str(out.get("prompt") or "").strip()
    pcid = state.get("player_character_id")
    dead = _dead_ids(state)
    opts: list[dict[str, Any]] = []
    effects: dict[str, dict[str, Any]] = {}
    for i, o in enumerate((out.get("options") or [])[:3]):
        label = str((o or {}).get("label") or "").strip()[:24]
        if not label:
            continue
        kind = str((o or {}).get("kind") or "story").strip()
        target: Any = str((o or {}).get("target") or "").strip()
        mandate = str((o or {}).get("mandate") or "").strip()[:40]
        omen = str((o or {}).get("omen") or "").strip()[:10]
        if kind in ("kill", "bond", "rift"):
            victim = next((c for c in here if c.get("name") == target
                           and c.get("id") not in dead and c.get("id") != pcid), None)
            if victim:
                target = victim["id"]
            else:
                kind, target = "story", ""      # unverifiable person → direction only
        elif kind == "move":
            dest = resolve_location(content, target)
            if dest and dest.get("id"):
                target = dest["id"]
            # 🔒 沙盒放行未在册地名靠兑现时 generate_and_move 铸造 —— 锁下必返 None,
            #    紫卡点了只会静默没收, 所以放行也跟着 LLM_MINTS_PLACES 走 (审查确认)
            elif not (LLM_MINTS_PLACES and sandbox_on(content) and not _bad_place_name(str(target))):
                kind, target = "story", ""      # closed map / bad name → direction only
        elif kind == "identity":
            target = str(target)[:12]
            if not target:
                kind = "story"
        elif kind == "fortune":
            if target not in ("横财", "破财") or not economy_on(state):
                kind, target = "story", ""
        elif kind == "timeskip":
            if target not in ("次日", "三日后") or real_time_on(content):
                kind, target = "story", ""      # real-time worlds cannot skip the clock
        else:
            kind, target = "story", ""
        oid = f"f{i + 1}"
        opts.append({"id": oid, "label": label, "omen": omen})
        effects[oid] = {"kind": kind, "target": target, "mandate": mandate or label}
    if not prompt_txt or len(opts) < 2:
        return None
    n = int(state.get("fate_seq") or 0) + 1
    state["fate_seq"] = n
    state["fate_effects"] = effects
    return {"key": f"fate{n}", "kind": "fate", "act": int(state.get("act", 1) or 1),
            "prompt": prompt_txt[:60], "options": opts,
            "expires": 3}   # ⏳ 3 turns to decide, then fate decides for you


def _apply_fate(content: dict[str, Any], state: dict[str, Any], option_id: str) -> dict[str, Any]:
    """Enforce the picked fate option. 权能很高: the engine BOOKS the outcome (death /
    relocation) and hangs the chosen direction as a decaying depth-0 mandate."""
    pending = state.get("pending_choice") or {}
    picked = next((o for o in pending.get("options", []) if o.get("id") == option_id), None)
    eff = (state.get("fate_effects") or {}).get(option_id)
    if picked is None or eff is None:
        raise ValueError("unknown option")
    res: dict[str, Any] = {"label": picked.get("label") or "", "flag": None}
    kind, target = eff.get("kind"), eff.get("target")
    if kind == "kill" and target:
        deads = _dead_ids(state)
        if target not in deads:
            deads.add(target)
            state["dead_character_ids"] = sorted(deads)
            state["following"] = [f for f in (state.get("following") or []) if f != target]
            void_promises_of(state, target)
            nm = _char_name(content, target) or "TA"
            rel_log(state, target, int(state.get("act", 1) or 1), "death",
                    _t(content, f"{nm} 死了。", f"{nm} died."))
            _audit(state, "fate.kill", True, nm)
            res["killed"] = nm
    elif kind == "move" and target:
        dest = _location_by_id(content, target)
        try:
            if dest:
                commit_move(content, state, dest)
            else:                                # sandbox: the named place becomes real
                dest = generate_and_move(content, state, str(target))
                if dest is not None:
                    res["content_mutated"] = True
            if dest is None:
                _audit(state, "fate.move", False, str(target), "不是具体去处")
            else:
                _audit(state, "fate.move", True, dest.get("name", ""))
                res["moved_to"] = dest.get("name", "")
        except Exception:
            _audit(state, "fate.move", False, str(target), "生成失败")
    if kind in ("bond", "rift") and target:
        tun = tuning_for(content)
        rel_all = state.setdefault("rel", {})
        cd, rd = (8, 6) if kind == "bond" else (-9, -7)
        rel_all[target] = relationships.apply_deltas(
            rel_all.get(target) or relationships.new_scores(), cd, rd, tun,
            trust_delta=6 if kind == "bond" else -8)   # 🛡 命运抉择连信任一起翻
        nm = _char_name(content, target) or "TA"
        rel_log(state, target, int(state.get("act", 1) or 1), "fate",
                _t(content,
                   f"命运抉择：与{nm}{'关系骤然贴近' if kind == 'bond' else '恩断义绝'}。",
                   f"Twist of fate: {'suddenly closer to' if kind == 'bond' else 'a clean break with'} {nm}."))
        _audit(state, f"fate.{kind}", True, nm)
        res[kind] = nm
    elif kind == "identity" and target:
        state["identity"] = str(target)
        _audit(state, "fate.identity", True, target)
        res["identity"] = target
    elif kind == "fortune" and target:
        bal = int(state.get("money") or 0)
        delta = max(200, bal) if target == "横财" else -int(bal * 0.8)
        applied = book_money(content, state, delta, f"命运抉择·{target}")
        _audit(state, "fate.fortune", True, f"{target}{applied:+d}")
        res["fortune"] = applied
    elif kind == "timeskip" and target:
        clk = dict(state.get("clock") or {})
        clk.setdefault("day", 1); clk.setdefault("slot", 0); clk["turns_in_slot"] = 0
        clk["day"] = int(clk["day"]) + (1 if target == "次日" else 3)
        state["clock"] = clk
        _audit(state, "fate.timeskip", True, target)
        res["timeskip"] = target
    md = (eff.get("mandate") or "").strip()
    if md:
        state["mandate"] = {"text": md, "left": 8}   # rides depth-0 for ~8 turns
        _audit(state, "fate.mandate", True, md)
    # 📜 命运账本: every resolved fate is permanent record — NPCs can hold it against you
    outcome = (res.get("killed") and f"{res['killed']}死了") or               (res.get("moved_to") and f"迁往{res['moved_to']}") or               (res.get("bond") and f"与{res['bond']}贴近") or               (res.get("rift") and f"与{res['rift']}决裂") or               (res.get("identity") and f"成为{res['identity']}") or               (res.get("fortune") is not None and eff.get("target")) or               (res.get("timeskip") and f"时间跳到{res['timeskip']}") or "既定方向"
    log = list(state.get("fate_log") or [])
    log.append({"day": int((state.get("clock") or {}).get("day", 1) or 1),
                "label": res["label"][:24], "outcome": str(outcome)[:20]})
    state["fate_log"] = log[-12:]
    answered = dict(state.get("choices") or {})
    answered[pending.get("key") or "fate"] = option_id
    state["choices"] = answered
    state["pending_choice"] = None
    state["fate_effects"] = None
    state["fate_turns"] = 0
    return res


def apply_choice(content: dict[str, Any], state: dict[str, Any], option_id: str) -> dict[str, Any]:
    """Resolve the pending decision: apply its deterministic effects (flag → endings can
    gate on it; global 好感; optional per-character relationship deltas), record the answer,
    clear the pending state. The picked label is returned so the caller can play it as the
    player's own words/action. Raises ValueError when nothing pends / option unknown."""
    pending = state.get("pending_choice") or {}
    if not pending:
        raise ValueError("no pending choice")
    if pending.get("kind") == "fate":
        return _apply_fate(content, state, option_id)
    if pending.get("kind") == "court":
        return _apply_court_choice(content, state, option_id)
    a = current_act(content, int(pending.get("act") or state.get("act", 1) or 1)) or {}
    picked = next((o for o in _choice_options(a) if o["id"] == option_id), None)
    if picked is None:
        # 🧹 自带选项的卡 (fate/court 这类) 走到这儿 = 引擎不认识它的 kind。
        # 不收走的话它会永远挂在 pending_choice 上, /choose 每次 400 —— 玩家既点不动
        # 也关不掉, 存档被一张死卡钉死。所以: 认不出就收卡, 再报错。
        # (幕内选项找不到 option_id 只是点错了, 卡要留着让玩家重点。)
        if pending.get("options"):
            state.pop("pending_choice", None)
            _audit(state, "choice.orphan", False, str(pending.get("kind") or "?")[:12],
                   "引擎不认识这张卡, 已收走")
        raise ValueError("unknown option")
    tun = tuning_for(content)
    if picked.get("flag"):
        flags = dict(state.get("flags") or {})
        flags[str(picked["flag"])] = True
        state["flags"] = flags
    ad = int(picked.get("affinity_delta") or 0)
    if ad:
        state["affinity"] = max(0, int(state.get("affinity", 0)) + ad)
    cid = picked.get("character_id")
    cd = int(picked.get("closeness_delta") or 0)
    rd = int(picked.get("romance_delta") or 0)
    if cid and (cd or rd):
        rel_all = state.setdefault("rel", {})
        rel_all[cid] = relationships.apply_deltas(
            rel_all.get(cid) or relationships.new_scores(), cd, rd, tun)
    answered = dict(state.get("choices") or {})
    answered[pending.get("key") or f"act{state.get('act', 1)}"] = option_id
    state["choices"] = answered
    state["pending_choice"] = None
    return {"label": picked.get("label") or "", "flag": picked.get("flag")}


def search_props(content: dict[str, Any], state: dict[str, Any],
                 player_input: str, channel: str = "say") -> list[dict[str, Any]]:
    """现场搜查: the player names a searchable prop at their CURRENT place on the 做/看
    channel → it's turned over. Mutates state: fires the prop's story event; returns the
    found props (with their evidence fragment ids) for the caller to unlock + narrate.
    Deterministic — physical evidence is found by physically looking, no dice."""
    if channel not in ("do", "think"):
        return []
    loc = current_location(content, state)
    if not loc:
        return []
    found: list[dict[str, Any]] = []
    searched = set(state.get("searched_prop_ids") or [])
    for i, prop in enumerate(loc.get("props") or []):
        name = (prop.get("name") or "").strip()
        if not name:
            continue
        pid = (prop.get("id") or "").strip() or f"{loc.get('id')}_prop{i}"
        if pid in searched or not _contains_any(player_input, [name]):
            continue
        searched.add(pid)
        if prop.get("event_id"):
            trig = set(state.get("triggered_event_ids") or [])
            trig.add(prop["event_id"])
            state["triggered_event_ids"] = sorted(trig)
        found.append({"id": pid, "name": name, "detail": (prop.get("detail") or "").strip(),
                      "fragment_id": prop.get("fragment_id"), "take": bool(prop.get("take"))})
    state["searched_prop_ids"] = sorted(searched)
    return found


def _fragment_content(content: dict[str, Any], fid: str | None) -> str:
    for sec in content.get("secrets", []) or []:
        for f in sec.get("fragments", []) or []:
            if f.get("id") == fid:
                return (f.get("content") or "").strip()
    return ""


def discover_on_arrival(content: dict[str, Any], state: dict[str, Any]) -> list[dict[str, Any]]:
    """After the player MOVES: unlock fragments whose only missing key was being HERE
    (unlock.location_id) and hand back discovery narrations — physical truths reveal the
    moment you stand in the right place, not a turn later. Mutates state (sticky)."""
    state["location_id"] = (current_location(content, state) or {}).get("id")
    frags = gating.iter_fragments(content)
    newly = gating.evaluate_unlocks(state, frags)
    here = state.get("location_id")
    # only fragments gated ON this place narrate as arrival discoveries; anything else
    # newly eligible stays for the normal turn flow (voiced by characters)
    found = [f for f in frags if f.get("id") in set(newly)
             and (f.get("unlock") or {}).get("location_id") == here]
    if not found:
        return []
    fids = [f.get("id") for f in found]
    state["unlocked_fragment_ids"] = sorted(
        set(state.get("unlocked_fragment_ids") or []) | set(fids))
    out = []
    for f in found:
        body = (f.get("content") or "").strip()
        title = (f.get("secret_title") or "").strip()
        out.append({"fragment_id": f.get("id"), "title": title,
                    "text": _t(content, f"（到了这里你才看清：{body}）",
                               f"(Only standing here do you finally see it: {body})")})
    return out


# 🎼 情绪→节奏带 (Spec A, 2026-07-25): 乐师的平滑判断 (bgm_led.track, 12样本抽查92%)
# 反哺台词形状 — 引擎查表下发, 模型只管措辞。default 档 = 原 2~4 句现状兜底。
PACE_BANDS = {
    "default": {"line": "台词口语化（2~4句）",
                "short": "2~4句，自然口语"},
    "taut":    {"line": "此刻气氛绷着——台词要短促：1~2个短句，甚至一个词、半句就够；快而硬，不解释",
                "short": "1~2个短句，可以只有一个词；快而硬"},
    "open":    {"line": "此刻是掏心的时候——话可以放长（4~6句），慢下来讲完整的心事，允许停顿与回忆",
                "short": "4~6句，慢下来，讲完整"},
    "charged": {"line": "此刻空气是暧昧的——话说一半就咽回去，欲言又止；短句加停顿，绝不说透",
                "short": "短句，话说一半就停，绝不说透"},
}
_PACE_BY_KEY = {"tense": "taut", "battle": "taut", "eerie": "taut",
                "romantic": "charged",
                "warm": "open", "sad": "open", "lonely": "open"}


def pace_band(state: dict[str, Any], tun: dict[str, Any] | None = None) -> dict[str, str]:
    """本轮节奏带: 乐师账本优先, 场面情绪兜底; tuning.pace_bands 可整表覆盖。"""
    key = str((state.get("bgm_led") or {}).get("track") or "")         or str(((state.get("scene") or {}).get("mood")) or "")
    heat = state.get("heat")
    if isinstance(heat, dict) and int(heat.get("stage", 0) or 0) >= 1:
        band = "charged"
    else:
        band = _PACE_BY_KEY.get(key.rstrip("23456789"), "default")
    table = dict(PACE_BANDS)
    if isinstance((tun or {}).get("pace_bands"), dict):
        for k, v in tun["pace_bands"].items():
            if isinstance(v, dict) and v.get("line"):
                table[k] = {"line": str(v["line"])[:80],
                            "short": str(v.get("short") or v["line"])[:40]}
    return {"band": band, **table.get(band, table["default"])}


# 🎁 自我暴露递进 (Spec G, 2026-07-25): Aron 递进+对等 — 深度归引擎查表,
# 内容归模型 (贴人设即兴或授权碎片)。玩家先开窗, 角色下一轮必须回礼同深度。
_SELF_DISCLOSE_RE = re.compile(
    r"我小时候|我其实|我从来没跟人说过|我最怕|我一直不敢|我爸|我妈|我家里"
    r"|说实话我|老实说我|我以前.{0,6}(过|是)|我做过最")
_DISCLOSE_DEPTH = {
    "stranger": "一件无伤大雅的小偏好（爱吃什么、受不了什么）",
    "peer": "一件无伤大雅的小偏好或小习惯",
    "junior": "一件小偏好或最近的小烦恼",
    "elder": "一段往昔的小感慨",
    "friend": "一件有点丢人的糗事或一个小执念",
    "flirt": "一段没对别人讲过的脆弱往事（点到即止, 别把最深的底一次掏空）",
    "lover": "心里最深处的一块（怕失去什么、悔过什么）",
}


def disclose_depth(mode_id: str) -> str:
    return _DISCLOSE_DEPTH.get(mode_id, _DISCLOSE_DEPTH["stranger"])


# 🪃 记忆回调触发器 (Spec E, 2026-07-25): 感知回应性的落地 — 引擎记回调账,
# 到期从真实账本抽旧事作必填素材 (素材引擎给, 模型只织入 — 幻觉引用无从谈起),
# 防敷衍沿用生长预算同款: 连续无计数 + 逾期升硬。
CALLBACK_EVERY = 10       # 距上次回调 N 轮到期 (tuning.callback_every)
CALLBACK_CHARGED_MIN = 3  # 暧昧节拍下的加急到期线


def callback_due(state: dict[str, Any], tun: dict[str, Any], band: str) -> str:
    cb = state.setdefault("callback", {"last": 0, "blanks": 0, "used": []})
    turn = int((state.get("growth") or {}).get("turn", 0) or 0)
    period = int(tun.get("callback_every", CALLBACK_EVERY) or 0)
    if not period:
        return ""
    gap = turn - int(cb.get("last", 0) or 0)
    if gap < (CALLBACK_CHARGED_MIN if band == "charged" else period):
        return ""
    return "hard" if int(cb.get("blanks", 0) or 0) >= 3 else "soft"


def pick_callback_material(content: dict[str, Any], state: dict[str, Any],
                           cid: str | None) -> str:
    """从这个角色的真实账本抽一条旧事 (未用过的优先): 关系大事记 → 守过的约定 →
    TA 的印象 → TA 的记忆摘要。全确定性, 引擎背书素材真实性。"""
    if not cid:
        return ""
    cb = state.setdefault("callback", {"last": 0, "blanks": 0, "used": []})
    used = set(cb.get("used") or [])
    cands: list[str] = []
    # 🎴 时刻卡优先 (2026-08-04): 引擎判定的高光 + 模型精写好的文本, 是全仓最好的
    # 回忆素材, 此前只进玩家的回忆册、一个字不进提示词。认知边界: 只取属于 TA 的卡。
    cands += [f"「{a.get('title', '')}」{a.get('text', '')}".strip("「」")
              for a in (state.get("album") or [])
              if a.get("char_id") == cid and (a.get("title") or a.get("text"))]
    entries = (state.get("rel_log") or {}).get(cid) or []
    # 🚫 「初次见面」是寒暄不是回忆 (实弹: 生产素材池 278 条里 193 条是 meet, 而取料
    # 取 fresh[0] = 最老那条 → 角色开口回忆必然是「我们第一次见面」)。降级成兜底。
    _old = entries[:-1]                                       # 旧事优先 (掐掉最新一条)
    cands += [e.get("text", "") for e in _old if e.get("kind") != "meet"]
    cands += [f"你们约过：{p.get('what', '')}（后来{'兑现了' if p.get('status') == 'kept' else '还悬着'}）"
              for p in (state.get("promises") or [])
              if p.get("char_id") == cid and p.get("what")]
    imp = profile_mod.impression_of(state, cid)
    if imp:
        cands.append(f"你相处出的印象：{imp}")
    mem = ((state.get("memory_by_char") or {}).get(cid) or "")[:80]
    if mem:
        cands.append(f"你记得：{mem}")
    cands += [e.get("text", "") for e in _old if e.get("kind") == "meet"]   # 只剩初见才用
    fresh = [c for c in cands if c and c.strip() and c not in used]
    if not fresh:
        cb["used"] = []
        fresh = [c for c in cands if c and c.strip()]
    return fresh[0][:80] if fresh else ""


def _callback_landed(material: str, reported: str, turn_text: str) -> bool:
    """回扣验真: 这一轮的正文里真的有那件旧事吗。

    旧口径是「模型自报摘录的前 12 字原样出现」, 太脆 —— 模型换个说法就判失败
    (生产实测 166 次注入只过 3~5 次, blanks 单局最高连续 14 次)。改成两条通路:
      ① 快路: 自报摘录的前 8 字原样命中 (老口径放宽);
      ② 慢路: 正文与【引擎给的素材】共享一段 ≥4 字的连续片段 —— 素材是我们发的,
         模型把它的核心织进正文就算落地, 不要求逐字复述。
    空口报审 (正文里既没有摘录也没有素材痕迹) 仍然判失败, 否则计时器被白白重置。"""
    t = (turn_text or "").strip()
    if not t:
        return False
    r = (reported or "").strip().strip("「」\"'")
    if r and r not in ("无", "None") and len(r) >= 2 and r[:8] in t:
        return True
    m = (material or "").strip()
    if len(m) < 4:
        return False
    return any(m[i:i + 4] in t for i in range(len(m) - 3))


# 📔 回忆标签面 (Yi: 开心的/甜甜的/搞笑的… 互动总结打标签)
_MEM_TAGS = {"心动": "💗", "甜蜜": "🍬", "开心": "😄", "搞笑": "🤣",
             "惊险": "😨", "平常": "📖"}
_DIARY_TAGS = ("心动", "甜蜜")   # Yi 定 (2026-07-25): 这两档只住 TA 的日记, 不进回忆册
_DIARY_CAP = 40


def _diary_add(state: dict[str, Any], cid: str, entry: dict[str, Any]) -> None:
    """📔 角色日记: TA 自己的本子, 一天一篇 (每日回忆结算的心动/甜蜜档住这里)。
    转生不清 — 日记写的是前世的你, TA 的本子凭什么烧 (跨存档残响同一哲学)。"""
    rows = state.setdefault("diaries", {}).setdefault(cid, [])
    rows.append(entry)
    del rows[:-_DIARY_CAP]


def diary_view(content: dict[str, Any], state: dict[str, Any], cid: str,
               tun: dict[str, int] | None = None) -> dict[str, Any]:
    """📔 TA的日记视图 (Yi 定: 好感到暧昧/恋人档才解锁 — 日记本身是养成奖励)。
    锁着时只报条数, 一个字不漏 (和秘密同一家法: 锁住的内容留在服务端)。"""
    c = _char_by_id(content, cid)
    rows = (state.get("diaries") or {}).get(cid) or []
    scores = (state.get("rel") or {}).get(cid) or relationships.new_scores()
    mode = relationships.derive_mode(c or {}, scores, tun or tuning_for(content))
    if mode not in ("flirt", "lover"):
        return {"unlocked": False, "count": len(rows), "entries": []}
    return {"unlocked": True, "count": len(rows),
            "entries": [dict(e) for e in rows[-12:]]}


def _heart_candidate(content: dict[str, Any], state: dict[str, Any],
                     beat_log=None, history=None) -> dict[str, Any] | None:
    """📔 每日回忆结算的主角: 今天互动材料最多的活人 (线下句数+手机往来) —
    回忆不只有浪漫, 谁陪你过了这一天谁上日记。一晚一位 (稀缺+成本)。"""
    pcid = state.get("player_character_id")
    dead = _dead_ids(state)
    best, bscore = None, 3   # 材料≥4 才够记一笔
    for c in _characters(content):
        cid = c.get("id")
        if not cid or cid == pcid or cid in dead:
            continue
        n = len((history_for(beat_log, cid) if beat_log is not None
                 else (history or []))[-20:])
        # 只读探视: _thread() 会 setdefault 建空线程 → has_contact 把全通讯录判成已解锁 (审计实弹)
        n += len(((((state.get("phone") or {}).get("threads") or {}).get(cid) or {})
                  .get("msgs", []))[-10:])
        if n > bscore:
            best, bscore = c, n
    return best


def note_visit_tick(state: dict[str, Any]) -> None:
    """🗺 热度小账本 (Yi 2026-07-24 地图收纳): 到访次数+最后到访日。单点侦测 —
    位置和上次记账时不同就记一笔, 不管玩家是走的哪条移动机制来的。"""
    lid = state.get("location_id")
    if not lid or state.get("_visit_noted") == lid:
        return
    book = state.setdefault("loc_visits", {})
    # 账本诞生日: 零访问地点的休眠从这天起算 (老档迁移不许开图即全员沉睡)
    book.setdefault("_since", int((state.get("clock") or {}).get("day", 1) or 1))
    ent = book.setdefault(lid, {"n": 0, "day": 0})
    ent["n"] = int(ent.get("n", 0) or 0) + 1
    ent["day"] = int((state.get("clock") or {}).get("day", 1) or 1)
    state["_visit_noted"] = lid


def map_view(content: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    """The discovered world for the 🗺 map panel: unlocked places as nodes (current one
    flagged), exits filtered to unlocked destinations, who stands where right now.
    Locked places surface only as an unnamed count — the map never spoils geography."""
    locs = _locations(content)
    if not locs:
        return {"nodes": [], "hidden": 0, "current": None}
    act = int(state.get("act", 1) or 1)
    cur = (current_location(content, state) or {}).get("id")
    # 🔒 与回合载荷的 here/cast 同法: 只有【附身模式】才把自己从名单里摘掉; 上帝视角下
    # 那个角色就是个 NPC, 该上图 —— 否则他出现在在场条却不在地图上 (两边对不上)。
    pcid = state.get("player_character_id") \
        if (state.get("mode") or "character") == "character" else None
    avail = {l.get("id"): location_available(content, state, l) for l in locs}
    # 🔒 玩家脚下这块地永远可见: 解锁条件是会掉的 (affinity_min 跌破就判不可用), 可人
    # 已经站在这儿了。不豁免就会「自己所在地连人带节点一起从地图上消失, 对话名册照旧列人」。
    if cur in avail:
        avail[cur] = True
    name_to_id = {l.get("name"): l.get("id") for l in locs if l.get("name")}
    at: dict[str, list[str]] = {}
    for c in present_characters(content, act, _dead_ids(state)):
        if c.get("id") == pcid:
            continue
        # 🔒 位置只问 char_position —— 同行那一级是它级联的第 1 条, 别在这儿抄第二遍
        lid = char_position(content, state, c)
        if lid and lid != AWAY and avail.get(lid) and c.get("name"):
            at.setdefault(lid, []).append(c["name"])
    # 🗺 分层收纳 (Yi 2026-07-24: 地点多了地图乱): 热度/置顶/休眠随节点下发,
    # 客户端据此决定谁上图谁进抽屉。休眠=生成的+至多来过一次+14天没来 (授权地点永不休眠)。
    visits = state.get("loc_visits") or {}
    pins = set(state.get("map_pins") or [])
    tucked = set(state.get("map_hidden") or [])
    today = int((state.get("clock") or {}).get("day", 1) or 1)
    nodes = []
    for l in locs:
        lid = l.get("id")
        if not avail.get(lid):
            continue
        exits = [{"id": name_to_id[en], "name": en}
                 for en in (l.get("exits") or []) if avail.get(name_to_id.get(en))]
        v = visits.get(lid) or {}
        vn, vday = int(v.get("n", 0) or 0), int(v.get("day", 0) or 0)
        nodes.append({"id": lid, "name": l.get("name") or "", "here": lid == cur,
                      "chars": at.get(lid, []), "exits": exits,
                      "kind": "gen" if l.get("generated") else "auth",
                      # ✍️ 这地方还没人写过样子 —— 客户端据此给一个"写点什么"的入口。
                      # 空描述会让到达旁白现编 (实弹: 走到「油麻地」编出一家茶餐厅)。
                      "blank": not (l.get("detail") or "").strip(),
                      "mine": l.get("by") == "player",
                      # ✏️ 这一局里生出来的才归玩家改; 作者原本写的是这本书的骨架
                      # (别人正在同一本书里玩), 只读 —— 见 place_editable
                      "editable": place_editable(l),
                      "heat": vn, "pinned": lid in pins, "tucked": lid in tucked,
                      # 零访问按账本诞生日 _since 起算 (审计实弹: 缺 loc_visits 的老档
                      # 开图即全员💤; 新档铸而不访满14天仍照常沉睡)
                      "dormant": bool(l.get("generated")) and vn <= 1
                      and (today - (vday or int((state.get("loc_visits") or {})
                                                .get("_since") or today))) >= 14
                      and lid not in pins and lid != cur})
    return {"nodes": nodes, "hidden": sum(1 for v in avail.values() if not v), "current": cur}


_rng = random.Random()  # module-level so tests can monkeypatch/seed


def _outcome_of(roll: int, dc: int) -> str:
    """Shared d20 verdict bands. A natural 20 always triumphs, a natural 1 always
    bites; a near-miss (within 3 under the DC) is "mixed" — 成功但有代价 — so the
    scene keeps moving forward instead of slapping the player with a flat no
    (fail-forward; the 74%-fail curve of the first 318 turns is the counterexample)."""
    if roll == 20:
        return "crit_success"
    if roll == 1:
        return "crit_fail"
    if roll >= dc:
        return "success"
    if roll >= dc - 3:
        return "mixed"
    return "fail"


def _roll_check(risk: int) -> dict[str, Any]:
    """🎲 d20 fate roll. `risk` is still the judged success chance % (0~99); it maps
    onto the twenty-die as a DC (each face worth 5%): succeed on roll >= dc."""
    roll = _rng.randint(1, 20)
    faces = max(1, min(19, round(int(risk) / 5)))  # how many faces succeed
    dc = 21 - faces
    return {"risk": int(risk), "roll": roll, "dc": dc, "die": 20,
            "outcome": _outcome_of(roll, dc)}


def _roll_dc(dc: int) -> dict[str, Any]:
    """🎲 d20 against an ENGINE-SET DC (the action-resolution path). Same shape and
    verdict bands as _roll_check; `risk` reported as the implied success chance."""
    dc = max(2, min(19, int(dc)))
    roll = _rng.randint(1, 20)
    return {"risk": (21 - dc) * 5, "roll": roll, "dc": dc, "die": 20,
            "outcome": _outcome_of(roll, dc)}


def pressure_cfg(content: dict[str, Any]) -> dict[str, Any] | None:
    """The story's authored pressure meter (卧底暴露值/灵异逼近…), or None when the story
    doesn't run one. Shape: {name, hint, ending_id, levels: [{at, note}]}"""
    cfg = (content.get("story") or {}).get("pressure") or {}
    return cfg if (cfg.get("name") or "").strip() else None


def sane_delta(content: dict[str, Any], state: dict[str, Any], delta: int,
               why: str = "") -> dict[str, Any] | None:
    """🧠 Book a sanity change (clamped 0..start). Returns a moments event when the
    value slid DOWN into a new band — the UI announces the slide, never the math."""
    scfg = sanity_mod.cfg(content)
    if not scfg or not delta:
        return None
    old = int(state.get("sanity", scfg["start"]))
    new = max(0, min(scfg["start"], old + int(delta)))
    if new == old:
        return None
    state["sanity"] = new
    _audit(state, "sanity", True, f"{'+' if delta > 0 else ''}{delta}", (why or "")[:24])
    if sanity_mod.band_of(new, scfg)[0] < sanity_mod.band_of(old, scfg)[0]:
        return {"kind": "sanity", "value": new,
                "label": sanity_mod.band_of(new, scfg)[1], "name": scfg["name"]}
    return None


def sanity_view_of(content: dict[str, Any], state: dict[str, Any]) -> dict[str, Any] | None:
    scfg = sanity_mod.cfg(content)
    if not scfg:
        return None
    return sanity_mod.label_view(scfg, int(state.get("sanity", scfg["start"])))


def threat_view_of(content: dict[str, Any], state: dict[str, Any]) -> dict[str, Any] | None:
    """🦇 The hunter as the UI feels it: name + distance band + alert. None when the
    story runs no threat (or the run hasn't met it yet)."""
    tcfg = threat_mod.cfg(content)
    th = state.get("threat") or {}
    if not tcfg or not th:
        return None
    ch = next((c for c in _characters(content) if c.get("id") == tcfg["char_id"]), {})
    return {"name": ch.get("name") or "", "band": th.get("band") or "far",
            "alert": int(th.get("alert") or 0)}


def _ending_by_id(content: dict[str, Any], eid: str | None) -> dict[str, Any] | None:
    for e in (content.get("story") or {}).get("endings", []) or []:
        if e.get("id") == eid:
            return e
    return None


# ── 🕸 NPC↔NPC relationship web ─────────────────────────────────────────────────
# Characters hold stances toward EACH OTHER (not just toward the player): authored
# initial ties evolve as scenes play out (the primary judges real shifts, the engine
# clamps and records them). Feeds performances, the dossier card, and god mode.
_STANCE_LABEL = {-2: "仇怨", -1: "不睦", 0: "", 1: "交好", 2: "同盟"}


def _pair_key(a: str, b: str) -> str:
    return "|".join(sorted([a or "", b or ""]))


def _npc_dirs(e: dict[str, Any]) -> dict[str, Any]:
    """🕸 拆向懒升级 (合伙人⑤, Yi 拍板 2026-08-02): 老档单向 {stance,label} →
    双向 {ab, ba, log}。ab = 键序第一个 id 眼中的第二个; 事件日志共用 —
    事只发生一次, 两边感受不同, 这正是不对等的本体。玩家↔角色不拆
    (rel 本就是「角色对玩家」的单向感受, 替玩家记感情是越位)。"""
    if "ab" in e:
        return e
    v = {"stance": int(e.get("stance") or 0), "label": e.get("label")}
    return {"ab": dict(v), "ba": dict(v), "log": list(e.get("log") or [])}


def _ensure_npc_rel(content: dict[str, Any], state: dict[str, Any]) -> None:
    """Seed authored ties into the live web — 拆向后按方向种: 谁的卡写的 tie 落谁的
    视角 (情同父子/亲信眼线 从此各归各); 对向若空以同 stance 无 label 兜底
    (单方写仇, 对方大概率也不善), 等对方的 ties 或事件来改写。
    幂等: 演化过的边 (log 非空) 与已带电的方向绝不重置。"""
    web = dict(state.get("npc_rel") or {})
    ids = {c.get("id") for c in _characters(content)}
    mirrors: list[tuple[str, str, int]] = []
    for c in _characters(content):
        cid = c.get("id")
        for t in (c.get("ties") or []):
            other = t.get("char_id")
            if not cid or other not in ids or other == cid:
                continue
            try:
                stance = max(-2, min(2, int(t.get("stance") or 0)))
            except (TypeError, ValueError):
                continue
            key = _pair_key(cid, other)
            e = _npc_dirs(dict(web.get(key) or {"ab": {"stance": 0, "label": None},
                                                "ba": {"stance": 0, "label": None},
                                                "log": []}))
            if e.get("log"):
                web[key] = e
                continue   # 演化过的边不重种
            dk = "ab" if cid == key.split("|", 1)[0] else "ba"
            if not int((e.get(dk) or {}).get("stance") or 0):
                e[dk] = {"stance": stance,
                         "label": (t.get("label") or "").strip() or None}
                mirrors.append((key, "ba" if dk == "ab" else "ab", stance))
            web[key] = e
    for key, mk, stance in mirrors:   # 对向兜底 — 只填还空着的
        e = web.get(key) or {}
        if not int((e.get(mk) or {}).get("stance") or 0):
            e[mk] = {"stance": stance, "label": None}
    state["npc_rel"] = web
    # 💗🛡 作者写的关系起点 (编辑器 rel_start): 只种还没建账的角色 — 已经处出来的
    # 关系绝不被起点覆盖 (与 ties 幂等同法); 顺着本函数的每回合节拍走, 零新调用
    rel_all = state.setdefault("rel", {})
    for c in _characters(content):
        cid = c.get("id")
        if cid and c.get("rel_start") and cid not in rel_all:
            rel_all[cid] = relationships.new_scores_for(c)


def npc_stance(state: dict[str, Any], a: str, b: str) -> dict[str, Any] | None:
    """【a 眼中的 b】(拆向后方向敏感): {stance, label}; 无带电立场 → None。
    全引擎读立场一律走这里 — 别自己解 npc_rel 形状 (位置账本同款收口)。"""
    key = _pair_key(a, b)
    e = (state.get("npc_rel") or {}).get(key)
    if not e:
        return None
    e = _npc_dirs(e)
    v = e["ab"] if a == key.split("|", 1)[0] else e["ba"]
    stance = int((v or {}).get("stance") or 0)
    if not stance:
        return None
    return {"stance": stance, "label": (v or {}).get("label") or _STANCE_LABEL.get(stance, "")}


def apply_npc_shift(content: dict[str, Any], state: dict[str, Any], a_ref: str, b_ref: str,
                    delta: int, why: str, act: int) -> dict[str, Any] | None:
    """Apply ONE judged NPC↔NPC shift: both names must resolve to LIVING characters
    PRESENT in the player's scene (never the player), delta clamps to ±1, stance to
    [-2,2]. A shift past an authored label drops the label (the old flavor no longer
    fits). Returns {a,b,delta,stance} for the UI moment, or None when refused."""
    here = {(c.get("name") or ""): c for c in scene_characters(content, state)
            if c.get("id") != state.get("player_character_id")}

    def _resolve(ref):
        ref = (ref or "").strip()
        for nm, c in here.items():
            if nm and ref and (nm == ref or nm in ref or ref in nm):
                return c
        return None

    ca, cb = _resolve(a_ref), _resolve(b_ref)
    if not ca or not cb or ca.get("id") == cb.get("id"):
        return None
    delta = 1 if int(delta or 0) > 0 else -1 if int(delta or 0) < 0 else 0
    if not delta:
        return None
    web = dict(state.get("npc_rel") or {})
    key = _pair_key(ca["id"], cb["id"])
    e = _npc_dirs(dict(web.get(key) or {"ab": {"stance": 0, "label": None},
                                        "ba": {"stance": 0, "label": None}, "log": []}))
    changed = False
    for _dk in ("ab", "ba"):   # v1 事件对称 (Yi 拍板): 不对等来自 ties 与后续单向事件
        _old = int((e.get(_dk) or {}).get("stance") or 0)
        _ns = max(-2, min(2, _old + delta))
        if _ns != _old:
            e[_dk] = {"stance": _ns, "label": None}  # evolved past the authored flavor
            changed = True
    if not changed:
        return None
    new_stance = int((e.get("ab") or {}).get("stance") or 0)
    log = list(e.get("log") or [])
    log.append({"act": int(act), "delta": delta, "why": (why or "").strip()[:60]})
    e["log"] = log[-12:]
    web[key] = e
    state["npc_rel"] = web
    return {"a": ca.get("name"), "b": cb.get("name"), "delta": delta, "stance": new_stance}


def npc_stance_line(content: dict[str, Any], state: dict[str, Any], sp_id: str,
                    others: list[dict[str, Any]]) -> str:
    """ONE lean prompt line: this speaker's charged stances toward who else is here."""
    bits = []
    for c in others:
        s = npc_stance(state, sp_id, c.get("id") or "")
        if s and c.get("name"):
            bits.append(f"你与{c['name']}：{s['label']}")
    return "；".join(bits)


def offscreen_drama(content: dict[str, Any], state: dict[str, Any],
                    llm: LLM) -> dict[str, Any] | None:
    """One beat of life WITHOUT the player: when the hour turns, two living NPCs who
    stand in the same OTHER place have a moment — their tie shifts, and a RUMOR starts
    circulating (someone in the player's next scene passes it on, once). The engine
    rolls who; the model writes what; no model output, no drama (never fabricated)."""
    if not _locations(content):
        return None
    pcid = state.get("player_character_id")
    here = state.get("location_id")
    groups: dict[str, list[dict[str, Any]]] = {}
    for c in present_characters(content, int(state.get("act", 1) or 1), _dead_ids(state)):
        cid = c.get("id")
        if not cid or cid == pcid or cid in (state.get("following") or []):
            continue
        pos = char_position(content, state, c)
        if pos and pos != AWAY and pos != here:
            groups.setdefault(pos, []).append(c)
    spots = sorted((lid, cs) for lid, cs in groups.items() if len(cs) >= 2)
    if not spots:
        return None
    lid, cs = spots[_rng.randint(0, len(spots) - 1)]
    a, b = _rng.sample(cs, 2)
    stance = npc_stance(state, a.get("id"), b.get("id")) or {}
    try:
        out = llm.generate({"offscreen": True,
                            "place": (_location_by_id(content, lid) or {}).get("name") or "",
                            "a": {"name": a.get("name"), "role": a.get("role") or "",
                                  "persona": (a.get("persona_text") or "")[:80],
                                  # 🎯 what happens offscreen ADVANCES their agenda, not dice
                                  "goal": char_agenda(content, state, a).get("goal", "")},
                            "b": {"name": b.get("name"), "role": b.get("role") or "",
                                  "persona": (b.get("persona_text") or "")[:80],
                                  "goal": char_agenda(content, state, b).get("goal", "")},
                            "stance": stance.get("label") or "没什么交情"}) or {}
    except Exception:
        out = {}
    rumor = (out.get("rumor") or "").strip()[:80]
    if not rumor:
        return None
    # 🎯 book the moment as both characters' latest step — the next scene REMEMBERS it
    ti = _time_index(state)
    for who in (a, b):
        ag = char_agenda(content, state, who)
        ag["step"], ag["at"] = rumor[:60], ti
    delta = 1 if int(out.get("delta") or 0) > 0 else -1 if int(out.get("delta") or 0) < 0 else 0
    if delta:
        web = dict(state.get("npc_rel") or {})
        key = _pair_key(a.get("id"), b.get("id"))
        e = _npc_dirs(dict(web.get(key) or {"ab": {"stance": 0, "label": None},
                                            "ba": {"stance": 0, "label": None}, "log": []}))
        _moved = False
        for _dk in ("ab", "ba"):   # v1 事件对称 (拆向家法同上)
            _old = int((e.get(_dk) or {}).get("stance") or 0)
            _ns2 = max(-2, min(2, _old + delta))
            if _ns2 != _old:
                e[_dk] = {"stance": _ns2, "label": None}
                _moved = True
        if _moved:
            log = list(e.get("log") or [])
            log.append({"act": int(state.get("act", 1) or 1), "delta": delta,
                        "why": rumor[:60]})
            e["log"] = log[-12:]
            web[key] = e
            state["npc_rel"] = web
    rumors = list(state.get("rumors") or [])
    rumors.append({"text": rumor, "at": (clock_view(content, state) or {}).get("label", ""),
                   "heard": False})
    state["rumors"] = rumors[-6:]
    return {"a": a.get("name"), "b": b.get("name"), "rumor": rumor}


def serve_rumor(state: dict[str, Any]) -> str:
    """The next untold rumor (marks it told — a rumor is passed on exactly once)."""
    for ru in state.get("rumors") or []:
        if not ru.get("heard"):
            ru["heard"] = True
            return ru.get("text") or ""
    return ""


def npc_ties_of(content: dict[str, Any], state: dict[str, Any], char_id: str) -> list[dict[str, Any]]:
    """The dossier view: this character's charged stances toward people the player has MET
    (unmet names never leak). [{name, stance, label}] sorted worst-first."""
    met = set(state.get("met_ids") or [])
    out = []
    for c in _characters(content):
        other = c.get("id")
        if not other or other == char_id or other not in met:
            continue
        s = npc_stance(state, char_id, other)
        if s:
            out.append({"name": c.get("name") or "", "stance": s["stance"], "label": s["label"]})
    return sorted(out, key=lambda x: x["stance"])


# ── 🤝 约定 (appointments) ──────────────────────────────────────────────────────
# The strongest come-back hook: a character sets a FUTURE meeting with the player
# (place + day + 时段, hung visibly in the top bar). Showing up = a dedicated scene
# and a relationship reward — a romance-tier appointment plays as a proper 约会名场面
# (恋与深空-style). Standing them up costs the relationship and they hold the grudge.
# Runs entirely off the diegetic clock; stories with the clock off never see it.
def _time_index(state: dict[str, Any]) -> int:
    clk = state.get("clock") or {}
    return int(clk.get("day", 1) or 1) * len(SLOTS) + int(clk.get("slot", 0) or 0) % len(SLOTS)


def _promise_index(pr: dict[str, Any]) -> int:
    slot = pr.get("slot")
    si = SLOTS.index(slot) if slot in SLOTS else 0
    return int(pr.get("day", 1) or 1) * len(SLOTS) + si


def promise_when_label(content: dict[str, Any], pr: dict[str, Any],
                       state: dict[str, Any]) -> str:
    diff = int(pr.get("day", 1) or 1) - int((state.get("clock") or {}).get("day", 1) or 1)
    if lang_of(content) == "en":
        day = ("today" if diff <= 0 else "tomorrow" if diff == 1
               else "in two days" if diff == 2 else f"day {pr.get('day')}")
        slot = _SLOT_EN.get(pr.get("slot", ""), pr.get("slot", "")).lower()
        return f"{day}{(' ' + slot) if slot else ''}"
    day = "今天" if diff <= 0 else "明天" if diff == 1 else "后天" if diff == 2 else f"第{pr.get('day')}天"
    return f"{day}{pr.get('slot', '')}"


def promises_view(content: dict[str, Any], state: dict[str, Any]) -> list[dict[str, Any]]:
    """Open appointments for the UI, soonest first: [{name, what, when, place, romantic}]."""
    out = []
    for pr in sorted((p for p in state.get("promises") or [] if p.get("status") == "open"),
                     key=_promise_index):
        loc = _location_by_id(content, pr.get("location_id")) if pr.get("location_id") else None
        out.append({"name": pr.get("char_name") or "", "what": pr.get("what") or "",
                    "when": promise_when_label(content, pr, state),
                    "place": (loc or {}).get("name") or "", "romantic": bool(pr.get("romantic"))})
    return out


# ── 🗓 玩家自己的行程 (2026-07-31 Yi 采纳路线图里的日历方向): 玩家在日历上写
#    「周五考试」这类安排, 世界要记得 — 公开的行程, 角色会顺着关心; 日子过了,
#    在意你的人会主动问一句结果 (问过即翻篇, 同爽约的 voiced-once 家法)。
#    私密的只是备忘, 绝不入戏。「无点击不推进」照旧: 这里只有账本和提示词。 ──

def _player_event_passed(state: dict[str, Any], ev: dict[str, Any]) -> bool:
    ck = state.get("clock") or {}
    d, s = int(ck.get("day", 1) or 1), int(ck.get("slot", 0) or 0)
    ed = int(ev.get("day", 1) or 1)
    if ed != d:
        return ed < d
    try:
        si = SLOTS.index(ev.get("slot") or "")
    except ValueError:
        return False   # 当天不带时段的, 过完这一天才算过去
    return si < s


def player_events_view(content: dict[str, Any], state: dict[str, Any]) -> list[dict[str, Any]]:
    """玩家行程表 (UI 用), 未过期在前、近的在前。"""
    evs = []
    for ev in state.get("player_events") or []:
        evs.append({"id": ev.get("id"), "text": ev.get("text") or "",
                    "day": int(ev.get("day", 1) or 1), "slot": ev.get("slot") or "",
                    "told": ev.get("told") or "all",
                    "when": promise_when_label(content, ev, state),
                    "passed": _player_event_passed(state, ev)})
    return sorted(evs, key=lambda e: (e["passed"], e["day"]))


def player_diary_for_prompt(content: dict[str, Any], state: dict[str, Any]) -> dict[str, Any] | None:
    """本回合值得让角色知道的玩家行程: 将来的最多 3 条 + 刚过去还没问过的 1 条。
    只取公开 (told=all) 的; 私密备忘永不入戏。"""
    evs = [e for e in state.get("player_events") or [] if (e.get("told") or "all") == "all"]
    if not evs:
        return None
    up = [f"{promise_when_label(content, e, state)}，{e.get('text')}"
          for e in evs if not _player_event_passed(state, e)][:3]
    passed = next((e for e in evs if _player_event_passed(state, e)
                   and e.get("status") != "asked"), None)
    if not (up or passed):
        return None
    return {"upcoming": up,
            "passed": (passed.get("text") or "") if passed else "",
            "_passed_id": passed.get("id") if passed else None}


def void_promises_of(state: dict[str, Any], cid: str) -> list[dict[str, Any]]:
    """A death cancels that character's open promises — no 爽约 penalties from the
    grave. Returns the voided ones so the caller can mourn them in a beat."""
    voided = []
    for pr in state.get("promises") or []:
        if pr.get("status") == "open" and pr.get("char_id") == cid:
            pr["status"] = "void"
            voided.append(pr)
    return voided


def open_promise_of(state: dict[str, Any], cid: str | None) -> dict[str, Any] | None:
    """🤝 这个角色手上还欠着的那个约定 (没有就 None)。

    Yi 2026-08-06:「AI 角色不能无限和玩家有约定，之前线下约过了，手机上就不能再约。」
    闸本来就在 make_promise 里 (每角色同时一个 open), 但【模型不知道】—— 于是它照样在
    短信正文里开口约, 账本悄悄拒收, 玩家读到「明晚老地方见」而约定栏空空如也。
    正文说了、账上没有, 正是本仓最忌的文与实分家。这个读口就是拿去喂提示词的。
    """
    if not cid:
        return None
    for p in state.get("promises") or []:
        if p.get("status") == "open" and p.get("char_id") == cid:
            return p
    return None


def make_promise(content: dict[str, Any], state: dict[str, Any], char: dict[str, Any],
                 pm: dict[str, Any], tun: dict[str, int]) -> dict[str, Any] | None:
    """Record a judged appointment. Refuses: clock off, empty/overlong intent, bad slot,
    a time not in the future, a char who already has one open, or a full slate."""
    if tun["turns_per_slot"] <= 0:
        return None
    what = str(pm.get("what") or "").strip()[:40]
    slot = str(pm.get("slot") or "").strip()
    if not what or slot not in SLOTS:
        return None
    try:
        off = max(0, min(3, int(pm.get("day_offset", 0))))
    except (TypeError, ValueError):
        return None
    prs = list(state.get("promises") or [])
    cid = char.get("id")
    # 🧾 拒收要留痕: 被闸挡下的那一次, 正是「正文里说约好了、账上没有」的现场。
    # 不留痕就永远量不出这件事发生过多少回 (Yi 2026-08-06)。
    if sum(1 for p in prs if p.get("status") == "open") >= MAX_OPEN_PROMISES:
        _audit(state, "promise.refuse", False, char.get("name", ""), "约定已满")
        return None
    if any(p.get("status") == "open" and p.get("char_id") == cid for p in prs):
        _audit(state, "promise.refuse", False, char.get("name", ""), "这个人已经有约在身")
        return None
    day = int((state.get("clock") or {}).get("day", 1) or 1) + off
    pr = {"char_id": cid, "char_name": char.get("name") or "", "what": what,
          "day": day, "slot": slot, "status": "open"}
    if _promise_index(pr) <= _time_index(state):
        return None  # the promised hour must lie ahead
    # the meeting must be somewhere the character WILL be: their 作息 at that hour wins
    # over whatever place was named; an hour they're AWAY can't host a promise at all
    # 🔒 【未来时段】问句 — char_position 只解得开"现在", 这里故意直读 _char_home
    expected = _char_home(char, int(state.get("act", 1) or 1), slot)
    if expected == AWAY:
        return None
    if expected:
        pr["location_id"] = expected
    else:
        dest = resolve_location(content, str(pm.get("place") or "").strip())
        pr["location_id"] = dest.get("id") if dest else state.get("location_id")
    # a promise made at 暧昧/恋人 warmth is a DATE — the fulfillment scene plays as one
    scores = (state.get("rel") or {}).get(cid) or relationships.new_scores()
    pr["romantic"] = relationships.derive_mode(char, scores, tun) in ("flirt", "lover")
    prs.append(pr)
    state["promises"] = prs
    return pr


# ── 📱 小手机 (phase 1: 信息) ────────────────────────────────────────────────────
# Characters REACH OUT to the player between scenes — a promise reminder, a hurt text
# after being stood up, a can't-stop-thinking-of-you note after parting (恋与深空-style
# proactive contact). The player can text back from anywhere; the character answers in
# voice — or leaves them on read. Threads live in run state, separate from scene beats;
# a thread's tail is injected into that character's next scene prompt so the two worlds
# remember each other. Period stories rename the device (城寨 → 口信/字条).
PHONE_MAX_PER_TURN = 2   # incoming deliveries per turn, tops (no notification spam)

# 📱 回复的【时机】与【形状】—— 引擎判定, 模型只写词 (Yi 2026-08-05)。
#
# 生产实况 (176 个存档全扫): 四种形状里【已读晾着 0 次、刷屏 0 次】, 所有消息都在
# 第 1 天、时间戳挤在同一分钟里。查下来是三层原因, 不是一个:
#   ① 刷屏是死码 —— 解析器把回复硬截成 3 条, 而判 burst 要 >=4;
#   ② 已读的短写法被解析器静默吞掉;
#   ③ 长写法能通, 但四种形状并列交给模型自选 —— 它永远选中庸那一档。
# ③ 才是根: 判断权本就不该在模型手里。导演、乐师、骰子都是引擎判定的, 唯独这里交了出去。
PHONE_TIERS = ("now", "soon", "later", "next_slot", "morning", "never")
PHONE_SHAPES = ("normal", "word", "long", "burst", "read")


def phone_cfg(content: dict[str, Any]) -> dict[str, Any]:
    return (content.get("story") or {}).get("phone") or {}


def phone_enabled(content: dict[str, Any]) -> bool:
    return phone_cfg(content).get("enabled", True) is not False


# ── 📇 联系方式 (Yi 定): 通讯录要靠剧情挣, 不是见过面就有 ────────────────────
# 三条路: 玩家开口要 (好感够就给, 不够按性格婉拒) / 好感过阈值 TA 主动给 /
# 没要过的人在 TA 心情好的日子随缘塞给你。老档大赦: 已有短信往来 = 已交换。
_CONTACT_RE = re.compile(
    r"联系方式|联络方式|(呼机|传呼|电话|手机)号|号码留|留个号|怎么联系你|怎么找你"
    r"|留个联系|加个联系|把号(给|留)")
# 📇 联系方式不再是熬出来的 (Yi 2026-08-04: 直接把最好的陪伴体验给玩家)。
# 原本 ASK=10 / OFFER=20 外加一道随缘骰 —— 而中位一局只有 4 拍, 绝大多数玩家一辈子
# 拿不到任何人的号, 于是短信、朋友圈、主动联系这整条陪伴链从来没被打开过。
# 现在: 见面即入通讯录 (grant_contact_on_meet), 这两个阈值只作为剧本级可调的兜底保留。
CONTACT_ASK_T = 0      # 玩家开口要: 好感 ≥ 这个数就给 (0 = 从不拒绝)
# TA 自己把号塞过来的【戏】保留在高位: 能力早就由 grant_contact_on_meet 静默给了,
# 这条路只负责「有戏剧动机时演一句」。压到 0 会让开场每个在场角色都播一句进通讯录, 很吵。
CONTACT_OFFER_T = 20


def contact_will_give(content: dict[str, Any], state: dict[str, Any],
                      cid: str | None) -> bool:
    """玩家开口要号, TA 肯给吗。门槛走 tuning.contact_ask_t (默认 0 = 一律肯给)。"""
    if not cid:
        return False
    thr = int(tuning_for(content).get("contact_ask_t", CONTACT_ASK_T) or 0)
    clo = int(((state.get("rel") or {}).get(cid) or {}).get("closeness", 0) or 0)
    return clo >= thr


def grant_contact_on_meet(content: dict[str, Any], state: dict[str, Any]) -> None:
    """初次见面即交换联系方式 —— 陪伴链的第一环不该是道门。

    只给【已照面且活着】的人, 不给玩家自己。幂等。剧本可用 tuning.contact_on_meet=0
    关掉 (悬疑/恐怖本可能就是要「拿不到号」的封闭感)。"""
    if not int(tuning_for(content).get("contact_on_meet", 1) or 0):
        return
    dead = _dead_ids(state)
    # met_ids 只在 run_turn_stream 里写, 而开场不走那条路 —— 只认它的话, 玩家开局第一件
    # 事点开手机会看到「通讯录空空如也」, 而屏幕上明明写着「在场 2 人」(实弹截图 08-04)。
    # 所以并上此刻在场的人: 站在你面前的就是见过的。
    known = set(state.get("met_ids") or []) | {
        c.get("id") for c in scene_characters(content, state) if c.get("id")}
    for c in _characters(content):
        cid = c.get("id")
        if not cid or cid not in known or cid in dead or cid == state.get("player_character_id"):
            continue
        if not has_contact(state, cid):
            ids = state.setdefault("contact_ids", [])
            ids.append(cid)
            _audit(state, "contact.grant", True, f"{c.get('name', '')}·照面即交换"[:30])


def has_contact(state: dict[str, Any], cid: str | None) -> bool:
    if not cid:
        return False
    if cid in ((state.get("phone") or {}).get("threads") or {}):
        return True   # 老档大赦: 聊过天的人不没收
    return cid in (state.get("contact_ids") or [])


def grant_contact(content: dict[str, Any], state: dict[str, Any],
                  char: dict[str, Any], how: str) -> str:
    ids = state.setdefault("contact_ids", [])
    cid = char.get("id")
    if cid and cid not in ids:
        ids.append(cid)
        _audit(state, "contact.grant", True, f"{char.get('name', '')}·{how}"[:30])
    return f"（{char.get('name', '')}的{phone_device(content)}号，进了你的通讯录。）"


def phone_device(content: dict[str, Any]) -> str:
    return (phone_cfg(content).get("device") or "").strip() or "手机"


def _thread(state: dict[str, Any], cid: str) -> dict[str, Any]:
    ph = state.setdefault("phone", {})
    return ph.setdefault("threads", {}).setdefault(cid, {"msgs": [], "unread": 0})


# 📱 一条线程留多少条消息。60 → 200 (Yi 2026-08-06:「要存更多的聊天记录」)。
# 存储根本不是瓶颈: 生产 state JSON 中位 5KB、最大 48KB, 手机线程最大才 2KB,
# 整个 DB 42MB。而主动引擎一上线, 角色开始频繁找玩家, 60 条很快就不够。
THREAD_MSG_CAP = 200


def _thread_cap(th: dict[str, Any]) -> None:
    """Cap a thread at 60 messages WITHOUT breaking the digest pointer (indices shift
    when the front is dropped — an uncorrected pointer silently loses undigested talk)."""
    msgs = th.get("msgs") or []
    if len(msgs) > THREAD_MSG_CAP:
        dropped = len(msgs) - THREAD_MSG_CAP
        th["msgs"] = msgs[-THREAD_MSG_CAP:]
        th["digested_upto"] = max(0, int(th.get("digested_upto") or 0) - dropped)
    # ⏳ 待发也要封顶。放在这里而不是写入处 —— 写入有好几条路 (延迟回复/已读的补偿句/
    # 老档), 而每条消息落账都会过 _thread_cap, 这是唯一必经的收口。存档的 state 是一个
    # JSON 列, 让它无界增长迟早撑爆。
    pend = th.get("pending")
    if pend and len(pend) > PHONE_PENDING_CAP:
        th["pending"] = pend[-PHONE_PENDING_CAP:]


def _thread_tail(state: dict[str, Any], cid: str, n: int = 4) -> list[dict[str, Any]]:
    return list((((state.get("phone") or {}).get("threads") or {}).get(cid) or {}).get("msgs") or [])[-n:]


def sms_tail_line(state: dict[str, Any], cid: str) -> str:
    """The recent exchange with this character, for scene continuity. 6×60 — 短信里
    定好的时间地点细节要能完整进场上 (实弹: 3×30 截头去尾, 玩家觉得线上线下不通)."""
    tail = _thread_tail(state, cid, 6)
    if not tail:
        return ""
    return "；".join(f"{'TA' if m.get('from') == 'me' else '你'}：{(m.get('text') or '')[:60]}"
                     for m in tail)


# ── 🐲 生物账本 P0 (Yi 拍板 2026-07-20): 兽/龙/鬼 — 第三实体类 ────────────────
# 设计参照 D&D 五版 stat block (怪物是障碍不是社交实体, 独立底盘) + MH 本体
# (隐藏血条外在表现/部位破坏/激怒/濒死逃巢)。合同: 引擎持有血阶与位置账本,
# 命中由模型报审 (creature_hit) 按骰面裁决; 血阶联动行为是引擎规则不是模型好意:
# 重创→自动激怒, 濒死→逃回巢穴 (真实移动, 狩猎自带三幕)。鬼 killable=false 打不死。
_CR_HP = ["完好", "带伤", "重创", "濒死", "讨伐"]


def _creatures(content: dict[str, Any]) -> list[dict[str, Any]]:
    return (content.get("story") or {}).get("creatures") or []


def _creature_by_ref(content: dict[str, Any], ref: str) -> dict[str, Any] | None:
    ref = (ref or "").strip()
    for cr in _creatures(content):
        nm = cr.get("name") or ""
        if cr.get("id") == ref or nm == ref or (nm and (nm in ref or ref in nm)):
            return cr
    return None


def _cr_sim(state: dict[str, Any], crid: str, cr: dict[str, Any] | None = None) -> dict[str, Any]:
    sims = state.setdefault("creature_sim", {})
    return sims.setdefault(crid, {"hp": 0, "pos": (cr or {}).get("lair"),
                                  "enraged": False, "wounds": [], "seen": False,
                                  "carved": False})


def creatures_here(content: dict[str, Any], state: dict[str, Any],
                   mark: bool = True) -> list[dict[str, Any]]:
    """在场生物: sim 位置=玩家当前地点的 (讨伐了的尸体也在场 — 剥取要走过去)。
    mark=False 是只读视图路径 (序列化器不许有副作用)。"""
    loc = state.get("location_id")
    if not loc:
        return []
    out = []
    for cr in _creatures(content):
        sim = _cr_sim(state, cr.get("id"), cr)
        if sim.get("pos") == loc:
            if mark:
                sim["seen"] = True
            out.append({"id": cr.get("id"), "name": cr.get("name"), "kind": cr.get("kind") or "兽",
                        "desc": (cr.get("desc") or "")[:120], "habits": (cr.get("habits") or "")[:80],
                        "hp": _CR_HP[min(int(sim.get("hp") or 0), 4)],
                        "enraged": bool(sim.get("enraged")),
                        "killable": cr.get("killable", True) is not False,
                        "speech": cr.get("speech") or "none",
                        "menace": int(cr.get("menace") or 1)})
    return out


def _player_rank_idx(content: dict[str, Any], state: dict[str, Any]) -> int:
    """玩家段位序号 (progression 阶梯); 无阶梯=0。碾压锚用。"""
    prog = state.get("progression") or {}
    try:
        return int(prog.get("idx") or prog.get("rank_idx") or 0)
    except (TypeError, ValueError):
        return 0


def apply_creature_hit(content: dict[str, Any], state: dict[str, Any], raw: str,
                       dice: dict[str, Any] | None) -> dict[str, Any] | None:
    """模型报审的命中「生物名|部位|轻重」→ 引擎裁决入账。
    规矩: 没掷骰/骰败不认; 鬼不认; 段位碾压不认 (menace 高两档=打不动是账本事实);
    重伤走一档血阶 (crit 附送部位伤), 轻伤记部位。"""
    nm, _, rest = (raw or "").partition("|")
    part, _, sev = rest.partition("|")
    cr = _creature_by_ref(content, nm)
    if not cr:
        return None
    crid = cr.get("id")
    sim = _cr_sim(state, crid, cr)
    if sim.get("pos") != state.get("location_id"):
        _audit(state, "creature.hit", False, cr.get("name", ""), "它不在这儿")
        return None
    if int(sim.get("hp") or 0) >= 4:
        _audit(state, "creature.hit", False, cr.get("name", ""), "它已经倒下了")
        return None
    if cr.get("killable", True) is False:
        _audit(state, "creature.hit", False, cr.get("name", ""),
               "这不是能被杀死的东西——你的攻击穿了过去")
        return {"kind": "creature", "name": cr.get("name"), "ghost": True}
    if int(cr.get("menace") or 1) > _player_rank_idx(content, state) + 2:
        _audit(state, "creature.hit", False, cr.get("name", ""),
               "段位碾压——它的皮肉毫发无伤，这不是你现在够得着的对手")
        return {"kind": "creature", "name": cr.get("name"), "no_dent": True}
    if not dice or dice.get("outcome") not in ("success", "crit_success", "mixed"):
        _audit(state, "creature.hit", False, cr.get("name", ""), "没有命中判定背书，不入账")
        return None
    part = (part or "").strip()[:8]
    heavy = "重" in (sev or "") or dice.get("outcome") == "crit_success"
    moved = False
    if heavy:
        sim["hp"] = min(4, int(sim.get("hp") or 0) + 1)
        moved = True
    if part and part not in (sim.get("wounds") or []):
        sim.setdefault("wounds", []).append(part)
    hp_i = int(sim["hp"])
    ev = {"kind": "creature", "name": cr.get("name"), "hp": _CR_HP[hp_i],
          "part": part, "heavy": heavy}
    # 血阶联动 (引擎规则): 重创→激怒; 濒死→逃回巢穴 (真实移动, 追击到领地决战)
    if moved and hp_i == 2 and not sim.get("enraged"):
        sim["enraged"] = True
        ev["enraged"] = True
        _audit(state, "creature", True, cr.get("name", ""), "重创——它被激怒了")
    if moved and hp_i == 3 and sim.get("pos") != cr.get("lair") and cr.get("lair"):
        sim["pos"] = cr.get("lair")
        ev["fled"] = (_location_by_id(content, cr["lair"]) or {}).get("name") or "巢穴"
        _audit(state, "creature", True, cr.get("name", ""), f"濒死——逃往{ev['fled']}")
    if hp_i >= 4:
        ev["slain"] = True
        sim["enraged"] = False
        _audit(state, "creature", True, cr.get("name", ""), "讨伐完成")
    else:
        _audit(state, "creature.hit", True, f"{cr.get('name', '')}·{part or '躯干'}",
               "重伤" if heavy else "轻伤")
    return ev


_CARVE_RE = re.compile(r"剥取|剥皮|采集素材|收取素材|剥了")


def carve_creature(content: dict[str, Any], state: dict[str, Any],
                   player_input: str, channel: str) -> list[dict[str, Any]]:
    """剥取: 讨伐倒地的生物, 素材真实入包 (走物品实体); 部位伤=手艺加成 qty+1。"""
    if channel != "do" or not _CARVE_RE.search(player_input or ""):
        return []
    got = []
    for cr in _creatures(content):
        sim = _cr_sim(state, cr.get("id"), cr)
        if sim.get("pos") != state.get("location_id") or int(sim.get("hp") or 0) < 4 \
                or sim.get("carved"):
            continue
        sim["carved"] = True
        bonus = len(sim.get("wounds") or [])
        for i, d in enumerate((cr.get("drops") or [])[:4]):
            nm = str(d.get("name") or "").strip()[:16]
            if not nm:
                continue
            qty = 2 if (bonus and i == 0) else 1   # 部位破坏的头件素材翻倍
            for _ in range(qty):
                _inv_add(state, nm, str(d.get("detail") or "").strip()[:60])
            got.append({"name": nm, "qty": qty})
        _audit(state, "creature.carve", True, cr.get("name", ""),
               f"素材{len(got)}种" + (f"·部位加成×{bonus}" if bonus else ""))
    return got


def creature_arrival_beat(content: dict[str, Any], state: dict[str, Any]) -> dict[str, Any] | None:
    """进入生物盘踞的地点: 遭遇拍 (确定性)。"""
    here = creatures_here(content, state)
    live = [c for c in here if c["hp"] != "讨伐"]
    if not live:
        return None
    c = live[0]
    mood = "它带着伤，暴戾之气几乎凝成实物" if c["enraged"] else \
           ("空气骤然一沉" if c["kind"] != "鬼" else "温度毫无来由地降了下去")
    return {"type": "description", "speaker_name": None,
            "text": _t(content,
                       f"（{mood}。{c['name']}就在这片地方——{c['desc'][:60]}）",
                       f"({c['name']} is here.)")}


def bestiary_view(content: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    """📖 图鉴: 只列见过的 (server-authoritative — 没遭遇过的生物不剧透), 余者计数。"""
    rows, unseen = [], 0
    for cr in _creatures(content):
        sim = (state.get("creature_sim") or {}).get(cr.get("id")) or {}
        if not sim.get("seen"):
            unseen += 1
            continue
        rows.append({"id": cr.get("id"), "name": cr.get("name"), "kind": cr.get("kind") or "兽",
                     "desc": cr.get("desc") or "", "habits": cr.get("habits") or "",
                     "menace": int(cr.get("menace") or 1),
                     "hp": _CR_HP[min(int(sim.get("hp") or 0), 4)],
                     "wounds": sim.get("wounds") or [],
                     "img": f"/scene/creature/{cr.get('id')}.jpg"})
    return {"rows": rows, "unseen": unseen}


# ── 💘 追求系统 P0 (Yi 拍板 2026-07-20): AI 角色主动追玩家 ────────────────────
# 合同: 引擎持有追求台账并排节拍 (一游戏日至多一拍), 模型只演当拍的行为;
# 玩家回应由模型报审 (court_response), 裁决归引擎: 三次明拒=死心 (退火+记疤, 永不再启);
# 单追求者锁 (同时只有一位在追); 表白=关键节点抉择卡, 拒绝直接死心 (选择有重量)。
# 风格差异不加新字段 — 各 love_style 的追法写进节拍指令 (傲娇的殷勤全用借口包装)。
COURT_STAGES = {
    1: "留意：眼神多停半拍，记住对方随口提过的话，找机会接一句——还不到刻意接近的时候",
    2: "借口接近：制造一次自然的照面或搭话（顺路/带话/正好多了一份），绝不显得刻意",
    3: "小殷勤：把一样具体的小东西真的递到对方手里（吃的/用得上的小物件——用 item 申报入账），"
       "或顺手帮一个不求回报的忙；嘴上要有个说得过去的借口",
    4: "邀约：约对方去一个具体的地方做一件具体的事（说清时间地点，让约定成立）；被婉拒就笑着留后路",
    5: "心迹渐显：让在意藏不住半次——一次没收住的关心、一句说了一半的话、一点看得见的吃醋；"
       "但还不摊牌",
    6: "表白：把话说到明处——用你的性格能说出口的方式，正面告诉对方你的心意",
}
_COURT_STYLE = {
    "tsundere": "（你是傲娇：每一步殷勤都必须用借口包装——「顺路」「多出来的」「别多想」，被点破就恼羞）",
    "aloof": "（你冷感慢热：动作永远比话多，靠近的幅度极小，但每一步都是真的）",
    "avoidant": "（你回避亲密：当面只敢做到七分，剩下的靠捎话和不在场的惦记）",
    "possessive": "（你占有欲强：靠近带着宣示性，但绝不越界成控制——可以吃醋，不可以拦路）",
    "sunny": "（你是直球：大方承认自己乐意见到对方，殷勤给得坦荡，被拒也笑得住）",
}


def _court_of(state: dict[str, Any], cid: str) -> dict[str, Any]:
    return _sim(state, cid).setdefault("court", {})


def court_tick(content: dict[str, Any], state: dict[str, Any]) -> None:
    """回合末: 心动过线的角色开一本追求台账 (单追求者锁: 同时只有一位)。"""
    tun = tuning_for(content)
    thr = int(tun.get("pursue_threshold", DEFAULT_TUNING["pursue_threshold"]) or 0)
    if thr <= 0:
        return
    active = [cid for cid, si in (state.get("char_sim") or {}).items()
              if (si.get("court") or {}).get("stage")
              and not (si.get("court") or {}).get("dead")
              and not (si.get("court") or {}).get("done")]
    if active:
        return
    dead_ids = _dead_ids(state)
    best, best_r = None, thr - 1
    for c in _characters(content):
        cid = c.get("id")
        if not cid or cid in dead_ids or cid == state.get("player_character_id"):
            continue
        if not relationships._romance_capable(c):
            continue
        court = _court_of(state, cid)
        if court.get("dead") or court.get("done"):
            continue
        scores = (state.get("rel") or {}).get(cid) or {}
        mode = relationships.derive_mode(c, scores, tun)
        if mode in ("lover", "enemy"):
            continue
        r = int(scores.get("romance") or 0)
        if r > best_r:
            best, best_r = cid, r
    if best:
        _court_of(state, best).update({"stage": 1, "rebuffs": 0, "last_day": -1, "beats": 0})
        _audit(state, "court.start", True,
               (_char_by_id(content, best) or {}).get("name", ""), "心动过线，TA开始留意你")


def court_directive_for(content: dict[str, Any], state: dict[str, Any],
                        cid: str) -> str | None:
    """这一拍该 TA 主动了吗 —— 【只读】: 一游戏日至多一拍, 返回注入TA提示词的节拍指令。

    ⚠️ 这里绝不许写账。落账走 court_beat_book(), 由结算期在戏【真的演出来】之后再记。
    实弹排雷 2026-08-04: 原本取数即消费 (就地写 last_day/beats/_court_confess), 而
    调用处 (runtime:10322 `court_dir = ...`) 赋了值从来没人读 —— 一旦有人接上
    court_tick, 生成失败或守卫重写的那一拍就会「名额已花、表白已武装、玩家一个字没看到」。"""
    c = _char_by_id(content, cid)
    if not c:
        return None
    court = ((state.get("char_sim") or {}).get(cid) or {}).get("court") or {}
    if not court.get("stage") or court.get("dead") or court.get("done"):
        return None
    day = _time_index(state) // 3
    if day < int(court.get("skip_until") or 0):
        return None
    # ⏱ 两把计时器谁先到算谁: 换了游戏日 或 距上一拍主动够了 pursue_gap_turns 个回合。
    # 只留游戏日那把的话, real_clock 开着时一次长坐只会被追一下 (实测 12 拍演 1 次)。
    _tun = tuning_for(content)
    _gap = int(_tun.get("pursue_gap_turns", DEFAULT_TUNING["pursue_gap_turns"]) or 0)
    _turn = int((state.get("growth") or {}).get("turn", 0) or 0)
    # ⚠️ 别写成 `court.get("last_turn") or -999` —— 第 0 回合落的账 last_turn 就是 0,
    # 而 0 是假值, 会被 or 吞掉当成「从没演过」, 间隔判定直接失效 (测试先抓到的)。
    _lt = court.get("last_turn")
    _since = (_turn - int(_lt)) if _lt is not None else 10 ** 9
    if court.get("last_day") == day and not (_gap > 0 and _since >= _gap):
        return None
    stage = int(court["stage"])
    style = _COURT_STYLE.get((c.get("love_style") or "").strip(), "")
    return (f"【追求节拍·这一轮你要主动】你对对方的心意到了该行动的一步。"
            f"本拍任务——{COURT_STAGES.get(stage, COURT_STAGES[1])}。{style}"
            "把它演成贴你人设的具体言行，融进当下的场面，绝不突兀跳戏。")


def court_beat_book(content: dict[str, Any], state: dict[str, Any], cid: str) -> None:
    """追求节拍落账: 消费当日名额、推进拍数、到点武装表白。

    只在这一拍的戏真的产出之后调 —— 与 court_directive_for 成对使用, 一个取数一个记账。"""
    c = _char_by_id(content, cid)
    court = ((state.get("char_sim") or {}).get(cid) or {}).get("court") or {}
    if not c or not court.get("stage") or court.get("dead") or court.get("done"):
        return
    court["last_day"] = _time_index(state) // 3
    court["last_turn"] = int((state.get("growth") or {}).get("turn", 0) or 0)
    court["beats"] = int(court.get("beats") or 0) + 1
    stage = int(court["stage"])
    if stage >= 6:
        state["_court_confess"] = cid   # 表白拍: 台词由模型演, 抉择卡由引擎在回合末立
    _audit(state, "court.beat", True, f"{c.get('name', '')}·第{stage}步")


def court_apply_response(content: dict[str, Any], state: dict[str, Any],
                         cid: str, resp: str) -> None:
    """模型报审的玩家回应 → 引擎裁决: 暧昧/接受推进, 回避原地, 明拒记振 (三振死心)。"""
    court = ((state.get("char_sim") or {}).get(cid) or {}).get("court") or {}
    if not court.get("stage") or court.get("dead") or court.get("done"):
        return
    c = _char_by_id(content, cid) or {}
    resp = (resp or "").strip()
    if resp in ("接受", "暧昧"):
        court["stage"] = min(6, int(court["stage"]) + 1)
        court["beats"] = 0
        _audit(state, "court.step", True, f"{c.get('name', '')}→第{court['stage']}步")
    elif resp == "明拒":
        court["rebuffs"] = int(court.get("rebuffs") or 0) + 1
        court["skip_until"] = _time_index(state) // 3 + 1 + int(court["rebuffs"])  # 冷却随拒绝加长
        if court["rebuffs"] >= 3:
            _court_die(content, state, cid, "你一次次把话挑明，TA终于把那份心思收起来了")
        else:
            _audit(state, "court", False, c.get("name", ""),
                   f"被明确拒过{court['rebuffs']}次，TA退了半步")
    elif int(court.get("beats") or 0) >= 2 and int(court["stage"]) < 6:
        # 殷勤两拍没被拒 = 默许 — 不逼模型每拍都报审
        court["stage"] = int(court["stage"]) + 1
        court["beats"] = 0


def _court_die(content: dict[str, Any], state: dict[str, Any], cid: str, why: str) -> None:
    """死心: 台账关死永不再启, 心动退到暧昧线下, 记忆留疤。铁律: 尊重拒绝。"""
    court = _court_of(state, cid)
    court.update({"dead": True, "stage": 0})
    tun = tuning_for(content)
    rel_all = state.setdefault("rel", {})
    sc = dict(rel_all.get(cid) or relationships.new_scores())
    sc["romance"] = min(int(sc.get("romance") or 0), max(0, int(tun["flirt_t"]) // 2))
    rel_all[cid] = sc
    c = _char_by_id(content, cid) or {}
    mem = (state.get("memory_by_char", {}) or {}).get(cid) or ""
    state.setdefault("memory_by_char", {})[cid] = \
        (mem + f"；{why}——这件事你不会再提，也不会再试").strip("；")
    _audit(state, "court.over", True, c.get("name", ""), "死心")


def court_confession_pending(content: dict[str, Any], state: dict[str, Any]) -> None:
    """表白拍的回合末: 立关键节点抉择卡 (拒绝直接死心 — 选择有重量)。"""
    cid = state.pop("_court_confess", None)
    if not cid or state.get("pending_choice"):
        return
    c = _char_by_id(content, cid)
    if not c:
        return
    state["pending_choice"] = {
        "kind": "court", "key": f"court_{cid}", "char_id": cid,
        "prompt": _t(content, f"{c.get('name')}把话说到了明处。你要怎么回答？",
                     f"{c.get('name')} has laid it all out. Your answer?"),
        "options": [
            {"id": "court_yes", "label": _t(content, f"接受{c.get('name')}的心意",
                                            f"Accept {c.get('name')}'s feelings")},
            {"id": "court_no", "label": _t(content, "把话说明白：你们不合适",
                                           "Be honest: this isn't it")},
        ]}


def _apply_court_choice(content: dict[str, Any], state: dict[str, Any],
                        option_id: str) -> dict[str, Any]:
    pending = state.get("pending_choice") or {}
    cid = pending.get("char_id")
    c = _char_by_id(content, cid) or {}
    picked = next((o for o in pending.get("options") or [] if o.get("id") == option_id), None)
    if picked is None:
        raise ValueError("unknown option")
    tun = tuning_for(content)
    if option_id == "court_yes":
        rel_all = state.setdefault("rel", {})
        sc = dict(rel_all.get(cid) or relationships.new_scores())
        sc["romance"] = max(int(sc.get("romance") or 0), int(tun["lover_t"]))
        sc["closeness"] = max(int(sc.get("closeness") or 0), int(tun["lover_close_min"]))
        rel_all[cid] = sc
        _court_of(state, cid).update({"done": True, "stage": 0})
        mem = (state.get("memory_by_char", {}) or {}).get(cid) or ""
        state.setdefault("memory_by_char", {})[cid] = \
            (mem + "；你们把心意挑明了，从那天起是彼此的人").strip("；")
        _audit(state, "court.won", True, c.get("name", ""))
    else:
        _court_die(content, state, cid, "你当面拒绝了TA的表白")
    answered = dict(state.get("choices") or {})
    answered[pending.get("key") or "court"] = option_id
    state["choices"] = answered
    state["pending_choice"] = None
    return {"label": picked.get("label") or "", "flag": None}


# ── 📱🔍 查TA的设备 (偷看手机) — 随身版搜查物证 ────────────────────────────
# 设计合同 (Yi 拍板 2026-07-20):
# · 机会三层: 作者写死 (event.peek_cid) > 引擎遗落骰 (TA离场且TA的账本有新货才掷)
#   > 没有导演报审通道 (防模型滥发)
# · 内容全有账本背书: 玩家线程用真账 (从TA视角+备注名彩蛋), NPC线程从 npc_rel/char_sim/
#   promises 渲染一次缓存 + rel 立场快照 — 立场跳变时插「转折消息」再续 (防一致性穿帮)
# · 浅翻 (线程末句+备注名, 渲染素材结构化不含任何秘密 — 措辞想泄密也无密可泄) /
#   深翻 (全文+authored 素材+device_of 碎片解锁, DC 加高 = 风险加倍)
# · 代价: fail=被撞见 (好感掉+TA记一笔), crit_fail=设备加锁永久封路
#   (lint 保证 device_of 碎片必有备用通路, 锁死不锁本)
# · 节奏: 每角色每游戏日至多一次窗口; 账本无新增不开窗 (机会=世界有新货的信号)
_PEEK_WINDOW_TURNS = 3
_PEEK_RE = re.compile(
    r"(?:偷看|偷翻|翻看|翻查|查看|检查|翻|查)\s*(?:一下|了|看)?\s*"
    r"([^，。！？\s]{1,10}?)的(?:手机|设备|通讯|传呼机|数据板|沃克斯|水晶|留言|口信)")


def peekable(content: dict[str, Any]) -> bool:
    # 口信没有实体设备可翻 — 功能整体沉默 (沉默即叙事)
    return phone_enabled(content) and "口信" not in phone_device(content)


def _peek_state(state: dict[str, Any], cid: str) -> dict[str, Any]:
    return state.setdefault("phone_peek", {}).setdefault(cid, {})


def _peek_ledger_mark(content: dict[str, Any], state: dict[str, Any], cid: str) -> int:
    """TA的账本指纹: 关系演变/约定/短信/在办的事有新增, 指纹就变 — 没新货不开窗。"""
    n = 0
    for k, e in (state.get("npc_rel") or {}).items():
        if cid in k.split("|"):
            n += 1 + len(e.get("log") or [])
    n += sum(1 for p in (state.get("promises") or []) if p.get("char_id") == cid)
    n += len((((state.get("phone") or {}).get("threads") or {}).get(cid) or {}).get("msgs") or [])
    n += 1 if ((state.get("char_sim") or {}).get(cid) or {}).get("intent") else 0
    return n


def peek_maybe_drop(content: dict[str, Any], state: dict[str, Any],
                    cid: str, name: str) -> dict[str, Any] | None:
    """TA 离场时的遗落骰。条件全过才掷: 可翻设备/未上锁/今天没开过窗/账本有新货。"""
    if not peekable(content) or not cid:
        return None
    chance = int(tuning_for(content).get("peek_drop_chance", 0) or 0)
    if chance <= 0:
        return None
    pk = _peek_state(state, cid)
    if pk.get("locked") or int(pk.get("window") or 0) > 0:
        return None
    day = _time_index(state) // 3
    if pk.get("last_window_day") == day:
        return None
    mark = _peek_ledger_mark(content, state, cid)
    if mark <= int(pk.get("ledger_mark") or 0):
        return None    # 世界没新东西, 翻了也是空转 — 不骗玩家赌命运判定
    if _rng.randint(1, 100) > chance:
        return None
    pk["window"] = _PEEK_WINDOW_TURNS
    pk["last_window_day"] = day
    pk["shallow_done"] = False
    _audit(state, "peek.window", True, name)
    return {"kind": "peek_window", "name": name, "device": phone_device(content)}


def peek_open_window(state: dict[str, Any], cid: str) -> None:
    """作者写死的机会窗口 (event.peek_cid): 确定性开窗, 不掷骰不看账本。"""
    pk = _peek_state(state, cid)
    if not pk.get("locked"):
        pk["window"] = _PEEK_WINDOW_TURNS
        pk["shallow_done"] = False


def peek_tick(state: dict[str, Any]) -> None:
    """每回合窗口倒数 — 机会稍纵即逝。"""
    for pk in (state.get("phone_peek") or {}).values():
        if int(pk.get("window") or 0) > 0:
            pk["window"] = int(pk["window"]) - 1


def _peek_cache(content: dict[str, Any], state: dict[str, Any],
                c: dict[str, Any], llm: LLM) -> dict[str, Any]:
    """渲染并缓存TA设备的内容 (一次生成永远一致)。素材结构化保证不含秘密:
    只喂 npc_rel 立场/演变人话、char_sim 在办的事、约定 — 措辞想泄密也无密可泄。"""
    cid = c.get("id")
    pk = _peek_state(state, cid)
    tun = tuning_for(content)
    scores = (state.get("rel") or {}).get(cid) or relationships.new_scores()
    mode = relationships.derive_mode(c, scores, tun)
    if not pk.get("nickname"):
        try:
            out = llm.generate({"peek_nickname": True,
                                "char": {"name": c.get("name"), "eq_style": (c.get("eq_style") or "")[:80]},
                                "relation": relationships.name_of(mode),
                                "impression": profile_mod.impression_of(state, cid)}) or {}
            pk["nickname"] = str(out.get("nickname") or "").strip()[:10] \
                or relationships.name_of(mode)
        except Exception:
            pk["nickname"] = relationships.name_of(mode)
    # NPC↔NPC 线程: 立场最重的两对
    web = state.get("npc_rel") or {}
    pairs = sorted([(k, e) for k, e in web.items() if cid in k.split("|")],
                   key=lambda kv: -abs(int(kv[1].get("stance") or 0)))[:2]
    threads = pk.setdefault("threads", {})
    for k, e in pairs:
        other_id = next((x for x in k.split("|") if x != cid), None)
        other = _char_by_id(content, other_id)
        if not other:
            continue
        stance = int(e.get("stance") or 0)
        th = threads.get(other_id)
        if th is None:
            material = {"owner": {"name": c.get("name"), "persona": (c.get("persona_text") or "")[:80]},
                        "with": other.get("name"),
                        "stance": stance, "label": e.get("label") or "",
                        "whys": [str(l.get("why") or "")[:40] for l in (e.get("log") or [])[-3:]],
                        "intent": (((state.get("char_sim") or {}).get(cid) or {}).get("intent") or "")[:40],
                        "device": phone_device(content)}
            try:
                out = llm.generate({"peek_threads": True, **material}) or {}
                msgs = [dedash(m[:60]) for m in as_str_list(out.get("msgs"))][:4]
            except Exception:
                msgs = []
            threads[other_id] = {"with": other.get("name"), "msgs": msgs or ["……"],
                                 "snap": stance}
        else:
            old = int(th.get("snap") or 0)
            # 立场跳变 (变号或跨两档): 插转折消息再续 — 防「上周密谋这周如常」穿帮
            if (old > 0 > stance) or (old < 0 < stance) or abs(stance - old) >= 2:
                try:
                    out = llm.generate({"peek_twist": True, "with": th.get("with"),
                                        "old_stance": old, "new_stance": stance,
                                        "label": e.get("label") or "",
                                        "last": (th.get("msgs") or [""])[-1],
                                        "device": phone_device(content)}) or {}
                    tw = [dedash(m[:60]) for m in as_str_list(out.get("msgs"))][:2]
                except Exception:
                    tw = []
                th["msgs"] = ((th.get("msgs") or []) + (tw or ["……以后别用这个号找我。"]))[-8:]
                th["snap"] = stance
    return pk


def _peek_deep_frags(content: dict[str, Any], c: dict[str, Any]) -> list[str]:
    """深翻的碎片收成: unlock.device_of 指着TA的 + authored 素材标 reveals 的。"""
    fids = []
    for sec in content.get("secrets") or []:
        for f in sec.get("fragments") or []:
            if (f.get("unlock") or {}).get("device_of") == c.get("id") and f.get("id"):
                fids.append(f["id"])
    for e in (c.get("device_peek") or []):
        if e.get("reveals"):
            fids.append(str(e["reveals"]))
    return fids


def peek_attempt(content: dict[str, Any], state: dict[str, Any], player_input: str,
                 channel: str, llm: LLM) -> dict[str, Any] | None:
    """玩家「做:翻TA的手机」。返回 {beats, frag_ids, moments} 或 None (不是这个动作)。"""
    if channel != "do" or not peekable(content):
        return None
    m = _PEEK_RE.search(player_input or "")
    if not m:
        return None
    ref = m.group(1)
    c = next((x for x in _characters(content) if x.get("name")
              and (x["name"] == ref or x["name"] in ref or ref in x["name"])), None)
    if not c or c.get("id") == state.get("player_character_id"):
        return None
    cid = c["id"]
    dev = phone_device(content)
    pk = _peek_state(state, cid)
    corpse = cid in _dead_ids(state)
    beats: list[dict[str, Any]] = []
    moments: list[dict[str, Any]] = []

    def _b(zh, en):
        beats.append({"type": "description", "speaker_name": None, "text": _t(content, zh, en)})

    if pk.get("locked"):
        _audit(state, "peek", False, c.get("name", ""), "设备已上锁——上次被抓的代价")
        _b(f"（{c.get('name')}的{dev}换了锁。上次的事之后，这条路对你永远封死了。）",
           f"({c.get('name')}'s {dev} is locked now. That door closed for good.)")
        return {"beats": beats, "frag_ids": [], "moments": moments}
    if not corpse and int(pk.get("window") or 0) <= 0:
        _audit(state, "peek", False, c.get("name", ""), "没有机会窗口")
        _b(f"（{c.get('name')}的{dev}此刻不在你够得到的地方。）",
           f"({c.get('name')}'s {dev} isn't within your reach right now.)")
        return {"beats": beats, "frag_ids": [], "moments": moments}

    deep = corpse or bool(pk.get("shallow_done"))
    wits = int(((state.get("attrs") or {}).get("心思") or 5))
    dice = {"outcome": "success", "roll": 0, "dc": 0} if corpse \
        else _roll_dc((13 if deep else 9) - (wits - 5))
    out = dice["outcome"]
    scores = (state.get("rel") or {}).get(cid) or relationships.new_scores()
    tun = tuning_for(content)
    if out == "crit_fail":
        pk["locked"] = True
        pk["window"] = 0
        state.setdefault("rel", {})[cid] = relationships.apply_deltas(
            scores, -8, -4, tun, trust_delta=-6)   # 🛡 偷看被抓现行 = 信任塌方
        mem = (state.get("memory_by_char", {}) or {}).get(cid) or ""
        state.setdefault("memory_by_char", {})[cid] = \
            (mem + f"；对方偷翻你的{dev}被你当场抓住，你从此对TA设了防").strip("；")
        _audit(state, "peek", False, c.get("name", ""), "当场抓包——设备从此上锁")
        _b(f"（{c.get('name')}回来得比你想的快。TA一言不发拿回{dev}，看你的眼神变了。）",
           f"({c.get('name')} came back too soon. They took the {dev} without a word.)")
        moments.append({"kind": "peek_caught", "name": c.get("name")})
        return {"beats": beats, "frag_ids": [], "moments": moments}
    if out == "fail":
        pk["window"] = 0
        state.setdefault("rel", {})[cid] = relationships.apply_deltas(
            scores, -4, -2, tun, trust_delta=-3)   # 🛡 手脚不干净被察觉
        mem = (state.get("memory_by_char", {}) or {}).get(cid) or ""
        state.setdefault("memory_by_char", {})[cid] = \
            (mem + f"；你撞见对方动过你的{dev}，心里存了个疙瘩").strip("；")
        _audit(state, "peek", False, c.get("name", ""), "被撞见——什么都没看到")
        _b(f"（你刚拿起{dev}，{c.get('name')}的脚步声就到了门口。你放下的动作快了半拍——但TA看见了。）",
           f"(You'd barely lifted the {dev} when {c.get('name')} walked in. They saw.)")
        return {"beats": beats, "frag_ids": [], "moments": moments}

    cache = _peek_cache(content, state, c, llm)
    if out == "mixed" and not corpse:
        mem = (state.get("memory_by_char", {}) or {}).get(cid) or ""
        state.setdefault("memory_by_char", {})[cid] = \
            (mem + f"；你隐约觉得有人动过你的{dev}").strip("；")
    if not deep:
        pk["shallow_done"] = True
        my_th = (((state.get("phone") or {}).get("threads") or {}).get(cid) or {}).get("msgs") or []
        mine = f"你们的对话置顶着——TA给你的备注是「{cache.get('nickname')}」。" if my_th else \
               f"通讯录里有你——备注是「{cache.get('nickname')}」。"
        peeks = "；".join(f"和{t.get('with')}的最后一条：「{(t.get('msgs') or ['……'])[-1]}」"
                          for t in (cache.get("threads") or {}).values()) or "没有别的对话。"
        _audit(state, "peek", True, c.get("name", ""), "浅翻")
        _b(f"（你飞快扫了一眼{c.get('name')}的{dev}。{mine} {peeks} 屏幕还亮着——要不要翻得更深？）",
           f"(A quick glance at {c.get('name')}'s {dev}. {peeks})")
        view = {"mode": "shallow", "device": dev, "nickname": cache.get("nickname"),
                "owner": {"name": c.get("name"), "avatar_url": c.get("avatar_url")},
                "threads": [{"with": t.get("with"), "msgs": [(t.get("msgs") or ["……"])[-1]]}
                            for t in (cache.get("threads") or {}).values()],
                "mine_last": (my_th or [{}])[-1].get("text") if my_th else None}
        return {"beats": beats, "frag_ids": [], "moments": moments, "view": view}
    # 深翻: 全文 + authored 素材 + 碎片收成
    pk["window"] = 0
    pk["ledger_mark"] = _peek_ledger_mark(content, state, cid)
    lines = []
    for t in (cache.get("threads") or {}).values():
        lines.append(f"和{t.get('with')}：" + " / ".join((t.get("msgs") or [])[-4:]))
    for e in (c.get("device_peek") or []):
        who = str(e.get("with") or "未知号码")
        lines.append(f"和{who}：" + " / ".join(str(x)[:60] for x in (e.get("msgs") or [])[:4]))
    body = "。".join(lines) or "里面干净得反常。"
    _audit(state, "peek", True, c.get("name", ""), "深翻")
    _b(f"（你把{c.get('name')}的{dev}翻了个底朝天。{body}）",
       f"(You went through {c.get('name')}'s {dev}. {body})")
    view = {"mode": "deep", "device": dev, "nickname": pk.get("nickname"),
            "owner": {"name": c.get("name"), "avatar_url": c.get("avatar_url")},
            "threads": ([{"with": t.get("with"), "msgs": list(t.get("msgs") or [])}
                         for t in (cache.get("threads") or {}).values()]
                        + [{"with": str(e.get("with") or "未知号码"),
                            "msgs": [str(x)[:60] for x in (e.get("msgs") or [])[:4]]}
                           for e in (c.get("device_peek") or [])])}
    return {"beats": beats, "frag_ids": _peek_deep_frags(content, c),
            "moments": moments, "view": view}


def shared_phone_view(content: dict[str, Any], state: dict[str, Any],
                      c: dict[str, Any], llm: LLM) -> dict[str, Any] | None:
    """💞 关系够近, TA大方把手机递给你看 (通讯录入口, 无骰无代价, Yi 定 2026-07-31)。
    只有「TA愿意给你看」那一层: 备注/和你的置顶/和别人的最后一句 — 内容与偷看共用
    _peek_cache (一次生成永远一致, 偷看过再光明正大看, 两边对得上)。日记、搜索、
    全文这些深处仍然只能冒险偷看。关系不够 → None (调用方给人话)。"""
    cid = c.get("id")
    scores = (state.get("rel") or {}).get(cid) or relationships.new_scores()
    tun = tuning_for(content)
    if cid in _dead_ids(state) or not relationships.can_view_phone(c, scores, tun):
        return None
    cache = _peek_cache(content, state, c, llm)
    pk = _peek_state(state, cid)
    if not pk.get("shared_once"):
        # 第一次递手机是个时刻 — 记进TA的账, 戏里可以被提起
        pk["shared_once"] = True
        mem = (state.get("memory_by_char", {}) or {}).get(cid) or ""
        state.setdefault("memory_by_char", {})[cid] = \
            (mem + f"；TA把自己的{phone_device(content)}大方递给你看过").strip("；")
    my_th = (((state.get("phone") or {}).get("threads") or {}).get(cid) or {}).get("msgs") or []
    return {"mode": "shared", "device": phone_device(content),
            "nickname": cache.get("nickname"),
            "owner": {"name": c.get("name"), "avatar_url": c.get("avatar_url")},
            "threads": [{"with": t.get("with"), "msgs": [(t.get("msgs") or ["……"])[-1]]}
                        for t in (cache.get("threads") or {}).values()],
            "mine_last": (my_th or [{}])[-1].get("text") if my_th else None}


# ── 📔 玩家备忘录 (Yi 定 2026-07-31): 玩家亲手记/改/删的本子, 影响接下来的戏 ──
# 笔记是玩家私人的 (角色看不见本子), 但它是玩家在意的方向 — 主叙者的提示词拿它
# 当叙事罗盘: 相关的细节、契机、人物动向要有机会浮现。绝无 LLM 后台调用。

def player_notes_view(state: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"id": n.get("id"), "text": n.get("text") or ""}
            for n in state.get("player_notes") or []]


# ── 🏦📸 小手机新 app: 银行 + 社媒 (Yi 拍板 2026-07-20, P0 纯内环) ────────────
# 银行 = money/money_log 账本的视图 + 转账(传令落账: 真钱动了, TA 短信里真会回应);
# 社媒 = 活世界账本的可见面: 角色动态从 npc_rel 演变/在办的事/约定渲染, 一次生成
# 缓存 (账本指纹变了才出新帖), 点赞确定性回好感(每帖一次), 评论走小 LLM 限频。
# 皮肤铁律: 只有现代设定 (device=手机) 默认开, 作者可用 phone.apps 显式配置。


def phone_apps(content: dict[str, Any]) -> set[str]:
    """📱 这个世界的随身设备上有哪几个 app。

    作者显式配了 apps 就听他的 (最高优先, 一个字都不猜)。没配时:
      · 沙盒 —— 一律全开, 不看设备叫什么 (Yi 2026-08-04:「小手机所有功能不管是
        什么时代都要全部开启」, 范围定在沙盒)。玩家自己写的世界可能是任何年代,
        传讯符也好飞鸽也好, 那是【称谓】; 功能是界面, 不该被年代关掉。
        称谓换皮在客户端做 (古风的「动态」叫「风声」、「银行」叫「账房」)。
      · 授权剧情本 —— 照旧按设备皮肤判 (作者写死了年代与设备, 引擎不越权改)。
    ⚠️ 银行还有第二道门在 phone_threads_view: 没有钱账本就不亮。那是【钱账本门】,
    不是年代门 —— 没有账本的银行是个空壳, 点进去只有一句「无账可管」。
    """
    cfg = phone_cfg(content)
    if isinstance(cfg.get("apps"), list):
        apps = {str(a) for a in cfg["apps"]}
    elif sandbox_on(content):
        apps = {"bank", "social"}
    else:
        apps = {"bank", "social"} if phone_device(content) == "手机" else set()
    if _creatures(content):
        apps.add("bestiary")   # 📖 有生物的世界自动有图鉴 (不吃现代皮肤门槛)
    return apps


def bank_view(content: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    dead = _dead_ids(state)
    met = set(state.get("met_ids") or [])
    contacts = [{"id": c.get("id"), "name": c.get("name")}
                for c in _characters(content)
                if c.get("id") in met and c.get("id") not in dead
                and c.get("id") != state.get("player_character_id")
                and has_contact(state, c.get("id"))]
    return {"currency": currency_of(content), "balance": int(state.get("money") or 0),
            "log": list(reversed(state.get("money_log") or [])),
            "contacts": contacts}


def bank_transfer(content: dict[str, Any], state: dict[str, Any], persona: dict[str, Any],
                  char_id: str, amount: int, llm: LLM | None = None) -> dict[str, Any]:
    """💸 给角色转账 — 真钱落账 (book_money), TA 的记忆与短信都会知道这件事。"""
    llm = lang_llm(llm or get_llm(), content)
    c = _char_by_id(content, char_id)
    if not c or char_id in _dead_ids(state) or char_id not in set(state.get("met_ids") or []):
        raise ValueError("没有这个收款人")
    if not has_contact(state, char_id):
        raise ValueError("你还没有TA的账户——先要到联系方式")
    amount = _to_int(amount, 0, 9999)
    if amount <= 0:
        raise ValueError("金额不对")
    if amount > int(state.get("money") or 0):
        raise ValueError("余额不够")
    applied = book_money(content, state, -amount, f"转给{c.get('name')}")
    if not applied:
        raise ValueError("没有入账")
    _audit(state, "bank.transfer", True, f"{c.get('name')}·{amount}")
    mem = (state.get("memory_by_char", {}) or {}).get(char_id) or ""
    state.setdefault("memory_by_char", {})[char_id] = \
        (mem + f"；对方给你转了{amount}{currency_of(content)}").strip("；")
    # TA 的短信回应: 收钱不是无声的 (走既有 compose+push 管线, 进线程带未读)
    now_label = (clock_view(content, state) or {}).get("label", "")
    msgs = compose_message(content, state, c, "received_transfer",
                           f"对方刚给你转了{amount}{currency_of(content)}，你按自己的性格回应"
                           "（谢/推辞/起疑/打趣都行），1~2条短消息",
                           _t(content, "收到了。这是做什么？", "Got it. What's this for?"), llm)
    push = phone_push(content, state, c, msgs, now_label)
    return {"view": bank_view(content, state), "reply": push}


_SOCIAL_CAP = 12          # feed 最多留几条
_SOCIAL_COMMENTS_PER_DAY = 5


def _social_state(state: dict[str, Any]) -> dict[str, Any]:
    return state.setdefault("social", {"posts": [], "mark": -1, "cday": -1, "cnum": 0})


def _social_mark(content: dict[str, Any], state: dict[str, Any]) -> int:
    """账本指纹: 变了才出新帖 (没新货不烧调用)。

    ⚠️ 2026-08-05 补进「你们之间刚发生的事」—— 此前指纹只认角色【彼此】之间的关系
    (npc_rel)、在办的事、约定、见过谁, 唯独不认玩家和角色之间发生了什么。于是你跟
    某人刚经历完一场大事, 动态照旧是旧的那两条: 朋友圈跟不上剧情。
    现在把每个角色的关系大事记(rel_log)和相册也计进来 —— 它们正是「你俩之间」的账。"""
    n = _time_index(state)
    for e in (state.get("npc_rel") or {}).values():
        n += 1 + len(e.get("log") or [])
    for si in (state.get("char_sim") or {}).values():
        n += 1 if si.get("intent") else 0
    n += len(state.get("promises") or []) + len(state.get("met_ids") or [])
    for entries in (state.get("rel_log") or {}).values():
        n += len(entries or [])
    n += len(state.get("album") or [])
    return n


def _welcome_post(content: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    """📣 开卷通告 (Yi 定 2026-07-31): feed 的第一条是欢迎玩家进入这个世界的公告,
    顺带交代眼下的处境。确定性拼装 (标题/一句话简介/所在地/身边的人), 零 LLM,
    引擎不带任何具体剧本的字。它随时间自然沉底、被容量顶掉 — 通告本来就该过期。"""
    story = content.get("story") or {}
    en = lang_of(content) == "en"
    title = (story.get("title") or "").strip()
    tease = (story.get("one_liner") or "").strip() \
        or _first_sentence(story.get("synopsis") or "", 60)
    loc = current_location(content, state)
    here = [c.get("name") for c in scene_characters(content, state)
            if c.get("id") != state.get("player_character_id") and c.get("name")][:3]
    if en:
        bits = [f"Welcome to {title}." if title else "Welcome.",
                (tease + ".") if tease and not tease.endswith((".", "!", "?")) else tease,
                f"You are at {loc.get('name')}." if loc and loc.get("name") else "",
                ("Nearby: " + ", ".join(here) + ".") if here
                else "Go meet the people of this world.",
                "Likes and comments here are remembered."]
        text = " ".join(b for b in bits if b)
    else:
        bits = [f"欢迎来到《{title}》。" if title else "欢迎。",
                (tease + "。") if tease and not tease.endswith(("。", "！", "？")) else tease,
                f"你现在在{loc.get('name')}。" if loc and loc.get("name") else "",
                ("身边有" + "、".join(here) + "。") if here else "先去见见这个世界里的人。",
                "在这里点的赞、留的言，TA们都会记在心里。"]
        text = "".join(b for b in bits if b)
    return {"id": "po_welcome", "cid": "", "name": "📣 " + ("Notice" if en else "通告"),
            "welcome": True, "text": text[:180],
            "label": (clock_view(content, state) or {}).get("label", ""),
            "liked": False, "comments": []}


def social_feed(content: dict[str, Any], state: dict[str, Any],
                llm: LLM | None = None) -> dict[str, Any]:
    """📸 动态: 已认识角色的"朋友圈"。素材全取自账本 (演变人话/在办的事/约定),
    账本指纹没变不出新帖 — 一次生成永久缓存, 不烧无谓的调用。"""
    llm = lang_llm(llm or get_llm(), content)
    so = _social_state(state)
    if not so.get("welcomed"):
        # 📣 第一次打开 feed: 先立欢迎通告 (此刻的处境写进去, 越早打开越准)
        so["welcomed"] = True
        so.setdefault("posts", []).insert(0, _welcome_post(content, state))
    mark = _social_mark(content, state)
    if mark != so.get("mark"):
        so["mark"] = mark
        dead = _dead_ids(state)
        met = set(state.get("met_ids") or [])
        # 📍 动态也读位置真源: 帖子里的地名因此是【可印证的】—— 玩家真走过去就能撞见 TA,
        # 因为地图/对白/通讯录/这里问的是同一个 char_position。这才是"世界真在转"的体感,
        # 而不是模型随口编的地名。口径同地图: 只给地图上已经能看见的地方。
        _avail_s = {l.get("id"): location_available(content, state, l) for l in _locations(content)}
        items = []
        for c in _characters(content):
            cid = c.get("id")
            if not cid or cid not in met or cid in dead \
                    or cid == state.get("player_character_id"):
                continue
            hooks = []
            for k, e in (state.get("npc_rel") or {}).items():
                if cid in k.split("|"):
                    hooks += [str(l.get("why") or "")[:40] for l in (e.get("log") or [])[-1:]]
            intent = ((state.get("char_sim") or {}).get(cid) or {}).get("intent")
            if intent:
                hooks.append(f"正在办：{str(intent)[:40]}")
            for p in state.get("promises") or []:
                if p.get("char_id") == cid and p.get("status") == "open":
                    hooks.append(f"惦记着约好的：{str(p.get('what') or '')[:30]}")
            if hooks:
                _pos = char_position(content, state, c)
                _at = ((_location_by_id(content, _pos) or {}).get("name") or "") \
                    if (_pos and _pos != AWAY and _avail_s.get(_pos)) else ""
                items.append({"cid": cid, "name": c.get("name"),
                              "persona": (c.get("persona_text") or "")[:80],
                              "eq_style": (c.get("eq_style") or "")[:60],
                              # at 单开一档, 不跟近况素材抢 hooks[:2] 的名额
                              "at": _at, "hooks": hooks[:2],
                              # 🧠 接上记忆断头路 (2026-08-04): 此前朋友圈素材里
                              # 一个玩家字段都没有 —— 角色在物理上不可能提到你们刚
                              # 发生过的事, 于是能在刚吵完架的当天发没事人的动态。
                              # 场上↔短信早就共用 memory_by_char, 这里是最后一段。
                              # 认知边界照旧: 只给【这个角色自己的】那本, 绝不给全局
                              # 摘要 (信息不开天眼), 也绝不给未解锁秘密。
                              "memory": ((state.get("memory_by_char") or {}).get(cid) or "")[:160],
                              # 🧠 事实【跟着各自的 cid 走】—— 这条调用一次带多个角色,
                              # 拍平成一份就等于甲的事出现在乙的动态里 (开天眼)。
                              "knows": knows_of(state, cid)[:4],
                              "player_read": profile_mod.impression_of(state, cid)})
        posted = {p.get("cid") for p in (so.get("posts") or [])[-3:]}
        items = [i for i in items if i["cid"] not in posted][:2]
        if items:
            try:
                out = llm.generate({"social_posts": True, "items": items, "era": era_of(content), "device": phone_device(content)}) or {}
                new_posts = out.get("posts") or []
            except Exception:
                new_posts = []
            now_label = (clock_view(content, state) or {}).get("label", "")
            by_name = {i["name"]: i["cid"] for i in items}
            import uuid as _uuid_s
            for p in new_posts[:2]:
                nm = str(p.get("name") or "").strip()
                cid = by_name.get(nm)
                txt = dedash(str(p.get("text") or "").strip()[:80])
                if not cid or not txt:
                    continue
                so["posts"].append({"id": f"po_{_uuid_s.uuid4().hex[:8]}", "cid": cid,
                                    "name": nm, "text": txt, "label": now_label,
                                    "liked": False, "comments": []})
            so["posts"] = so["posts"][-_SOCIAL_CAP:]
    return {"posts": list(reversed(so.get("posts") or []))}


def social_like(content: dict[str, Any], state: dict[str, Any], post_id: str) -> dict[str, Any]:
    so = _social_state(state)
    post = next((p for p in so.get("posts") or [] if p.get("id") == post_id), None)
    if not post:
        raise ValueError("这条动态不见了")
    if post.get("welcome"):
        raise ValueError("通告只是通告——把赞留给活人吧")
    if not post.get("liked"):
        post["liked"] = True
        tun = tuning_for(content)
        cid = post.get("cid")
        scores = (state.get("rel") or {}).get(cid) or relationships.new_scores()
        state.setdefault("rel", {})[cid] = relationships.apply_deltas(scores, 1, 0, tun)
        _audit(state, "social.like", True, post.get("name", ""))
    return {"liked": True}


def social_comment(content: dict[str, Any], state: dict[str, Any], persona: dict[str, Any],
                   post_id: str, text: str, llm: LLM | None = None) -> dict[str, Any]:
    """💬 评论TA的动态 — TA 会用自己的声音回一句 (小调用, 每游戏日限5条)。"""
    llm = lang_llm(llm or get_llm(), content)
    so = _social_state(state)
    post = next((p for p in so.get("posts") or [] if p.get("id") == post_id), None)
    if not post:
        raise ValueError("这条动态不见了")
    if post.get("welcome"):
        raise ValueError("通告没有嘴——去评论活人的动态吧")
    text = (text or "").strip()[:60]
    if not text:
        raise ValueError("评论不能是空的")
    day = _time_index(state) // 3
    if so.get("cday") != day:
        so["cday"], so["cnum"] = day, 0
    if int(so.get("cnum") or 0) >= _SOCIAL_COMMENTS_PER_DAY:
        raise ValueError("今天的嘴已经聊累了——明天再来（每天限5条评论）")
    so["cnum"] = int(so.get("cnum") or 0) + 1
    c = _char_by_id(content, post.get("cid")) or {}
    tun = tuning_for(content)
    scores = (state.get("rel") or {}).get(post.get("cid")) or relationships.new_scores()
    try:
        out = llm.generate({"social_reply": True, "post": post.get("text"), "era": era_of(content), "device": phone_device(content),
                            "comment": text,
                            "char": {"name": c.get("name"), "eq_style": (c.get("eq_style") or "")[:80],
                                     "persona_text": (c.get("persona_text") or "")[:100]},
                            "relation": relationships.name_of(
                                relationships.derive_mode(c, scores, tun))}) or {}
    except Exception:
        out = {}
    reply = dedash(str(out.get("reply") or "").strip()[:60]) or "（TA看到了，没回。）"
    dc = max(0, min(2, _to_int(out.get("closeness"), 0, 2)))
    dc, _ = _offscene_rel_budget(state, post.get("cid"), dc, 0, tun)   # 📱 刷分止血带
    if dc:
        state.setdefault("rel", {})[post.get("cid")] = \
            relationships.apply_deltas(scores, dc, 0, tun)
    post.setdefault("comments", []).append({"from": "me", "text": text})
    post["comments"].append({"from": "them", "text": reply})
    post["comments"] = post["comments"][-6:]
    _audit(state, "social.comment", True, f"{post.get('name', '')}:{text[:15]}")
    return {"reply": reply, "closeness": dc, "comments": post["comments"]}


_SNAP_GAP = 5   # 📷 at least this many exchanges between two photos in one thread

# 📷 生图频率交给玩家 (Yi 2026-08-06)。从前只有作者侧的 tuning.snap_chance + 引擎写死
# 的冷却, 玩家一点话语权没有 —— 而这件事该他说了算, 两个理由都硬: 花的是真钱
# (火山刚因余额见底停过一天生图), 而且口味差得远 (有人想多看几张, 有人嫌照片打断读文)。
#   0 关 / 1 少 / 2 正常(缺省, 老档逐位不变) / 3 多
# (系数, 冷却来回数)
SNAP_PREFS = {0: (0.0, 999), 1: (0.5, 10), 2: (1.0, _SNAP_GAP), 3: (2.0, 3)}
SNAP_PREF_DEFAULT = 2


def snap_pref_of(state: dict[str, Any]) -> int:
    """玩家这一档。脏值/缺省一律回落"正常" —— 老档逐位不变。"""
    try:
        v = int(state.get("snap_pref", SNAP_PREF_DEFAULT))
    except (TypeError, ValueError):
        return SNAP_PREF_DEFAULT
    return v if v in SNAP_PREFS else SNAP_PREF_DEFAULT


def set_snap_pref(state: dict[str, Any], level: Any) -> int:
    try:
        v = int(level)
    except (TypeError, ValueError):
        v = SNAP_PREF_DEFAULT
    if v not in SNAP_PREFS:
        v = SNAP_PREF_DEFAULT
    state["snap_pref"] = v
    return v


def maybe_snap(content: dict[str, Any], state: dict[str, Any], char: dict[str, Any],
               gist: str) -> dict[str, Any] | None:
    """📷 随手拍: occasionally a character's message carries a PHOTO — a selfie, or a
    shot of whatever is in front of them right now (恋与深空-style proactive warmth;
    in a horror world the same mechanic delivers dread). The ENGINE rolls the dice,
    owns the cooldown ledger and writes the prompt; the ROUTER queues the actual
    render (it owns the serialized image worker). Returns {"url", "prompt"} or None."""
    _cfg = get_settings()
    if _cfg.llm_provider == "mock" or not ((_cfg.dashscope_api_key or "").strip()
                                           or (getattr(_cfg, "ark_api_key", "") or "").strip()):
        return None   # no image backend (or deterministic test mode) → never mint a URL
    chance = int(tuning_for(content).get("snap_chance", 0) or 0)
    # 🎚 玩家那一档在作者设定【之上】再缩放一次: 作者定这个世界该有多少照片,
    #    玩家定他自己想看多少。关掉是硬关, 不掷骰也不动冷却账。
    _mul, _gap = SNAP_PREFS[snap_pref_of(state)]
    if _mul <= 0:
        return None
    chance = min(60, int(round(chance * _mul)))
    if chance <= 0 or not char.get("id"):
        return None
    th = _thread(state, char["id"])
    since = int(th.get("snap_since", _gap))
    th["snap_since"] = since + 1
    if since < _gap or _rng.randint(1, 100) > chance:
        return None
    th["snap_since"] = 0
    import uuid as _uuid_s
    url = f"/scene/snap/snap_{_uuid_s.uuid4().hex[:10]}.jpg"
    loc = _location_by_id(content, char_position(content, state, char) or "") or {}
    look = ((char.get("persona_text") or "").strip().replace("\n", " "))[:100]
    scene = f"{loc.get('name', '')}，{(loc.get('detail') or '')[:80]}"
    if _rng.randint(1, 100) <= 45 and look:
        # 📷 自拍必须同脸 (Yi 2026-07-15: 角色形象要稳定): 身份锚随包出门 —
        # router 有底图走 i2i 改绘 (EDIT_MODEL 保脸), 无底图用 char_seed 定种 t2i
        # (同角色历张自拍互相同脸)。此处 prompt 只是 t2i 回落用。
        prompt = (f"{char.get('name')}用手机拍的一张自拍：{look}。"
                  f"所在环境：{scene}。"
                  "写实手机自拍质感，轻微俯仰角，浅景深，生活抓拍感，无文字水印")
        _art = art_style_of(content)
        if _art:
            prompt += f"。画面基调：{_art}"
        from .gal import char_seed as _cseed
        return {"url": url, "prompt": prompt, "selfie": True, "cid": char["id"],
                "seed": _cseed((content.get("story") or {}).get("id") or "", char["id"]),
                "scene": scene, "art": _art or ""}
    prompt = (f"一张随手拍的手机照片，拍下此刻眼前的景象：{loc.get('name', '')}，"
              f"{(loc.get('detail') or '')[:140]}。与这句话有关：{(gist or '')[:60]}。"
              "手机摄影质感，自然光影，轻微晃动与噪点，写实，画面里没有文字或水印")
    _art = art_style_of(content)
    if _art:
        prompt += f"。画面基调：{_art}"
    return {"url": url, "prompt": prompt}


def phone_push(content: dict[str, Any], state: dict[str, Any], char: dict[str, Any],
               msgs: list[str], now_label: str, call: bool = False) -> dict[str, Any]:
    """Deliver incoming message bubbles from a character. Returns the UI event payload.
    call=True marks the lines as spoken down the line (📞 来电) — the UI rings.
    A text delivery may carry a 📷 随手拍 on the last bubble (never on a call)."""
    th = _thread(state, char.get("id"))
    snap = None if call else maybe_snap(content, state, char, (msgs or [""])[-1])
    for i, m in enumerate(msgs):
        rec = {"from": "them", "text": m[:120], "at": now_label}
        if call:
            rec["call"] = True
        if snap and i == len(msgs) - 1:
            rec["img"] = snap["url"]
        th["msgs"].append(rec)
    _thread_cap(th)
    th["unread"] = int(th.get("unread", 0)) + len(msgs)
    return {"char_id": char.get("id"), "name": char.get("name") or "",
            "avatar_url": char.get("avatar_url"), "msgs": msgs, "call": bool(call),
            "snap": snap,  # router: queue the render, then strip before the wire
            "device": phone_device(content)}


# ── 📟 主动找你 (Yi 2026-08-05: 让玩家感觉总是有人在找他) ──────────────────────
# 生产实况: 174 个存档里只有 5 个有过短信往来 —— 97% 的局角色一条消息没发过。
# 根因不是管线缺 (compose_message + phone_push 早就通用), 是【由头只有一个】:
# 唯一主动的产地 offline_pulse 只在「玩家离开又回来」那一拍开火, 而中位一局只有
# 4 个玩家回合 —— 中位玩家从来没有「回来」过, 于是永远收不到任何消息。
#
# 所以这里加的不是新能力, 是新【由头】。铁律两条:
#   · 名额: 一律过 PHONE_MAX_PER_TURN, 主动是免费的但玩家的注意力不是。
#   · 边界: 只有在场见证过的人才来聊那件事 —— 不在场的人不该知道。

def reachout_on_meet(content: dict[str, Any], state: dict[str, Any], llm: LLM,
                     busy: set[str] | None = None) -> list[dict[str, Any]]:
    """初次见面之后的自我介绍短信。

    「照面即给联系方式」(08-04) 之后, 新玩家打开手机是一部空机: 通讯录里有人,
    一条消息也没有。这条补上那个空 —— 也是这台设备对玩家说的第一句话。
    每人一生一次 (intro_sent 记账)。"""
    if not phone_enabled(content) or (state.get("mode") or "character") == "god":
        return []
    sent = state.setdefault("intro_sent", [])
    dead = _dead_ids(state)
    # 🤝 「见过」得是【真打过照面】, 不是账本上有名字。phone.seen 记的是上次面对面的
    # 时刻, 只有它能证明你俩真的站到过一起 —— met_ids 会被开场、路过、旁白提及写进去。
    # 实弹: 两条旧测试里的「乙」一直待在后巷从没露面, 却收到了一条「乙。」的自我介绍。
    met = set(state.get("met_ids") or []) & set(((state.get("phone") or {}).get("seen") or {}).keys())
    # 🚪 人还站在你面前时不发 —— 当面聊着天, 手机响一声「你好我是阿彩」很蠢。
    # 自我介绍要等你们分开之后才到 (那才是真人存完号会做的事)。
    here = {c.get("id") for c in scene_characters(content, state) if c.get("id")}
    now_label = (clock_view(content, state) or {}).get("label", "")
    out: list[dict[str, Any]] = []
    for c in _characters(content):
        cid = c.get("id")
        if not cid or cid in sent or cid not in met or cid in dead \
                or cid in here or cid == state.get("player_character_id"):
            continue
        if not has_contact(state, cid):        # 剧本关掉照面即给时, 这条自然也不发
            continue
        # 🥇 让位: 这个人本回合已经因为【有后果的事】发过话了 (约定到点/爽约/刚分别),
        # 就不许再叠一条寒暄 —— 实弹 test_promise_reminder: 「别忘了夜里后巷见」后面
        # 跟了一条「乙。」, 玩家的未读变成 2, 而第二条毫无信息量。
        # 自我介绍不消耗 intro_sent, 下次他安静的时候再发。
        if busy and (c.get("name") or "") in busy:
            continue
        if len(out) >= PHONE_MAX_PER_TURN:     # 一屋子人不许一口气弹一屏通知
            break
        sent.append(cid)
        msgs = compose_message(
            content, state, c,
            "你们刚刚初次见面, 你把号存给了对方 —— 发一条自我介绍的短信",
            "一两句, 贴你的性格: 报个名号/说句场面话/或者只丢一句冷淡的确认。"
            "别热情得不像你, 也别写成客服话术。",
            f"{c.get('name', '')}。", llm)
        out.append(phone_push(content, state, c, msgs, now_label))
        _audit(state, "reach.intro", True, str(c.get("name") or "")[:12])
    return out


def reachout_after_event(content: dict[str, Any], state: dict[str, Any], llm: LLM,
                         moments: list[dict[str, Any]] | None,
                         busy: set[str] | None = None) -> list[dict[str, Any]]:
    """刚一起经历了点什么, 事后来一条总结性的短信。

    「他还在想刚才那件事」是陪伴感里最便宜也最有效的一条。
    两道门都要过:
      · 见证 —— 只发给亲历这件事的人 (不在场的人来聊, 就是认知边界破了);
      · 分开 —— 人还站在你面前时不发, 当面的事当面说完了, 短信是【离场之后】
        那点没说完的余温。押成词债, 等他离场的那一拍再送。"""
    if not phone_enabled(content) or (state.get("mode") or "character") == "god":
        return []
    here = {c.get("id") for c in scene_characters(content, state) if c.get("id")}
    dead = _dead_ids(state)
    # 📥 押账: 本回合的高光先记下 (只记亲历者), 等他离场那一拍再送。
    owed = state.setdefault("reach_owed", {})
    for m in (moments or []):
        nm = (m.get("name") or "").strip()
        what = str(m.get("title") or "").strip()
        c0 = next((x for x in _characters(content) if (x.get("name") or "").strip() == nm), None)
        cid0 = (c0 or {}).get("id")
        if cid0 and what and cid0 in here and cid0 != state.get("player_character_id"):
            owed[cid0] = what
    now_label = (clock_view(content, state) or {}).get("label", "")
    out: list[dict[str, Any]] = []
    for cid in list(owed.keys()):
        c = _char_by_id(content, cid)
        # 还站在你面前 = 当面的事当面说, 这条继续押着
        if not c or cid in here or cid in dead or not has_contact(state, cid):
            continue
        if busy and (c.get("name") or "") in busy:      # 同上: 有后果的消息优先
            continue
        if len(out) >= PHONE_MAX_PER_TURN:
            break
        what = str(owed.pop(cid, "") or "").strip()
        if not what:
            continue
        msgs = compose_message(
            content, state, c,
            f"你们刚一起经历了「{what}」—— 分开之后你回味起来, 给对方发一条",
            "别复述刚才的事, 那是你们俩都在场的; 写此刻心里剩下的那点东西, "
            "一两句, 可以只说半句。",
            "……", llm)
        out.append(phone_push(content, state, c, msgs, now_label))
        _audit(state, "reach.after", True, f"{c.get('name', '')}·{what[:10]}")
    return out


def compose_message(content: dict[str, Any], state: dict[str, Any], char: dict[str, Any],
                    reason: str, hint: str, fallback: str, llm: LLM) -> list[str]:
    """1~2 short in-voice bubbles for an occasion. LLM-written; deterministic fallback."""
    tun = tuning_for(content)
    scores = (state.get("rel") or {}).get(char.get("id")) or relationships.new_scores()
    try:
        out = llm.generate({"compose_msg": True, "device": phone_device(content), "era": era_of(content),
                            "char": {"name": char.get("name"), "role": char.get("role") or "",
                                     "persona_text": (char.get("persona_text") or "")[:160],
                                     "eq_style": (char.get("eq_style") or "")[:120],
                                     "examples": [str(x)[:60] for x in
                                                  (char.get("examples") or [])][:4]},
                            "relation": relationships.name_of(
                                relationships.derive_mode(char, scores, tun)),
                            "reason": reason, "hint": hint,
                            # 🧠 TA 主动开口时最该用上那些具体的事 —— Yi 要的
                            # 「几天后 TA 主动用上」正是这条路 (半夜一条「你不是说不吃香菜」)。
                            # 认知边界照旧: 只给这个角色自己那本。
                            "knows": knows_of(state, char.get("id")),
                            "thread_tail": _thread_tail(state, char.get("id"))}) or {}
        msgs = [dedash(m[:120]) for m in as_str_list(out.get("msgs"))][:2]
    except Exception:
        msgs = []
    return msgs or [fallback]


def phone_deliveries(content: dict[str, Any], state: dict[str, Any], here_ids: set,
                     llm: LLM) -> list[dict[str, Any]]:
    """Turn-end scan: which ABSENT characters have a reason to reach out RIGHT NOW.
    Deterministic triggers (LLM only writes the words): ① a promise whose hour is next
    (reminder, once); ② just stood up (the hurt text, once); ③ a 暧昧/恋人 the player
    just parted from (the afterglow note, once per parting). Capped per turn."""
    if not phone_enabled(content):
        return []
    tun = tuning_for(content)
    now_idx = _time_index(state)
    now_label = (clock_view(content, state) or {}).get("label", "")
    dead = _dead_ids(state)
    met = set(state.get("met_ids") or [])
    out: list[dict[str, Any]] = []

    def absent(cid):
        return cid and cid in met and cid not in dead and cid not in here_ids

    # ① / ② promise-driven
    for pr in state.get("promises") or []:
        if len(out) >= PHONE_MAX_PER_TURN:
            break
        cid = pr.get("char_id")
        c = _char_by_id(content, cid)
        if not c or not absent(cid):
            continue
        when, what = promise_when_label(content, pr, state), pr.get("what") or ""
        if pr.get("status") == "open" and _promise_index(pr) == now_idx + 1 and not pr.get("reminded"):
            pr["reminded"] = True
            msgs = compose_message(content, state, c, "reminder",
                                   f"你们约好了{when}（{what}），时辰快到了，你捎话提醒TA，带上你自己的语气",
                                   _t(content, f"别忘了{when}，{what}。我等你。",
                                      f"Don't forget: {when}, {what}. I'll be waiting."), llm)
            out.append(phone_push(content, state, c, msgs, now_label))
        elif pr.get("status") in ("missed", "missed_noted") and not pr.get("texted"):
            pr["texted"] = True
            msgs = compose_message(content, state, c, "stood_up",
                                   f"TA爽约了你们约好的（{what}），你心里不好受，忍不住捎话给TA",
                                   _t(content, "我等了你很久。你没来。",
                                      "I waited a long time. You never came."), llm)
            out.append(phone_push(content, state, c, msgs, now_label))
    # ③ afterglow: a romance-tier character the player was JUST with, now apart
    seen = (state.get("phone") or {}).get("seen") or {}
    rels = state.get("rel") or {}
    for c in _characters(content):
        if len(out) >= PHONE_MAX_PER_TURN:
            break
        cid = c.get("id")
        if not absent(cid) or int(seen.get(cid, -99)) < now_idx - 1:
            continue
        if relationships.derive_mode(c, rels.get(cid) or relationships.new_scores(), tun) \
                not in ("flirt", "lover"):
            continue
        th = _thread(state, cid)
        if int(th.get("auto_idx", -1)) >= int(seen.get(cid, -99)):
            continue  # this parting already got its note
        th["auto_idx"] = int(seen.get(cid, -99))
        # 恋人 doesn't settle for a text — TA 直接拨过来 (恋与深空-style incoming call)
        as_call = relationships.derive_mode(
            c, rels.get(cid) or relationships.new_scores(), tun) == "lover"
        msgs = compose_message(content, state, c, "missing_you",
                               ("TA刚离开你身边就忍不住拨通了你——写TA接通后开口说的1~2句话，"
                                "短、软、像TA的性格" if as_call else
                                "TA刚离开你身边，你心里还想着TA，忍不住捎一句——短、软、像TA的性格"),
                               _t(content, "你刚走，我就开始想你了。",
                                  "You just left and I already miss you."), llm)
        out.append(phone_push(content, state, c, msgs, now_label, call=as_call))
    return out


def phone_threads_view(content: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    """The 信息 app's inbox: one row per thread, unread counts, newest first."""
    rows = []
    for cid, th in (((state.get("phone") or {}).get("threads")) or {}).items():
        c = _char_by_id(content, cid)
        msgs = th.get("msgs") or []
        if not c or not msgs:
            continue
        rows.append({"char_id": cid, "name": c.get("name") or "",
                     "avatar_url": c.get("avatar_url"), "dead": cid in _dead_ids(state),
                     "last": (msgs[-1].get("text") or "")[:40], "at": msgs[-1].get("at", ""),
                     "unread": int(th.get("unread", 0))})
    rows.reverse()
    rows.sort(key=lambda r: -r["unread"])
    # 👥 通讯录: ONLY people the player has actually met (server-authoritative — the
    # contact list must never reveal characters the player hasn't encountered yet)
    pcid = state.get("player_character_id")
    dead = _dead_ids(state)
    have = set((((state.get("phone") or {}).get("threads")) or {}))
    # 📍 通讯录也读位置真源 (2026-07-30): 打不通就该在通讯录里看得懂, 而不是拨过去
    # 撞一鼻子灰。口径【完全对齐地图】—— 地图能看见的地方才写地名, 看不见的只给
    # "联系得上/联系不上"; 一个字的新情报都不多给, 两个面板也永远不会各说各话。
    _here_ids = {c.get("id") for c in scene_characters(content, state)}
    _avail = {l.get("id"): location_available(content, state, l) for l in _locations(content)}
    contacts = []
    for cid in state.get("met_ids") or []:
        c = _char_by_id(content, cid)
        if not c or cid == pcid:
            continue
        if not has_contact(state, cid):
            continue   # 📇 联系方式要靠剧情挣 (Yi): 没交换过的人不在通讯录里
        row = {"char_id": cid, "name": c.get("name") or "",
               "role": (c.get("role") or "")[:24],
               "avatar_url": c.get("avatar_url"),
               "dead": cid in dead, "has_thread": cid in have,
               # away=拨过去无人接听 (phone_call 用的是同一句 char_position == AWAY)
               "away": False, "here": False, "where": ""}
        pos = None if cid in dead else char_position(content, state, c)
        if pos is not None:   # None = 这本没有地图, 位置系统压根没启用 → 一个位置字都不给
            row["away"] = _phone_unreachable(content, state, c)   # 与拨号同一句判据
            row["here"] = cid in _here_ids
            if pos != AWAY and _avail.get(pos):
                row["where"] = (_location_by_id(content, pos) or {}).get("name") or ""
        # 📱 关系够近, TA愿意把手机递给你看 (通讯录里的解锁位)
        _sc = (state.get("rel") or {}).get(cid) or relationships.new_scores()
        row["peek_ok"] = (cid not in dead
                          and relationships.can_view_phone(c, _sc, tuning_for(content)))
        contacts.append(row)
    apps = phone_apps(content)
    if not economy_on(state):
        apps = apps - {"bank"}   # 💰 没有经济账本的本, 银行 app 无账可管 — 不亮
    return {"device": phone_device(content), "threads": rows,
            "unread": sum(r["unread"] for r in rows), "contacts": contacts,
            "apps": sorted(apps)}   # 🏦📸 现代设定的扩展 app 清单


def phone_thread(content: dict[str, Any], state: dict[str, Any], char_id: str,
                 mark_read: bool = True) -> dict[str, Any] | None:
    c = _char_by_id(content, char_id)
    if not c:
        return None
    th = _thread(state, char_id)
    if mark_read:
        th["unread"] = 0
    pend = th.get("pending") or []
    view = {"char_id": char_id, "name": c.get("name") or "", "avatar_url": c.get("avatar_url"),
            "dead": char_id in _dead_ids(state), "device": phone_device(content),
            "msgs": list(th.get("msgs") or [])}
    if pend:
        # ⏳ 有话在路上 —— 只报【几条 / 还有多久】, 绝不带正文 (给了就是剧透)。
        # 客户端据此显示"已送达, TA还没回"而不是一片空白 (不然玩家以为卡住了)。
        soonest = min((int(p.get("due_ts") or 0) for p in pend), default=0)
        view["pending"] = {"n": len(pend),
                           "in_s": max(0, soonest - _wall_ts()) if soonest else None}
    return view


def _phone_unreachable(content: dict[str, Any], state: dict[str, Any],
                       c: dict[str, Any]) -> bool:
    """📞 拨过去到底有没有人接 —— 电话与通讯录共用这一句, 两处永远不会各说各话。

    位置先问真源 char_position (于是同行/守约/被钉在某处的人都打得通, 不再像从前那样
    只认作息表); 真源报 AWAY 时再问一句是不是作者的班表说的 —— 只有作者写的"这个钟点
    找不到TA"才等于无人接听, 引擎那颗"走出了这一场"的钉子不是关机。
    """
    return (char_position(content, state, c) == AWAY
            and _schedule_says_away(content, state, c))


def _phone_target(content: dict[str, Any], state: dict[str, Any], char_id: str,
                  text: str) -> dict[str, Any]:
    """Shared reachability checks for texting/calling someone. Raises player-readable."""
    if not phone_enabled(content):
        raise ValueError("这个故事里没有这种联系方式")
    c = _char_by_id(content, char_id)
    if not c:
        raise ValueError("没有这个人")
    if char_id in _dead_ids(state):
        raise ValueError("TA已不在人世——这条消息永远不会有回音了")
    if char_id == state.get("player_character_id"):
        raise ValueError("不能发给你自己")
    if char_id not in set(state.get("met_ids") or []):
        raise ValueError("你还不认识TA，没有TA的联系方式")
    if not (text or "").strip():
        raise ValueError("说点什么吧")
    if state.get("player_hp") == "dead":
        raise ValueError("你已经死了，发不出任何消息")
    return c


KNOWS_CAP = 12   # 每个角色记得多少件【具体的事】(进提示词, 肥了模型反而抓不住重点)


def knows_of(state: dict[str, Any], cid: str | None) -> list[str]:
    """🧠 这个角色亲耳听你说过的具体的事。

    与已有那两本账的分工 (别再多造一本):
      · profile.facts   跨角色的玩家习惯, 合同里明写【不进对白】—— 角色不开上帝视角
      · profile.by_char 相处出来的印象, 60 字的"感觉"(「嘴硬心软」), 不是具体的事
      · memory_by_char  滚动散文摘要 —— 每蒸馏一次就更概括一层, 细节必然褪色
    这本账专治最后那条: 摘要可以越滚越概括, **具体的事不许被概括掉**, 三天后 TA 还能
    原样搬出来 (「你不是说不吃香菜」)。
    """
    if not cid:
        return []
    return list(((state.get("knows") or {}).get(cid) or []))[:KNOWS_CAP]


def _knows_key(s: str) -> str:
    """去重用的归一形 —— 模型每次换个说法就存一条的话, 三天后这本账没法看。
    只做最保守的归一 (去标点/去人称头), 不做语义合并: 宁可多一条, 不许合错。"""
    # ⚠️ 绝不抹人称头。「他妹妹在城南」与「你妹妹在城南」是【两件事】, 抹掉主语就
    # 归一成同一条, 后来的那条被静默丢弃 —— 合错比多存坏得多 (验收点名)。
    # 只做最保守的一层: 去标点与空白。
    return re.sub(r"[，。！？、；：,.!?;:\s「」【】\"']", "", s or "")


def knows_add(state: dict[str, Any], cid: str | None, facts: Any) -> list[str]:
    """把一批事实记到【这个角色】名下。去重 + 截长 + 封顶, 最新的留下。"""
    if not cid:
        return []
    book = state.setdefault("knows", {})
    cur = list(book.get(cid) or [])
    seen = {_knows_key(x) for x in cur}
    for f in as_str_list(facts):
        t = f.strip()[:40]
        if not t or t in ("无", "None", "-"):
            continue
        k = _knows_key(t)
        if not k or k in seen:
            continue
        seen.add(k)
        cur.append(t)
    book[cid] = cur[-KNOWS_CAP:]
    return book[cid]


def rewind_phone(state_after: dict[str, Any], state_before: dict[str, Any]) -> dict[str, Any]:
    """⏪ 回溯时手机怎么办 —— 回卷 state 的调用方在写回之前过一道这里。

    本仓回溯的既有法条是「被抹掉的时间线要把它造的东西一起带走」(涌现的角色/地点就是
    这么处理的)。手机上要分两半, 因为它们的性质相反:

      · 【还没送到的待发】—— 那句话是在一个已经不存在的回合里写的, 必须跟着消失。
        留着它, 玩家会在几十分钟后收到一条"上一条时间线"的回信。
      · 【已经送达、玩家读过的消息】—— 不许凭空消失。整份 state 回卷本来就会把它们
        一起卷走, 但"我明明看见过"那种崩坏比多留一条更伤。所以以回溯点的线程为底,
        把回溯点【之后】才落地的正式消息也保留下来。

    只动 phone 这一块; 返回要写回存档的那份 state (就地改 state_before 并返回它)。
    """
    if not isinstance(state_before, dict):
        return state_before
    th_a = ((state_after or {}).get("phone") or {}).get("threads") or {}
    if not th_a:
        return state_before
    ph_b = state_before.setdefault("phone", {})
    th_b = ph_b.setdefault("threads", {})
    for cid, ta in th_a.items():
        tb = th_b.setdefault(cid, {"msgs": [], "unread": 0})
        msgs_b = tb.get("msgs") or []
        msgs_a = ta.get("msgs") or []
        if len(msgs_a) > len(msgs_b):
            # 回溯点之后真的送到过的, 留着 —— 读过就是读过
            tb["msgs"] = list(msgs_a)
            tb["unread"] = int(ta.get("unread", 0) or 0)
        # ⏳ 只作废【回溯点之后】排的那些 —— 玩家在回溯点之前发的消息, 回信还在路上,
        # 把它也弄没等于那条消息永远等不到回音, 而玩家根本不知道为什么 (验收点名)。
        keep = list(tb.get("pending") or [])
        if keep:
            tb["pending"] = keep
        else:
            tb.pop("pending", None)
    return state_before


PHONE_PENDING_CAP = 12   # 一条线程最多攒多少条待发 (存档的 JSON 列不是无底洞)
PHONE_FLUSH_MAX = 3      # 一次投递最多送几条 —— 攒了一堆同时到期不许变成意外刷屏


def _wall_ts() -> int:
    """墙钟秒 (UTC epoch)。

    ⚠️ 测【时长】一律 UTC, 绝不用 _now_for —— 那是日历口径 (今天几号/星期几/落在哪个
    时段), 换个时区就让到期时间跟着漂。living.due 的心跳到期也是这个规矩。
    """
    from datetime import datetime, timezone
    return int(datetime.now(timezone.utc).timestamp())


def _phone_due(content: dict[str, Any], state: dict[str, Any], tier: str) -> dict[str, Any]:
    """按档位算这条待发什么时候送到。

    为什么要另起一条墙钟轴: 老的 deliver_at 走 _time_index, 粒度是【时段】—— 而全舰
    默认 real_clock=1 让时段跟真实钟点走 (5-11/12-17/18-4), `now+1` 实际等待 1 分钟到
    11 小时不等, 表达不了「隔一阵」; turns_per_slot=0 的本 _time_index 干脆冻住不动,
    pending 永不到期, 是个死信箱 (生产 0 个线程用过它, 这是根因之一)。
    """
    now = _wall_ts()
    if tier == "never":
        # ☠️ 「这条不该有回音」不是"很久以后"。没有分支的话它会掉进下面那个注释写着
        # morning 的 else, 于是一个重伤濒死的人 11 小时后给你发来一条短信 (验收实跑)。
        return {"tier": "never"}
    if tier == "soon":
        secs = _rng.randint(75, 400)              # 一两分钟到几分钟: 刚下工/手上正忙
    elif tier == "later":
        secs = _rng.randint(1200, 3600)           # 二十分钟到一小时: 在别处办事
    elif tier == "next_slot":
        secs = 120                                # 墙钟只做兜底, 真正的门是时段
    else:                                         # morning: 真的等到下一个早上六点
        h = _story_hour(content, state)
        h = 3 if h is None else h
        # 至少三小时 —— 否则凌晨五点发的会在 later(最多一小时) 之前到, 档位就乱了序
        secs = max(3 * 3600, ((6 - h) % 24 or 24) * 3600)
    out: dict[str, Any] = {"due_ts": now + secs, "tier": tier}
    # 🚧 时段门只在【时钟真的在走】的本子上挂; 冻住的钟会把它变成死信箱
    if tier == "next_slot" and int(tuning_for(content).get("turns_per_slot") or 0) > 0:
        out["due_idx"] = _time_index(state) + 1
    return out


INTENT_FRESH_SLOTS = 3   # 应承的差事管几个时段 —— 过了就当办完了


def _intent_stale(state: dict[str, Any], sim: dict[str, Any]) -> bool:
    """这桩应承是不是早该办完了。

    char_sim[cid]["intent"] 全仓【没有任何清除点】(验收查出)。所以说过一次
    「我去码头取个东西」的角色, 此后每一条短信都判 later —— 永远慢半拍, 而玩家
    完全不知道为什么。给它一个保质期: 没有落时间戳的老账一律当过期 (老档宽恕)。
    """
    at = sim.get("intent_at")
    if at is None:
        return True
    try:
        return _time_index(state) - int(at) >= INTENT_FRESH_SLOTS
    except (TypeError, ValueError):
        return True


def _story_hour(content: dict[str, Any], state: dict[str, Any]) -> int | None:
    """这个故事此刻的钟点 (0~23), 虚构钟的本子返回 None。

    先读存档自己的 clock["real"] —— 那正是【玩家在屏幕上看到的】那个时间, 每回合由
    现实对齐同步写入; 缺了才退回墙钟 _now_for。
    ⚠️ 别直接用 _now_for: 它读的是真实系统时间, 与存档显示的时刻可能不是一回事,
    而且测试里没法构造 (实弹: 深夜那两条为此白红了一轮)。
    """
    if not real_time_on(content):
        return None
    raw = str((state.get("clock") or {}).get("real") or "").strip()
    if raw and ":" in raw:
        try:
            return int(raw.split(":", 1)[0]) % 24
        except ValueError:
            pass
    try:
        return _now_for(state).hour
    except Exception:
        return None


def _phone_beat(content: dict[str, Any], state: dict[str, Any], c: dict[str, Any],
                text: str, here: bool, th: dict[str, Any]) -> tuple[str, str]:
    """📱 这一次回复的【时机】与【形状】—— 一次判完, 一起进提示词。

    为什么合成一个函数 (四路探查后的合稿裁定): 时机与形状读的是【同一批信号】, 分成
    两条阶梯就会各判各的 —— 实测冲突: 上次晾过 (last_read) 时, 时机那条说"再延一次",
    形状那条说"必须当场还债"。同一份线程状态两个相反结论, 谁先跑谁说了算。

    硬互斥表 (不许绕):
      · shape == "read"  ⇒ tier 强制 now  —— read 本身就是"不回", 不许再叠一层延迟,
        否则玩家一次发送会看到两条已读灰条
      · tier  != "now"   ⇒ shape 不许 read
      · 线程上还欠着债 (last_read 或 pending 非空) ⇒ 强制 now 且不许 read
        —— 一条线程任何时刻最多欠一笔债。连着两次不回, 玩家读到的是「坏了」,
        不是「TA在气我」。

    ⚠️ 硬信号一律【不掷骰】, 默认档确定性命中 (now, normal)。判定里一掷骰,
    tests/test_phone.py 那条逐字全等的回复断言就会变成 flaky —— 间歇红比确定红难查
    十倍 (判官在合稿里点名的坑)。

    返回 (tier, shape)。
    """
    cid = c.get("id")
    sim = (state.get("char_sim") or {}).get(cid) or {}
    tun = tuning_for(content)
    scores = (state.get("rel") or {}).get(cid) or relationships.new_scores()
    mode = relationships.derive_mode(c, scores, tun)
    owes = bool(th.get("last_read")) or bool(th.get("pending"))

    # ── 时机 ────────────────────────────────────────────────────────────
    def _tier() -> str:
        if sim.get("hp") in ("dead", "dying") or cid in _dead_ids(state):
            return "never"                      # 死人不回短信 (投递侧还有第二道闸)
        if here or cid in (state.get("following") or []):
            return "now"                        # 人就在眼前 / 一路同行
        if owes:
            return "now"                        # 💳 欠着债就得还, 不许再拖
        if cid in (state.get("taken") or {}):
            return "morning"                    # 🚪 被掳走的人, 天亮才有下文
        if _phone_unreachable(content, state, c):
            return "next_slot"                  # 作者班表说的, 不许软化; 下个时段自然恢复
        h = _story_hour(content, state)
        if h is not None and 0 <= h < 6:
            # 🌙 睡不着的人只为一个人爬起来
            return "soon" if mode in ("flirt", "lover") else "morning"
        if _promise_loc_now(state, cid):
            return "later"                      # 此刻正赴另一个约
        if (sim.get("intent") or "").strip() and not _intent_stale(state, sim):
            return "later"                      # 应承了具体差事, 手上有活
        if char_position(content, state, c) == AWAY:
            return "later"                      # 钉子 AWAY: 只是慢, 不是关机
        return "now"

    tier = _tier()

    # ── 形状 ────────────────────────────────────────────────────────────
    def _shape() -> str:
        if tier != "now":
            # 延迟里不许 read; 长短由玩家这句话的分量定
            return "long" if len(text) >= 30 else "normal"
        if owes:
            return "normal"                     # 还债这一拍老老实实说话
        # 🧊 冷关系 + 玩家一直说 = 已读晾着 (每天一次为限, 多了就是被无视)
        if mode in ("stranger", "enemy") and _phone_quota(state, cid, "read", 1):
            unanswered = 0
            for m in reversed(th.get("msgs") or []):
                if m.get("from") != "me":
                    break
                unanswered += 1
            if unanswered >= 2 or int(scores.get("closeness", 0)) < 0:
                return "read"
        # 🔥 亲近 + 玩家抛了个钩子 = 连环刷屏 (每天两次为限)
        if mode in ("flirt", "lover") and any(ch in text for ch in "？?！!") \
                and _phone_quota(state, cid, "burst", 2):
            return "burst"
        if len(text) >= 30:
            return "long"                       # 你写了一长段, TA 也认真回
        return "normal"

    shape = _shape()
    if shape == "read":
        tier = "now"                            # 互斥表: read 永不叠延迟
    if tier != "now" and shape == "read":
        shape = "normal"                        # 兜底 (上面已保证不会走到)
    return tier, shape


def _phone_quota(state: dict[str, Any], cid: str, kind: str, cap: int) -> bool:
    """极端形状的每日配额 —— 「别把一种用成习惯」得有个真闸, 不能只写在提示词里。
    只【查】不扣; 真扣在 _phone_beat 定案之后 (查而不用不该烧配额)。"""
    day = int((state.get("clock") or {}).get("day", 1) or 1)
    book = (state.get("phone_shape_day") or {})
    if book.get("_day") != day:
        return True
    return int((book.get(kind) or {}).get(cid, 0) or 0) < cap


def _phone_quota_spend(state: dict[str, Any], cid: str, kind: str) -> None:
    day = int((state.get("clock") or {}).get("day", 1) or 1)
    book = state.setdefault("phone_shape_day", {})
    if book.get("_day") != day:
        book.clear()
        book["_day"] = day
    book.setdefault(kind, {})[cid] = int((book.get(kind) or {}).get(cid, 0) or 0) + 1


def _phone_probe(content: dict[str, Any], state: dict[str, Any], char_id: str,
                 text: str) -> tuple[list[str], list[str]]:
    """套话挖秘密: probing over text/call counts for real. The player's words register
    as asks (same keyword detection as a scene turn), the gate re-evaluates, and any
    layer that cracks open NOW is returned so the character can voice it in their reply.
    known_by still holds — only truths THIS character carries surface here; unlocks are
    global and sticky, exactly like in-scene ones. Returns (newly_ids, unlocked_titles
    limited to what this speaker may voice)."""
    asks = dict(state.get("asks") or {})
    for sid in _detect_asks(content, text):
        asks[sid] = asks.get(sid, 0) + 1
    state["asks"] = asks
    frags = gating.iter_fragments(content)
    already = set(state.get("unlocked_fragment_ids") or [])
    newly = gating.evaluate_unlocks(state, frags)
    if not newly:
        return [], []
    state["unlocked_fragment_ids"] = sorted(already | set(newly))
    act = int(state.get("act", 1) or 1)
    titles: list[str] = []
    newset = set(newly)
    for sec in content.get("secrets", []) or []:
        hit = [f for f in sec.get("fragments", []) or [] if f.get("id") in newset]
        if not hit:
            continue
        title = (sec.get("title") or "").strip()
        rel_log(state, sec.get("character_id"), act, "reveal",
                _t(content,
                   f"关于「{title}」的真相，在{phone_device(content)}里揭开了一层。",
                   f"A layer of the truth about “{title}” came loose in the {phone_device(content)}."))
        # only truths this speaker is allowed to voice count as "撬开了TA的嘴"
        if any(not f.get("known_by_character_ids")
               or char_id in (f.get("known_by_character_ids") or []) for f in hit):
            titles.append(title)
    return newly, titles


def _phone_exchange(content: dict[str, Any], state: dict[str, Any], persona: dict[str, Any],
                    c: dict[str, Any], text: str, llm: LLM, newly: list[str],
                    call: bool = False, same_room: bool = False,
                    beat_log: list[dict[str, Any]] | None = None,
                    tier: str = "now", shape: str = "normal") -> dict[str, Any]:
    """One gated text/call exchange with a character: build their view, ask the model,
    apply relationship movement. Returns the raw LLM output dict."""
    char_id = c.get("id")
    # 📱↔🎭 线上线下要通气 (玩家实弹: 剧情里刚一起经历大事, 短信里TA像没事人):
    # memory_by_char 只蒸馏滑出窗口的旧回合, 刚发生的戏必须现喂 — TA 亲历的最近几拍
    recent_scene = [str(m.get("content") or "")[:80]
                    for m in history_for(beat_log, char_id)[-8:]] if beat_log else []
    tun = tuning_for(content)
    scores = (state.get("rel") or {}).get(char_id) or relationships.new_scores()
    mode = relationships.derive_mode(c, scores, tun)
    ctx = gating.build_context(char_id, gating.iter_fragments(content), state, newly_ids=newly)
    pcid = state.get("player_character_id")
    pc = _char_by_id(content, pcid) if pcid else None
    _th_lr = (_thread(state, char_id).get("last_read") or {}).get("reason") or ""
    out = llm.generate({"phone_reply": True, "call": bool(call), "same_room": bool(same_room),
                        # 📱 引擎点名的时机与形状 —— 模型不再自选 (它永远选中庸那一档)
                        "shape": shape,
                        "reply_when": {"tier": tier,
                                       "hour": _story_hour(content, state),
                                       "busy": (_sim(state, char_id).get("intent") or "")[:40]},
                        "last_ignored": _th_lr,   # 📱 上次晾过要认账 (Spec C)
                        # 🤝 已经约过了就别再约 (Yi 2026-08-06)。闸在 make_promise 里,
                        # 但从前【模型不知道】—— 于是正文照约、账本悄悄拒收, 文与实分家。
                        # 🫂 线上线下一个心境: 当面记着账, 短信里就不该突然热络
                        "relation_read": (state.get("rel_read") or {}).get(char_id) or {},
                        "open_promise": (lambda p: {"what": p.get("what", ""),
                                                    "when": promise_when_label(content, p, state)}
                                         if p else None)(open_promise_of(state, char_id)),
                        "device": phone_device(content),
                        "char": {"name": c.get("name"), "role": c.get("role") or "",
                                 "persona_text": (c.get("persona_text") or "")[:200],
                                 "eq_style": (c.get("eq_style") or "")[:150],
                                 "examples": [str(x)[:60] for x in (c.get("examples") or [])][:4],
                                 "agenda": (c.get("agenda") or "")[:100]},
                        "relation": relationships.name_of(mode),
                        "relationship_playbook": relationships.playbook_block(
                            mode, mature=bool(state.get("mature")), char=c),
                        "player_read": profile_mod.impression_of(state, char_id),  # 🪞
                        "context": ctx,
                        "player_name": (pc or {}).get("name") or (persona or {}).get("name") or "",
                        # 信息不开天眼: strictly THIS character's own digest — the global
                        # digest is the PLAYER's whole life and must never leak into a
                        # character who wasn't there for it
                        "memory": (state.get("memory_by_char", {}) or {}).get(char_id) or "",
                        # 🧠 TA 记得的【具体的事】—— 只给这个角色自己那一本, 不许开天眼
                        "knows": knows_of(state, char_id),
                        "recent_scene": recent_scene,
                        "thread_tail": _thread_tail(state, char_id, 12),
                        "real_now": real_now_line(content, state),
                        "text": text}) or {}
    dc = int(out.get("closeness", 0) or 0)
    dr = int(out.get("romance", 0) or 0)
    dc, dr = _offscene_rel_budget(state, char_id, dc, dr, tun)   # 📱 刷分止血带
    if dc or dr:
        new_scores = relationships.apply_deltas(scores, dc, dr, tun)
        state.setdefault("rel", {})[char_id] = new_scores
        # 隔着屏幕也是经营 (Yi: 手机聊天也要影响好感): surface the movement so the
        # player SEES the bond move — and a tier crossed over text is a moment
        new_mode = relationships.derive_mode(c, new_scores, tun)
        out["rel_view"] = {"closeness": dc, "romance": dr,
                           "mode_name": relationships.name_of(new_mode),
                           "rel_up": (relationships.name_of(new_mode)
                                      if new_mode != mode else "")}
    return out


def _offscene_rel_budget(state: dict[str, Any], cid: str, dc: int, dr: int,
                         tun: dict[str, int]) -> tuple[int, int]:
    """📱 场外每句判分通道的日预算 (审查实锤: 事件记账制管住正戏后, 短信/评论的
    每句打分成了最快刷分通路 — 几十条短信可刷到恋人)。rel_events 开着时, 每角色
    每天经手机/评论入账的正向合计封顶; 负向照旧零限流 (伤害不设闸)。
    手机通道的完整事件化申报是下一刀 — 这一手是止血带。"""
    if not tun.get("rel_events"):
        return dc, dr
    day = int((state.get("clock") or {}).get("day", 1) or 1)
    book = state.setdefault("phone_rel_day", {})
    if book.get("_day") != day:
        book.clear()
        book["_day"] = day
    used = int(book.get(cid, 0) or 0)
    room = max(0, 4 - used)
    dc2 = min(dc, room) if dc > 0 else dc
    room -= max(0, dc2)
    dr2 = min(dr, room) if dr > 0 else dr
    book[cid] = used + max(0, dc2) + max(0, dr2)
    return dc2, dr2


def _digest_phone_overflow(state: dict[str, Any], cid: str, llm: LLM) -> None:
    """📱 电话记忆并账 (Yi: 手机聊天的记忆有问题): the prompt only carries the last 12
    messages verbatim — anything older folds into THIS character's rolling digest
    (the same memory the scenes read), so a long thread never evaporates."""
    th = _thread(state, cid)
    msgs = th.get("msgs") or []
    done = int(th.get("digested_upto") or 0)
    keep = 12
    if len(msgs) - done <= keep + 6:      # not enough overflow yet
        return
    chunk = msgs[done:len(msgs) - keep]
    if not chunk:
        return
    lines = [{"content": f"{'对方' if m.get('from') == 'me' else '你'}：{m.get('text', '')}"}
             for m in chunk if m.get("from") in ("me", "them")]
    prior = (state.get("memory_by_char", {}) or {}).get(cid) or ""
    try:
        out = llm.generate({"summarize": True, "prior_memory": prior,
                            # 🧠 顺手把【具体的事】抽出来 —— 搭在这一次调用上, 零新增成本。
                            # 摘要越滚越概括是它的本分, 而具体细节要另存一本才不会被概括掉。
                            "want_facts": True,
                            "new_lines": lines}) or {}
    except Exception:
        return
    mem = (out.get("memory") or "").strip()
    knows_add(state, cid, out.get("facts"))   # 🧠 事实记在这个角色名下 (认知有边界)
    if mem:
        state.setdefault("memory_by_char", {})[cid] = mem
        th["digested_upto"] = len(msgs) - keep


PHONE_SCENE_RECENT = 6


def phone_recent_for_scene(content: dict[str, Any], state: dict[str, Any],
                           cid: str) -> list[str]:
    """📱↔🎭 面对面时, TA 记得你刚才发的短信 (Yi 的铁律: 记忆一定要共享)。

    原本是单向镜: phone_send 收 beat_log —— 手机读得到剧情; 而主拍提示词里只有
    phone_unread 这个红点数, 没有任何一条真实短信。你连发五条再走到人家面前, 他不知道。

    并不是完全没接线: _digest_phone_overflow 会把溢出的旧消息折进 memory_by_char,
    但闸在「线程超过 18 条」。生产实测 10 条线程, 长度中位 13, 只有 2 条并过账 ——
    中位数天生够不着那个闸。折账那条路留着不动 (它管长线程的压缩), 这里补的是"刚聊过"。

    只给【这个角色自己那条线程】: 认知有边界, 别人看不见你俩的短信。
    已折账的部分不重复喂 (memory_by_char 里已经有了, 两处都喂是白花 token)。
    """
    th = ((state.get("phone") or {}).get("threads") or {}).get(cid) or {}
    msgs = th.get("msgs") or []
    if not msgs:
        return []
    start = max(int(th.get("digested_upto") or 0), len(msgs) - PHONE_SCENE_RECENT)
    out = []
    for m in msgs[start:]:
        t = str((m or {}).get("text") or "").strip()
        if not t or (m or {}).get("kind") == "read":
            continue
        out.append(("你：" if m.get("from") == "me" else "我：") + t[:60])
    return out[-PHONE_SCENE_RECENT:]


def invite_chip(content: dict[str, Any], state: dict[str, Any], where: str,
                by_id: str | None, by_name: str | None,
                llm: LLM | None = None) -> dict[str, Any] | None:
    """🎟 台词里的邀约 → 一张「跟 TA 去 / 留下」的确认条 (INVITE_MOVE 关着时永远 None)。

    抽成具名函数是为了让那把锁只装一处: 从前这段逻辑内联在回合尾, 四个由头
    (角色邀请 / 玩家提到的地名 / 生长种子 / 探索意图) 各写一遍, 锁一处漏三处。

    Yi 2026-08-06:「不通过文字控制！」—— 移动只剩点界面。角色照样能嘴上邀你,
    但要走得玩家自己点地图或点出口。见 INVITE_MOVE 那一段的原委与代价。
    """
    if not INVITE_MOVE:
        return None
    where = (where or "").strip()
    if not where:
        return None
    cur = location_view(content, state) or {}
    cur_id, exits = cur.get("id"), (cur.get("exits") or [])

    def _ok(d):
        return (d and d.get("id") and d.get("id") != cur_id
                and location_available(content, state, d)
                and (not exits or d.get("name") in exits or d.get("id") in exits))

    dest = resolve_location(content, where)
    if _ok(dest):
        return {"to": dest["id"], "to_name": dest.get("name"),
                "by_id": by_id, "by_name": by_name,
                **({} if by_id else {"self_go": True})}
    if dest:
        return None                      # 在册但走不到: 不造垃圾确认条
    near = near_location(content, where)
    if _ok(near):
        # 🧭 近似命中改道: 别造重复地点 — 确认条指真名, 不对玩家自然会拒绝
        return {"to": near["id"], "to_name": near.get("name"),
                "by_id": by_id, "by_name": by_name,
                **({} if by_id else {"self_go": True})}
    if near:
        return None
    # 铸地那半边早被 LLM_MAP_WRITES 堵死 (generate_and_move 在锁下返回 None)
    try:
        mint = generate_and_move(content, state, where, llm=llm, move=False)
    except ValueError:
        mint = None
    if mint and mint.get("id"):
        return {"to": mint["id"], "to_name": mint.get("name"),
                "by_id": by_id, "by_name": by_name, "minted": True,
                **({} if by_id else {"self_go": True})}
    return None


def deliver_due_phone(content: dict[str, Any], state: dict[str, Any]) -> int:
    """📬 延迟消息投递扫描: pending 里到点的搬进正式消息并计未读。幂等。

    ⚠️ 这里只搬字, 一个字都不新写 —— 那些话是玩家点发送那一刻模型就写好的。所以这个
    函数放进世界心跳也不违反「无点击不推进」(它不产生任何新内容)。

    三道闸 (都是评审实弹点名的坑, 原版一条没有):
      ⚰️ 死人不投递, 而且【清空】待发 —— 玩家中午发消息判了延迟、角色下午死了,
         晚上不许弹出一条死人发来的消息 (本仓最忌的文与实分家)。留着不清, 转生/
         复活时会集体喷发。
      🚿 一次最多送 PHONE_FLUSH_MAX 条 —— 攒了一堆同时到期, 不许变成引擎没点过的刷屏。
      🕰 老档宽恕 —— 老条目写的是 {deliver_at}(时段轴)。虚构钟的本里那条轴冻住不动,
         它们永远送不出去; 读侧一律当已到期, 一次性了结。
    """
    now_ts = _wall_ts()
    now_idx = _time_index(state)
    label = (clock_view(content, state) or {}).get("label", "")
    dead = _dead_ids(state)
    moved = 0

    def _ready(p: dict[str, Any]) -> bool:
        if not p.get("due_ts") and not p.get("due_idx"):
            return True                      # 🕰 老档条目 (只有 deliver_at 或什么都没有)
        if int(p.get("due_ts") or 0) > now_ts:
            return False
        idx = p.get("due_idx")
        return idx is None or int(idx) <= now_idx

    for cid, th in ((state.get("phone") or {}).get("threads") or {}).items():
        pend = list(th.get("pending") or [])
        if not pend:
            continue
        _hp = ((state.get("char_sim") or {}).get(cid) or {}).get("hp")
        if cid in dead or _hp == "dead":
            th["pending"] = []               # ⚰️ 死了: 连同还没到期的一起作废
            continue
        if _hp == "dying":
            # 🩸 判定侧 (_phone_beat) 判 never 认的是 (dead, dying), 读侧这道闸从前只
            # 写了 "dead" —— 而 set_char_hp 全仓只写 hurt/dying/None, 那半句是死代码,
            # 濒死一个都拦不住 (验收实跑: 濒死的人照样把话发了出去)。两侧同一本账。
            # 濒死不清空: 救回来了自然接着送; 真死了上面那条会清。
            continue
        ready = [i for i, p in enumerate(pend) if _ready(p)]
        if not ready:
            continue
        take = set(ready[:PHONE_FLUSH_MAX])  # 🚿 其余顺延, 不是丢掉
        for i in sorted(take):
            _row = {"from": "them", "text": str(pend[i].get("text") or "")[:120],
                    "at": label}
            if pend[i].get("img"):
                _row["img"] = pend[i]["img"]   # 📷 照片跟着它那条消息一起到
            th.setdefault("msgs", []).append(_row)
        # 按【下标】剔除, 不按值 —— 两条文本完全相同的待发会被 `p not in due` 一起删掉
        th["pending"] = [p for i, p in enumerate(pend) if i not in take]
        th["unread"] = int(th.get("unread", 0) or 0) + len(take)
        th.pop("last_read", None)   # 补偿送达 = 晾着的债清了
        _thread_cap(th)
        moved += len(take)
    return moved


def phone_send(content: dict[str, Any], state: dict[str, Any], persona: dict[str, Any],
               char_id: str, text: str, llm: LLM | None = None,
               beat_log: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """The player texts a character from anywhere. The character answers IN VOICE with
    their gated context (locked truths can't leak over text either) — or reads and says
    nothing (已读不回 is a statement too). Small relationship movement applies. Probing
    over text COUNTS: keep asking the right question and TA may crack right here in the
    thread (the unlock is global and sticky, same as in-scene)."""
    llm = lang_llm(llm or get_llm(), content)
    text = (text or "").strip()
    c = _phone_target(content, state, char_id, text)
    # 📍 same-room check: texting someone standing right next to you is a MOMENT, not
    # an error — they get to react to the absurdity in voice（「我人不就在这？」）
    here = any(ch.get("id") == char_id for ch in scene_characters(content, state))
    now_label = (clock_view(content, state) or {}).get("label", "")
    deliver_due_phone(content, state)   # 📬 打开线程先收到期的延迟消息 (Spec D)
    th = _thread(state, char_id)
    th["msgs"].append({"from": "me", "text": text[:200], "at": now_label})
    _thread_cap(th)
    newly, cracked = _phone_probe(content, state, char_id, text)
    # 📱 时机与形状一次判完 (引擎判定, 模型写词) —— 判据见 _phone_beat
    tier, shape = _phone_beat(content, state, c, text, here, th)
    if tier == "never":
        # ☠️ 判定层说了这条不该有回音 —— 不许再走延迟通道变成一个到期戳。
        # 放在 _phone_exchange 之前: 顺手省掉那次模型调用, 也避免 _apply_phone_judgments
        # 把一个濒死的人钉成「这就来」。
        _audit(state, "phone.never", True, str(c.get("name") or "")[:12], "无回音")
        th["unread"] = 0
        view = phone_thread(content, state, char_id)
        view["replied"] = False
        view["unlocked"] = cracked
        return view
    out = _phone_exchange(content, state, persona, c, text, llm, newly, same_room=here,
                          beat_log=beat_log, tier=tier, shape=shape)
    msgs = [dedash(m[:120]) for m in as_str_list(out.get("msgs"))][:5]
    # 配额挪到【兑现之后】才扣 —— 引擎点了 read 而模型没照做, 不该白白吃掉当天
    # 唯一的一次名额 (验收点名)。延迟支线里形状永远不是 read/burst, 不涉及。
    # ⏳ 判了延迟: 词现在就写好, 但【送达】押后。延迟的是送达不是生成 —— 投递侧因此
    #    零 LLM, 世界心跳搬运它也不违反「无点击不推进」。
    if tier != "now" and msgs:
        due = _phone_due(content, state, tier)
        # 📷「TA 在外面办事」正是最该拍一张「我在这儿呢」的时候 —— 从前这条支线在
        #    maybe_snap 之前就 return 了, 判了延迟的回复永远不带照片。照片挂在最后
        #    一条上, 跟那条消息【一起】送到 (提前出现等于剧透 TA 在哪)。
        snap_d = maybe_snap(content, state, c, msgs[-1])
        pend = list(th.get("pending") or [])
        for i, m in enumerate(msgs):
            row = {"text": m, **due}
            if snap_d and i == len(msgs) - 1:
                row["img"] = snap_d["url"]
            pend.append(row)
        th["pending"] = pend[-PHONE_PENDING_CAP:]   # 🧾 不许无界增长
        _audit(state, "phone.delay", True, f"{c.get('name', '')}·{tier}", f"{len(msgs)}条")
        try:
            from .. import metrics as _phm
            _phm.log("phone_shape", shape=shape, asked=shape, tier=tier, got=len(msgs))
        except Exception:
            pass
        th["unread"] = 0
        view = phone_thread(content, state, char_id)
        view["replied"] = False
        view["unlocked"] = cracked
        view["snap"] = snap_d   # router: 现在就排渲染, 图和消息各走各的路
        if out.get("rel_view"):
            view["rel"] = out["rel_view"]
        # 🧾 延迟【不等于】没答应。TA 在这条还没送到的回信里说了"我这就过来"/"这事我
        # 去办", 账上必须有 —— 否则正文说了、账上没有, 正是本仓最忌的文与实分家。
        # (验收实跑抓到: 早退跳过了这一句, 短信里应下的赴约/差事/约定全部丢。)
        _apply_phone_judgments(content, state, c, out, view, here)
        return view
    # 📱 形状④【已读：原因】晾着 (Spec C): 记账可追问, 「稍后：」补偿走延迟投递 (Spec D)
    # 🔒 形状以【引擎点的名】为准。从前这里是按模型输出【事后重认】—— 模型只要自己
    # 写一句「【已读：…】」或凑够四条, 就能绕开互斥表和每日配额, 判断权等于没收回来
    # (验收实跑证实)。现在只在引擎真的点了 read 时才认那套记账。
    _shape = shape
    if shape == "read" and msgs and msgs[0].startswith("【已读"):
        _reason = msgs[0].split("：", 1)[-1].split(":", 1)[-1].strip("】 ")[:12]
        th["last_read"] = {"reason": _reason or _t(content, "现在不想说", "not now"),
                           "at": _time_index(state)}
        th["msgs"].append({"from": "them", "kind": "read", "text": "已读", "at": now_label})
        for m in msgs[1:]:
            if m.startswith(("稍后：", "稍后:")):
                _mk = m.split("：", 1)[-1].split(":", 1)[-1].strip()[:120]
                if _mk:
                    th.setdefault("pending", []).append(
                        # 📮 待发只有一个写法 (判官定的): 走 _phone_due 的墙钟轴。
                        # 老的 deliver_at 时段轴在虚构钟的本里冻住不动 = 死信箱, 而
                        # 读侧对"没有 due_ts"的条目一律当已到期 —— 再写老格式会让
                        # 「稍后」当场就送到, 已读晾着那口气一秒都撑不住。
                        {"text": _mk, **_phone_due(content, state, "later")})
        _audit(state, "phone.shape", True, f"{c.get('name')}·已读晾着", _reason)
        msgs = []
    elif shape == "read":
        # 引擎点了 read, 模型却写了正文 —— 不兑现。那当天的配额不该白扣 (下面还回去)。
        _audit(state, "phone.shape", False, f"{c.get('name')}·点了已读没兑现", "")
    if _shape in ("read", "burst") and (_shape != "read" or th.get("last_read")):
        _phone_quota_spend(state, char_id, _shape)   # 真兑现了才扣配额
    if _shape != "read":
        th.pop("last_read", None)   # 正常回了 = 认过账翻篇
    try:
        from .. import metrics as _phm
        # 📊 口径与延迟那条写点一致 —— 报表逐个写点核对字段 (改写侧忘读侧是老病)。
        # asked=引擎点的名, got=模型真给了几条 ⇒ 两者一比才知道形状有没有兑现。
        # asked 必须是【引擎点的名】(shape), 不是事后按模型输出反推的 _shape ——
        # 反推的话兑现率在结构上恒 100%, 这个为验收造的读口就测不出任何不服从。
        _phm.log("phone_shape", shape=_shape, asked=shape, tier="now", got=len(msgs))
    except Exception:
        pass
    snap = None
    if msgs:
        # 📷 a reply may come with a photo — what TA sees right now, or a selfie
        snap = maybe_snap(content, state, c, msgs[-1])
        for m in msgs:
            th["msgs"].append({"from": "them", "text": m, "at": now_label})
        if snap:
            th["msgs"][-1]["img"] = snap["url"]
        _thread_cap(th)
    th["unread"] = 0  # the player is looking at this thread right now
    _digest_phone_overflow(state, char_id, llm)
    view = phone_thread(content, state, char_id)
    view["snap"] = snap  # router: queue the render, then strip before the wire
    view["replied"] = bool(msgs)
    view["unlocked"] = cracked  # 🔓 titles pried open by THIS text (UI toast)
    if out.get("rel_view"):
        view["rel"] = out["rel_view"]
    _apply_phone_judgments(content, state, c, out, view, here)
    return view


def _apply_phone_judgments(content: dict[str, Any], state: dict[str, Any], c: dict[str, Any],
                           out: dict[str, Any], view: dict[str, Any], here: bool) -> None:
    """The message的确定性后果 (the Yi contract: 传令要落账，不许只是嘴上应):
    - 赴约 (coming): the character agreed to come → their whereabouts is PINNED to the
      player's place; the arrival machinery walks them in. Meaningless if already here.
    - 应承 (task): they took on an errand → it becomes their standing intent on the sim
      sheet, the same ledger that constrains their behavior in every scene turn."""
    char_id = c.get("id")
    view["coming"] = False
    if out.get("coming") and not here and state.get("location_id"):
        pins = dict(state.get("char_pins") or {})
        pins[char_id] = state.get("location_id")
        state["char_pins"] = pins
        _audit(state, "phone.summon", True, c.get("name", ""))
        view["coming"] = True
    task = str(out.get("task") or "").strip()
    if task and task not in ("无", "none"):
        _sim(state, char_id)["intent"] = task[:40]
        _sim(state, char_id)["intent_at"] = _time_index(state)   # ⏳ 应承有保质期
        _audit(state, "phone.task", True, f"{c.get('name', '')}:{task[:20]}")
        view["task"] = task[:40]
    # 🤝 短信里定下的约会走同一本约定账（到点没去，TA 记仇的那本）
    pm = out.get("promise")
    if isinstance(pm, dict) and str(pm.get("what") or "").strip():
        made = make_promise(content, state, c, pm, tuning_for(content))
        if made:
            when = promise_when_label(content, made, state)
            loc_nm = (_location_by_id(content, made.get("location_id")) or {}).get("name") or ""
            _audit(state, "phone.promise", True, f"{c.get('name', '')}:{made['what']}")
            view["promise"] = {"what": made["what"], "when": when, "place": loc_nm,
                               "romantic": bool(made.get("romantic"))}
            view["promises"] = promises_view(content, state)


def phone_call(content: dict[str, Any], state: dict[str, Any], persona: dict[str, Any],
               char_id: str, text: str, llm: LLM | None = None,
               beat_log: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """📞 the player CALLS a character. Live voice: the reply comes back as spoken lines
    plus one line of what the player HEARS down the line (背景音 — a truth of its own).
    Same gate as everything else; probing on a call counts too. A character whose 作息
    says they're unreachable right now simply doesn't pick up."""
    llm = lang_llm(llm or get_llm(), content)
    text = (text or "").strip()
    c = _phone_target(content, state, char_id, text)
    if any(ch.get("id") == char_id for ch in scene_characters(content, state)):
        raise ValueError("TA就在你身边，当面说吧")
    now_label = (clock_view(content, state) or {}).get("label", "")
    th = _thread(state, char_id)
    # 作者的班表说 TA 这个钟点找不到 → 无人接听 (the world doesn't bend for the dial tone)。
    # 🔒 判据与通讯录共用 _phone_unreachable, 不许在这儿手拼 (实弹 2026-07-30):
    # 曾直读 _char_home 跳过前六级 —— 角色被钉在码头, 地图和对话都说"在那儿", 电话却回
    # "TA此刻不知在何处"; 改成硬判 char_position==AWAY 又走过了头, 让散文离场的永久钉子
    # 等于关机, 于是短信召得回、电话永远不接。两次都是同一个病: 判据没归一。
    if _phone_unreachable(content, state, c):
        th["msgs"].append({"from": "me", "text": f"📞 {text[:120]}", "at": now_label, "call": True})
        th["msgs"].append({"from": "sys", "text": "（无人接听。TA此刻不知在何处。）",
                           "at": now_label, "call": True})
        _thread_cap(th)
        th["unread"] = 0
        view = phone_thread(content, state, char_id)
        view["replied"] = False
        view["unlocked"] = []
        return view
    th["msgs"].append({"from": "me", "text": f"📞 {text[:200]}", "at": now_label, "call": True})
    _thread_cap(th)
    newly, cracked = _phone_probe(content, state, char_id, text)
    out = _phone_exchange(content, state, persona, c, text, llm, newly, call=True,
                          beat_log=beat_log)
    msgs = [dedash(m[:120]) for m in as_str_list(out.get("msgs"))][:3]
    ambient = dedash((out.get("ambient") or "").strip())[:60]
    if ambient:
        th["msgs"].append({"from": "sys", "text": f"（{ambient}）", "at": now_label, "call": True})
    if msgs:
        for m in msgs:
            th["msgs"].append({"from": "them", "text": m, "at": now_label, "call": True})
    else:
        th["msgs"].append({"from": "sys", "text": "（电话那头沉默了几秒，挂断了。）",
                           "at": now_label, "call": True})
    _thread_cap(th)
    th["unread"] = 0
    _digest_phone_overflow(state, char_id, llm)
    view = phone_thread(content, state, char_id)
    view["replied"] = bool(msgs)
    view["unlocked"] = cracked
    if out.get("rel_view"):
        view["rel"] = out["rel_view"]
    _apply_phone_judgments(content, state, c, out, view, here=False)
    return view


# ── 📮 信箱 (mail) ───────────────────────────────────────────────────────────────
# Long-form letters, the slow warm counterpart to texts: a lover writes when the
# relationship crosses into 恋人, and a long absence earns a letter from whoever
# missed the player most. Engine-triggered; the model only writes the words.
MAIL_CAP = 20


def _mailbox(state: dict[str, Any]) -> list[dict[str, Any]]:
    return state.setdefault("phone", {}).setdefault("mail", [])


def mail_push(content: dict[str, Any], state: dict[str, Any], char: dict[str, Any],
              subject: str, body: str) -> dict[str, Any]:
    import uuid as _uuid
    box = _mailbox(state)
    m = {"id": f"mail_{_uuid.uuid4().hex[:8]}", "char_id": char.get("id"),
         "name": char.get("name") or "", "avatar_url": char.get("avatar_url"),
         "subject": dedash((subject or "").strip())[:24] or "一封信",
         "body": dedash((body or "").strip())[:800],
         "at": (clock_view(content, state) or {}).get("label", ""), "read": False}
    box.append(m)
    del box[:-MAIL_CAP]
    return m


def compose_letter(content: dict[str, Any], state: dict[str, Any], char: dict[str, Any],
                   reason: str, hint: str, llm: LLM) -> dict[str, Any]:
    """One letter in this character's hand. LLM-written; deterministic fallback."""
    tun = tuning_for(content)
    scores = (state.get("rel") or {}).get(char.get("id")) or relationships.new_scores()
    try:
        out = llm.generate({"compose_letter": True, "device": phone_device(content), "era": era_of(content),
                            "char": {"name": char.get("name"), "role": char.get("role") or "",
                                     "persona_text": (char.get("persona_text") or "")[:200],
                                     "eq_style": (char.get("eq_style") or "")[:120],
                                     "examples": [str(x)[:60] for x in
                                                  (char.get("examples") or [])][:4]},
                            "relation": relationships.name_of(
                                relationships.derive_mode(char, scores, tun)),
                            "reason": reason, "hint": hint,
                            # 🧠 信是最该提起旧事的地方 —— 认知边界照旧, 只给这一本
                            "knows": knows_of(state, char.get("id")),
                            "memory": (state.get("memory_by_char", {}) or {})
                            .get(char.get("id")) or ""}) or {}
    except Exception:
        out = {}
    subject = (out.get("subject") or "").strip()
    body = (out.get("body") or "").strip()
    if not body:
        subject = subject or _t(content, "想对你说的话", "The things I meant to say")
        body = _t(content,
                  f"有些话，当着面说不出口，只好写下来。\n\n这段日子里发生的事，"
                  f"我想了很多。你是其中想得最多的那一个。\n\n—— {char.get('name') or ''}",
                  "Some things won't come out face to face, so I'm writing them down.\n\n"
                  "I've been thinking about everything that's happened. "
                  f"Mostly, I've been thinking about you.\n\n— {char.get('name') or ''}")
    return mail_push(content, state, char, subject, body)


def mail_view(content: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    box = _mailbox(state)
    return {"device": phone_device(content),
            "mail": [{k: v for k, v in m.items() if k != "body"} for m in reversed(box)],
            "unread": sum(1 for m in box if not m.get("read"))}


def mail_open(state: dict[str, Any], mail_id: str) -> dict[str, Any] | None:
    for m in _mailbox(state):
        if m.get("id") == mail_id:
            m["read"] = True
            return dict(m)
    return None


def phone_total_unread(content: dict[str, Any], state: dict[str, Any]) -> int:
    """Everything blinking on the 小手机: unread texts + unread letters."""
    return (phone_threads_view(content, state)["unread"]
            + sum(1 for m in (state.get("phone") or {}).get("mail") or [] if not m.get("read")))


# ── 💌 你不在的时候 (offline pulse) ───────────────────────────────────────────────
def offline_pulse(content: dict[str, Any], state: dict[str, Any], here_ids: set,
                  away_hours: float, llm: LLM) -> list[dict[str, Any]]:
    """The world missed the player while they were gone. On a comeback turn, the
    absent characters who'd genuinely reach out do: the warmest hearts first (lover >
    flirt > an open promise > friend), each with ONE in-voice message about the time
    apart. A LONG absence (≥ letter_away_hours) upgrades the warmest one to a real
    LETTER in the 信箱. Deterministic triggers; the model only writes the words.
    Returns UI event payloads ({...,"mail": True} for the letter)."""
    if not phone_enabled(content):
        return []
    tun = tuning_for(content)
    dead = _dead_ids(state)
    met = set(state.get("met_ids") or [])
    rels = state.get("rel") or {}
    open_pr = {p.get("char_id") for p in state.get("promises") or [] if p.get("status") == "open"}
    ranked: list[tuple[int, dict[str, Any], str]] = []
    for c in _characters(content):
        cid = c.get("id")
        if not cid or cid not in met or cid in dead or cid in here_ids \
                or cid == state.get("player_character_id"):
            continue
        mode = relationships.derive_mode(c, rels.get(cid) or relationships.new_scores(), tun)
        if mode == "lover":
            ranked.append((0, c, "你们是恋人，TA数着日子想你，捎来的话要软、要往心里去"))
        elif mode == "flirt":
            ranked.append((1, c, "你们正暧昧着，TA嘴上不肯认，字里行间都是惦记"))
        elif cid in open_pr:
            ranked.append((2, c, "你们还有个约定没赴，TA提一句，看你还记不记得"))
        elif mode == "friend":
            ranked.append((3, c, "TA这些天遇到点事，想找你说说，顺口问你去哪了"))
    ranked.sort(key=lambda t: t[0])
    # 🎰 变率强化 (Spec H): 谁发不发是掷出来的 — 越暖概率越高但【永不保证】,
    # 不确定性本身是钩子; 单角色冷却防轰炸 (initiate_cooldown 天, tuning)
    _init = state.setdefault("initiate", {})
    _today = int((state.get("clock") or {}).get("day", 1) or 1)
    _cool = int(tun.get("initiate_cooldown", 1) or 1)
    _P_BY_RANK = {0: 0.75, 1: 0.55, 2: 0.5, 3: 0.3}
    _picked: list[tuple[int, dict[str, Any], str]] = []
    _letter_due = away_hours >= tun["letter_away_hours"]
    for rank, c, hint in ranked:
        _cid = c.get("id")
        if _today - int((_init.get(_cid) or {}).get("day", -99) or -99) < _cool:
            continue
        # 💌 超长离别的信是情感兑付, 免掷 (骰子只管日常问候的不确定性)
        if not (_letter_due and rank <= 1 and not _picked) \
                and _rng.random() >= _P_BY_RANK.get(rank, 0.3):
            _audit(state, "reach.skip", True, c.get("name", ""), "这次没舍得发")
            continue
        _init[_cid] = {"day": _today}
        _picked.append((rank, c, hint))
    now_label = (clock_view(content, state) or {}).get("label", "")
    out: list[dict[str, Any]] = []
    for rank, c, hint in _picked[:PHONE_MAX_PER_TURN]:
        # a LONG absence: the warmest one writes a letter instead of a text
        if not out and away_hours >= tun["letter_away_hours"] and rank <= 1:
            m = compose_letter(content, state, c,
                               "away_letter",
                               f"你有{int(away_hours // 24)}天没见到TA了，把这些天攒下的话写成一封信",
                               llm)
            out.append({"char_id": c.get("id"), "name": c.get("name") or "",
                        "avatar_url": c.get("avatar_url"), "mail": True,
                        "msgs": [m["subject"]], "device": phone_device(content)})
            continue
        msgs = compose_message(content, state, c, "away_pulse",
                               f"你们有阵子没见了（离开了约{max(1, int(away_hours))}小时）。{hint}。",
                               _t(content, "好久没你的消息了。一切都好吗？",
                                  "Haven't heard from you in a while. Everything okay?"), llm)
        out.append(phone_push(content, state, c, msgs, now_label))
    return out


def rel_log(state: dict[str, Any], char_id: str | None, act: int, kind: str, text: str) -> None:
    """Append a moment to this character's 关系大事记 (capped)."""
    if not char_id or not (text or "").strip():
        return
    log = dict(state.get("rel_log") or {})
    entries = list(log.get(char_id) or [])
    entries.append({"act": int(act), "kind": kind, "text": text.strip()})
    log[char_id] = entries[-30:]
    state["rel_log"] = log


# ── 💞 名场面收藏 (the album) ─────────────────────────────────────────────────────
# The run's keepsake gallery: golden moments, tier-ups, honored dates, endings — the
# scenes worth reliving, collected as they happen and browsable from the 小手机.
# Each entry is a 时刻卡: front = the place's backdrop + the key line, back = the
# excerpt/date/rarity. `bg` pins WHERE it happened so the card wears that place's art.
_ALBUM_RARITY = {"golden": 3, "breakthrough": 3, "ending": 2, "rel_up": 2, "date": 2,
                 "secret": 2, "crit": 2, "promise": 1}


def album_add(content: dict[str, Any], state: dict[str, Any], kind: str, title: str,
              text: str, char: dict[str, Any] | None = None,
              rarity: int | None = None) -> dict[str, Any]:
    entry = {"kind": kind, "title": (title or "").strip()[:24],
             "text": dedash((text or "").strip())[:200],
             "char_id": (char or {}).get("id"), "name": (char or {}).get("name") or "",
             "at": (clock_view(content, state) or {}).get("label", ""),
             "act": int(state.get("act", 1) or 1),
             "bg": state.get("location_id"),
             "rarity": max(1, min(3, int(rarity or _ALBUM_RARITY.get(kind, 1))))}
    album = list(state.get("album") or [])
    album.append(entry)
    state["album"] = album[-40:]
    return entry


def golden_moment_now(content: dict[str, Any], state: dict[str, Any], llm: LLM,
                      recent: list[dict[str, str]],
                      char_id: str | None = None) -> dict[str, Any] | None:
    """✨ 玩家主动点的金色瞬间 (Yi 2026-08-04 改制)。

    原来是程序每回合摇一次骰 (golden_chance 4%), 中了就当场写。喂给模型的上下文只有
    said_this_turn[-4:] —— **本回合最后四句** —— 模型根本不知道最近发生了什么, 写出
    来的东西又贵又空 (Yi:「没有全部理解最近的对话」)。

    改成玩家自己挑时机点。两条是一体的: 正因为不再每回合白摇, 才付得起「认真读一遍
    最近的戏」的成本 —— `recent` 由调用方从存档的 beats 里捞几十拍进来。

    返回 {"title","text","char_id","name","closeness","romance"}; 不该出/没出就 None。
    ⚠️ 模型哑火不扣冷却 —— 那等于收了钱不给货。
    """
    if state.get("ended"):
        return None
    if int(state.get("golden_cd", 0) or 0) > 0:
        return None
    tun = tuning_for(content)
    rel_all = state.setdefault("rel", {})
    pool = [c for c in present_characters(content, int(state.get("act", 1) or 1),
                                          _dead_ids(state))
            if c.get("id") != state.get("player_character_id")]
    if char_id:
        pool = [c for c in pool if c.get("id") == char_id] or pool
    if not pool:
        return None
    star = max(pool, key=lambda c: (
        int((rel_all.get(c.get("id")) or {}).get("romance", 0)) * 2
        + int((rel_all.get(c.get("id")) or {}).get("closeness", 0))))
    sid = star.get("id")
    scores = rel_all.get(sid) or relationships.new_scores()
    mode = relationships.derive_mode(star, scores, tun)
    g = llm.generate({"golden_moment": True,
                      "char": {"name": star.get("name"), "role": star.get("role") or "",
                               "persona_text": (star.get("persona_text") or "")[:200],
                               "eq_style": (star.get("eq_style") or "")[:120]},
                      "relation": relationships.name_of(mode),
                      "place": (current_location(content, state) or {}).get("name") or "",
                      "clock": (clock_view(content, state) or {}).get("label", ""),
                      # 🔑 质量的命门: 玩家点的这一次要读【最近的戏】, 不是本回合四句
                      "recent": list(recent or [])[-40:],
                      "on_demand": True,
                      "mature": bool(state.get("mature"))}) or {}
    text = dedash((g.get("text") or "").strip())
    if not text:
        return None      # 哑火 — 冷却一分不扣, 玩家可以立刻再点
    # 标题消毒: 模型自带的括号会跟外层「」套娃 (实弹: ✨「【绿宝与板车轮声】」)
    title = (g.get("title") or "").strip().strip("《》「」【】『』“”")[:16] or "金色瞬间"
    state["golden_cd"] = max(1, int(tun.get("golden_cooldown") or 10))
    old = rel_all.get(sid) or relationships.new_scores()
    rel_all[sid] = relationships.apply_deltas(
        old, 2, 2 if mode in ("flirt", "lover") else 1, tun)
    dc = int(rel_all[sid].get("closeness", 0)) - int(old.get("closeness", 0))
    dr = int(rel_all[sid].get("romance", 0)) - int(old.get("romance", 0))
    album_add(content, state, "golden", title, text, star)
    rel_log(state, sid, int(state.get("act", 1) or 1), "golden",
            _t(content, f"「{title}」：{text[:40]}", f"“{title}”: {text[:80]}"))
    # 💘 金色瞬间是一次暖峰 — 有恋爱风格的角色下次会回拉一下
    if relationships.love_style_of(star):
        _sim(state, sid)["warm_peak"] = {"t": _time_index(state), "served": False}
    return {"title": title, "text": text, "char_id": sid,
            "name": star.get("name") or "", "closeness": dc, "romance": dr}


def _last_line_of(said: list[dict[str, str]], name: str) -> str:
    """The most recent thing this character said this turn (album snippet material)."""
    for s in reversed(said or []):
        if s.get("speaker") == name and (s.get("text") or "").strip():
            return s["text"].strip()
    return ""


def _re_split_mats(s: str) -> list[str]:
    import re as _re
    return _re.split(r"[、，,+和/]", s or "")


def _inv_find(items: list, name: str) -> int:
    """Index of an item matching `name` leniently, else -1."""
    n = (name or "").strip()
    for i, it in enumerate(items or []):
        inm = (it.get("name") or "").strip()
        if inm and (inm == n or inm in n or n in inm):
            return i
    return -1


def _inv_add(state: dict[str, Any], name: str, detail: str = "") -> bool:
    """模型报审/确定性动词的单件入包: 防重复守卫照旧 (模型隔轮重报同一收获 =
    幻觉, 不是第二件)。行出生即带籍 (tid + qty, 物性卡快照进档 — items.py)。"""
    items = list(state.get("inventory") or [])
    if not (name or "").strip() or _inv_find(items, name) >= 0:
        return False
    tid = items_mod.ensure_template(state, name)
    items.append({"name": name.strip(), "tid": tid, "qty": 1,
                  **({"detail": detail.strip()} if detail.strip() else {})})
    state["inventory"] = items
    return True


def _inv_remove(state: dict[str, Any], name: str) -> dict[str, Any] | None:
    items = list(state.get("inventory") or [])
    i = _inv_find(items, name)
    if i < 0:
        return None
    it = items.pop(i)
    state["inventory"] = items
    return it


_STASH_WORDS = ("放在", "搁在", "留在", "藏在", "藏到", "藏好", "存放", "寄存",
                "收纳", "放下", "收在", "存到", "埋在")


def stash_items(content: dict[str, Any], state: dict[str, Any],
                player_input: str, channel: str = "say") -> list[dict[str, Any]]:
    """📦 收纳: saying/doing 「把X放在这里/藏好/寄存」 with X in the pocket books it into
    THIS place's stash. DETERMINISTIC twin of retrieve_stash — the engine keeps the
    ledger itself instead of hoping the model fills the right judgment field (it used
    to reach for item_lost and the thing simply vanished)."""
    if channel not in ("do", "say"):
        return []
    text = (player_input or "").strip()
    lid = state.get("location_id")
    if not text or not lid or not any(w in text for w in _STASH_WORDS):
        return []
    # handing something TO someone is a gift/trade, not a stash — leave it to judgment
    if any(w in text for w in ("送", "给你", "给他", "给她", "递给", "交给", "还给", "换")):
        return []
    put = []
    for it in list(state.get("inventory") or []):
        nm = (it.get("name") or "").strip()
        if nm and nm in text:
            _inv_remove(state, nm)
            stashes = dict(state.get("stashes") or {})
            stashes.setdefault(lid, []).append(it)
            state["stashes"] = stashes
            put.append(it)
    return put


def retrieve_stash(content: dict[str, Any], state: dict[str, Any],
                   player_input: str, channel: str = "say") -> list[dict[str, Any]]:
    """取回寄存: naming an item you stashed at THIS place puts it back in your pocket.
    Deterministic, mirrors search_props. 说/做/看 all count — 「取回它」 is usually said."""
    if channel not in ("do", "think", "say"):
        return []
    if not any(w in (player_input or "") for w in ("取回", "拿回", "取出", "拿出", "取走", "带上")):
        return []
    loc = current_location(content, state)
    if not loc:
        return []
    lid = loc.get("id")
    stash = list((state.get("stashes") or {}).get(lid) or [])
    got = []
    for it in list(stash):
        if (it.get("name") or "") and _contains_any(player_input, [it["name"]]):
            stash.remove(it)
            _inv_add(state, it.get("name", ""), it.get("detail", ""))
            got.append(it)
    if got:
        stashes = dict(state.get("stashes") or {})
        if stash:
            stashes[lid] = stash
        else:
            stashes.pop(lid, None)
        state["stashes"] = stashes
    return got


# 🤲 受赠: the player says they take/accept a named thing. Zh + a conservative en set.
_ACCEPT_RE_ZH = re.compile(
    r"(?:收下|接过|接下|收好|揣上|揣好|拿起|捡起|拾起|抄起|拿走|取走|拿上|捡走)"
    r"(?:这把|那把|这个|那个|这枚|那枚|这块|那块|这)?"
    r"([^，。！？!?,.、\s]{1,12})")
_ACCEPT_BA_RE_ZH = re.compile(
    r"把(?:这把|那把|这个|那个)?([^，。！？!?,.、\s]{1,12}?)"
    r"(?:收进|收入|放进|装进|收好|揣进|揣好|收起来|收下|拿上|带上|捡走|拿走)")
_ACCEPT_RE_EN = re.compile(
    r"(?:\baccept the\b|\bpocket the\b|\btuck the\b|\bput the\b|\bpick up the\b|\bgrab the\b)\s+([a-zA-Z' -]{2,30}?)"
    r"(?:\s+(?:in|into|away)\b|[,.!?]|$)", re.IGNORECASE)


_EXAMINE_WORDS = ("掂", "端详", "打量", "细看", "翻看", "查验", "examine")


def examine_items(content: dict[str, Any], state: dict[str, Any], player_input: str,
                  channel: str = "say") -> list[tuple[str, str]]:
    """🔍 主动查验 (物品实体化 第3题③): 掂一掂/端详一件随身或在册物件 →
    物性卡经叙事渗出 (确定性孪生, 零 LLM)。想知道的玩家有确定的获知渠道,
    不想管的玩家不被标签打扰。返回 [(物名, 叙事句)]。"""
    if channel not in ("do", "think", "say"):
        return []
    text = (player_input or "").strip()
    if not text or not any(w in text for w in _EXAMINE_WORDS):
        return []
    # 🎒 掂量隔离区里的名字 = 玩家对它发起动词 — 最强转正信号 (P3 §4.1)
    for _q in list(state.get("item_quarantine") or []):
        if _q.get("name") and _q["name"] in text:
            items_mod.quarantine_touch(state, _q["name"])
    out: list[tuple[str, str]] = []
    rows = list(state.get("inventory") or []) \
        + list(items_mod.scene_rows(state, state.get("location_id")))
    for r in rows:
        nm = (r.get("name") or "").strip()
        if not nm or nm not in text:
            continue
        card = items_mod.card_of(state, r)
        bits = ([str(card["desc"])] if card.get("desc") else []) \
            + [items_mod.card_desc(card)]
        indiv = "，".join(str(v) for v in (r.get("indiv") or {}).values() if str(v).strip())
        if indiv:
            bits.append(indiv)
        desc = "。".join(b for b in bits if b)
        if desc:
            out.append((nm, desc))
        if len(out) >= 2:   # 一回合至多查验两件, 别把回合变成鉴宝大会
            break
    return out


def accept_item(content: dict[str, Any], state: dict[str, Any], player_input: str,
                channel: str = "say", history: list[dict[str, str]] | None = None
                ) -> list[dict[str, Any]]:
    """🤲 受赠确定性化: 「收下短刃」「把短刃收入背包」 books the thing into the pocket —
    DETERMINISTIC third twin of stash/retrieve. The model's item_gained judgment misses
    real handovers often enough (格伦 said 拿着, twice, and nothing landed) that the
    engine keeps this ledger itself. Guard against minting arbitrary loot: the named
    thing must exist in the world — carried by someone present, or spoken of in the
    recent conversation."""
    if channel not in ("do", "say"):
        return []
    text = (player_input or "").strip()
    if not text:
        return []
    # handing something AWAY is the opposite move — that stays with gift/trade judgment
    if any(w in text for w in ("送", "给你", "给他", "给她", "递给", "交给", "还给")):
        return []
    names: list[str] = []
    for rx in (_ACCEPT_BA_RE_ZH, _ACCEPT_RE_ZH, _ACCEPT_RE_EN):
        names += [m.strip(" 的了吧。，、") for m in rx.findall(text)]
    names = [n for n in names if n and n not in ("背包", "东西", "它", "他", "她", "it", "them")]
    if not names:
        return []
    recent = " ".join(str(m.get("content", "")) for m in (history or [])[-12:])
    got: list[dict[str, Any]] = []
    pcid = state.get("player_character_id")
    for n in names:
        if _inv_find(state.get("inventory") or [], n) >= 0:
            continue  # already carrying it
        item = None
        from_scene = False
        # someone present is carrying it → a consensual handover moves the real object
        for c in scene_characters(content, state):
            if c.get("id") == pcid:
                continue
            their = char_items(content, state, c.get("id"))
            ti = _inv_find(their, n)
            if ti >= 0:
                item = their.pop(ti)
                break
        # 🎒 场景在册物 (实体化 P1): 申报过的场景物件是真东西 — 拿走 = 场上少一件
        if item is None:
            srow = items_mod.scene_take(state, state.get("location_id"), n)
            if srow is not None:
                item, from_scene = srow, True
        # otherwise it must at least have come up in the recent conversation
        if item is None and n in recent:
            item = {"name": n}
        # ⚖️ 拿取判定 (第3题②): 从环境里拿的东西过物性关 — 失败点名肇因属性,
        # 且东西留回原地 (人递到手里的不查: 递得动就接得住)。判定驳回是终审:
        # 绝不落 _pending_take, 否则回合末「正文认可」通道会绕过物理关 (实弹后门)
        if item is not None and from_scene:
            rejected = False
            card = items_mod.card_of(state, item)
            for ok, why in (items_mod.lift_check(card, _player_strength(state)),
                            items_mod.bag_check(card)):
                if not ok:
                    _audit(state, "take", False, n, why)
                    items_mod.scene_add(state, state.get("location_id"), n)
                    rejected = True
                    break
            if rejected:
                continue
        if item is not None and _inv_add(state, item.get("name", n), item.get("detail", "")):
            got.append(item)
        elif item is None:
            # 🎣 环境物件: the player named a thing the ledger can't source (a pole by the
            # wall the prose is about to invent). Park it; if THIS turn's prose ratifies
            # the name, settle_pending_takes books it — no loot minted, no pickup lost.
            pend = list(state.get("_pending_take") or [])
            if n not in pend:
                pend.append(n)
            state["_pending_take"] = pend[:2]
            items_mod.quarantine_touch(state, n)   # 伸手 = 最强转正信号 (P3 §4.1)
    return got


def settle_pending_takes(state: dict[str, Any], all_beats: list[dict[str, Any]]) -> list[str]:
    """End of turn: a pending environmental take whose name the prose actually used is
    REAL — book it. Unratified names drop silently (the scene refused the pickup)."""
    pend = list(state.get("_pending_take") or [])
    if not pend:
        return []
    state["_pending_take"] = []
    txt = " ".join((b.get("text") or "") for b in all_beats)
    booked = []
    for n in pend:
        if n and n in txt and _inv_find(state.get("inventory") or [], n) < 0:
            # ⚖️ 正文认可 ≠ 免检: 环境物件入包同样过物性关 (石碑不因被提到就装进背包)
            _card = items_mod.card_of(state, n)
            _bad = next((why for ok, why in
                         (items_mod.lift_check(_card, _player_strength(state)),
                          items_mod.bag_check(_card)) if not ok), "")
            if _bad:
                _audit(state, "take", False, n, _bad)
            elif _inv_add(state, n):
                _audit(state, "take", True, f"{n}（正文认可）")
                booked.append(n)
        elif n:
            _audit(state, "take", False, n, "正文未认可")
    return booked


# 🚶 说走就走: the player's own clear "go there" EXECUTES, deterministically — the fourth
# twin (props/stash/accept/move). Waiting for the model to honor a 地点 marker left players
# saying 「去工会」 three times and standing still.
_MOVE_NEG = ("别去", "不去", "不要去", "先不去", "不想去", "别回", "怎么去", "如何去", "怎么走")
_MOVE_OTHER_RE = re.compile(
    r"(?:你|您|你们|他|她|它|TA|他们|她们)\s*(?:先|自己)?\s*(?:去|回|前往)"
    r"|(?:让|叫|派|请|带|催|送)\s*\S{1,6}?(?:去|回|前往)")
_MOVE_DEST_ZH = re.compile(
    r"(?:前往|走到|走去|走回|赶到|赶去|赶回|动身去|出发去|走进|进入|踏入|穿过"
    # 去 only counts as SETTING OUT when it isn't the tail of a compound verb —
    # 擦去汗水/抹去/拭去/失去/死去/褪去/望去 never mint「汗水」as a destination
    r"|(?<![擦抹拭挥拂褪失死逝除减略抛甩撇掸洗刮剪削隐退散拿送递寄捎传望看离夺])去(?!死|了)"
    r"|回到|回(?!头|想|忆|味|应|答|复|收|避|绝|放|礼|敬|嘴|神|过头))"
    r"([^，。！？!?,.;；、\s]{1,20})")
# directionless leave (「离开」「出去」): only unambiguous with exactly ONE way out
_LEAVE_RE = re.compile(r"^(?:我)?(?:先)?(?:离开|出去|出门)(?:这里|这儿|吧|了)?$")
# a plausible PLACE NAME never contains pronouns, gaze verbs or question tails —
# the parser once minted a location called 「头看看他跟不跟」 (from 回头看看…)
_BAD_PLACE_RE = re.compile(r"[他她你我您谁]|看看|跟不跟|[吗呢吧么]$"
                           r"|^(情况|动静|热闹|究竟|风景|一眼|一圈|一趟|一下)$")


_CJK_ANY = re.compile(r"[一-鿿]")
# 🌐 EN 泛指/坏词头 (第二刀): 指方向不指实体的词, 和不可能开启地名的词
_EN_DEICTIC = {"here", "there", "somewhere", "elsewhere", "nearby", "around",
               "outside", "inside", "away", "anywhere", "someplace", "home"}
_EN_BAD_LEAD = ("i", "you", "he", "she", "they", "we", "it", "me", "him", "her",
                "them", "us", "who", "what", "where", "when", "why", "how",
                "tell", "ask", "let", "see", "do", "does", "did")


def _bad_place_name(n: str) -> bool:
    n = (n or "").strip()
    if not n or len(n) < 2:
        return True
    if _CJK_ANY.search(n):
        return len(n) > 12 or n in _DEICTIC or bool(_BAD_PLACE_RE.search(n))
    # 🌐 EN 尺: 12 字符的 CJK 上限曾把 "the old lighthouse" 一刀切驳回 — 文实分家复发。
    # 英文量词数不量字符: ≤5 词、≤40 字符、词头不是代词/疑问/使役词。
    if len(n) > 40 or "?" in n or "？" in n:
        return True
    ws = n.lower().split()
    return (len(ws) > 5 or n.lower() in _EN_DEICTIC or ws[0] in _EN_BAD_LEAD
            or bool(_BAD_PLACE_RE.search(n)))


# 🗺 地名准入门 (Yi 实锤: 「去求老爹把秘方卖了」被解析成去处「求老爹把秘方卖」):
# 已知地点走注册库 (resolve_location); 要铸造【新】去处的名字必须长得像个地方 —
# 带地名后缀直接放行, 无后缀只许 ≤6 字的干净名词; 含动词/介词/请求字的句子碎片免谈
_PLACE_SUFFIX = ("街", "巷", "店", "馆", "楼", "房", "台", "山", "海", "湖", "河", "桥",
                 "寺", "庙", "院", "校", "厅", "室", "城", "村", "镇", "园", "场", "铺",
                 "摊", "口", "道", "路", "堤", "塔", "所", "局", "吧", "厂", "港", "站",
                 "门", "洞", "林", "岛", "阁", "殿", "坊", "市", "区", "顶", "库", "仓",
                 "崖", "滩", "谷", "峰", "田", "井", "亭")
_PLACE_VERBY = re.compile(r"[求把被让请帮跟对给说问买卖借还偷抢救杀骂嫁娶想愿肯敢趟]")


def _placey(n: str) -> bool:
    n = (n or "").strip()
    if _bad_place_name(n):
        return False
    if not _CJK_ANY.search(n):
        return len(n.split()) <= 4   # 🌐 EN: 词数尺 (句子碎片已被 bad 门滤掉)
    if any(n.endswith(s) for s in _PLACE_SUFFIX):
        return True
    return len(n) <= 6 and not _PLACE_VERBY.search(n)


# deictics that name a direction, not a place — never a generatable destination
_DEICTIC = ("哪里", "哪儿", "那里", "这里", "那边", "这边", "前面", "后面",
            "里面", "外面", "附近", "别处", "远处")
_MOVE_DEST_EN = re.compile(
    r"\b(?:go|head|walk|move|travel|run|get|come)\s+(?:straight\s+)?(?:back\s+)?to\s+(?:the\s+)?"
    r"([^,.!?;]{2,40})", re.IGNORECASE)


def _route_exists(content: dict[str, Any], state: dict[str, Any],
                  from_id: str | None, to_id: str) -> bool:
    """Is `to_id` reachable from `from_id` through currently-available exits (BFS)?
    Mirrors apply_move's leniency: a current place with NO authored exits = free travel."""
    if not from_id or from_id == to_id:
        return True
    locs = {l.get("id"): l for l in _locations(content) if l.get("id")}
    cur = locs.get(from_id)
    if cur is not None and not (cur.get("exits") or []):
        return True
    seen, frontier = {from_id}, [from_id]
    while frontier:
        nxt: list[str] = []
        for lid in frontier:
            for ref in (locs.get(lid) or {}).get("exits") or []:
                d = resolve_location(content, ref)
                did = (d or {}).get("id")
                if not did or did in seen or not location_available(content, state, d):
                    continue
                if did == to_id:
                    return True
                seen.add(did)
                nxt.append(did)
        frontier = nxt
    return False


def player_move(content: dict[str, Any], state: dict[str, Any], player_input: str,
                channel: str = "do") -> dict[str, Any] | None:
    """When the player's own words are a clear first-person move to a KNOWN, available
    place (「去工会」「我们回客栈」"head to the guild"), execute it: walks multi-hop through
    unlocked exits, so 想去哪就去哪 — while locked places stay locked. None = not a move
    (questions, orders aimed at others, negations, unknown names) → the director handles it."""
    if channel not in ("do", "say"):
        return None
    text = (player_input or "").strip()
    if not text or len(text) > 80:   # long prose is a scene, not a travel order
        return None
    if any(q in text for q in ("吗", "要不要", "敢不敢", "好不好", "？", "?")):
        return None                   # questions/invitations are for the cast to answer
    if any(n in text for n in _MOVE_NEG):
        return None
    if _MOVE_OTHER_RE.search(text):
        return None                   # sending someone ELSE somewhere
    cands = [m.strip(" 的了吧啊呀去看一趟") for m in _MOVE_DEST_ZH.findall(text)]
    cands += [m.strip() for m in _MOVE_DEST_EN.findall(text)]
    cur = current_location(content, state)
    for ref in cands:
        if not ref:
            continue
        dest = resolve_location(content, ref)
        if not dest or not dest.get("id") or dest.get("id") == (cur or {}).get("id"):
            continue
        if not location_available(content, state, dest):
            continue
        if not _route_exists(content, state, (cur or {}).get("id"), dest["id"]):
            continue
        return commit_move(content, state, dest)
    # 🚪 「离开/出去」names no place — unambiguous only when there is exactly ONE way out
    if _LEAVE_RE.match(text):
        outs = []
        for ref in (cur or {}).get("exits") or []:
            d = resolve_location(content, ref)
            if d and d.get("id") and d["id"] != (cur or {}).get("id") \
                    and location_available(content, state, d):
                outs.append(d)
        if len(outs) == 1:
            return commit_move(content, state, outs[0])
    return None


def player_move_emergent(content: dict[str, Any], state: dict[str, Any], player_input: str,
                         channel: str = "do") -> str | None:
    """SANDBOX: the player names a destination that is NOT on the map (「去后台」 with no
    后台 anywhere). Returns that name so the turn can surface a generate-and-go confirm
    chip — the same gated door the cast's invitations use. None everywhere else."""
    if not sandbox_on(content) or channel not in ("do", "say"):
        return None
    text = (player_input or "").strip()
    if not text or len(text) > 80:
        return None
    if any(q in text for q in ("吗", "要不要", "敢不敢", "好不好", "？", "?")):
        return None
    if any(n in text for n in _MOVE_NEG) or _MOVE_OTHER_RE.search(text):
        return None
    cands = [m.strip(" 的了吧啊呀去看一趟") for m in _MOVE_DEST_ZH.findall(text)]
    cands += [m.strip() for m in _MOVE_DEST_EN.findall(text)]
    names = [c.get("name") for c in _characters(content) if c.get("name")]
    for ref in cands:
        cap = 12 if _CJK_ANY.search(ref or "") else 40   # 🌐 EN 多词名放行到 40
        if not ref or len(ref) < 2 or len(ref) > cap or ref in _DEICTIC:
            continue
        if ref[0] in "找见寻接等约":
            continue                      # 「去找X」「去见X」 are seeks, not places
        if not _placey(ref):
            continue                      # 🗺 地名准入门: 不像地方的碎片不许铸造去处
        if resolve_location(content, ref):
            continue                      # known place → player_move's business, not ours
        if any(n == ref or n in ref for n in names):
            continue                      # names a person, not a place
        return ref
    return None


# ═══════════════════ ⚡ 修为数值账本 (story-defined progression ladder) ═══════════════════
# The STORY defines the ladder (sandbox.progression = {name, ranks:[...]}); the engine
# owns the numbers. Design after 一念逍遥/鬼谷八荒 research: visible progress, breakthrough
# as a RISKY ritual, diminishing returns on grinding, offline trickle, 境界碾压 as law.

_TRAIN_RE = re.compile(r"修炼|修行|打坐|苦修|练功|冥想|吐纳|炼化|闭关|参悟|温养|服用|吞服|服下")
_BREAK_RE = re.compile(r"突破|冲击(境界|瓶颈|下一)|渡劫|历劫")

# 小境界: every major realm has these four sub-stages — the frequent small wins between
# the rare, scary major crossings (深化 mechanics after 鬼谷八荒/一念逍遥).
_STAGES = ["初期", "中期", "后期", "圆满"]
# 资质 (aptitude): rolled ONCE at first cultivation — run-to-run identity + speed gate.
# (d20 threshold, name, training multiplier)
_APTS = [(20, "天纵之资", 1.8), (18, "上上之资", 1.5), (14, "上乘之资", 1.3),
         (4, "中平之资", 1.0), (0, "驽钝之资", 0.8)]
# resources the model may have written into the pocket — consuming one supercharges a
# training turn (丹药/灵石/异火 economy hooked at last).
_RESOURCE_RE = re.compile(r"丹|药|灵石|晶石|魔核|精元|异火|灵液|符|玉髓")
# a place whose fixtures breathe spirit-energy trickles extra (洞天福地).
_SPIRIT_PLACE_RE = re.compile(r"灵气|福地|聚灵|灵脉|洞天|温养|药园|灵泉")


def cult_cfg(content: dict[str, Any]) -> dict[str, Any] | None:
    sb = (content.get("story") or {}).get("sandbox")
    pg = (sb or {}).get("progression") if isinstance(sb, dict) else None
    if isinstance(pg, dict) and pg.get("ranks") and pg.get("name"):
        return pg
    return None


def _cult(state: dict[str, Any]) -> dict[str, Any]:
    c = state.get("cult")
    if not isinstance(c, dict):
        c = {"rank": 0, "stage": 0, "prog": 0, "streak": 0, "apt": None}
        state["cult"] = c
    c.setdefault("stage", 0)
    c.setdefault("apt", None)
    return c


def _apt_of(c: dict[str, Any]) -> tuple[str, float]:
    a = c.get("apt")
    for _thr, name, mult in _APTS:
        if a == name:
            return name, mult
    return "中平之资", 1.0


def cult_power(content: dict[str, Any], state: dict[str, Any]) -> int:
    """⚔ 战力: one integer the whole engine can compare. Grows ~exponentially per major
    realm so 境界碾压 is real — a 斗皇 dwarfs a 斗者 numerically, not just in prose."""
    cfg = cult_cfg(content)
    if not cfg:
        return 0
    c = _cult(state)
    ri = min(int(c.get("rank") or 0), len(cfg["ranks"]) - 1)
    _n, mult = _apt_of(c)
    base = int((10 * (1.9 ** ri)) * (1 + int(c.get("stage") or 0) * 0.22)
               + int(c.get("prog") or 0) * 0.1)
    return max(1, int(base * (0.9 + mult * 0.15)))


def cult_tier(state: dict[str, Any]) -> int:
    """A small ordinal (major*4 + stage) for cheap relative-strength math."""
    c = _cult(state)
    return int(c.get("rank") or 0) * 4 + int(c.get("stage") or 0)


# classes where raw cultivation actually helps the roll (境界碾压 at the dice); social/
# fiddly skills don't scale with realm.
_CULT_PHYS = {"强攻", "腾跃", "追逃", "破闯", "豪赌", "潜行", "威慑"}


def cult_action_mod(content: dict[str, Any], state: dict[str, Any], cls: str) -> int:
    """DC delta from the player's cultivation on a classified physical feat: the higher
    your realm, the more trivial mortal-scale danger becomes. Capped so it never fully
    removes the dice; 0 for social/technical classes and non-cultivation worlds."""
    if not cult_cfg(content) or cls not in _CULT_PHYS:
        return 0
    return -min(8, cult_tier(state) // 2)


def cult_view(content: dict[str, Any], state: dict[str, Any]) -> dict[str, Any] | None:
    cfg = cult_cfg(content)
    if not cfg:
        return None
    c = _cult(state)
    ranks = cfg["ranks"]
    ri = min(int(c.get("rank") or 0), len(ranks) - 1)
    stage = int(c.get("stage") or 0)
    at_summit = ri >= len(ranks) - 1 and stage >= len(_STAGES) - 1
    apt_name, _m = _apt_of(c)
    return {"name": cfg["name"], "rank": ranks[ri], "rank_index": ri,
            "stage": _STAGES[min(stage, len(_STAGES) - 1)], "stage_index": stage,
            "prog": int(c.get("prog") or 0), "cap": at_summit,
            "power": cult_power(content, state),
            "apt": apt_name if c.get("apt") else None,
            "ready": int(c.get("prog") or 0) >= 100 and not at_summit}


def _roll_aptitude(state: dict[str, Any]) -> str | None:
    """First cultivation rolls the character's lifelong 资质 — reported once."""
    c = _cult(state)
    if c.get("apt"):
        return None
    r = random.randint(1, 20)
    for thr, name, _m in _APTS:
        if r >= thr:
            c["apt"] = name
            _audit(state, "cult.aptitude", True, name)
            return name
    return None


def player_train(content: dict[str, Any], state: dict[str, Any], player_input: str,
                 channel: str = "do") -> dict[str, Any] | None:
    """修炼孪生: gains progress within the current 小境界 NOW. Gain scales with 资质,
    consumed resources (丹药/灵石), and spirit-rich locations; diminishing returns on
    back-to-back grinding (streak). Story-agnostic — reads only generic signals."""
    cfg = cult_cfg(content)
    if not cfg or channel not in ("do", "say"):
        return None
    text = (player_input or "").strip()
    if not text or len(text) > 40 or not _TRAIN_RE.search(text):
        return None
    if any(w in text for w in ("别", "不", "陪", "教", "你去")):
        return None
    c = _cult(state)
    apt_new = _roll_aptitude(state)
    if c["prog"] >= 100:
        return {"full": True, "apt_new": apt_new}
    _apt_name, mult = _apt_of(c)
    roll = random.randint(1, 20)
    base = (8 + roll // 2)
    bonus, why = 0, []
    # 🔴 consume a resource named in the line for a real jolt
    consumed = None
    for it in list(state.get("inventory") or []):
        nm = (it.get("name") or "").strip()
        if nm and nm in text and _RESOURCE_RE.search(nm):
            consumed = _inv_remove(state, nm)
            bonus += 12
            why.append(f"服{nm}")
            break
    if _SPIRIT_PLACE_RE.search((current_location(content, state) or {}).get("detail", "")):
        bonus += 4
        why.append("灵气充裕")
    gain = max(2, (int(base * mult) >> min(int(c.get("streak") or 0), 3)) + bonus)
    c["prog"] = min(100, int(c["prog"]) + gain)
    c["streak"] = int(c.get("streak") or 0) + 1
    _audit(state, "cult.train", True, f"+{gain}%→{c['prog']}%" + (f"（{'/'.join(why)}）" if why else ""))
    return {"gain": gain, "prog": c["prog"], "roll": roll, "full": c["prog"] >= 100,
            "apt_new": apt_new, "consumed": (consumed or {}).get("name") if consumed else None,
            "why": why}


def player_breakthrough(content: dict[str, Any], state: dict[str, Any], player_input: str,
                        channel: str = "do") -> dict[str, Any] | None:
    """突破孪生: a full bottleneck breaks. A SUB-stage step (初期→中期…) is the small,
    forgiving win (d20≥6). Crossing a 圆满 into the next major realm is the 天劫/心魔 —
    harder (≥12), a bigger fall on failure, but 顿悟 (crit) possible. 境界碾压 numbers
    update instantly via power."""
    cfg = cult_cfg(content)
    if not cfg or channel not in ("do", "say"):
        return None
    text = (player_input or "").strip()
    if not text or len(text) > 30 or not _BREAK_RE.search(text):
        return None
    c = _cult(state)
    ranks = cfg["ranks"]
    ri, stage = int(c.get("rank") or 0), int(c.get("stage") or 0)
    if ri >= len(ranks) - 1 and stage >= len(_STAGES) - 1:
        return {"capped": True}
    if int(c.get("prog") or 0) < 100:
        return {"not_ready": True, "prog": int(c.get("prog") or 0)}
    major = stage >= len(_STAGES) - 1          # 圆满 → cross into the next major realm
    roll = random.randint(1, 20)
    need = 12 if major else 6                   # the 天劫 is the real gate
    crit = roll >= (19 if major else 17)
    if roll >= need:
        if major:
            c["rank"], c["stage"] = ri + 1, 0
        else:
            c["stage"] = stage + 1
        c["prog"] = 25 if crit else 0
        c["streak"] = 0
        v = cult_view(content, state)
        _audit(state, "cult.breakthrough", True,
               f"{v['rank']}·{v['stage']}" + ("（天劫）" if major else ""))
        return {"success": True, "crit": crit, "roll": roll, "major": major,
                "rank_name": v["rank"], "stage_name": v["stage"], "power": v["power"]}
    # failure: a major 天劫 backlash bites harder than a stalled sub-step
    c["prog"] = max(40 if major else 60, int(c["prog"]) - (55 if major else 30))
    harm = major and roll <= 3                  # a botched 天劫 can wound the body
    if harm and sandbox_on(content):
        state["player_hp"] = "hurt"
    _audit(state, "cult.breakthrough", False, f"roll{roll}", "天劫反噬" if major else "冲击受挫")
    return {"success": False, "roll": roll, "major": major, "prog": c["prog"], "harm": harm}


def cult_absorb(content: dict[str, Any], state: dict[str, Any], outcome: str) -> str:
    """⚡ 剧情炼化结算: the player absorbed/refined something IN THE FICTION and the dice
    spoke. Success feeds the ladder (aptitude-scaled), a crit doubles, a critical botch
    backfires into the meridians (进度倒扣). Returns the engine beat text ("" = nothing)."""
    cfg = cult_cfg(content)
    if not cfg or not outcome:
        return ""
    c = _cult(state)
    _roll_aptitude(state)
    _n, mult = _apt_of(c)
    v0 = cult_view(content, state)
    if outcome == "crit_fail":
        loss = 8
        c["prog"] = max(0, int(c.get("prog") or 0) - loss)
        _audit(state, "cult.absorb", False, f"-{loss}%", "炼化反噬")
        return _t(content,
                  f"（那股力量在你经脉里暴走反噬！{v0['name']}进度倒退{loss}%，你强行压下翻涌的气血。）",
                  f"(The energy turns on you inside your meridians — {v0['name']} falls back {loss}%.)")
    if outcome not in ("success", "crit_success", "mixed"):
        return ""
    if int(c.get("prog") or 0) >= 100:
        return _t(content, "（那股力量涌入体内，却被已然充盈的瓶颈挡在门外：先突破，再谈吞吸。）",
                  "(The energy pours in but the full bottleneck turns it away — break through first.)")
    # 险成 absorbs too, just rougher: half the take (the prose narrates the cost)
    gain = int((22 if outcome == "crit_success" else 5 if outcome == "mixed" else 10) * mult)
    c["prog"] = min(100, int(c.get("prog") or 0) + gain)
    c["streak"] = 0
    v = cult_view(content, state)
    _audit(state, "cult.absorb", True, f"+{gain}%→{c['prog']}%")
    return _t(content,
              f"（你成功将那股力量炼入体内！{v['name']}进度大涨{gain}%，"
              f"当前【{v['rank']}·{v['stage']} {c['prog']}%】。"
              + ("本境瓶颈已满，可尝试突破。）" if c["prog"] >= 100 else "）"),
              f"(You refine the power into yourself — {v['name']} surges {gain}%, now "
              f"[{v['rank']} {v['stage']} · {c['prog']}%].)")


def cult_declared_gain(content: dict[str, Any], state: dict[str, Any], grade: str) -> str:
    """⚡ 导演申报的修为进益 (被传功/丹浴/顿悟 — gains no dice roll saw). Clamped small:
    小/中/大 → +4/+10/+18, aptitude-scaled, capped at the bottleneck."""
    cfg = cult_cfg(content)
    g = {"小": 4, "中": 10, "大": 18}.get((grade or "").strip())
    if not cfg or not g:
        return ""
    c = _cult(state)
    if int(c.get("prog") or 0) >= 100:
        return ""
    _roll_aptitude(state)
    _n, mult = _apt_of(c)
    gain = max(2, int(g * mult))
    c["prog"] = min(100, int(c.get("prog") or 0) + gain)
    v = cult_view(content, state)
    _audit(state, "cult.gain", True, f"+{gain}%→{c['prog']}%（申报）")
    return _t(content,
              f"（一番机缘，你的{v['name']}进度悄然上涨{gain}%，当前【{v['rank']}·{v['stage']} {c['prog']}%】。）",
              f"(A stroke of fortune — {v['name']} rises {gain}%, now [{v['rank']} {v['stage']} · {c['prog']}%].)")


def ensure_progression(content: dict[str, Any], llm=None) -> bool:
    """🌱 开局立法: a sandbox with NO authored ladder gets one GENERATED to fit its
    worldview at run creation (每个世界都该有自己的升级之路). Mutates content (caller
    persists the pinned copy). Returns True when a ladder was added."""
    if not sandbox_on(content) or cult_cfg(content):
        return False
    story = content.get("story") or {}
    world = (story.get("world_facts") or story.get("world_long") or "").strip()
    if not world:
        return False
    out = (lang_llm(llm or get_llm(), content).generate(
        {"gen_progression": True, "world": world[:800],
         "title": story.get("title") or ""}) or {})
    name = str(out.get("name") or "").strip()[:8]
    ranks = [r[:8] for r in as_str_list(out.get("ranks"))]
    if not name or not (4 <= len(ranks) <= 12):
        return False
    sb = story.get("sandbox")
    if not isinstance(sb, dict):
        return False
    sb["progression"] = {"name": name, "ranks": ranks}
    return True


def cult_offline_gain(content: dict[str, Any], state: dict[str, Any],
                      away_hours: float) -> int:
    """一念逍遥 lesson: the numbers grow a little while you're away (温养), scaled by 资质,
    capped and never past the bottleneck — returning always feels like motion."""
    cfg = cult_cfg(content)
    if not cfg or away_hours < 3:
        return 0
    c = _cult(state)
    if not c.get("apt") or c["prog"] >= 100:
        return 0
    if int(c.get("rank") or 0) >= len(cfg["ranks"]) - 1 and int(c.get("stage") or 0) >= len(_STAGES) - 1:
        return 0
    _n, mult = _apt_of(c)
    gain = min(18, int((away_hours // 2) * mult))
    if gain <= 0:
        return 0
    c["prog"] = min(100, int(c["prog"]) + gain)
    c["streak"] = 0
    _audit(state, "cult.offline", True, f"+{gain}%→{c['prog']}%")
    return gain


def cult_anchor(content: dict[str, Any], state: dict[str, Any]) -> str:
    """One depth-0 line: rank + sub-stage + 战力 are LAW — the world treats you by them."""
    v = cult_view(content, state)
    if not v:
        return ""
    line = f"你的{v['name']}修为：{v['rank']}·{v['stage']}（战力{v['power']}，本境瓶颈{v['prog']}%）。"
    if v["ready"]:
        nxt = "跨越大境界（有天劫/心魔之险）" if v["stage_index"] >= len(_STAGES) - 1 else "突破小境界"
        line += f"瓶颈已满：可尝试{nxt}。"
    line += ("境界即铁律：战力差一大截就是碾压性的差距，跨大境界如隔天堑；"
             "在场者按你的境界与战力对待你，你的表现不能超出这个境界该有的水平（金手指除外）。")
    return line


# 🎬 关键帧落账: the primary declares which OTHER present bodies visibly changed this
# turn; the engine validates each name against the live roster and books the frame.
# Everyone undeclared is carried forward unchanged — deterministic tweening, like anime.
def book_scene_frame(content: dict[str, Any], state: dict[str, Any],
                     directed: dict[str, Any], sp_id: str | None) -> int:
    frames = directed.get("scene_frame") or []
    if not frames:
        return 0
    here = {(c.get("name") or ""): c.get("id") for c in scene_characters(content, state)}
    pcid = state.get("player_character_id")
    booked = 0
    for f in frames[:4]:
        nm, fr = (f or {}).get("name") or "", ((f or {}).get("frame") or "").strip()[:16]
        cid = here.get(nm)
        if not cid or not fr or cid == sp_id or cid == pcid:
            if nm:
                _audit(state, "frame.set", False, nm, "不在场或不可代报")
            continue
        _sim(state, cid)["pos"] = {"text": fr, "at": state.get("location_id")}
        _audit(state, "frame.set", True, f"{nm}:{fr}")
        booked += 1
    return booked


def _track_prep(content: dict[str, Any], state: dict[str, Any],
                persona: dict[str, Any], all_beats: list[dict[str, Any]]):
    """场记备料 (主线程): 提示词素材 + 合账上下文快照。无戏可记返回 None。"""
    txt = " ".join((b.get("text") or "") for b in all_beats if b.get("text")).strip()[:1500]
    if not txt:
        return None
    here = scene_characters(content, state)
    lid = state.get("location_id")
    pcid = state.get("player_character_id")
    sim = state.get("char_sim", {}) or {}
    prev = []
    for c in here:
        if not c.get("name") or c.get("id") == pcid:
            continue
        e = (sim.get(c["id"], {}) or {}).get("pos")
        line = ""
        if isinstance(e, dict) and e.get("at") == lid:
            line = (e.get("text") or "") + (f"·着{e['wear']}" if e.get("wear") else "")
        prev.append({"name": c["name"], "prev": line})
    pc = _char_by_id(content, pcid) if pcid else None
    pname = (pc or {}).get("name") or (persona or {}).get("name") or "玩家"
    pp = state.get("player_pos") if isinstance(state.get("player_pos"), dict) else {}
    pprev = ((pp.get("text") or "") + (f"·着{pp['wear']}" if pp.get("wear") else "")) if pp.get("at") == lid else ""
    _tp = {"track_scene": True, "beats": txt, "present": prev,
           "player": {"name": pname, "prev": pprev},
           "place": (current_location(content, state) or {}).get("name", ""),
           "mature": bool(state.get("mature"))}
    if lang_of(content) == "en":      # the language stamp rides EN runs only (convention)
        _tp["language"] = "en"
    ctx = {"lid": lid,
           "name2id": {c.get("name"): c.get("id") for c in here if c.get("id") != pcid}}
    return _tp, ctx


def track_scene_frames(content: dict[str, Any], state: dict[str, Any],
                       persona: dict[str, Any], all_beats: list[dict[str, Any]],
                       llm) -> None:
    """🎥 场记 (turn-end tracker pass): one small extraction call reads THIS turn's prose
    and re-derives every present body's frame (pos·doing·wear). The ledger follows the
    text — declarations and twins remain fast-path hints, the tracker is the authority.
    Hard contradictions against last frame land in state.track_note (next turn's anchor
    tells the model the ledger wins) + the audit sheet. Fail-open: any error keeps the
    previous frames. (同步版: 测试与 run_turn 包装器用; 回合流水线走 track_frames_async)"""
    prep = _track_prep(content, state, persona, all_beats)
    if not prep:
        return
    _tp, ctx = prep
    out = llm.generate(_tp) or {}
    _track_apply(state, out, ctx)


def _track_apply(state: dict[str, Any], out: dict[str, Any], ctx: dict[str, Any]) -> None:
    """场记合账 (主线程): 帧上台账。帧钉着记账时的地点 id — 玩家换过场自动作废
    (char_position 只认 at==当前地点的帧), 迟一回合入账依旧安全。"""
    lid = ctx.get("lid")
    name2id = ctx.get("name2id") or {}
    sim = state.get("char_sim", {}) or {}
    pp = state.get("player_pos") if isinstance(state.get("player_pos"), dict) else {}

    def _entry(f, old):
        pos = str((f or {}).get("pos") or "").strip()[:14]
        doing = str((f or {}).get("doing") or "").strip()[:10]
        wear = str((f or {}).get("wear") or "").strip()[:10]
        text = (pos + ("·" + doing if doing and doing not in pos else "")).strip("·")[:22]
        if not text and not wear:
            return None
        e = {"text": text or ((old or {}).get("text") or ""), "at": lid}
        w = wear or ((old or {}).get("wear") if (old or {}).get("at") == lid else "")
        if w:
            e["wear"] = w
        return e if e["text"] or e.get("wear") else None

    booked = 0
    for f in (out.get("frames") or [])[:8]:
        nm = str((f or {}).get("name") or "").strip()
        cid = name2id.get(nm)
        if not cid:
            if nm:
                _audit(state, "track.update", False, nm, "不在名单")
            continue
        e = _entry(f, (sim.get(cid, {}) or {}).get("pos"))
        if e:
            _sim(state, cid)["pos"] = e
            booked += 1
    pe = _entry(out.get("player") or {}, pp)
    if pe:
        state["player_pos"] = pe
        booked += 1
    if booked:
        _audit(state, "track.update", True, f"{booked}帧")
    cons = [c[:40] for c in as_str_list(out.get("contradictions"))][:2]
    if cons:
        state["track_note"] = cons[0]
        _audit(state, "track.conflict", False, cons[0])
    # 📈 欠账追讨: a thread teased without CONCRETE progress builds debt; at 2+ stalled
    # turns the next anchor demands payoff (爆发/揭晓/后果), not more atmosphere.
    prog = out.get("progressed")
    prog = (str(prog).strip().lower() != "false") if prog is not None else True
    hang = str(out.get("hanging") or "").strip()[:16]
    st_prev = state.get("stall") if isinstance(state.get("stall"), dict) else None
    if not prog:
        state["stall"] = {"n": int((st_prev or {}).get("n") or 0) + 1,
                          "thread": hang or (st_prev or {}).get("thread") or ""}
        _audit(state, "stall", False, f"{state['stall']['n']}轮:{state['stall']['thread']}")
    else:
        state["stall"] = None
    try:
        from .. import metrics as _metrics
        _metrics.log("track", booked=booked, conflict=len(cons))
    except Exception:
        pass


_TRACK_PENDING: dict = {}   # 一次性票据 → {"out": 模型产出, "ctx": 记账上下文}
_TRACK_CAP = 30


def track_frames_async(content: dict[str, Any], state: dict[str, Any],
                       persona: dict[str, Any], all_beats: list[dict[str, Any]],
                       llm) -> None:
    """⚡ 场记出关键路径 (4秒军令): 注释一直说「玩家不用等」, 但收尾事件与落库
    都排在生成器耗尽之后 — 场记那 ~1.5s 实际一直挡着输入框解锁。同折叠家法:
    备料主线程 / 模型后台 / 下一回合 apply_pending_track 合账。帧钉记账时地点,
    换场自动作废; 丢单 = 保留旧帧 (fail-open 语义不变)。"""
    prep = _track_prep(content, state, persona, all_beats)
    if not prep:
        return
    payload, ctx = prep
    import threading
    import uuid
    tok = uuid.uuid4().hex[:12]
    state["track_pending"] = tok

    def _work():
        try:
            out = llm.generate(payload) or {}
        except Exception:
            out = {}
        while len(_TRACK_PENDING) >= _TRACK_CAP:
            _TRACK_PENDING.pop(next(iter(_TRACK_PENDING)), None)
        _TRACK_PENDING[tok] = {"out": out, "ctx": ctx}

    threading.Thread(target=_work, daemon=True).start()


def apply_pending_track(state: dict[str, Any]) -> bool:
    """回合开演前把后台记好的场记帧合进账 (主线程)。没记完票不烧 (折叠同款)。"""
    tok = state.get("track_pending")
    if not tok:
        return False
    got = _TRACK_PENDING.pop(tok, None)
    if got is None:
        return False               # 后台还没记完: 票留着, 下回合再收
    state.pop("track_pending", None)
    if got.get("out"):
        try:
            _track_apply(state, got["out"], got.get("ctx") or {})
        except Exception:
            pass
    return True


def unframed_names(content: dict[str, Any], state: dict[str, Any],
                   exclude_id: str | None = None) -> list[str]:
    """Present characters with NO fresh frame on the sheet (excluding the player and the
    current speaker). These are the bodies the next declaration MUST seed — an animation
    needs its 原画 before tweening means anything."""
    lid = state.get("location_id")
    pcid = state.get("player_character_id")
    out = []
    for c in scene_characters(content, state):
        cid = c.get("id")
        if not c.get("name") or cid in (pcid, exclude_id):
            continue
        pos = (state.get("char_sim", {}) or {}).get(cid, {}).get("pos")
        if not (isinstance(pos, dict) and pos.get("at") == lid and (pos.get("text") or "").strip()):
            out.append(c["name"])
    return out[:4]


# 🎙 旁白人称铁律: narration speaks to the player as 你; a description beat overrun with
# 我 and empty of 你 is a hijacked narrator (observed in prod) — regeneratable violation.
_POV_CORRECTION = ("上一版旁白的人称错了：旁白必须自始至终用第二人称「你」称呼玩家本人，"
                   "在场的其他所有角色（包括原著里的知名主角）一律用名字称呼，绝不能反过来"
                   "把玩家写成第三人称（用玩家角色的名字或「他/她」指玩家），更不能把「你」安到"
                   "别的角色身上，也不能把旁白写成某个角色的第一人称独白。重写这一轮。")


# 写走必记走的架构版 (Yi: 这个铁律是走的架构吗): departure prose per present name
_EXIT_TAIL_RE = (r"[^。！？\n]{0,12}?(?:离开|走了出去|走出了|迈出|迈下台阶|退了出去|出了门"
                 r"|拂袖而去|大步离去|走远|转身走了|头也不回地走|离场而去)")
# 🚪 台词里的第一人称告别 (Yi: 角色「说」自己要走却没走 — 之前只读旁白不读台词)
_SELF_EXIT_RE = re.compile(
    r"我(?:先|得|这就|还是|要|该|去)?\s*(?:走一步|走了|走|离开|回去了?|撤了?|闪了?|告辞|失陪|先撤)"
    r"(?=[。！？，、\s」”』’]|$)|失陪了|告辞了|我先走|我得走|我这就走")
_EXIT_NEG_RE = re.compile(r"如果|要是|假如|万一|别走|不走|不能走|走不了|想走吗|要不要走|走神|走运|走心")
# 🤝 邀请不是离场 (实弹: 「跟我走」被判离场钉成 AWAY)。审查教训: 不能整句否决 ——
# 「改天带你去看看，我先走了」邀请与真告别同句, 整句放行会反向复刻原 bug。
# 做法 = 先把邀请短语从台词里【剥掉】再判离场, 两者互不遮蔽。
_INVITE_RE = re.compile(r"跟我走|跟我来|随我来|随我走|带你去|带你走|我们走|咱们走|一起走|一块走|同去")
# 旁白同行白名单: 只有明确「带着玩家」的构式才豁免; 「丢下你/朝你摆手后离开」是真离场
_LEAD_PLAYER_RE = re.compile(r"[拉牵带领拽挽扶搂背抱]着你|带你|领你|招呼你")


def _settle_prose_exits(content: dict[str, Any], state: dict[str, Any],
                        d_beats: list[dict[str, Any]], pcid: str | None) -> list[str]:
    """Deterministic backstop for npc_moves: a PRESENT character walked out (in NARRATION)
    or SAID they're leaving (in their own DIALOGUE) books the exit in the ledger even when
    the model forgot to file it — prose and ledger may never part ways. Unknown destination
    → routed HOME (a real place, per Yi「到另一个场景就好」); no home → AWAY. Returns names."""
    narr = "\n".join(b.get("text") or "" for b in d_beats or [] if b.get("type") != "dialogue")
    # 谁在自己那句台词里说了要走 (排掉条件句/否定句: 如果我走了 / 别走 / 走神)
    # 邀请短语先剥掉再判: 「跟我走」不算走, 但「带你去看看，我先走了」里的真告别不被邀请遮蔽
    said_bye: set[str] = set()
    for b in d_beats or []:
        if b.get("type") == "dialogue":
            t = _INVITE_RE.sub("", b.get("text") or "")
            sp = (b.get("speaker_name") or "").strip()
            if sp and _SELF_EXIT_RE.search(t) and not _EXIT_NEG_RE.search(t):
                said_bye.add(sp)
    if not narr and not said_bye:
        return []
    cur = state.get("location_id")
    loc_ids = {l.get("id") for l in _locations(content)}
    outed: list[str] = []
    for c in list(scene_characters(content, state)):
        cid, nm = c.get("id"), (c.get("name") or "").strip()
        if not cid or not nm or cid == pcid:
            continue
        _m = narr and re.search(re.escape(nm) + _EXIT_TAIL_RE, narr)
        # 旁白里【带着玩家】一起走的不算离场 (「他拉着你走了出去」= 同行)。审查教训:
        # 只认明确带人构式白名单 — 「丢下你走了出去」「朝你摆了摆手，转身走了」是真离场
        leaving = bool(_m and not _LEAD_PLAYER_RE.search(_m.group(0))) or nm in said_bye
        if not leaving:
            continue
        # 去处不明 → 回家(真地点); 没家、家不在册、或家就在此地 → AWAY
        home = str(c.get("home_location_id") or "").strip()
        dest = home if (home and home != cur and home in loc_ids) else AWAY
        pins = dict(state.get("char_pins") or {})
        pins[cid] = dest
        state["char_pins"] = pins
        if cid in (state.get("following") or []):
            state["following"] = [f for f in state["following"] if f != cid]
        _audit(state, "npc.exit", True, nm, "台词/散文离场→" + ("回家" if dest != AWAY else "离开"))
        outed.append(nm)
    return outed


def _heal_away_pins(content: dict[str, Any], state: dict[str, Any],
                    all_beats: list[dict[str, Any]],
                    away0: set[str] | None = None) -> list[str]:
    """🩹 AWAY 钉子自愈: 台账说人「下落不明」(__away__ 钉永不被 _drop_pins_on_leave 释放),
    正文却让 TA 开口说话 — 以台上证据为准, 解钉回玩家身边。(实弹: 「跟我走」误判离场后
    人物从此消失, 文与账每拍打架。) 三道闸: ①只认台词证据, 不认旁白提及; ②只治【回合初
    就钉着】的历史粘钉 (away0), 本回合刚离场者的告别台词不算证据; ③证据台词自己就是
    告别语(「走了，各位保重」)的不算 — 那是在演他离开, 不是在演他在场。
    已知残余: 幻觉台词可复活真离场者 — 按场记教义「文本即权威」有意接受 (模型坚持演
    TA 在场, 账本就该跟文走; 反向硬拦会复刻钉死不放的原 bug)。"""
    pins = state.get("char_pins") or {}
    cur = state.get("location_id")
    if AWAY not in pins.values() or not cur:
        return []
    speakers: set[str] = set()
    for b in all_beats or []:
        if b.get("type") == "dialogue":
            sp = (b.get("speaker_name") or "").strip()
            t = _INVITE_RE.sub("", b.get("text") or "")
            if sp and not _SELF_EXIT_RE.search(t):
                speakers.add(sp)
    if not speakers:
        return []
    pcid = state.get("player_character_id")
    healed: list[str] = []
    for c in _characters(content):
        cid, nm = c.get("id"), (c.get("name") or "").strip()
        if cid and nm and cid != pcid and pins.get(cid) == AWAY and nm in speakers \
                and (away0 is None or cid in away0):
            pins = dict(pins)
            pins[cid] = cur
            state["char_pins"] = pins
            _audit(state, "npc.heal", True, nm, "台上开口→解除下落不明")
            healed.append(nm)
    return healed


def _addressed_char(content: dict[str, Any], state: dict[str, Any],
                    d_beats: list[dict[str, Any]], sp_id: str | None,
                    pcid: str | None) -> dict[str, Any] | None:
    """Vocative detection: a dialogue line opening with a PRESENT character's name (or
    2-char short name)＋呼语标点 addresses them — they should get to answer this turn."""
    here = [c for c in scene_characters(content, state)
            if c.get("id") not in (sp_id, pcid) and (c.get("name") or "").strip()]
    for b in d_beats or []:
        if b.get("type") != "dialogue":
            continue
        head = (b.get("text") or "").strip()[:12]
        for c in here:
            nm = c["name"].strip()
            for cand in {nm, nm[-2:] if len(nm) > 2 else nm}:
                if cand and head.startswith(cand) \
                        and head[len(cand):len(cand) + 1] in ("，", ",", "：", ":", "、", " ", "！", "!"):
                    return c
    return None


def _pov_break(directed: dict[str, Any], player_name: str = "") -> bool:
    pn = (player_name or "").strip()
    for b in directed.get("beats", []) or []:
        if b.get("type") == "dialogue":
            continue
        t = b.get("text") or ""
        # 我-hijack: narration slipped into a character's first person. Two spans may
        # legitimately say 我 — quoted speech (「…」) and 你-anchored interiority
        # (「你心里只有一个念头：我不能输」) — strip both, then judge what's left.
        bare = re.sub(r"「[^」]*」", "", t)
        bare = re.sub(r"：[^。！？!?]*", "", bare)
        if len(re.findall(r"我", bare)) >= 2:
            return True
        # 3rd-person-player: the player is 你, ALWAYS — their name appearing in narration
        # at all is the referent inversion (worst form: 「你」 pinned on an NPC while the
        # player walks by in third person — the field case had BOTH in one beat)
        if pn and pn in t:
            return True
    return False


# 🧍 姿位: the player states their own body plainly (坐下/躺到床上/靠在墙边) → engine
# law, not model memory. Entries carry the location id, so a move auto-stales them.
_POSE_RE = re.compile(
    r"(坐到|坐在|坐回|坐下|躺到|躺在|躺回|躺下|跪下|跪在|趴到|趴在|趴下|蹲下|蹲在"
    r"|靠在|靠着|倚在|倚着|站起来|站起身|站到|站在|起身)"
    r"([^，。！？!?,.;；、\s]{0,10})")


def player_pose(state: dict[str, Any], player_input: str, channel: str = "do") -> str | None:
    """Deterministic pose twin: an unambiguous first-person posture statement books the
    player's 姿位 directly. None = not a pose (questions, negations, orders at others)."""
    if channel not in ("do", "say"):
        return None
    text = (player_input or "").strip()
    if not text or len(text) > 40:
        return None
    if any(q in text for q in ("吗", "要不要", "？", "?")):
        return None
    m = _POSE_RE.search(text)
    if not m:
        return None
    lead = text[max(0, m.start() - 2):m.start()]
    if any(w in lead for w in ("你", "他", "她", "让", "请", "别", "不", "TA")):
        return None                         # someone else's body, or a negation
    pose = (m.group(1) + m.group(2)).strip()[:14]
    state["player_pos"] = {"text": pose, "at": state.get("location_id")}
    return pose


# 🔎 找人: 「去找X」 pops a confirmable "TA此刻在Y" prompt — and X WILL be there.
_SEEK_RE_ZH = re.compile(
    r"(?:去找|去见|(?<![寻搜查])找|(?<![意遇碰撞听看再相偏成瞧望瞥])见)"
    r"\s*([^，。！？!?,.、\s]{1,12})")
_SEEK_RE_EN = re.compile(r"\b(?:find|look for|go see|visit)\s+([A-Za-z' ]{2,30})", re.IGNORECASE)


def player_seek(content: dict[str, Any], state: dict[str, Any], player_input: str,
                channel: str = "say") -> dict[str, Any] | None:
    """When the player wants to FIND a known character who isn't in this scene, locate
    them. Returns {"char": c, "loc": loc} when they're somewhere reachable (loc is the
    location dict), {"char": c, "loc": None} when they're AWAY/unreachable this hour,
    None when the input isn't a seek (or the person is already right here)."""
    if channel not in ("do", "say"):
        return None
    text = (player_input or "").strip()
    if not text or len(text) > 60:
        return None
    if any(n in text for n in ("别去", "不去", "不想", "别找", "不找")):
        return None
    toks = [m.strip() for m in _SEEK_RE_ZH.findall(text)]
    toks += [m.strip() for m in _SEEK_RE_EN.findall(text)]
    toks = [t for t in toks if len(t) >= 2]
    if not toks:
        return None
    act = int(state.get("act", 1) or 1)
    pcid = state.get("player_character_id")
    here_ids = {c.get("id") for c in scene_characters(content, state)}
    cur = current_location(content, state)
    for tok in toks:
        for c in present_characters(content, act, _dead_ids(state)):
            nm = (c.get("name") or "").strip()
            if not nm or c.get("id") == pcid or c.get("id") in here_ids:
                continue
            if not (nm == tok or nm in tok or tok in nm):
                continue
            pos = char_position(content, state, c)
            if pos is None:
                return None          # mapless story — everyone is 'here' already
            if pos == AWAY:
                return {"char": c, "loc": None}
            loc = _location_by_id(content, pos)
            if not loc or not location_available(content, state, loc) \
                    or loc.get("id") == (cur or {}).get("id") \
                    or not _route_exists(content, state, (cur or {}).get("id"), loc["id"]):
                return {"char": c, "loc": None}
            return {"char": c, "loc": loc}
    return None


def seek_unknown(content: dict[str, Any], state: dict[str, Any], player_input: str,
                 channel: str = "say") -> str | None:
    """A seek-shaped input whose target matches NO known character or place. The engine
    can't resolve it — but the director must not let the player spin on it turn after
    turn, so the name is surfaced into the prompt (mint/refer in a sandbox, honest deny
    in an authored story). Returns the sought name, or None when this isn't that."""
    if channel not in ("do", "say"):
        return None
    text = (player_input or "").strip()
    if not text or len(text) > 60:
        return None
    if any(n in text for n in ("别去", "不去", "不想", "别找", "不找")):
        return None
    toks = [m.strip() for m in _SEEK_RE_ZH.findall(text)]
    toks += [m.strip() for m in _SEEK_RE_EN.findall(text)]
    toks = [t for t in toks if len(t) >= 2]
    if not toks:
        return None
    act = int(state.get("act", 1) or 1)
    known = [(c.get("name") or "").strip() for c in present_characters(content, act, set())]
    known += [(l.get("name") or "").strip() for l in _locations(content)]
    known = [n for n in known if n]
    for tok in toks:
        if any(n == tok or n in tok or tok in n for n in known):
            return None      # a real someone/somewhere — the resolvers above own it
    return toks[0][:12]


def mint_sought_character(content: dict[str, Any], state: dict[str, Any], name: str,
                          scout: dict[str, Any], llm: LLM | None) -> dict[str, Any] | None:
    """The scout confirmed the sought name belongs in this world — make them REAL, now,
    deterministically: character into the cast, their whereabouts minted as a first-class
    location, ready for the standard seek confirm chip (which pins them there). 文与实
    不分家：账本先动，散文跟上 — the player never again hunts a name for 20 turns.
    Mutates `content` (caller must flag content_mutated). Returns {"char", "loc"}."""
    import uuid as _uuid
    nm = (name or "").strip()[:12]
    if not nm:
        return None
    if not npc_name_ok(nm):
        _audit(state, "seek.scout", False, nm, "名字不像人名，驳回")
        return None
    tun = tuning_for(content)
    gen_now = sum(1 for c in _characters(content) if c.get("generated"))
    if gen_now >= tun["max_new_characters"]:
        _audit(state, "seek.scout", False, nm, "本局涌现人数已到上限")
        return None
    where = (scout.get("where") or "").strip() or _t(content, "附近的去处", "somewhere near")
    if LLM_MAP_WRITES:
        try:
            # move=False: 确认片才移动玩家, 铸造只立档 — 也因此绝不惊动现场的钉子/场账本
            loc = generate_and_move(content, state, where, llm=llm, invent=True, move=False)
        except ValueError:
            loc = None
    else:
        # 🔒 地图锁上时人照样涌现, 只是【不给他新造一块地】: 把他安置在已有地点上。
        # 找人是角色涌现 (吃 max_new_characters 的额度), 不是地图玩法 —— 关地图不该
        # 顺手把它一起关了 (实弹: 头一版直接 return None, 找人系统整个哑了)。
        loc = resolve_location(content, where)
        if loc and not location_available(content, state, loc):
            loc = None
        if loc is None:
            loc = current_location(content, state)
    if loc is None:
        return None
    char = {
        "id": f"gen_{_uuid.uuid4().hex[:8]}",
        "name": nm,
        "role": clip_sentence(scout.get("who") or "", 24).rstrip("。") or "打听来的人物",
        "persona_text": clip_sentence(scout.get("persona") or scout.get("who") or "", 200),
        "voice_print": str(scout.get("voice") or "").strip()[:60],
        "relation_default": "stranger",
        "home_location_id": loc.get("id"),
        "generated": True,
    }
    (content.get("story") or {}).setdefault("characters", []).append(char)
    return {"char": char, "loc": loc}


def free_day_suggestions(content: dict[str, Any], state: dict[str, Any]) -> list[str]:
    """🌅 新的一天的自由活动菜单: 确定性, 从作息+关系温度里长出来 —
    最暖的两个人「此刻在哪、去找TA」+ 一个独处去处。剧情这一刻不抢戏。"""
    dead = _dead_ids(state)
    met = set(state.get("met_ids") or [])
    pcid = state.get("player_character_id")
    cands = [c for c in _characters(content)
             if c.get("id") and c.get("id") in met
             and c.get("id") not in dead and c.get("id") != pcid]

    def _warm(c):
        sc = (state.get("rel") or {}).get(c.get("id")) or {}
        return int(sc.get("closeness", 0) or 0) + int(sc.get("romance", 0) or 0)

    cands.sort(key=_warm, reverse=True)
    out: list[str] = []
    for c in cands[:2]:
        pos = char_position(content, state, c)
        loc = _location_by_id(content, pos) if (pos and pos != AWAY) else None
        where = (loc.get("name") if loc and location_available(content, state, loc)
                 else None)
        out.append(f"去{where}找{c.get('name')}" if where
                   else f"去找{c.get('name')}，看TA今天在忙什么")
    spots = [l for l in _locations(content)
             if l.get("name") and location_available(content, state, l)
             and l.get("id") != state.get("location_id")]
    if spots:
        out.append(f"一个人去{random.choice(spots).get('name')}转转")
    return [dedash(s) for s in out if s][:3]


def echo_line(content: dict[str, Any], state: dict[str, Any], sp_id: str | None) -> str:
    """🌌 跨存档残响 (活世界 P4): 上一段人生里暖过的角色, 新时间线里对玩家有一种
    说不清的既视感 — 一瞬恍惚级别, 绝不解释, 绝不复述前尘 (TA并不真的记得)."""
    if not sp_id or sp_id not in ((state.get("echo") or {}).get("chars") or []):
        return ""
    return _t(content,
              "你对这位玩家有一种说不清的既视感，像在另一段人生里认识过TA。"
              "偶尔（低频）可以流露一瞬恍惚，一句『我们是不是在哪儿见过』的程度，"
              "说不出所以然，也绝不解释。",
              "You feel an inexplicable deja vu about this player, as if you knew them "
              "in another life. Rarely, let a flicker of it slip; never explain it.")


def character_profile(content: dict[str, Any], state: dict[str, Any],
                      char_id: str) -> dict[str, Any] | None:
    """Everything the player may KNOW about one character, gathered for the 档案卡:
    public profile, relationship axes + next tier, their secrets' progress (titles only,
    and only once ≥1 layer is open), where they are, the shared 大事记 timeline, and the
    bio layers closeness has unlocked. Locked content never leaves the server."""
    c = _char_by_id(content, char_id)
    if not c:
        return None
    act = int(state.get("act", 1) or 1)
    tun = tuning_for(content)
    scores = (state.get("rel") or {}).get(char_id) or relationships.new_scores()
    rel = relationships.state_for(c, scores, tun, lang=lang_of(content))
    dead = char_id in _dead_ids(state)
    # their secrets: titles appear only after the first layer opened (journal's rule)
    unlocked = set(state.get("unlocked_fragment_ids") or [])
    secrets, hidden = [], 0
    for sec in content.get("secrets", []) or []:
        if sec.get("character_id") != char_id:
            continue
        frags = sec.get("fragments", []) or []
        got = sum(1 for f in frags if f.get("id") in unlocked)
        if got:
            secrets.append({"title": (sec.get("title") or "").strip(),
                            "unlocked": got, "total": len(frags)})
        else:
            hidden += 1
    # where they are right now (only if the place is discovered)
    home = char_position(content, state, c)
    loc = _location_by_id(content, home) if (home and home != AWAY) else None
    where = (loc.get("name") if (loc and location_available(content, state, loc)) else None)
    if home == AWAY:
        where = _t(content, "此刻不知去向", "whereabouts unknown right now")
    if char_id in set(state.get("following") or []):
        where = _t(content, "与你同行", "traveling with you")
    # 分层小传: closeness unlocks authored layers; the next locked bar is shown as a tease
    closeness = int(scores.get("closeness", 0))
    bio_open, bio_next = [], None
    for layer in sorted(c.get("bio_layers") or [], key=lambda x: int(x.get("closeness_min", 0))):
        need = int(layer.get("closeness_min", 0))
        if closeness >= need:
            bio_open.append(layer.get("text") or "")
        elif bio_next is None:
            bio_next = need
    return {
        "id": char_id, "name": c.get("name") or "", "role": c.get("role") or "",
        "persona_text": c.get("persona_text") or "", "avatar_url": c.get("avatar_url"),
        "is_lead": bool(c.get("is_lead")), "generated": bool(c.get("generated")),
        "dead": dead, "relation": rel,
        "following": char_id in set(state.get("following") or []),
        "can_follow": (not dead) and relationships.can_follow(c, scores, tun),
        "secrets": secrets, "secrets_hidden": hidden,
        "where": where,
        "ties": npc_ties_of(content, state, char_id),  # 🕸 TA与其他人 (met-only, no leaks)
        "hp": char_hp(state, char_id),                 # healthy | hurt | dying | dead
        "keepsakes": [k.get("name") for k in
                      (((state.get("char_sim") or {}).get(char_id) or {})
                       .get("keepsakes") or [])],       # 🎁 gifts they kept
        "carrying": [i.get("name") for i in char_items(content, state, char_id)],
        "log": list((state.get("rel_log") or {}).get(char_id) or []),
        "bio": [b for b in bio_open if b], "bio_next_at": bio_next,
        "closeness": closeness, "romance": int(scores.get("romance", 0)),
        # 🪞 TA眼中的你 (活世界 P2): 相处蒸馏出的印象, 档案卡可见
        "impression": profile_mod.impression_of(state, char_id),
        # 📔 TA的日记 (Yi 2026-07-25: 心动/甜蜜只住这里): 暧昧/恋人档解锁,
        # 锁着只报条数 — 日记本身是养成奖励
        "diary": diary_view(content, state, char_id, tun),
    }


def journal(content: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    """The player's reviewable dossier (线索档案 + 结局图鉴). Discovery made tangible:
    - secrets the player has STARTED uncovering, with their unlocked fragments' full text
      and a count of layers still locked (locked bodies never leave the server; untouched
      secrets aren't listed at all — only a global remaining count)
    - the ending gallery: achieved milestones by title, the rest as ？？？ slots
    - the key decisions already made."""
    unlocked = set(state.get("unlocked_fragment_ids") or [])
    story = content.get("story") or {}
    chars = {c.get("id"): c.get("name") for c in story.get("characters", []) or []}
    # 🃏 who can be confronted right now: the secret's owner, alive, standing in this scene
    here_ids = {c.get("id") for c in scene_characters(content, state)
                if c.get("id") != state.get("player_character_id")}
    secrets, untouched = [], 0
    for sec in content.get("secrets", []) or []:
        frags = sec.get("fragments", []) or []
        got = [f for f in frags if f.get("id") in unlocked]
        if not got:
            untouched += 1
            continue
        scid = sec.get("character_id")
        secrets.append({
            "title": (sec.get("title") or "").strip(),
            "character": chars.get(scid) or "",
            "character_id": scid,
            # 出示对峙 is offered only when there's still a layer to pry open
            "confrontable": bool(scid in here_ids and len(got) < len(frags)
                                 and (state.get("mode") or "character") != "god"),
            "unlocked": [(f.get("content") or "").strip() for f in got],
            "frags": [{"id": f.get("id"), "text": (f.get("content") or "").strip()} for f in got],
            "locked_count": len(frags) - len(got),
        })
    achieved = set(state.get("achieved_endings") or [])
    endings = [{"kind": e.get("kind", "normal"),
                "achieved": e.get("id") in achieved,
                "title": (e.get("title") or "") if e.get("id") in achieved else None}
               for e in story.get("endings", []) or []]
    loc_names = {l.get("id"): l.get("name") for l in _locations(content)}
    promises = [{"name": p.get("char_name") or "", "what": p.get("what") or "",
                 "when": promise_when_label(content, p, state), "status": p.get("status"),
                 "romantic": bool(p.get("romantic"))}
                for p in (state.get("promises") or [])]
    return {"secrets": secrets, "secrets_untouched": untouched, "endings": endings,
            "promises": promises,  # 🤝 约定史: open + kept + missed
            # 📜 守则原文 (规则怪谈): shown as authored — contradictions included
            "rules": [(r.get("text") or "").strip()
                      for r in (story.get("rules") or []) if (r.get("text") or "").strip()],
            "album": list(reversed(state.get("album") or [])),  # 💞 名场面, newest first
            "choices": dict(state.get("choices") or {}),
            "identity": state.get("identity"),
            "identity_log": list(state.get("identity_log") or []),
            "inventory": list(state.get("inventory") or []),
            "stashes": [{"location": loc_names.get(lid, lid), "items": items}
                        for lid, items in (state.get("stashes") or {}).items() if items],
            "deaths": [c.get("name") for c in _characters(content)
                       if c.get("id") in _dead_ids(state) and c.get("name")]}


# ── 🌱 achievements & NG+ (二周目) ───────────────────────────────────────────────
# Story-AGNOSTIC milestones computed from the run state whenever an ending fires;
# they persist per (user, story) alongside the cross-run ending gallery. Perks are
# small NG+ start advantages a player earns by reaching any ending once.
PERKS = {
    "veteran": {"name": "故人", "desc": "似曾相识——开局便与每个人多几分亲近"},
    "instinct": {"name": "直觉", "desc": "冥冥之感——所有命运判定成功率 +10%"},
}
INSTINCT_BONUS = 10
VETERAN_CLOSENESS = 8


def compute_achievements(content: dict[str, Any], state: dict[str, Any]) -> list[dict[str, Any]]:
    """The achievements this run's CURRENT state has earned. Evaluated when an ending
    fires; the router merges them into the player's per-story meta. Pure & agnostic:
    only the abstract shape of the story is consulted, never any specific 剧本."""
    out: list[dict[str, Any]] = []
    achieved = list(state.get("achieved_endings") or [])
    if not achieved:
        return out
    story = content.get("story") or {}
    kinds = {e.get("id"): e.get("kind") for e in story.get("endings") or []}
    if any(kinds.get(eid) == "true" for eid in achieved):
        out.append({"id": "true_end", "name": "拨云见日", "desc": "达成真结局"})
    if _characters(content) and not state.get("dead_character_ids"):
        out.append({"id": "no_blood", "name": "一滴血都没流", "desc": "抵达结局时，无人死去"})
    all_frag_ids = {f.get("id") for f in gating.iter_fragments(content) if f.get("id")}
    if all_frag_ids and all_frag_ids <= set(state.get("unlocked_fragment_ids") or []):
        out.append({"id": "all_truths", "name": "无所不知", "desc": "揭开这个故事的全部真相"})
    tun = tuning_for(content)
    rel = state.get("rel") or {}
    if any(relationships.derive_mode(c, rel.get(c.get("id")) or relationships.new_scores(), tun)
           == "lover" for c in _characters(content)):
        out.append({"id": "heartbeat", "name": "心有所属", "desc": "有人真正为你心动"})
    if int(state.get("confronts_won") or 0) >= 3:
        out.append({"id": "interrogator", "name": "铁齿铜牙", "desc": "三次对质撬开真相"})
    if tun["turns_per_slot"] > 0 and int((state.get("clock") or {}).get("day", 1) or 1) <= 2:
        out.append({"id": "swift", "name": "雷厉风行", "desc": "两天之内便抵达结局"})
    if (state.get("flags") or {}).get("verdict_solved") \
            and len(state.get("verdict_tried") or []) == 1:
        out.append({"id": "sharp_eye", "name": "一锤定音", "desc": "第一次指认就命中真相"})
    return out


# ── 🃏 万物铸卡 (card minting) ───────────────────────────────────────────────────
# Hidden-Door-style cross-run assets: what a run BIRTHED (emergent characters, emergent
# places) and its 名场面 (relationship highlights) mint into a permanent per-story card
# collection. A character card can be carried into an NG+ run — an old acquaintance
# from a previous life walks back in.
def mint_cards(content: dict[str, Any], state: dict[str, Any]) -> list[dict[str, Any]]:
    """Cards this run has earned. Ids are stable so re-minting dedups; capped."""
    cards: list[dict[str, Any]] = []
    for c in _characters(content):
        if c.get("generated") and c.get("name"):
            cards.append({"id": f"char:{c.get('id')}", "kind": "character",
                          "name": c["name"],
                          "text": (c.get("persona_text") or c.get("role") or "")[:60],
                          "payload": {"name": c.get("name"), "role": c.get("role") or "",
                                      "persona_text": (c.get("persona_text") or "")[:200]}})
    for l in _locations(content):
        if l.get("generated") and l.get("name"):
            cards.append({"id": f"place:{l.get('id')}", "kind": "place",
                          "name": l["name"], "text": (l.get("detail") or "")[:60]})
    names = {c.get("id"): c.get("name") for c in _characters(content)}
    for cid, entries in (state.get("rel_log") or {}).items():
        for e in entries or []:
            if e.get("kind") in ("rel_up", "confront", "promise", "death"):
                txt = (e.get("text") or "").strip()
                cards.append({"id": f"m:{cid}:{e.get('act')}:{e.get('kind')}:{txt[:12]}",
                              "kind": "moment", "name": names.get(cid) or "",
                              "text": txt[:80]})
    return cards[:20]


# ── 🔍 指认结案 (the verdict) ────────────────────────────────────────────────────
# Dead-Meat-style closure: ask anything, all game long — but the case ends with the
# player FORMALLY committing to a conclusion, with limited attempts. Knowledge stops
# being a scrapbook and becomes an exam. Authored per story (story.verdict):
#   {prompt, options: [{id, label, correct, text?}], attempts, act_min,
#    fail_ending_id}  — a correct call sets flags.verdict_solved (gate your 真结局 on
# it); burning every attempt fires fail_ending_id (trigger:"verdict").
def verdict_cfg(content: dict[str, Any]) -> dict[str, Any] | None:
    v = (content.get("story") or {}).get("verdict") or {}
    return v if (v.get("prompt") or "").strip() and (v.get("options") or []) else None


def verdict_view(content: dict[str, Any], state: dict[str, Any]) -> dict[str, Any] | None:
    """What the UI shows: None until the act unlocks it; never leaks which option is
    correct. Solved/failed runs see their outcome."""
    v = verdict_cfg(content)
    if not v or (state.get("mode") or "character") == "god":
        return None
    act_min = int(v.get("act_min") or 0) or _max_act_index(content)
    if int(state.get("act", 1) or 1) < act_min:
        return None
    tried = list(state.get("verdict_tried") or [])
    attempts = max(1, int(v.get("attempts") or 2))
    return {"prompt": (v.get("prompt") or "").strip(),
            "options": [{"id": o.get("id"), "label": (o.get("label") or "").strip()}
                        for o in v.get("options") or [] if o.get("id")],
            "attempts_left": max(0, attempts - len(tried)),
            "tried": tried,
            "solved": bool((state.get("flags") or {}).get("verdict_solved")),
            "failed": bool(state.get("verdict_failed"))}


def submit_verdict(content: dict[str, Any], state: dict[str, Any],
                   option_id: str) -> dict[str, Any]:
    """One formal accusation. Correct → flags.verdict_solved (endings gate on it) and
    the authored reveal text. Wrong → an attempt burns; the last wrong one fires the
    authored fail ending (trigger:"verdict"). Raises ValueError when not submittable."""
    view = verdict_view(content, state)
    if not view:
        raise ValueError("还不到结案的时候")
    if view["solved"]:
        raise ValueError("你已经指认过了，案子结了")
    if view["failed"] or view["attempts_left"] <= 0:
        raise ValueError("你的机会用完了")
    v = verdict_cfg(content)
    opt = next((o for o in v.get("options") or [] if o.get("id") == option_id), None)
    if not opt:
        raise ValueError("没有这个选项")
    if option_id in (state.get("verdict_tried") or []):
        raise ValueError("这个结论你已经指认过了")
    state["verdict_tried"] = list(state.get("verdict_tried") or []) + [option_id]
    if opt.get("correct"):
        flags = dict(state.get("flags") or {})
        flags["verdict_solved"] = True
        state["flags"] = flags
        text = (opt.get("text") or "").strip() or "真相在这一刻拼合完整，再没有对不上的地方。"
        return {"correct": True, "text": text, "attempts_left": view["attempts_left"] - 1,
                "ending": None}
    left = view["attempts_left"] - 1
    text = (opt.get("text") or "").strip() or "不对。有什么地方对不上，这个结论立不住。"
    ending = None
    if left <= 0:
        state["verdict_failed"] = True
        authored = _ending_by_id(content, v.get("fail_ending_id")) or {}
        ending = {"id": authored.get("id") or "verdict_fail",
                  "kind": authored.get("kind", "bad"),
                  "title": authored.get("title") or "错判",
                  "text": authored.get("text") or "",
                  "terminal": bool(authored.get("kind") == "death")}
        achieved = set(state.get("achieved_endings") or [])
        achieved.add(ending["id"])
        state["achieved_endings"] = sorted(x for x in achieved if x)
        state["ending"] = ending
        if ending["terminal"]:
            state["ended"] = True
    return {"correct": False, "text": text, "attempts_left": left, "ending": ending}


def _secret_has_newly(content: dict[str, Any], sid, newly) -> bool:
    """Did any of this secret's fragments unlock THIS turn?"""
    newset = set(newly or [])
    for s in content.get("secrets", []) or []:
        if s.get("id") == sid:
            return any(f.get("id") in newset for f in s.get("fragments", []) or [])
    return False


def build_parting_hook(content: dict[str, Any], state: dict[str, Any],
                       persona: dict[str, Any], llm: LLM | None = None,
                       comeback: bool = False) -> list[dict[str, Any]]:
    """悬念离场: ONE cliffhanger narration — the last thing they see on return, pulling
    them back in. Spoiler-safe (topic labels only).
    ⚖️ comeback=True (现行唯一入口): /leave 只暂存, 归来的点击回合才在这里写词回放,
    框成〔上回〕闪回, 且不带下幕预告 (人都回来了, 不用再钓)."""
    llm = lang_llm(llm or get_llm(), content)
    act = int(state.get("act", 1) or 1)
    topics = _pending_topics(act_progress(content, state, act))
    here = [c.get("name") for c in scene_characters(content, state) if c.get("name")]
    loc = current_location(content, state) or {}
    out = llm.generate({"parting": True, "persona": persona,
                        "place": loc.get("name") or "", "cast": here,
                        "topics": topics[:2], "scene": current_act(content, act)}) or {}
    beats = [b for b in (out.get("beats") or [])
             if b.get("type") == "description" and (b.get("text") or "").strip()]
    if not beats:
        hint = f"关于「{topics[0]}」的话" if topics else "有句话"
        hint_en = f"something about “{topics[0]}”" if topics else "something"
        beats = [{"type": "description", "speaker_name": None,
                  "text": _t(content,
                             f"（你起身离开。身后{(here[0] if here else '有人')}欲言又止，"
                             f"{hint}似乎还没说完。）",
                             f"(You rise to leave. Behind you, someone hesitates, "
                             f"{hint_en} left unsaid.)")}]
    beats = beats[:1]
    if comeback:
        beats[0]["text"] = _t(content, f"〔上回〕{beats[0]['text']}",
                              f"[Previously] {beats[0]['text']}")
        return [dedash_beat(b) for b in beats]
    # 📺 下幕预告: leaving mid-story gets a next-episode tease — the NEXT act's authored
    # title only (never its events), like the preview after the credits. Retention hook.
    nxt = current_act(content, act + 1)
    if nxt and (nxt.get("title") or "").strip() and not state.get("ended"):
        beats.append({"type": "description", "speaker_name": None,
                      "text": _t(content,
                                 f"〔下幕预告〕第{act + 1}幕《{nxt['title'].strip()}》。"
                                 "这个故事，会在你回来的地方等你。",
                                 f"[Next act] Act {act + 1}: “{nxt['title'].strip()}”. "
                                 "The story will be waiting right where you left it.")})
    return [dedash_beat(b) for b in beats]


def confront_stream(content: dict[str, Any], state: dict[str, Any], persona: dict[str, Any],
                    fragment_id: str, char_id: str,
                    llm: LLM | None = None, beat_log: list[dict[str, Any]] | None = None):
    """🃏 证据对峙: the player slams a truth they've UNLOCKED down in front of the character
    it belongs to. A visible opposed check decides the scene: success pries the secret's
    next layer open ON THE SPOT (evidence beats every unlock gate — but being cornered
    costs the relationship); failure hardens them, and a 大失败 hands them the round and
    feeds the story's pressure meter. Knowledge stops being a museum piece — it's a verb.

    Validates EAGERLY (raises ValueError with a player-readable reason), then returns a
    generator speaking the /play stream contract: ('dice',…) ('beat',…) ('final',…)."""
    llm = lang_llm(llm or get_llm(), content)
    state = {**default_state(), **(state or {})}
    state["location_id"] = (current_location(content, state) or {}).get("id")
    if (state.get("mode") or "character") == "god":
        raise ValueError("旁观者不在故事里，无法与人对峙")
    target = _char_by_id(content, char_id)
    if not target:
        raise ValueError("没有这个人")
    if char_id in _dead_ids(state):
        raise ValueError("TA已不在人世")
    if char_id == state.get("player_character_id"):
        raise ValueError("不能对峙你自己")
    if not any(c.get("id") == char_id for c in scene_characters(content, state)):
        raise ValueError("TA不在这里——先找到TA再当面对质")
    secret = frag = None
    for sec in content.get("secrets") or []:
        for f in sec.get("fragments") or []:
            if f.get("id") == fragment_id:
                secret, frag = sec, f
                break
    if not frag:
        raise ValueError("没有这条线索")
    unlocked = set(state.get("unlocked_fragment_ids") or [])
    if fragment_id not in unlocked:
        raise ValueError("你还没真正掌握这条线索")
    if secret.get("character_id") != char_id:
        raise ValueError("这件事不在TA身上——证据要摆到当事人面前才有分量")
    next_locked = next((f for f in secret.get("fragments") or []
                        if f.get("id") not in unlocked), None)
    if next_locked is None:
        raise ValueError("关于这件事，TA已经没什么可瞒你的了")
    return _confront_gen(content, state, persona, secret, frag, next_locked, target, llm, beat_log)


def _confront_gen(content, state, persona, secret, frag, next_locked, target, llm, beat_log):
    tun = tuning_for(content)
    char_id = target.get("id")
    tname = target.get("name") or "TA"
    old_act = int(state.get("act", 1) or 1)
    rel_all = state.setdefault("rel", {})
    scores = rel_all.get(char_id) or relationships.new_scores()
    closeness = int(scores.get("closeness", 0))
    # the closer you are, the likelier they come clean when cornered
    chance = max(25, min(90, tun["confront_base"] + closeness // 2))
    if state.get("perk") == "instinct":   # 🌱 NG+ 直觉: every fate check runs warmer
        chance = min(95, chance + INSTINCT_BONUS)
    dice = _roll_check(chance)
    yield ("dice", dice)
    success = dice["outcome"] in ("success", "crit_success", "mixed")
    if success:
        state["confronts_won"] = int(state.get("confronts_won") or 0) + 1
    forced_id = next_locked.get("id") if success else None
    if forced_id:
        state["unlocked_fragment_ids"] = sorted(set(state.get("unlocked_fragment_ids") or [])
                                                | {forced_id})
    # being cornered stings even when they yield; a 大成功 lands so true it costs nothing
    cost = tun["confront_cost"]
    dc = {"crit_success": 0, "success": -cost, "mixed": -cost * 2,
          "fail": -cost * 2, "crit_fail": -cost * 3}[dice["outcome"]]
    rel_deltas: dict[str, dict[str, int]] = {}
    if dc:
        rel_all[char_id] = relationships.apply_deltas(scores, dc, 0, tun)
        applied = int(rel_all[char_id].get("closeness", 0)) - closeness
        if applied:
            rel_deltas[char_id] = {"name": tname, "closeness": applied, "romance": 0}
    moments: list[dict[str, Any]] = [{"kind": "confront", "name": tname,
                                      "outcome": dice["outcome"]}]
    pcfg = pressure_cfg(content)
    if pcfg and dice["outcome"] == "crit_fail":
        # a blown confrontation makes noise. Capped at 99: only a full turn can blow the lid
        state["pressure"] = min(99, int(state.get("pressure", 0)) + 8)
        moments.append({"kind": "pressure",
                        "note": _t(content, "这场对质闹出了动静。",
                                   "That confrontation made some noise."),
                        "value": state["pressure"]})
    title = (secret.get("title") or "").strip() or "那件事"
    ev = (frag.get("content") or "").strip()
    beats_out: list[dict[str, Any]] = []

    def emit(b):
        dedash_beat(b)
        beats_out.append(b)
        return ("beat", b)

    yield emit({"type": "description", "speaker_name": None,
                "text": _t(content, f"（你直视着{tname}，把你已经知道的事一字一句摆到TA面前：{ev}）",
                           f"(You look {tname} in the eye and lay out, word by word, "
                           f"what you already know: {ev})")})
    if forced_id:
        for t in _titles_for_fragments(content, [forced_id]):
            moments.append({"kind": "unlock", "title": t})
        rel_log(state, char_id, old_act, "confront",
                _t(content, f"你当面摆出证据，TA终于松口，「{title}」又揭开一层。",
                   f"You laid out the evidence; they finally gave, and “{title}” peeled another layer."))
    else:
        rel_log(state, char_id, old_act, "confront",
                _t(content, f"你拿「{title}」的证据当面对质，被TA挡了回来。",
                   f"You confronted them with the “{title}” evidence and got stonewalled."))
    # the model PERFORMS the aftermath with the character's full normal context; the forced
    # fragment rides the standard new_reveal channel (【必须亲口说出来】 machinery)
    frags = gating.iter_fragments(content)
    ctx = gating.build_context(char_id, frags, state, newly_ids=[forced_id] if forced_id else [])
    pcid = state.get("player_character_id")
    player_char = _char_by_id(content, pcid) if pcid else None
    persona_for_prompt = persona or {}
    if player_char:
        _pc_bits = [player_char.get("background") or persona_for_prompt.get("background", "")]
        if (player_char.get("persona_text") or "").strip():
            _pc_bits.append(f"【TA的为人】{player_char['persona_text'].strip()}")
        if (player_char.get("wants") or "").strip():
            _pc_bits.append(f"【TA自己的立场与目标】{player_char['wants'].strip()}")
        persona_for_prompt = {**persona_for_prompt, "name": player_char.get("name"),
                              "background": "　".join(b for b in _pc_bits if b)}
    pl_name = persona_for_prompt.get("name") or "对方"
    # 🗣 只有真走行首前缀协议的本子才给旁白贴记号 (plan_render 的拍2 才用 _LineSegmenter)
    sp_hist = (history_for(beat_log, char_id, tag_narration=plan_render_on(content))
               if beat_log is not None else [])
    directed = llm.generate({
        "speaker_name": tname,
        "speaker_persona": target.get("persona_text", ""),
        "persona": persona_for_prompt,
        "player_input": f"（{pl_name}把关于「{title}」的证据摆在你面前，要你说清楚。）",
        "channel": "say",
        "context": ctx,
        "history": sp_hist,
        "memory": (state.get("memory_by_char", {}) or {}).get(char_id) or "",
        "world_facts": (content.get("story") or {}).get("world_facts") or "",
        "world": ((content.get("story") or {}).get("world_long") or "")[:600],
        # 🏛 年代随行 (只管世界长什么样, 不管日子 — 日历走玩家自己的时区)。
        # device 同行是因为年代块自带手机豁免: 不带设备名就豁免不了。
        "era": era_of(content), "device": phone_device(content),
        # 🎯 玩家亲手定的目标 (沙盒): 世界要向它倾斜
        "player_goal": next((g.get("text") for g in reversed(goals_of(state))
                             if g.get("status") == "open" and g.get("kind") == "player"), ""),
        # 🎬 作者开场白进每回合 (Yi: 是给模型学习的重要材料, 文风与事实之锚)
        "auth_opening": ((content.get("story") or {}).get("opening") or "")[:1200],
        "style": (content.get("story") or {}).get("style") or "",  # ✍️ 文风
        "roster": _physical_roster(content, state, persona),
        "creatures_here": creatures_here(content, state),
        "place": _physical_place(content, state),
        "eq_style": target.get("eq_style", ""),
        "agenda": target.get("agenda", ""),
        "relationship_playbook": relationships.playbook_block(
            relationships.derive_mode(target, rel_all.get(char_id) or scores, tun),
            mature=bool(state.get("mature")), char=target),
        "knowledge": target.get("knowledge", ""),
        "mature": bool(state.get("mature")),
        "scene": current_act(content, old_act),
        "clock": (clock_view(content, state) or {}).get("label", ""),
            "real_now": real_now_line(content, state),
        "confrontation": {"evidence": ev, "title": title, "outcome": dice["outcome"],
                          # the authored lie this reveal just tore down (if one was told)
                          "shattered": ((next_locked.get("cover") or "").strip()
                                        if forced_id else "")},
    })
    conf_beats = list(directed.get("beats", []))
    mood = (directed.get("self_state") or "").strip()[:12]
    if mood and tun["mind_reader"]:
        for b in reversed(conf_beats):
            if b.get("type") == "dialogue":
                b["mood"] = mood
                break
    for b in conf_beats:
        yield emit(b)
    # a successful confrontation may satisfy an act gate — let it open right here
    new_act = old_act
    max_act = _max_act_index(content)
    if act_has_gate(content, old_act) and max_act and can_advance(content, state, old_act):
        new_act = min(max_act, old_act + 1)
        state["act"], state["turns_in_act"] = new_act, 0
        nxt = current_act(content, new_act) or {}
        moments.append({"kind": "act", "index": new_act, "title": nxt.get("title", "")})
        yield emit({"type": "description", "speaker_name": None,
                    "text": _t(content, f"✦ 第{new_act}幕 · {nxt.get('title', '')} ✦",
                               f"✦ Act {new_act} · {nxt.get('title', '')} ✦")})
        nc = choice_for_act(content, state, new_act)
        if nc:
            state["pending_choice"] = nc
    # 🎯 新幕只换幕层兜底, 差事/自立目标不被幕推进冲掉 (目标栈)
    state["goal"] = goal_top(content, state)
    yield ("final", {
        "state": state,
        "newly_unlocked": [forced_id] if forced_id else [],
        "moments": moments,
        "rel_deltas": rel_deltas,
        "dice": dice,
        "goal": state["goal"],
        "progress": act_progress(content, state, new_act),
        "pending_choice": state.get("pending_choice"),
        "pressure_view": ({"name": pcfg.get("name"), "value": int(state.get("pressure", 0))}
                          if pcfg else None),
        "relations": relations_summary(content, state),
    })


def run_turn(
    content: dict[str, Any],
    state: dict[str, Any],
    persona: dict[str, Any],
    player_input: str,
    channel: str = "say",
    llm: LLM | None = None,
    history: list[dict[str, str]] | None = None,
    target_character_id: str | None = None,
    returning: bool = False,
    away_hours: float = 0.0,
) -> dict[str, Any]:
    """Advance one turn, returning the whole result at once (beats + state + extras).

    A thin wrapper over run_turn_stream — used by tests and the opening flow. The SSE
    endpoint uses run_turn_stream directly so each character's reply streams out as it's
    computed (first speaker in ~2-3s instead of waiting for the whole room)."""
    beats: list[dict[str, Any]] = []
    final: dict[str, Any] = {}
    for kind, payload in run_turn_stream(
        content, state, persona, player_input, channel, llm, history, target_character_id,
        returning=returning, away_hours=away_hours,
    ):
        if kind == "beat":
            beats.append(payload)
        elif kind == "final":
            final = payload  # "dice" etc. ride inside the final payload for this wrapper
    final["beats"] = beats
    return final


def _settle_directed(content, state, tun, sp, sp_id, sp_name, is_primary, directed,
                     observer, pcid, old_act, dice, pcfg, newly, asks,
                     provisional_asks, provisional_events, probe_cands, event_cands,
                     moments, rel_deltas, rel_all, rel_active, said_this_turn,
                     dead_names, emergent_ids, emit, llm, flags):
    """管线 P7b · 逐人落账: everything this speaker's directed output REPORTS gets
    validated and booked — relationship flow & tier-ups, promises, probe/event
    reconciliation, pressure, wounds & two-stage deaths, NPC moves, emergent
    characters, identity, craft/take/trade/gift, money, quests, world facts, items.
    Scalar outcomes ride `flags`; every rejection lands on the audit sheet.
    Extracted verbatim from run_turn_stream (管线刀1)."""
    if tun.get("rel_events"):
        # 💞 事件记账制 (Yi 定: 关系由事写成, 每句话打分作废): 模型只申报
        # {kind, evidence}, 分值查引擎法条; 正面事件按 (角色,类别) 冷却防刷,
        # 负面零冷却; 无事件 = 关系纹丝不动 (闲聊就是闲聊)。
        this_delta, _rd_event, _td_event = 0, 0, 0
        _ev = directed.get("rel_event")
        if isinstance(_ev, dict) and sp_id and sp_id != pcid:
            _kind = str(_ev.get("kind") or "").strip()
            _evid = dedash(str(_ev.get("evidence") or "").strip())[:20]
            _law = _REL_EVENTS.get(_kind)
            if not _law:
                if _kind:
                    _audit(state, "rel.event", False, _kind[:8], "不在法条里")
            elif _law[3] and not any(m in ("flirt", "lover")
                                     for m in relationships.allowed_modes(sp or {})):
                # 与 derive_mode 同一部法: relation_allowed 没排除恋爱线就算可恋
                # (未配置 = 全模式可达; _romance_capable 是更严的显式白名单, 不用它)
                _audit(state, "rel.event", False, f"{sp_name}:{_kind}", "这条线TA不走")
            else:
                _cdb = state.setdefault("rel_ev_cd", {})
                _seq = int(state.get("turn_seq") or 0)
                _key = f"{sp_id}:{_kind}"
                if _law[2] and _seq - int(_cdb.get(_key) or -999) < _law[2]:
                    _audit(state, "rel.event", False, f"{sp_name}:{_kind}", "冷却中(刷分驳回)")
                else:
                    this_delta, _rd_event = _law[0], _law[1]
                    _td_event = _law[4] if len(_law) > 4 else 0   # 🛡 信任Δ随法条走
                    if _law[2]:
                        _cdb[_key] = _seq
                        if len(_cdb) > 60:
                            for _k in list(_cdb)[:-40]:
                                _cdb.pop(_k, None)
                    _audit(state, "rel.event", True, f"{sp_name}:{_kind}·{_evid[:12]}")
        flags["affinity_delta"] += this_delta
    else:
        this_delta = int(directed.get("affinity_delta", 0) or 0)
        _rd_event = None
        _td_event = 0   # 旧打分制没有信任语义
        flags["affinity_delta"] += this_delta
    # ✍️ 编剧拍落账 (剧组 P2): 情绪申报 / 伏笔埋收 / 人生目标推进 — 主答者一人申报。
    # 申报消毒 (实弹: 模型把 schema 碎片回显进 setup_plant): 带结构符号的值一律驳回
    def _claim(v: Any, cap: int) -> str:
        t = dedash(str(v or "").strip())[:cap]
        return "" if any(ch in t for ch in "{}[]\"':`") else t
    if is_primary:
        _mood_claim = str(directed.get("mood") or "").strip()
        if _mood_claim:
            flags["mood_claim"] = _mood_claim[:6]
        # 🎬 场账本申报 (docs/scene-ledger.md): 本拍花掉的动作/抛出的问题/接住的回答 —
        # 与 mood 同款三段式 (申报→flags 暂存→回合尾 _sl_settle 统一落账)
        for _sk in ("spent", "asked", "answered"):
            _sv = _claim(directed.get(_sk), 12)
            if _sv:
                flags["scene_" + _sk] = _sv
        _day_now = int((state.get("clock") or {}).get("day", 1) or 1)
        stps = state.setdefault("setups", [])
        _plant = _claim(directed.get("setup_plant"), 24)
        if _plant and all(_plant != s.get("text") for s in stps):
            stps.append({"text": _plant, "day": _day_now, "due": _day_now + 2, "paid": False})
            del stps[:-6]
            _audit(state, "setup.plant", True, _plant[:20])
        _pay = _claim(directed.get("setup_pay"), 30)
        if _pay:
            _hit = next((s for s in stps if not s.get("paid")
                         and (str(s.get("text")) in _pay or _pay in str(s.get("text")))), None)
            if _hit:
                _hit["paid"] = True
                _audit(state, "setup.pay", True, str(_hit["text"])[:20])
            else:
                _audit(state, "setup.pay", False, "没有对得上的伏笔")
        for s in stps:   # 过期的钩子明书作废 — 说了不算要留痕, 不许悄悄蒸发
            if not s.get("paid") and _day_now > int(s.get("due") or 0):
                s["paid"] = "expired"
                _audit(state, "setup.expired", True, str(s.get("text"))[:20])
        _ag = directed.get("agenda_step")
        if isinstance(_ag, dict) and _claim(_ag.get("who"), 12):
            _who = next((c for c in scene_characters(content, state)
                         if c.get("name") == _claim(_ag.get("who"), 12)), None)
            if _who:
                agenda_advance(state, _who, stage=_claim(_ag.get("stage"), 16),
                               step=_claim(_ag.get("step"), 20))
            else:
                _audit(state, "agenda.step", False, f"{_ag.get('who')}不在场")
    # per-character relationship FLOW: apply this speaker's own closeness (=好感) and
    # 心动 deltas to their relationship-toward-player scores; the derived mode shifts
    # gradually (clamped) so next turn this character treats the player accordingly.
    if rel_active and sp_id and sp_id != pcid:
        old_scores = rel_all.get(sp_id) or relationships.new_scores()
        mode_before = relationships.derive_mode(sp, old_scores, tun)
        # 🎭 今日心气上色 (Yi: 好感要像真实的人一样忽高忽低): 心气差的日子
        # 好话打折坏话加倍, 心气好反之 — 当天稳定, 跨天翻面
        _mood_day = relationships.day_mood(sp_id, int((state.get("clock") or {}).get("day", 1) or 1))
        _rd_raw = (_rd_event if _rd_event is not None
                   else int(directed.get("romance_delta", 0) or 0))
        _cd_in, _rd_in = relationships.temper(this_delta, _rd_raw, _mood_day)
        if _mood_day and (_cd_in, _rd_in) != (this_delta, _rd_raw):
            _audit(state, "rel.mood", True, f"{sp_name}:{'差' if _mood_day < 0 else '好'}")
        rel_all[sp_id] = relationships.apply_deltas(old_scores, _cd_in, _rd_in, tun,
                                                    trust_delta=_td_event)
        mode_after = relationships.derive_mode(sp, rel_all[sp_id], tun)
        dc = int(rel_all[sp_id].get("closeness", 0)) - int(old_scores.get("closeness", 0))
        dr = int(rel_all[sp_id].get("romance", 0)) - int(old_scores.get("romance", 0))
        if dc or dr:
            rel_deltas[sp_id] = {"name": sp_name, "closeness": dc, "romance": dr}
        # 🏛 阵营声望落账 (报审): 发言者代表自己的阵营感受玩家言行; 对头反向记半
        _fac = factions_mod.of_char(content, sp)
        _fd = int(directed.get("rep_delta") or 0)
        if _fac and _fd:
            _applied = factions_mod.apply_delta(state, content, _fac["id"], _fd)
            if _applied:
                _audit(state, "faction.rep", True,
                       "；".join(f"{(factions_mod.by_id(content, k) or {}).get('name', k)}"
                                 f"{'+' if v > 0 else ''}{v}" for k, v in _applied.items()))
        # CELEBRATE a tier-up (陌生→朋友→暧昧→恋人): the "高潮=阈值被跨过" moment, made
        # visible — a strong reward + come-back hook. Only on an UPGRADE, never a downgrade.
        if mode_after != mode_before and _RANK.get(mode_after, 0) > _RANK.get(mode_before, 0):
            mn = relationships.name_of(mode_after, lang_of(content))
            # 💗 机械弹窗软化 (Yi: 账本过线突然蹦心动瞬间不合逻辑): 只有「成为恋人」
            # 当场亮牌; 其余档位静默入账 (面板数值照常), 戏交给每日浪漫结算的袒露心声
            if mode_after == "lover":
                moments.append({"kind": "rel_up", "character_id": sp_id, "name": sp_name,
                                "mode": mode_after, "mode_name": mn})
            # 💘 a tier-up is a warm spike — a styled character will pull back next time
            if relationships.love_style_of(sp):
                _sim(state, sp_id)["warm_peak"] = {"t": _time_index(state), "served": False}
            rel_log(state, sp_id, old_act, "rel_up",
                    _t(content, f"你们成了「{mn}」。", f"You became “{mn}”."))
            album_add(content, state, "rel_up",
                      _t(content, f"成为{mn}", f"Becoming {mn}"),
                      _last_line_of(said_this_turn, sp_name)
                      or _t(content, f"你和{sp_name}成了「{mn}」。",
                            f"You and {sp_name} became “{mn}”."), sp,
                      rarity=3 if mode_after == "lover" else 2)
            if mode_after == "lover":
                yield emit({"type": "description", "speaker_name": None,
                            "text": _t(content,
                                       f"💗（你感觉到，和{sp_name}的关系又近了一层。现在你们是"
                                       f"「{mn}」了。）",
                                       f"💗 (You can feel it — something between you and {sp_name} "
                                       f"has shifted closer. You are now “{mn}”.)")})
            # 📮 crossing into 恋人 earns a LETTER: some things TA can only write down
            if mode_after == "lover" and phone_enabled(content):
                lm = compose_letter(content, state, sp, "love_letter",
                                    "你们刚刚捅破了那层窗户纸，成了恋人。把当面说不出口的"
                                    "那些话，写成一封信给TA", llm)
                yield ("phone", {"char_id": sp_id, "name": sp_name,
                                 "avatar_url": sp.get("avatar_url"), "mail": True,
                                 "msgs": [lm["subject"]], "device": phone_device(content)})
                moments.append({"kind": "mail", "name": sp_name,
                                "device": phone_device(content)})
    if directed.get("advance_act"):
        flags["advance"] = True
    if is_primary:
        model_ending = directed.get("ending")  # only the addressed scene can end the run
        if sandbox_on(content):
            mk = (model_ending or {}).get("kind") if isinstance(model_ending, dict) \
                else (model_ending or "")
            if "death" in str(mk) and not (directed.get("player_harm") or "").strip():
                directed["player_harm"] = "重伤"
            model_ending = None  # 🏖 the sandbox has no exits
        flags["model_ending"] = model_ending
        # a character may ASK to lead the player elsewhere — captured here, surfaced as a
        # confirm prompt (never auto-applied; the player relocates via /move on a yes).
        flags["primary_invite"] = directed.get("move_invite")
        flags["primary_name_for_invite"] = sp_name
        flags["time_skip"] = (directed.get("time_skip") or "").strip()
        # 📇 戏里把号给了 (模型申报) → P8 落账; 只认主答者这一路
        if directed.get("contact_given") and not observer:
            flags["contact_given"] = True
        # 🧭 声明式移动: the narration itself already WALKED the player somewhere this
        # turn (穿过窄门/出了大门). The engine makes it true so prose and state can never
        # drift apart: known & reachable → move; sandbox & off-map → the place gets
        # generated for real (the prose has committed); otherwise rejected on the audit.
        _cg = (directed.get("cult_gain") or "").strip() if not observer else ""
        if _cg:
            _cg_txt = cult_declared_gain(content, state, _cg)
            if _cg_txt:
                yield emit({"type": "description", "speaker_name": None, "text": _cg_txt})
        mv_to = (directed.get("moved_to") or "").strip() if not observer else ""
        # 🔒 声明式移动整条关掉 (LLM_MAP_WRITES)。注意这里有两条分支要一起堵: 去【未知】
        # 地点被铸造闸挡住了, 去【已有】地点却是直接 commit_move —— 只堵铸造等于只堵一半。
        if mv_to and not LLM_MAP_WRITES:
            _audit(state, "move.narrated", False, mv_to, "对话改地图已关闭")
            mv_to = ""
        if mv_to:
            cur_l = current_location(content, state)
            dest_l = resolve_location(content, mv_to)
            if dest_l and dest_l.get("id") == (cur_l or {}).get("id"):
                pass                                   # narrated arriving where we already are
            # 🗺 通路检查已拿掉 (Yi 2026-08-08「模型决定」)。作者写的 exits 只是对相邻
            # 关系的一次猜测, 而故事知道得更准 —— 实弹: 某剧本里两地走三分钟就到、
            # 角色开场台词就是相邀去那儿, 作者只是没把这条边写进 exits。引擎拿一张
            # 不完整的邻接表去否决, 模型照样把人写过去, 只是账本不跟 = 文与实分家。
            # 解锁闸留着: 哪一幕能去哪是作者的剧作结构, 不是地理。
            elif dest_l and dest_l.get("id") \
                    and location_available(content, state, dest_l):
                commit_move(content, state, dest_l, lead_id=sp_id)   # 带路的人一起走
                _audit(state, "move.narrated", True, mv_to,
                       "" if _route_exists(content, state, (cur_l or {}).get("id"),
                                           dest_l["id"]) else "作者没写这条通路")
            elif not dest_l and sandbox_on(content) and not _bad_place_name(mv_to):
                try:
                    if generate_and_move(content, state, mv_to, llm=llm,
                                         lead_id=sp_id) is not None:
                        flags["content_mutated"] = True    # run grew a location → persist content
                        _audit(state, "move.narrated", True, f"{mv_to}（新生成）")
                    else:
                        _audit(state, "move.narrated", False, mv_to, "不是具体去处")
                except Exception:
                    _audit(state, "move.narrated", False, mv_to, "生成失败")
            else:
                _audit(state, "move.narrated", False, mv_to, "不可达或未解锁")
        # 🤝 the speaker set a future appointment with the player (恋与深空-style
        # proactive 邀约 at romance tiers) — record it, announce it, hang it in the bar
        pm = directed.get("promise")
        if pm and not observer:
            made = make_promise(content, state, sp, pm, tun)
            if made:
                loc_nm = (_location_by_id(content, made.get("location_id")) or {}).get("name") or "老地方"
                when = promise_when_label(content, made, state)
                moments.append({"kind": "promise", "status": "made",
                                "name": sp_name, "what": made["what"], "when": when,
                                "romantic": bool(made.get("romantic"))})
                yield emit({"type": "description", "speaker_name": None,
                            "text": _t(content,
                                       f"（约定立下了：{when}，{loc_nm}见，{made['what']}。）",
                                       f"(It's a promise: {when}, at {loc_nm} — "
                                       f"{made['what']}.)")})
        emo = (directed.get("player_emotion") or "").strip()
        if emo:
            state["player_emotion"] = emo       # carry the emotional read into next turn
        # RECONCILE ask/event judgment (root fix for keyword-stuffing). When the model
        # supplies a judgment it becomes the truth: a provisional keyword ask it rejects
        # is rolled back (unless it already unlocked something — unlocks stay sticky),
        # and a genuine probe the keywords missed is counted (its reveal lands next
        # turn, same one-turn lag as affinity reveals). No judgment (mock/prose
        # fallback) → the keyword result stands, so tests stay deterministic.
        judged = directed.get("probed")
        if judged is not None:
            judged_ids = _match_candidates(probe_cands, judged, "title")
            for sid in provisional_asks:
                if sid not in judged_ids and asks.get(sid, 0) > 0 \
                        and not _secret_has_newly(content, sid, newly):
                    asks[sid] -= 1
            for sid in judged_ids:
                if sid not in provisional_asks:
                    asks[sid] = asks.get(sid, 0) + 1
            state["asks"] = asks
        occurred = directed.get("occurred")
        if occurred is not None:
            ev_ids = _match_candidates(event_cands, occurred, "label")
            trig = set(state.get("triggered_event_ids") or [])
            trig -= (provisional_events - ev_ids)  # roll back denied keyword guesses
            trig |= ev_ids
            state["triggered_event_ids"] = sorted(trig)
        # ⚠️ pressure: apply the judged delta, announce level crossings, remember a blowout
        if pcfg and directed.get("pressure_delta") is not None:
            p_old = int(state.get("pressure", 0))
            p_new = max(0, min(100, p_old + int(directed.get("pressure_delta") or 0)))
            state["pressure"] = p_new
            for lv in sorted(pcfg.get("levels") or [], key=lambda x: int(x.get("at", 0))):
                at = int(lv.get("at", 0))
                if p_old < at <= p_new and (lv.get("note") or "").strip():
                    yield emit({"type": "description", "speaker_name": None,
                                "text": f"（{lv['note']}）"})
                    moments.append({"kind": "pressure", "note": lv["note"], "value": p_new})
            if p_new >= 100:
                flags["pressure_blown"] = True
        # 💀 THE PLAYER'S OWN BODY (sandbox): judged wounds on the same two-stage
        # ladder as everyone else — a killing blow on the healthy leaves them 濒死,
        # never instantly dead. Death is not an ending here: the world keeps
        # running; the dead lose 说 and 做, and can only watch.
        ph_ref = (directed.get("player_harm") or "").strip()
        if ph_ref and sandbox_on(content) and not observer \
                and (state.get("player_hp") or "healthy") != "dead":
            cur_php = state.get("player_hp") or "healthy"
            if any(w in ph_ref for w in ("好转", "救", "包扎", "缓")):
                nxt_php = {"dying": "hurt", "hurt": "healthy"}.get(cur_php)
                if nxt_php:
                    state["player_hp"] = nxt_php
                    moments.append({"kind": "player_hp", "hp": nxt_php})
                    yield emit({"type": "description", "speaker_name": None,
                                "text": "（你缓过来一些了。还疼，但死神松了手。）"
                                        if nxt_php == "hurt"
                                        else "（伤势稳住了。你重新站稳了脚。）"})
            else:
                heavy = any(w in ph_ref for w in ("重", "濒", "毙", "致命", "死"))
                nxt_php = ("dead" if cur_php == "dying" and heavy else
                           "dying" if (cur_php in ("hurt", "dying") or heavy) else "hurt")
                if nxt_php != cur_php:
                    state["player_hp"] = nxt_php
                    moments.append({"kind": "player_hp", "hp": nxt_php})
                    yield emit({"type": "description", "speaker_name": None, "text": {
                        "hurt": "（你挂了彩。不致命，但每动一下，伤口都在提醒你。）",
                        "dying": "（你眼前发黑，力气一丝丝往外漏。再没有人管你，你就交代在这了。）",
                        "dead": "（世界没有停下来。只是你再也发不出声音，再也碰不到任何东西。"
                                "从这一刻起，你成了看客。）"}[nxt_php]})
        # 🩸 HARM: judged wounds move ONE step on the graded ladder (轻伤/重伤/好转)
        harm_ref = (directed.get("harmed") or "").strip()
        if harm_ref:
            hname, _, hlevel = harm_ref.partition("|")
            hvictim = next((c for c in scene_characters(content, state)
                            if c.get("id") != pcid and (c.get("name") or "")
                            and (c["name"] in hname or hname.strip() in c["name"])), None)
            if not hvictim:
                _audit(state, "harm", False, hname.strip(), "伤的人不在这个场景里")
            if hvictim and hvictim.get("id") not in _dead_ids(state):
                hid, cur_hp = hvictim["id"], char_hp(state, hvictim.get("id"))
                hl = hlevel.strip()
                if "好转" in hl or "包扎" in hl or "救" in hl:
                    nxt = {"dying": "hurt", "hurt": None}.get(cur_hp, None)
                    if cur_hp in ("dying", "hurt"):
                        set_char_hp(state, hid, nxt)
                        moments.append({"kind": "recover", "name": hvictim.get("name")})
                        rel_log(state, hid, old_act, "hurt",
                                _t(content, f"{hvictim.get('name')} 的伤势缓过来了。",
                                   f"{hvictim.get('name')} pulled through their injury."))
                else:
                    nxt = "dying" if ("重" in hl or "濒" in hl or cur_hp == "hurt") else "hurt"
                    if nxt != cur_hp:
                        set_char_hp(state, hid, nxt)
                        if nxt == "dying" and state.get("location_id"):
                            _sim(state, hid)["pos"] = state["location_id"]
                        moments.append({"kind": nxt, "name": hvictim.get("name")})
                        rel_log(state, hid, old_act, "hurt",
                                _t(content,
                                   f"{hvictim.get('name')} {'重伤濒死' if nxt == 'dying' else '受了伤'}。",
                                   f"{hvictim.get('name')} is {'critically wounded' if nxt == 'dying' else 'hurt'}."))
        # ☠️ DEATH is TWO-STAGE: only the already-dying can die. A killing blow on a
        # healthy body books them as 濒死 instead — there is always a window to save.
        died_ref = (directed.get("died") or "").strip()
        if died_ref:
            victim = next((c for c in scene_characters(content, state)
                           if c.get("id") != pcid and (c.get("name") or "")
                           and ((c["name"] == died_ref) or (c["name"] in died_ref)
                                or (died_ref in c["name"]))), None)
            if not victim:
                _audit(state, "death", False, died_ref, "死的人不在场，改判无效")
            if victim and char_hp(state, victim.get("id")) != "dying":
                _audit(state, "death", False, victim.get("name", ""),
                       "两段式规则：健康之身先判濒死，给施救留窗口")
                set_char_hp(state, victim["id"], "dying")
                if state.get("location_id"):
                    _sim(state, victim["id"])["pos"] = state["location_id"]
                moments.append({"kind": "dying", "name": victim.get("name")})
                rel_log(state, victim.get("id"), old_act, "hurt",
                        _t(content, f"{victim.get('name')} 重伤濒死。",
                           f"{victim.get('name')} is critically wounded."))
                yield emit({"type": "description", "speaker_name": None,
                            "text": f"（{victim.get('name')}还吊着一口气，气若游丝。"
                                    "现在施救，或许还来得及。）"})
            elif victim:
                deads = _dead_ids(state)
                deads.add(victim["id"])
                state["dead_character_ids"] = sorted(deads)
                state["following"] = [f for f in (state.get("following") or [])
                                      if f != victim["id"]]
                dead_names.append(victim.get("name"))
                moments.append({"kind": "death", "name": victim.get("name")})
                rel_log(state, victim.get("id"), old_act, "death",
                        _t(content, f"{victim.get('name')} 死了。", f"{victim.get('name')} died."))
                for _vp in void_promises_of(state, victim["id"]):
                    yield emit({"type": "description", "speaker_name": None,
                                "text": f"（你们约好的（{_vp.get('what','')}），"
                                        "再也没有人来赴了。）"})
        # 🚶 对话意向自动同行: someone said yes to traveling together — TA joins `following`
        # now, so the player's next move carries TA along (文与实不分家). Skip if TA is
        # also booked to walk off this turn (leaving wins — the prose put them elsewhere).
        cj = (directed.get("companion_join") or "").strip()
        if cj and not observer:
            _leaving = {str(m.get("who") or "").strip()
                        for m in (directed.get("npc_moves") or []) if isinstance(m, dict)}
            if cj not in _leaving:
                joined = accept_companion(content, state, cj)
                if joined:
                    moments.append({"kind": "follow", "on": True, "name": joined["name"],
                                    "id": joined["id"]})
        # 🚶 booked NPC moves: the model narrated someone setting off — validate and
        # BOOK it (the turn-end roster diff narrates the departure + destination)
        for mv in (directed.get("npc_moves") or [])[:2]:
            if isinstance(mv, dict):
                booked = apply_char_move(content, state, mv.get("who", ""), mv.get("to", ""))
                if booked:
                    _audit(state, "npc_move", True, f"{booked.get('name')}→{booked.get('to_name')}")
                    # 📱🔍 遗落骰: TA刚起身离开 — 设备可能落下 (条件在函数里)
                    _pw_ev = peek_maybe_drop(content, state, booked.get("id") or "",
                                             booked.get("name") or "")
                    if _pw_ev:
                        moments.append(_pw_ev)
                else:
                    _audit(state, "npc_move", False,
                           f"{mv.get('who', '')}→{mv.get('to', '')}",
                           "不在场/被作息钉住/目的地不存在")
        # 👋 EMERGENT CHARACTER: the story brought in a brand-new face — make them real
        nc_raw = (directed.get("new_char") or "").strip()
        if nc_raw and flags["gen_count"] >= tun["max_new_characters"]:
            _audit(state, "new_char", False, nc_raw[:20], "本局涌现人数已到上限")
        if nc_raw and flags["gen_count"] < tun["max_new_characters"]:
            import re as _re
            import uuid as _uuid
            parts = _re.split(r"[｜|：:，,]", nc_raw, maxsplit=1)
            nc_name = parts[0].strip().strip("「」\"'")[:12]
            nc_rest = parts[1].strip() if len(parts) > 1 else ""
            # 🗣 指纹自动出生: 约定格式「身份与外貌｜说话规律」。说话规律永远是【最末段】，
            # 身份外貌吃中间全部段——模型把「身份与外貌」再拆成两段(共≥2段)时，外貌仍留在
            # 人设里，绝不被当成腔调误存进 voice_print。只有一段=只有身份外貌、没给指纹。
            segs = [s.strip() for s in _re.split(r"[｜|]", nc_rest) if s.strip()]
            nc_voice = segs[-1][:60] if len(segs) >= 2 else ""
            nc_desc = clip_sentence("，".join(segs[:-1]) if len(segs) >= 2 else nc_rest, 140)
            if nc_name and not npc_name_ok(nc_name):
                _audit(state, "new_char", False, nc_name, "名字不像人名（像句子片段），驳回")
                nc_name = ""
            exists = any((c.get("name") or "") == nc_name for c in _characters(content))
            if nc_name and exists:
                _audit(state, "new_char", False, nc_name, "已有同名角色，不重复登场")
            if nc_name and not exists:
                nc_id = f"gen_{_uuid.uuid4().hex[:8]}"
                emergent_ids.add(nc_id)
                growth_mod.note_mint(state)   # 🌱 出生也吃生长额度 (双通道共享)
                (content.get("story") or {}).setdefault("characters", []).append({
                    "id": nc_id,
                    "name": nc_name,
                    "role": nc_desc[:24] or "新登场的人物",
                    "persona_text": nc_desc,
                    "voice_print": nc_voice[:60],
                    "relation_default": "stranger",
                    "home_location_id": state.get("location_id"),
                    "generated": True,
                })
                flags["content_mutated"] = True
                flags["gen_count"] += 1
                # id 随行: 首次登场的 toast 上给玩家一个当场改名的机会 (Yi: 名字乱)
                moments.append({"kind": "arrival", "name": nc_name, "id": nc_id})
        # 🕸 NPC↔NPC shifts: the scene moved two characters closer/apart (≤2 a turn,
        # both must be living and present, never the player — engine-enforced)
        for sh in (directed.get("npc_shifts") or [])[:2]:
            applied_sh = apply_npc_shift(content, state, sh.get("a"), sh.get("b"),
                                         sh.get("delta"), sh.get("why", ""), old_act)
            if applied_sh:
                moments.append({"kind": "npc_rel", **applied_sh})
        # 🎖 IDENTITY: the player's role/standing changed for real
        idt = (directed.get("identity") or "").strip()
        if idt and not observer and idt != (state.get("identity") or ""):
            state["identity"] = idt
            log = list(state.get("identity_log") or [])
            log.append({"act": old_act, "text": idt})
            state["identity_log"] = log
            moments.append({"kind": "identity", "text": idt})
        # 🛠 CRAFT: the player made something with their own materials — every
        # material must be in the pocket; a failed fate roll voids the attempt
        # ⚡ 主拍自带的建议 chips (提速: 免掉独立小调用)
        if is_primary:
            flags["dir_ran"] = True   # 主拍在场证明: world_seed 结算凭它区分「真填无」与「没问过」
        if is_primary and directed.get("suggestions"):
            # 🧩 走 as_str_list: 模型把它写成字符串时, 裸迭代会逐字符炸开 (Yi 实弹)
            _sg_items = [s[:48] for s in as_str_list(directed["suggestions"])]
            if lang_of(content) == "en":
                # 🌐 合同护栏 (GH 实弹 2026-08-01: 英文本子建议 chips 冒中文): _lang_rule
                # 白纸黑字管着 suggestions, 模型随机违约 → 含中文的建议整条丢弃走兜底,
                # 宁缺勿错 (兜底 ensure_three_suggestions 有确定性货)
                _sg_items = [s for s in _sg_items if not re.search(r"[一-鿿]", s)]
            # 🎭 视角护栏 (Yi 实弹 2026-08-02 二犯): 建议是玩家的下一步; 「你…」开头
            # 是角色劝玩家的口气 = 视角串了, 在垫底之前丢掉, 缺口由确定性货补齐
            _sg_items = [s for s in _sg_items
                         if not re.match(r"^(你|請你|请你|You\b|Your\b)", s, re.IGNORECASE)]
            flags["dir_suggestions"] = _sg_items[:2]
        # 🐲 生物命中报审 → 引擎按骰面裁决入账 (血阶联动在函数里)
        _crh = (directed.get("creature_hit") or "").strip()
        if _crh and not observer:
            _crev = apply_creature_hit(content, state, _crh, dice)
            if _crev:
                moments.append(_crev)
        cr = (directed.get("crafted") or "").strip()
        if cr and dice and dice.get("outcome") in ("fail", "crit_fail"):
            _audit(state, "item.crafted", False, cr.partition("|")[0], "命运判定失败，制作作废")
        if cr and not observer \
                and not (dice and dice.get("outcome") in ("fail", "crit_fail")):
            cr_name, _, cr_mats = cr.partition("|")
            mats = [m.strip() for m in _re_split_mats(cr_mats) if m.strip()]
            inv = state.get("inventory") or []
            if cr_name.strip() and mats and all(_inv_find(inv, m) >= 0 for m in mats):
                used = [(_inv_remove(state, m) or {}).get("name") for m in mats]
                _inv_add(state, cr_name.strip(), "用" + "、".join(u for u in used if u) + "做的")
                moments.append({"kind": "item", "verb": "crafted", "name": cr_name.strip()})
            else:
                _audit(state, "item.crafted", False, cr_name.strip(),
                       "材料不在身上（或未报材料），引擎不凭空造物")
        # ✊ SNATCH: the player took something off a character BY FORCE — only a
        # successful fate roll (or an unresisted grab) makes it stick; the victim
        # remembers, the relationship pays, the story's pressure feels the noise
        tk = (directed.get("taken") or "").strip()
        if tk and dice and dice.get("outcome") in ("fail", "crit_fail"):
            _audit(state, "item.taken", False, tk.partition("|")[0], "命运判定失败，没抢到")
        if tk and not observer \
                and not (dice and dice.get("outcome") in ("fail", "crit_fail")):
            tk_item, _, tk_who = tk.partition("|")
            victim_t = next((c for c in scene_characters(content, state)
                             if c.get("id") != pcid and c.get("name")
                             and (c["name"] in tk_who or tk_who.strip() in c["name"])), None)
            if not victim_t:
                _audit(state, "item.taken", False, tk_item.strip(), "被抢的人不在场")
            if victim_t:
                their = char_items(content, state, victim_t["id"])
                ti = _inv_find(their, tk_item.strip())
                if ti < 0:
                    _audit(state, "item.taken", False, tk_item.strip(),
                           f"{victim_t.get('name')}身上没有这件东西")
                if ti >= 0:
                    it = their.pop(ti)
                    _inv_add(state, it.get("name", ""), it.get("detail", ""))
                    vid = victim_t["id"]
                    old_s = rel_all.get(vid) or relationships.new_scores()
                    rel_all[vid] = relationships.apply_deltas(old_s, -8, 0, tun)
                    rel_log(state, vid, old_act, "hurt",
                            _t(content, f"你从TA手里抢走了{it.get('name')}。TA记住了。",
                               f"You snatched the {it.get('name')} from them. They remember."))
                    moments.append({"kind": "item", "verb": "taken",
                                    "name": it.get("name"), "from": victim_t.get("name")})
                    if pcfg:
                        state["pressure"] = min(99, int(state.get("pressure", 0)) + 8)
        # 🔁 TRADE: a struck bargain — both sides must actually hold their ends
        tr = (directed.get("trade") or "").strip()
        if tr and not observer and sp_id:
            parts = tr.split("|")
            if len(parts) >= 2:
                give_n, get_n = parts[0].strip(), parts[1].strip()
                their = char_items(content, state, sp_id)
                gi = _inv_find(state.get("inventory") or [], give_n)
                ti = _inv_find(their, get_n)
                if gi < 0 or ti < 0:
                    _audit(state, "item.traded", False, f"{give_n}↔{get_n}",
                           "你没有这件筹码" if gi < 0 else "对方拿不出那件东西")
                if gi >= 0 and ti >= 0:
                    mine = _inv_remove(state, give_n)
                    theirs = their.pop(ti)
                    their.append(mine)
                    _inv_add(state, theirs.get("name", ""), theirs.get("detail", ""))
                    old_s = rel_all.get(sp_id) or relationships.new_scores()
                    rel_all[sp_id] = relationships.apply_deltas(old_s, 2, 0, tun)
                    rel_log(state, sp_id, old_act, "gift",
                            _t(content, f"你用{mine.get('name')}换了TA的{theirs.get('name')}。",
                               f"You traded your {mine.get('name')} for their {theirs.get('name')}."))
                    moments.append({"kind": "item", "verb": "traded",
                                    "name": theirs.get("name"), "gave": mine.get("name")})
        # 🎁 GIFT: the player handed the speaker something of theirs — the receiver
        # decided (in character) whether to take it and how it landed; kept gifts
        # become keepsakes they carry and remember
        g_raw = (directed.get("gift") or "").strip()
        if g_raw and not observer and sp_id:
            g_item, _, g_rest = g_raw.partition("|")
            g_taken = "拒" not in g_rest
            g_liked = "喜" in g_rest
            if _inv_find(state.get("inventory") or [], g_item.strip()) < 0:
                _audit(state, "gift", False, g_item.strip(), "你身上没有这件东西，送不出去")
            if _inv_find(state.get("inventory") or [], g_item.strip()) >= 0:
                if g_taken:
                    it = _inv_remove(state, g_item.strip())
                    ks = _sim(state, sp_id).setdefault("keepsakes", [])
                    ks.append({"name": it.get("name"), "at": _time_index(state)})
                    del ks[:-8]
                    old_g = rel_all.get(sp_id) or relationships.new_scores()
                    g_mode = relationships.derive_mode(sp, old_g, tun)
                    rel_all[sp_id] = relationships.apply_deltas(
                        old_g, 4 if g_liked else 1,
                        (2 if g_mode in ("flirt", "lover") else 0) if g_liked else 0, tun)
                    rel_log(state, sp_id, old_act, "gift",
                            _t(content, f"你把{it.get('name')}送给了TA{'，TA很喜欢' if g_liked else ''}。",
                               f"You gave them the {it.get('name')}{' and they loved it' if g_liked else ''}."))
                    moments.append({"kind": "gift", "name": sp_name,
                                    "item": it.get("name"), "liked": g_liked})
                else:
                    rel_log(state, sp_id, old_act, "gift",
                            _t(content, f"你想把{g_item.strip()}送给TA，被TA推回来了。",
                               f"You offered the {g_item.strip()}; they pushed it back."))
        # 💰 MONEY: judged payments/earnings hit a HARD ledger — spending clamps
        # at the balance, every booking is logged with its reason and hour
        md = (directed.get("money_delta") or "").strip()
        if md and not observer and economy_on(state):
            amt_s, _, m_why = md.partition("|")
            applied = book_money(content, state, _to_int(amt_s, -9999, 9999), m_why)
            if not applied:
                _audit(state, "money", False, md, "没有入账（余额不足或金额无效）")
            if applied:
                moments.append({"kind": "money", "delta": applied,
                                "why": (m_why or "").strip()[:30],
                                "balance": state["money"]})
        # 📋 QUEST accepted: a paid errand agreed to in dialogue, booked with a
        # REAL deadline (real-time sandbox: N days literally means N days)
        qa = (directed.get("quest_accepted") or "").strip()
        if qa and not observer:
            q_parts = qa.split("|")
            q_title = q_parts[0].strip()[:30]
            q_reward = _to_int(q_parts[1], 0, 9999) if len(q_parts) > 1 else 0
            q_days = _to_int(q_parts[2], 0, 30) if len(q_parts) > 2 else 0
            open_qs = [q for q in (state.get("quests") or []) if q.get("status") == "open"]
            if q_title and len(open_qs) < 4 and \
                    all(logic._norm(q.get("title", "")) != logic._norm(q_title) for q in open_qs):
                import uuid as _uuid_q
                day_now_q = int((state.get("clock") or {}).get("day", 1) or 1)
                quests = list(state.get("quests") or [])
                quests.append({"id": f"q_{_uuid_q.uuid4().hex[:6]}", "title": q_title,
                               "reward": q_reward, "giver": sp_name, "status": "open",
                               "kind": "job" if q_reward else "lead",  # 🧭 无酬=线索任务
                               "deadline_day": (day_now_q + q_days) if q_days else None})
                state["quests"] = _trim_ledger(quests)
                moments.append({"kind": "quest", "status": "open", "title": q_title,
                                "reward": q_reward, "days": q_days})
                yield emit({"type": "description", "speaker_name": None,
                            "text": (f"（你应下了这桩事：{q_title}。"
                                     f"讲好的酬劳是{q_reward}{currency_of(content)}。"
                                     if q_reward else
                                     f"（你把这个目标记在了心里：{q_title}。")
                                    + (f"限{q_days}天之内。" if q_days else "") + "）"})
        # 📋 QUEST delivered: the errand is done for real — the reward pays out
        qd = (directed.get("quest_done") or "").strip()
        if qd and not observer:
            for q in (state.get("quests") or []):
                if q.get("status") == "open" and (
                        logic._norm(q.get("title", "")) in logic._norm(qd)
                        or logic._norm(qd) in logic._norm(q.get("title", ""))):
                    q["status"] = "done"
                    q_pay = book_money(content, state, int(q.get("reward") or 0),
                                       q.get("title", "")) if q.get("reward") else 0
                    moments.append({"kind": "quest", "status": "done",
                                    "title": q.get("title"), "reward": q_pay})
                    if q_pay:
                        moments.append({"kind": "money", "delta": q_pay,
                                        "why": q.get("title", ""),
                                        "balance": state["money"]})
                    yield emit({"type": "description", "speaker_name": None,
                                "text": f"（{q.get('title')}，办成了。"
                                        + (f"{q_pay}{currency_of(content)}的酬劳落进了口袋。"
                                           if q_pay else "") + "）"})
                    break
        # 🌍 场面事实账本: a judged PERSISTENT physical change to this place gets
        # booked and served back forever (the smashed door stays smashed) — the
        # world's memory is engine-owned, not vibes
        wf = (directed.get("world_fact") or "").strip()[:60]
        if wf and not observer and state.get("location_id"):
            pf = dict(state.get("place_facts") or {})
            lst = list(pf.get(state["location_id"]) or [])
            if all(logic._norm(x.get("text", "")) != logic._norm(wf) for x in lst):
                lst.append({"text": wf,
                            "label": (clock_view(content, state) or {}).get("label", "")})
                pf[state["location_id"]] = lst[-6:]
                state["place_facts"] = pf
                moments.append({"kind": "world", "text": wf})
        # 🎒 ITEMS: gained / lost / stashed at the current place
        if not observer:
            g = (directed.get("gained") or "").strip()
            if g:
                # 🎒 申报制铸卡 (P0/P3): 世界首现的新物, 物性+效果随申报一次产出
                # (item_new「重量|体积|手|材质|可燃|外观|效果段|c|uses」) → minted 卡;
                # 没申报的走 rule_card 保守默认 (backfilled)。已有档内卡永不覆盖。
                _decl = (directed.get("new_item") or "").strip()
                if _decl:
                    _, _dd = items_mod.decl_from_pipes(_decl)
                    for _x in items_mod.parse_effects(_dd.get("effects_raw") or "")[1]:
                        _audit(state, "item.effect", False, _x,
                               "枚举外或账本未立，夹逼成无效果")
                    items_mod.ensure_template(state, g, items_mod.card_from_decl(g, _dd))
                # ⚖️ 判定渗出 (第3题②): 拿得起吗 — 失败叙事点名肇因属性, 不是黑箱
                _card = items_mod.card_of(state, g)
                _ok, _why = items_mod.lift_check(_card, _player_strength(state))
                if not _ok:
                    _audit(state, "item.gained", False, g, _why)
                elif _inv_add(state, g):
                    moments.append({"kind": "item", "verb": "gained", "name": g})
                else:
                    _audit(state, "item.gained", False, g, "已在身上，不重复入包")
            l = (directed.get("lost") or "").strip()
            if l:
                _li = _inv_find(state.get("inventory") or [], l)
                _lrow = (state.get("inventory") or [])[_li] if _li >= 0 else None
                _lcard = items_mod.card_of(state, _lrow) if _lrow else {}
                if (_lrow is not None and _lcard.get("consumable")
                        and items_mod.live_effects(_lcard)):
                    # 🧴 lost 封口 (P3 §2.6): 带效果的消耗品报 lost 十有八九是"用掉" —
                    # 驳回改道 item_used (真丢弃的罕见误伤在 audit 里可见)
                    _audit(state, "item.lost", False, l,
                           "消耗走 item_used——lost 只用于遗失/被夺/丢弃")
                elif _lrow is not None and {k: v for k, v in (_lrow.get("indiv") or {}).items()
                                            if str(v or "").strip()}:
                    # 🔥 有籍件 (线索/铭文在身) 不许经 lost 悄悄消失 —
                    # 销毁走 item_transformed 的毁证显式确认 (P3 §3.4)
                    _audit(state, "item.lost", False, l,
                           "此物上系有线索——销毁走 item_transformed 显式确认")
                else:
                    it = _inv_remove(state, l)
                    if it:
                        moments.append({"kind": "item", "verb": "lost", "name": it.get("name")})
                    else:
                        _audit(state, "item.lost", False, l, "身上没有这件东西，不能凭空失去")
                        # 🎒 隔离区喂料: 模型笃定存在却不在册的名字 — 监控指标, 不铸造
                        items_mod.quarantine(state, l, "judged.lost",
                                             int((state.get("clock") or {}).get("day", 1) or 1))
            st_ref = (directed.get("stashed") or "").strip()
            if st_ref and state.get("location_id"):   # never remove without a shelf
                it = _inv_remove(state, st_ref)
                if not it:
                    _audit(state, "item.stashed", False, st_ref, "身上没有这件东西")
                    items_mod.quarantine(state, st_ref, "judged.stashed",
                                         int((state.get("clock") or {}).get("day", 1) or 1))
                if it:
                    stashes = dict(state.get("stashes") or {})
                    stashes.setdefault(state["location_id"], []).append(it)
                    state["stashes"] = stashes
                    moments.append({"kind": "item", "verb": "stashed", "name": it.get("name")})
            # 🎒 场景物申报 (实体化 P1): 导演特写的新物件入册 — 从此有籍可查,
            # 玩家伸手拿它不再是幽灵 (accept_item 的场景源)。每拍≤3, 每地上限内轮换。
            # 防复活查重 = inventory ∪ stashes ∪ char_items (P3 §5): 已在任何账本里的
            # 同名物 → 申报按过期幻觉驳回 (收进柜子的灯笼也不许被重报出场)
            _sp = (directed.get("stage_props") or "").strip()
            if _sp and state.get("location_id"):
                for _n in [x.strip(" 。，,.") for x in _re_split_mats(_sp)][:3]:
                    if not _n:
                        continue
                    if _item_known_anywhere(state, _n):
                        _audit(state, "prop.staged", False, _n, "已在账本上——重复申报不复活")
                    elif items_mod.scene_add(state, state["location_id"], _n):
                        _audit(state, "prop.staged", True, _n)
            # 🧴 item_used (P3 §2): 使用走报审, 效果引擎落账, 消耗归卡与成败解耦。
            # 效果孪生拍就地 yield — 点名肇因是不变式, 不靠模型自觉 (实现偏差④)。
            _used = (directed.get("used") or "").strip()
            if _used:
                _day3 = int((state.get("clock") or {}).get("day", 1) or 1)
                _up = [x.strip() for x in _used.split("|")]
                _uname = _up[0]
                _utgt = _up[1] if len(_up) > 1 and _up[1] else "self"
                _urow = items_mod.find_usable(state, _uname)   # 先用开封的那件
                if _urow is None:
                    _audit(state, "item.used", False, _uname, "身上没有此物")
                    items_mod.quarantine(state, _uname, "judged.used", _day3)
                else:
                    _ucard = items_mod.card_of(state, _urow)
                    _effs = items_mod.live_effects(_ucard)
                    if not _effs:
                        _audit(state, "item.used", False, _uname,
                               "此物无可用之效")   # 驳回但允许正文描写徒劳动作
                    else:
                        _texts = [
                            _apply_item_effect(content, state, _e, _utgt,
                                               _urow.get("name", _uname), moments)
                            for _e in _effs]
                        _spent = items_mod.consume_one_use(state, _urow)
                        if _spent == "destroyed":
                            _texts.append(f"（{_urow.get('name', _uname)}用尽了。）")
                        _audit(state, "item.used", True, f"{_uname}[{_spent}]",
                               str(_up[2] if len(_up) > 2 else "")[:24])
                        moments.append({"kind": "item", "verb": "used",
                                        "name": _urow.get("name", _uname)})
                        for _t3 in _texts:
                            if _t3:
                                yield emit({"type": "description",
                                            "speaker_name": None, "text": _t3})
            # 🔥 item_transformed (P3 §3): 一笔原子交换 — 销 n 铸 m 同拍落账,
            # 不许拆 lost+gained (拆开漏报一半=幽灵)。物理必然, 不过骰。
            _tr = directed.get("transformed") or {}
            if isinstance(_tr, dict) and (_tr.get("inputs") or _tr.get("outputs")):
                _day4 = int((state.get("clock") or {}).get("day", 1) or 1)
                _ins = [str(x).strip() for x in (_tr.get("inputs") or [])
                        if str(x).strip()][:3]
                _outs_raw = [str(x).strip() for x in (_tr.get("outputs") or [])
                             if str(x).strip()][:3]
                _rows = state.get("inventory") or []
                _src, _bad = [], ""
                for _n in _ins:
                    _i = _inv_find(_rows, _n)
                    if _i < 0:
                        _bad = _n
                        break
                    _src.append(_rows[_i])
                if _bad or not _ins or not _outs_raw:
                    _audit(state, "item.transformed", False, _bad or "（空单）",
                           "材料不在身上" if _bad else "投入产出必须一笔报全")
                    if _bad:
                        items_mod.quarantine(state, _bad, "judged.transformed", _day4)
                else:
                    # 有籍件销毁 = 毁证, 须显式确认 (P3 §3.4 — 世界记得玩家毁证)
                    _clues = [r for r in _src
                              if {k: v for k, v in (r.get("indiv") or {}).items()
                                  if str(v or "").strip()}]
                    if _clues and not _tr.get("destroys_clues"):
                        _audit(state, "item.transformed", False,
                               _clues[0].get("name", ""), "此物上系有线索，销毁须显式确认")
                    else:
                        for _r in _clues:
                            _de = list(state.get("destroyed_evidence") or [])
                            _de.append({"name": _r.get("name"),
                                        "indiv": dict(_r.get("indiv") or {}),
                                        "day": _day4,
                                        "method": str(_tr.get("method") or "")[:30]})
                            state["destroyed_evidence"] = _de
                        # 原子落账: 全验已过, 先销后铸
                        for _r in _src:
                            if _r.get("iid"):
                                _rows2 = list(state.get("inventory") or [])
                                if _r in _rows2:
                                    _rows2.remove(_r)
                                    state["inventory"] = _rows2
                            else:
                                items_mod.take_stack(state, _r.get("name", ""), 1)
                        _made = []
                        for _o in _outs_raw:
                            if "|" in _o:   # 内联申报 — 走现有铸卡口, 不新增出生入口
                                _nm, _dd2 = items_mod.decl_from_pipes(_o, with_name=True)
                                if not _nm:
                                    continue
                                for _x in items_mod.parse_effects(
                                        _dd2.get("effects_raw") or "")[1]:
                                    _audit(state, "item.effect", False, _x,
                                           "枚举外或账本未立，夹逼成无效果")
                                items_mod.ensure_template(
                                    state, _nm, items_mod.card_from_decl(_nm, _dd2))
                                items_mod.add_stack(state, _nm, 1)
                                _made.append(_nm)
                            else:
                                _m = re.match(r"^(.+?)[×xX*](\d+)$", _o)
                                _nm, _q = ((_m.group(1).strip(), int(_m.group(2)))
                                           if _m else (_o, 1))
                                items_mod.add_stack(state, _nm, max(1, min(9, _q)))
                                _made.append(f"{_nm}×{_q}" if _q > 1 else _nm)
                        _audit(state, "item.transformed", True,
                               f"{'、'.join(_ins)}→{'、'.join(_made)}",
                               str(_tr.get("method") or "")[:24])
                        moments.append({"kind": "item", "verb": "transformed",
                                        "name": "、".join(_made)})
                        yield emit({"type": "description", "speaker_name": None,
                                    "text": _t(content,
                                               f"（{'、'.join(_ins)}化作了{'、'.join(_made)}。）",
                                               f"(The {'、'.join(_ins)} became "
                                               f"{'、'.join(_made)}.)")})


def _emit_twin_beats(content, moments, emit, moved, arrival_discoveries,
                     retrieved, stashed_now, accepted, found_props, examined=()):
    """管线 P6 · 确定性旁白: the deterministic twins' narration beats — the move and
    its arrival discoveries, retrieved/stashed/accepted/examined items, searched
    evidence — all land BEFORE anyone speaks. First phase physically extracted (刀1)."""
    for nm, desc in examined:
        # 🔍 主动查验 (第3题③): 物性用世界的语言说出来, 不是数字标签
        yield emit({"type": "description", "speaker_name": None,
                    "text": _t(content, f"（你掂量着{nm}：{desc}。）",
                               f"(You look the {nm} over: {desc}.)")})
    if moved:
        yield emit({"type": "description", "speaker_name": None,
                    "text": _t(content, f"（你动身去了{moved.get('name','')}。）",
                               f"(You make your way to {moved.get('name','')}.)")})
        for d in arrival_discoveries:
            if d.get("text"):
                yield emit({"type": "description", "speaker_name": None, "text": d["text"]})
    for it in retrieved:
        yield emit({"type": "description", "speaker_name": None,
                    "text": _t(content, f"（你取回了之前放在这里的{it.get('name','')}。）",
                               f"(You retrieve the {it.get('name','')} you left here.)")})
    for it in stashed_now:
        moments.append({"kind": "item", "verb": "stashed", "name": it.get("name")})
        yield emit({"type": "description", "speaker_name": None,
                    "text": _t(content,
                               f"（你把{it.get('name','')}收放在了这里。想用时回到这里说一声取回。）",
                               f"(You stash the {it.get('name','')} here. Come back and ask "
                               "for it when you need it.)")})
    for it in accepted:
        moments.append({"kind": "item", "verb": "gained", "name": it.get("name")})
        yield emit({"type": "description", "speaker_name": None,
                    "text": _t(content, f"（{it.get('name','')}到手了，已收进背包。）",
                               f"(The {it.get('name','')} is yours — tucked into your bag.)")})

    # searching paid off → narrate the physical evidence BEFORE anyone reacts to it
    for pf in found_props:
        body = _fragment_content(content, pf.get("fragment_id"))
        if body:
            yield emit({"type": "description", "speaker_name": None,
                        "text": _t(content, f"（你翻查{pf['name']}：{body}）",
                                   f"(You search the {pf['name']}: {body})")})
        elif pf.get("detail"):
            yield emit({"type": "description", "speaker_name": None,
                        "text": _t(content, f"（你翻查{pf['name']}：{pf['detail']}）",
                                   f"(You search the {pf['name']}: {pf['detail']})")})
        else:
            yield emit({"type": "description", "speaker_name": None,
                        "text": _t(content, f"（你翻查了{pf['name']}，没有发现特别的东西。）",
                                   f"(You search the {pf['name']} and find nothing unusual.)")})


def run_turn_stream(
    content: dict[str, Any],
    state: dict[str, Any],
    persona: dict[str, Any],
    player_input: str,
    channel: str = "say",
    llm: LLM | None = None,
    history: list[dict[str, str]] | None = None,
    target_character_id: str | None = None,
    beat_log: list[dict[str, Any]] | None = None,
    returning: bool = False,
    away_hours: float = 0.0,
):
    """Advance one turn as a GENERATOR. Yields ('beat', beat) for each beat the moment
    it's computed (so responders stream out one by one), then a final ('final', result)
    carrying state/scene/suggestions/ending/cast/goal. Pure w.r.t. DB.

    ━━ 回合管线 (the turn pipeline — banners below mark each phase) ━━
      P0 归一与时钟      state defaults, location normalize, real-clock sync, ghost gate
      P1 感知           keyword probes → asks, event triggers (provisional, reconciled in P7)
      P2 确定性孪生      audit reset; move / seek(may end the turn) / props / stash / accept
      P3 行动解算        verb class → tier → DC → d20 (power invocations never roll)
      P4 解锁与问候      five-condition gating, threshold moments, comeback pulse
      P5 选角与脚手架    responder pick, promise-kept, persona, stuck, intent digest, emit()
      P6 确定性旁白      the twins' narration beats land before anyone speaks
      P7 导演循环        per speaker: gated prompt → generate → guards → settle its events
      P8 场后结算        golden moment, observe/think, world pulse, affinity → act advance
      P9 世界翻页        new places, slot roll + offscreen, arrivals/exits, phone, endings,
                        memory, final assembly
    Invariants live in docs/engine-logic.md; each phase's rejections land on the audit
    sheet. Extraction into module-level phase functions is staged (刀2+): P6 done."""
    llm = lang_llm(llm or get_llm(), content)
    state = {**default_state(), **(state or {})}
    # 🎒 懒迁移 (物品实体化 P0): 旧档物品行在被加载的这一刻补籍, 幂等零感知
    items_mod.migrate_state(state)
    # ⚡ 上一回合后台折好的记忆/场记先合账 (4秒军令: 两者都出关键路径, 迟一回合
    # 入账; audit 在 P2 才重置, 这里不记账)
    apply_pending_folds(state)
    apply_pending_track(state)
    apply_pending_reads(state)   # 🫂 后台判好的「TA 此刻怎么看你」也在这里合账
    # 💞 全局回合序号 (事件记账制的冷却时钟 — turns_in_act 换幕会清零, 不能用)
    state["turn_seq"] = int(state.get("turn_seq") or 0) + 1
    old_act = int(state.get("act", 1))
    # 🌅 日翻页哨兵 (Yi: 每天要给玩家自由活动的时间) — 回合末对账, 翻了天就发自由活动菜单
    _day0 = int((state.get("clock") or {}).get("day", 1) or 1)
    _loc0 = state.get("location_id")   # 🧭 回合起点位置 (文实合一兜底的比对基准)
    # 🩹 回合初就钉着 AWAY 的名单 (自愈只治历史粘钉; 本回合新离场的人不许被告别台词复活)
    _away0 = {k for k, v in (state.get("char_pins") or {}).items() if v == AWAY}
    # normalize the player's position to the EFFECTIVE location (unset → first authored)
    # so the location gating dimension always sees where they truly stand
    state["location_id"] = (current_location(content, state) or {}).get("id")
    tun = tuning_for(content)
    # ⏰ 现实同步: the real hour walks in with the player; a turned hour narrates below
    real_slot_turned = None
    if real_time_on(content):
        prev_rt = (int((state.get("clock") or {}).get("day", 1) or 1),
                   int((state.get("clock") or {}).get("slot", 0) or 0))
        cv_rt = sync_real_clock(content, state)
        if state.get("real_seen") and cv_rt \
                and prev_rt != (state["clock"]["day"], state["clock"]["slot"]):
            real_slot_turned = cv_rt
        # 🌊 世界自转: every real day the player stayed away, the world made news
        if state.get("real_seen") and sandbox_on(content):
            days_gone = int(state["clock"]["day"]) - int(prev_rt[0])
            if days_gone > 0:
                mint_world_news(content, state, llm, days_gone)
        state["real_seen"] = True
    # 💀 the dead have neither voice nor hands: 说/做 are refused; watching remains
    ghost = sandbox_on(content) and (state.get("player_hp") == "dead")
    if ghost and channel in ("say", "do"):
        yield ("beat", dedash_beat({
            "type": "description", "speaker_name": None,
            "text": "（你已经死了。喉咙发不出声，手也穿不过任何东西。你所能做的，只剩下看。）"}))
        channel = "think"
    _ensure_npc_rel(content, state)  # 🕸 authored ties come alive on first touch
    # 🎯 五维属性: minted lazily on the first sandbox turn (existing runs pick them up)
    if sandbox_on(content) and not state.get("attrs") \
            and (state.get("mode") or "character") != "god":
        ensure_player_attrs(content, state, persona, llm)
    # who stands in the scene as the turn OPENS — the closing diff narrates arrivals/exits
    here_before = {c.get("id") for c in scene_characters(content, state) if c.get("id")}
    emergent_ids: set = set()  # characters born THIS turn (their entrance is already scripted)
    all_beats: list[dict[str, Any]] = []  # accumulated for scene classification
    # snapshot which places are reachable BEFORE this turn, so we can announce any that
    # newly open up (so a new exit never just silently appears — "莫名其妙解锁" fix)
    locs_before = {l.get("id") for l in _locations(content) if location_available(content, state, l)}

    # ━━━━━━━━━━ 管线 P1 · 感知：试探与事件（暂记，P7 对账） ━━━━━━━━━━
    # 1. probing → asks counters (per secret); also note which characters are probed.
    #    Keyword hits are PROVISIONAL (they keep same-turn reveals working) — the primary
    #    director call judges what the player truly probed, and we reconcile after it.
    note_visit_tick(state)   # 🗺 热度账本: 上一回合挪过窝这里落账
    # 🌱 世界生长预算 (节奏归引擎): 本回合是否向主拍下发生长字段, 起点定死
    _ws_mode = ""
    if (state.get("mode") or "character") != "god":
        growth_mod.tick(state)
        _ws_mode = growth_mod.due(content, state, taste_mod.top(state))
        if _ws_mode:
            try:
                from .. import metrics as _gm
                _gm.log("growth", ev="due", mode=_ws_mode)
            except Exception:
                pass
    _pace = pace_band(state, tun)   # 🎼 本轮节奏带 (乐师账本→台词形状, Spec A)
    _cb_mode = "" if (state.get("mode") or "character") == "god" \
        else callback_due(state, tun, _pace["band"])   # 🪃 回调到期? (Spec E)
    # 🎁 对等回礼 (Spec G): 上一轮玩家开了窗 → 这一轮主答者欠一块同深度的自己
    _owe_disclose = bool(state.pop("owe_disclosure", None))
    if (state.get("mode") or "character") != "god" and channel in ("say", "do") \
            and _SELF_DISCLOSE_RE.search(player_input or ""):
        state["owe_disclosure"] = True
        _audit(state, "disclose.player", True, (player_input or "")[:16])
    # 📬 到期的延迟消息随回合送达。⚠️ 不挂 mode != "god" 的闸: 投递是【纯搬运】
    # (那些字是玩家点发送那一刻就写好的, 零 LLM), 挡住只会让观剧局无限攒待发,
    # 谁也不投 —— 那是个黑洞, 不是保护。
    deliver_due_phone(content, state)
    asks = dict(state.get("asks") or {})
    probed_secret_ids = _detect_asks(content, player_input)
    for sid in probed_secret_ids:
        asks[sid] = asks.get(sid, 0) + 1
    state["asks"] = asks
    provisional_asks = list(probed_secret_ids)
    sec_char = _secret_char_map(content)
    probed_char_ids = [sec_char.get(sid) for sid in probed_secret_ids if sec_char.get(sid)]

    _ev_before = set(state.get("triggered_event_ids") or [])
    _apply_event_triggers(content, state, player_input)
    provisional_events = set(state.get("triggered_event_ids") or []) - _ev_before

    # ▶ 观剧拍: the player just watches this beat — the DIRECTOR drives the plot forward.
    drive = channel == "drive"
    if drive:
        channel, player_input = "say", ""

    # ━━━━━━━━━━ 管线 P2 · 确定性孪生（移动/找人/搜证/收纳/取回/受赠） ━━━━━━━━━━
    state["last_audit"] = []   # 📋 fresh audit sheet each turn

    # 🎒 隔离区例行 (P3 §4): 过期清扫 + 满足条件的名字批量补铸转正 (origin=promoted)。
    # LLM 只在这个点击回合里跑; 补铸失败走规则表兜底不阻塞 (保守默认)。
    items_mod.quarantine_sweep(state, int((state.get("clock") or {}).get("day", 1) or 1))
    _promo = items_mod.promotable(state)[:4]
    if _promo and (state.get("mode") or "character") != "god" and channel != "think":
        _qcards: dict = {}
        try:
            _qout = llm.generate({"mint_item_cards": True, "names": _promo,
                                  "world": ((content.get("story") or {}).get("world_long")
                                            or "")[:200],
                                  "language": lang_of(content)}) or {}
            for _c in (_qout.get("cards") or []):
                if isinstance(_c, dict) and _c.get("name"):
                    _qcards[items_mod._norm(str(_c["name"]))] = _c
        except Exception:
            _qcards = {}
        for _n in _promo:
            _cd = _qcards.get(items_mod._norm(_n))
            _card = items_mod.card_from_decl(_n, _cd) if _cd else items_mod.rule_card(_n)
            _card["origin"] = "promoted"
            items_mod.ensure_template(state, _n, _card)
            if state.get("location_id"):   # 入籍位置: 当前场景 (伸手就能拿到的地方)
                items_mod.scene_add(state, state["location_id"], _n)
            items_mod.quarantine_remove(state, _n)
            _audit(state, "quarantine.promoted", True, _n)

    # ⏳ 命运不等人: a pending fate loses one grace turn per player turn; at zero the
    # engine resolves it ITSELF (random pick) — the fork cannot be shelved forever.
    # ⚖️ 默认关 (Yi 2026-07-14: 无点击不推进 — 玩家没点的选择不许系统代点); 要这口
    # 紧迫感的剧本自己开 tuning.fate_auto_resolve. 关着时岔口一直等, 宽限也不倒数.
    _pc0 = state.get("pending_choice")
    if (tun["fate_auto_resolve"] > 0 and isinstance(_pc0, dict)
            and _pc0.get("kind") == "fate" and (state.get("mode") or "character") != "god"):
        _pc0["expires"] = int(_pc0.get("expires", 3)) - 1
        if _pc0["expires"] <= 0:
            _opt = random.choice(_pc0.get("options") or [{}])
            try:
                _fres = _apply_fate(content, state, _opt.get("id"))
                _audit(state, "fate.forced", True, _fres.get("label", ""))
                yield ("beat", dedash_beat({
                    "type": "description", "speaker_name": None,
                    "text": _t(content,
                               f"（你迟迟未决。命运替你落了子：{_fres.get('label', '')}）",
                               f"(You hesitated too long. Fate moved for you: "
                               f"{_fres.get('label', '')})")}))
            except ValueError:
                state["pending_choice"] = None

    # 1b. 🚶 说走就走 FIRST: a clear "I go to X" moves the player NOW, so every twin below
    #     and the whole prompt (place anchor, roster, responders) already lives at X.
    # 🗺 TYPED_MOVE 关掉后这条整条不走: 换场只认地图面板点的那一下 (Yi 2026-08-04)。
    moved = None if (not TYPED_MOVE or (state.get("mode") or "character") == "god") else \
        player_move(content, state, player_input, channel)
    # 🤝 两步握手 (Yi 2026-08-08): 上一拍角色邀约、这一拍玩家答应 ⇒ 现在就过去。
    # 必须排在这里 —— 后面整套 (到达旁白/在场名单/建议/责任人) 都读 location_id,
    # 晚一步做就全都还在旧地点上, 而正文已经在写新地方了。
    moved = moved or take_invite(content, state, player_input, channel)
    if moved:
        _audit(state, "move", True, moved.get("name", ""))
        _enc = creature_arrival_beat(content, state)   # 🐲 走进了它的领地
        if _enc:
            yield ("beat", dedash_beat(_enc))
    arrival_discoveries = discover_on_arrival(content, state) if moved else []
    # 🏖 the player named an OFF-MAP destination in a sandbox (「去后台」, no 后台 yet):
    # surface a generate-and-go confirm chip at final — 想去哪就去哪, even somewhere new
    # 🗺 同上: 打字点名图外地点的「造一个并过去」确认条也一并取消 (要新场景请作者手加)。
    emergent_dest = None if (moved or not TYPED_MOVE) else \
        player_move_emergent(content, state, player_input, channel)
    # 🚶 玩家亲口说要走? (Yi 2026-08-08 拍板 A: 把摩擦摆到明处, 宁可生硬不许撒谎)
    # 已经真的换过场的那一拍不算 —— 那是点地图走成了, 没有摩擦可言。
    # ⚠️ 这里【不能】用 observer: 它要到一千多行之后才赋值, 提早引用会 UnboundLocalError
    #    (实弹: 258 条测试当场全红)。上帝视角本来就没有「玩家的脚」, 用 mode 判。
    _wants_move = (not moved) and (state.get("mode") or "character") != "god" \
        and player_wants_to_move(player_input, channel)

    # 🧍 姿位孪生: a plain first-person posture statement books itself (坐下就是坐下)
    if (state.get("mode") or "character") != "god":
        _pose = player_pose(state, player_input, channel)
        if _pose:
            _audit(state, "pose", True, _pose)
    # 🎥 last turn's tracker conflict rides this turn's anchor once, then clears
    track_note = str(state.pop("track_note", "") or "")
    # ⚡ 修为: offline trickle (温养), then the training / breakthrough twins
    cult_beat = None
    # 📸 moments born BEFORE the moments list exists (breakthrough/crit fire early in
    # the pipeline) — stashed here, merged in when the list is created at P4
    early_moments: list[dict[str, Any]] = []
    # 🧠 理智账本 init + the turn's opening balance (recovery only on no-net-loss turns)
    _scfg = sanity_mod.cfg(content)
    if _scfg:
        state.setdefault("sanity", _scfg["start"])
    _san0 = int(state.get("sanity", 0) or 0)
    if cult_cfg(content) and (state.get("mode") or "character") != "god":
        _og = cult_offline_gain(content, state, away_hours if returning else 0)
        if _og:
            _v0 = cult_view(content, state)
            cult_beat = _t(content,
                           f"（离开的这段时间里，你的{_v0['name']}在温养中悄然增长了{_og}%。）",
                           f"(While you were away, your {_v0['name']} quietly grew {_og}%.)")
        _tr = player_train(content, state, player_input, channel)
        if _tr and _tr.get("apt_new"):
            yield ("beat", dedash_beat({"type": "description", "speaker_name": None,
                   "text": _t(content, f"（你静心内视，测得自身资质：【{_tr['apt_new']}】。）",
                              f"(You look inward — your aptitude reveals itself: [{_tr['apt_new']}].)")}))
        if _tr and _tr.get("gain"):
            _v1 = cult_view(content, state)
            extra = ("，" + "、".join(_tr.get("why") or [])) if _tr.get("why") else ""
            cult_beat = _t(content,
                           f"（这一番修行{extra}，{_v1['name']}进度推进了{_tr['gain']}%，"
                           f"当前【{_v1['rank']}·{_v1['stage']} {_tr['prog']}%】。"
                           + ("本境瓶颈已满，可尝试突破。）" if _tr.get("full") else "）"),
                           f"(Training pushed your {_v1['name']} up {_tr['gain']}%, now "
                           f"[{_v1['rank']} {_v1['stage']} · {_tr['prog']}%].)")
        elif _tr and _tr.get("full") and not _tr.get("gain"):
            cult_beat = _t(content, "（本境瓶颈早已充盈到极限，再修无益：是时候尝试【突破】了。）",
                           "(This stage's bottleneck is already full — time to attempt a breakthrough.)")
        _bk = player_breakthrough(content, state, player_input, channel)
        if _bk is not None:
            # 📸 a breakthrough is a keepsake: every major ascension, or a 顿悟-crit
            # sub-stage — routine sub-steps stay off the shelf so the cards feel earned
            if _bk.get("success") and (_bk.get("major") or _bk.get("crit")):
                _bt = (_bk["rank_name"] + ("" if _bk.get("major")
                                           else "·" + _bk.get("stage_name", "")))
                album_add(content, state, "breakthrough",
                          _t(content, f"踏入{_bt}", f"Ascending to {_bt}"),
                          _t(content,
                             (f"天劫压顶，你在雷光中挺住，一举踏入【{_bt}】。"
                              if _bk.get("major") else
                              f"一丝顿悟入心，你稳稳踏入【{_bt}】。") + f"战力{_bk['power']}。",
                             f"You broke through into [{_bt}] — power {_bk['power']}."),
                          rarity=3 if _bk.get("major") else 2)
                early_moments.append({"kind": "breakthrough", "title": _bt})
            if _bk.get("success") and _bk.get("major"):
                cult_beat = _t(content,
                               ("（天劫轰然压顶，你在雷光中挺住了！一举踏入【" + _bk["rank_name"] +
                                "】，战力跃升至" + str(_bk["power"]) +
                                ("。此劫渡得圆满无瑕，根基远超同辈。）" if _bk.get("crit") else "。）")),
                               f"(The tribulation crashes down — you endure! You ascend to "
                               f"[{_bk['rank_name']}], power now {_bk['power']}.)")
            elif _bk.get("success"):
                cult_beat = _t(content,
                               ("（气息水到渠成，你稳稳踏入【" + _bk["rank_name"] + "·" +
                                _bk["stage_name"] + "】，战力" + str(_bk["power"]) +
                                ("，更有一丝顿悟入心。）" if _bk.get("crit") else "。）")),
                               f"(You step cleanly into [{_bk['rank_name']} {_bk['stage_name']}], "
                               f"power {_bk['power']}.)")
            elif _bk.get("not_ready"):
                cult_beat = _t(content,
                               f"（本境瓶颈尚未充盈（{_bk['prog']}%），强行冲击只会自伤。再积累些吧。）",
                               f"(The bottleneck is not full yet ({_bk['prog']}%) — forcing it would only hurt.)")
            elif _bk.get("capped"):
                cult_beat = _t(content, "（你已站在这条路已知的顶点。）",
                               "(You already stand at the known summit of this path.)")
            elif _bk.get("success") is False:
                if _bk.get("major"):
                    cult_beat = _t(content,
                                   f"（天劫反噬，你未能撑住那道雷！进度跌回{_bk['prog']}%"
                                   + ("，一口鲜血喷出，气息大乱。）" if _bk.get("harm") else "，气息大乱。）"),
                                   f"(The tribulation overwhelms you — progress falls to {_bk['prog']}%.)")
                else:
                    cult_beat = _t(content,
                                   f"（气息在关口溃散，冲击小境界失败：进度跌回{_bk['prog']}%。）",
                                   f"(The surge collapses — sub-stage breakthrough failed, progress {_bk['prog']}%.)")
    if cult_beat:
        yield ("beat", dedash_beat({"type": "description", "speaker_name": None,
                                    "text": cult_beat}))

    if cult_cfg(content) and not _TRAIN_RE.search((player_input or "")[:40]):
        _cult(state)["streak"] = 0

    # ⚖️ a standing fate mandate decays one notch per turn (fresh picks last ~8 turns)
    _md = state.get("mandate")
    if isinstance(_md, dict):
        _md["left"] = int(_md.get("left") or 0) - 1
        if _md["left"] <= 0:
            state["mandate"] = None

    # 1b². 🔎 找人: 「去找X」→ pop a confirmable "TA此刻在Y，去吗？" and STOP the turn there.
    #      The pin guarantees X is still at Y when the player arrives (作息让位于约见).
    seek = None if (moved or (state.get("mode") or "character") == "god") else \
        player_seek(content, state, player_input, channel)
    # 1b²⁺. 🔎 找一个引擎里还没有的名字 — 合同（Yi 拍板 2026-07-08）：先做一次智能检索
    #       （Tavily 落地 + 模型判断）确认这名字属不属于本世界观；属于就【当场造真】：
    #       角色入册、去处生成为一等地点、行踪钉住，走同一条「TA此刻在Y，去吗？」确认片。
    #       玩家绝不再为一个名字空转十几个回合。判定不属于才交给导演在世界观内如实否认。
    seek_minted = False
    seek_denied = False
    seek_unknown_tok = None
    if seek is None and not moved and (state.get("mode") or "character") != "god":
        seek_unknown_tok = seek_unknown(content, state, player_input, channel)
    # 🔎 SEEK_AUTO_MINT 关掉后整段不走: 名字交给导演判断, 不再由判官代拍 (Yi 2026-08-05)
    if SEEK_AUTO_MINT and seek_unknown_tok and sandbox_on(content):
        story_s = content.get("story") or {}
        try:
            scout = llm.generate({"scout_char": seek_unknown_tok,
                                  "story_title": story_s.get("title") or "",
                                  "world": (story_s.get("world_facts")
                                            or story_s.get("world_long") or ""),
                                  "cast": [c.get("name") for c in _characters(content)],
                                  "mature": bool(state.get("mature"))}) or {}
        except Exception:
            scout = {}
        if scout.get("fits"):
            minted = mint_sought_character(content, state, seek_unknown_tok, scout, llm)
            if minted:
                _audit(state, "seek.scout", True,
                       f"{seek_unknown_tok}@{(minted['loc'] or {}).get('name', '')}")
                seek, seek_minted = minted, True
                seek_unknown_tok = None   # resolved for real — no directive needed
        elif scout:
            seek_denied = True
            _audit(state, "seek.scout", False, seek_unknown_tok, "检索判定不属于本世界观")
    if seek_unknown_tok:
        _audit(state, "seek.unknown", True, seek_unknown_tok)
    if seek and seek.get("loc"):
        c_s, l_s = seek["char"], seek["loc"]
        pins = dict(state.get("char_pins") or {})
        pins[c_s["id"]] = l_s["id"]
        state["char_pins"] = pins
        _audit(state, "seek", True, f"{c_s.get('name')}@{l_s.get('name')}")
        pcid_s = state.get("player_character_id")
        mode_s = state.get("mode") or "character"
        state["goal"] = goal_top(content, state)
        yield ("beat", dedash_beat({
            "type": "description", "speaker_name": None,
            "text": _t(content, f"（你打听了一圈：{c_s.get('name')}这会儿就在{l_s.get('name')}。）",
                       f"(You ask around: {c_s.get('name')} is at {l_s.get('name')} right now.)")}))
        yield ("final", {
            "state": state, "newly_unlocked": [], "suggestions": [], "scene": None,
            "cast": cast_for(content, old_act, exclude_id=pcid_s if mode_s == "character" else None,
                             state=state),
            "here": scene_cast(content, state, exclude_id=pcid_s if mode_s == "character" else None),
            "following": list(state.get("following") or []),
            "goal": state["goal"], "progress": act_progress(content, state, old_act),
            "hint": "", "moments": [], "dice": None, "content_mutated": seek_minted,
            "pressure_view": None, "clock_view": clock_view(content, state),
            "promises": promises_view(content, state),
            "player_events": player_events_view(content, state),
            "player_notes": player_notes_view(state),
            "phone_unread": phone_total_unread(content, state),
            "verdict": verdict_view(content, state),
            "pending_choice": state.get("pending_choice"), "rel_deltas": {},
            "location": location_view(content, state),
            # 🎟 打听到人在哪【照旧告诉你】(上面那一拍旁白), 但不再给一个能走人的按钮
            # (INVITE_MOVE): 想去就自己点地图 —— 地图上本来就标着谁站在哪。
            "move_request": ({"seek": True, "to": l_s["id"], "to_name": l_s.get("name"),
                              "by_id": c_s.get("id"), "by_name": c_s.get("name")}
                             if INVITE_MOVE else None),
            "relations": relations_summary(content, state),
        })
        return
    if seek and not seek.get("loc"):
        _audit(state, "seek", False, seek["char"].get("name", ""), "AWAY/此时不可达")
        # the person exists but can't be reached this hour — say so, then play the scene on
        yield ("beat", dedash_beat({
            "type": "description", "speaker_name": None,
            "text": _t(content,
                       f"（你打听了一圈，这个时辰没人说得清{seek['char'].get('name')}在哪，"
                       "恐怕得等TA自己露面。）",
                       f"(You ask around, but no one can say where {seek['char'].get('name')} "
                       "is at this hour.)")}))

    #     现场搜查: naming a searchable prop at THIS place (做/看 channel) turns it over —
    #     physical evidence unlocks directly, its story event fires. Deterministic.
    found_props = search_props(content, state, player_input, channel)
    prop_frag_ids = [pf["fragment_id"] for pf in found_props if pf.get("fragment_id")]
    peek_tick(state)   # 📱🔍 机会稍纵即逝: 窗口每回合倒数
    carved = carve_creature(content, state, player_input, channel)   # 🐲 剥取素材入包
    for _cv in carved:
        yield ("beat", dedash_beat({"type": "description", "speaker_name": None,
            "text": _t(content, f"（你俯身剥取。{_cv['name']}×{_cv['qty']}，收进了行囊。）",
                       f"(You carve: {_cv['name']} ×{_cv['qty']}.)")}))
    peeked = peek_attempt(content, state, player_input, channel, llm)
    if peeked:
        if peeked.get("view"):
            yield ("peek", peeked["view"])   # 📱 P1 手机壳: TA的设备界面
        for _pb in peeked["beats"]:
            yield ("beat", dedash_beat(_pb))
        prop_frag_ids += [f for f in peeked["frag_ids"] if f]
        early_moments.extend(peeked.get("moments") or [])
    retrieved = retrieve_stash(content, state, player_input, channel)
    stashed_now = stash_items(content, state, player_input, channel)  # 📦 deterministic 收纳
    accepted = accept_item(content, state, player_input, channel, history)  # 🤲 受赠确定性化
    examined = examine_items(content, state, player_input, channel)  # 🔍 主动查验 (物性渗出)
    for pf in found_props:   # 🎒 a takeable prop goes straight into the pocket
        if pf.get("take"):
            _inv_add(state, pf.get("name", ""), pf.get("detail", ""))
    content_mutated = False  # set when this turn adds an emergent character

    # ━━━━━━━━━━ 管线 P3 · 行动解算（类目→难度→DC→d20） ━━━━━━━━━━
    # 1c. 🎲 fate check: a risky 做-action gets judged (tiny call) and ROLLED for real.
    #     The result is handed to the director, who must narrate accordingly — no fiat.
    #     A deterministic move is just walking — never a gamble; and invoking a declared
    #     金手指 by name NEVER rolls — the cheat power is a higher law, it just works.
    dice = None
    _pw = _power_named(state, player_input) if channel == "do" else ""
    if _pw:
        _audit(state, "power", True, _pw, "金手指动作不掷骰，必然生效")
    # 🥊 竞技合同 (Yi): 约好的较量 + 玩家喊「开始」= 骰子当场定胜负，剧情按结果推进
    # —— 说/做通道都触发，DC 按双方位阶差压上去（大魂师就是压魂士），不许再摆三拍架势
    if tun["dice"] and not moved and not _pw and channel in ("say", "do") \
            and (state.get("mode") or "character") != "god" \
            and contest_signal(player_input):
        _opp = _contest_opponent(content, state, target_character_id)
        if _opp is not None:
            _cdc = 8 + 2 * _rank_gap(content, state, _opp, llm)
            _cattrs = state.get("attrs") or {}
            _cav = max(int(_cattrs.get("力量") or 0), int(_cattrs.get("敏捷") or 0))
            if _cav:
                _cdc -= (_cav - 5) // 2
            _cdc = max(2, min(19, _cdc))
            dice = _roll_dc(_cdc)
            dice["contest"] = _opp.get("name") or ""
            _audit(state, "check", True, f"比试·vs{_opp.get('name')}(DC{_cdc})",
                   "位阶与身手已折算")
            yield ("dice", dice)
    if dice is None and channel == "do" and tun["dice"] and not moved and not _pw \
            and (state.get("mode") or "character") != "god":
        # 五层筛 [1]+[3]: the ENGINE classifies the attempt first (verb class → base
        # tier + wound/equipment modifiers). A classified action ALWAYS rolls — the
        # model no longer holds a no-roll veto over stunts.
        base = actions_mod.classify(content, state, player_input)
        risk = 100
        if base is None:
            # 🎲 只有引擎认不出的非常规尝试才请模型判险 (否则奇招永远不掷骰)
            rj = llm.generate({"risk_judge": True, "action": player_input,
                               "place": (current_location(content, state) or {}).get("name") or "",
                               # ✨ declared powers count as real capability when judging odds
                               "powers": list(state.get("powers") or []),
                               "world_facts": (content.get("story") or {}).get("world_facts") or ""}) or {}
            try:
                risk = max(0, min(100, int(rj.get("risk", 100))))
            except (TypeError, ValueError):
                risk = 100
        if base:
            # ⚡ 引擎独立定档 (提速 2026-07-22): 已分类的动作不再花一次 LLM 调用问意见 —
            # 模型原本也只能调一档, 为一档每个动作回合多付 ~1.7s 不值 (骰子归引擎)
            final = actions_mod.resolve_dc(base, None)
            dc = final["dc"]
            # ⚡ 境界碾压 at the dice: cultivation lowers the DC of physical feats — a
            # 斗皇 shrugs off what floors a 斗者. This is the mechanical teeth of rank.
            _cm = cult_action_mod(content, state, base.get("cls", ""))
            if _cm:
                dc = max(2, dc + _cm)
                final.setdefault("mods", base.get("mods") or []).append(
                    f"{cult_view(content, state)['rank']}·{cult_view(content, state)['stage']}{_cm}")
            if state.get("perk") == "instinct":   # 🌱 NG+ 直觉: fate runs warmer
                dc = max(2, dc - max(1, INSTINCT_BONUS // 5))
            _sm = sanity_mod.dc_mod(int(state.get("sanity", 999)), sanity_mod.cfg(content))
            if _sm and sanity_mod.cfg(content):   # 🧠 shaking hands miss
                dc = min(19, dc + _sm)
            dice = _roll_dc(dc)
            _audit(state, "check", True,
                   f"{base['cls']}·{final['tier']}(DC{dc})",
                   "；".join(base["mods"] + (["模型调档"] if final["adjusted"] else [])))
            yield ("dice", dice)
            # ⚡ 剧情炼化: an absorb-class attempt that SUCCEEDS feeds the ladder right
            # here — 吸收异火/炼化魔核 is cultivation, not just prose. Crit doubles;
            # a critical botch backfires into the meridians.
            if base.get("cls") == "炼化" and cult_cfg(content):
                _ab_txt = cult_absorb(content, state, (dice or {}).get("outcome") or "")
                if _ab_txt:
                    yield ("beat", dedash_beat({"type": "description", "speaker_name": None,
                                                "text": _ab_txt}))
        elif risk < 100:
            if state.get("perk") == "instinct":  # 🌱 NG+ 直觉: fate runs warmer
                risk = min(95, risk + INSTINCT_BONUS)
            dice = _roll_check(risk)
            yield ("dice", dice)

    # 📸 a natural 20 is a story you'll retell — the attempt itself goes on the shelf
    if dice and dice.get("outcome") == "crit_success":
        _cw = (f"对{dice['contest']}" if dice.get("contest") else "")
        album_add(content, state, "crit",
                  _t(content, "命运一掷·20", "A fated roll · 20"),
                  _t(content, f"骰面落定，正是二十。你{_cw}放手一搏：{player_input}",
                     f"The die lands on twenty. You went all in: {player_input}"),
                  rarity=2)
        early_moments.append({"kind": "crit"})

    # ━━━━━━━━━━ 管线 P3.5 · 🦇 猎手 (循声而猎，账本执行) ━━━━━━━━━━
    # The story's declared stalker HEARS the noise this turn made (deterministic
    # loudness), patrols or stalks on the ledger, and a catch costs for real:
    # the authored ladder (请回→打伤→濒死→死) is program-enforced. The director
    # only ever narrates AROUND the ledger (threat_line depth-anchor) — a monster
    # that lives only in prose is toothless one turn and omniscient the next.
    threat_line = ""
    threat_view = None
    threat_caught = False
    tcfg = threat_mod.cfg(content)
    _hunter = _char_by_id(content, tcfg["char_id"]) if tcfg else None
    if (tcfg and _hunter and (state.get("mode") or "character") != "god"
            and not state.get("ended") and tcfg["char_id"] not in _dead_ids(state)
            and (state.get("player_hp") or "healthy") != "dead"):
        th = state.setdefault("threat", threat_mod.default_state(tcfg))
        for _k, _v in threat_mod.default_state(tcfg).items():
            th.setdefault(_k, _v)
        th["tick"] = int(th.get("tick", 0)) + 1
        _adj = threat_mod.neighbors(content)
        _ploc = state.get("location_id")
        _hname = _hunter.get("name") or ""
        _zh = lang_of(content) != "en"
        _ncls = ((actions_mod.classify(content, state, player_input) or {}).get("cls", "")
                 if channel == "do" else "")
        noise = (0 if channel == "think" else
                 threat_mod.noise_of(player_input, channel, _ncls,
                                     (dice or {}).get("outcome") or "", tcfg["senses"]))
        attacking = bool(channel == "do" and _ncls == "强攻" and _hname
                         and _hname in (player_input or ""))
        # talking TO the hunter is a scene, not a stimulus — but ATTACKING it is
        addressed = (not attacking) and bool(target_character_id == tcfg["char_id"]
                                             or (_hname and _hname in (player_input or "")))
        old_band = th.get("band") or "far"
        struck_this_turn = False
        # 🎬 张弛导演: sustained menace forces a backstage breather — 恐怖是波浪不是墙
        if th.get("away", 0) <= 0 and int(th.get("menace", 0)) >= threat_mod.MENACE_HIGH:
            th["away"] = 3 + _rng.randint(0, 2)
            th["menace"] = 0
            th["alert"] = 0
            th["pos"] = threat_mod.far_stop(_adj, tcfg, _ploc)
            _audit(state, "threat.director", True, "backstage", f"{th['away']}回合")
            yield ("beat", dedash_beat({"type": "description", "speaker_name": None,
                   "text": _t(content,
                              "不知是楼里哪儿的动静把TA引开了——那份压在你后颈上的存在感松开，"
                              "越来越远。楼安静下来。安静得让你明白：这份安静，迟早要还。",
                              "Something elsewhere draws it away — the presence on the back of "
                              "your neck lets go, further and further. The building goes quiet. "
                              "Quiet enough that you know it will have to be paid back.")}))
        if noise >= 2:
            th["alert"] = min(3, int(th["alert"]) + (2 if noise >= 3 else 1))
            _audit(state, "threat.alert", True, f"噪音{noise}", f"警觉{th['alert']}")
            if pressure_cfg(content):   # sloppiness feeds the story's pressure meter
                state["pressure"] = min(99, int(state.get("pressure", 0)) + 3 * noise)
        elif noise == 0:
            th["alert"] = max(0, int(th["alert"]) - 1)
        if th.get("away", 0) > 0:
            # backstage: genuinely elsewhere — but a BLATANT noise cuts the break short
            if noise >= 3:
                th["away"] = 0
                th["alert"] = max(int(th["alert"]), 2)
                _audit(state, "threat.director", True, "recall", "巨响截断了喘息")
            else:
                th["away"] = int(th["away"]) - 1
        band, cue = "far", ""
        if th.get("away", 0) <= 0:
            # feet: hunting (alert≥2) walks TOWARD the player, one door per turn;
            # otherwise the authored beat. Squeeze-spaces stop it at the mouth.
            if th["alert"] >= 2 and _ploc:
                th["pos"] = threat_mod.step_toward(_adj, th["pos"], _ploc, tcfg["cannot_enter"])
            else:
                th["pos"] = threat_mod.step_patrol(tcfg, th["pos"])
            band = threat_mod.band_of(_adj, th["pos"], _ploc)
            cue = threat_mod.cue_line(tcfg, band, th["tick"], _zh)
        th["band"] = band
        can_touch = band == "here" and _ploc and _ploc not in tcfg["cannot_enter"]
        if can_touch and not addressed and (th["alert"] >= 2 or noise >= 2 or attacking):
            # 遭遇: hide or be caught — 敏捷 helps, alert hurts, a hiding spot it has
            # LEARNED hurts more, and attacking the unfightable is handing yourself over
            _ag = int((state.get("attrs") or {}).get("敏捷") or 5)
            _hdc = max(2, min(19, 6 + 3 * int(th["alert"]) - (_ag - 5) // 2))
            _hw = threat_mod.hide_word_of(player_input)
            _known = int((th.get("hides") or {}).get(_hw, 0)) if _hw else 0
            if _known >= 2:
                _hdc = min(19, _hdc + min(4, 2 * (_known - 1)))
                _audit(state, "threat.learned", True, _hw, f"这一手TA已见过{_known}次")
            _unf = bool(attacking and tcfg.get("unfightable"))
            if _unf:
                _hdc = 19   # and a mixed roll won't save you either (下面降档)
                _audit(state, "threat.unfightable", True, _hname, "攻击它等于把自己递过去")
            _hdc = min(19, _hdc + sanity_mod.dc_mod(int(state.get("sanity", 999)),
                                                     sanity_mod.cfg(content)))
            hdice = _roll_dc(_hdc)
            hdice["contest"] = _hname
            yield ("dice", hdice)
            _audit(state, "threat.check", True, f"遭遇·{_hname}(DC{_hdc})", "循声而至")
            if hdice["outcome"] in ("success", "crit_success", "mixed") \
                    and not (_unf and hdice["outcome"] == "mixed"):
                _mixed = hdice["outcome"] == "mixed"
                yield ("beat", dedash_beat({"type": "description", "speaker_name": None,
                       "text": (cue + " " if cue else "") + _t(content,
                          f"你贴进暗处，屏住呼吸。{_hname}在几步之外停住——很久，很久——脚步声终于移开了。"
                          + ("但这一次，TA记住了这里的动静。" if _mixed else ""),
                          f"You press into the dark and hold your breath. {_hname} stops a few "
                          f"steps away — a long, long moment — then moves off."
                          + (" But this time, it remembers this room." if _mixed else ""))}))
                th["alert"] = 3 if _mixed else 1
                if _hw:   # it now knows one more thing about how you hide
                    th.setdefault("hides", {})
                    th["hides"][_hw] = int(th["hides"].get(_hw, 0)) + 1
                _sev = sane_delta(content, state, -4 if _mixed else -3, "擦肩而过")
                if _sev:
                    early_moments.append(_sev)
                if not _mixed:
                    th["pos"] = threat_mod.step_patrol(tcfg, th["pos"])
                    th["band"] = threat_mod.band_of(_adj, th["pos"], _ploc)
                    band = th["band"]  # the view reflects where it ACTUALLY ended up
            else:
                struck_this_turn = True
                th["strikes"] = int(th["strikes"]) + 1
                stage = tcfg["ladder"][min(th["strikes"] - 1, len(tcfg["ladder"]) - 1)]
                if (state.get("player_hp") or "healthy") == "dying":
                    stage = "dead"   # a dying body has nothing left to pay with
                threat_caught = True
                _audit(state, "threat.strike", True, f"{_hname}·第{th['strikes']}次", stage)
                _sev = sane_delta(content, state,
                                  {"return": -6, "hurt": -8, "dying": -10}.get(stage, 0),
                                  f"被{_hname}逮住")
                if _sev:
                    early_moments.append(_sev)
                if stage == "return":
                    _dest = _location_by_id(content, tcfg["return_to"]) or {}
                    commit_move(content, state, _dest if _dest.get("id") else {"id": _ploc})
                    th["alert"] = 0
                    yield ("beat", dedash_beat({"type": "description", "speaker_name": None,
                           "text": (cue + " " if cue else "") + _t(content,
                              f"一只手落在你肩上，力道大得不容商量。{_hname}几乎没有出声，"
                              f"把你半提半推地带走——回过神时，你已经在【{_dest.get('name') or '原处'}】。"
                              f"这一次，TA只是把你「请」了回来。你很清楚，不会有第二次「请」。",
                              f"A hand lands on your shoulder, far too strong to argue with. "
                              f"{_hname} says almost nothing and walks you away — when your head "
                              f"clears you are back in [{_dest.get('name') or ''}]. This time you "
                              f"were 'escorted'. There will not be a second escort.")}))
                elif stage in ("hurt", "dying"):
                    state["player_hp"] = stage
                    early_moments.append({"kind": "player_hp", "hp": stage})
                    th["alert"] = 1
                    yield ("beat", dedash_beat({"type": "description", "speaker_name": None,
                           "text": (cue + " " if cue else "") + _t(content,
                              f"{_hname}没有给你反应的时间。冷硬的一下砸在你身上，世界斜了斜——"
                              + ("你挣开时带着伤，每一步都扯着疼。" if stage == "hurt"
                                 else "你倒下去，血的温度贴着地面漫开。你还有一口气，只有一口。"),
                              f"{_hname} gives you no time to react. Something cold and hard "
                              f"lands on you and the world tilts — "
                              + ("you tear free, hurt, every step pulling at the wound."
                                 if stage == "hurt" else
                                 "you go down; warmth spreads along the floor. One breath left."))}))
                else:  # dead — the building keeps its quiet
                    state["player_hp"] = "dead"
                    early_moments.append({"kind": "player_hp", "hp": "dead"})
                    yield ("beat", dedash_beat({"type": "description", "speaker_name": None,
                           "text": (cue + " " if cue else "") + _t(content,
                              f"{_hname}到得比你的反应快。没有争执，没有声音——这一次，"
                              f"连你自己的声音也没有了。",
                              f"{_hname} arrives faster than your reflexes. No struggle, no "
                              f"sound — this time, not even your own.")}))
        elif can_touch and cue and not addressed:
            # it passes THROUGH the room — 先声后形, no contact (yet); noise draws its eye
            if noise >= 1:
                th["alert"] = min(3, int(th["alert"]) + 1)
            _sev = sane_delta(content, state, -2, "TA经过了这个房间")
            if _sev:
                early_moments.append(_sev)
            yield ("beat", dedash_beat({"type": "description", "speaker_name": None, "text": cue}))
        elif band == "near" and cue and (th["alert"] >= 1 or old_band != "near"):
            _sev = sane_delta(content, state, -1, "一门之隔")
            if _sev:
                early_moments.append(_sev)
            yield ("beat", dedash_beat({"type": "description", "speaker_name": None, "text": cue}))
        elif band == "far" and noise >= 2 and th["alert"] >= 2 and th.get("away", 0) <= 0:
            yield ("beat", dedash_beat({"type": "description", "speaker_name": None,
                   "text": _t(content, "远处，什么东西停了一下——然后朝这边来了。",
                              "Somewhere far off, something pauses — then starts this way.")}))
        # 🎬 menace/calm bookkeeping: a catch IS the release; proximity charges the
        # gauge; long comfort makes the director send it drifting back your way
        if struck_this_turn:
            th["menace"], th["calm"] = 0, 0
        elif th.get("away", 0) > 0:
            th["calm"] = 0
        else:
            th["menace"] = max(0, int(th.get("menace", 0))
                               + (3 if band == "here" else 2 if band == "near"
                                  else 1 if int(th["alert"]) >= 2 else -1))
            if band == "far" and int(th["alert"]) == 0:
                th["calm"] = int(th.get("calm", 0)) + 1
                if th["calm"] >= threat_mod.CALM_LIMIT:
                    th["calm"] = 0
                    # the director sends it HUNTING your way — full alert plus a first
                    # step now, or next turn's quiet-decay eats the restage entirely
                    th["alert"] = 3
                    if _ploc:
                        th["pos"] = threat_mod.step_toward(_adj, th["pos"], _ploc,
                                                           tcfg["cannot_enter"])
                    _audit(state, "threat.director", True, "restage", "你安静得太久了")
            else:
                th["calm"] = 0
        _alab = (["松弛", "起疑", "循声而来", "紧盯不放"] if _zh
                 else ["idle", "uneasy", "tracking", "locked on"])[int(th["alert"])]
        _tloc = (_location_by_id(content, th["pos"]) or {}).get("name") or th["pos"]
        if th.get("away", 0) > 0:
            _where = ("TA此刻被别处的动静绊住，不在这一带——本轮绝不可让TA现身，"
                      "楼里的安静本身就是戏。" if _zh else
                      "It is currently drawn elsewhere — it may NOT appear this turn; "
                      "the building's quiet IS the scene. ")
        elif band == "here":
            _where = ("TA就在本场，可被看见、可对话。" if _zh
                      else "It IS in this scene and may be seen or addressed. ")
        else:
            _where = ((f"TA不在本场（{'一门之隔' if band == 'near' else '在别处'}）——"
                       "本轮旁白与台词绝不可让TA现身、发声或被看见，至多写远处的声息。")
                      if _zh else
                      "It is NOT in this scene — it may not appear, speak or be seen this "
                      "turn; at most distant sounds. ")
        threat_line = ((f"【猎手实态·铁律】{_hname}此刻在【{_tloc}】，警觉：{_alab}。{_where}"
                        f"TA的每次现身必须先声后形：先写声音/气味/影子，最后才见形。")
                       if _zh else
                       f"[Hunter ledger — law] {_hname} is at [{_tloc}], alert: {_alab}. "
                       f"{_where}Its every appearance is heard before it is seen.")
        # 😨 dread turns tighten the pen: when it is close, the prose itself must hold
        # its breath — anticipation is the horror, and labels break the spell
        if band == "here" or (band == "near" and int(th["alert"]) >= 2):
            threat_line += (("【本轮文笔收紧】短句。听觉与触觉先行。日常物写出错位感。"
                             "不解释，不点破，不用「恐怖、诡异、可怕」这类标签词——"
                             "让读者自己后颈发凉。") if _zh else
                            (" [Tighten the prose this turn: short sentences; sound and "
                             "touch before sight; no explaining, no mood labels like "
                             "'creepy' — let the reader's own neck prickle.]"))
        threat_view = {"name": _hname, "band": band, "alert": int(th["alert"])}

    # ━━━━━━━━━━ 管线 P3.6 · 📜 规则怪谈 (house rules, program-enforced) ━━━━━━━━━━
    # 规则怪谈's dread = trust in rules gone wrong. Ours have TEETH: the ENGINE, not
    # the model, decides a rule was broken and collects the price (pressure spike /
    # sanity loss / the hunter turns). Flavor rules with no violate clause are pure
    # authored dread — contradictions welcome; the hidden core is the author's craft.
    if (state.get("mode") or "character") != "god" and not state.get("ended") \
            and channel in ("say", "do"):
        _slot_now = active_slot(content, state)
        for ru in (content.get("story") or {}).get("rules") or []:
            _vio = ru.get("violate") or {}
            _kws = [k for k in (_vio.get("keywords") or []) if k]
            if not _kws or not any(k in (player_input or "") for k in _kws):
                continue
            _when = ru.get("when") or {}
            if _when.get("location_id") and _when["location_id"] != state.get("location_id"):
                continue
            if _when.get("slots") and _slot_now and _slot_now not in _when["slots"]:
                continue
            if _vio.get("channel") and channel not in _vio["channel"]:
                continue
            _cq = ru.get("consequence") or {}
            _audit(state, "rule.broken", True, ru.get("id") or "", (ru.get("text") or "")[:20])
            early_moments.append({"kind": "rule", "text": (ru.get("text") or "")[:40]})
            if int(_cq.get("pressure") or 0) and pressure_cfg(content):
                state["pressure"] = min(99, int(state.get("pressure", 0))
                                        + int(_cq["pressure"]))
            if int(_cq.get("sanity") or 0):
                _sev = sane_delta(content, state, -abs(int(_cq["sanity"])), "违反守则")
                if _sev:
                    early_moments.append(_sev)
            if _cq.get("threat_aggro") and tcfg and state.get("threat"):
                state["threat"]["alert"] = 3   # it heard. it is coming.
                state["threat"]["away"] = 0
            yield ("beat", dedash_beat({"type": "description", "speaker_name": None,
                   "text": (_cq.get("text") or "").strip()
                   or _t(content, "（你违反了守则。这栋楼记下了。）",
                         "(You broke a rule. The building took note.)")}))

    # ━━━━━━━━━━ 管线 P4 · 解锁评估与回归问候 ━━━━━━━━━━
    # 2. gate on the CURRENT state (asks updated; affinity not yet changed this turn).
    #    asks-driven reveals surface THIS turn so the director can voice them; affinity-
    #    driven ones land NEXT turn (the warmth rose now, the confession follows) — that
    #    one-turn lag is intentional and reads naturally.
    frags = gating.iter_fragments(content)
    already0 = set(state.get("unlocked_fragment_ids") or [])
    newly = gating.evaluate_unlocks(state, frags)
    for fid in prop_frag_ids:  # physical evidence found by searching = direct unlock
        if fid not in already0 and fid not in newly:
            newly.append(fid)
    state["unlocked_fragment_ids"] = sorted(already0 | set(newly))

    # 🧠 terrible knowledge costs (CoC's oldest law): prying open a dark truth takes
    # its toll — heavy secrets bite, medium ones nick, light ones are free
    if _scfg and newly:
        _newset0 = set(newly)
        for sec in content.get("secrets", []) or []:
            _sens = {"heavy": -5, "medium": -2}.get((sec.get("sensitivity") or "").strip(), 0)
            if not _sens:
                continue
            for f in sec.get("fragments", []) or []:
                if f.get("id") in _newset0:
                    _sev = sane_delta(content, state, _sens, "窥见了不该知道的")
                    if _sev:
                        early_moments.append(_sev)

    # judgment candidates for the primary director call (titles/labels only, never bodies)
    probe_cands = _probe_candidates(content, state)
    event_cands = _event_candidates(content, state, old_act)

    # THRESHOLD MOMENTS (阈值时刻演出): structured events the UI celebrates — a truth
    # clicking into place, a relationship tier-up, a new act, an ending milestone.
    moments: list[dict[str, Any]] = list(early_moments)
    rel_deltas: dict[str, dict[str, int]] = {}   # per-char ♥ movement this turn (UI float)
    pressure_blown = False                       # ⚠️ meter hit 100 → forced terminal ending
    for t in _titles_for_fragments(content, newly):
        moments.append({"kind": "unlock", "title": t})
    if newly:
        newset = set(newly)
        logged = set()
        unlocked_now = set(state.get("unlocked_fragment_ids") or [])
        for sec in content.get("secrets", []) or []:
            scid = sec.get("character_id")
            title = (sec.get("title") or "").strip()
            if scid and title and sec.get("id") not in logged                     and any(f.get("id") in newset for f in sec.get("fragments", []) or []):
                logged.add(sec.get("id"))
                rel_log(state, scid, old_act, "reveal",
                        _t(content, f"关于「{title}」的真相，揭开了一层。",
                           f"A layer of the truth about “{title}” came loose."))
            # 📸 秘密拼全: the LAST piece of a layered secret just clicked in — that's
            # a keepsake. Single-fragment secrets don't count (nothing was "assembled").
            sfids = [f.get("id") for f in sec.get("fragments", []) or [] if f.get("id")]
            if (title and len(sfids) >= 2 and set(sfids) <= unlocked_now
                    and any(fid in newset for fid in sfids)):
                sch = next((c for c in _characters(content) if c.get("id") == scid), None)
                last_txt = next((f.get("content") or "" for f in reversed(sec.get("fragments") or [])
                                 if f.get("id") in newset), "")
                album_add(content, state, "secret", title,
                          last_txt or _t(content, f"「{title}」的全部真相，拼上了。",
                                         f"The whole truth of “{title}” came together."),
                          sch, rarity=2)
                moments.append({"kind": "secret_full", "title": title})

    # 🚪 悬念钩回放 (⚖️ 无点击不推进): /leave 的 beacon 只暂存不落拍, 真正离场归来的
    # 这一拍才把钩子写词上台. 只是切了下标签页 (没到回归门槛) — 钩子作废, 当没走过.
    _pp = state.pop("parting_pending", None)
    if (_pp and returning and (state.get("mode") or "character") != "god"
            and channel != "think"):
        for _b in build_parting_hook(content, state, persona, llm, comeback=True):
            all_beats.append(_b)
            yield ("beat", _b)

    # 🌍 活世界回归播报: 心跳期间落账的后果 (缺席戏/世界邀约), 玩家一回来就摆在面前，
    # 各讲一次 — 你看到的是既成事实，不是过期任务列表
    if (state.get("mode") or "character") != "god" and channel != "think":
        from . import living as _living_mod
        # ⚖️ 先补演心跳押下的词债 (缺席戏文/带刺短信/周年讯息/邀约) — LLM 只在
        # 这个点击驱动的回合里跑, 心跳里绝不跑 (无点击不推进)
        for _pev in _living_mod.settle_pending(content, state, llm):
            yield ("phone", _pev)
            moments.append({"kind": "phone", "name": _pev.get("name", ""),
                            "device": _pev.get("device"), "call": False})
        for _nw in _living_mod.serve_living_news(state):
            _lb = dedash_beat({"type": "description", "speaker_name": None,
                               "text": _t(content, f"（你不在的时候：{_nw}）",
                                          f"(While you were gone: {_nw})")})
            all_beats.append(_lb)
            yield ("beat", _lb)

    # 💌 你不在的时候: this turn is a COMEBACK → the absent hearts that missed the
    # player reach out first thing (texts; a long absence earns a letter). The present
    # primary's greeting rides on the `returning` prompt flag as before.
    if returning and (state.get("mode") or "character") != "god" and channel != "think":
        for ev in offline_pulse(content, state, here_before, away_hours, llm):
            yield ("phone", ev)
            moments.append({"kind": "mail" if ev.get("mail") else "phone",
                            "name": ev["name"], "device": ev["device"],
                            "call": bool(ev.get("call"))})

    # ━━━━━━━━━━ 管线 P5 · 选角与提示词脚手架 ━━━━━━━━━━
    # responder selection. With an explicit @target → just that character. With NO target
    # (and not an inner thought) the player is addressing the WHOLE room — every present
    # character may answer, though some can choose to stay silent. Otherwise the router
    # picks the single most-relevant speaker.
    mode = state.get("mode") or "character"
    pcid = state.get("player_character_id")  # the character the player embodies (character mode)

    # only characters in the player's CURRENT scene take part (present this act AND here by
    # location/following). In CHARACTER mode the player IS pcid, so that character is not an
    # NPC responder. In GOD mode the player embodies no one.
    all_chars = [c for c in scene_characters(content, state) if c.get("id") != pcid]

    # 关系大事记: first time you lay eyes on someone, remember where it happened
    met = set(state.get("met_ids") or [])
    here_name = (current_location(content, state) or {}).get("name") or ""
    for c in all_chars:
        cid = c.get("id")
        if cid and cid not in met:
            met.add(cid)
            rel_log(state, cid, old_act, "meet",
                    _t(content, f"初次见面{('，在' + here_name) if here_name else ''}。",
                       f"First met{(' at ' + here_name) if here_name else ''}."))
    state["met_ids"] = sorted(met)

    # 📱 remember WHEN the player was last face to face with each character — the
    # afterglow text trigger ("你刚走就想你了") keys off this parting moment
    ph_seen = state.setdefault("phone", {}).setdefault("seen", {})
    for c in all_chars:
        if c.get("id"):
            ph_seen[c["id"]] = _time_index(state)

    # 🤝 赴约: an open promise whose hour is NOW, its person standing right here, the
    # player at the promised place → this very scene is the appointment. Steer the
    # conversation to them; the relationship reward lands immediately (you SHOWED UP).
    promise_kept = None
    if mode != "god" and tun["turns_per_slot"] > 0 and channel != "think":
        now_idx = _time_index(state)
        here_ids = {c.get("id") for c in all_chars}
        for pr in state.get("promises") or []:
            if (pr.get("status") == "open" and _promise_index(pr) == now_idx
                    and pr.get("char_id") in here_ids
                    and ((not pr.get("location_id"))
                         or pr["location_id"] == state.get("location_id"))):
                promise_kept = pr
                break
        if promise_kept:
            promise_kept["status"] = "kept"
            if not target_character_id:
                target_character_id = promise_kept["char_id"]
            kc = promise_kept["char_id"]
            old_sc = (state.get("rel") or {}).get(kc) or relationships.new_scores()
            state.setdefault("rel", {})[kc] = relationships.apply_deltas(
                old_sc, tun["promise_keep_bonus"],
                tun["promise_keep_bonus"] if promise_kept.get("romantic") else 0, tun,
                trust_delta=4)   # 🛡 如约 = 可靠感的头号来源
            got = state["rel"][kc]
            dcl = int(got.get("closeness", 0)) - int(old_sc.get("closeness", 0))
            drm = int(got.get("romance", 0)) - int(old_sc.get("romance", 0))
            if dcl or drm:
                rel_deltas[kc] = {"name": promise_kept.get("char_name"),
                                  "closeness": dcl, "romance": drm}
            moments.append({"kind": "promise", "status": "kept",
                            "name": promise_kept.get("char_name"),
                            "what": promise_kept.get("what"),
                            "romantic": bool(promise_kept.get("romantic"))})
            rel_log(state, kc, old_act, "promise",
                    _t(content, f"你如约而至：{promise_kept.get('what','')}。",
                       f"You kept the promise: {promise_kept.get('what','')}."))

    if mode == "god":
        # Invisible-observer mode: the player doesn't speak in-scene; the present cast
        # interact WITH EACH OTHER (the 旁观/CP mode). The player's input is a director
        # cue. Everyone present takes part; an explicit target spotlights one character.
        observer = True
        if target_character_id:
            spot = _char_by_id(content, target_character_id)
            primary = spot or (all_chars[0] if all_chars else None)
        else:
            primary = all_chars[0] if all_chars else None
        primary_id = primary.get("id") if primary else None
        broadcast = len(all_chars) > 1
        responders = [primary] if primary else []
    else:
        observer = False
        # 🎬 导演场次单 (每场一次, 缓存): 戏眼/心事/主动权; 降级为空 = 行为原样。
        # troupe 灰度旗 (剧本级试点, plan_render 前例): 关 = 零额外调用零行为差
        _brief = (ensure_scene_brief(content, state, persona, llm)
                  if tun.get("troupe") else {})
        # 选角接管: 玩家没点名、没提名、没在试探谁时, 导演点的「该主动的人」接话
        _init_id = None
        if _brief.get("initiative") and not target_character_id \
                and not any((c.get("name") or "") in (player_input or "")
                            for c in all_chars if c.get("name")) \
                and not probed_char_ids:
            _init_id = next((c.get("id") for c in all_chars
                             if c.get("name") == _brief["initiative"]), None)
            if _init_id:
                _audit(state, "director.cast", True, _brief["initiative"])
        primary = pick_responder(content, state, player_input,
                                 _init_id or target_character_id,
                                 probed_char_ids, all_chars)
        primary_id = primary.get("id") if primary else None
        broadcast = bool(primary) and channel != "think" and not target_character_id and len(all_chars) > 1
        if primary is None or channel == "think" or threat_caught:
            # think = observe/examine (handled separately below), no NPC responds;
            # 🦇 a hunter's strike interrupts the scene — the engine beats ARE the turn
            responders = []
        else:
            responders = [primary]
    # REAL conversations aren't a roll call: in a broadcast, the members who follow are
    # decided AFTER the primary speaks — by the primary's next_speakers judgment (who would
    # naturally chime in, 0~2, order = who jumps in first), plus deterministic must-speaks
    # (named in the player's line / owner of a probed secret). No judgment (mock/prose) →
    # legacy everyone-answers. See the extension inside the responder loop.
    member_pool = [c for c in all_chars if c.get("id") != primary_id] if broadcast else []
    pcfg = pressure_cfg(content)
    dead_names = [c.get("name") for c in _characters(content)
                  if c.get("id") in _dead_ids(state) and c.get("name")]
    gen_count = sum(1 for c in _characters(content) if c.get("generated"))
    if channel != "think":
        state["last_speaker_id"] = primary_id

    # 📇 联系方式 (Yi 2026-07-28 改架构): 好感【只定倾向】不再当判决 —— 判决只管命中
    # 关键词的那一拍, 而谈判跨好几拍(实弹: 追问一句「那我现在打一个」那拍零约束, 模型
    # 就把号给了, 通讯录却空着)。现在与其余五十个账本事件一视同仁: 模型申报 contact_given,
    # 引擎按申报落账; 玩家死缠磨出来的号码本来就算「靠剧情挣」。
    _contact_ask = bool(player_input) and channel in ("say", "do") \
        and bool(_CONTACT_RE.search(player_input))
    _contact_will = False
    _contact_note = ""
    _can_give_contact = bool(primary and not observer and phone_enabled(content)
                             and primary.get("id") != state.get("player_character_id")
                             and not has_contact(state, primary.get("id")))
    if _contact_ask and primary and not observer:
        if has_contact(state, primary.get("id")):
            _contact_note = "TA其实已经有你的联系方式了，自然地提醒一句就好。"
        else:
            _contact_will = contact_will_give(content, state, primary.get("id"))
            _contact_note = ("玩家在向你要联系方式。以你们现在的交情你愿意给："
                             "自然地把号报给TA或写给TA，并申报 contact_given。" if _contact_will else
                             "玩家在向你要联系方式，但你们还没熟到那份上：按你的性格自然地"
                             "婉拒或岔开，话别说死。（TA若一再坚持，你也可以按自己的性子松口——"
                             "那就照实把号给出去并申报 contact_given，别嘴上给了却当没给。）")

    # In character mode the player speaks AS their chosen character — give the model that
    # identity instead of the generic persona name, so NPCs address the right person.
    player_char = _char_by_id(content, pcid) if (mode == "character" and pcid) else None
    persona_for_prompt = persona
    if player_char:
        # 扮演谁，立场就是谁的: the embodied character's own persona + agenda ride every
        # turn — NPCs treat the player as THAT person with THAT stake, not a generic guest
        _pc_bits = [player_char.get("background") or (persona or {}).get("background", "")]
        if (player_char.get("persona_text") or "").strip():
            _pc_bits.append(f"【TA的为人】{player_char['persona_text'].strip()}")
        if (player_char.get("wants") or "").strip():
            _pc_bits.append(f"【TA自己的立场与目标】{player_char['wants'].strip()}")
        persona_for_prompt = {**(persona or {}), "name": player_char.get("name"),
                              "background": "　".join(b for b in _pc_bits if b)}
    # 🎖 the player's EVOLVED identity overrides the authored one (升职/揭穿/新头衔) —
    # NPCs address and treat them by who they are NOW
    if state.get("identity"):
        persona_for_prompt = {**(persona_for_prompt or {}),
                              "background": ((persona_for_prompt or {}).get("background") or "")
                              + f"　【TA现在的身份：{state['identity']}——在场的人都知道并按此对待TA】"}

    # think only applies when the player actually embodies/voices someone (not in god mode)
    is_think = channel == "think" and not observer
    # the player spoke/acted but NOBODY is in this scene to answer (e.g. they walked into an
    # empty place) → narrate the place + their action instead of emitting silence.
    narrate_only = (not observer) and (channel != "think") and (not responders) \
        and not threat_caught

    # hard-gate guidance: is this act still locked, and what key info is still missing?
    # (unlocks for THIS turn already applied above, so this reflects the current truth.)
    progress0 = act_progress(content, state, old_act)
    needed_topics = _pending_topics(progress0)
    act_locked = act_has_gate(content, old_act) and not can_advance(content, state, old_act)

    # stuck-hint escalation: how many consecutive PRIOR turns the player has been on this
    # gated act without uncovering a new required clue. The longer they spin, the more
    # forthcoming the NPCs' guidance becomes (and at the top tier a narrator nudge fires).
    # Only meaningful while the act is locked and there's still something to find.
    stuck_in = int(state.get("stuck", 0) or 0) if (act_locked and needed_topics) else 0
    stuck_level = 1 if stuck_in >= tun["stuck_nudge"] else 0
    stuck_level = 2 if stuck_in >= tun["stuck_push"] else stuck_level

    # 3. the model is the DIRECTOR for each responder: per-speaker gated context (so a
    #    character can only ever voice what IT is allowed to know — no cross-leak). Each
    #    responder's beats are YIELDED the moment they're computed → they stream out.
    next_act = current_act(content, old_act + 1)
    place = _physical_place(content, state)   # concrete "you are here" anchor (empty if none)
    # 🧩 input analysis: the player's line decomposed into ENGINE-VERIFIED referents
    # (who/where/what it names + live status) — computed once AFTER the twins so it
    # reflects the post-move truth, then rides every responder prompt at depth-0
    intent_digest = intent_mod.digest(
        intent_mod.analyze(content, state, player_input, channel), lang_of(content)) \
        if (player_input or "").strip() and not observer else ""
    # 🔥 床戏进度: engine-owned intimate ladder (mature runs only) — climbs from the
    # player's line, never slides back, resets when the scene moves. Rides depth-0 so
    # the model can't re-undress her or reset the room (both observed in prod).
    heat_anchor = ""
    if state.get("mature") and not observer:
        # self-healing ignition first: if the ladder reads colder than the recent
        # transcript (deploy mid-scene / a climb the patterns missed), jump to truth
        _recent = ([b.get("text") or "" for b in (beat_log or [])[-12:]]
                   or [h.get("content") or "" for h in (history or [])[-12:]])
        # 🧯 先反向自愈: 账本比正文烫得多就降温 (一次误判会把整局钉在第4级, 阶梯单调,
        # 老档自己下不来 — 这样存量误判档不必动生产库, 下一拍自己凉下去)
        _h_was = int((state.get("heat") or {}).get("stage") or 0)
        _h_cool = heat_mod.cool_if_unsupported(
            state, [b.get("text") or "" for b in (beat_log or [])[-24:]] or _recent)
        if _h_cool != _h_was:
            _audit(state, "heat.cool", True, f"{_h_was}→{_h_cool}", "正文无实锤，账本降温")
        _h_old, _h_new = heat_mod.catchup(state, _recent, state.get("location_id"))
        if _h_new != _h_old:
            _audit(state, "heat.stage", True, f"{_h_old}→{_h_new}（回填）")
        _h_old, _h_new = heat_mod.advance(state, player_input or "", state.get("location_id"))
        if _h_new != _h_old:
            _audit(state, "heat.stage", True, f"{_h_old}→{_h_new}")
        heat_anchor = heat_mod.anchor(state, lang_of(content))
    affinity_delta = 0
    advance = False
    model_ending = None
    primary_invite = None  # a character asked to LEAD the player elsewhere → confirm prompt
    time_skip = ""         # ⏳ the primary judged the scene skipped time (睡到天亮/等到入夜)

    # ⏳ the hour, for narration consistency + deadline awareness (one lean line)
    clock_line = ""
    cv0 = clock_view(content, state)
    if cv0:
        clock_line = cv0["label"]
        dl0 = cv0.get("deadline")
        if dl0 and dl0["days_left"] > 0:
            clock_line += f"。距离「{dl0['text']}」还有{dl0['days_left']}天"
        elif dl0 and dl0["days_left"] == 0:
            clock_line += f"。「{dl0['text']}」就在今天"

    def emit(b: dict[str, Any]):
        dedash_beat(b)
        all_beats.append(b)
        return ("beat", b)

    # Group naturalness (SillyTavern-style): characters answer ONE AT A TIME and each later
    # speaker is shown what the others ALREADY said THIS turn, so they genuinely react to one
    # another (接话/附和/反驳) instead of being generated in parallel and talking past each
    # other / echoing the same opener.
    said_this_turn: list[dict[str, str]] = []
    _music_job: dict[str, Any] = {}   # 🎼 乐师线程句柄 (主拍起卷, 流末收卷)
    responder_hist: dict[str, list[dict[str, str]]] = {}  # each responder's witnessed history

    rel_all = state.setdefault("rel", {})
    # relationship mode applies to character↔player only (not god/observer, not the
    # player's own embodied character)
    rel_active = (not observer)

    # ━━━━━━━━━━ 管线 P6 · 确定性旁白（孪生的叙事落地）━━━━━━━━━━
    yield from _emit_twin_beats(content, moments, emit, moved, arrival_discoveries,
                                retrieved, stashed_now, accepted, found_props, examined)

    # P7 shared flag sheet: the scalars the settle cascade accumulates across speakers
    flags = {"affinity_delta": affinity_delta, "advance": advance,
             "model_ending": model_ending, "primary_invite": primary_invite,
             "primary_name_for_invite": None, "time_skip": time_skip,
             "pressure_blown": pressure_blown, "content_mutated": content_mutated,
             "gen_count": gen_count, "contact_given": False}
    # 🔒 生长通道盘点 (对抗性审查 P1): 地点通道锁死 (LLM_MINTS_PLACES) 且人物额度
    #    用尽时, 没有任何通道能兑现 world_seed —— 这拍就不问 (问了必被驳回, 驳回
    #    不销账, due 每拍重催), 结算侧按同一口径跳过, 不记幻影空账
    ws_askable = bool(_ws_mode) and (LLM_MINTS_PLACES or gen_count < tun["max_new_characters"])
    # ━━━━━━━━━━ 管线 P7 · 导演循环（逐人：门控提示词→生成→守卫→落账） ━━━━━━━━━━
    for idx, sp in enumerate(responders):
        sp_id = sp.get("id")
        sp_name = sp.get("name") or "角色"
        ctx = gating.build_context(sp_id, frags, state, newly_ids=newly)
        rel_scores = rel_all.get(sp_id) or relationships.new_scores()
        rel_playbook = relationships.playbook_block(
            relationships.derive_mode(sp, rel_scores, tun), mature=bool(state.get("mature")),
            char=sp) if rel_active else ""
        # 💘 追求节拍: 引擎排拍, 这一轮该TA主动就把节拍指令贴进TA的提示词。
        # 取数只读, 落账等戏产出之后 (见下方 court_beat_book) —— 生成失败/守卫重写时
        # 那一天的名额不该白花。
        court_dir = court_directive_for(content, state, sp_id) if rel_active else None
        if court_dir:
            rel_playbook = (rel_playbook + "\n" + court_dir) if rel_playbook else court_dir
        # 💘 防御风格: the style's voice always rides along; after a warm spike (rel-up /
        # golden moment) the ENGINE schedules ONE pullback at the next meeting — the
        # "昨天那么好，今天怎么冷了" hook is a rule, not model whim.
        style_id = relationships.love_style_of(sp) if rel_active else None
        if style_id:
            retreat_now = False
            wp = _sim(state, sp_id).get("warm_peak")
            # 🚫 追求拍硬性压掉当拍回落: 「这一轮你要主动」和「昨天那么好今天冷一下」
            # 同帧就是两条互斥指令, 模型二选一 = 花掉的那一天有一半概率被回落吃掉。
            # 不消费 warm_peak, 让它改天再演。
            if isinstance(wp, dict) and not wp.get("served") and court_dir:
                pass
            elif isinstance(wp, dict) and not wp.get("served"):
                dt = _time_index(state) - int(wp.get("t") or 0)
                if 0 < dt <= 6:          # the next meeting within ~two days
                    retreat_now, wp["served"] = True, True
                    _audit(state, "style.retreat", True, sp_name)
                elif dt > 6:
                    wp["served"] = True  # too long ago — the moment cooled on its own
            sb = relationships.style_block(style_id, retreat=retreat_now)
            if sb:
                rel_playbook = (rel_playbook + "\n" + sb) if rel_playbook else sb
        others = [c.get("name") for c in all_chars if c.get("id") != sp_id and c.get("name")]
        is_primary = idx == 0
        # each character only recalls what THEY witnessed + their OWN private digest — no
        # silent cross-character/cross-scene info leak.
        sp_hist = (history_for(beat_log, sp_id, tag_narration=plan_render_on(content))
                   if beat_log is not None else (history or []))
        responder_hist[sp_id] = sp_hist
        # 信息不开天眼: a character remembers THEIR digest only; the global digest is
        # the player's whole history and never feeds a character's head
        sp_mem = (state.get("memory_by_char", {}) or {}).get(sp_id) or ""
        prompt = {
            "speaker_name": sp_name,
            "speaker_persona": sp.get("persona_text", ""),
            # 🎭 卡 v2: 性别/年龄/软肋/底线随卡进后台 — 称呼代词有法可依,
            # 底线是「一推就破的角色不可信」的最后一道闸
            "speaker_card": {k: v for k, v in (
                ("gender", sp.get("gender")), ("age_band", sp.get("age_band")),
                ("fear", sp.get("fear")), ("line", sp.get("line"))) if v},
            "persona": persona_for_prompt,
            "player_input": player_input,
            "channel": channel,
            # 🫂 TA 此刻心里把玩家当什么 (定期由判官读着正文得出, 盖在算术之上)
            "relation_read": (state.get("rel_read") or {}).get(sp_id) or {},
            # 🚶 玩家亲口说要走, 而换场只剩点地图 —— 压住模型别用文字兑现
            "move_blocked": _wants_move,
            # 💞 事件记账制旗 (Yi 定): 开着 = 契约只收 rel_event 申报, 不收每句打分
            "rel_events": bool(tun.get("rel_events")),
            "context": ctx,
            "history": sp_hist,
            "memory": sp_mem,   # THIS character's private rolling digest
            "world_facts": (content.get("story") or {}).get("world_facts") or "",
            # 🌍 世界书 (Yi: 角色不尊重世界观 — world_long 从前只到开场旁白为止)
            "world": ((content.get("story") or {}).get("world_long") or "")[:600],
        # 🏛 年代随行 (只管世界长什么样, 不管日子 — 日历走玩家自己的时区)。
        # device 同行是因为年代块自带手机豁免: 不带设备名就豁免不了。
        "era": era_of(content), "device": phone_device(content),
            # 🎯 玩家亲手定的目标 (沙盒): 世界要向它倾斜
            "player_goal": next((g.get("text") for g in reversed(goals_of(state))
                                 if g.get("status") == "open" and g.get("kind") == "player"), ""),
            # 🎬 作者开场白进每回合 (文风与事实之锚)
            "auth_opening": ((content.get("story") or {}).get("opening") or "")[:1200],
            # ⏰ 现实时刻 (Yi: 角色也得知道才行): 主答者知道现在真的是几点/星期几/什么季节
            "real_now": real_now_line(content, state),
            # 💘 全员追玩家 (行为层, 不碰 voice_print): 各角色透过自己人设吊系地追
            "pursue_player": bool(tun.get("pursue_player")) and not observer,
            # 🎭 露怯放大 (治下头): 主答者每 4 拍一记明显处下风, 打破「永远精准反击」
            "off_balance": (bool(tun.get("fallible", 1)) and not observer and idx == 0
                            and int(state.get("turn_seq") or 0) % 4 == 3),
            # 🏛 阵营底色 (权谋地基): 归属 + 玩家在本阵营的风评
            "faction_block": factions_mod.block(content, state, sp,
                                                zh=lang_of(content) != "en"),
            # 🧭 口味罗盘: 只给主答者, 样本够了才有内容 (倾斜不转向)
            **({"taste_line": taste_mod.prompt_line(state, lang_of(content) != "en")}
               if idx == 0 else {}),
            # 🌱 生长预算到期: 主拍必填 world_seed (软邀请/硬指令两档; 通道全死不问)
            **({"world_seed": _ws_mode} if idx == 0 and ws_askable else {}),
            # 🎬 本场已经写过的意象 (2026-08-05): 只给写旁白的那位 (主答者)。
            # 生产实测 59 条旁白里「桃花眼」8 次、「喉结上下滚动」6 次 —— 从前这些
            # 只喂给事后的复读守卫, 而守卫一响就是一次整包重生, 又慢又贵。
            **({"narr_motifs": narration_motifs(state)} if idx == 0 else {}),
            # 🎼 节奏带 (Spec A): 引擎按乐师账本查表, 全体发言者同一拍点
            "pace": _pace,
            # 🎭 基调事实 (贴生成点): 治「字面狠词压过语境基调」— 只在软基调且已稳住时发
            "tone": tone_anchor(state, zh=lang_of(content) != "en") if is_primary else "",
            # 🪃 记忆回调 (Spec E): 到期时引擎抽真实旧事作必填素材, 只给主答者
            **({"callback": {"mode": _cb_mode,
                             "material": pick_callback_material(content, state, sp_id)}}
               if idx == 0 and _cb_mode and sp_id else {}),
            # 🔥 推拉节拍 (Spec F): 暧昧档的张弛相位归引擎, 措辞归模型
            **({"pushpull": relationships.pushpull_line(
                    relationships.pushpull_tick(
                        state.setdefault("pushpull", {}).setdefault(sp_id or "?", {}),
                        active=bool(sp_id and relationships.derive_mode(
                            sp, (state.get("rel") or {}).get(sp_id)
                            or relationships.new_scores(), tun) == "flirt"),
                        give=int(tun.get("pushpull_give", relationships.PUSHPULL_GIVE) or 3),
                        hold=int(tun.get("pushpull_hold", relationships.PUSHPULL_HOLD) or 1)))}
               if idx == 0 and sp_id else {}),
            # 🎁 对等回礼 (Spec G): 深度由引擎按档查表, 只问不答=查户口
            **({"disclose": disclose_depth(relationships.derive_mode(
                    sp, (state.get("rel") or {}).get(sp_id)
                    or relationships.new_scores(), tun) if sp_id else "stranger")}
               if idx == 0 and _owe_disclose else {}),
            # 🚫 负面清单 (Spec J): 按好感档查表 — 热情过载的缰绳
            "negatives": relationships.negative_list(
                relationships.derive_mode(sp, (state.get("rel") or {}).get(sp_id)
                                          or relationships.new_scores(), tun)
                if sp_id else "stranger", lang_of(content) != "en"),
            # 🤐 沉默权阶梯归引擎 (Spec B): 被点名/秘密被戳/上轮已沉默 → 必须开口
            "must_speak": bool(sp_id in probed_char_ids
                               or (target_character_id and target_character_id == sp_id)
                               or int(_sim(state, sp_id).get("silent_streak", 0) or 0) >= 1),
            "speaker_faction": (factions_mod.of_char(content, sp) or {}).get("name", ""),
            "style": (content.get("story") or {}).get("style") or "",  # ✍️ 文风
            "fate_log": list(state.get("fate_log") or [])[-3:],  # 📜 命运的既定轨迹
            "roster": _physical_roster(content, state, persona),  # deterministic headcount
            "creatures_here": creatures_here(content, state),
            "place": place,                       # concrete current-location anchor (if authored)
            "intent_digest": intent_digest,       # 🧩 engine-verified referents of the line
            "eq_style": sp.get("eq_style", ""),   # how THIS character reads/expresses emotion
            "voice_print": sp.get("voice_print", ""),  # 🗣 语言指纹: 句长/口头禅/忌语/标点脾气
            # 🎬 表演指纹 v3: 动作/感官/描写的规律 (亲密/高光拍放满, 日常轻描)
            "act_pace": sp.get("act_pace", ""),
            "sense_focus": sp.get("sense_focus", ""),
            "emote_form": sp.get("emote_form", ""),
            # 🧩 已确知: 授权的玩家/局势事实 (防角色现编不该知道的私事)
            "known_facts": sp.get("known_facts", ""),
            # 台词范例 (mes_example): lines that ARE this voice — the most durable 去AI味 lever
            "examples": [str(x) for x in (sp.get("examples") or [])][:5],
            # 🎯 this character's OWN goal/will: authored wants + the engine-tracked step
            "agenda": _agenda_prompt(content, state, sp),
            # 🎬 导演场次单切片: 本场戏眼 + 这个角色自己的心事 + 是否该主动 (P1)
            "scene_brief": ({"crux": (state.get("scene_brief") or {}).get("crux", ""),
                             "mind": ((state.get("scene_brief") or {}).get("minds") or {})
                             .get(sp_name, ""),
                             "initiative": (state.get("scene_brief") or {})
                             .get("initiative") == sp_name,
                             "spark": (state.get("scene_brief") or {}).get("spark", "")}
                            if isinstance(state.get("scene_brief"), dict) else None),
            # 📌 未收的伏笔 (剧组 P2): 编剧埋的钩子到点必须收线或明书作废
            "setups_due": ([str(s.get("text")) for s in (state.get("setups") or [])
                            if not s.get("paid")][:2] if is_primary else []),
            # 🎬 场账本切片 (docs/scene-ledger.md): 已演动作 + 问答账 — 饿死语义重演。
            # 旗关着两账皆空 = 零提示词成本
            "scene_spent": (list(((state.get("scene_ledger") or {}) if isinstance(
                state.get("scene_ledger"), dict) else {}).get("spent") or [])[:6]
                if is_primary else []),
            "asked_state": (_asked_view(state) if is_primary else None),
            # 📇 联系方式 (Yi): 要靠剧情挣 — 玩家开口要时按好感给或婉拒
            "contact_note": _contact_note if is_primary else "",
            # 📇 申报口只在「还没拿到这人联系方式」时挂载 (拿到后字段消失, 一次性状态翻转)
            "can_give_contact": _can_give_contact if is_primary else False,
            "relationship_playbook": rel_playbook,  # current relationship mode toward player
            # 💞 大事记切片 (同事建议, Yi 拍板混合式): 说话人自己与玩家之间最近的事,
            # 让反应长在具体事件上 — 模式剧本是粗锚, 事件是细节 (文本已随剧本 _t 双语)
            "rel_recent": ([str(e.get("text") or "") for e in
                            list((state.get("rel_log") or {}).get(sp_id) or [])[-4:]
                            if e.get("text")] if rel_active else []),
            # 🛡 信任/戒备行为学 (合伙人 2026-08-02): 亲近高信任低 = 嘴上热心里防
            "trust_note": (relationships.trust_note(rel_scores, lang_of(content))
                           if rel_active else ""),
            # 🪞 玩家档案: 这个角色自己相处出来的印象 (认知边界: 只有见证过的才有)
            "player_read": profile_mod.impression_of(state, sp_id),
            # 🌌 跨存档残响: 前一段人生的回声 (仅上一档暖过的角色)
            "echo": echo_line(content, state, sp_id),
            # 🎭 今日心气: 引擎掷的情绪日 — 台上的行为要和好感账本的算法一致
            "day_temper": (relationships.day_mood(
                sp_id, int((state.get("clock") or {}).get("day", 1) or 1))
                if sp_id else 0),
            "player_emotion": state.get("player_emotion", ""),  # prior emotional read (continuity)
            "knowledge": sp.get("knowledge", ""),  # 智能增强: this character's background lore
            "mature": bool(state.get("mature")),   # 18+ run → adult content permitted
            "observer": observer,                  # 👁 god mode: no second-person player
            "drive": drive,                        # ▶ 观剧拍: director advances, player watches
            "track_note": track_note,              # 🎥 ledger-wins correction (one turn)
            "cult": cult_anchor(content, state),   # ⚡ 修为是铁律 (depth-0)
            "threat": threat_line,                 # 🦇 猎手实态 (depth-0, ledger-owned)
            # 🧠 理智实态: below the waterline the narration may quietly go wrong
            "sanity": (sanity_mod.anchor(_scfg, int(state.get("sanity", 0)),
                                         lang_of(content) != "en") if _scfg else ""),
            # 📜 守则贴在墙上，人人可引用 — the cast lives under these rules too
            "house_rules": [(r.get("text") or "").strip()
                            for r in (content.get("story") or {}).get("rules") or []
                            if (r.get("text") or "").strip()][:6],
            # ⚡ 你自己是什么位阶 + 身上有多少钱 (Yi: 别人不能什么也不是)
            "own_rank": _own_rank_line(content, state, sp, llm),
            # 📈 剧情欠账: 2+ stalled turns → this turn MUST pay the thread off
            "stall": (state.get("stall") if isinstance(state.get("stall"), dict)
                      and int((state.get("stall") or {}).get("n") or 0) >= 2 else None),
            # 🔎 hunting a name the engine can't resolve → the打听 must land this turn
            "seek_unknown": seek_unknown_tok if is_primary else None,
            # …and when the scout ruled the name OUT of this world, deny — don't mint
            "seek_denied": seek_denied if is_primary else False,
            "heat_anchor": heat_anchor,            # 🔥 床戏阶段表 (depth-0, replaces the generic line)
            "mandate": ((state.get("mandate") or {}).get("text") or ""
                        if isinstance(state.get("mandate"), dict) else ""),  # ⚖️ 命运已定
            "scene": current_act(content, old_act),
            "next_act_title": (next_act or {}).get("title", "") if next_act else "",
            "clock": clock_line,                  # ⏳ 第几天·什么时段 (+ deadline countdown)
            # 🏖 sandbox: never-ending world, real-hour sync, the player's own body
            "sandbox": sandbox_on(content),
            "real_time": real_time_on(content),
            "player_dead": ghost,
            "player_hp_label": ({"hurt": "受了伤，行动吃力", "dying": "重伤濒死，命悬一线"}
                                .get(state.get("player_hp") or "", "")
                                if sandbox_on(content) else ""),
            # ✨ 金手指: the player's declared powers are REAL in this world
            "player_powers": (list(state.get("powers") or [])
                              if sandbox_on(content) and not observer else []),
            # 💰 hard cash + 📋 open errands + 🌊 the world's own news (told once)
            "player_money": ({"amount": int(state.get("money") or 0),
                              "currency": currency_of(content)}
                             if economy_on(state) and not observer else None),
            "player_quests": [
                f"{q.get('title', '')}（报酬{q.get('reward') or 0}{currency_of(content)}"
                + (f"，限第{q['deadline_day']}天之内" if q.get("deadline_day") else "") + "）"
                for q in (state.get("quests") or []) if q.get("status") == "open"][:4],
            "news": (serve_news(state) if is_primary and not observer else ""),
            # 🕸 this speaker's charged stances toward who else is in the scene
            "npc_stances": npc_stance_line(content, state, sp_id,
                                           [c for c in all_chars if c.get("id") != sp_id]),
            # 🤝 THIS scene is the appointment being honored (a romance one plays as a date)
            "appointment": ({"what": promise_kept.get("what", ""),
                             "romantic": bool(promise_kept.get("romantic"))}
                            if (promise_kept and sp_id == promise_kept.get("char_id")) else None),
            # 🤝 the player stood this speaker up — they hold it (voiced once, then let go)
            "broken_promise": next((p.get("what") for p in (state.get("promises") or [])
                                    if p.get("status") == "missed" and p.get("char_id") == sp_id), None),
            # 🌆 a rumor from offscreen life, told once when the moment fits
            "rumor": (serve_rumor(state) if is_primary and not observer else ""),
            # 🗓 玩家公开的行程: 将来的可以顺着关心, 刚过去的问一句结果 (只主叙者问)
            "player_diary": (player_diary_for_prompt(content, state)
                             if is_primary and not observer else None),
            # 📔 玩家备忘录: 叙事罗盘 (角色看不见本子, 但相关线头要有机会浮现)
            "player_notes": ([n.get("text") for n in (state.get("player_notes") or [])][:8]
                             if is_primary and not observer else None),
            # 📱 what you two texted lately — the scene remembers the phone
            "sms_tail": sms_tail_line(state, sp_id),
            # 🧠 TA 记得你说过的【具体的事】。从前这本账只接在短信回复一条路上 ——
            # 于是你在短信里说过"我不吃香菜", 见了面 TA 一句不提; 蒸馏出来的事实
            # 也只在手机里用得上。Yi 要的是"几天后 TA 主动用上", 而当面才是最该用上
            # 的场合 (旁白体检第 21 条)。认知边界照旧: 只给这个角色自己那一本。
            "knows": knows_of(state, sp_id),
            # the sim sheet: body state + standing intention + how the LAST scene left them
            "condition": {"hp": _HP_LABEL.get(char_hp(state, sp_id), ""),
                          "intent": (((state.get("char_sim") or {}).get(sp_id) or {})
                                     .get("intent") or ""),
                          "mood": _carried_mood(state, sp_id),
                          "keepsakes": [k.get("name") for k in
                                        (((state.get("char_sim") or {}).get(sp_id) or {})
                                         .get("keepsakes") or [])],
                          "carrying": [i.get("name")
                                       for i in char_items(content, state, sp_id)]},
            "cast": others,
            # in a broadcast, non-primary characters may stay silent and never narrate
            "group_mode": ("primary" if is_primary else "member") if broadcast else None,
            # god mode: characters interact with EACH OTHER; player is an unseen director
            "observer": observer,
            "director_note": player_input if observer else None,
            # hard-gate: act not yet cleared → don't resolve/jump; may steer toward these
            "act_locked": act_locked,
            "needed_topics": needed_topics,
            "stuck_level": stuck_level,
            # ask/event judgment: the primary states what the player truly probed and which
            # story events actually happened this turn (keyword hits above are provisional)
            "probe_candidates": probe_cands if is_primary else [],
            "event_candidates": event_cands if is_primary else [],
            # the player came back after a while away → greet them and pick up the thread
            "returning": bool(returning) if is_primary else False,
            # 🎲 the fate roll for this 做-action (director must narrate its outcome)
            "check": dice if is_primary else None,
            # ⚠️ the story's pressure meter (model judges this turn's delta)
            "pressure_cfg": ({**pcfg, "value": int(state.get("pressure", 0))}
                             if (pcfg and is_primary) else None),
            # ☠️/👋/🎖/🎒 dynamic-world context
            "deaths": dead_names,
            "player_items": ([i.get("name") for i in (state.get("inventory") or [])]
                             if is_primary else []),
            # 🎒 场景在册物 (物品实体化 P1): 此地被特写过的物件 — 提示词里划清
            # 在册与布景的界线, 申报过的才许发挥剧情作用
            "scene_items": ([r.get("name") for r in
                             items_mod.scene_rows(state, state.get("location_id"))]
                            if is_primary else []),
            "can_new_char": (is_primary and flags["gen_count"] < tun["max_new_characters"]),
            # what the others have ALREADY said this turn → react, don't echo
            "said_this_turn": list(said_this_turn),
        }
        if plan_render_on(content) and hasattr(llm, "plan_and_render"):
            # 双拍合同 (docs/plan-render.md): the prose streams out token-by-token while
            # it's being written; the judgments arrived in the fast plan beat before it.
            # Members ride the same seam: their line-protocol render is speech-only and
            # 「无」 is a valid (silent) result — no fallback double-call on silence.
            directed = None
            # 🧾 整改 P0: 引擎在两拍之间先判, 把回执交给演员 (runtime.plan_receipt)。
            # 闭包在这里成型是因为 qwen 拿不到 content/state —— 适配器不该知道世界长什么样,
            # 它只负责在正确的时刻回头问一句。
            def _settle_plan(_plan, _c=content, _s=state,
                             _pn=(persona_for_prompt or {}).get("name") or ""):
                return plan_receipt(_c, _s, _plan, _pn)

            for _pr_kind, _pr_val in plan_render_call(llm, prompt, _settle_plan):
                if _pr_kind == "token":
                    tok = _pr_val if isinstance(_pr_val, dict) else \
                        {"kind": "narration", "text": str(_pr_val)}
                    yield ("token", {"speaker": sp_name, **tok})
                elif _pr_kind == "final":
                    directed = _pr_val
            if directed is None:  # backend yielded nothing usable — old contract
                directed = llm.generate(prompt)
        else:
            directed = llm.generate(prompt)
        # 🎙 人称守卫 (Yi field case: 「你」被安到NPC头上、玩家名字进旁白): the referent
        # inversion is deterministic to catch — one corrective rewrite, then settle.
        _pn_guard = ((_char_name(content, pcid) if pcid else "")
                     or (persona_for_prompt or {}).get("name") or "")
        if is_primary and not observer and _pov_break(directed, _pn_guard):
            _audit(state, "pov.enforced", True, sp_name, "旁白人称错位，已重写")
            _rt = llm.generate({**prompt, "logic_correction": _POV_CORRECTION})
            if _rt.get("beats") and not _pov_break(_rt, _pn_guard):
                directed = _rt
        if prompt.get("broken_promise"):
            # the grudge got its scene — from here on it's history, not a broken record
            for p in (state.get("promises") or []):
                if p.get("status") == "missed" and p.get("char_id") == sp_id:
                    p["status"] = "missed_noted"
        _pd = prompt.get("player_diary") or {}
        if _pd.get("_passed_id"):
            # 「那天怎么样」问过一次就翻篇 — 别每个回合都追问 (同爽约家法)
            for e in state.get("player_events") or []:
                if e.get("id") == _pd["_passed_id"]:
                    e["status"] = "asked"
        # LOGIC BACKSTOP (primary/addressed character only): verify the turn against the live
        # scene before streaming it — no absent character walks in, no locked secret leaks.
        if is_primary and not observer and get_settings().logic_guard:
            directed = _logic_guard(llm, prompt, directed, content, state, frags)
        elif not is_primary:
            # members skip the full logic guard, but an EN story still can't leak Chinese
            directed = _lang_guard(llm, prompt, directed, content)
        if is_primary and state.get("mature"):
            # 🔥 the model may lead the scene forward on its own — the ladder follows the
            # prose too (strict pattern set), so next turn's anchor states the truth
            _h_old, _h_new = heat_mod.advance(
                state, " ".join(b.get("text", "") for b in directed.get("beats", [])),
                state.get("location_id"), from_model=True)
            if _h_new != _h_old:
                _audit(state, "heat.stage", True, f"{_h_old}→{_h_new}")
        d_beats = directed.get("beats", [])
        if not is_primary:
            # members contribute dialogue only (one shared narration from the primary)
            d_beats = [b for b in d_beats if b.get("type") == "dialogue"]
            # ECHO GUARD: drop a member line that just parrots what someone already said this
            # turn (verbatim or near-verbatim) — better silence than two characters in unison.
            prior_said = {_norm_line(s.get("text", "")) for s in said_this_turn}
            d_beats = [b for b in d_beats if _norm_line(b.get("text", "")) not in prior_said
                       and not _too_similar(b.get("text", ""), said_this_turn)]
        # the sim sheet remembers what this character SAID they'd do next
        # (英文一词好几个字母, 中文字数截断会腰斩英文句 — 语言分档)
        _intent = (directed.get("self_intent") or "").strip()[:80 if lang_of(content) == "en" else 40]
        if _intent and sp_id:
            _sim(state, sp_id)["intent"] = _intent
            _sim(state, sp_id)["intent_at"] = _time_index(state)   # ⏳ 应承有保质期
        # 🧍 姿位账本: where this body is inside the room and how it's held. Entries
        # carry the location id, so moving scenes auto-stales them (no cleanup pass).
        # ⚠️ 两处都必须走 book_position: 姿位是模型填的自由文本, 从前引擎原样收下,
        #    于是「往【别处】走」这种自相矛盾的值也能入账 (线上实弹 2026-08-08)。
        _spos = (directed.get("self_position") or "").strip()[:16]
        if _spos and sp_id and book_position(content, state, sp_id, _spos):
            _audit(state, "pos.set", True, f"{sp_name}:{_spos}")
        if is_primary:
            _ppos = (directed.get("player_position") or "").strip()[:14]
            if _ppos and book_position(content, state, None, _ppos):
                _audit(state, "pos.set", True, f"你:{_ppos}")
        # 📟 心象仪: the speaker's own judged inner state rides on their LAST line
        mood = (directed.get("self_state") or "").strip()[:40 if lang_of(content) == "en" else 12]
        # 🎭 …and PERSISTS: how this scene left them is how the next one finds them
        if mood and sp_id:
            # scene = 这股情绪生在哪一场; 同场之内不再回喂 (见 _carried_mood)
            _sim(state, sp_id)["mood"] = {"text": mood, "at": _time_index(state),
                                          "scene": _scene_tag(state)}
        if mood and tun["mind_reader"]:
            for b in reversed(d_beats):
                if b.get("type") == "dialogue":
                    b["mood"] = mood
                    break
        # 🧍 动作位: 帧表里报了明确的肢体动作 → 随最后一句台词下发动作差分
        # (可见的身体语言, 不吃 mind_reader 门 — 那道门拦的是内心剧透)
        from .director import pose_of as _pose_of
        _act = _pose_of(directed.get("self_position"))
        if _act:
            for b in reversed(d_beats):
                if b.get("type") == "dialogue":
                    b["act"] = _act
                    break
        # 💘 追求节拍落账: 戏真的产出了才消费当天的名额 (取数见上方 court_directive_for)
        if court_dir and any((b.get("text") or "").strip() for b in d_beats):
            court_beat_book(content, state, sp_id)
        # 🪃 回调收卷 (Spec E): 报审+验真 — 报的摘录必须真出现在这一轮的拍里
        if is_primary and _cb_mode:
            _cbq = str(directed.get("callback_done") or "").strip().strip("「」\"'")
            _cb = state.setdefault("callback", {"last": 0, "blanks": 0, "used": []})
            _turn_text = " ".join((b.get("text") or "") for b in d_beats)
            _mat_now = pick_callback_material(content, state, sp_id)
            if _callback_landed(_mat_now, _cbq, _turn_text):
                _cb["last"] = int((state.get("growth") or {}).get("turn", 0) or 0)
                _cb["blanks"] = 0
                _mat = _mat_now
                _cb.setdefault("used", []).append(_mat)
                _cb["used"] = _cb["used"][-12:]
                _audit(state, "callback", True, f"{sp_name}·{_cbq[:16]}")
            else:
                _cb["blanks"] = int(_cb.get("blanks", 0) or 0) + 1
                _audit(state, "callback", False, sp_name,
                       "谎报摘录" if _cbq and _cbq not in ("无", "None") else
                       f"连续第{_cb['blanks']}次无")
        # 🤐 沉默账 (Spec B): 没说话但有动作拍 = 合法沉默, 记类审计+连续计数
        _spoke = any(b.get("type") == "dialogue" and (b.get("text") or "").strip()
                     for b in d_beats)
        if sp_id:
            _ssim = _sim(state, sp_id)
            if _spoke:
                _ssim["silent_streak"] = 0
            elif any((b.get("text") or "").strip() for b in d_beats):
                _ssim["silent_streak"] = int(_ssim.get("silent_streak", 0) or 0) + 1
                _audit(state, "beat.silence", True, sp_name,
                       f"连续{_ssim['silent_streak']}轮")
        # 🌱 生长种子收卷第一步: 人物种子并入 new_char 出生管线 (守卫/配额原样),
        # 地点种子暂存 — 铸造与确认条在回合尾统一处理 (move_request 在那里才定)
        if is_primary and _ws_mode:
            _wso = str(directed.get("world_seed") or "").strip().strip("「」\"'")
            flags["world_seed_out"] = _wso
            if _wso.startswith(("人物：", "人物:")) and not (directed.get("new_char") or "").strip():
                directed["new_char"] = _wso.split("：", 1)[-1].split(":", 1)[-1].strip()
        # 🎼 乐师起卷 (Yi 2026-07-22: 高精度观察情绪切 BGM): 主拍一结算就开线程读
        # 这一回合的实际文字判情绪 — 跑在配角发言/结算的影子里, 不占关键路径;
        # 流末收卷 (direct 事件本来就在流末发, 音乐不差这一拍)
        if is_primary and not observer and d_beats and not _music_job.get("thread"):
            try:
                import threading as _muth

                from .director import BGM_TRACKS as _BT
                _mled = state.get("bgm_led") or {}
                _mtxt = (f"玩家：{player_input}\n" + "\n".join(
                    f"{b.get('speaker_name') or '旁白'}：{b.get('text', '')}"
                    for b in d_beats if b.get("text")))[:1200]
                _music_job["box"] = {}
                _music_job["thread"] = _muth.Thread(
                    target=_music_worker, daemon=True,
                    args=(llm, {"music_judge": True, "text": _mtxt,
                                "context": f"地点：{(current_location(content, state) or {}).get('name', '')}",
                                "current": str(_mled.get("track") or ""),
                                "held": int(_mled.get("held") or 0),
                                "menu": [{"key": k, "tags": sorted(v["tags"]), "energy": v["energy"]}
                                         for k, v in _BT.items()]},
                          _music_job["box"]))
                _music_job["thread"].start()
            except Exception:
                _music_job.pop("thread", None)
        for b in d_beats:
            said_this_turn.append({
                "speaker": b.get("speaker_name") or "旁白",
                "text": b.get("text", ""),
            })
            yield emit(b)
        yield from _settle_directed(content, state, tun, sp, sp_id, sp_name,
                                    is_primary, directed, observer, pcid, old_act,
                                    dice, pcfg, newly, asks, provisional_asks,
                                    provisional_events, probe_cands, event_cands,
                                    moments, rel_deltas, rel_all, rel_active,
                                    said_this_turn, dead_names, emergent_ids,
                                    emit, llm, flags)
        # 🚫 建议不抢跑 (Yi 2026-07-25 改令, 覆盖早前的「提前上桌」): 选项要等剧情
        # 演完才出来 — 早推的 sugg 事件会在配角还在说话时就亮 chips。撤掉早推,
        # chips 随 final 的权威版走, 客户端在正文播完的 finishTurn 才上桌。
        # WHO ELSE speaks this turn: the primary judged who'd naturally chime in
        # (varies 0~2 by context/personality — not everyone, not a fixed order);
        # characters named by the player or whose secret was probed always get to
        # speak. Extending the list mid-iteration is safe (list iterator is indexed).
        if is_primary and broadcast and member_pool:
            picked = directed.get("next_speakers")
            if picked is None:
                chosen = list(member_pool)  # no judgment (mock/prose) → legacy: everyone
            else:
                chosen = []
                for nm in picked:
                    nm = str(nm).strip()
                    for c in member_pool:
                        cn = c.get("name") or ""
                        if nm and cn and (cn == nm or cn in nm or nm in cn) and c not in chosen:
                            chosen.append(c)
                for c in member_pool:  # deterministic must-speaks
                    if c in chosen:
                        continue
                    cn = c.get("name") or ""
                    if (cn and cn in (player_input or "")) or c.get("id") in probed_char_ids:
                        chosen.append(c)
                chosen = chosen[:3]
            responders.extend(chosen)
        # 🚪 写走必记走（架构层）: narration walked someone out → the ledger walks them
        # out too, even when the npc_moves judgment forgot to file it
        _settle_prose_exits(content, state, d_beats, pcid)
        # 🗣 点名要有回应 (Yi: 戴沐白问竹清，竹清没法答): ANY speaker whose line opens
        # with a present character's name/short-name hands them the floor this turn —
        # a spoken question must be answerable. Capped so chains can't run away.
        if len(responders) < 4:
            _voc = _addressed_char(content, state, d_beats, sp_id, pcid)
            if _voc is not None and all(r.get("id") != _voc.get("id") for r in responders):
                responders.append(_voc)
                _audit(state, "floor.pass", True,
                       f"{sp_name}→{_voc.get('name', '')}", "台词点名，话权移交")

    # the flag sheet unpacks back into turn locals for the phases below
    affinity_delta = flags["affinity_delta"]
    advance = flags["advance"]
    model_ending = flags["model_ending"]
    primary_invite = flags["primary_invite"]
    primary_name_for_invite = flags["primary_name_for_invite"]
    time_skip = flags["time_skip"]
    pressure_blown = flags["pressure_blown"]
    content_mutated = flags["content_mutated"]
    gen_count = flags["gen_count"]

    # ━━━━━━━━━━ 管线 P8 · 场后结算（相册/金色瞬间/观察/世界自转/幕推进） ━━━━━━━━━━
    # 📇 联系方式结算 (Yi): 开口要的按好感给/婉拒 (台词已演过, 这里落账);
    # 没开口的走两条主动线: 好感过阈值 TA 必给 / 心情好的日子随缘塞 (每人每天掷一次)
    if not observer and primary and channel in ("say", "do") and not ghost:
        _pcid_c = primary.get("id")
        if _pcid_c and _pcid_c != pcid and _pcid_c not in _dead_ids(state)                 and not has_contact(state, _pcid_c):
            _clo_c = int(((state.get("rel") or {}).get(_pcid_c) or {})
                         .get("closeness", 0) or 0)
            _day_c = int((state.get("clock") or {}).get("day", 1) or 1)
            _gave = ""
            if flags.get("contact_given"):
                # ① 戏里给了 (模型申报) — 最高优先: 正文说给了就真给, 文与实不许分家
                _gave = "戏里TA亲口给你的"
            elif _contact_ask:
                if _contact_will:
                    _gave = "你开口要的"
                else:
                    _audit(state, "contact.refuse", False,
                           f"{primary.get('name', '')} 交情{_clo_c}<{CONTACT_ASK_T}")
            elif _clo_c >= CONTACT_OFFER_T:
                _gave = "熟到了这份上，TA自己给的"
            else:
                _rolls = state.setdefault("contact_rolls", {})
                if _clo_c >= 12 and relationships.day_mood(_pcid_c, _day_c) > 0                         and str(_rolls.get(_pcid_c)) != str(_day_c):
                    _rolls[_pcid_c] = _day_c
                    import zlib as _zlib
                    if _zlib.crc32(f"{_pcid_c}|{_day_c}".encode("utf-8")) % 10 < 3:
                        _gave = "TA今天心情好，主动塞给你的"
            if _gave:
                _cbeat = dedash_beat({"type": "description", "speaker_name": None,
                                      "text": grant_contact(content, state, primary, _gave)})
                all_beats.append(_cbeat)
                yield ("beat", _cbeat)

    # 🤝 a kept promise is a scene worth keeping: the date goes into the album with the
    # character's own best line from it as the caption.
    if promise_kept:
        kc_char = _char_by_id(content, promise_kept.get("char_id"))
        album_add(content, state, "date" if promise_kept.get("romantic") else "promise",
                  promise_kept.get("what") or "如约而至",
                  _last_line_of(said_this_turn, (kc_char or {}).get("name") or "")
                  or f"你如约而至：{promise_kept.get('what', '')}。", kc_char)

    # ✨ 稀有奇遇 (golden moment): a rare, unprompted flash the story didn't owe you —
    # program-rolled (tuning.golden_chance% per eligible turn, cooldown-gated),
    # model-written for whoever in the scene is closest to the player, celebrated,
    # and collected into the album. The 恋与深空 "金色瞬间" as a drop, not a schedule.
    state["golden_cd"] = max(0, int(state.get("golden_cd", 0) or 0) - 1)
    if (responders and not observer and not is_think and tun["golden_chance"] > 0
            and state["golden_cd"] <= 0 and not state.get("ended")
            and _rng.randint(1, 100) <= tun["golden_chance"]):
        star = max(responders, key=lambda c: (
            int((rel_all.get(c.get("id")) or {}).get("romance", 0)) * 2
            + int((rel_all.get(c.get("id")) or {}).get("closeness", 0))))
        g_scores = rel_all.get(star.get("id")) or relationships.new_scores()
        g_mode = relationships.derive_mode(star, g_scores, tun)
        g = llm.generate({"golden_moment": True,
                          "char": {"name": star.get("name"), "role": star.get("role") or "",
                                   "persona_text": (star.get("persona_text") or "")[:200],
                                   "eq_style": (star.get("eq_style") or "")[:120]},
                          "relation": relationships.name_of(g_mode),
                          "place": (current_location(content, state) or {}).get("name") or "",
                          "clock": clock_line,
                          "said_this_turn": list(said_this_turn)[-4:],
                          "mature": bool(state.get("mature"))}) or {}
        g_text = dedash((g.get("text") or "").strip())
        if g_text:
            # 标题消毒: 模型自带的括号会跟外层「」套娃 (实弹: ✨「【绿宝与板车轮声】」)
            g_title = (g.get("title") or "").strip().strip("《》「」【】『』“”") [:16] or "金色瞬间"
            state["golden_cd"] = tun["golden_cooldown"]
            sid_g = star.get("id")
            yield emit({"type": "description", "speaker_name": None,
                        "text": f"✨「{g_title}」 {g_text}"})
            old_g = rel_all.get(sid_g) or relationships.new_scores()
            rel_all[sid_g] = relationships.apply_deltas(
                old_g, 2, 2 if g_mode in ("flirt", "lover") else 1, tun)
            dc_g = int(rel_all[sid_g].get("closeness", 0)) - int(old_g.get("closeness", 0))
            dr_g = int(rel_all[sid_g].get("romance", 0)) - int(old_g.get("romance", 0))
            if dc_g or dr_g:
                prev = rel_deltas.get(sid_g) or {"name": star.get("name"),
                                                 "closeness": 0, "romance": 0}
                rel_deltas[sid_g] = {"name": star.get("name"),
                                     "closeness": int(prev.get("closeness", 0)) + dc_g,
                                     "romance": int(prev.get("romance", 0)) + dr_g}
            album_add(content, state, "golden", g_title, g_text, star)
            moments.append({"kind": "golden", "title": g_title, "name": star.get("name")})
            rel_log(state, sid_g, old_act, "golden",
                    _t(content, f"「{g_title}」：{g_text[:40]}", f"“{g_title}”: {g_text[:80]}"))
            # 💘 a golden moment is a warm spike — a styled character will pull back next time
            if relationships.love_style_of(star):
                _sim(state, sid_g)["warm_peak"] = {"t": _time_index(state), "served": False}

    # think = OBSERVE/EXAMINE. No target → look at the surroundings (where am I, what's
    # going on). With a target → examine that person: a brief intro + their CURRENT state
    # (expression / posture / appearance / mood). Narration only; no dialogue, no affinity;
    # secrets are never passed in, so observation can't leak locked truths.
    if is_think or narrate_only:
        observe_target = _char_by_id(content, target_character_id) if (is_think and target_character_id) else None
        _obs_prompt = {
            "observe": True,
            "observe_target": observe_target,
            "persona": persona_for_prompt,
            "player_input": player_input,
            "scene": current_act(content, old_act),
            "world": (content.get("story") or {}).get("world_long", "") or "",
            "world_facts": (content.get("story") or {}).get("world_facts") or "",
            "style": (content.get("story") or {}).get("style") or "",  # ✍️ 文风
            "roster": _physical_roster(content, state, persona),
            "creatures_here": creatures_here(content, state),
            "place": place,
            "knowledge": (observe_target or {}).get("knowledge", "") if observe_target else "",
            "mature": bool(state.get("mature")),
            "sandbox": sandbox_on(content),
            # 🔁 近拍旁白档 (原本只喂审稿): 独角戏最容易打转 —— 场账本在这条路上开不了
            # (它要「有台词拍」且「有别人在场」), 所以「本场已经演过」永远到不了这里。
            "recent_narr": [t for t in (state.get("_recent_narr") or []) if t][:2],
            # 🎬 写之前就把复读过的意象摊出来 (事后守卫太贵: 一响就是整包重生)
            "narr_motifs": narration_motifs(state),
            # 🏛 年代也走这条路 (Step 5 漏了 observe: 独自一人时到达/打量全归它写)
            "era": era_of(content), "device": phone_device(content),
            "player_dead": ghost,
            # observe = the PLAYER looking around → the player's own full view (they witnessed
            # everything they did); their private digest.
            "history": (history_for(beat_log, pcid) if beat_log is not None else (history or [])),
            "memory": (state.get("memory_by_char", {}) or {}).get(pcid) or state.get("memory", ""),
            "cast": [c.get("name") for c in all_chars if c.get("name")],
        }
        if plan_render_on(content) and hasattr(llm, "narrate_stream"):
            # 想/观察也逐字直出 — narration-only, so every token is kind=narration
            directed = None
            for _ns_kind, _ns_val in llm.narrate_stream(_obs_prompt):
                if _ns_kind == "token":
                    yield ("token", {"speaker": "", **_ns_val})
                elif _ns_kind == "final":
                    directed = _ns_val
            if directed is None:
                directed = llm.generate(_obs_prompt)
        else:
            directed = llm.generate(_obs_prompt)
        if _pov_break(directed, _char_name(content, pcid) or ""):
            # 🎙 the looking-around narration hijacked a character's first person → one retry
            _audit(state, "pov.enforced", True, "旁白", "观察旁白人称错误，已重写")
            retry = llm.generate({**_obs_prompt, "logic_correction": _POV_CORRECTION})
            if retry.get("beats"):
                directed = retry

        # 🚷 absent-cast hijack (Yi field case: 陆九秋 answered a look-around from another
        # room, key in hand): an observation that names an ABSENT character while carrying
        # spoken dialogue has summoned someone the ledger says isn't here → one stern retry
        def _absent_summon(d: dict) -> str:
            txt = " ".join((b.get("text") or "") for b in (d.get("beats") or []))
            if not re.search(r"「[^」]{6,}」", txt):
                return ""   # no real dialogue → mentions are just thoughts, allowed
            _here = {c.get("name") for c in all_chars if c.get("name")}
            for c in _characters(content):
                nm = c.get("name")
                if nm and nm not in _here and c.get("id") != pcid and nm in txt \
                        and c.get("id") not in _dead_ids(state):
                    return nm
            return ""
        _ab = _absent_summon(directed)
        if _ab:
            _audit(state, "obs.absent", True, _ab, "观察召来了不在场的人，已重写")
            retry = llm.generate({**_obs_prompt, "logic_correction":
                                  f"你上一版旁白让不在场的「{_ab}」出现并开口——TA根本不在这里，"
                                  f"这是硬错误。重写这段观察：只写眼前可见的环境、痕迹与在场的人；"
                                  f"名单之外的人绝不能出现、说话或递东西；玩家的疑问只能靠眼前的"
                                  f"线索回应。"})
            if retry.get("beats") and not _absent_summon(retry):
                directed = retry
        obs = [b for b in directed.get("beats", []) if b.get("type") == "description"]
        if not obs:
            obs = [{"type": "description", "speaker_name": None,
                    "text": ((directed.get("beats") or [{}])[0].get("text", ""))}]
        for b in obs:
            yield emit(b)
        affinity_delta = 0

    # 🌊 the world moves by itself: after enough quiet turns, an authored event of the
    #    current act HAPPENS (its people must be in the player's scene) — the world stops
    #    waiting for the player to make everything occur. Feeds event-gated progress too.
    if not is_think and responders:
        trig_now = set(state.get("triggered_event_ids") or [])
        if trig_now - _ev_before:
            state["world_pulse"] = 0          # something already happened this turn
        else:
            state["world_pulse"] = int(state.get("world_pulse", 0) or 0) + 1
        wev = tun["world_event_every"]
        if wev > 0 and state["world_pulse"] >= wev:
            here_ids = {c.get("id") for c in scene_characters(content, state)}
            for ev in (current_act(content, old_act) or {}).get("events", []) or []:
                eid = ev.get("id")
                who = ev.get("who_character_ids") or []
                if eid and eid not in trig_now and (not who or set(who) <= here_ids)                         and (ev.get("what_happens") or "").strip():
                    trig_now.add(eid)
                    state["triggered_event_ids"] = sorted(trig_now)
                    yield emit({"type": "description", "speaker_name": None,
                                "text": f"就在这时，{ev['what_happens']}"})
                    moments.append({"kind": "event", "label": ev["what_happens"][:40]})
                    state["world_pulse"] = 0
                    break

    # authored events may KILL (剧本说他死了，引擎里他就真的死了): every event confirmed
    # THIS turn applies its kills_character_ids — the author's word bypasses the
    # two-stage ladder. Rolled-back keyword guesses never reach here.
    _new_evs = set(state.get("triggered_event_ids") or []) - _ev_before
    if _new_evs:
        _ev_by_id = {e.get("id"): e
                     for a in (content.get("story") or {}).get("acts", []) or []
                     for e in a.get("events", []) or []}
        for _eid in sorted(_new_evs):
            _pcid_ev = (_ev_by_id.get(_eid) or {}).get("peek_cid")
            if _pcid_ev:
                # 📱🔍 作者写死的机会窗口: 事件落地, 设备就搁在那儿
                peek_open_window(state, _pcid_ev)
                _pc_ev = _char_by_id(content, _pcid_ev)
                if _pc_ev:
                    moments.append({"kind": "peek_window", "name": _pc_ev.get("name"),
                                    "device": phone_device(content)})
            for _kid in (_ev_by_id.get(_eid) or {}).get("kills_character_ids") or []:
                _kc = _char_by_id(content, _kid)
                if _kc and _kid not in _dead_ids(state) and _kid != pcid:
                    _deads = _dead_ids(state)
                    _deads.add(_kid)
                    state["dead_character_ids"] = sorted(_deads)
                    state["following"] = [f for f in (state.get("following") or [])
                                          if f != _kid]
                    moments.append({"kind": "death", "name": _kc.get("name")})
                    rel_log(state, _kid, old_act, "death",
                            _t(content, f"{_kc.get('name')} 死了。", f"{_kc.get('name')} died."))
                    for _vp in void_promises_of(state, _kid):
                        yield emit({"type": "description", "speaker_name": None,
                                    "text": f"（你们约好的（{_vp.get('what','')}），"
                                            "再也没有人来赴了。）"})

    affinity_delta = 0 if is_think else max(tun["affinity_clamp_min"],
                                            min(tun["affinity_clamp_max"], affinity_delta))
    if affinity_delta > 0:
        # diminishing returns: the warmer things already are, the less another nice line moves
        scale = max(0.3, 1 - int(state.get("affinity", 0)) / max(1, tun["affinity_taper_den"]))
        affinity_delta = max(1, int(round(affinity_delta * scale)))

    # 4. apply affinity, then decide progression. HARD GATE: if this act authored advance
    #    conditions, it advances ONLY when can_advance() is satisfied (program-checked) —
    #    the model's 推进 and affinity backstop can no longer talk past it. Acts with NO
    #    authored conditions fall back to the old soft advance (model 推进 / affinity).
    state["affinity"] = max(0, int(state.get("affinity", 0)) + affinity_delta)
    if not is_think:
        state["turns_in_act"] = int(state.get("turns_in_act", 0) or 0) + 1
    max_act = _max_act_index(content)
    if act_has_gate(content, old_act):
        new_act = (min(max_act, old_act + 1)
                   if (max_act and can_advance(content, state, old_act)) else old_act)
    else:
        # a soft act needs REAL time in it before anything can advance it — the model's
        # eager 推进 and the affinity backstop both wait out min_turns_per_act, and a turn
        # moves at most ONE act (no affinity-fueled multi-act jumps).
        if int(state.get("turns_in_act", 0)) >= tun["min_turns_per_act"]:
            backstop = 1 + state["affinity"] // tun["act_backstop_div"]  # stall safety net
            target = max(old_act + (1 if advance else 0), backstop)
        else:
            target = old_act
        target = min(target, old_act + 1)
        new_act = min(max_act, target) if max_act else target
    if new_act > old_act:
        state["turns_in_act"] = 0
    state["act"] = new_act

    # 4a. (movement is player-driven only — see the /move endpoint. The model can no longer
    #     relocate the player, so there is no model-reported place to apply here.)

    # 4b. update the stuck counter for NEXT turn: did THIS turn make headway on the gate?
    #     Progress = the act advanced, or a clue this act requires was newly unlocked. If so,
    #     reset; otherwise (still locked, still missing clues) increment. At the top tier a
    #     narrator nudge fires this turn, openly pointing at one thing left to investigate
    #     (the topic label only — never the locked body).
    still_locked = act_has_gate(content, new_act) and not can_advance(content, state, new_act)
    if new_act == old_act and still_locked:
        req = set(_advance_cond(content, old_act).get("required_fragment_ids") or [])
        made_progress = bool(req & set(newly))
        state["stuck"] = 0 if made_progress else stuck_in + 1
    else:
        state["stuck"] = 0
    # stuck hint: surfaced as a PERSISTENT top-bar string (not a chat beat), so it doesn't
    # spam the conversation. Labels only — the locked bodies are never named.
    hint = ""
    if state["stuck"] >= tun["stuck_spell"] and needed_topics:
        todo = "、".join(f"「{t}」" for t in needed_topics)
        todo_en = ", ".join(f"“{t}”" for t in needed_topics)
        hint = _t(content,
                  f"还没弄明白的是：{todo}。别干等，主动开口去问，或动手查一查，这一章的结就卡在这上面。",
                  f"Still unresolved: {todo_en}. Don't just wait — ask directly, or go dig; "
                  "this chapter is stuck on exactly this.")
    elif state["stuck"] >= tun["stuck_push"] and needed_topics:
        hint = _t(content,
                  f"眼下最该弄清的，是「{needed_topics[0]}」。不妨直接追问，或留意周围相关的破绽。",
                  f"What most needs untangling right now is “{needed_topics[0]}”. "
                  "Press the question, or watch for a crack nearby.")

    # 5. act transition: a divider, then a narration that actually carries the plot into
    #    the new act (what's changed, the new situation, the new goal) — not just a title.
    if new_act > old_act:
        nxt = current_act(content, new_act) or {}
        moments.append({"kind": "act", "index": new_act, "title": nxt.get("title", "")})
        nc = choice_for_act(content, state, new_act)
        if nc:
            state["pending_choice"] = nc
        yield emit({"type": "description", "speaker_name": None,
                    "text": _t(content, f"✦ 第{new_act}幕 · {nxt.get('title', '')} ✦",
                               f"✦ Act {new_act} · {nxt.get('title', '')} ✦")})
        # ⏳ the act anchors the clock: 剧本说这场戏在第几天什么时辰，进幕就到那个时辰。
        # Snap BEFORE the transition prose so it narrates the right hour, and void any
        # judged time_skip this turn (the anchor already placed us).
        day_pre = int((state.get("clock") or {}).get("day", 1) or 1)
        cv_snap = align_clock_to_act(content, state, new_act)
        if cv_snap:
            time_skip = ""
            yield emit({"type": "description", "speaker_name": None,
                        "text": _slot_narr(content, cv_snap["slot"], cv_snap["day"])})
            yield ("clock", cv_snap)
            dl_s = cv_snap.get("deadline")
            if dl_s and dl_s["days_left"] == 0 and cv_snap["day"] > day_pre:
                yield emit({"type": "description", "speaker_name": None,
                            "text": f"（已经是第{cv_snap['day']}天，「{dl_s['text']}」就在今天。）"})
                moments.append({"kind": "deadline", "text": dl_s["text"]})
        for b in build_act_transition(content, state, old_act, new_act, persona, llm):
            yield emit(b)

    # 💘 追求台账开卷 (2026-08-04 点火): 挂在这里而不是回合开头的 peek_tick 旁边 ——
    # 本回合的关系分 (结算 + 金色瞬间) 到这一步才全部落进 state["rel"], 早一步读到的是
    # 上一回合的旧分, 会晚整整一回合才开卷。开卷本身是无声的 (账本过线不弹窗)。
    if not observer:
        # 📇 照面即交换联系方式: 挂在这里 (met_ids 本回合已经收全) —— 陪伴链的第一环
        # 不该是道熬出来的门。
        grant_contact_on_meet(content, state)
        court_tick(content, state)

    # ━━━━━━━━━━ 管线 P9 · 世界翻页（新去处/时段/进出场/手机/结局/final） ━━━━━━━━━━
    # 5b. announce any places that JUST became reachable this turn (so a new exit never just
    #     silently shows up — the player is told they've learned of a new place to go).
    locs_after = [l for l in _locations(content) if location_available(content, state, l)]
    new_places = [l.get("name") for l in locs_after
                  if l.get("id") not in locs_before and l.get("id") != state.get("location_id") and l.get("name")]
    if new_places:
        where = "、".join(f"「{n}」" for n in new_places)
        where_en = ", ".join(f"“{n}”" for n in new_places)
        yield emit({"type": "description", "speaker_name": None,
                    "text": _t(content, f"（你打听到还有能去的地方：{where}，现在可以过去看看了。）",
                               f"(You've learned of somewhere new: {where_en}. "
                               "You can head over and take a look.)")})

    # 5c. ⏳ time flows: turns spend the current 时段; enough of them — or the scene
    #     explicitly skipping time (睡到天亮/等到入夜) — roll it over. Characters keep
    #     their 作息: the roster the player sees next reflects the new hour. A pure
    #     look-around costs no time. Sleeping past an authored deadline ends the story.
    deadline_blown = False
    if tun["turns_per_slot"] > 0 and not is_think:
        clk = dict(state.get("clock") or {})
        clk.setdefault("day", 1); clk.setdefault("slot", 0); clk.setdefault("turns_in_slot", 0)
        day_before = int(clk["day"])
        if real_time_on(content):
            steps = 0    # ⏰ real time cannot be spent — or slept away — by turns
        else:
            skip = "" if time_skip in ("无", "没有", "none") else time_skip
            if skip:
                steps = (len(SLOTS) - int(clk["slot"])) if ("次日" in skip or "天亮" in skip) else 1
                clk["turns_in_slot"] = 0
            else:
                clk["turns_in_slot"] = int(clk["turns_in_slot"]) + 1
                steps = 1 if clk["turns_in_slot"] >= tun["turns_per_slot"] else 0
                if steps:
                    clk["turns_in_slot"] = 0
            # 🎬 场账本·让位规则b: 场开着时时段不许悄悄穿越 — 自然拨格前 2 次推迟
            # (凝滞入 ticks, 收场一次性补拨), 第 3 次放行 (_slot_narr 会当场向玩家交代
            # 时段翻页)。明确的时间跳跃 (睡到天亮/次日) 是有意为之 → 收场后照常放行。
            _slx = _sl(state)
            if _slx and steps:
                if skip:
                    # 欠的格并进本次 steps 一起拨 — _sl_close 不许直接碰 state["clock"],
                    # 5c 尾部的 state["clock"] = clk 会覆写它 (自查实弹)
                    steps += int(_slx.get("ticks") or 0)
                    _slx["ticks"] = 0
                    _sl_close(state)
                elif int(_slx.get("ticks") or 0) < 2:
                    _slx["ticks"] = int(_slx.get("ticks") or 0) + 1
                    clk["turns_in_slot"] = int(tun["turns_per_slot"])   # 下一拍重新叩门
                    steps = 0
        for _ in range(steps):
            clk["slot"] = int(clk["slot"]) + 1
            if clk["slot"] >= len(SLOTS):
                clk["slot"], clk["day"] = 0, int(clk["day"]) + 1
        state["clock"] = clk
        cv = clock_view(content, state)
        if (steps or real_slot_turned) and cv:
            yield emit({"type": "description", "speaker_name": None,
                        "text": _slot_narr(content, cv["slot"], cv["day"])})
            yield ("clock", cv)
            # 🌆 while the hour turned, life happened elsewhere too
            if not observer:
                offscreen_drama(content, state, llm)
        # authored deadline: crossing INTO the day warns loudly; letting it pass ends it
        dl = (cv or {}).get("deadline")
        if dl and dl["days_left"] == 0 and int(clk["day"]) > day_before:
            yield emit({"type": "description", "speaker_name": None,
                        "text": _t(content, f"（已经是第{clk['day']}天，「{dl['text']}」就在今天。）",
                                   f"(It is already day {clk['day']}. “{dl['text']}” is today.)")})
            moments.append({"kind": "deadline", "text": dl["text"]})
        elif dl and dl["days_left"] < 0 and not state.get("ended"):
            deadline_blown = True
        # 🤝 爽约: time rolled past a promise the player never showed for. It stings —
        # and the stood-up character will bring it up next time they meet (once).
        now2 = _time_index(state)
        for pr in (state.get("promises") or []):
            if pr.get("status") == "open" and _promise_index(pr) < now2:
                pr["status"] = "missed"
                mc = pr.get("char_id")
                old_sc = (state.get("rel") or {}).get(mc) or relationships.new_scores()
                state.setdefault("rel", {})[mc] = relationships.apply_deltas(
                    old_sc, -tun["promise_break_cost"],
                    -tun["promise_break_cost"] if pr.get("romantic") else 0, tun,
                    trust_delta=-5)   # 🛡 爽约塌信任, 比掉好感更疼
                moments.append({"kind": "promise", "status": "missed",
                                "name": pr.get("char_name"), "what": pr.get("what")})
                rel_log(state, mc, old_act, "promise",
                        _t(content, f"你爽约了：{pr.get('what','')}。",
                           f"You stood them up: {pr.get('what','')}."))
                yield emit({"type": "description", "speaker_name": None,
                            "text": _t(content,
                                       f"（你猛然想起，和{pr.get('char_name','')}约好的"
                                       f"（{pr.get('what','')}）已经过了时辰。）",
                                       f"(It hits you — the promise you made with "
                                       f"{pr.get('char_name','')} ({pr.get('what','')}) "
                                       "has already come and gone.)")})
        # 📋 差事黄了: an open quest whose deadline day has slipped past fails for real
        for q in (state.get("quests") or []):
            if q.get("status") == "open" and q.get("deadline_day") \
                    and int(clk["day"]) > int(q["deadline_day"]):
                q["status"] = "failed"
                moments.append({"kind": "quest", "status": "failed", "title": q.get("title")})
                yield emit({"type": "description", "speaker_name": None,
                            "text": f"（{q.get('title')}的期限过了。这单，黄了。）"})

    # 5d. people come and go with the hour and the act — never silently. Anyone the
    #     roster diff shows arriving gets a concrete line (looks + role); anyone leaving
    #     gets a farewell that says where they've gone when the作息 knows. The cast bar
    #     never just mutates behind the player's back.
    here_now = scene_characters(content, state)
    here_after = {c.get("id") for c in here_now if c.get("id")}
    dead_now = _dead_ids(state)
    # 🦇 the hunter's comings and goings are narrated by its authored cues (先声后形) —
    # a generic entrance/farewell beat on top would announce it like a house guest
    _tid = (threat_mod.cfg(content) or {}).get("char_id")
    for c in here_now:
        if c.get("id") in (here_after - here_before) and c.get("id") != pcid \
                and c.get("id") != _tid and c.get("id") not in emergent_ids:
            yield emit(entrance_beat(content, state, c))
    farewell_budget = 2  # spoken goodbyes per turn; any further departures narrate only
    for cg in _characters(content):
        if cg.get("id") in (here_before - here_after) and cg.get("id") != pcid \
                and cg.get("id") != _tid and cg.get("id") not in dead_now:
            if farewell_budget > 0:
                farewell_budget -= 1
                for b in farewell_beats(content, state, cg, llm):
                    yield emit(b)
            else:
                yield emit(exit_beat(content, state, cg))

    # 5e. 📱 the world texts back: absent characters with a live reason (a promise whose
    #     hour is next / just stood up / a lover just parted from) reach out. Capped.
    if not observer and not is_think:
        for ev in phone_deliveries(content, state, here_after, llm):
            yield ("phone", ev)
            moments.append({"kind": "phone", "name": ev["name"], "device": ev["device"]})

        # 📟 主动找你 (Yi 2026-08-05: 让玩家感觉总是有人在找他)。挂在 phone_deliveries
        # 【之后】—— 那里发的是有后果的消息 (约定到点、爽约、刚分别), 这里发的是寒暄
        # 与余温。顺序即优先级: 实弹 test_promise_reminder —— 我原先插在它前面, 于是
        # 「别忘了夜里后巷见」被一条自我介绍挤成第二条, 玩家一眼看到的成了打招呼。
        # busy 把本回合已经发过话的人让出去, 一个人一回合只响一次。
        _busy = {str(m.get("name") or "") for m in moments if m.get("kind") == "phone"}
        _reach = list(reachout_after_event(content, state, llm, moments, _busy))
        _busy |= {str(e.get("name") or "") for e in _reach}
        _reach += list(reachout_on_meet(content, state, llm, _busy))
        for ev in _reach:
            yield ("phone", ev)
            moments.append({"kind": "phone", "name": ev["name"], "device": ev["device"]})

    # 5f. 🚪 预定命运 (authored dooms): on the appointed night someone is CARRIED OFF —
    #     unless the player earned the prevention (knowledge + trust), or is standing
    #     with them that night (the building waits; it doesn't take witnesses). The
    #     taken are NOT dead — they are somewhere, and can be found. Story-agnostic:
    #     story.dooms = [{id, day, char_id, to, text, warn_text, prevented_text,
    #                     prevent:{fragment_ids, closeness_min, flags}}].
    if not observer and not state.get("ended"):
        _clkd = dict(state.get("clock") or {})
        _dday = int(_clkd.get("day", 1) or 1)
        _dslot = int(_clkd.get("slot", 0) or 0)
        _fired = set(state.get("dooms_fired") or [])
        _warned = set(state.get("dooms_warned") or [])
        _here_ids_now = {c.get("id") for c in scene_characters(content, state)}
        for dm in (content.get("story") or {}).get("dooms") or []:
            did = (dm.get("id") or f"doom_{dm.get('char_id')}").strip()
            dch = _char_by_id(content, dm.get("char_id"))
            d_day = int(dm.get("day") or 0)
            if not dch or d_day <= 0 or did in _fired or dch.get("id") in _dead_ids(state):
                continue
            due = _dday > d_day or (_dday == d_day and _dslot >= len(SLOTS) - 1)
            if not due:
                # the appointed day dawns — the dread gets a date, said out loud once
                if _dday == d_day and did not in _warned:
                    _warned.add(did)
                    yield emit({"type": "description", "speaker_name": None,
                                "text": (dm.get("warn_text") or "").strip()
                                or _t(content, "（说不清为什么，你觉得就是今夜。）",
                                      "(You can't say why — but you know it's tonight.)")})
                    moments.append({"kind": "deadline",
                                    "text": _t(content, f"{dch.get('name')}的那一夜",
                                               f"{dch.get('name')}'s night")})
                continue
            if dch.get("id") in _here_ids_now:
                continue  # you are WITH them tonight — it does not take witnesses
            pv = dm.get("prevent") or {}
            _fl = state.get("flags")
            _fl_have = set(_fl.keys()) if isinstance(_fl, dict) else set(_fl or [])
            prevented = bool(pv) and (
                set(pv.get("fragment_ids") or [])
                <= set(state.get("unlocked_fragment_ids") or [])
            ) and (
                int(((state.get("rel") or {}).get(dch["id"]) or {}).get("closeness") or 0)
                >= int(pv.get("closeness_min") or 0)
            ) and (set(pv.get("flags") or []) <= _fl_have)
            _fired.add(did)
            if prevented:
                yield emit({"type": "description", "speaker_name": None,
                            "text": (dm.get("prevented_text") or "").strip()
                            or _t(content, f"（那一夜过去了。{dch.get('name')}还在——因为你。）",
                                  f"(The night passes. {dch.get('name')} is still here — "
                                  "because of you.)")})
                moments.append({"kind": "doom", "status": "averted", "name": dch.get("name")})
                rel_log(state, dch["id"], old_act, "doom",
                        _t(content, "那一夜没有轮到TA——因为你。",
                           "That night did not take them — because of you."))
                _audit(state, "doom", True, did, "averted")
            else:
                if (dm.get("to") or "").strip():
                    state.setdefault("taken", {})[dch["id"]] = dm["to"].strip()
                yield emit({"type": "description", "speaker_name": None,
                            "text": (dm.get("text") or "").strip()
                            or _t(content, f"（{dch.get('name')}不见了。没有人提起这件事。）",
                                  f"({dch.get('name')} is gone. No one speaks of it.)")})
                moments.append({"kind": "doom", "status": "taken", "name": dch.get("name")})
                rel_log(state, dch["id"], old_act, "doom",
                        _t(content, "TA在那一夜被带走了。", "That night, they were taken."))
                _audit(state, "doom", True, did, "taken")
        state["dooms_fired"] = sorted(_fired)
        state["dooms_warned"] = sorted(_warned)

    # 🧠 watching someone go costs; a no-loss turn with the hunter far away lets the
    # player breathe a little of it back (tension-release lives in the ledger too)
    if _scfg and not state.get("ended"):
        _sev_all = []
        for _m in list(moments):
            _d = {"death": -5, "dying": -3}.get(_m.get("kind"), 0)
            if _m.get("kind") == "doom" and _m.get("status") == "taken":
                _d = -6
            if _d:
                _sev = sane_delta(content, state, _d, "目睹")
                if _sev:
                    _sev_all.append(_sev)
        moments.extend(_sev_all)
        if int(state.get("sanity", 0)) >= _san0 and _scfg["regen"] and not observer \
                and (threat_view or {}).get("band") in (None, "far"):
            sane_delta(content, state, _scfg["regen"], "缓过来一点")

    # 6. ending check. Authored endings are MILESTONES (true/normal/bad) — reaching one
    #    shows its narration but the open world keeps going, so the player can explore on
    #    and even upgrade to a higher-tier ending later. Only a fatal action (death) is
    #    terminal and locks the run. Each milestone announces once (tracked by id).
    if pressure_blown and pcfg:
        authored = _ending_by_id(content, pcfg.get("ending_id")) or {}
        model_ending = None
        candidate = {"id": authored.get("id") or "pressure",
                     "kind": authored.get("kind", "bad"),
                     "title": authored.get("title") or f"{pcfg.get('name','压力')}到达顶点",
                     "text": authored.get("text") or "",
                     "terminal": True}
    elif _scfg and int(state.get("sanity", 1) or 0) <= 0 and not state.get("ended"):
        # 🧠 the mind snaps before the body does — a sanity break is terminal
        authored = _ending_by_id(content, _scfg.get("ending_id")) or {}
        model_ending = None
        candidate = {"id": authored.get("id") or "sanity",
                     "kind": authored.get("kind", "bad"),
                     "title": authored.get("title") or f"{_scfg['name']}崩断",
                     "text": authored.get("text") or "",
                     "terminal": True}
    elif deadline_blown:
        ccfg = clock_cfg(content)
        authored = _ending_by_id(content, ccfg.get("deadline_ending_id")) or {}
        model_ending = None
        candidate = {"id": authored.get("id") or "deadline",
                     "kind": authored.get("kind", "bad"),
                     "title": authored.get("title")
                     or f"{(ccfg.get('deadline_text') or '大限').strip()}，为时已晚",
                     "text": authored.get("text") or "",
                     "terminal": True}
    else:
        candidate = evaluate_ending(content, state, model_ending)
    fired = None
    if candidate:
        achieved = set(state.get("achieved_endings") or [])
        eid = candidate.get("id")
        terminal = bool(candidate.get("terminal"))
        if terminal or eid not in achieved:
            fired = candidate
            kind = candidate.get("kind", "normal")
            if eid:
                achieved.add(eid)
            state["achieved_endings"] = sorted(x for x in achieved if x)
            state["ending"] = candidate  # last reached, for replay display
            if terminal:
                state["ended"] = True
            head = ({
                "death": "—— You died ——",
                "bad": "—— Bad Ending ——",
                "true": "—— Ending Reached · True Ending ——",
                "normal": "—— Ending Reached ——",
            } if lang_of(content) == "en" else {
                "death": "—— 你死了 ——",
                "bad": "—— 坏结局 ——",
                "true": "—— 达成结局 · 真结局 ——",
                "normal": "—— 达成结局 ——",
            }).get(kind, "—— Ending Reached ——" if lang_of(content) == "en" else "—— 达成结局 ——")
            title = candidate.get("title") or ""
            moments.append({"kind": "ending", "ending_kind": kind, "title": title,
                            "terminal": terminal})
            album_add(content, state, "ending", title or head,
                      (candidate.get("text") or "").strip() or f"{head} {title}".strip(),
                      rarity=3 if kind == "true" else 1 if kind in ("bad", "death") else 2)
            yield emit({"type": "description", "speaker_name": None,
                        "text": f"{head}  {title}".strip()})
            if candidate.get("text"):
                yield emit({"type": "description", "speaker_name": None, "text": candidate["text"]})
            if not terminal:
                yield emit({"type": "description", "speaker_name": None,
                            "text": _t(content,
                                       "（你已抵达一种结局，但故事并未就此打住。你仍可以留在这个世界继续探索。）",
                                       "(You have reached an ending — but the story doesn't stop here. "
                                       "You may stay in this world and keep exploring.)")})

    # 6b. roll older turns into the long-horizon digest (every ~MEMORY_BATCH turns). Done
    #     here — after the reply beats have already streamed — so it never delays what the
    #     player sees; the refreshed digest takes effect on the next turn.
    if beat_log is not None:
        # per-character: each responder folds THEIR OWN witnessed history into THEIR digest
        # (isolation holds long-term). Only present responders this turn need updating.
        # ⚡ 4秒军令: 折叠彻底出关键路径 — 后台折, 下一回合合账 (曾 join 1.5~2s
        # 拖住建议/收尾/落库, 是整回合 p90 尖刺的元凶之一)
        _folds_async(state, list(responder_hist.items()), llm)
        # 🫂 定时重判关系 (Yi 2026-08-06)。搭在这里是因为 responder_hist 已经把
        # 每个角色【自己亲历的】那份 history 备好了 —— 判官看的必须是 TA 看得见的
        # 那些话, 不是玩家的全部人生。节奏另算: 记忆折叠要等 history 到 20 条,
        # 而生产中位一局 14 拍, 挂那个节奏等于大多数人永远等不到。
        _n = int(state.get("turn_seq") or 0)
        _due = [(cid, h) for cid, h in responder_hist.items()
                if relation_read_due(state, cid, _n)]
        if _due:
            relation_reads_async(content, state, _due, llm)
    else:
        _update_memory(state, history, llm)  # legacy/global (tests, opening)

    # 7. immersive scene (background / mood / sfx) from this turn's text
    # 🎣 pending environmental takes: prose ratified → booked into the pocket
    settle_pending_takes(state, all_beats)
    # 🎒 隔离区提及计数 (P3 §4.1): 正文再次点到在押名字 → hits+1 (提及≥2 可转正)
    items_mod.note_mentions(state, " ".join((b.get("text") or "") for b in all_beats))
    # 🧭 文实合一兜底: 旁白把人写到了别的已知地点而账本没动 → 确定性收账
    if not observer and settle_prose_arrival(content, state, all_beats, _loc0,
                                             sp_id=state.get("last_speaker_id")):
        pass
    # 🩹 AWAY 粘钉自愈 (排在收账后: 若这拍换了场, 解钉解到新地点)
    if not observer:
        _heal_away_pins(content, state, all_beats, away0=_away0)
    scene = scene_mod.classify_scene(
        " ".join(b.get("text", "") for b in all_beats), default_bg=story_default_bg(content)
    )
    # ✍️ 编剧申报的情绪压过关键词猜 (剧组 P2: mood 两套推导收敛, 猜是兜底)
    _MOOD_ZH = {"日常": "daily", "温馨": "warm", "浪漫": "romantic", "悲伤": "sad",
                "孤独": "lonely", "悬疑": "mystery", "诡异": "eerie",
                "紧张": "tense", "战斗": "battle"}
    _mc = _MOOD_ZH.get(str(flags.get("mood_claim") or "").strip())
    if _mc:
        scene["mood"] = _mc
        _audit(state, "scene.mood", True, f"编剧:{_mc}")
    state["scene"] = scene
    # 🎯 目标栈镜像 (治单槽盖写: 开场由头曾只活一回合就被这行用幕目标顶掉)
    state["goal"] = goal_top(content, state)
    progress = act_progress(content, state, state["act"])  # clue checklist for the (new) act
    location = location_view(content, state)  # current place w/ exits filtered to unlocked ones

    # 🎟 台词里的邀约 → 确认条。锁在 invite_chip 里 (INVITE_MOVE), 四个由头共用一口 ——
    # 从前这段逻辑内联在这里各写一遍, 锁一处漏三处。Yi 2026-08-06:「不通过文字控制！」
    move_request = None
    if primary_invite and not observer:
        move_request = invite_chip(content, state, primary_invite,
                                   primary_id, primary_name_for_invite, llm=llm)
        # 🤝 确认条照弹 (要点就点), 但同时记下这张邀约 —— 玩家下一句直接说「好啊跟你去」
        # 也算数。按钮和嘴两条路都通, 这才是「引导」: 不逼玩家用我们规定的方式同意。
        note_invite(state, move_request)
        if move_request and move_request.get("minted"):
            flags["content_mutated"] = True
            content_mutated = True
            growth_mod.note_mint(state)
            _audit(state, "place.mint", True, move_request.get("to_name", ""), "听说的去处已立档")
    # 🌱 生长收卷第二步 (Yi 四条拍板): 地点种子过判官铸造; 填无入账升级档;
    # 铸造成功共享额度 (note_mint), 确认条与提及即立档同款 (只立档不落脚)
    if _ws_mode and ws_askable and not observer:
        _wso = str(flags.get("world_seed_out") or "").strip()
        try:
            from .. import metrics as _gm2
        except Exception:
            _gm2 = None
        if _wso.startswith(("地点：", "地点:")):
            _wsn = _wso.split("：", 1)[-1].split(":", 1)[-1].strip().strip("「」\"'")[:12]
            try:
                _wsl = generate_and_move(content, state, _wsn, llm=llm, move=False)
            except ValueError:
                _wsl = None
            if _wsl and _wsl.get("id"):
                flags["content_mutated"] = True
                content_mutated = True
                growth_mod.note_mint(state)
                _audit(state, "growth.seed", True, _wsl.get("name", ""), "预算铸造·地点")
                if _gm2:
                    _gm2.log("growth", ev="mint", ch="seed_place")
                # 🎟 立档照旧, 但不再变成一个能走人的按钮 (INVITE_MOVE)
                if move_request is None and INVITE_MOVE:
                    move_request = {"to": _wsl["id"], "to_name": _wsl.get("name"),
                                    "by_id": None, "by_name": None, "self_go": True,
                                    "minted": True}
            else:
                _audit(state, "growth.seed", False, _wsn, "判官驳回")
                if _gm2:
                    _gm2.log("growth", ev="reject", ch="seed_place")
                if not LLM_MAP_WRITES:
                    # 🔒 锁下地点种子无路可铸 (schema 已不教「地点：」, 这是模型不听话
                    #    的兜底): 烧掉本期预算, 否则驳回不销账, due 每拍重催成永动循环
                    growth_mod.note_mint(state)
        elif _wso.startswith(("人物：", "人物:")):
            # 出生已并入 new_char 管线; 出生成功与否看 emergent_ids
            if emergent_ids:
                growth_mod.note_mint(state)
                _audit(state, "growth.seed", True, _wso[:16], "预算铸造·人物")
                if _gm2:
                    _gm2.log("growth", ev="mint", ch="seed_char")
            else:
                _audit(state, "growth.seed", False, _wso[:16], "出生管线驳回")
                if _gm2:
                    _gm2.log("growth", ev="reject", ch="seed_char")
        elif flags.get("dir_ran"):
            # 只有主拍真跑过才算「填无」—— think 轮/空场轮根本没问过 world_seed,
            # 不许记空账升硬指令 (审计实弹: 死亡玩家每轮被记一次幻影拒绝)
            _bl = growth_mod.note_blank(state)
            _audit(state, "growth.seed", False, "无",
                   f"连续第{_bl}次{'·下次升硬指令' if _bl >= growth_mod.BLANK_ESCALATE else ''}")
            if _gm2:
                _gm2.log("growth", ev="blank", n=_bl, mode=_ws_mode)
    # 🚶 探索硬出口 (②): 玩家亲口要「出去走走」却没有目的地 → 判官发明一个贴世界观
    # 的去处, 确认条自去; 吃同一本生长额度
    if move_request is None and not observer and sandbox_on(content) \
            and growth_mod.explore_intent(player_input):
        try:
            _expl = generate_and_move(content, state, "附近随便走走能撞见的去处",
                                      llm=llm, move=False, invent=True)
        except ValueError:
            _expl = None
        if _expl and _expl.get("id"):
            flags["content_mutated"] = True
            content_mutated = True
            growth_mod.note_mint(state)
            _audit(state, "growth.explore", True, _expl.get("name", ""), "探索发明")
            try:
                from .. import metrics as _gm3
                _gm3.log("growth", ev="mint", ch="explore")
            except Exception:
                pass
            # 🎟 立档照旧, 但不再变成一个能走人的按钮 (INVITE_MOVE)
            if INVITE_MOVE:
                move_request = {"to": _expl["id"], "to_name": _expl.get("name"),
                                "by_id": None, "by_name": None, "self_go": True,
                                "minted": True}
    # 🎟 玩家自己说出口的去处: 同一口闸, 没有邀请人 (INVITE_MOVE 关着时只立档不给条)
    if move_request is None and emergent_dest and not observer \
            and not resolve_location(content, emergent_dest):
        _chip = invite_chip(content, state, emergent_dest, None, None, llm=llm)
        if _chip:
            move_request = _chip
            if _chip.get("minted"):
                flags["content_mutated"] = True
                content_mutated = True
                growth_mod.note_mint(state)   # 🌱 双通道共享额度
                _audit(state, "place.mint", True, _chip.get("to_name", ""), "你说起的去处已立档")

    # 🗺 玩家说了要走却走不了 —— 把这道摩擦摆到明处 (Yi 2026-08-08 拍板 A)。
    # 走 moments→toast 那条管道, 不进正文: 引擎硬写的旁白不过文风, 还会进历史污染示范。
    # ⚠️ 确认条已经在屏幕上时不许再弹 —— 一个「跟 TA 去」的按钮配一条「自己去点地图」
    #    的提示, 是两个不一样的指路, 玩家只会更懵 (2026-08-08 邀约锁开回来时的接缝)。
    if _wants_move and not move_request:
        moments.append(map_move_hint())

    # 💡 建议单一来源 (Yi 2026-07-20 重做): 导演随主拍写的两条, 不够垫底句补齐。
    # 旧的独立小调用/门控模板层已删 — 少一层逻辑, 少一次调用, 一个声音。
    suggestions = []
    if not (fired and fired.get("terminal")):
        suggestions = ensure_three_suggestions(
            [s for s in (flags.get("dir_suggestions") or []) if s][:2], [], content)

    # ⚖️ 命运抉择: every N turns (tuning key_choice_every, 0=off) the story throws a
    # high-authority fork generated from the LIVE scene. Options are engine-verified and
    # typed — the pick will be ENFORCED (death booked / relocation applied / direction
    # mandated at depth-0), not merely narrated. God mode gets them too: there the player
    # IS the hand of fate, and the options read as decrees.
    if not (fired and fired.get("terminal")) and not state.get("ended"):
        state["fate_turns"] = int(state.get("fate_turns") or 0) + 1
        _lo = int(tun.get("key_choice_min") or 0)
        _hi = max(_lo, int(tun.get("key_choice_max") or 0))
        if _lo and not state.get("pending_choice"):
            # the fork ARMS at a random point inside [min, max]; once armed it waits for
            # a HIGH-TENSION turn (dice rolled / a moment landed / a truth unlocked /
            # intimate scene / pressure blown) so fate knocks at a dramatic beat, not
            # over breakfast. If no tension shows for 6 more turns, it fires anyway.
            if not state.get("fate_next"):
                state["fate_next"] = random.randint(_lo, _hi)
            armed = state["fate_turns"] >= int(state["fate_next"])
            tension = bool(dice) or bool(moments) or bool(newly)                 or heat_mod.stage(state) >= 1 or bool(flags.get("pressure_blown"))
            overdue = state["fate_turns"] >= int(state["fate_next"]) + 6
            if armed and (tension or overdue):
                _live = "玩家：" + (player_input or "") + " ／ " + " ".join(
                    (b.get("text") or "") for b in all_beats[-6:])
                _fc = fate_generate(content, state, llm, observer=observer, recent=_live)
                if _fc:
                    state["pending_choice"] = _fc
                    state["fate_turns"] = 0
                    state["fate_next"] = random.randint(_lo, _hi)
                    _audit(state, "fate.offered", True, _fc["prompt"][:30])

    # 🌅 新的一天 = 自由活动时段: 建议换成「去哪找谁」的菜单 (作息+关系温度长出来的),
    # 剧情不抢戏 — 客户端配过场卡与输入锁
    _day1 = int((state.get("clock") or {}).get("day", 1) or 1)
    new_day = _day1 if _day1 > _day0 and not (fired and fired.get("terminal")) else None
    if new_day:
        _free = free_day_suggestions(content, state)
        if _free:
            suggestions = _free
        _audit(state, "day.free", True, f"day{_day1} menu:{len(_free)}")

    # 🪞 玩家档案 (活世界 P2): 记回合, 到节拍就蒸馏一次; 见证名单=此刻在场的角色。
    # ⚡ 蒸馏在后台线程 (Yi: 等待太长 — 曾最多顶 10s), 结果下一回合 apply_pending 合账
    if profile_mod.apply_pending(state):
        _audit(state, "profile.merged", True, "后台蒸馏入账")
    if player_input and channel in ("say", "do") and not observer:
        if profile_mod.note_turn(state):
            _wit = [{"id": c.get("id"), "name": c.get("name")}
                    for c in scene_characters(content, state)
                    if c.get("id") and c.get("id") != state.get("player_character_id")]
            _rec = [f"玩家：{player_input}"] + [
                f"{b.get('speaker_name') or '旁白'}：{(b.get('text') or '')[:100]}"
                for b in all_beats[-12:]]
            profile_mod.distill_async(content, state, _rec, _wit, llm)
            _audit(state, "profile.distill", True, f"后台 wit={len(_wit)}")

    # 🎬 场账本落账 (docs/scene-ledger.md): 开/更新/收场 + 问答账 — 必须在 final 之前
    # (final 之后 router 才持久化 state, 晚了就丢账)。申报优先, 兜底确定性, 零 LLM。
    try:
        _sl_settle(content, state, tun, all_beats, player_input, flags, channel, pcid)
    except Exception:
        pass
    # 🔎 导演审稿的比对底稿: 本回合正文留档, 下回合据此识破「整局复读」;
    # 旁白单独留近3拍环形档, 供第④检识破「招牌动作/景物三拍复读」(蝴蝶刀实弹)
    state["_last_text"] = " ".join((b.get("text") or "") for b in all_beats)[:1600]
    _narr_now = " ".join((b.get("text") or "") for b in all_beats
                         if b.get("type") == "description")[:1200]
    if _narr_now.strip():
        # 留档从 3 拍扩到 8 拍: 守卫仍只看最近 2 拍, 但【意象复读】要跨更多拍才数得出来
        # (「桃花眼」是隔三拍出现一次慢慢磨死人的, 不是连着三拍蹦出来)。
        state["_recent_narr"] = ([_narr_now] + list(state.get("_recent_narr") or []))[:NARR_LEDGER]

    # 建议随档持久化: 重开 App 恢复存档时, 上一轮的下一步 chips 原样还在 (竖屏 App 常驻件)
    # 🧭 口味罗盘 (Yi: 了解玩家喜好非常重要): 引擎已知的硬信号记账, 零调用;
    # 玩家点了上一轮的建议 chips = 亲手投票, 当回合命中加倍
    if not observer:
        _hits = []
        if provisional_asks or taste_mod.curious(player_input):
            _hits.append("探查")
        if dice is not None:
            _hits.append("冒险")
        if move_request is not None or state.get("location_id") != _loc0:
            _hits.append("探索")
        if any(int((d or {}).get("romance", 0) or 0) > 0 for d in rel_deltas.values()):
            _hits.append("心动")
        if not _hits and channel == "say":
            _hits.append("闲话")
        _clicked = (player_input or "").strip() in {str(s) for s in
                                                    (state.get("suggestions") or [])}
        taste_mod.note(state, _hits, clicked=_clicked)
    suggestions = set_suggestions(state, suggestions, content)

    _final_payload = {
        "state": state,
        "newly_unlocked": newly,
        # only suppress suggestions on a terminal (death) ending; milestones keep playing
        "suggestions": suggestions,
        "new_day": new_day,   # 🌅 这一回合翻了天 → 客户端出「新的一天·自由活动」过场

        "scene": scene,
        "ending": fired,
        # who's addressable now (a new act may have brought someone onstage); in character
        # mode the embodied character is not in the list (you don't address yourself)
        "cast": cast_for(content, state["act"], exclude_id=pcid if mode == "character" else None,
                         state=state),
        "here": scene_cast(content, state, exclude_id=pcid if mode == "character" else None),
        "beasts": creatures_here(content, state, mark=False),   # 🐲 台上要站巨兽
        "factions": factions_mod.view(content, state),   # 🏛 玩家的江湖名声
        "following": list(state.get("following") or []),
        "goal": state["goal"],
        "progress": progress,  # {items:[{label,done}], done, total} — the clue checklist
        "hint": hint,          # persistent stuck-hint for the top bar ("" = not stuck / hide)
        "moments": moments,    # threshold moments this turn (UI celebration banners)
        "dice": dice,          # 🎲 this turn's fate roll (already streamed as its own event)
        "content_mutated": content_mutated,  # 👋 run grew a new character → persist pinned copy
        "pressure_view": ({"name": pcfg.get("name"), "value": int(state.get("pressure", 0))}
                          if pcfg else None),
        "threat_view": threat_view,  # 🦇 {name,band,alert} the hunter's felt distance (or None)
        "sanity_view": sanity_view_of(content, state),  # 🧠 {name,value,max,label} (or None)
        "clock_view": clock_view(content, state),  # ⏳ {day,slot,label,deadline?} or None
        "promises": promises_view(content, state),  # 🤝 open appointments, soonest first
        "player_events": player_events_view(content, state),  # 🗓 玩家自己的行程
        "player_notes": player_notes_view(state),  # 📔 玩家备忘录 (叙事罗盘)
        "phone_unread": phone_total_unread(content, state),  # 📱 badge (texts + letters)
        "verdict": verdict_view(content, state),  # 🔍 case-closing panel (None until unlocked)

        "pending_choice": state.get("pending_choice"),  # unanswered key-moment decision
        "rel_deltas": rel_deltas,  # per-char ♥ movement this turn (UI floating chips)
        "location": location,  # {id,name,detail,exits} the player's current place (or None)
        "move_request": move_request,  # {to,to_name,by_id,by_name} a char wants to lead you there (confirm)
        "relations": relations_summary(content, state),  # {cid:{mode,mode_name,...}} toward player
        # 📋 the turn's event audit: rejections logged where they happened + accepts derived
        # from moments — the debuggable "what the engine decided and why" sheet
        "cultivation": cult_view(content, state),  # ⚡ rank + bottleneck progress (or None)
        "audit": _finish_audit(state, moments),
        "music": None,   # 🎼 乐师判词 post-final 收卷后回填 (router 流末才读 final)
    }
    yield ("final", _final_payload)

    # 📊 节奏验收三数 (Spec): 句长分布/沉默率/节奏带 — metrics "pace" 事件
    try:
        from .. import metrics as _pm
        _dl = [len((b.get("text") or "")) for b in all_beats
               if b.get("type") == "dialogue"][:10]
        _pm.log("pace", band=_pace["band"], dlens=_dl,
                silence=bool(not _dl and any(b.get("type") == "description"
                                             for b in all_beats)))
    except Exception:
        pass
    # 🎼 乐师收卷 (post-final): 主拍时起的判官线程此刻多半早已回卷 — join≈0;
    # 万一没回, 最多等 6s (音乐迟到一拍不伤, 抢戏才伤)。router 与 run_turn 包装器
    # 都在流耗尽后才读 final 引用, 这里的回填照样落地。
    if _music_job.get("thread") is not None:
        try:
            _music_job["thread"].join(timeout=6.0)
            _final_payload["music"] = settle_music(
                state, (_music_job.get("box") or {}).get("out"))
        except Exception:
            pass
    # 📔 每日回忆结算 (Yi 2026-07-25 二改: 回忆不能只有一种 — 通盘总结当天互动
    # 打标签, 收进小手机回忆册, 零弹窗零打扰, 翻天定时更新)。
    if new_day and not observer:
        try:
            _hc = _heart_candidate(content, state, beat_log, history)
            if _hc is not None:
                _hcid = _hc.get("id")
                # assistant 拍已自带「说话人：台词」前缀, 再包主角名会把别人的话
                # 错记到日记主角头上 (审计实弹: 群戏日记张冠李戴)
                _off = [f"对方：{b.get('content', '')[:60]}" if b.get('role') == 'user'
                        else str(b.get('content') or '')[:60]
                        for b in (history_for(beat_log, _hcid) if beat_log is not None
                                  else (history or []))[-20:]]
                _pho = [f"{'对方' if m.get('from') == 'me' else _hc.get('name')}：{str(m.get('text') or '')[:60]}"
                        for m in _thread(state, _hcid).get("msgs", [])[-10:]]
                if len(_off) + len(_pho) >= 4:   # 相处太少就别硬袒露
                    _sc = (state.get("rel") or {}).get(_hcid) or {}
                    _hd = llm.generate({"heart_digest": True,
                                        "who": {"名字": _hc.get("name"),
                                                "人设": (_hc.get("persona_text") or "")[:160],
                                                "表达方式": _hc.get("eq_style") or ""},
                                        "relation": relationships.name_of(
                                            relationships.derive_mode(_hc, _sc, tun),
                                            lang_of(content)),
                                        "offline": _off, "phone": _pho}) or {}
                    _tag = str(_hd.get("tag") or "").strip()
                    _txt = dedash(str(_hd.get("text") or "").strip())[:220]
                    if _tag in _MEM_TAGS and _txt:
                        _ttl = dedash(str(_hd.get("title") or "").strip())[:10]
                        _hh = dedash(str(_hd.get("heart") or "").strip())[:80] \
                            if _tag in _DIARY_TAGS else ""
                        _day_no = int((state.get("clock") or {}).get("day", 1) or 1) - 1
                        if _tag in _DIARY_TAGS:
                            # 📔 Yi 定 (2026-07-25): 心动/甜蜜是 TA 的私心话, 只住 TA 的
                            # 日记本 (好感到暧昧/恋人档才解锁), 不进玩家回忆册
                            _diary_add(state, _hcid, {
                                "day": _day_no, "tag": _tag,
                                "title": _ttl or _t(content, "这一天", "the day"),
                                "text": _txt, "heart": _hh})
                            _audit(state, "day.diary", True,
                                   f"day{_day_no}·{_tag}·{_hc.get('name')}")
                        else:
                            album_add(content, state, "daily",
                                      f"{_MEM_TAGS[_tag]}{_tag}·{_ttl or _t(content, '这一天', 'the day')}",
                                      _txt[:200], _hc, rarity=1)
                            _audit(state, "day.memory", True,
                                   f"day{_day_no}·{_tag}·{_hc.get('name')}")
                    else:
                        _audit(state, "day.memory", False, _hc.get("name", ""),
                               "今天没记（判官没给出合规标签）")
        except Exception:
            pass
    # 🎥 场记: 后台记帧, 下一回合合账 (4秒军令 — 旧注释说 post-final 玩家不用等,
    # 但收尾事件/落库都排在生成器耗尽之后, 这 ~1.5s 一直挡着输入框解锁)
    try:
        track_frames_async(content, state, persona, all_beats, llm)
    except Exception:
        pass


def scene_cast(content: dict[str, Any], state: dict[str, Any],
               exclude_id: str | None = None) -> list[dict[str, Any]]:
    """The characters in the player's CURRENT scene (light dicts for the UI), each flagged
    with whether they are currently following the player. This is "who is in the room with
    you right now" — drives the on-screen roster + follow buttons."""
    following = set(state.get("following") or [])
    rel_all = state.get("rel") or {}
    tun = tuning_for(content)
    out = []
    for c in scene_characters(content, state):
        if c.get("id") == exclude_id:
            continue
        scores = rel_all.get(c.get("id")) or relationships.new_scores()
        out.append({"id": c.get("id"), "name": c.get("name"),
                    "is_lead": c.get("is_lead", False), "avatar_url": c.get("avatar_url"),
                    "following": c.get("id") in following,
                    "hp": char_hp(state, c.get("id")),  # 🩸 graded life state for the bar
                    "can_follow": relationships.can_follow(c, scores, tun)})  # 好感够不够请动
    return out


# 🫂 关系重判的节奏 (Yi 2026-08-06:「这个关系要定时结合上下文得出判断」)。
#
# 为什么不挂在记忆折叠上: 那条路要等 history 长到 MEMORY_WINDOW+MEMORY_BATCH=20 条
# 才第一次开火, 而生产中位一局只有 14 拍 —— 挂上去等于大多数玩家永远等不到,
# 跟 offline_pulse 同一个坑 (它只在「玩家离开又回来」那一拍开火, 而中位玩家
# 从来没有「回来」过)。关系恰恰是头几拍定下来的, 所以第一次必须早。
RELREAD_FIRST = 3      # 第 3 拍就判第一次 (中位局 14 拍, 这一刀要落在前面)
RELREAD_EVERY = 6      # 之后每 6 拍重判 —— 不是每拍: 每拍判就是「每句话打分」的复辟


def relation_of(content: dict[str, Any], state: dict[str, Any],
                cid: str | None) -> dict[str, Any] | None:
    """🫂 此刻 TA 跟玩家【是什么关系、心里对你什么感觉】。见过面就一定有, 不会是空的。

    Yi 2026-08-06:「人与人之间无论什么时候都有一个关系存在，AI 角色和玩家也不例外。」

    从前 relweb 里写的是 `sc = rel_all.get(cid); if not sc: continue` —— 见过面但还没
    打过分的人, 关系网上跟玩家之间一条边都没有。生产实测 205 人次里 19 个 (9%) 无边,
    3 局整局画不出一条玩家边。没打过分不等于没关系, 那也是一种关系 (初识/同僚/戒备)。

    三层, 后面的盖前面的:
      ① 作者写的 base_mode —— 没有任何互动时的底
      ② rel 账本推的 derive_mode —— 有账就按账走 (rel_events 那本账不许被架空)
      ③ 定期的上下文重判 —— 算术说「朋友」, 上下文可以说「面和心不和」
    ledger_mode 永远保留②那一档: 引擎里靠它开门的地方 (同行/看手机/床戏) 不受①③影响。
    """
    if not cid or cid == state.get("player_character_id"):
        return None
    if cid not in set(state.get("met_ids") or []):
        return None
    c = _char_by_id(content, cid) or {}
    tun = tuning_for(content)
    sc = (state.get("rel") or {}).get(cid)
    ledger = (relationships.derive_mode(c, sc, tun) if sc
              else relationships.initial_mode(c))
    out = {"mode": ledger, "ledger_mode": ledger, "feeling": "", "why": ""}
    read = (state.get("rel_read") or {}).get(cid) or {}
    if read.get("mode"):
        out["mode"] = read["mode"]
    if read.get("feeling"):
        out["feeling"] = read["feeling"]
    if read.get("why"):
        out["why"] = read["why"]
    return out


def relation_read_due(state: dict[str, Any], cid: str | None, turn: int) -> bool:
    """该给这个人重判一次关系了吗 (纯算, 零成本 —— 贵的那次调用由调用方决定要不要发)。"""
    if not cid or cid not in set(state.get("met_ids") or []):
        return False
    last = ((state.get("rel_read") or {}).get(cid) or {}).get("at")
    if last is None:
        return int(turn) >= RELREAD_FIRST
    return int(turn) - int(last) >= RELREAD_EVERY


def apply_relation_read(state: dict[str, Any], cid: str,
                        out: dict[str, Any] | None, at: int | None = None) -> bool:
    """把一次重判落账。空话不收 —— 收了就再也分不清哪些是真判过的。"""
    out = out or {}
    mode = str(out.get("mode") or "").strip()[:12]
    feeling = str(out.get("feeling") or "").strip()[:40]
    if not mode and not feeling:
        return False
    # ⚠️ 这里必须跟 relation_read_due 用【同一把尺】: turn_seq 每拍 +1。
    # 2026-08-07 查错抓到: 原本默认写的是 _time_index (日×3+时段), 而判到期拿
    # turn_seq 去减它 —— 量纲不同, 两头都坏: 钟点慢回合快的档差值永久 >=6, 变成
    # 每拍每人都开一次判官 (实测 30 拍开了 18 次); 跳很多天的档差值永远是负,
    # 判过一次就再也不重判 (实测 30 拍开 0 次)。
    # 单测当时全绿, 因为每一条都显式传了 at —— 而生产唯一的落账路径
    # apply_pending_reads 不传。教训: 要测【调用方真走的那条路】。
    row = {"mode": mode, "feeling": dedash(feeling),
           "why": dedash(str(out.get("why") or "").strip()[:24]),
           "at": int(at if at is not None else (state.get("turn_seq") or 0))}
    state.setdefault("rel_read", {})[cid] = row
    return True


_REL_PENDING: dict = {}   # 一次性票据 → {cid: read} (后台判官的成品架)
_REL_CAP = 30


def relation_reads_async(content: dict[str, Any], state: dict[str, Any],
                         jobs: list[tuple[str, list]], llm: LLM) -> None:
    """🫂 关系重判走后台 (与记忆折叠 _folds_async 同一家法: 备料在主线程,
    模型调用在后台线程, 成品下一回合 apply_pending_reads 合账, 线程绝不碰 state)。

    出口 0.4~0.8Mbps、旁白逐拍流式, 再加一次【同步】调用会直接压在 TTFT 上。
    票据丢失无害: 没合上账只是这一拍关系照旧, 下一拍到点了再判一次。
    """
    jobs = [(cid, lines) for cid, lines in jobs if cid and lines]
    if not jobs:
        return
    import threading
    import uuid
    tok = uuid.uuid4().hex[:12]
    state["reads_pending"] = tok
    _pl = (state.get("persona_name") or "") or "对方"
    snap = [(cid, _char_by_id(content, cid) or {},
             (relation_of(content, state, cid) or {}).get("ledger_mode") or "",
             list(lines)[-12:]) for cid, lines in jobs]

    def _work():
        got = {}
        for cid, c, ledger, lines in snap:
            try:
                out = llm.generate({"relation_judge": True,
                                    "char": {"name": c.get("name") or ""},
                                    "player_name": _pl, "ledger_mode": ledger,
                                    "lines": lines}) or {}
            except Exception:
                out = {}
            if out.get("mode") or out.get("feeling"):
                got[cid] = out
        while len(_REL_PENDING) >= _REL_CAP:
            _REL_PENDING.pop(next(iter(_REL_PENDING)), None)
        _REL_PENDING[tok] = got

    threading.Thread(target=_work, daemon=True).start()


def apply_pending_reads(state: dict[str, Any]) -> bool:
    """回合开演前把后台判好的关系合进账。没折完就把票留着, 下回合再收。"""
    tok = state.get("reads_pending")
    if not tok:
        return False
    got = _REL_PENDING.pop(tok, None)
    if got is None:
        return False
    state.pop("reads_pending", None)
    landed = False
    for cid, out in (got or {}).items():
        landed = apply_relation_read(state, cid, out) or landed
    return landed


def relations_summary(content: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    """Each in-scene character's CURRENT relationship mode toward the player (for the UI /
    API). Empty in god mode (no player participant). Player's own character excluded."""
    if (state.get("mode") or "character") == "god":
        return {}
    pcid = state.get("player_character_id")
    rel_all = state.get("rel") or {}
    tun = tuning_for(content)
    out: dict[str, Any] = {}
    for c in scene_characters(content, state):
        cid = c.get("id")
        if not cid or cid == pcid:
            continue
        out[cid] = relationships.state_for(c, rel_all.get(cid) or relationships.new_scores(),
                                           tun, lang=lang_of(content))
    return out


def story_default_bg(content: dict[str, Any]) -> str:
    """A sensible fallback background derived from the story's worldbuilding."""
    world = (content.get("story") or {}).get("world_long") or ""
    return scene_mod.classify_scene(world)["bg"]


def opening_scene(content: dict[str, Any]) -> dict[str, Any]:
    return scene_mod.classify_scene(opening_narration(content), default_bg=story_default_bg(content))
