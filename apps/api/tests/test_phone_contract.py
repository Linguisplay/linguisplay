"""📱 传讯合同 (Yi, 2026-07-09): the phone is a real comms system with ledger teeth —
contacts are met-people only (no omniscience), a summon pins the character to the
player's place, an errand becomes their standing intent, and texting someone standing
right next to you is a MOMENT they get to react to (never a silent normal reply)."""

from app.engine import runtime

STORY = {
    "story": {"id": "s",
              "characters": [
                  {"id": "a", "name": "甲", "is_lead": True, "home_location_id": "hall"},
                  {"id": "b", "name": "乙", "home_location_id": "alley"},
                  {"id": "c", "name": "丙", "home_location_id": "alley"},
              ],
              "acts": [{"index": 1, "title": "一"}],
              "locations": [{"id": "hall", "name": "门厅", "exits": ["后巷"]},
                            {"id": "alley", "name": "后巷", "exits": ["门厅"]}]},
    "secrets": [],
}


class PhoneSpy:
    def __init__(self, **out):
        self.out = out
        self.prompts = []

    def generate(self, prompt):
        if prompt.get("phone_reply"):
            self.prompts.append(prompt)
            return {"msgs": ["好。"], "closeness": 0, "romance": 0, **self.out}
        return {}


def _st(loc="hall", met=("a", "b", "c")):
    st = runtime.default_state()
    st["location_id"] = loc
    st["met_ids"] = list(met)
    return st


def test_contacts_are_met_people_only():
    st = _st(met=("b",))          # only 乙 has been met
    # 📇 新法 (Yi): 联系方式要靠剧情挣 — 只见过面还进不了通讯录
    view0 = runtime.phone_threads_view(STORY, st)
    assert [c["char_id"] for c in view0["contacts"]] == []
    st["contact_ids"] = ["b"]     # 交换过之后才出现
    view = runtime.phone_threads_view(STORY, st)
    ids = [c["char_id"] for c in view["contacts"]]
    assert ids == ["b"]           # 丙 exists in the story but is INVISIBLE here
    assert view["contacts"][0]["has_thread"] is False


def test_summon_pins_the_character_to_the_player():
    llm = PhoneSpy(coming=True)
    st = _st(loc="hall")          # 乙 lives in alley — absent
    view = runtime.phone_send(STORY, st, {"name": "我"}, "b", "过来门厅找我", llm=llm)
    assert view["coming"] is True
    assert st["char_pins"] == {"b": "hall"}       # TA真的会来：行踪已钉
    assert llm.prompts[0].get("same_room") is False


def test_task_becomes_standing_intent():
    llm = PhoneSpy(task="盯着丙的动静")
    st = _st(loc="hall")
    view = runtime.phone_send(STORY, st, {"name": "我"}, "b", "帮我盯着丙", llm=llm)
    assert view["task"] == "盯着丙的动静"
    assert st["char_sim"]["b"]["intent"] == "盯着丙的动静"


def test_character_memory_never_falls_back_to_the_players_global_digest():
    """信息不开天眼: a character with no digest of their own gets NOTHING — the global
    digest is the player's whole life and must never leak into a first contact."""
    llm = PhoneSpy()
    st = _st(loc="hall")
    st["memory"] = "玩家的全部人生流水账（乙从未在场）"
    runtime.phone_send(STORY, st, {"name": "我"}, "b", "你好", llm=llm)
    assert llm.prompts[0].get("memory") == ""

    class SceneSpy:
        def __init__(self):
            self.prompts = []

        def generate(self, prompt):
            if prompt.get("speaker_name"):
                self.prompts.append(prompt)
            if prompt.get("summarize"):
                return {"memory": ""}
            if prompt.get("suggest"):
                return {"suggestions": []}
            return {"beats": [{"type": "dialogue", "speaker_name": "甲", "text": "嗯。"}],
                    "affinity_delta": 0, "advance_act": False, "ending": None}

    spy = SceneSpy()
    st2 = _st(loc="hall")
    st2["memory"] = "全局流水账"
    runtime.run_turn(STORY, st2, {"name": "我"}, "你好", channel="say", llm=spy)
    assert all(p.get("memory") == "" for p in spy.prompts if "memory" in p)


def test_texted_appointment_books_a_real_promise():
    """短信里约的会走同一本约定账 — 到点没去TA记仇的那本 (Yi: 对对)。"""
    llm = PhoneSpy(promise={"what": "看画", "day_offset": 1, "slot": "晨",
                            "place": "后巷"})
    st = _st(loc="hall")
    view = runtime.phone_send(STORY, st, {"name": "我"}, "b", "明早去看你画画？", llm=llm)
    assert view["promise"]["what"] == "看画"
    booked = st.get("promises") or []
    assert any(p.get("char_id") == "b" and p.get("what") == "看画"
               for p in booked)
    assert view.get("promises") is not None   # the promise bar payload rides the reply


def test_phone_rel_movement_is_visible_and_tiers_announce():
    """隔着屏幕也是经营 (Yi): the delta shows in the thread, a tier-up announces."""
    llm = PhoneSpy(closeness=2, romance=1)
    st = _st(loc="hall")
    view = runtime.phone_send(STORY, st, {"name": "我"}, "b", "谢谢你昨天帮我", llm=llm)
    assert view["rel"]["closeness"] == 2 and view["rel"]["romance"] == 1
    assert st["rel"]["b"]["closeness"] >= 2          # the ledger moved for real


def test_long_thread_folds_into_the_characters_memory():
    """电话记忆并账 (Yi: 手机聊天的记忆有问题): overflow beyond the 12-message window
    digests into memory_by_char — the same memory the scenes read."""
    st = _st(loc="hall")
    th = runtime._thread(st, "b")
    for i in range(30):
        th["msgs"].append({"from": "me" if i % 2 else "them", "text": f"第{i}句", "at": ""})
    runtime._digest_phone_overflow(st, "b", MockLLMForDigest())
    assert "第0句" in (st["memory_by_char"]["b"])     # old talk survives in the digest
    assert th["digested_upto"] == 30 - 12
    # capping the thread never desyncs the pointer
    # ⚠️ 造的量必须真的越过上限, 否则这条断言在空转 (2026-08-06 上限 60→200 时
    #    这里原本写死 40 条, 加起来才 70, 一刀都掐不到)
    _before = len(th["msgs"])
    _over = runtime.THREAD_MSG_CAP + 10 - _before
    for i in range(_over):
        th["msgs"].append({"from": "me", "text": f"新{i}", "at": ""})
    runtime._thread_cap(th)
    assert len(th["msgs"]) == runtime.THREAD_MSG_CAP
    assert th["digested_upto"] == max(0, (30 - 12) - 10)


class MockLLMForDigest:
    def generate(self, prompt):
        if prompt.get("summarize"):
            lines = " ".join(l.get("content", "") for l in (prompt.get("new_lines") or []))
            return {"memory": ((prompt.get("prior_memory") or "") + " " + lines).strip()[-2000:]}
        return {}


def test_same_room_text_is_a_moment_not_a_summon():
    llm = PhoneSpy(coming=True)   # even if the model says coming, presence wins
    st = _st(loc="alley")         # the player walked INTO 乙's alley
    view = runtime.phone_send(STORY, st, {"name": "我"}, "b", "在吗", llm=llm)
    assert llm.prompts[0].get("same_room") is True   # the tease directive fires
    assert view["coming"] is False
    assert not st.get("char_pins")                   # no pin — TA已经在场
