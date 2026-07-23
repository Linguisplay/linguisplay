# -*- coding: utf-8 -*-
"""🎒 物品实体化 P0 (Yi 2026-07-15 拍板五题, 见 memory linguisplay-item-entity).

病根: 叙述物无籍 = 幽灵 — AI 猜位置/数量/状态, 玩家一碰就漂。
学界共识 (AriGraph/CaveAgent/Statler): 状态外置引擎, LLM 只写词 — 本引擎祖训。

两层模型:
  ItemTemplate (类, 物性卡宿主) — 铜钱一张卡: 重量/体积/单双手/可燃/材质/价值 +
    视觉字段 (color/era/condition, 配图管线 MVP 后做, 字段先留)。
  ItemInstance (个体/籍) — 只在获得独立叙事状态时存在 (split-on-write)。

落地形态 (兼容为王 — 行形状不变, 现有十动词/UI/提示词零改动):
  背包行(堆叠):  {name, detail?, tid, qty}          qty 缺省 1
  背包行(有籍):  {name, detail?, tid, iid, indiv{}}  永远单件
  state 新键:    item_templates {tid: card}  ← run 内快照 = 判定唯一读取源
                 item_quarantine [...]        ← 未申报实体隔离区
                 schema_version               ← 懒迁移闸门

⚖️ 快照法度: 模板首次被引用时快照进档。tid 由名字确定性生成 (同名同 tid,
跨世界配图缓存天然可行), 但判定永远读档内卡 — 改任何全局资源都不动老档
(与 pinned_content 冻结哲学同族)。

卡永不裸露 (第3题): 属性经叙事渗出 — card_desc() 生成世界语言的描述;
判定失败必须点名肇因属性 (lift/bag/break_check 返回的 why 就是叙事句)。
保守默认铁律 (第4题): 宁可少限制, 不可错限制 — 缺卡按 rule_card 兜底。
"""
from __future__ import annotations

import hashlib
from typing import Any

SCHEMA_VERSION = 3          # 2=物品实体化; 3=效果纪元 (P3: 效果字段+char_items 归队)
QUARANTINE_CAP = 24         # 隔离区账本上限
QUARANTINE_TTL_DAYS = 3     # 游戏内几天没转正就过期丢弃

# 档位叙事词表 (第3题①: 描述渗出 — 玩家读到的是世界的语言, 不是数字)
WEIGHT_WORDS = {1: "轻若无物", 2: "单手可提", 3: "得双手才使得动",
                4: "一个人搬不动，得搭把手", 5: "钉在原地般搬不走"}
BULK_WORDS = {1: "揣进口袋就走", 2: "塞得进背包", 3: "得手提着",
              4: "要整个抱在怀里", 5: "是动不了的大件"}


def _norm(name: str) -> str:
    return (name or "").strip().replace(" ", "")


def template_id(name: str) -> str:
    """确定性 tid: 同名同 id — 跨 run/跨世界的配图缓存不用建全局表就能命中。"""
    return "tpl_" + hashlib.md5(_norm(name).encode()).hexdigest()[:8]


# ── 效果枚举 (P3 第1节铁律: 只许出现引擎真正记账的状态 — 先有账本后有效果) ────
# live = 账本已立可落账; reserved = 占位暂拒 (夹逼成无效果+audit), 账本立了再点亮。
# heal → player_hp 阶梯 (dying→hurt→healthy, 现成);
# light → place_facts (地点持久物理事实, 提示词在读 — 诚实落点);
# cure → 异常状态表【不存在】(2026-07-15 实查: 无人写入无人读取) → reserved。
EFFECT_TYPES = {"heal": "live", "light": "live", "cure": "reserved"}
# examine 渗出话术 (第2.5节: 零 LLM, 世界语言暗示)
EFFECT_HINTS = {"heal": "闻着有股药草味，该是治外伤的",
                "cure": "清苦气味，像是解毒之物",
                "light": "掂起来轻，一晃有火石响"}


