# -*- coding: utf-8 -*-
"""🎙 作者开场白 (Yi 2026-07-21: 角色编辑加开场白): 作者写定的第一句话原样上台 —
模型即兴让位只留动作; 模型整段没交时确定性兜底同样用它。"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./test_e2e.db")
os.environ.setdefault("JWT_SECRET", "test")

from app.engine import runtime  # noqa: E402

STORY = {"story": {"id": "s", "characters": [
    {"id": "a", "name": "甲", "is_lead": True, "home_location_id": "hall",
     "opening_line": "把袖子卷起来，让我看看你的手。"}],
    "acts": [{"index": 1, "title": "一"}],
    "locations": [{"id": "hall", "name": "门厅", "detail": "一盏吊灯", "exits": []}]},
    "secrets": []}


class IntroLLM:
    def generate(self, prompt):
        if prompt.get("intro_vignettes"):
            return {"scene": "清晨的门厅。", "cast": [
                {"name": "甲", "action": "甲从柜台后抬起头。", "line": "模型自己编的一句"}]}
        return {}


class NullLLM:
    def generate(self, prompt):
        return {}


def _first_line(beats):
    return next((b for b in beats
                 if b.get("type") == "dialogue" and b.get("speaker_name") == "甲"), None)


def test_authored_opening_line_beats_model_improv():
    beats = runtime.build_opening(STORY, runtime.default_state(), llm=IntroLLM())
    b = _first_line(beats)
    assert b and b["text"] == "把袖子卷起来，让我看看你的手。"


def test_authored_opening_line_in_deterministic_fallback():
    beats = runtime.build_opening(STORY, runtime.default_state(), llm=NullLLM())
    b = _first_line(beats)
    assert b and b["text"] == "把袖子卷起来，让我看看你的手。"


def test_world_book_reaches_turn_system():
    """🌍 世界书进回合 (Yi 2026-07-21: 角色不尊重世界观): world_long 必须出现在
    发言 system 里 (从前只喂开场旁白)。"""
    from app.engine import qwen
    base = {"speaker": {"name": "甲"}, "persona": {"name": "我"}, "channel": "say"}
    txt = qwen._build_system({**base, "world": "蒸汽龙骨城，飞艇靠鲸油航行"})
    assert "蒸汽龙骨城" in txt and "世界观·这个世界的底色" in txt
    assert "蒸汽龙骨城" not in qwen._build_system(base)


def test_authored_opening_and_act_script():
    """🎬 作者亲笔开场白原样上台压过模型即兴; 幕情节底稿进导演 system (路标不轨道)。"""
    from app.engine import qwen
    story2 = {"story": {**STORY["story"],
                        "opening": "暴雨拍在铁皮棚上——你攥着那封没有署名的信。",
                        "acts": [{"index": 1, "title": "一",
                                  "script": "细辉借钱被拒；深夜仓库起火"}]},
              "secrets": []}
    beats = runtime.build_opening(story2, runtime.default_state(), llm=IntroLLM())
    assert beats[0]["text"] == "暴雨拍在铁皮棚上，你攥着那封没有署名的信。"   # 原样(过标点守卫)
    txt = qwen._build_system({"speaker": {"name": "甲"}, "persona": {"name": "我"},
                              "channel": "say",
                              "scene": {"index": 1, "title": "一",
                                        "script": "细辉借钱被拒；深夜仓库起火"}})
    assert "情节底稿" in txt and "仓库起火" in txt and "路标不是轨道" in txt


class CaptureLLM:
    """记录 build_opening 喂给开场生成的 payload"""
    def __init__(self):
        self.seen = None

    def generate(self, prompt):
        if prompt.get("intro_vignettes"):
            self.seen = prompt
        return {}


def test_authored_opening_feeds_cast_generation_and_stages_verbatim():
    # 🎬 (Yi 实弹: 角色也得跟着开场白演) 开场白必须: ①喂进开场生成 payload
    # ②一字不落按段落上台
    story = {k: (dict(v) if isinstance(v, dict) else v) for k, v in STORY.items()}
    story["story"] = dict(STORY["story"])
    story["story"]["opening"] = "暴雨拍在铁皮棚上。\n你攥着那封没有署名的信，站在牌坊底下。"
    llm = CaptureLLM()
    beats = runtime.build_opening(story, runtime.default_state(), llm=llm)
    assert llm.seen is not None and \
        llm.seen.get("auth_opening", "").startswith("暴雨拍在铁皮棚上"), \
        "开场白没喂给开场生成 — 角色会像没读过剧本"
    texts = [b.get("text") for b in beats if b.get("type") == "description"]
    assert "暴雨拍在铁皮棚上。" in texts and \
        "你攥着那封没有署名的信，站在牌坊底下。" in texts, "开场白没有一字不落分段上台"
