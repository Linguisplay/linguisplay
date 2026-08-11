# -*- coding: utf-8 -*-
"""📷 发图可以不打字 (Yi 报障 2026-08-11:「图片发送失败」)。

我给客户端加了「发图时文字可以为空」的分支，却没开服务端那道闸：
_phone_target 里有一条 `if not text: raise ValueError("说点什么吧")`，
于是不打字直接发图一律 400。

半件事比没做更糟——客户端让你点得下去，服务端一律拒收。
"""
import pytest

from app.engine import runtime as R


C = {"story": {"id": "s", "phone": {"enabled": True},
               "characters": [{"id": "a", "name": "甲"}],
               "acts": [{"index": 1, "title": "一"}],
               "locations": [{"id": "l1", "name": "旧巷", "detail": "x", "exits": []}]}}


def _st():
    st = R.default_state()
    st["location_id"] = "l1"
    st["met_ids"] = ["a"]
    R.grant_contact_on_meet(C, st)
    return st


def test_a_photo_alone_is_a_message():
    """一张图本身就是一句话。"""
    assert R._phone_target(C, _st(), "a", "", allow_empty=True)


def test_an_empty_text_without_a_photo_is_still_refused():
    """别把闸拆了 —— 空消息还是不许发。"""
    with pytest.raises(ValueError):
        R._phone_target(C, _st(), "a", "")


def test_the_other_checks_still_run_on_a_photo():
    """放行的只是「空」这一条, 不认识的人照旧发不出去。"""
    st = _st()
    st["met_ids"] = []
    st.setdefault("phone", {})["contacts"] = []
    with pytest.raises(ValueError):
        R._phone_target(C, st, "a", "", allow_empty=True)
