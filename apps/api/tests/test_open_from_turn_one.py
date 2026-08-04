# -*- coding: utf-8 -*-
"""🔓 陪伴三件从第一次对话就开 (Yi 2026-08-04):

「玩家没那么多时间堆好感, 直接把最好的陪伴体验给玩家。」三道熬时间的门拆掉:
  ① 联系方式: 原本要交情 10 才肯给、20 才主动给, 中间还有一道随缘骰 —— 而中位一局
     只有 4 拍, 大部分玩家【一辈子拿不到任何人的号】, 于是短信/朋友圈/主动联系整条
     陪伴链从来没被打开过。改成初次见面就进通讯录。
  ② 社交媒体: 互动不该再等交情。
  ③ 邀请同行: 原本要 closeness ≥ 25 (follow_min_closeness), 同样到不了。

稀缺性不再靠「熬」, 靠单追求者锁、主动名额、以及角色各自不同的热情方式。
"""
from app.engine import runtime


CHARS = [{"id": "c1", "name": "阿珍", "is_lead": True},
         {"id": "c2", "name": "阿强"}]
CONTENT = {"story": {"characters": CHARS,
                     "acts": [{"index": 1, "title": "一"}],
                     "locations": [{"id": "hall", "name": "大堂"}],
                     "phone": {"device": "手机"}},
           "secrets": []}


def _mock():
    from app.engine.llm import MockLLM
    return MockLLM()


def test_contact_lands_on_the_first_meeting():
    """第一次照面就该有号 —— 不再有「你们还没熟到那份上」。"""
    st = runtime.default_state()
    st["location_id"] = "hall"
    st = runtime.run_turn(CONTENT, st, {"name": "我"}, "你好", channel="say",
                          llm=_mock())["state"]
    assert runtime.has_contact(st, "c1"), "见了面还没号 — 陪伴链的第一环还锁着"


def test_asking_for_contact_is_never_refused_now():
    """开口要号不许再被交情挡回去。"""
    st = runtime.default_state()
    st["met_ids"] = ["c1"]
    st["rel"] = {"c1": {"closeness": 0, "romance": 0}}
    assert runtime.contact_will_give(CONTENT, st, "c1"), "交情 0 就该给"


def test_invite_along_works_for_a_stranger():
    """一开始就能邀人同行 (陌生人也行) —— 只有敌对才拒绝。"""
    st = runtime.default_state()
    st["location_id"] = "hall"
    st["met_ids"] = ["c1"]
    st["rel"] = {"c1": {"closeness": 0, "romance": 0}}
    out = runtime.set_follow(CONTENT, st, "c1", True)
    assert out["ok"], f"陌生人邀不动: {out.get('reason')}"
    assert "c1" in st.get("following", [])


def test_enemy_still_refuses_to_come_along():
    """敌对仍然拒绝 —— 这不是熬时间的门, 是人物立场。"""
    from app.engine import relationships
    st = runtime.default_state()
    st["location_id"] = "hall"
    st["met_ids"] = ["c1"]
    st["rel"] = {"c1": {"closeness": -50, "romance": 0}}
    char = dict(CHARS[0], relation_allowed=["stranger", "peer", "enemy"])
    c = {"story": dict(CONTENT["story"], characters=[char, CHARS[1]]), "secrets": []}
    if relationships.derive_mode(char, st["rel"]["c1"], runtime.tuning_for(c)) == "enemy":
        out = runtime.set_follow(c, st, "c1", True)
        assert not out["ok"], "敌对也肯跟你走就没立场了"


def test_social_app_is_open_from_the_start():
    """动态 app 从一开始就在, 不吃交情门槛。"""
    assert "social" in runtime.phone_apps(CONTENT)