def live_effects(card: dict[str, Any]) -> list[dict[str, Any]]:
    return [e for e in (card.get("effects") or [])
            if EFFECT_TYPES.get(str(e.get("type"))) == "live"]


# ── 保守默认 + 关键词规则表 (LLM 缺席时的兜底物理学) ─────────────────────────
# 宁可少限制不可错限制: 默认单手/中等/不可燃 — 老玩家不会突然拿不动用了半年的剑
_DEFAULT = {"weight": 2, "bulk": 2, "hands": 1, "flammable": False,
            "material": "", "value": 2, "color": "", "era": "", "condition": "",
            "effects": [], "consumable": False, "uses": 1}
_RULES: list[tuple[tuple[str, ...], dict]] = [
    (("钱", "币", "戒指", "耳环", "钥匙", "信", "纸", "符", "丹", "药丸"),
     {"weight": 1, "bulk": 1}),
    (("火折子", "火把", "灯笼", "蜡烛", "油"), {"flammable": True}),
    (("书", "账本", "卷轴", "地图"), {"weight": 1, "bulk": 1, "flammable": True}),
    (("剑", "刀", "匕首", "短刃", "斧", "锤"), {"material": "金属"}),
    (("枪", "矛", "戟", "弓", "棍"), {"hands": 2, "bulk": 3}),
    # ⚠️ 关键词要收敛: 裸「笼」误伤过灯笼 (实弹: 灯笼被判成箱笼级拿不动)
    (("箱", "笼子", "牢笼", "坛", "缸"), {"weight": 4, "bulk": 4, "hands": 2}),
    (("桌", "床", "柜", "碑", "炉", "灶", "门"), {"weight": 5, "bulk": 5}),
    # 效果规则 (P3: 默认无效果, 宁可少效果不可错效果 — 关键词照旧收敛,
    # 裸「药」会误伤火药, 用双字词):
    (("绷带", "伤药", "金疮", "药膏", "丹药", "药丸"),
     {"effects": [{"type": "heal", "magnitude": 1, "target": "self"}],
      "consumable": True}),
    (("火折", "火把", "灯笼", "蜡烛", "油灯"),
     {"effects": [{"type": "light", "magnitude": 1, "target": "self"}],
      "consumable": True, "uses": 3}),
    # cure 关键词 (解毒/清毒) 暂不进表 — 账本未立 (见 EFFECT_TYPES)
]


def rule_card(name: str) -> dict[str, Any]:
    """纯代码物性卡 (backfilled): 保守默认 + 名字关键词微调。
    深拷贝覆盖 — effects 是列表, 共享引用会让两张卡互相污染。"""
    import copy as _copy
    card = {"id": template_id(name), "name": _norm(name),
            "desc": "", **_copy.deepcopy(_DEFAULT), "origin": "backfilled"}
    for keys, over in _RULES:
        if any(k in name for k in keys):
            card.update(_copy.deepcopy(over))
    return card


def parse_effects(raw: str) -> tuple[list[dict[str, Any]], list[str]]:
    """效果段「type:档:目标,…」→ (合法效果, 被夹逼名单) — 枚举铁律的执行点:
    不在 live 枚举里的 type 一律夹逼掉, 调用方拿名单进 audit。"""
    ok: list[dict[str, Any]] = []
    dropped: list[str] = []
    for seg in str(raw or "").split(","):
        seg = seg.strip()
        if not seg:
            continue
        bits = seg.split(":")
        t = bits[0].strip()
        if EFFECT_TYPES.get(t) != "live":
            dropped.append(t or seg)
            continue
        try:
            mag = max(1, min(3, int(bits[1]))) if len(bits) > 1 else 1
        except (TypeError, ValueError):
            mag = 1
        tgt = bits[2].strip() if len(bits) > 2 and bits[2].strip() else "self"
        ok.append({"type": t, "magnitude": mag,
                   "target": "self" if tgt in ("self", "自己") else "other"})
    return ok, dropped


