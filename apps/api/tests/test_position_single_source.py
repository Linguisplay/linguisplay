# -*- coding: utf-8 -*-
"""🔒 位置真源守卫 (Yi 2026-07-30: 玩家高频反馈「地图说他走了，对话里还在互动」)。

「谁此刻在哪」全引擎只有一个出口: runtime.char_position()。它是九级级联 —— 同行 →
濒死 → 威胁 → 被掳 → 约定 → 钉子 → 作息 → 模拟位 → 兜底。任何表现层 (地图/对白名册/
在场铁律/通讯录/电话/动态) 只要绕过它自己算, 两个面板就会当着玩家的面各说各话。

两次实弹, 都是同一个病「判据没归一」:
  ① 打电话直读作息表 (级联第 7 级) → 角色被钉在码头时, 地图和对白说「在那儿」, 电话却说
     「无人接听。TA此刻不知在何处。」
  ② 改成硬判 char_position == AWAY 又走过了头 → 散文离场钉的 __away__ 永不释放, 于是
     角色说一句「我先走了」电话就此永久打不通, 短信却还能把人召回来。
现在电话与通讯录共用 _phone_unreachable 一句判据; 位置一律问 char_position。

这份文件两层网, 缺一不可:
  · 源码守卫 —— 直读作息表/位置账本会被当场拦下 (AST, 认标识符不认调用形态);
  · 行为回归 —— 上面两次实弹各有一条真打 phone_call 的测试钉着, 改回去立刻红。
"""
import ast
from pathlib import Path

from app.engine import runtime
from app.engine.llm import MockLLM

APP = Path(__file__).resolve().parents[1] / "app"

# 作息表 _char_home 的合法直读者 (文件, 函数)。每个都有【不是在问"现在谁在哪"】的理由:
#   char_position       — 它就是级联的第 7 级本身
#   apply_char_move     — 问【所有权】: 作息管着这双脚吗 (管着就不许模型搬人)
#   make_promise        — 问【未来某时段】TA会在哪; char_position 只解得开"现在"
#   _schedule_says_away — 问【作者意图】: 班表把这个钟点写成"找不到人"了吗
# 白名单带文件名: 否则别的模块新写一个恰好同名的壳函数就白拿豁免。
_CHAR_HOME_OK = {("runtime.py", "char_position"), ("runtime.py", "apply_char_move"),
                 ("runtime.py", "make_promise"), ("runtime.py", "_schedule_says_away")}

# 位置账本 char_pins 的合法读写者 —— 全在 runtime.py, 且都是【落账】而非【问路】。
# (2026-07-30 实扫得出, 不是拍脑袋: 谁想读"人在哪"一律走 char_position)
_PINS_OK = {("runtime.py", "char_position"),          # 唯一的读者 (级联第 6 级)
            ("runtime.py", "_drop_pins_on_leave"), ("runtime.py", "_heal_away_pins"),
            ("runtime.py", "_settle_prose_exits"), ("runtime.py", "settle_prose_arrival"),
            ("runtime.py", "_settle_directed"), ("runtime.py", "_apply_phone_judgments"),
            ("runtime.py", "build_opening"), ("runtime.py", "run_turn_stream"),
            # 🎬 场账本 (docs/scene-ledger.md): 开场钉 cast/收场拔自己钉的钉 —— 落账,
            # 「正在陪你」由此成为显式状态 (钉子天然压作息、被危机链压过)
            ("runtime.py", "_sl_open"), ("runtime.py", "_sl_close")}

# schedule 字段本身的合法读者: 级联第 7 级 / 校验作者数据的剧本 linter / 起草空骨架
_SCHEDULE_OK = {("runtime.py", "_char_home"), ("logic.py", "lint_story"),
                ("stories.py", "draft_engine")}


def _py_files() -> list[Path]:
    """engine + routers 全部源码 (rglob: 将来拆成子包也不会让守卫悄悄失效)。"""
    out = []
    for d in ("engine", "routers"):
        out += [p for p in (APP / d).rglob("*.py") if "__pycache__" not in p.parts]
    return sorted(out)


