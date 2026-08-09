# -*- coding: utf-8 -*-
"""🎙 一个角色只有一套声音 (Yi 报障 2026-08-08:「手机上性格跟线下不一样」)。

逐字段对照过: 主拍 payload 105 个字段, 手机回复 36 个。而且少的不是细节, 正是那几样
【管声音】的东西 —— style（剧本文风卡）、voice_print（语言指纹）、speaker_card
（性别/年龄/软肋/底线）、negatives（忌用清单）、era、world。

后果很直接: 主拍里有一条家规叫 _defer_style ——「长短与腔调一律听【文风】那一段」，
引擎主动把声音的裁量权交给了剧本。而手机那条路【从来没接过它】，于是同一个角色
线下归剧本的文风管、手机上归模型的默认中文腔管。玩家读到的就是「两个人」。

根因不是漏了字段, 是【手机那条路是另起炉灶写的系统提示词】。补字段只能治这一次,
下次加东西还得补三遍 (今天已经在同类问题上栽过两次: 手机看不见刚才那场戏、
主动消息看不见上下文)。所以抽公共块, 只留一处实现。

两块分开是有原因的, 不是随手拆的:
  · voice_head  身份/角色卡/说话方式/指纹/范例 —— 每个角色稳定不变, 排前面吃前缀缓存
  · style_band  文风卡/忌用清单 —— 剧本级常量, 主拍有自己的排位, 各路自己决定放哪
"""
from app.engine import qwen


P = {
    "speaker_name": "甲",
    "speaker_persona": "码头挑夫，话少",
    "speaker_card": {"gender": "男", "age_band": "三十上下",
                     "fear": "怕水", "line": "不出卖同乡"},
    "eq_style": "冷的人有冷的体贴",
    "voice_print": "句子短，爱用反问，从不说「我觉得」",
    "examples": ["行啦。", "你自己看着办。"],
    "style": "港片写实腔：写景合计不超过两句，绝不原地渲染气氛。",
    "negatives": "【忌用】不许写「空气仿佛凝固」这类套话。",
    "era": "1987 年的香港",
}


# ── 两块各自都完整 ────────────────────────────────────────────────────────────

def test_the_voice_head_carries_who_and_how():
    h = qwen.voice_head(P)
    for must in ("甲", "码头挑夫", "怕水", "不出卖同乡", "反问", "行啦"):
        assert must in h, f"身份带漏了：{must}"


def test_the_style_band_carries_the_story_voice():
    b = qwen.style_band(P)
    assert "港片写实腔" in b, "文风卡没进来"
    assert "空气仿佛凝固" in b, "忌用清单没进来"


def test_both_are_quiet_when_there_is_nothing_to_say():
    """没有的东西不许平白多一段 —— 每条消息都在花 token。"""
    assert qwen.voice_head({"speaker_name": "甲"}).strip()
    assert qwen.style_band({}) == ""


# ── 三个入口用的是同一套 ──────────────────────────────────────────────────────

def _phone_sys(payload):
    sent = {}

    def _fake(url, key, body, **kw):
        sent["sys"] = body["messages"][0]["content"]

        class _R:
            @staticmethod
            def json():
                return {"choices": [{"message": {"content": "嗯。"}}]}
        return _R()

    old = qwen._post_chat
    qwen._post_chat = _fake
    try:
        llm = qwen.QwenLLM.__new__(qwen.QwenLLM)
        llm._url, llm._key, llm._model = "http://never", "k", "m"
        yield_fn = llm._phone_reply if payload.get("phone_reply") else llm._compose_msg
        yield_fn(payload)
    finally:
        qwen._post_chat = old
    return sent.get("sys", "")


def test_the_phone_reply_speaks_in_the_same_voice():
    """⚠️ 这一条就是 Yi 报的那件事。"""
    sys = _phone_sys({**P, "phone_reply": True, "char": {"name": "甲"},
                      "player_name": "我", "text": "在吗"})
    assert "港片写实腔" in sys, "手机回复读不到剧本文风 —— 角色在手机上换了个腔调"
    assert "反问" in sys, "语言指纹没进手机"
    assert "不出卖同乡" in sys, "底线没进手机"
    assert "空气仿佛凝固" in sys, "忌用清单在手机上失效了"


def test_a_proactive_message_speaks_in_the_same_voice():
    sys = _phone_sys({**P, "compose_msg": True, "char": {"name": "甲"}, "hint": "打个招呼"})
    assert "港片写实腔" in sys and "反问" in sys


def test_the_main_turn_still_says_all_of_it():
    """抽公共块不许让主拍丢东西 —— 它本来全都有。"""
    sys = qwen._build_system({**P, "persona": {"name": "我"}, "context": {}})
    for must in ("码头挑夫", "怕水", "不出卖同乡", "反问", "港片写实腔", "空气仿佛凝固"):
        assert must in sys, f"主拍反而丢了：{must}"


def test_no_double_printing_in_the_main_turn():
    """抽出来之后不许两处都印一遍 —— 那是白烧 token 又自相重复。"""
    sys = qwen._build_system({**P, "persona": {"name": "我"}, "context": {}})
    # ⚠️ 别拿文风卡的【第一句】做判据: 深度 0 有一个 40 字的「文风不换台」重锚是【故意的】
    #    (完整块在 system 稳定带吃缓存, 但长历史里会漂, 所以每拍再钉一句)。
    #    要查重复得用只在完整块里出现的后半句。我第一版就栽在这上面。
    assert sys.count("绝不原地渲染气氛") == 1, "文风卡完整块印了两遍"
    assert sys.count("不出卖同乡") == 1, "底线印了两遍"
