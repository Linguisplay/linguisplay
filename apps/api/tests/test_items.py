# -*- coding: utf-8 -*-
"""🎒 物品实体化 P0 (Yi 2026-07-15 拍板): 模板+实例两层、堆叠、split-on-write、
申报制铸卡、隔离区、懒迁移、判定点名属性。幽灵物品的执法点。"""

from app.engine import items, runtime

STORY = {
    "story": {"id": "it", "characters": [{"id": "c1", "name": "Mara", "is_lead": True}],
              "acts": [{"index": 1, "title": "一"}],
              "locations": [{"id": "l1", "name": "堂屋", "detail": "一张方桌", "exits": []}]},
    "secrets": [],
}


# ── 模板层 ────────────────────────────────────────────────────────────────────
def test_template_id_deterministic_and_snapshot_frozen():
    assert items.template_id("铜钱") == items.template_id(" 铜钱 ")  # 同名同 tid
    st = {}
    tid = items.ensure_template(st, "铜钱")
    st["item_templates"][tid]["weight"] = 9  # 档内卡被"外界"改过
    # 再次 ensure 不覆盖 — 快照冻结法度
    assert items.ensure_template(st, "铜钱") == tid
    assert st["item_templates"][tid]["weight"] == 9


def test_rule_card_conservative_defaults_and_keywords():
    c = items.rule_card("不知名的物件")
    assert (c["weight"], c["bulk"], c["hands"], c["flammable"]) == (2, 2, 1, False)
    assert c["origin"] == "backfilled"
    assert items.rule_card("火折子")["flammable"] is True
    assert items.rule_card("铜钱")["bulk"] == 1
    assert items.rule_card("石碑")["weight"] == 5
    assert items.rule_card("长弓")["hands"] == 2


def test_card_from_decl_clamps_and_mints():
    c = items.card_from_decl("秘银匕首", {"weight": "99", "bulk": "1", "hands": "2",
                                          "material": "秘银", "flammable": False,
                                          "desc": "冷光流转"})
    assert c["weight"] == 5 and c["bulk"] == 1 and c["hands"] == 2
    assert c["material"] == "秘银" and c["origin"] == "minted"


# ── 堆叠与立籍 ────────────────────────────────────────────────────────────────
def test_stack_merge_take_and_split_on_write():
    st = {}
    items.add_stack(st, "铜钱", 3)
    items.add_stack(st, "铜钱", 2)
    rows = st["inventory"]
    assert len(rows) == 1 and rows[0]["qty"] == 5  # 五枚铜钱一行, 不立五个籍
    # split-on-write: 其中一枚被下了毒 → qty-1, 铸个体籍
    inst = items.split_on_write(st, "铜钱", {"毒": "淬了见血封喉"})
    assert inst and inst["iid"] and st["inventory"][0]["qty"] == 4
    # 空个体状态不立籍 (立籍判据只有一条)
    assert items.split_on_write(st, "铜钱", {"note": "  "}) is None
    # 出库不动有籍件
    assert items.take_stack(st, "铜钱", 4) is True
    left = [r for r in st["inventory"] if r.get("tid") == items.template_id("铜钱")]
    assert len(left) == 1 and left[0].get("iid")  # 只剩那枚毒钱
    assert items.take_stack(st, "铜钱", 1) is False  # 堆空了, 有籍件不许当库存扣
    # 个体状态清空 → 合并回堆
    inst["indiv"] = {}
    assert items.merge_back(st, inst["iid"]) is True
    assert st["inventory"][0].get("qty") == 1 and not st["inventory"][0].get("iid")