def _outer_scopes(tree: ast.AST) -> list[ast.AST]:
    """只认最外层 def —— 嵌套闭包归属它的宿主函数, 别自成一档 (否则把级联某一级
    抽成内部 def 就会被误判成违规调用者)。"""
    inner = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for sub in ast.walk(node):
                if sub is not node and isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    inner.add(id(sub))
    return [n for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and id(n) not in inner]


def _mentions(py: Path, name: str) -> list[tuple[str | None, int]]:
    """[(所属最外层函数名 | None=模块级, 行号)] —— 凡这个标识符【出现】就算数。

    刻意不只看 Call.func: 别名 (h = _char_home)、getattr 字符串、模块级调用、
    存进表里回头再调 —— 任何一种都能绕开"只认调用形态"的扫描器。
    """
    tree = ast.parse(py.read_text(encoding="utf-8"))
    owner = {}
    for fn in _outer_scopes(tree):
        for sub in ast.walk(fn):
            owner[id(sub)] = fn.name
    hits = []
    for sub in ast.walk(tree):
        got = ((isinstance(sub, ast.Name) and sub.id == name)
               or (isinstance(sub, ast.Attribute) and sub.attr == name)
               or (isinstance(sub, ast.Constant) and sub.value == name)
               or (isinstance(sub, ast.alias) and (sub.asname or sub.name) == name))
        if got:
            hits.append((owner.get(id(sub)), getattr(sub, "lineno", 0)))
    return hits


def _guard(name: str, allowed: set, what: str) -> None:
    bad = []
    for py in _py_files():
        for fn, ln in _mentions(py, name):
            if (py.name, fn) not in allowed:
                where = f"函数 {fn}()" if fn else "模块级"
                bad.append(f"{py.name}:{ln} {where} 碰了 {name} —— {what}")
    assert not bad, "\n".join(bad)


def test_char_home_is_never_read_outside_its_exemptions():
    """作息表只是级联的一级, 不许有人拿它当答案。"""
    _guard("_char_home", _CHAR_HOME_OK, "要问「现在谁在哪」请用 char_position()")
    # 老名字连影子都不许留 (改名后若有人复活它, 这条会红)
    _guard("char_home", _CHAR_HOME_OK | {("runtime.py", "_char_home")},
           "作息表函数已私有化为 _char_home")


def test_position_ledger_is_only_touched_by_its_bookkeepers():
    """char_pins 是落账用的账本, 不是查询接口 —— 想知道人在哪只能问 char_position。"""
    _guard("char_pins", _PINS_OK, "问路走 char_position(), 别自己翻账本")


def test_schedule_field_has_only_three_readers():
    """作息字段本身也只有三个读者: 级联第 7 级、剧本 linter、起草空骨架。"""
    _guard("schedule", _SCHEDULE_OK, "作息只该经由 char_position 的级联被读到")


# ── 行为面: 四个表现层必须给同一个答案 ──────────────────────────────────────────
CONTENT = {"story": {
    "id": "ps",
    "characters": [
        # 作息把她钉成「此刻不知去向」, 但引擎另有钉子说她在码头 —— 钉子压过作息
        {"id": "c1", "name": "甲", "persona_text": "p",
         "schedule": [{"from_act": 1, "location_id": "lA", "slots": ["晨"]}]},
        {"id": "c2", "name": "乙", "persona_text": "p"},
    ],
    "acts": [{"index": 1}],
    "tuning": {"turns_per_slot": 6, "real_clock": 0},
    "locations": [
        {"id": "lA", "name": "堂口", "detail": "d", "exits": ["码头"]},
        {"id": "lB", "name": "码头", "detail": "d", "exits": ["堂口"]},
    ]}, "secrets": []}

PERSONA = {"name": "我", "pronouns": "they", "tagline": "t"}


