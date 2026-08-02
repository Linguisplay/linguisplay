# -*- coding: utf-8 -*-
"""🔒 作者可填的资产 URL 必须是本站相对路径 — 治存储型 XSS。

实弹 (2026-08-02 审查): 角色卡的 avatar_url / 剧本 cover_url 是作者自由字符串,
服务端零校验, 前端 `src="${...}"` 直插属性。已发布剧本的作者可写
    avatar_url = 'x" onerror="fetch(...)'
在【玩这本的其他玩家】浏览器里执行 JS (同源, 可代玩家删档/改剧本)。
前端转义是一道闸 (tests/client_units.test.js), 这里是第二道。

设计决策: 清洗成 None, 不抛异常。Character 是入库出库【共用】模型 —
抛异常会让库里已有的脏行整本读不出 (500); 清洗则恶意值进不了库、老脏行也读得出。
"""
import pytest

from app.schemas import Character, Story, StoryInput

# 必须被清洗掉的
BAD = [
    'x" onerror="alert(1)',                  # 属性逃逸
    "x' onerror='alert(1)",
    "javascript:alert(1)",                   # 伪协议
    "JaVaScRiPt:alert(1)",
    "data:text/html;base64,PHNjcmlwdD4=",    # data URI 挂 HTML
    "//evil.example.com/x.jpg",              # 协议相对 → 跳站外
    "http://evil.example.com/x.jpg",         # 站外绝对地址
    "<img src=x onerror=alert(1)>",
    "/scene/avatar/../../../etc/passwd",     # 路径穿越
]
# 必须原样放行的 (线上真实在用的形状)
GOOD = [
    "/scene/avatar/kf_adai.jpg",
    "/scene/avatar/gh_marek.jpg?v=1754000000",
    "/scene/sprite/c_1.webp",
    "/scene/bg/loc_1.jpg",
    "",
    None,
]


@pytest.mark.parametrize("bad", BAD)
def test_character_avatar_sanitized(bad):
    assert Character(name="X", avatar_url=bad).avatar_url is None, f"未挡住: {bad}"


@pytest.mark.parametrize("good", GOOD)
def test_character_avatar_allows_site_relative(good):
    assert Character(name="X", avatar_url=good).avatar_url == good


@pytest.mark.parametrize("bad", BAD)
def test_story_cover_sanitized(bad):
    assert StoryInput(title="X", cover_url=bad).cover_url is None, f"未挡住: {bad}"


def test_story_cover_allows_site_relative():
    assert StoryInput(title="X", cover_url="/scene/cover/s1.jpg").cover_url == "/scene/cover/s1.jpg"


def test_dangerous_avatar_cannot_ride_in_inside_a_story():
    """真实攻击路径: 整本提交时藏在角色数组里的恶意 URL 同样被清洗。"""
    s = StoryInput(title="X", characters=[{"name": "坏人",
                                           "avatar_url": 'x" onerror="alert(1)'}])
    assert s.characters[0].avatar_url is None


def test_legacy_dirty_rows_do_not_break_reads():
    """库里若已有脏数据, 读取不许 500 — 清成 None, 同卡其余字段不受影响。"""
    s = Story(id="s1", title="X",
              characters=[{"name": "旧", "avatar_url": 'x" onerror="y'}])
    assert s.characters[0].avatar_url is None
    assert s.characters[0].name == "旧"