# ── 懒迁移 ────────────────────────────────────────────────────────────────────
def test_migrate_state_idempotent_and_detail_promoted():
    st = {"inventory": [{"name": "短刃", "detail": "柄上錾着后山"}],
          "stashes": {"l1": [{"name": "灯笼"}]}}
    assert items.migrate_state(st) is True
    row = st["inventory"][0]
    assert row["tid"] and row["qty"] == 1
    assert st["item_templates"][row["tid"]]["desc"] == "柄上錾着后山"  # detail 上收
    assert row["detail"] == "柄上錾着后山"                             # 行上保留 (旧 UI 读)
    assert st["stashes"]["l1"][0]["tid"]
    assert st["schema_version"] == items.SCHEMA_VERSION
    snap = str(st)
    assert items.migrate_state(st) is False and str(st) == snap  # 幂等: 跑两遍结果一样


# ── 判定点名属性 (第3题②: 失败不许黑箱) ──────────────────────────────────────
def test_checks_name_the_culprit_attribute():
    ok, why = items.lift_check(items.rule_card("石碑"))
    assert not ok and "搬" in why
    ok, why = items.lift_check(items.rule_card("木箱"), strength=5)  # 常人搬不动大箱
    assert not ok and "搭把手" in why
    assert items.lift_check(items.rule_card("木箱"), strength=9)[0]  # 大力士搬得动
    ok, why = items.bag_check(items.rule_card("长弓"))
    assert not ok and "背包" in why
    ok, why = items.break_check(items.rule_card("铁刀"))
    assert not ok and "硬家伙" in why
    assert items.break_check(items.rule_card("铁刀"),
                             tool_card=items.rule_card("石锤"))[0]
    # 保守默认: 无名物件全绿灯 (宁可少限制不可错限制)
    c = items.rule_card("旧包袱")
    assert items.lift_check(c)[0] and items.bag_check(c)[0] and items.break_check(c)[0]


# ── 管线整合: 申报铸卡 + 隔离区 ───────────────────────────────────────────────
class DeclLLM:
    """报一件世界首现的新物 (带物性申报), 再谎报失去一件不在册的东西。"""

    def __init__(self):
        self.turn = 0

    def generate(self, prompt):
        if prompt.get("risk_judge"):
            return {"risk": 100}
        if not prompt.get("speaker_name"):
            return {}
        self.turn += 1
        if self.turn == 1:
            return {"beats": [{"type": "dialogue", "speaker_name": "Mara",
                               "text": "拿着这个火折子。"}],
                    "affinity_delta": 0, "advance_act": False, "ending": None,
                    "gained": "火折子", "new_item": "1|1|1|竹木|1|裹着油纸的小竹筒",
                    "next_speakers": []}
        return {"beats": [{"type": "dialogue", "speaker_name": "Mara", "text": "嗯。"}],
                "affinity_delta": 0, "advance_act": False, "ending": None,
                "lost": "并不存在的怀表", "next_speakers": []}


# ── P3: 效果/使用/变形/隔离区转正 (docs/item-effects-p3.md 验收清单) ──────────
def _turn_llm(fields):
    """一次性导演: 首拍报 fields, 之后闭嘴。"""
    class L:
        def __init__(self):
            self.turn = 0

        def generate(self, prompt):
            if prompt.get("risk_judge"):
                return {"risk": 100}
            if prompt.get("mint_item_cards"):
                return {"cards": [{"name": n, "weight": 1, "bulk": 1,
                                   "material": "布", "desc": "补铸之物"}
                                  for n in prompt.get("names") or []]}
            if not prompt.get("speaker_name"):
                return {}
            self.turn += 1
            base = {"beats": [{"type": "dialogue", "speaker_name": "Mara", "text": "嗯。"}],
                    "affinity_delta": 0, "advance_act": False, "ending": None,
                    "next_speakers": []}
            return {**base, **(fields if self.turn == 1 else {})}
    return L()


def test_use_bandage_full_hp_noop_still_consumes():
    """满血用绷带: 绷带-1, 血条不动, 正文点明白费, audit 有 no_op。"""
    st = {**runtime.default_state(), "location_id": "l1", "player_hp": "healthy"}
    items.add_stack(st, "绷带", 2)
    out = runtime.run_turn(STORY, st, {"name": "我"}, "我把绷带敷上", channel="do",
                           llm=_turn_llm({"used": "绷带|self|敷伤"}))
    st = out["state"]
    row = next(r for r in st["inventory"] if r["name"] == "绷带")
    assert row["qty"] == 1 and st["player_hp"] == "healthy"      # 消耗与成败解耦
    assert any("白费" in (b.get("text") or "") for b in out["beats"])
    assert any(e["e"] == "item.effect" and "no_op" in str(e.get("data"))
               for e in out["audit"])