class _SpyLLM(MockLLM):
    """房里现成的确定性替身, 加一本流水账 —— 用来断言"真的走到了模型那一步"。"""

    def __init__(self):
        self.prompts = []

    def generate(self, prompt):
        self.prompts.append(prompt)
        return super().generate(prompt)


def _state(**kw):
    st = {**runtime.default_state(), "location_id": "lA",
          "met_ids": ["c1", "c2"], "contact_ids": ["c1", "c2"],
          "clock": {"day": 1, "slot": 1, "turns_in_slot": 0}}   # 午 → 甲的晨班不覆盖
    st.update(kw)
    return st


def _contact(content, st, cid):
    return next(r for r in runtime.phone_threads_view(content, st)["contacts"]
                if r["char_id"] == cid)


def _dial(st, cid="c1"):
    llm = _SpyLLM()
    view = runtime.phone_call(CONTENT, st, PERSONA, cid, "喂", llm=llm)
    picked_up = not any("无人接听" in (m.get("text") or "") for m in view["msgs"])
    return picked_up, bool(llm.prompts)


def test_pin_beats_schedule_for_map_scene_and_phone_alike():
    """实弹①回归: 作息说 AWAY、钉子说在码头 —— 四个面板必须一致地说「在码头」。

    修复前电话独走作息表, 于是玩家看见地图上有人、打过去却「不知在何处」。"""
    st = _state(char_pins={"c1": "lB"})
    assert runtime.char_position(CONTENT, st, CONTENT["story"]["characters"][0]) == "lB"
    nodes = {n["id"]: n for n in runtime.map_view(CONTENT, st)["nodes"]}
    assert "甲" in nodes["lB"]["chars"]                          # 地图: 站在码头
    assert all(c["id"] != "c1" for c in runtime.scene_characters(CONTENT, st))  # 不在这一场
    row = _contact(CONTENT, st, "c1")
    assert row["away"] is False and row["here"] is False and row["where"] == "码头"
    picked_up, reached_model = _dial(st)                        # 电话: 真的打得通
    assert picked_up and reached_model


def test_prose_exit_pin_does_not_kill_the_phone_forever():
    """实弹②回归: 「我先走了」钉下的 __away__ 永不释放, 不许等于关机。

    它一旦等于无人接听, 这个人从此电话永久打不通 (自愈只认台上台词, 而离场的人不上台),
    偏偏短信没有这道闸还能把人召回来 —— 一局越玩越久, 能拨通的人单调递减。"""
    st = _state(char_pins={"c2": runtime.AWAY})                 # 乙无作息, 只被散文钉走
    assert runtime.char_position(CONTENT, st, CONTENT["story"]["characters"][1]) == runtime.AWAY
    assert _contact(CONTENT, st, "c2")["away"] is False         # 通讯录不许说"联系不上"
    picked_up, reached_model = _dial(st, "c2")
    assert picked_up and reached_model


def test_author_scheduled_away_still_means_nobody_picks_up():
    """反面: 作者班表写的「这个钟点找不到TA」照旧无人接听 —— 别把闸修没了。"""
    st = _state()                                               # 甲的班只覆盖晨, 现在是午
    assert runtime.char_position(CONTENT, st, CONTENT["story"]["characters"][0]) == runtime.AWAY
    for n in runtime.map_view(CONTENT, st)["nodes"]:
        assert "甲" not in n["chars"]
    row = _contact(CONTENT, st, "c1")
    assert row["away"] is True and row["where"] == ""
    picked_up, reached_model = _dial(st)
    assert not picked_up and not reached_model                  # 短路返回, 不惊动模型


def test_following_character_reads_present_on_every_surface():
    st = _state(following=["c1"])
    nodes = {n["id"]: n for n in runtime.map_view(CONTENT, st)["nodes"]}
    assert "甲" in nodes["lA"]["chars"]                          # 跟着玩家 → 玩家脚下
    assert any(c["id"] == "c1" for c in runtime.scene_characters(CONTENT, st))
    row = _contact(CONTENT, st, "c1")
    assert row["here"] is True and row["away"] is False


