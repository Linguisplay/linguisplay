# -*- coding: utf-8 -*-
"""💞 大事记切片进生成 (同事建议, Yi 拍板混合式): 模式剧本当粗锚, 具体事件当细节。
断言 _build_system 消费 rel_recent, 且外壳遵守语言合同 (zh 中文壳 / en 英文壳)。"""
from app.engine.qwen import _build_system


def _sys(**kw):
    base = {"speaker_name": "某人", "channel": "say"}
    base.update(kw)
    return _build_system(base)


def test_rel_recent_feeds_zh_shell():
    s = _sys(rel_recent=["初次见面，在天台。", "你如约而至：喝汽水。"])
    assert "你们之间最近的事" in s
    assert "你如约而至：喝汽水。" in s
    assert "压过关系标签" in s


def test_rel_recent_feeds_en_shell():
    s = _sys(language="en", rel_recent=["First met at Base Camp.", "You kept the promise: coffee."])
    assert "What has passed between you two lately" in s
    assert "You kept the promise: coffee." in s
    assert "你们之间最近的事" not in s   # en 本子外壳零中文 (语言合同)


def test_rel_recent_absent_adds_nothing():
    s = _sys()
    assert "你们之间最近的事" not in s
    assert "What has passed between you two lately" not in s
