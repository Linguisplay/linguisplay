# -*- coding: utf-8 -*-
"""🚶 玩家说要走, 就把「换场只能点地图」摆到明处 (Yi 2026-08-08 选 A)。

生产实测 8 例「正文把人写去别处、而 location_id 纹丝没动」。最典型的一例连着三拍
把人从巷口 → 龙津道 → 街角 → 糖水店一路写过去。

根因不是提示词缺规则 —— 规则在, 写得很明白「这一拍的戏必须仍然发生在此地」。
根因是【玩家亲口说了要走, 而引擎没有办法兑现】: 2026-08-06 三把锁把移动收成只剩
点地图之后, 玩家打「跟他走」时系统无路可走, 模型只好用文字兑现。
那一例的上一拍正是: 蔡妍「（反手扣紧他的手，跟他走）好啊」。

Yi 拍板 A: 引擎明说「想去哪点地图」, 把摩擦摆到明处 —— 宁可生硬, 不许撒谎。

【两头都要接】只告诉玩家是半件事:
  · 对玩家: 一条 toast「想去别处？点地图」—— 不进正文, 不占线索栏
  · 对模型: 一条提示词规则「玩家这一拍想走但走不了, 戏留在原地」
只做前者的话模型照样把人写去别处, 玩家就会看到「点地图」的提示 + 一段已经到了
别处的正文, 比现在还乱。
"""
from app.engine import qwen, runtime


# ── 意图识别 ────────────────────────────────────────────────────────────────

def test_it_catches_going_with_someone():
    """生产实弹那一句。"""
    for t in ("（反手扣紧他的手，跟他走）好啊", "跟他走", "我跟你去", "好啊，跟你去",
              "一起去吧", "带我去"):
        assert runtime.player_wants_to_move(t), f"没认出移动意图: {t}"


def test_it_catches_naming_a_destination():
    for t in ("我们去果栏", "去庙街看看", "我去天台", "我们回警署吧"):
        assert runtime.player_wants_to_move(t), f"没认出移动意图: {t}"


def test_it_catches_wandering():
    assert runtime.player_wants_to_move("我出去走走")


def test_it_stays_quiet_on_ordinary_talk():
    """误报比漏报更坏 —— 每句话都弹「点地图」等于把玩家赶走。"""
    for t in ("你还好吗？", "我坐下", "我看看四周", "他走了吗", "你走开",
              "这条路好走吗", "我不想去"):
        assert not runtime.player_wants_to_move(t), f"误报了: {t}"


def test_moving_around_inside_the_room_is_not_leaving():
    for t in ("我走到窗边", "我走过去扶他", "我往前走两步"):
        assert not runtime.player_wants_to_move(t), f"场内走动被当成换场: {t}"


def test_an_action_channel_counts_too():
    """打字框里说「跟他走」不管走的是 say 还是 do, 意图都一样。"""
    assert runtime.player_wants_to_move("跟他走", channel="do")


def test_blank_input_is_quiet():
    assert not runtime.player_wants_to_move("")
    assert not runtime.player_wants_to_move(None)


# ── 对模型: 这一拍戏留在原地 ──────────────────────────────────────────────────

def _sys(**kw):
    p = {"speaker_name": "蓝信一", "speaker_persona": "马仔", "channel": "say",
         "persona": {"name": "蔡妍"}, "context": {}, "place": "九龙城区"}
    p.update(kw)
    return qwen._build_system(p)


def test_the_model_is_told_the_move_was_refused():
    s = _sys(move_blocked=True)
    assert "留在" in s or "不许离开" in s or "仍然发生在此地" in s
    assert "地图" in s, "没告诉模型玩家该去点地图, 角色就没法自然接这句"


def test_the_character_may_still_agree_out_loud():
    """不许把角色演成拒绝 —— 玩家说「跟你走」, 角色回「不行」是另一种坏。"""
    s = _sys(move_blocked=True)
    assert any(k in s for k in ("答应", "起身", "相邀", "可以说")), \
        "只写了禁令没给出路, 角色只能演成拒绝"


def test_no_flag_no_block():
    """没有移动意图时不许平白多一段提示词 (每回合都在花 token)。"""
    assert "点地图" not in _sys()


# ── 对玩家: 一条 toast, 不进正文 ──────────────────────────────────────────────

def test_the_hint_is_a_moment_not_a_beat():
    """摆到明处 ≠ 写进故事。引擎硬写的旁白不过文风, 而且会污染历史。"""
    mo = runtime.map_move_hint()
    assert isinstance(mo, dict) and mo.get("kind") == "map_move"
    assert mo.get("text"), "toast 没有文案"