def decl_from_pipes(s: str, with_name: bool = False) -> tuple[str, dict[str, Any]]:
    """申报串共享解析 (item_new / 变形 outputs 内联申报同一格式):
    「(名|)重量|体积|手|材质|可燃|外观|效果段|c|uses」。"""
    p = [x.strip() for x in str(s or "").split("|")]
    name = ""
    if with_name:
        name, p = (p[0] if p else ""), p[1:]
    return name, {
        "weight": p[0] if len(p) > 0 else None,
        "bulk": p[1] if len(p) > 1 else None,
        "hands": p[2] if len(p) > 2 else None,
        "material": p[3] if len(p) > 3 else "",
        "flammable": (p[4] == "1") if len(p) > 4 else False,
        "desc": p[5] if len(p) > 5 else "",
        "effects_raw": p[6] if len(p) > 6 else "",
        "consumable": (p[7].lower() in ("c", "1", "true")) if len(p) > 7 else False,
        "uses": p[8] if len(p) > 8 else None,
    }


def card_from_decl(name: str, decl: dict[str, Any]) -> dict[str, Any]:
    """申报制铸卡 (minted): 模型在申报里连物性一起报, 引擎夹逼进合法档位 —
    不再单独打一次铸卡调用 (第1题: new_template 的卡随申报产出)。"""
    card = rule_card(name)
    for k, lo, hi in (("weight", 1, 5), ("bulk", 1, 5), ("hands", 1, 2), ("value", 1, 5)):
        try:
            v = int(decl.get(k))
            card[k] = max(lo, min(hi, v))
        except (TypeError, ValueError):
            pass
    for k in ("material", "color", "era", "condition", "desc"):
        if str(decl.get(k) or "").strip():
            card[k] = str(decl[k]).strip()[:60]
    card["flammable"] = bool(decl.get("flammable", card["flammable"]))
    # P3: 效果/消耗/次数随申报产出 (parse_effects 已按枚举铁律夹逼;
    # 夹逼名单调用方另行 parse_effects 取用进 audit)
    if str(decl.get("effects_raw") or "").strip():
        card["effects"] = parse_effects(decl["effects_raw"])[0]
    if decl.get("consumable"):
        card["consumable"] = True
    try:
        card["uses"] = max(1, min(9, int(decl.get("uses"))))
    except (TypeError, ValueError):
        pass
    card["origin"] = "minted"
    return card


# ── 模板快照与读取 ────────────────────────────────────────────────────────────
def templates(state: dict[str, Any]) -> dict[str, Any]:
    return state.setdefault("item_templates", {})


def ensure_template(state: dict[str, Any], name: str,
                    card: dict[str, Any] | None = None) -> str:
    """首次引用即快照进档; 已有档内卡永不覆盖 (冻结法度)。返回 tid。"""
    tid = template_id(name)
    tpls = templates(state)
    if tid not in tpls:
        tpls[tid] = card or rule_card(name)
    return tid


def card_of(state: dict[str, Any], row_or_name) -> dict[str, Any]:
    """行/名字 → 档内物性卡; 无卡按规则表现算 (不落档, 判定照样有物理)。"""
    if isinstance(row_or_name, dict):
        tid = row_or_name.get("tid") or template_id(row_or_name.get("name", ""))
        name = row_or_name.get("name", "")
    else:
        tid, name = template_id(row_or_name), row_or_name
    return templates(state).get(tid) or rule_card(name)


def card_desc(card: dict[str, Any]) -> str:
    """第3题①: 物性 → 一句世界语言 (模板级, 调用方可缓存)。
    效果经 EFFECT_HINTS 暗示话术渗出 (P3 §2.5, 零 LLM)。"""
    bits = [WEIGHT_WORDS.get(int(card.get("weight", 2)), "")]
    if int(card.get("bulk", 2)) != 2:
        bits.append(BULK_WORDS.get(int(card.get("bulk", 2)), ""))
    if card.get("material"):
        bits.insert(0, str(card["material"]) + "质地")
    if card.get("flammable"):
        bits.append("沾火就着")
    for eff in live_effects(card):
        hint = EFFECT_HINTS.get(str(eff.get("type")))
        if hint:
            bits.append(hint)
    return "，".join(b for b in bits if b)


