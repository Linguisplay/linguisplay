# -*- coding: utf-8 -*-
"""🚪 到达旁白: 别传送、别重开机 (Yi 报障 2026-08-06 第二例)。

玩家实况:
    （你带着同行的人来到了 九龙城区。）
    推开糖水店的木门，吊扇搅动着甜腻的杏仁茶气味……蓝信一背靠柜台……

两个病, 根因各不相同。

【一 · 传送】九龙城区是个【大区】, 到达旁白却把玩家放进了一家糖水店。
   这不是 test_arrival_blank_place 治的那一例 —— 那例是 detail 为空;
   九龙城区【有】detail(80 字, 写的是"横跨九龙城寨、土瓜湾、红磡……")。
   根因: 那句「绝不许把它替换成或改写成另一个具名场所」只写在【detail 为空】那一支,
   detail 存在时模型拿到的是「必须扣住给出的地点细节，不要泛泛」。而大区的 detail
   天生就是大尺度的, 「不要泛泛」于是【主动把模型往具名小场所推】。
   修法: 防传送与尺度这两条改成【无条件】, 与有没有 detail 无关。

【二 · 重开机】到达旁白收到的字段只有 place/detail/slot/people/observer/player_name
   —— 没有历史、没有目标、没有刚才发生了什么。它结构上就不可能接着演,
   只能把在场每个人从零再描述一遍, 读起来就是剧情被打断、场景被重置。
   修法: 照 phone_send 的成例把 beat_log 喂进来 (那条路早就通气了), 并要求接着演。

顺带补上今天第三次撞见的同一个病: 这条路也没有文风卡。
"""
import pytest

from app.engine import qwen, runtime


# 九龙城区在生产库里的真实 detail (大区尺度)
DISTRICT = ("80 年代九龙城区横跨九龙城寨、土瓜湾、红磡、何文田、马头围，"
            "临启德机场跑道，是东九龙工业、民生、码头货运集中地")
VENUE = "巷子最深处的旧式理发店，几张红色皮转椅，镜子斑驳。"

STYLE = "作者腔：香港市井味。忌文艺腔堆砌。经济律：写景全回合合计不超过两句。"


def _prompt_for(detail, place="九龙城区", observer=False, **extra):
    """把 _arrive 真实发出去的两段抓回来 (只换掉 HTTP 那一层)。"""
    box = {}

    def fake(url, key, body, **k):
        box["sys"] = body["messages"][0]["content"]
        box["user"] = body["messages"][1]["content"]

        class R:
            def json(self):
                return {"choices": [{"message": {"content": "{}"}}]}
        return R()

    old = qwen._post_chat
    qwen._post_chat = fake
    try:
        q = qwen.QwenLLM.__new__(qwen.QwenLLM)
        q._url = q._key = q._model = "x"
        p = {"arrive": True, "place": place, "detail": detail,
             "slot": "第2天·夜", "observer": observer,
             "people": [{"name": "蓝信一", "role": "龙城帮马仔",
                         "look": "懒洋洋", "relation": "暧昧"}],
             "player_name": "蔡妍"}
        p.update(extra)
        q._arrive(p)
    finally:
        qwen._post_chat = old
    return box


def _both(box):
    return box["sys"] + box["user"]


# ── 一 · 别传送 ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("detail,tag", [(DISTRICT, "大区·有描述"), ("", "空描述"),
                                        (VENUE, "小场所·有描述")])
def test_never_substitute_another_named_venue(detail, tag):
    """防传送必须是【无条件】的。原本只写在空描述那一支, 而报障的这一例有描述。"""
    t = _both(_prompt_for(detail))
    assert any(k in t for k in ("不许把", "不要把", "换成别的", "另一个具名")), \
        f"[{tag}] 没有任何一句拦着它把地点换成一家店:\n{t[:400]}"


@pytest.mark.parametrize("detail", [DISTRICT, "", VENUE])
def test_scale_rule_is_unconditional(detail):
    """尺度规则同理: 是街区就写街面, 是屋子就写屋里。"""
    assert "尺度" in _both(_prompt_for(detail))


def test_venue_detail_keeps_the_strict_rule():
    """回归闸: 小场所那条严格规则本来就是对的, 别为了治大区把它误伤
    (test_arrival_blank_place 也在守这一条)。"""
    assert "扣住给出的地点细节" in _prompt_for(VENUE)["sys"]


def test_district_detail_reaches_the_model():
    assert "启德" in _prompt_for(DISTRICT)["user"]


def test_observer_branch_gets_the_same_guards():
    """上帝视角是另写的一段 —— 两支都要治, 不然换个模式又传送。"""
    t = _both(_prompt_for(DISTRICT, observer=True))
    assert "尺度" in t
    assert any(k in t for k in ("不许把", "不要把", "换成别的", "另一个具名"))


# ── 二 · 别重开机 ──────────────────────────────────────────────────────────────

