# -*- coding: utf-8 -*-
"""⚡ 记忆折叠出关键路径 (4秒军令): 后台折、下一回合合账。三道闸 (审查实锤):
没折完票不烧 / prior 等值守卫 (回合间追账不被覆盖) / 游标单调。丢单自愈。"""
import time

from app.engine import runtime


class DigestLLM:
    def __init__(self, text="早年的事都记成一句话了"):
        self.text = text
        self.calls = 0

    def generate(self, prompt):
        assert prompt.get("summarize")
        self.calls += 1
        return {"memory": self.text}


def _long_history(n):
    return [{"speaker": "b", "text": f"第{i}句"} for i in range(n)]


def _wait_shelf(tok):
    for _ in range(150):
        if tok in runtime._FOLD_PENDING:
            return True
        time.sleep(0.02)
    return False


def test_fold_runs_in_background_and_lands_next_turn():
    st = runtime.default_state()
    llm = DigestLLM()
    hist = _long_history(runtime.MEMORY_WINDOW + runtime.MEMORY_BATCH)
    runtime._folds_async(st, [("c1", hist)], llm)
    tok = st.get("folds_pending")
    assert tok, "折叠票据要挂在 state 上"
    assert "c1" not in (st.get("memory_by_char") or {}), "本回合不动账"
    assert _wait_shelf(tok) and llm.calls == 1
    assert runtime.apply_pending_folds(st) is True
    assert st["memory_by_char"]["c1"] == llm.text
    assert st["memcov_by_char"]["c1"] > 0
    assert not st.get("folds_pending"), "取到货票据才销"
    assert runtime.apply_pending_folds(st) is False


def test_unfinished_fold_keeps_the_ticket():
    """快节奏连打: 后台没折完, 票不烧 — 下回合还能收 (profile 家法)。"""
    st = runtime.default_state()
    st["folds_pending"] = "notyet0000ok"
    assert runtime.apply_pending_folds(st) is False
    assert st["folds_pending"] == "notyet0000ok", "货没到票必须留着"
    # 货到了: 下一次收账成功
    runtime._FOLD_PENDING["notyet0000ok"] = {"c1": ("折好了", 30, "")}
    assert runtime.apply_pending_folds(st) is True
    assert st["memory_by_char"]["c1"] == "折好了"


def test_interturn_append_survives_fold_landing():
    """🏦 P1 回归锁: 回合间 bank/手机往 memory_by_char 追的账, 不被旧底折叠成品覆盖。"""
    st = runtime.default_state()
    st["memory_by_char"] = {"c1": "旧底"}
    st["folds_pending"] = "tokclobber00"
    runtime._FOLD_PENDING["tokclobber00"] = {"c1": ("旧底折成的摘要", 40, "旧底")}
    # 回合间: 银行转账追了一笔
    st["memory_by_char"]["c1"] = "旧底；对方给你转了30文"
    assert runtime.apply_pending_folds(st) is False, "底变了本单作废"
    assert st["memory_by_char"]["c1"] == "旧底；对方给你转了30文", "追加的账一字不少"
    assert int((st.get("memcov_by_char") or {}).get("c1", 0)) == 0, "游标不动, 重折自愈"


def test_reincarnate_ticket_cannot_resurrect_past_life():
    """🔄 转生清空记忆后, 前世折叠成品被 prior 守卫挡下。"""
    st = runtime.default_state()
    st["memory_by_char"] = {}          # 转生清账后
    st["folds_pending"] = "pastlife0000"
    runtime._FOLD_PENDING["pastlife0000"] = {"c1": ("前世的记忆", 60, "前世的底")}
    assert runtime.apply_pending_folds(st) is False
    assert "c1" not in st["memory_by_char"], "前世记忆不许复活"


def test_not_enough_material_no_ticket():
    st = runtime.default_state()
    llm = DigestLLM()
    runtime._folds_async(st, [("c1", _long_history(3))], llm)
    assert not st.get("folds_pending")
    assert llm.calls == 0


def test_cursor_never_regresses():
    st = runtime.default_state()
    st["memcov_by_char"] = {"c1": 99}
    st["memory_by_char"] = {"c1": "新账"}
    st["folds_pending"] = "tok123456789"
    runtime._FOLD_PENDING["tok123456789"] = {"c1": ("旧账", 50, "新账")}
    runtime.apply_pending_folds(st)
    assert st["memory_by_char"]["c1"] == "新账", "过期折叠不许倒灌"
    assert st["memcov_by_char"]["c1"] == 99


# ── 场记同款 pending (4秒军令第二刀) ─────────────────────────────────────────

def test_track_async_lands_next_turn():
    st = runtime.default_state()
    st["location_id"] = None

    class TrackLLM:
        def generate(self, prompt):
            assert prompt.get("track_scene")
            return {"frames": [], "player": {"pos": "靠窗坐着", "doing": "翻账本"},
                    "progressed": True}

    content = {"story": {"id": "s", "characters": [], "acts": [{"index": 1, "title": "一"}]},
               "secrets": []}
    runtime.track_frames_async(content, st, {"name": "我"},
                               [{"type": "description", "text": "你靠窗坐下翻起账本。"}],
                               TrackLLM())
    tok = st.get("track_pending")
    assert tok
    for _ in range(150):
        if tok in runtime._TRACK_PENDING:
            break
        time.sleep(0.02)
    assert not (st.get("player_pos") or {}).get("text"), "本回合不动账"
    assert runtime.apply_pending_track(st) is True
    assert "靠窗坐着" in (st.get("player_pos") or {}).get("text", "")
    assert runtime.apply_pending_track(st) is False


def test_track_unfinished_keeps_ticket():
    st = runtime.default_state()
    st["track_pending"] = "slowtrack000"
    assert runtime.apply_pending_track(st) is False
    assert st["track_pending"] == "slowtrack000"