def _find_row(rows: list, name: str) -> int:
    """宽松名字匹配 (与 runtime._inv_find 同则; 本地副本避免 import 成环)。"""
    n = _norm(name)
    for i, r in enumerate(rows or []):
        rn = _norm((r or {}).get("name", ""))
        if rn and (rn == n or rn in n or n in rn):
            return i
    return -1


def find_usable(state: dict[str, Any], name: str) -> dict[str, Any] | None:
    """使用目标解析: 先用开封的那件 (带 uses_left 的有籍件), 才动堆里的新件 —
    不然三根火折子会被各点一口 (实弹: 第二次使用又拆了根新的)。"""
    rows = state.get("inventory") or []
    tid = template_id(name)
    for r in rows:
        if (r.get("tid") == tid or _norm(r.get("name", "")) == _norm(name)) \
                and r.get("iid") and "uses_left" in (r.get("indiv") or {}):
            return r
    i = _find_row(rows, name)
    return rows[i] if i >= 0 else None


def consume_one_use(state: dict[str, Any], row: dict[str, Any]) -> str:
    """P3 §2.3 消耗与 split-on-write 联动 (消耗归卡, 与效果成败解耦):
    uses≤1 一次性 → 堆叠 qty-1; uses>1 首用即立籍记 uses_left, 用满销毁实例。
    返回 kept|spent|split|tick|destroyed 供叙事层措辞。"""
    card = card_of(state, row)
    if not card.get("consumable"):
        return "kept"
    uses = max(1, int(card.get("uses", 1) or 1))
    if row.get("iid"):
        left = int((row.get("indiv") or {}).get("uses_left", uses) or 0) - 1
        if left <= 0:
            rows = list(state.get("inventory") or [])
            if row in rows:
                rows.remove(row)
                state["inventory"] = rows
            return "destroyed"
        row.setdefault("indiv", {})["uses_left"] = left
        return "tick"
    if uses <= 1:
        take_stack(state, row.get("name", ""), 1)
        return "spent"
    inst = split_on_write(state, row.get("name", ""), {"uses_left": uses - 1})
    return "split" if inst else "spent"


# ── 堆叠 (第2题: 背包默认形态 = (template, qty), 三枚铜钱一行) ────────────────
def add_stack(state: dict[str, Any], name: str, qty: int = 1, detail: str = "",
              card: dict[str, Any] | None = None) -> dict[str, Any]:
    """入库 (add_stock/市集/授权物走这里): 同模板并行, qty 相加。
    模型报审的 gained 不走这里 — 它保持单件+防重复入包的旧守卫。"""
    tid = ensure_template(state, name, card)
    rows = list(state.get("inventory") or [])
    for r in rows:
        if r.get("tid") == tid and not r.get("iid"):
            r["qty"] = int(r.get("qty", 1) or 1) + max(1, int(qty))
            state["inventory"] = rows
            return r
    row = {"name": _norm(name), "tid": tid, "qty": max(1, int(qty))}
    if detail.strip():
        row["detail"] = detail.strip()
    rows.append(row)
    state["inventory"] = rows
    return row


def take_stack(state: dict[str, Any], name: str, qty: int = 1) -> bool:
    """出库 qty 件 (堆叠行优先, 不动有籍件)。不够 = False, 一件不扣。"""
    tid = template_id(name)
    rows = list(state.get("inventory") or [])
    for r in rows:
        if (r.get("tid") == tid or _norm(r.get("name", "")) == _norm(name)) \
                and not r.get("iid"):
            have = int(r.get("qty", 1) or 1)
            if have < qty:
                return False
            if have == qty:
                rows.remove(r)
            else:
                r["qty"] = have - qty
            state["inventory"] = rows
            return True
    return False


