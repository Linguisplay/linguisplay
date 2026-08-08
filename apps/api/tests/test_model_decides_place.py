# -*- coding: utf-8 -*-
"""🗺 谁在哪，模型说了算 (Yi 2026-08-08:「模型决定」)。

2026-08-04 把地图从模型手里收了回来。今天两场实弹把这个决定推翻了:

  实验一 (批准分支): 真实存档 5 轮 A/B。回执写着「只演到起身相邀为止，别写已经到了」，
    有回执和没回执【一样】2/5 把人写到了别处。
  实验二 (驳回分支): 同一存档，只剪掉一条通路。回执写着「从此地去不了那里」，
    A 3/5 到达、B 3/5 到达，而且五次【一次都没提过】去不了。

第二场是关键: 那个剧本里千夏住商店街，海堤走三分钟就到，她的开场台词就是
「要不要跟我去海边透透气」。是我人为剪了那条边。【模型是对的，地图是错的】。

所以规矩改成: 模型申报到达 ⇒ 引擎照办并记账。作者写的 exits 只是对相邻关系的猜测，
而故事知道得更准。引擎的活从【否决】变成【跟上】。

⚠️ 没有一起交出去的是【铸造新地点】: 那条有造出「个地方」这种垃圾地名的前科，
   是一个独立的问题，单独一把 LLM_MINTS_PLACES 管着，这一刀没碰它。
⚠️ 也没有交出去的是【解锁闸】: 哪些地方这一幕能去，是作者的剧作结构，不是地理。
"""
import copy

from app.engine import runtime


CONTENT = {"story": {
    "id": "s",
    "characters": [{"id": "a", "name": "甲", "is_lead": True}],
    "acts": [{"index": 1, "title": "一"}],
    "locations": [
        {"id": "l1", "name": "旧巷", "detail": "x", "exits": ["老码头"]},
        {"id": "dock", "name": "老码头", "detail": "x", "exits": ["旧巷"]},
        # 🔬 作者没给它写任何通路 —— 从前这等于「永远到不了」
        {"id": "far", "name": "孤岛", "detail": "x", "exits": []},
        # ⚠️ 字段名是 act_min。我第一版写的是 "act"，被静默忽略 —— 于是这条锁根本没上，
        #    而当时的断言又在读传进去的那个 st（run_turn 在副本上干活），所以照样绿。
        #    两个错互相遮掩，正好演示了「不会红的红样本」是怎么来的。
        {"id": "locked", "name": "内堂", "detail": "x", "exits": ["旧巷"],
         "unlock": {"act_min": 3}}]}}


def _st():
    st = runtime.default_state()
    st["location_id"] = "l1"
    st["act"] = 1
    return st


# ── 两把锁分家 ────────────────────────────────────────────────────────────────

def test_moving_is_the_models_call_now():
    assert runtime.LLM_MAP_WRITES is True


def test_minting_places_is_still_not():
    """这一刀只交出「谁在哪」，没交出「有哪些地方」。"""
    assert runtime.LLM_MINTS_PLACES is False


def test_minting_is_still_dead_end_to_end():
    class _L:
        def generate(self, p):
            if p.get("describe_place"):
                return {"name": "河堤", "detail": "水汽"}
            if p.get("risk_judge"):
                return {"risk": 100}
            return {}

    assert runtime.generate_and_move(copy.deepcopy(CONTENT), _st(), "河堤",
                                     llm=_L(), move=False) is None


# ── 模型申报到达 → 引擎跟上 ───────────────────────────────────────────────────

class _MoverLLM:
    """一个照实申报「我把人带到 X 了」的模型。"""

    def __init__(self, dest):
        self.dest = dest

    def generate(self, prompt):
        if prompt.get("summarize"):
            return {"memory": ""}
        if prompt.get("suggest"):
            return {"suggestions": []}
        if prompt.get("intro") or prompt.get("observe"):
            return {"beats": [{"type": "description", "speaker_name": None, "text": "x"}],
                    "affinity_delta": 0, "advance_act": False, "ending": None}
        return {"beats": [{"type": "description", "speaker_name": None,
                           "text": f"你们一路走到了{self.dest}。"}],
                "affinity_delta": 0, "advance_act": False, "ending": None,
                "moved_to": self.dest}


def _turn(llm, content=None):
    """⚠️ run_turn 在副本上干活，结果在 out["state"] 里。
    我第一版断言的是传进去那个 st —— 于是“不该动”那几条全部空转，
    无论闸在不在都绿。一个不会红的红样本比没有红样本更坏。"""
    out = runtime.run_turn(content or CONTENT, _st(), {"name": "我"}, "走吧",
                           channel="say", llm=llm)
    return (out.get("state") or {}).get("location_id")


def test_a_declared_arrival_moves_the_player():
    assert _turn(_MoverLLM("老码头")) == "dock", "模型说到了，引擎没跟上"


def test_the_authors_exits_no_longer_veto_the_fiction():
    """⚠️ 这一条是这一刀的核心。孤岛没有任何通路，从前一律驳回。

    线上实弹: 剧本自己的设定里那两个地方走三分钟就到，作者只是没把这条边写进 exits。
    引擎拿一张不完整的邻接表去否决故事，输的永远是引擎 —— 模型照样把人写过去，
    只是账本不跟，于是文与实分家。现在账本跟上。
    """
    assert _turn(_MoverLLM("孤岛")) == "far", "作者漏写一条边，就永远去不了那儿"


def test_the_unlock_gate_still_holds():
    """解锁是作者的剧作结构，不是地理 —— 这一条【没有】交给模型。"""
    assert _turn(_MoverLLM("内堂")) == "l1", "第一幕就进了第三幕才开的地方"


def test_a_place_that_does_not_exist_moves_nobody():
    """不在册的地方仍然去不了 —— 那是铸造，归另一把锁。"""
    assert _turn(_MoverLLM("河堤")) == "l1"


# ── 散文已经把人写过去了 → 回合末收账 ─────────────────────────────────────────

def test_prose_arrival_is_settled_instead_of_ignored():
    """模型忘了申报，但旁白已经把人写到门口了。从前这一整类被丢弃，正是
    「正文在别处、位置没动」的最大来源。"""
    st = _st()
    runtime.settle_prose_arrival(CONTENT, st, [
        {"type": "description", "text": "你们一路走到了老码头，风很大。"}], "l1", None)
    assert st["location_id"] == "dock"


def test_prose_arrival_still_respects_the_unlock_gate():
    st = _st()
    runtime.settle_prose_arrival(CONTENT, st, [
        {"type": "description", "text": "你们推门走进了内堂。"}], "l1", None)
    assert st["location_id"] == "l1"


# ── 玩家自己那条路毫发无伤 ────────────────────────────────────────────────────

def test_tapping_the_map_still_works():
    st = _st()
    runtime.apply_move(CONTENT, st, "老码头")
    assert st["location_id"] == "dock"
