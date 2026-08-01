# -*- coding: utf-8 -*-
"""🎬 场账本 (docs/scene-ledger.md) 单测: 开收场/钉子豁免/时钟补拨/问答账申报与兜底。
全部打在 helpers 上 (settle 的在场名单用 monkeypatch 喂, 不依赖完整剧本 fixture)。"""
from app.engine import runtime


def _tun(on=1):
    return {**runtime.DEFAULT_TUNING, "scene_ledger": on}


def _clk(day=1, slot=0):
    return {"day": day, "slot": slot, "turns_in_slot": 0}


def test_open_pins_cast_and_close_unpins_only_own():
    st = {"clock": _clk(), "char_pins": {"shin": "loc_alley"}}   # 约定钉在先
    runtime._sl_open(st, "loc_roof", ["shin", "twelfth"], st["clock"])
    sl = runtime._sl(st)
    assert sl and sl["loc"] == "loc_roof" and sl["cast"] == ["shin", "twelfth"]
    # shin 已有约定钉 — 不许清抢; twelfth 是本场钉的
    assert st["char_pins"]["shin"] == "loc_alley"
    assert st["char_pins"]["twelfth"] == "loc_roof"
    assert sl["pins"] == ["twelfth"]
    runtime._sl_close(st)
    assert runtime._sl(st) is None
    assert "twelfth" not in st["char_pins"]          # 自己钉的拔了
    assert st["char_pins"]["shin"] == "loc_alley"    # 别人的钉原样


def test_close_repays_deferred_ticks():
    st = {"clock": _clk(day=2, slot=2)}
    runtime._sl_open(st, "loc_roof", ["shin"], st["clock"])
    runtime._sl(st)["ticks"] = 2
    runtime._sl_close(st)
    # 夜(2) + 2 格 = 次日午(1)
    assert st["clock"]["day"] == 3 and st["clock"]["slot"] == 1


def test_drop_pins_on_leave_closes_scene():
    st = {"clock": _clk(), "char_pins": {}}
    runtime._sl_open(st, "loc_roof", ["shin"], st["clock"])
    runtime._drop_pins_on_leave(st, "loc_roof")
    assert runtime._sl(st) is None
    assert "shin" not in (st.get("char_pins") or {})


def test_settle_opens_on_dialogue_and_flag_off_closes(monkeypatch):
    st = {"clock": _clk(), "location_id": "loc_roof"}
    monkeypatch.setattr(runtime, "scene_characters",
                        lambda c, s: [{"id": "shin"}, {"id": "cai"}])
    beats = [{"type": "dialogue", "speaker_name": "蓝信一", "text": "走不走。"}]
    runtime._sl_settle({}, st, _tun(1), beats, "好呀", {}, "say", "cai")
    sl = runtime._sl(st)
    assert sl and sl["cast"] == ["shin"] and sl["loc"] == "loc_roof"   # 玩家不入 cast
    # 旗中途关掉 → settle 负责把残留的场收干净
    runtime._sl_settle({}, st, _tun(0), beats, "嗯", {}, "say", "cai")
    assert runtime._sl(st) is None


def test_settle_spent_dedup_and_age_close(monkeypatch):
    st = {"clock": _clk(), "location_id": "loc_roof"}
    monkeypatch.setattr(runtime, "scene_characters", lambda c, s: [{"id": "shin"}])
    beats = [{"type": "dialogue", "speaker_name": "蓝信一", "text": "喝。"}]
    runtime._sl_settle({}, st, _tun(1), beats, "好", {}, "say", "cai")
    for _ in range(2):
        runtime._sl_settle({}, st, _tun(1), beats, "好", {"scene_spent": "递汽水"}, "say", "cai")
    assert runtime._sl(st)["spent"] == ["递汽水"]     # 去重
    runtime._sl(st)["turns"] = 25
    runtime._sl_settle({}, st, _tun(1), beats, "好", {}, "say", "cai")
    assert runtime._sl(st) is None                     # 场龄超限强制收


def test_asked_fallback_and_answered_pairing(monkeypatch):
    st = {"clock": _clk(), "location_id": "loc_roof"}
    monkeypatch.setattr(runtime, "scene_characters", lambda c, s: [{"id": "shin"}])
    q_beats = [{"type": "dialogue", "speaker_name": "蓝信一",
                "text": "外面的人都说城寨是狗窝。一个月了，城寨怎么样？"}]
    runtime._sl_settle({}, st, _tun(1), q_beats, "我到了", {}, "say", "cai")
    log = st["asked_log"]
    assert len(log) == 1 and log[0]["a"] is None and "城寨怎么样" in log[0]["q"]
    # 下一回合玩家发言 → 最旧未答者结账 (兜底)
    runtime._sl_settle({}, st, _tun(1), [], "有人情味，比想象好", {}, "say", "cai")
    assert st["asked_log"][0]["a"] is not None
    view = runtime._asked_view(st)
    assert view["answered"] and not view["open"]


def test_asked_claim_rejected_when_prose_diverged(monkeypatch):
    """申报要对得上正文: plan 说问「你怕不怕高」, 渲染实际问了别的 → 驳回申报;
    正文问句带问号时兜底接管, 不带问号时宁漏 (不许记从没问出口的问题)。"""
    st = {"clock": _clk(), "location_id": "loc_roof"}
    monkeypatch.setattr(runtime, "scene_characters", lambda c, s: [{"id": "shin"}])
    beats = [{"type": "dialogue", "speaker_name": "某人",
              "text": "这个点钟不睡觉，是睡不着还是不想睡。"}]   # 无问号的问句
    runtime._sl_settle({}, st, _tun(1), beats, "随便聊聊", {"scene_asked": "你怕不怕高"},
                       "say", "cai")
    assert not st["asked_log"]          # 申报驳回 + 兜底无问号 → 宁漏
    beats2 = [{"type": "dialogue", "speaker_name": "某人", "text": "你到底怕不怕高？"}]
    runtime._sl_settle({}, st, _tun(1), beats2, "再聊", {"scene_asked": "你怕不怕高"},
                       "say", "cai")
    assert any("怕不怕高" in a["q"] for a in st["asked_log"])   # 对得上 → 收下


def test_asked_log_expires_by_day(monkeypatch):
    st = {"clock": _clk(day=5), "location_id": "loc_roof",
          "asked_log": [{"q": "旧问题", "a": None, "day": 1}]}
    monkeypatch.setattr(runtime, "scene_characters", lambda c, s: [{"id": "shin"}])
    runtime._sl_settle({}, st, _tun(1), [], "随便说点", {}, "say", "cai")
    assert all(a["q"] != "旧问题" for a in st["asked_log"])   # day+2 过期