# ── split-on-write (第2题基石: 状态分化即立籍, 纯代码判定) ────────────────────
def split_on_write(state: dict[str, Any], name: str,
                   indiv: dict[str, Any]) -> dict[str, Any] | None:
    """堆里某一件获得独立叙事状态 (下过毒/刻了字/成了信物) → qty-1, 铸个体籍。
    indiv 全空 = 不立籍 (立籍判据就一条: 有非空个体状态)。"""
    indiv = {k: v for k, v in (indiv or {}).items() if str(v or "").strip()}
    if not indiv:
        return None
    tid = template_id(name)
    rows = list(state.get("inventory") or [])
    src = next((r for r in rows
                if (r.get("tid") == tid or _norm(r.get("name", "")) == _norm(name))
                and not r.get("iid")), None)
    if src is None:
        return None
    have = int(src.get("qty", 1) or 1)
    if have <= 1:
        rows.remove(src)
    else:
        src["qty"] = have - 1
    n = state["_iid_seq"] = int(state.get("_iid_seq", 0)) + 1
    ensure_template(state, name)
    inst = {"name": src.get("name", _norm(name)), "tid": tid,
            "iid": f"itm_{n:04d}", "indiv": indiv,
            **({"detail": src["detail"]} if src.get("detail") else {})}
    rows.append(inst)
    state["inventory"] = rows
    return inst


def merge_back(state: dict[str, Any], iid: str) -> bool:
    """个体状态清空 → 籍注销, 合并回堆 (split 的逆向)。"""
    rows = list(state.get("inventory") or [])
    inst = next((r for r in rows if r.get("iid") == iid), None)
    if inst is None or {k: v for k, v in (inst.get("indiv") or {}).items()
                        if str(v or "").strip()}:
        return False
    rows.remove(inst)
    state["inventory"] = rows
    add_stack(state, inst.get("name", ""), 1, inst.get("detail", ""))
    return True


# ── 判定 (第3题②: 失败叙事强制点名肇因属性 — why 即叙事句) ────────────────────
def lift_check(card: dict[str, Any], strength: int = 5) -> tuple[bool, str]:
    """拿得起吗: 重量档 vs 五维力量 (1~10, 5=常人; 缺省常人)。
    保守默认铁律: 只有明确超出人力的档位才拦, 宁可少限制不可错限制。"""
    w = int(card.get("weight", 2))
    if w >= 5:
        return False, f"{card.get('name', '它')}{WEIGHT_WORDS[5]}——这不是力气的事"
    if w == 4 and strength < 8:
        return False, f"{card.get('name', '它')}{WEIGHT_WORDS[4]}，你一个人抱不起来"
    if w == 3 and strength < 3:
        return False, f"{card.get('name', '它')}{WEIGHT_WORDS[3]}，你的力气还差着"
    return True, ""


def bag_check(card: dict[str, Any]) -> tuple[bool, str]:
    """装得进背包吗: 尺寸档 1~2 可入包, 3 手提不入包, 4+ 抱都费劲。"""
    b = int(card.get("bulk", 2))
    if b <= 2:
        return True, ""
    return False, f"{card.get('name', '它')}{BULK_WORDS.get(b, '太大')}，塞不进背包"


def break_check(card: dict[str, Any], tool_card: dict[str, Any] | None = None,
                strength: int = 5) -> tuple[bool, str]:
    """砸得坏吗: 金属/石质徒手砸不了; 有硬家伙或超人力气才行 (骰子由调用方掷)。
    力量 1~10, 5=常人。"""
    hard = str(card.get("material", "")) in ("金属", "石", "铁", "钢", "玉")
    armed = tool_card is not None and str(tool_card.get("material", "")) in ("金属", "石", "铁", "钢")
    if hard and not armed and strength < 8:
        return False, (f"{card.get('name', '它')}是{card.get('material', '硬')}打的，"
                       "赤手空拳砸不开，得找个硬家伙")
    return True, ""


