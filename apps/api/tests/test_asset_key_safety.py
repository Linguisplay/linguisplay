# -*- coding: utf-8 -*-
"""🔒 P0 路径穿越回归: 生成图落盘的 key/target_id 必须消毒 (审计实弹:
认证用户可用 ../ 删/覆盖他人的图, 进程还跑在 root)。"""
import pytest

from app.engine.gal import safe_asset_key


def test_legit_keys_pass():
    for k in ["c2_喜", "kf_adai", "sk_chinatsu", "s1", "bg_x", "cover2", "龙卷风_怒"]:
        assert safe_asset_key(k) == k


def test_traversal_and_separators_blocked():
    bad = ["../victim/cover", "..", "a/b", "", "  ", "/etc/passwd",
           "c1/../c2", ".", "a\\b", "a.b", "x/../../y", "\t"]
    for k in bad:
        with pytest.raises(ValueError):
            safe_asset_key(k)
