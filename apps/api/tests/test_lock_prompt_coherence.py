"""🔒 半吊子锁收尾: 锁关掉的能力, 提示词层不许再向模型征收。

实弹 (Yi 2026-08-06, 浮生·蓝信一): schema 仍向模型征 moved_to/npc_moves/move_invite,
模型好心叙事走位、申报到达, runtime 在散文已经流给玩家之后才静默丢弃 (move.narrated),
下一拍空间锚按旧地点喂 + 守卫按旧名单强制重生成 + 作息把人拽回 home —— 玩家看到的
就是「地图不断把角色往场景里拉 / 重演赶路」。

家规: 拿掉约束前先确认接手的那个真会生效 —— 08-04 锁上引擎侧时, 提示词侧没人接手。
修法: 按锁旗摘 schema 字段 + 锚文案不再教模型发起移动/叙写赶路。
旗开着时旧字段旧文案原样回来 (休眠代码回归网, 同 conftest 各 *_on 夹具)。
"""

from app.engine import qwen, runtime

MAP = {
    "story": {
        "id": "st",
        "characters": [{"id": "c1", "name": "蓝信一", "is_lead": True, "persona_text": "头马"}],
        "acts": [{"index": 1, "title": "一"}],
        "locations": [
            {"id": "hall", "name": "巷口", "detail": "旧石板路，一盏路灯", "exits": ["糖水店"]},
            {"id": "shop", "name": "糖水店", "detail": "靠窗的卡座", "exits": ["巷口"]},
        ],
    },
    "secrets": [],
}

MAP_EN = {
    "story": {**MAP["story"], "language": "en",
              "locations": [{"id": "hall", "name": "The Lane",
                             "detail": "old flagstones", "exits": ["The Shop"]},
                            {"id": "shop", "name": "The Shop",
                             "detail": "a window booth", "exits": ["The Lane"]}]},
    "secrets": [],
}

PROMPT = {"place": "此刻玩家所在的地点是【巷口】", "speaker_name": "蓝信一",
          "speaker_persona": "城寨头马", "persona": {"name": "蔡妍"}}


def _tool(prompt):
    return str(qwen._render_tool(prompt, "蓝信一", False, None, "say", "x"))


# ── schema: 关着的锁不许再征字段 ──────────────────────────────────────────────

def test_schema_asks_for_moved_to_by_default():
    """🗺 2026-08-08「模型决定」: 谁在哪归模型, 所以要向它收申报。
    不收会怎样, 线上两场实弹验过: 模型没有申报口就用散文兑现, 账本跟不上。"""
    assert "moved_to" in _tool(PROMPT)


def test_schema_omits_moved_to_when_locked(map_writes_off):
    """可逆合同: 旗一关, 死信字段就不许再征 —— 引擎收到只会静默丢弃。"""
    assert "moved_to" not in _tool(PROMPT)


def test_schema_asks_for_move_invite_by_default():
    """🎟 2026-08-08 起邀约锁默认开着 —— 确认条弹得出来, 就得向模型收这个字段。
    不收会怎样, 线上验过: 模型没有出口就用散文兑现, 把人写去别处而位置没动。"""
    assert "move_invite" in _tool(PROMPT)


def test_schema_omits_move_invite_when_locked(invite_move_off):
    """可逆合同: 锁一关, 死信字段就不许再征。"""
    assert "move_invite" not in _tool(PROMPT), \
        "INVITE_MOVE 关着, 确认条永远不弹, move_invite 是死信"


def test_schema_returns_declare_fields_when_unlocked(map_writes_on):
    s = _tool(PROMPT)
    assert "moved_to" in s and "npc_moves" in s, "旗开回来时休眠字段必须原样回来"


def test_schema_returns_invite_when_unlocked(invite_move_on):
    assert "move_invite" in _tool(PROMPT), "旗开回来时 move_invite 必须原样回来"


# ── qwen 空间锚: 不再教模型发起移动 ──────────────────────────────────────────

def test_anchor_teaches_move_invite_by_default():
    sys = qwen._build_system(PROMPT)
    assert "move_invite" in sys, "锁开着却不教申报 —— 模型只剩散文一条路兑现"
    assert "征求玩家同意" in sys or "玩家点头" in sys, "得说清是玩家点头才走, 否则模型会自己走"


def test_anchor_stops_teaching_move_invite_when_locked(invite_move_off, map_writes_off):
    sys = qwen._build_system(PROMPT)
    assert "move_invite" not in sys, "锁关着, 锚文案还在教模型用 move_invite 申报带路"
    assert "玩家自己在地图上点" in sys, "得告诉模型: 换场只由玩家点地图, 戏留在原地写"


def test_anchor_teaches_invite_again_when_unlocked(invite_move_on):
    assert "move_invite" in qwen._build_system(PROMPT)


# ── runtime 地点锚: 不再要求「把移动过程写出来」 ─────────────────────────────

def test_place_anchor_demands_travel_prose_by_default():
    """开着就要教叙写赶路 —— 一边收 moved_to 一边喊「绝不要写玩家启程」是自相矛盾。"""
    st = {**runtime.default_state(), "location_id": "hall"}
    block = runtime._physical_place(MAP, st)
    assert "把移动过程写出来" in block or "不能瞬移" in block