RECENT = [
    {"author": "engine", "type": "dialogue", "speaker_name": "蓝信一",
     "text": "果栏那批货今晚就得走，你敢不敢跟我去。"},
    {"author": "player", "type": "dialogue", "speaker_name": None, "text": "我跟你去。"},
]


def test_arrival_sees_what_just_happened():
    """结构上就得让它看得见刚才那一场, 否则它只能把人从零再描述一遍。"""
    t = _both(_prompt_for(DISTRICT, recent=RECENT))
    assert "果栏" in t, f"刚才那句话没喂进到达旁白:\n{t[:400]}"


def test_arrival_is_told_to_continue_not_to_restart():
    t = _both(_prompt_for(DISTRICT, recent=RECENT))
    assert any(k in t for k in ("接着", "刚才", "延续", "别重新介绍")), \
        "没有任何一句要求它接着演"


def test_arrival_without_recent_still_builds():
    """开局那一次没有历史 —— 不许因此炸掉。"""
    assert _prompt_for(DISTRICT)["sys"]


def test_arrival_carries_the_style_card():
    """今天第三次撞见同一个病: 这条路一样收不到文风卡。"""
    t = _both(_prompt_for(DISTRICT, style=STYLE))
    assert "香港市井味" in t and "文风" in t


def test_arrival_length_defers_to_the_author():
    """引擎硬写的「2~4句」要跟主拍一样让位给作者的经济律。"""
    t = _prompt_for(DISTRICT, style=STYLE)["sys"]
    assert "不超过两句" in t
    assert "2~4句" not in t and "2~4 句" not in t


def test_arrival_keeps_its_default_without_a_style_card():
    assert "句" in _prompt_for(DISTRICT)["sys"]


# ── 三 · runtime 那一头真的把料喂进来了 ─────────────────────────────────────────

CONTENT = {"story": {
    "id": "s", "title": "九龙城寨·狗笼", "style": STYLE,
    "characters": [{"id": "a", "name": "蓝信一", "is_lead": True, "persona_text": "龙城帮马仔"}],
    "acts": [{"index": 1, "title": "一"}],
    "locations": [{"id": "kc", "name": "九龙城区", "detail": DISTRICT, "exits": []}]}, "secrets": []}


class _Spy:
    def __init__(self):
        self.p = None

    def generate(self, prompt):
        self.p = prompt
        return {"beats": [{"type": "description", "text": "街面上人来人往。"}]}


def test_runtime_hands_the_arrival_its_context():
    st = runtime.default_state()
    st["location_id"] = "kc"
    spy = _Spy()
    runtime.arrival_narration(CONTENT, st, {"name": "蔡妍"}, llm=spy,
                              beat_log=[dict(b) for b in RECENT])
    assert spy.p is not None
    assert spy.p.get("style"), "runtime 没把文风卡交给到达旁白"
    assert spy.p.get("recent"), "runtime 没把刚才发生的事交给到达旁白"


def test_runtime_arrival_survives_without_a_beat_log():
    st = runtime.default_state()
    st["location_id"] = "kc"
    assert runtime.arrival_narration(CONTENT, st, {"name": "蔡妍"}, llm=_Spy())


# ── ⚠️ 2026-08-07 玩家报障: 到达旁白把上一场的人一起搬过来了 ──────────────────
#
# 实况: 玩家独自走到西九龙警署总部, scene_characters 只有玩家自己 (following 空、
# char_pins 空), 而到达旁白写着「蓝信一靠在走廊入口那块指示牌下面，手指转着打火机」
# —— 人不在场、不同行、地图上也没有, 却在正文里活灵活现。文与实分家。
#
# 根因是我昨天那一刀: 为治「换地方剧情被清零」, 我把最近几拍喂进了到达旁白, 还加了
# 「接着刚才那一场演，别把在场的人当第一次见面重新介绍一遍」。但我【没告诉它谁不在】。
# 上一场的人出现在 recent 里, 模型就顺理成章地把他们一起搬进新场景。
# 接上下文是对的, 缺的是那半句: 只有名单上这些人在这儿。

def test_the_arrival_never_carries_absent_people_over():
    t = _both(_prompt_for(DISTRICT, recent=RECENT))
    assert any(k in t for k in ("不在这里", "不在场", "只有", "名单上")), \
        f"喂了上一场却没说谁不在 —— 模型会把人一起搬过来:\n{t[:500]}"


def test_an_empty_room_says_so():
    """一个人都没有时, 得明说这儿没别人 —— 否则模型最省事的写法就是补几个人进来。"""
    box = _prompt_for(DISTRICT, recent=RECENT, people=[])
    t = _both(box)
    assert "没有别人" in t or "没有其他人" in t or "空" in t


def test_the_present_list_is_still_the_authority():
    """在场名单照旧要喂 —— 这一刀不许把它也一起掐了。"""
    assert "蓝信一" in _both(_prompt_for(DISTRICT, recent=RECENT))
