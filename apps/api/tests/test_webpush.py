# -*- coding: utf-8 -*-
"""🔔 Web Push (活世界 P3): 静默时段、发送结果分级、未配置即全层降级."""
from datetime import datetime

from app import webpush


def test_quiet_hours_wrap_around():
    # defaults: 23:00 – 08:00 Asia/Shanghai
    assert webpush.quiet_now(datetime(2026, 1, 1, 23, 30)) is True
    assert webpush.quiet_now(datetime(2026, 1, 1, 3, 0)) is True
    assert webpush.quiet_now(datetime(2026, 1, 1, 7, 59)) is True
    assert webpush.quiet_now(datetime(2026, 1, 1, 8, 0)) is False
    assert webpush.quiet_now(datetime(2026, 1, 1, 12, 0)) is False
    assert webpush.quiet_now(datetime(2026, 1, 1, 22, 59)) is False


def test_disabled_without_keys():
    """dev/test 环境没配 VAPID → 层整体静默, 谁也不会被 push 打扰."""
    assert webpush.enabled() is False
    assert webpush.send_one({"endpoint": "https://x", "keys": {}}, {"title": "t"}) == "fail"
    assert webpush.push_to_user(None, "u1", "t", "b") == 0


def test_send_one_grades_results(monkeypatch):
    monkeypatch.setattr(webpush, "enabled", lambda: True)

    class _Resp:
        status_code = 410

    def gone(**kw):
        e = Exception("gone")
        e.response = _Resp()
        raise e

    sub = {"endpoint": "https://push.example/x", "keys": {"p256dh": "k", "auth": "a"}}
    monkeypatch.setattr(webpush, "_webpush", lambda **kw: None)
    assert webpush.send_one(sub, {"title": "t"}) == "ok"
    monkeypatch.setattr(webpush, "_webpush", gone)
    assert webpush.send_one(sub, {"title": "t"}) == "gone"

    def flaky(**kw):
        raise RuntimeError("network")

    monkeypatch.setattr(webpush, "_webpush", flaky)
    assert webpush.send_one(sub, {"title": "t"}) == "fail"
