# -*- coding: utf-8 -*-
"""📱↔🎭 线上线下不许对不上 (Yi 的产品铁律: 记忆一定要共享)。

单向镜: phone_send 收 beat_log —— 手机读得到剧情; 而主拍提示词里只有
phone_unread 这个红点数和 device, 【没有任何一条真实短信内容】。所以你给某人
连发五条消息, 走到他面前, 他不知道。

它并不是完全没接线: _digest_phone_overflow 会把溢出的旧消息折进 memory_by_char,
但闸在 `len(msgs) - digested <= 12 + 6` —— 线程要【超过 18 条】才折。
生产实测: 10 条线程, 长度中位 13, 只有 2 条并过账, 8 条从没并过。
中位数天生够不着那个闸。

修法是把 phone_send 的成例反过来做一遍: 在场角色的最近几条短信直接进主拍提示词。
零新增 LLM 调用 —— 这些字本来就在 state 里躺着。
折账那条路留着不动: 它管的是长线程的压缩, 跟这里管的"刚聊过"是两件事。
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
    runtime._digest_phone_overflow(st, "a", None)   # llm 用不到: 应当在闸前就返回
    assert not (st.get("memory_by_char") or {}).get("a"), "两条消息就折账了? 闸的口径变了"


def test_recent_texts_reach_the_scene_prompt():
    st = _state()
    got = runtime.phone_recent_for_scene(CONTENT, st, "a")
    assert got, "在场角色刚聊过的短信没进主拍"
    assert "果栏" in "".join(str(x) for x in got)


def test_it_marks_who_said_what():
    """分不清谁说的, 角色会把自己说过的话当成玩家说的。"""
    got = "".join(str(x) for x in runtime.phone_recent_for_scene(CONTENT, _state(), "a"))
    assert "你" in got or "我" in got or "对方" in got


def test_a_character_never_sees_someone_elses_thread():
    """认知边界: 阿鬼看不到你跟蓝信一的短信。"""
    assert not runtime.phone_recent_for_scene(CONTENT, _state(), "b")


def test_no_thread_no_block():
    """没聊过就不该平白多一段提示词 (每回合都在花 token)。"""
    st = runtime.default_state()
    assert runtime.phone_recent_for_scene(CONTENT, st, "a") == []


def test_it_is_capped():
    st = _state()
    st["phone"]["threads"]["a"]["msgs"] = [
        {"from": "me", "text": f"第{i}条", "at": "x"} for i in range(40)]
    assert len(runtime.phone_recent_for_scene(CONTENT, st, "a")) <= 6


def test_it_reaches_the_scene_prompt_for_real():
    """进了 state 不算数, 要真进提示词。"""
    from app.engine import qwen
    s = qwen._build_system({"speaker_name": "蓝信一", "speaker_persona": "马仔",
                            "channel": "say", "persona": {"name": "蔡妍"}, "context": {},
                            "device": "大哥大",
                            "phone_recent": ["你：果栏那批货我跟你去。", "我：别乱说话。"]})
    assert "果栏" in s and "大哥大" in s
    assert "已经说过" in s, "只贴了短信却没说要拿它怎么办"


def test_no_texts_no_block():
    from app.engine import qwen
    s = qwen._build_system({"speaker_name": "蓝信一", "speaker_persona": "马仔",
                            "channel": "say", "persona": {"name": "蔡妍"}, "context": {}})
    assert "刚在" not in s


def test_already_folded_messages_are_not_repeated():
    """已经折进 memory_by_char 的旧消息不该再原样喂一遍 (两处都在花 token)。"""
    st = _state()
    st["phone"]["threads"]["a"]["msgs"] = [
        {"from": "me", "text": f"第{i}条", "at": "x"} for i in range(30)]
    st["phone"]["threads"]["a"]["digested_upto"] = 24
    got = "".join(str(x) for x in runtime.phone_recent_for_scene(CONTENT, st, "a"))
    assert "第0条" not in got and "第10条" not in got, "把已经折过账的旧消息又喂了一遍"
    assert "第29条" in got
