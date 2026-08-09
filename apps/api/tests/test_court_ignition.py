# -*- coding: utf-8 -*-
"""💘 追求系统点火 (2026-08-04):

court_tick 全仓零调用 → char_sim 里永远没有 court 键 → court_directive_for 永远返回
None → 那 150 行追求代码从写完那天起一次都没跑过 (生产 162 局, 含 court 键的 run = 0)。

同时触发线定在心动 15, 而生产实测心动天花板只有 6~8 (只有「心动」和「和好」两种事件
产 romance, 且「心动」带 8 回合冷却)。也就是说【就算接上电, 这条线物理上也到不了】。

Yi 的方向 (2026-08-04): 玩家没那么多时间堆好感, 直接把最好的陪伴体验给玩家 ——
所以线要降到「玩家明确撩过一次」就够 (一次心动事件 = romance +4)。
稀缺性靠【单追求者锁】守, 不靠让玩家熬。
"""
from app.engine import runtime


def _content(*chars):
    return {"story": {"characters": list(chars),
                      "acts": [{"index": 1, "title": "一"}]}, "secrets": []}


ROMANCEABLE = {"id": "c1", "name": "阿珍", "is_lead": True,
               "love_style": "傲娇",
               "relation_allowed": ["stranger", "peer", "friend", "flirt", "lover"]}
ROMANCEABLE2 = {"id": "c2", "name": "阿强",
                "love_style": "直球",
                "relation_allowed": ["stranger", "peer", "friend", "flirt", "lover"]}


def test_one_flirt_is_enough_to_start_being_pursued():
    """撩过一次 (心动 +4) 就该有人开始留意你 —— 不许让玩家熬到 15。"""
    st = runtime.default_state()
    st["rel"] = {"c1": {"closeness": 5, "romance": 4}}
    runtime.court_tick(_content(ROMANCEABLE), st)
    court = ((st.get("char_sim") or {}).get("c1") or {}).get("court") or {}
    assert court.get("stage") == 1, f"心动 4 还没人追 — 门槛还是太高: {court}"


def test_stone_cold_player_is_not_pursued():
    """一次都没撩过就被追 = 角色像销售。零心动不许开台账。"""
    st = runtime.default_state()
    st["rel"] = {"c1": {"closeness": 40, "romance": 0}}   # 好搭档, 但没心动
    runtime.court_tick(_content(ROMANCEABLE), st)
    assert not ((st.get("char_sim") or {}).get("c1") or {}).get("court")


def test_single_pursuer_lock_holds():
    """两个人都够线也只开一本 —— 稀缺性靠这把锁, 不靠门槛。"""
    st = runtime.default_state()
    st["rel"] = {"c1": {"closeness": 5, "romance": 8},
                 "c2": {"closeness": 5, "romance": 6}}
    c = _content(ROMANCEABLE, ROMANCEABLE2)
    runtime.court_tick(c, st)
    runtime.court_tick(c, st)          # 再跑一轮也不许开第二本
    opened = [cid for cid, si in (st.get("char_sim") or {}).items()
              if (si.get("court") or {}).get("stage")]
    assert len(opened) == 1, f"同时开了 {len(opened)} 本追求台账 — 后宫感就是这么来的"
    assert opened[0] == "c1", "该由心动最高的那位来追"


def test_tick_is_actually_wired_into_a_turn():
    """点火验收: 跑一个真回合, 台账要自己开出来 (不是靠测试手调 court_tick)。"""
    st = runtime.default_state()
    st["rel"] = {"c1": {"closeness": 5, "romance": 6}}
    out = runtime.run_turn(_content(ROMANCEABLE), st, {"name": "我"}, "你好",
                           channel="say", llm=runtime_mock())
    court = ((out["state"].get("char_sim") or {}).get("c1") or {}).get("court") or {}
    assert court.get("stage"), "court_tick 没被接进回合管线 — 追求系统仍然是零调用"


def test_threshold_zero_disables_everything():
    """剧本级关闭: pursue_threshold=0 时全系统零副作用。"""
    st = runtime.default_state()
    st["rel"] = {"c1": {"closeness": 5, "romance": 40}}
    c = _content(ROMANCEABLE)
    c["story"]["tuning"] = {"pursue_threshold": 0}
    runtime.court_tick(c, st)
    assert not ((st.get("char_sim") or {}).get("c1") or {}).get("court")


def runtime_mock():
    from app.engine.llm import MockLLM
    return MockLLM()


def test_a_long_sitting_gets_more_than_one_beat():
    """一游戏日一拍 + real_clock 默认开 = 一个现实日只演一拍, 六阶要走六天。
    玩家的时间货币是【一次长坐】不是【一个现实日】—— 加回合计时, 二者先到先算。"""
    st = runtime.default_state()
    st["rel"] = {"c1": {"closeness": 5, "romance": 6}}
    c = _content(ROMANCEABLE)
    llm = runtime_mock()
    for _ in range(12):
        out = runtime.run_turn(c, st, {"name": "我"}, "你今天真好看", channel="say", llm=llm)
        st = out["state"]
    court = (((st.get("char_sim") or {}).get("c1") or {}).get("court") or {})
    # ⚠️ 判据 2026-08-09 换了。从前用 beats >= 2 当「被追了不止一次」的代理——那时候
    #    beats 只增不减，因为消费它的 court_apply_response 【没有任何调用点】。
    #    第四环接上之后 beats 会在推进时清零，所以要看走到第几步：保底推进需要攒够
    #    两拍才走一级，stage >= 2 就等于至少演过两次主动，比原来的代理更硬。
    assert int(court.get("stage") or 0) >= 2, \
        f"12 拍追求线没往前走一步（stage={court.get('stage')}, beats={court.get('beats')}）"


def test_turn_gap_is_tunable_and_respected():
    """回合计时可按剧本调; 没到间隔就不许出第二拍 (慢热本调大即可)。"""
    st = runtime.default_state()
    st["rel"] = {"c1": {"closeness": 5, "romance": 6}}
    c = _content(ROMANCEABLE)
    c["story"]["tuning"] = {"pursue_gap_turns": 99}
    llm = runtime_mock()
    for _ in range(8):
        st = runtime.run_turn(c, st, {"name": "我"}, "你好", channel="say", llm=llm)["state"]
    beats = int((((st.get("char_sim") or {}).get("c1") or {})
                 .get("court") or {}).get("beats") or 0)
    assert beats <= 1, f"间隔调到 99 还演了 {beats} 拍 — 计时器没生效"