# ── 配图 (第5题: 图挂 template_id, 提示词 = 纯函数(物性卡)) ───────────────────
# 同模板永远同图: tid 定 seed、字段确定性拼接 — 自由生成永远给不了的一致性。
# 风格中性道具图 (模板跨世界共享的必然): 卡上的 era/material/color 字段带风味。
# 懒生成: 背包/集市第一次展示时排队, 生成后永久缓存 /scene/item/{tid}.jpg。
def icon_seed(tid: str) -> int:
    try:
        return int(str(tid).replace("tpl_", ""), 16) % 2147483647
    except ValueError:
        return 42


def icon_prompt(card: dict[str, Any]) -> tuple[str, str]:
    """物性卡 → (提示词, 负向词), 零 LLM 确定性拼接。"""
    name = str(card.get("name") or "物件")
    bits = ["游戏道具立绘，单件物品居中特写"]
    if card.get("era"):
        bits.append(f"{card['era']}风格")
    subject = f"{card.get('material') or ''}{name}"
    if card.get("color"):
        subject += f"，{card['color']}"
    bits.append(subject)
    if card.get("desc"):
        bits.append(str(card["desc"])[:40])
    if card.get("condition"):
        bits.append(str(card["condition"])[:20])
    bits.append("纯色深灰背景，柔和顶光，高细节，干净构图")
    neg = "文字,水印,人物,人脸,手,多件物品,拼贴,场景,低质量,变形"
    return "，".join(bits), neg


# ── 场景在册物 (P1: 幽灵的正主 — 被特写过的场景物件有籍可查) ─────────────────
# 三级真实度的中间层: L0 布景(不登记) / L1 在册(这里) / L2 随身(inventory)。
# 来源: 导演 props_on_stage 申报 + 玩家伸手兜底; 授权 props 是另一套 (搜证机制)。
SCENE_CAP = 12   # 每地在册上限 — 防世界变仓库管理游戏 (超限最老的退回布景)


def scene_rows(state: dict[str, Any], lid: str) -> list[dict[str, Any]]:
    return (state.get("scene_items") or {}).get(lid) or []


def scene_add(state: dict[str, Any], lid: str, name: str,
              card: dict[str, Any] | None = None) -> dict[str, Any] | None:
    if not lid or not _norm(name):
        return None
    tid = ensure_template(state, name, card)
    reg = dict(state.get("scene_items") or {})
    rows = list(reg.get(lid) or [])
    for r in rows:
        if r.get("tid") == tid:
            return r          # 已在册
    if len(rows) >= SCENE_CAP:
        rows.pop(0)           # 布景化退册
    row = {"name": _norm(name), "tid": tid, "qty": 1}
    rows.append(row)
    reg[lid] = rows
    state["scene_items"] = reg
    return row


def scene_take(state: dict[str, Any], lid: str, name: str) -> dict[str, Any] | None:
    """从场景账本里取走真实的那一件 (拿走 = 场上少一件, 不是复制)。"""
    reg = dict(state.get("scene_items") or {})
    rows = list(reg.get(lid) or [])
    tid = template_id(name)
    row = next((r for r in rows if r.get("tid") == tid
                or _norm(r.get("name", "")) == _norm(name)), None)
    if row is None:
        return None
    rows.remove(row)
    if rows:
        reg[lid] = rows
    else:
        reg.pop(lid, None)
    state["scene_items"] = reg
    return row


# ── 隔离区 (第1题: NER/未申报实体不铸造, 进候审; 流量本身是监控指标) ──────────
def quarantine(state: dict[str, Any], name: str, src: str, day: int = 0) -> None:
    """入区/复见: 已在区的名字 hits+1 (提及≥2 是转正条件之一)。"""
    n = _norm(name)
    if not n:
        return
    for q in state.get("item_quarantine") or []:
        if _norm(q.get("name", "")) == n:
            q["hits"] = int(q.get("hits", 1) or 1) + 1
            return
    q = list(state.get("item_quarantine") or [])
    q.append({"name": n, "src": src, "day": int(day), "hits": 1})
    state["item_quarantine"] = q[-QUARANTINE_CAP:]


