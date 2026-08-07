# -*- coding: utf-8 -*-
"""📱↔🎭 线上线下不许对不上 (Yi 的产品铁律: 记忆一定要共享)。

⚠️ 本文件 2026-08-07 整个重写过, 因为我 2026-08-06 的诊断是【错的】。

错的那一版说:「主拍提示词里只有 phone_unread, 没有任何一条真实短信内容, 所以你
给某人连发五条, 走到他面前他不知道」。据此我造了 phone_recent_for_scene。
实际上 sms_tail (2026-07-03 就在了) 一直在把最近 6 条短信喂进主拍 —— 我 grep
run_turn_stream 时用的模式没匹配上它, 于是漏看, 于是重复造轮子。

而且新造的那块人称是【反的】: sms_tail 用「TA=玩家 / 你=角色本人」, 跟整份提示词
「你是蓝信一」一致; 我那块自己另立一套「你=对方 / 我=你」。两块同时挂在一个提示词
里, 同一条消息被标成相反的人。已删我那块, 本文件改成守住活下来的那个。

留下的真东西只有一条: _digest_phone_overflow 的折账闸在 18 条, 而生产 10 条线程
长度中位 13 —— 中位数天生够不着。那条闸管的是长线程压缩, 跟「刚聊过」是两件事,
后者由 sms_tail 负责, 一直好着。
"""
from app.engine import runtime


CONTENT = {"story": {
    "id": "s", "title": "t",
    "characters": [
        {"id": "a", "name": "蓝信一", "is_lead": True, "persona_text": "龙城帮马仔",
         "home_location_id": "hall"},
        {"id": "b", "name": "阿鬼", "persona_text": "跛脚", "home_location_id": "hall"},
    ],
    "acts": [{"index": 1, "title": "一"}],
    "locations": [{"id": "hall", "name": "祥记面档", "detail": "面档", "exits": []}],
    "phone": {"device": "手机"}}, "secrets": []}


def _state():
    st = runtime.default_state()
    st["location_id"] = "hall"
    st["contact_ids"] = ["a", "b"]
    st.setdefault("phone", {}).setdefault("threads", {})["a"] = {"msgs": [
        {"from": "me", "text": "果栏那批货我跟你去。", "at": "第2天·夜"},
        {"from": "them", "text": "别乱说话，到时候跟紧我。", "at": "第2天·夜"},
    ]}
    return st


def test_a_short_thread_never_folds_into_memory():
    """红样本: 折账那条路管不到刚聊完的两句 —— 闸在 18 条, 生产中位 13。"""
    st = _state()
    runtime._digest_phone_overflow(st, "a", None)
    assert not (st.get("memory_by_char") or {}).get("a"), "两条消息就折账了? 闸的口径变了"


# ── ⚠️ 2026-08-07 查错: 我昨天的结论错了, 这一节整个重写 ──────────────────────
#
# 昨天我 grep run_turn_stream 只看到 phone_unread, 就断言「主拍完全读不到手机内容」,
# 于是造了 phone_recent_for_scene 这个轮子。实际上 sms_tail (2026-07-03 就在了)
# 一直在把最近 6 条短信喂进主拍 —— 我搜漏了。
# 更糟的是我那块的人称是【反的】: sms_tail 用「TA=玩家 / 你=角色本人」, 跟整份
# 提示词「你是蓝信一」一致; 我却另立一套「你=对方 / 我=你」。两块同时挂在一个
# 提示词里, 同一条消息被标成相反的人。已删我那块, 这里改成守住活下来的那个。

def test_the_scene_prompt_does_carry_recent_texts():
    """线上线下不许对不上 —— 这条能力一直都在, 别在清理时把它也删了。"""
    st = _state()
    tail = runtime.sms_tail_line(st, "a")
    assert "果栏" in tail, f"最近的短信没进主拍: {tail!r}"


def test_the_pronouns_match_the_rest_of_the_prompt():
    """整份提示词是「你是蓝信一」—— 所以角色自己发的标「你」, 玩家发的标「TA」。
    两套人称同时存在过一次 (见本节抬头), 别再来第二次。"""
    st = _state()
    tail = runtime.sms_tail_line(st, "a")
    assert tail.startswith("TA："), f"玩家发的那条没标成 TA: {tail!r}"
    assert "；你：" in tail, f"角色自己发的那条没标成 你: {tail!r}"


def test_only_that_characters_own_thread():
    """认知边界: 十二少看不到你跟阿彩的短信。"""
    assert not runtime.sms_tail_line(_state(), "b")


def test_no_thread_no_block():
    assert runtime.sms_tail_line(runtime.default_state(), "a") == ""


def test_there_is_only_one_sms_block_in_the_prompt():
    """真正的合同: 同一件事只许有一个读口。两个读口 = 迟早对不上。"""
    from app.engine import qwen
    s = qwen._build_system({"speaker_name": "阿彩", "speaker_persona": "洗头妹",
                            "channel": "say", "persona": {"name": "蔡妍"}, "context": {},
                            "device": "手机", "sms_tail": "TA：在吗；你：在"})
    assert s.count("在吗") == 1, "同一条短信在提示词里出现了不止一次"
