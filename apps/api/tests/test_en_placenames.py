# -*- coding: utf-8 -*-
"""🌐 EN 地名口径包 (2026-08-03 地图深查第二刀): 全部地名启发式此前是 CJK 尺子,
Golden Hour 的涌现链被量残 — near_location 字符级 LCS 在英文里全是噪音 (实测 0/12),
准入门 len>12 一刀切驳回多词英文名, 提炼名硬截 [:12] 铸出 "The Rusty An"。
口径按语言分尺: zh 原样不动 (回归钉在案), en 走词级。"""
import copy

from app.engine import qwen, runtime

GH = {
    "story": {"id": "gh", "language": "en", "sandbox": {"enabled": True},
              "characters": [{"id": "a", "name": "Elias", "is_lead": True,
                              "home_location_id": "camp"}],
              "acts": [{"index": 1, "title": "One"}],
              "locations": [
                  {"id": "harb", "name": "The Harbour Set", "detail": "x", "exits": []},
                  {"id": "tav", "name": "Yannis's Taverna", "detail": "x", "exits": []},
                  {"id": "blue", "name": "The Blue House", "detail": "x", "exits": []},
                  {"id": "camp", "name": "Base Camp", "detail": "x", "exits": ["The Blue House"]},
              ]},
    "secrets": [],
}

ZH = {
    "story": {"id": "zh", "language": "zh",
              "characters": [], "acts": [{"index": 1}],
              "locations": [{"id": "b", "name": "阿柒冰室", "detail": "x", "exits": []}]},
    "secrets": [],
}


# ── near_location: EN 词级, 别再张冠李戴 (P0: 实测 0/12 正确) ───────────────────

def test_near_location_en_stops_false_matches():
    for ref in ("Elias's trailer", "the old lighthouse", "a quiet rooftop bar", "the roof"):
        assert runtime.near_location(GH, ref) is None, ref   # 半路亲戚一个都不许认

def test_near_location_en_still_finds_real_kin():
    assert runtime.near_location(GH, "the harbour")["id"] == "harb"
    assert runtime.near_location(GH, "blue house")["id"] == "blue"
    assert runtime.near_location(GH, "harbour set")["id"] == "harb"

def test_near_location_zh_lcs_unchanged():
    assert runtime.near_location(ZH, "冰室")["id"] == "b"     # zh 连续两字重合照旧
    assert runtime.near_location(ZH, "河堤") is None


# ── 地名准入门: 按语言分尺 ─────────────────────────────────────────────────────

def test_bad_place_name_en_accepts_multiword():
    for good in ("the old lighthouse", "rooftop bar", "Base Camp", "boathouse"):
        assert not runtime._bad_place_name(good), good
    for bad in ("where should we go now honestly speaking",   # >5 词
                "you should leave", "him", "somewhere", "what happens next?"):
        assert runtime._bad_place_name(bad), bad

def test_bad_place_name_zh_unchanged():
    assert not runtime._bad_place_name("河堤")
    assert runtime._bad_place_name("头看看他跟不跟")
    assert runtime._bad_place_name("这个名字有十三个字这么长呢")   # zh >12 仍拒

def test_placey_en_word_gauge():
    for good in ("boathouse", "rooftop bar", "library", "the old lighthouse"):
        assert runtime._placey(good), good
    assert not runtime._placey("tell him everything about it all")
    # zh 回归
    assert runtime._placey("河堤") and not runtime._placey("求老爹把秘方卖")


# ── 玩家自报去处: EN 多词名也要能出确认条 ──────────────────────────────────────

def test_player_move_emergent_en_multiword():
    content = copy.deepcopy(GH)
    st = runtime.default_state()
    st["location_id"] = "camp"
    got = runtime.player_move_emergent(content, st, "I go to the old lighthouse", channel="do")
    assert got == "old lighthouse"


# ── moved_to 生成路 EN 全链: 申报多词英文名 → 真铸真移, 名字不截断 ─────────────