def test_use_bandage_heals_and_narrates_cause():
    st = {**runtime.default_state(), "location_id": "l1", "player_hp": "hurt"}
    items.add_stack(st, "绷带", 1)
    out = runtime.run_turn(STORY, st, {"name": "我"}, "我把绷带敷上", channel="do",
                           llm=_turn_llm({"used": "绷带|self|敷伤"}))
    st = out["state"]
    assert st["player_hp"] == "healthy"                          # 血条阶梯升档
    assert not any(r["name"] == "绷带" for r in st["inventory"])  # 用即耗尽
    assert any("绷带" in (b.get("text") or "") and "伤" in (b.get("text") or "")
               for b in out["beats"])                            # 点名肇因


def test_multi_use_item_splits_then_destroys():
    """火折子 uses=3: 首用堆叠 qty-1 立籍 uses_left=2; 用满销毁。"""
    st = {**runtime.default_state(), "location_id": "l1"}
    items.add_stack(st, "火折子", 2)
    for i in range(3):
        out = runtime.run_turn(STORY, st, {"name": "我"}, "点火折子", channel="do",
                               llm=_turn_llm({"used": "火折子|self|照明"}))
        st = out["state"]
    rows = [r for r in st["inventory"] if "火折子" in r["name"]]
    assert len(rows) == 1 and rows[0].get("qty") == 1 and not rows[0].get("iid"), \
        "实例用满销毁, 堆里那根原封没动"
    # light 落在 place_facts 真账本上
    assert any("照亮" in f.get("text", "") for f in st["place_facts"].get("l1", []))


def test_lost_of_effectful_consumable_redirects_to_used():
    st = {**runtime.default_state(), "location_id": "l1"}
    items.add_stack(st, "绷带", 1)
    out = runtime.run_turn(STORY, st, {"name": "我"}, "包扎", channel="do",
                           llm=_turn_llm({"lost": "绷带"}))
    st = out["state"]
    assert any(r["name"] == "绷带" for r in st["inventory"])      # 没被悄悄吞掉
    assert any(e["e"] == "item.lost" and not e["ok"] and "item_used" in (e.get("why") or "")
               for e in out["audit"])


def test_transform_burn_letter_requires_clue_confirmation():
    """烧挂线索的信: 未带 destroys_clues → 驳回; 带了 → 信销灰入包+毁证日志。"""
    st = {**runtime.default_state(), "location_id": "l1"}
    items.add_stack(st, "密信", 1)
    items.split_on_write(st, "密信", {"线索": "信尾盖着后山的私印"})
    tr = {"inputs": ["密信"], "outputs": ["灰烬|1|1|1|其他|0|一小撮纸灰"], "method": "烧"}
    out = runtime.run_turn(STORY, st, {"name": "我"}, "烧了它", channel="do",
                           llm=_turn_llm({"transformed": tr}))
    st = out["state"]
    assert any(r["name"] == "密信" for r in st["inventory"])      # 驳回, 信还在
    assert any(e["e"] == "item.transformed" and not e["ok"] and "显式确认" in (e.get("why") or "")
               for e in out["audit"])
    out2 = runtime.run_turn(STORY, st, {"name": "我"}, "烧了它", channel="do",
                            llm=_turn_llm({"transformed": {**tr, "destroys_clues": True}}))
    st = out2["state"]
    assert not any(r["name"] == "密信" for r in st["inventory"])
    assert any(r["name"] == "灰烬" for r in st["inventory"])       # 原子交换: 销一铸一
    assert st["destroyed_evidence"][0]["name"] == "密信"           # 世界记得玩家毁证
    assert any("化作" in (b.get("text") or "") for b in out2["beats"])