def test_place_anchor_stops_demanding_travel_prose(map_writes_off):
    st = {**runtime.default_state(), "location_id": "hall"}
    block = runtime._physical_place(MAP, st)
    assert "把移动过程写出来" not in block and "不能瞬移" not in block, \
        "锁关着, 地点锚还在教模型叙写赶路 —— 这正是实录里散文走位的教唆者"
    assert "玩家自己在地图上点" in block
    assert "糖水店" in block  # 通路数据照常给（台词相邀、描写方位都用得上）


def test_place_anchor_stops_demanding_travel_prose_en(map_writes_off):
    st = {**runtime.default_state(), "location_id": "hall"}
    block = runtime._physical_place(MAP_EN, st)
    assert "must be narrated" not in block and "no teleporting" not in block
    assert "on the map" in block


def test_place_anchor_teaches_travel_again_when_unlocked(map_writes_on):
    st = {**runtime.default_state(), "location_id": "hall"}
    assert "把移动过程写出来" in runtime._physical_place(MAP, st)


# ── 审查补刀 (对抗性审查 2026-08-06 六条确认): 其余还在教死流程的嘴 ──────────

def test_world_seed_stops_soliciting_places(map_writes_off):
    # 🌱 P1: 地点种子锁下必被判官驳回且不销账, due 每拍重催 → 永动催生循环。
    #    锁关着只教「人物：」, 地点通道整个不教。
    s = _tool({**PROMPT, "world_seed": "soft"})
    assert "地点：名字" not in s and "竹棚渡口" not in s, \
        "LLM_MAP_WRITES 关着还在教模型往散文里织新去处 —— 铸造必被驳回, 预算永不销账"
    assert "人物：名字" in s, "人物通道还活着, 不许一起摘"


def test_world_seed_solicits_places_again_when_unlocked(map_writes_on):
    assert "地点：名字" in _tool({**PROMPT, "world_seed": "soft"})


def test_suggestions_stop_exemplifying_travel():
    s = _tool(PROMPT)
    assert "我…/问他…/去…" not in s, \
        "TYPED_MOVE 关着, 「去X」建议点了是死路 (正则嗅探整条不走)"
    assert "我…/问他…/找…" in s, "找人 (player_seek) 不归 TYPED_MOVE 管, 还活着"


def test_suggestions_exemplify_travel_again_when_unlocked(typed_move_on):
    assert "我…/问他…/去…" in _tool(PROMPT)


def test_suggestions_en_forbid_travel_under_lock():
    s = _tool({**PROMPT, "language": "en"})
    assert "Never suggest going somewhere else" in s


def test_suggestions_en_allow_travel_when_unlocked(typed_move_on):
    assert "Never suggest going somewhere else" not in _tool({**PROMPT, "language": "en"})


def test_anchor_under_map_writes_alone_teaches_declared_travel(map_writes_on, invite_move_off):
    # 🔒 可逆合同: 只翻回 LLM_MAP_WRITES 时, 锚必须教声明式移动 (moved_to),
    #    不许一边征收 moved_to 一边喊「绝不要写玩家启程」自相矛盾
    # ⚠️ 必须显式关掉邀约锁: 它默认开着且在分支里优先, 否则这里测的根本不是本条合同
    sys = qwen._build_system(PROMPT)
    assert "move_invite" not in sys, "INVITE_MOVE 还关着, 不该教确认条"
    assert "玩家自己在地图上点" not in sys, "原地文案与 moved_to 征收自相矛盾"
    assert "moved_to" in sys, "声明式移动开着就要教申报, 文与实不许分家"


# ── 两旗同时开着: 两件工具并存, 不是择一 (Yi 2026-08-08「模型决定」+「发挥空间」) ──

def test_both_tools_are_taught_when_both_flags_are_on():
    """⚠️ 这是我自己造的窟窿, 记在这里: 原来这段是 if/elif/else, 两旗同开时邀约那条
    抢先, moved_to 永远轮不上 —— schema 在收这个字段, 提示词却从没教过它。收了不教,
    模型自然不填, 于是「模型决定」那一刀在主拍上基本是空转的。"""
    sys = qwen._build_system(PROMPT)
    assert "moved_to" in sys, "收了 moved_to 却不教 —— 模型不知道自己能申报到达"
    assert "move_invite" in sys, "相邀那条路也得留着"
    assert "绝不要替玩家写出他已经" not in sys, \
        "还在说「不许写已经到了」—— 这正是「模型决定」推翻的那句，会跟 moved_to 打架"


def test_only_the_declared_move_when_the_invite_is_shut(invite_move_off):
    sys = qwen._build_system(PROMPT)
    assert "moved_to" in sys and "move_invite" not in sys


def test_only_the_invite_when_declared_move_is_shut(map_writes_off):
    sys = qwen._build_system(PROMPT)
    assert "move_invite" in sys and "moved_to" not in sys


def test_neither_falls_back_to_stay_put(map_writes_off, invite_move_off):
    sys = qwen._build_system(PROMPT)
    assert "玩家自己在地图上点" in sys
    assert "moved_to" not in sys and "move_invite" not in sys
