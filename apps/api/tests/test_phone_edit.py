# -*- coding: utf-8 -*-
"""✏️ 手机上也能改自己说过的话 (Yi 2026-08-11)。

线下 2026-07-23 就能改了 (PATCH /beat/{id})，手机那一半一直没有。

A/B 是「按下标改」还是「给消息发 id」。选 id：线程有 200 条上限、从头丢，
一丢下标就全错位，改到别人的话上去。
但【不写迁移】——存量消息没有 id，就在读/写这条线程时顺手补上：零迁移、零停机，
老档下次被打开时自己长好。
"""
import pytest

from app.engine import runtime as R


def _st(msgs):
    st = R.default_state()
    st.setdefault("phone", {}).setdefault("threads", {})["a"] = {"msgs": msgs, "unread": 0}
    return st


def test_old_messages_grow_an_id_when_touched():
    """存量消息没有 id —— 碰一下就补上，不用迁移。"""
    st = _st([{"from": "me", "text": "在吗", "at": "第1天·夜"}])
    R._stamp_msg_ids(st["phone"]["threads"]["a"])
    assert st["phone"]["threads"]["a"]["msgs"][0].get("id")


def test_ids_are_stable_across_calls():
    """补两次得是同一个 id —— 不然编辑指到的东西每次都变。"""
    st = _st([{"from": "me", "text": "在吗", "at": "第1天·夜"}])
    th = st["phone"]["threads"]["a"]
    R._stamp_msg_ids(th); first = th["msgs"][0]["id"]
    R._stamp_msg_ids(th)
    assert th["msgs"][0]["id"] == first


def test_editing_my_own_line_works():
    st = _st([{"from": "me", "text": "在吗", "at": "x"}])
    th = st["phone"]["threads"]["a"]; R._stamp_msg_ids(th)
    assert R.edit_phone_msg(st, "a", th["msgs"][0]["id"], "在不在")
    assert th["msgs"][0]["text"] == "在不在"
    assert th["msgs"][0]["edited"] is True


def test_i_cannot_edit_what_they_said():
    """只能改自己说过的话 —— 改对方的等于改历史。"""
    st = _st([{"from": "them", "text": "我在", "at": "x"}])
    th = st["phone"]["threads"]["a"]; R._stamp_msg_ids(th)
    with pytest.raises(ValueError):
        R.edit_phone_msg(st, "a", th["msgs"][0]["id"], "我不在")


def test_an_unknown_id_is_not_a_silent_noop():
    st = _st([{"from": "me", "text": "在吗", "at": "x"}])
    assert R.edit_phone_msg(st, "a", "nope", "改了") is False


def test_the_thread_view_hands_out_ids():
    """端到端: 客户端拿到的每条都得有 id, 否则铅笔画不出来。"""
    c = {"story": {"id": "s", "characters": [{"id": "a", "name": "甲"}],
                   "acts": [{"index": 1, "title": "一"}], "locations": []}}
    st = _st([{"from": "me", "text": "在吗", "at": "x"}])
    view = R.phone_thread(c, st, "a")
    assert all(m.get("id") for m in view["msgs"])