def test_transform_melt_gold_stacked_output():
    st = {**runtime.default_state(), "location_id": "l1"}
    items.add_stack(st, "金条", 1)
    out = runtime.run_turn(STORY, st, {"name": "我"}, "把金条熔了", channel="do",
                           llm=_turn_llm({"transformed": {
                               "inputs": ["金条"], "outputs": ["金锭×2"], "method": "熔"}}))
    st = out["state"]
    assert not any(r["name"] == "金条" for r in st["inventory"])
    gold = next(r for r in st["inventory"] if r["name"] == "金锭")
    assert gold["qty"] == 2


def test_enum_iron_law_clamps_unknown_and_reserved():
    """枚举外 (charm) 与账本未立 (cure) 一律夹逼成无效果 + audit。"""
    ok, dropped = items.parse_effects("charm:2:self,cure:1:self,heal:1:self")
    assert [e["type"] for e in ok] == ["heal"]
    assert set(dropped) == {"charm", "cure"}


def test_quarantine_promotes_on_touch():
    """玩家掂过隔离区名字 → 下一拍批量补铸转正 origin=promoted, 入当前场景。"""
    st = {**runtime.default_state(), "location_id": "l1"}
    items.quarantine(st, "怀表", "judged.lost", day=1)
    out = runtime.run_turn(STORY, st, {"name": "我"}, "我掂了掂怀表", channel="do",
                           llm=_turn_llm({}))
    st = out["state"]   # 本拍 touch, 下一拍转正
    out2 = runtime.run_turn(STORY, st, {"name": "我"}, "继续", channel="say",
                            llm=_turn_llm({}))
    st = out2["state"]
    assert not st["item_quarantine"]
    card = st["item_templates"][items.template_id("怀表")]
    assert card["origin"] == "promoted" and card["material"] == "布"  # 补铸调用生效
    assert any(r["name"] == "怀表" for r in items.scene_rows(st, "l1"))


def test_v3_migration_backfills_effects_idempotently():
    st = {"inventory": [{"name": "绷带", "detail": "干净的细布"}],
          "char_sim": {"a": {"items": [{"name": "短刃"}]}}}
    assert items.migrate_state(st) is True
    card = st["item_templates"][items.template_id("绷带")]
    assert card["effects"] and card["effects"][0]["type"] == "heal" and card["consumable"]
    assert st["char_sim"]["a"]["items"][0]["tid"]                 # NPC 家当入籍
    snap = str(st)
    assert items.migrate_state(st) is False and str(st) == snap   # 幂等


# ── P2: 配图 = 纯函数(物性卡), 同模板永远同图 ─────────────────────────────────
def test_icon_prompt_is_pure_and_seed_stable():
    card = items.card_from_decl("火折子", {"weight": 1, "bulk": 1, "material": "竹木",
                                           "flammable": True, "desc": "裹着油纸的小竹筒"})
    p1, n1 = items.icon_prompt(card)
    p2, n2 = items.icon_prompt(dict(card))
    assert p1 == p2 and n1 == n2                      # 确定性拼接, 零自由发挥
    assert "竹木火折子" in p1 and "裹着油纸" in p1 and "游戏道具" in p1
    assert "人物" in n1 and "文字" in n1               # 道具图不许长出人和字
    s = items.icon_seed(items.template_id("火折子"))
    assert s == items.icon_seed(items.template_id("火折子")) and s > 0


def test_market_goods_minted_on_stocking():
    class MarketLLM:
        def generate(self, prompt):
            if prompt.get("gen_market"):
                return {"items": [{"name": "火折子", "price": 5, "detail": "引火之物"}]}
            return {}
    st = {**runtime.default_state(), "money": 50,
          "clock": {"day": 1, "slot": 0, "turns_in_slot": 0}}
    view = runtime.market_view(STORY, st, MarketLLM())
    it = view["items"][0]
    assert it["tid"] == items.template_id("火折子")     # 上架即入籍
    assert st["item_templates"][it["tid"]]["desc"] == "引火之物"