def test_player_own_place_never_vanishes_from_the_map():
    """解锁条件会掉 (affinity_min 跌破), 可人已经站在这儿了。

    不豁免就会出现「自己所在地连人带节点一起从地图上消失, 对话名册照旧列人」。"""
    content = {"story": {**CONTENT["story"], "locations": [
        {**CONTENT["story"]["locations"][0], "unlock": {"affinity_min": 90}},
        CONTENT["story"]["locations"][1]]}, "secrets": []}
    st = _state(affinity=0)
    assert runtime.location_available(content, st, content["story"]["locations"][0]) is False
    nodes = {n["id"]: n for n in runtime.map_view(content, st)["nodes"]}
    assert "lA" in nodes and nodes["lA"]["here"] is True
    assert "乙" in nodes["lA"]["chars"]                          # 同场的人也还在
    assert any(c["id"] == "c2" for c in runtime.scene_characters(content, st))


def _cast_like_the_callers(content, st):
    """三个调用方 (回合载荷两处 + routers/runs.py) 的原话, 逐字照抄。

    测试不许自己另立口径 —— 否则把 exclude_id 改成无条件也照样绿。"""
    return runtime.scene_cast(
        content, st,
        exclude_id=(st.get("player_character_id")
                    if (st.get("mode") or "character") == "character" else None))


def test_god_mode_shows_the_embodied_character_on_the_map_too():
    """上帝视角下附身角色就是个 NPC: 在场条列他, 地图也得列他 (两边同法)。"""
    st = _state(mode="god", player_character_id="c2")
    nodes = {n["id"]: n for n in runtime.map_view(CONTENT, st)["nodes"]}
    assert "乙" in nodes["lA"]["chars"]
    assert any(c["id"] == "c2" for c in _cast_like_the_callers(CONTENT, st))


def test_character_mode_still_hides_yourself_on_the_map():
    st = _state(mode="character", player_character_id="c2")
    nodes = {n["id"]: n for n in runtime.map_view(CONTENT, st)["nodes"]}
    assert "乙" not in nodes["lA"]["chars"]
    assert all(c["id"] != "c2" for c in _cast_like_the_callers(CONTENT, st))


def test_mapless_story_gets_no_position_hints_at_all():
    """老剧本没写 locations → 位置系统压根没启用, 通讯录一个位置字都不给。

    不设这道闸就会满屏噪音: char_position 返回 None, scene_characters 退回「人人都在场」
    的 legacy 行为, 于是每一行联系人都顶着「就在眼前」。"""
    content = {"story": {**CONTENT["story"], "locations": []}, "secrets": []}
    st = _state()
    assert runtime.char_position(content, st, CONTENT["story"]["characters"][0]) is None
    rows = runtime.phone_threads_view(content, st)["contacts"]
    assert rows and all(r["here"] is False and r["away"] is False and r["where"] == ""
                        for r in rows)


def _social_at(content, st):
    spy = _SpyLLM()
    runtime.social_feed(content, st, llm=spy)
    return {i["name"]: i.get("at") for p in spy.prompts if p.get("social_posts")
            for i in (p.get("items") or [])}


def test_social_feed_place_comes_from_the_same_source_as_the_map():
    """动态里的地名也来自 char_position, 所以玩家真走过去能撞见 TA —— 可印证才有体感。

    口径同地图: 地图上还看不见的地方就不写地名 (不靠帖子泄露地理)。"""
    hooks = {"npc_rel": {"c1|c2": {"stance": 1, "log": [{"why": "一起喝了顿酒"}]}}}
    assert _social_at(CONTENT, _state(char_pins={"c1": "lB"}, **hooks))["甲"] == "码头"
    locked = {"story": {**CONTENT["story"], "locations": [
        CONTENT["story"]["locations"][0],
        {**CONTENT["story"]["locations"][1], "unlock": {"affinity_min": 90}}]}, "secrets": []}
    assert _social_at(locked, _state(char_pins={"c1": "lB"}, affinity=0, **hooks))["甲"] == ""