class EnMintLLM:
    def __init__(self, **fields):
        self.fields = fields

    def generate(self, prompt):
        if prompt.get("describe_place"):
            return {"name": "Old Lighthouse", "detail": "Salt wind and rusted rails."}
        if prompt.get("risk_judge"):
            return {"risk": 100}
        if prompt.get("start_place"):
            return {}
        out = {"beats": [{"type": "dialogue", "speaker_name": "Elias", "text": "Let's go."}],
               "affinity_delta": 0, "advance_act": False, "ending": None}
        if prompt.get("group_mode") in ("primary", None):
            out.update(self.fields)
        return out


def test_moved_to_en_multiword_mints_and_moves():
    content = copy.deepcopy(GH)
    st = runtime.default_state()
    st["location_id"] = "camp"
    out = runtime.run_turn(content, st, {"name": "Me"}, "lead the way", channel="say",
                           llm=EnMintLLM(moved_to="the old lighthouse", next_speakers=[]))
    st2 = out["state"]
    assert str(st2["location_id"]).startswith("loc_gen_")
    minted = next(l for l in content["story"]["locations"] if l["id"] == st2["location_id"])
    assert minted["name"] == "Old Lighthouse"                 # 不许铸成 "Old Lighthou"


# ── 提炼名截断按语言分 ────────────────────────────────────────────────────────

def test_place_clip_language_aware():
    assert qwen.place_clip("The Rusty Anchor Tavern", True) == "The Rusty Anchor Tavern"
    assert qwen.place_clip("河堤边上那间没有名字的旧茶馆延伸出去", False) == "河堤边上那间没有名字的旧"
    assert len(qwen.place_clip("x" * 80, True)) == 40


# ── 开场地: EN 无图剧本不许冒中文 ─────────────────────────────────────────────

class SpyLLM:
    def __init__(self):
        self.prompts = []

    def generate(self, prompt):
        self.prompts.append(prompt)
        return {}                                             # 逼出兜底名


def test_ensure_start_location_speaks_the_story_language():
    en = {"story": {"id": "e", "language": "en", "world_facts": "seaside",
                    "characters": [], "acts": [{"index": 1, "title": "One"}]}, "secrets": []}
    spy = SpyLLM()
    st = runtime.default_state()
    loc = runtime.ensure_start_location(en, st, llm=spy)
    assert loc["name"] == "here"                              # 兜底也不许是「此处」
    assert any(p.get("language") == "en" for p in spy.prompts)   # 生成走了语言戳
    zh = {"story": {"id": "z", "language": "zh", "world_facts": "码头",
                    "characters": [], "acts": [{"index": 1, "title": "一"}]}, "secrets": []}
    loc2 = runtime.ensure_start_location(zh, runtime.default_state(), llm=SpyLLM())
    assert loc2["name"] == "此处"


# ── 改名口径: EN 地名带空格合法; 作者图不许被 loc_ 前缀击穿 ────────────────────

def test_place_name_ok_language_aware():
    assert runtime.place_name_ok("Old Docks")                 # 空格合法 (npc_name_ok 会拒)
    assert runtime.place_name_ok("码头仓库")
    assert not runtime.place_name_ok("Old Docks?")
    assert not runtime.place_name_ok("where should we go now honestly speaking")
    assert not runtime.place_name_ok("这个名字有十三个字这么长呢")


# ── 夜巡判官: 自己打的中文不许判引擎的罪 ──────────────────────────────────────

def test_night_judge_skips_player_authored_cjk():
    import qa_playtour as qa
    story = {"language": "en"}
    beats = [
        {"seq": 8, "author": "player", "type": "do", "text": qa.TURN_INPUTS[0][1]},
        {"seq": 9, "author": "engine", "type": "dialogue", "speaker_name": "Elias",
         "text": "The night settles in."},
    ]
    errs, _ = qa._judge(story, beats, [], {"here": []}, ["look around"], None, None, None)
    assert not any("漏中文" in e for e in errs)               # 玩家自己的输入不算漏
    beats.append({"seq": 10, "author": "engine", "type": "dialogue",
                  "speaker_name": "Elias", "text": "夜色沉落。"})
    errs2, _ = qa._judge(story, beats, [], {"here": []}, ["look around"], None, None, None)
    assert any("漏中文" in e for e in errs2)                  # 引擎漏的照抓