# ── P1: 场景在册物 + 申报入册 + examine 渗出 ─────────────────────────────────
class StageLLM:
    """导演申报两件场景物出场 (props_on_stage)。"""

    def generate(self, prompt):
        if prompt.get("risk_judge"):
            return {"risk": 100}
        if not prompt.get("speaker_name"):
            return {}
        return {"beats": [{"type": "dialogue", "speaker_name": "Mara",
                           "text": "墙角有根竹竿，桌上搁着一盏灯笼。"}],
                "affinity_delta": 0, "advance_act": False, "ending": None,
                "stage_props": "竹竿、灯笼", "next_speakers": []}


def test_stage_props_register_then_player_takes_for_real():
    st = {**runtime.default_state(), "location_id": "l1"}
    out = runtime.run_turn(STORY, st, {"name": "我"}, "屋里有什么", channel="say",
                           llm=StageLLM())
    st = out["state"]
    reg = [r["name"] for r in items.scene_rows(st, "l1")]
    assert reg == ["竹竿", "灯笼"]                       # 申报入册, 有籍可查
    # 玩家伸手拿在册物 → 真实转移: 场上少一件, 包里多一件 (不再是幽灵)
    out2 = runtime.run_turn(STORY, st, {"name": "我"}, "我把灯笼收下",
                            channel="do", llm=StageLLM())
    st = out2["state"]
    assert any(r["name"] == "灯笼" for r in st["inventory"])
    assert [r["name"] for r in items.scene_rows(st, "l1")] == ["竹竿"]
    # 石碑级的东西申报了也拿不走 — 判定点名属性, 东西留回原地
    items.scene_add(st, "l1", "石碑")
    out3 = runtime.run_turn(STORY, st, {"name": "我"}, "我把石碑收下",
                            channel="do", llm=StageLLM())
    st = out3["state"]
    assert not any(r["name"] == "石碑" for r in st["inventory"])
    assert any(r["name"] == "石碑" for r in items.scene_rows(st, "l1"))
    assert any(e["e"] == "take" and not e["ok"] and "搬" in (e.get("why") or "")
               for e in out3["audit"])


def test_examine_reveals_physics_in_world_language():
    st = {**runtime.default_state(), "location_id": "l1"}
    items.add_stack(st, "铁刀", 1)
    got = runtime.examine_items(STORY, st, "我掂了掂铁刀", channel="do")
    assert got and got[0][0] == "铁刀" and "金属" in got[0][1]
    # 走完整管线出成拍子
    out = runtime.run_turn(STORY, st, {"name": "我"}, "我掂了掂铁刀",
                           channel="do", llm=StageLLM())
    assert any("掂量" in (b.get("text") or "") and "铁刀" in (b.get("text") or "")
               for b in out["beats"])


def test_pipeline_declared_mint_and_quarantine():
    st = {**runtime.default_state(), "location_id": "l1"}
    llm = DeclLLM()
    out = runtime.run_turn(STORY, st, {"name": "我"}, "有火种吗", channel="say", llm=llm)
    st = out["state"]
    row = next(r for r in st["inventory"] if r["name"] == "火折子")
    card = st["item_templates"][row["tid"]]
    assert card["origin"] == "minted" and card["flammable"] is True \
        and card["material"] == "竹木" and card["desc"] == "裹着油纸的小竹筒"
    # 第二回合: 谎报失去不在册物 → 驳回 + 进隔离区 (监控指标)
    out2 = runtime.run_turn(STORY, st, {"name": "我"}, "再聊聊", channel="say", llm=llm)
    st2 = out2["state"]
    assert any(e["e"] == "item.lost" and not e["ok"] for e in out2["audit"])
    assert any(q["name"] == "并不存在的怀表" and q["src"] == "judged.lost"
               for q in st2["item_quarantine"])
    # 隔离区 TTL: 游戏内三天没转正就过期丢弃
    assert items.quarantine_sweep(st2, day=99) >= 1
    assert not st2["item_quarantine"]