def quarantine_touch(state: dict[str, Any], name: str) -> bool:
    """玩家对隔离区名字发起过动词 (伸手/掂量) — 最强转正信号。"""
    n = _norm(name)
    for q in state.get("item_quarantine") or []:
        if _norm(q.get("name", "")) == n:
            q["touched"] = True
            return True
    return False


def note_mentions(state: dict[str, Any], text: str) -> None:
    """回合末: 正文再次提及隔离区名字 → hits+1 (转正计数)。"""
    for q in state.get("item_quarantine") or []:
        if q.get("name") and q["name"] in (text or ""):
            q["hits"] = int(q.get("hits", 1) or 1) + 1


def promotable(state: dict[str, Any]) -> list[str]:
    """P3 §4.1 转正条件 (纯代码): 提及≥2 次, 或玩家碰过。"""
    return [q.get("name", "") for q in state.get("item_quarantine") or []
            if q.get("touched") or int(q.get("hits", 1) or 1) >= 2]


def quarantine_remove(state: dict[str, Any], name: str) -> None:
    n = _norm(name)
    state["item_quarantine"] = [q for q in state.get("item_quarantine") or []
                                if _norm(q.get("name", "")) != n]


def quarantine_sweep(state: dict[str, Any], day: int) -> int:
    """过期丢弃 (游戏内 TTL); 返回丢弃数。转正走 promotable → 补铸 → remove。"""
    q = list(state.get("item_quarantine") or [])
    keep = [x for x in q if int(day) - int(x.get("day", 0)) <= QUARANTINE_TTL_DAYS]
    state["item_quarantine"] = keep
    return len(q) - len(keep)


# ── 懒迁移 (第4题: 加载即迁, 幂等, 玩家零感知) ───────────────────────────────
def migrate_state(state: dict[str, Any]) -> bool:
    """旧存档物品懒迁移 (加载即迁, 幂等, 玩家零感知):
    v2 物品实体化: 无 tid 的行补籍 (detail 上收模板 desc, 行上保留供旧 UI 读)。
    v3 效果纪元 (P3): char_items (char_sim[cid].items) 归队补籍;
    backfilled 卡按新规则表重推导 (补效果字段, 保守默认 — 宁可少效果不可错效果);
    minted 卡是导演申报的正史, 只补缺省键不改内容。"""
    if int(state.get("schema_version", 1) or 1) >= SCHEMA_VERSION:
        return False
    def _fix(rows):
        for r in rows or []:
            if not r.get("tid"):
                tid = ensure_template(state, r.get("name", ""))
                card = templates(state)[tid]
                if r.get("detail") and not card.get("desc"):
                    card["desc"] = str(r["detail"])[:80]
                r["tid"] = tid
            if not r.get("iid"):
                try:   # 残破 qty (0/负/非数) 一律扶正为 1 — 保守默认
                    r["qty"] = max(1, int(r.get("qty", 1) or 1))
                except (TypeError, ValueError):
                    r["qty"] = 1
    _fix(state.get("inventory"))
    for rows in (state.get("stashes") or {}).values():
        _fix(rows)
    for sim in (state.get("char_sim") or {}).values():   # v3: NPC 的家当也入籍
        _fix((sim or {}).get("items"))
    for tid, card in list(templates(state).items()):     # v3: 效果字段补装
        if card.get("origin") == "backfilled":
            fresh = rule_card(card.get("name", ""))
            if card.get("desc"):
                fresh["desc"] = card["desc"]
            templates(state)[tid] = fresh
        else:
            card.setdefault("effects", [])
            card.setdefault("consumable", False)
            card.setdefault("uses", 1)
    state["schema_version"] = SCHEMA_VERSION
    return True
