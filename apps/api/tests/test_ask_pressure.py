# -*- coding: utf-8 -*-
"""❓ 先弄懂玩家想干什么，问不问是这之后的事 (Yi 2026-08-08)。

Yi 的原话:「AI 角色要尽可能花多的时间理解玩家想要干什么、现在的感受，
这种时候才需要提问题，而不是一昧地邀请玩家去做不想做的事情。」

先量: 生产 2001 条角色台词, 632 条带问号 = 32%, 三句里有一句在问你;
连续提问最长链 7 条, 连问 ≥2 的情况 215 次。
(而带邀约措辞的只有 2% —— 所以「一昧邀请」的体感, 真正来源是被连续追问。)

剧本的忌用清单第一条明明写着「查户口式连环提问——每轮至多问一个问题」,
inner_read 也早就要求「动笔前先想: TA 想要什么」。两条都在, 32% 照旧 ——
因为它们都是【说一句就完了】: 没有事实支撑, 也没有后果。

所以不加第 242 条禁令 (今天的家规: 引导而非制止)。改成给它两样东西:
  · 一个【事实】—— 你最近问了几个, TA 答了几个
  · 一个更明确的【活】—— 你已经知道 TA 想干什么的话, 就别问, 直接接住

⚠️ 认知边界照旧: 只数这个角色自己问过的、并且它在场听得见的那些。
"""
from app.engine import qwen, runtime


def _b(author, typ, sp, text, pres=None):
    return {"author": author, "type": typ, "speaker_name": sp,
            "text": text, "present_ids": pres}


LOG = [
    _b("engine", "dialogue", "甲", "你今天怎么来这么早？", ["a"]),
    _b("player", "dialogue", None, "睡不着", ["a"]),
    _b("engine", "dialogue", "甲", "睡不着？是不是有心事？", ["a"]),
    _b("engine", "dialogue", "甲", "要不要说说看？", ["a"]),
    _b("player", "dialogue", None, "我就想坐一会", ["a"]),
    _b("engine", "dialogue", "甲", "坐哪儿？要不去楼上？", ["a"]),
]


def test_it_counts_this_characters_own_questions():
    p = runtime.ask_pressure(LOG, "a", "甲")
    assert p["asked"] == 4, f"数错了: {p}"


def test_a_statement_is_not_a_question():
    log = [_b("engine", "dialogue", "甲", "我知道了。", ["a"])]
    assert runtime.ask_pressure(log, "a", "甲")["asked"] == 0


def test_narration_is_not_asking():
    """旁白里的问号不算 —— 那不是角色在问玩家。"""
    log = [_b("engine", "description", None, "他看着你，像是在问什么？", ["a"])]
    assert runtime.ask_pressure(log, "a", "甲")["asked"] == 0


def test_another_characters_questions_do_not_count():
    log = LOG + [_b("engine", "dialogue", "乙", "你吃了吗？", ["a", "b"])]
    assert runtime.ask_pressure(log, "a", "甲")["asked"] == 4


def test_witness_isolation_holds():
    """⚠️ 我不在场的那几拍不该进我的账 —— 认知边界是护城河。"""
    log = [_b("engine", "dialogue", "甲", "你去哪了？", ["b"])]      # 甲 不在见证名单里
    assert runtime.ask_pressure(log, "a", "甲")["asked"] == 0


def test_it_only_looks_at_the_recent_window():
    log = [_b("engine", "dialogue", "甲", f"问题{i}？", ["a"]) for i in range(30)]
    assert runtime.ask_pressure(log, "a", "甲", window=6)["asked"] <= 6


def test_an_empty_log_is_quiet():
    assert runtime.ask_pressure(None, "a", "甲") == {"asked": 0, "streak": 0}


def test_the_streak_counts_unanswered_questions_in_a_row():
    """连问才是玩家真正受不了的那个东西 (线上最长链 7)。"""
    assert runtime.ask_pressure(LOG, "a", "甲")["streak"] == 1      # 最后一条问句前有玩家发言
    log = LOG[:4]                                            # …怎么来这么早 / 有心事 / 说说看
    assert runtime.ask_pressure(log, "a", "甲")["streak"] == 2


# ── 提示词: 给事实和活, 不加禁令 ──────────────────────────────────────────────

def _sys(**kw):
    p = {"speaker_name": "甲", "speaker_persona": "x", "channel": "say",
         "persona": {"name": "我"}, "context": {}}
    p.update(kw)
    return qwen._build_system(p)


def test_the_model_is_told_to_read_before_it_answers():
    s = _sys()
    assert "TA 现在想干什么" in s, "没让它先弄懂玩家要什么"
    assert "读懂了就直接接住" in s, "读懂之后该怎么办没说 —— 只说「先想想」等于没说"
    assert "真的不知道" in s, "没给出【什么时候才该问】的判据"
    assert "宁可猜错一次顺着演下去" in s, "没给不确定时的默认动作，它还是会停下来盘问"


def test_a_run_of_questions_becomes_a_fact_not_a_ban():
    """给数字, 不给禁令 —— 让它自己判断该不该再问。"""
    s = _sys(ask_pressure={"asked": 4, "streak": 3})
    assert "3" in s and ("连着" in s or "连续" in s), "连问没有变成一个它看得见的事实"
    assert "绝不许提问" not in s, "又加了一条禁令"


def test_no_pressure_no_block():
    """没在连问时不许平白多一段 —— 每回合都在花 token。"""
    assert "连着" not in _sys(ask_pressure={"asked": 0, "streak": 0})
