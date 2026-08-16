# 问卷造沙盒本（UGC）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 玩家在 /maker 问卷向导里答一套沙盒题，引擎铸出一个立刻可玩的私有沙盒本（满意再公开）。

**Architecture:** 复用 galmaker 问卷向导（wz* 机制）加「造什么」分支与沙盒题集；后端新增 `draft_sandbox` 起草管线（镜像 `draft_engine` 的 job/lint/降级闭环），新 prompt `sandbox_summary`/`sandbox_world` + 复用 `gen_progression`/`char_from_text`；沙盒九键走确定性组装 + 新形状闸 `sanitize_sandbox`（linter 对 sandbox 零校验，这道闸自己立）。

**Tech Stack:** FastAPI + SQLAlchemy(SQLite JSON 列) + 线程 job 台账 `_PARSE_JOBS` + vanilla JS 单文件前端 + pytest（MockLLM 确定性孪生）。

## Global Constraints

- Spec：`docs/superpowers/specs/2026-08-16-survey-sandbox-maker-design.md`（v1 只做中文本；立绘不自动生成；AI 不做动态追问，支线=前端配置表）
- TDD 铁律：每个任务先写测试、亲眼看它红、再写实现看它绿（红的理由必须是「功能缺失」）
- Windows 本机跑任何 `apps/api` 下的脚本都要 `PYTHONPATH=winshim`；pytest 不用（conftest 自带 fcntl 垫片）；解释器一律用 `apps/api/.venv/Scripts/python.exe`
- 仓库有并行会话：**绝不 `git stash`；`git add` 只点名自己改的文件**，不用 `git add -A`
- MockLLM 孪生与真 prompt 的字段面必须同构（共享常量 `SANDBOX_WORLD_KEYS` 锁死），这是历史实弹坑
- `style` 字段结构约定：作者腔在头、忌清单在尾（`qwen.py:63-93` 截断时保头保尾，布局错了忌清单会被切丢）
- `default_powers` 每条 ≤40 字（`runs.py:676-679` 开档还会再截一刀，超长=静默丢内容）
- 沙盒惯例：单幕、`endings=[]`、`visibility='private'` 落库（`status` 用模型默认 draft——owner 开自己私有本不受拦，`runs.py:593`）
- 中文注释、口吻与现有代码一致；错误文案是给玩家看的人话

---

### Task 1: 沙盒形状闸 `sanitize_sandbox`

**Files:**
- Modify: `apps/api/app/engine/logic.py`（加在 `lint_story` 定义之后、文件尾部工具区）
- Test: `apps/api/tests/test_sandbox_sanitize.py`（新建）

**Interfaces:**
- Consumes: 无（纯函数）
- Produces: `sanitize_sandbox(story: dict) -> list[str]` —— 原地修剪 `story["sandbox"]`，返回修剪记录字符串列表。Task 4 的管线在 `StoryInput(**payload)` 之前调它。

- [ ] **Step 1: 写失败测试**

```python
# -*- coding: utf-8 -*-
"""🏖 沙盒九键形状闸: linter 对 sandbox 内容零校验 (logic.py 只查它和其他系统的
冲突警告), 形状错 = 修为/串门/出生点静默失效。问卷起草管线必须自己把这道关。
原则: 确定性修剪, 不报错不打断 (烂零件摘掉, 世界照样能开)。"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./test_sanitize.db")
os.environ.setdefault("JWT_SECRET", "test")

from app.engine.logic import sanitize_sandbox  # noqa: E402


def _story(sandbox):
    return {"characters": [{"id": "ch_1", "name": "甲"}],
            "locations": [{"id": "loc_1", "name": "山门"}],
            "sandbox": sandbox}


def test_a_broken_progression_is_removed_not_kept():
    s = _story({"enabled": True, "progression": {"name": "", "ranks": ["a"]}})
    notes = sanitize_sandbox(s)
    assert "progression" not in s["sandbox"], "坏阶梯留着 = 修为系统静默失效"
    assert notes


def test_a_good_progression_survives_intact():
    ranks = ["淬体", "凝气", "问剑", "御剑", "剑心通明", "化神"]
    s = _story({"enabled": True, "progression": {"name": "剑心", "ranks": ranks}})
    sanitize_sandbox(s)
    assert s["sandbox"]["progression"] == {"name": "剑心", "ranks": ranks}


def test_dangling_visitor_and_start_location_are_pruned():
    s = _story({"enabled": True, "opening_visitor": "ch_99", "start_location": "loc_99"})
    sanitize_sandbox(s)
    assert "opening_visitor" not in s["sandbox"]
    assert "start_location" not in s["sandbox"]


def test_valid_visitor_and_start_location_survive():
    s = _story({"enabled": True, "opening_visitor": "ch_1", "start_location": "loc_1"})
    assert sanitize_sandbox(s) == []
    assert s["sandbox"]["opening_visitor"] == "ch_1"


def test_powers_are_clamped_to_four_and_forty_chars():
    s = _story({"enabled": True, "default_powers": ["长" * 60, "b", "c", "d", "e"]})
    sanitize_sandbox(s)
    ps = s["sandbox"]["default_powers"]
    assert len(ps) == 4 and all(len(p) <= 40 for p in ps), \
        "开档层还会截一刀 (runs.py:676) — 不在这里压好, 超出的字就静默蒸发"


def test_bogus_start_money_falls_back():
    s = _story({"enabled": True, "start_money": "很多"})
    sanitize_sandbox(s)
    assert s["sandbox"]["start_money"] == 100


def test_non_dict_sandbox_is_left_alone():
    s = {"characters": [], "locations": [], "sandbox": "corrupt"}
    assert sanitize_sandbox(s) == []
    assert s["sandbox"] == "corrupt"   # 老档实弹出现过字符串, 引擎自己会容错
```

- [ ] **Step 2: 跑测试看红**

```bash
cd /c/Users/17745/linguisplay/apps/api
./.venv/Scripts/python.exe -m pytest tests/test_sandbox_sanitize.py -q
```
Expected: FAIL —— `ImportError: cannot import name 'sanitize_sandbox'`

- [ ] **Step 3: 实现（logic.py 文件尾部追加）**

```python
def sanitize_sandbox(story: dict) -> list[str]:
    """🏖 沙盒九键形状闸 (问卷起草管线用)。lint_story 对 sandbox 内容零校验 —
    坏 progression/悬空 visitor 不是 error 是【静默失效】, 玩家问卷答完悄悄少一个
    系统。这道闸确定性修剪: 烂零件摘掉, 不报错不打断。原地改, 返回修剪记录。"""
    notes: list[str] = []
    sb = story.get("sandbox")
    if not isinstance(sb, dict):
        return notes   # 引擎对非 dict 自己容错 (runtime.py:1106) — 不越权改
    char_ids = {str(c.get("id")) for c in story.get("characters") or []}
    loc_ids = {str(l.get("id")) for l in story.get("locations") or []}
    prog = sb.get("progression")
    ok = (isinstance(prog, dict) and str(prog.get("name") or "").strip()
          and isinstance(prog.get("ranks"), list)
          and 4 <= len(prog["ranks"]) <= 12
          and all(isinstance(r, str) and 0 < len(r) <= 8 for r in prog["ranks"]))
    if prog is not None and not ok:
        sb.pop("progression", None)
        notes.append("progression 形状不合规已摘除 (开局 ensure_progression 兜底)")
    elif ok:
        sb["progression"] = {"name": str(prog["name"]).strip()[:8],
                             "ranks": [str(r) for r in prog["ranks"]]}
    if sb.get("opening_visitor") and str(sb["opening_visitor"]) not in char_ids:
        sb.pop("opening_visitor", None)
        notes.append("opening_visitor 指向不存在的角色已摘除")
    if sb.get("start_location") and str(sb["start_location"]) not in loc_ids:
        sb.pop("start_location", None)
        notes.append("start_location 不存在已摘除")
    if sb.get("default_powers") is not None:
        raw = sb["default_powers"] if isinstance(sb["default_powers"], list) else []
        clean = [str(p).strip()[:40] for p in raw if str(p).strip()][:4]
        if clean != sb["default_powers"]:
            notes.append("default_powers 已修剪 (≤4条×≤40字)")
        sb["default_powers"] = clean
    if "start_money" in sb:
        try:
            sb["start_money"] = max(0, int(sb["start_money"]))
        except (TypeError, ValueError):
            sb["start_money"] = 100
            notes.append("start_money 非法已回落 100")
    if sb.get("currency") is not None:
        sb["currency"] = str(sb["currency"]).strip()[:6] or "元"
    return notes
```

- [ ] **Step 4: 跑测试看绿**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_sandbox_sanitize.py -q
```
Expected: 7 passed

- [ ] **Step 5: 提交**

```bash
cd /c/Users/17745/linguisplay
git add apps/api/app/engine/logic.py apps/api/tests/test_sandbox_sanitize.py
git commit -m "🏖 沙盒九键形状闸 sanitize_sandbox: 确定性修剪, 治静默失效"
```

---

### Task 2: LLM 层 —— `sandbox_summary` / `sandbox_world` prompt + MockLLM 孪生

**Files:**
- Modify: `apps/api/app/engine/qwen.py`（方法加在 `_gen_progression` 之后；分发行加进 `generate()` 的分发块，`qwen.py:5828-5854` 一带，紧挨 `gen_progression` 那行）
- Modify: `apps/api/app/engine/llm.py`（MockLLM 孪生加在 `engine_skeleton` 孪生之前）
- Test: `apps/api/tests/test_sandbox_llm_contract.py`（新建）

**Interfaces:**
- Consumes: `_post_chat` / `_lang_rule`（qwen.py 现有私有工具，抄 `_gen_progression` 的用法）
- Produces:
  - `llm.generate({"sandbox_summary": True, "answers": dict}) -> {"summary": str}`
  - `llm.generate({"sandbox_world": True, "answers": dict, "summary": str}) -> dict`，键面 = `SANDBOX_WORLD_KEYS`
  - `qwen.SANDBOX_WORLD_KEYS: tuple[str, ...]`（模块级常量，mock/真两边共同的合同）
  - MockLLM 新增 `gen_progression` 孪生（固定六阶「剑心」阶梯）——Task 4 的 e2e 靠它确定性

- [ ] **Step 1: 写失败测试**

```python
# -*- coding: utf-8 -*-
"""📜 沙盒起草的 mock/真 prompt 同构合同。历史实弹: MockLLM 孪生与真 prompt 字段
不同构 → 测试绿真机歪。合同 = qwen.SANDBOX_WORLD_KEYS 一份常量锁两边。"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./test_sbllm.db")
os.environ.setdefault("JWT_SECRET", "test")

from app.engine import qwen  # noqa: E402
from app.engine.llm import MockLLM  # noqa: E402

ANSWERS = {"题材": "修仙", "世界观": "灵脉将枯的山城", "超凡体系": "剑心"}


def test_mock_sandbox_world_covers_the_contract_keys():
    out = MockLLM().generate({"sandbox_world": True, "answers": ANSWERS,
                              "summary": "云脊山脉深处的问剑小城"})
    for k in qwen.SANDBOX_WORLD_KEYS:
        assert k in out, f"mock 孪生缺 {k} — 测试世界与真机分家"


def test_mock_world_style_keeps_the_head_tail_layout():
    out = MockLLM().generate({"sandbox_world": True, "answers": ANSWERS, "summary": "x"})
    assert "忌" in out["style"], "style 尾部必须有忌清单 (截断保尾靠它, qwen.py:63-93)"
    assert out["tech_level"] in ("modern", "ancient", "future")
    assert 3 <= len(out["locations"]) <= 4


def test_mock_summary_and_progression_twins_exist():
    m = MockLLM()
    s = m.generate({"sandbox_summary": True, "answers": ANSWERS})
    assert len(s.get("summary") or "") >= 30
    p = m.generate({"gen_progression": True, "world": "x", "title": "y"})
    assert p.get("name") and 4 <= len(p.get("ranks") or []) <= 12


def test_real_prompt_methods_are_wired_into_dispatch():
    """真模型类必须有方法且 generate() 分发得到 — 只验静态接线, 不打真网。"""
    for cls_name in ("QwenLLM", "DeepSeekLLM"):
        cls = getattr(qwen, cls_name)
        assert hasattr(cls, "_sandbox_world") and hasattr(cls, "_sandbox_summary")
```

- [ ] **Step 2: 跑测试看红**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_sandbox_llm_contract.py -q
```
Expected: FAIL —— `AttributeError: module 'app.engine.qwen' has no attribute 'SANDBOX_WORLD_KEYS'`

- [ ] **Step 3: 实现**

qwen.py —— 模块级常量（放文件顶部常量区）：

```python
# 🏜 问卷造沙盒: 世界铸造的输出键面 — mock 孪生与真 prompt 的共同合同,
# 两边都以它为准 (历史实弹: 孪生漂移 = 测试绿真机歪)
SANDBOX_WORLD_KEYS = ("title", "one_liner", "synopsis", "world_long", "world_facts",
                      "era", "tech_level", "trope_tags", "locations", "style")
```

qwen.py —— 两个方法，加在 `_gen_progression` 之后（`_post_chat`/异常降级抄它）：

```python
    def _sandbox_summary(self, prompt: dict[str, Any]) -> dict[str, Any]:
        """🏜 问卷确认环: 答案 → 一段给创作者确认的世界概要 (可改可重摇)。"""
        a = prompt.get("answers") or {}
        lines = "\n".join(f"{k}：{v}" for k, v in a.items() if str(v).strip())
        sys = ("根据问卷答案写一段 150~250 字的【世界概要】给创作者确认："
               "这个世界是什么、此刻正在酝酿什么、主角开局的处境。"
               "有画面感、有钩子；简体中文，只输出概要本身，不加任何说明。")
        try:
            resp = _post_chat(self._url, self._key,
                              {"model": self._model,
                               "messages": [{"role": "system", "content": sys},
                                            {"role": "user", "content": lines or "随便来一个"}],
                               "max_tokens": 500, "temperature": 0.9},
                              timeout=60, kind="sandbox_summary")
            return {"summary": (resp.json()["choices"][0]["message"]["content"] or "").strip()}
        except Exception:
            return {}

    def _sandbox_world(self, prompt: dict[str, Any]) -> dict[str, Any]:
        """🏜 问卷造沙盒: answers + 创作者确认过的概要 → 世界件 (SANDBOX_WORLD_KEYS)。
        概要是权威 — 玩家改过的字不许被生成物推翻。"""
        import json as _json
        a = prompt.get("answers") or {}
        lines = "\n".join(f"{k}：{v}" for k, v in a.items() if str(v).strip())
        summary = (prompt.get("summary") or "").strip()
        sys = ("你为一个自由沙盒互动世界做设定铸造。只输出JSON："
               '{"title":"世界名(≤10字)","one_liner":"一句话引子(≤30字)",'
               '"synopsis":"给玩家看的简介(120~200字)",'
               '"world_long":"世界设定正文(400~600字, 忠实扩写给定概要)",'
               '"world_facts":"硬性物理事实(≤180字, 只写可观察事实, 分号隔开)",'
               '"era":"年代感(≤20字)","tech_level":"modern|ancient|future 三选一",'
               '"trope_tags":["2~4个题材标签, 每个≤6字"],'
               '"locations":[{"name":"地名≤8字","detail":"一句白描≤40字",'
               '"exits":["相邻地名"]}, 共3~4个, exits只许指向本列表里的地名],'
               '"style":"文风卡：第一句写作者腔(该题材代表作的叙事口吻)，'
               '中间写节奏要求，最后以「忌」字开头列3条忌用清单"}。'
               "设定必须与概要一致，不得引入与概要冲突的重大设定。")
        u = f"问卷：\n{lines}\n\n创作者确认过的世界概要（权威）：\n{summary}"
        try:
            resp = _post_chat(self._url, self._key,
                              {"model": self._model,
                               "messages": [{"role": "system", "content": sys},
                                            {"role": "user", "content": u}],
                               "max_tokens": 1800, "temperature": 0.6,
                               "response_format": {"type": "json_object"}},
                              timeout=60, kind="sandbox_world")
            data = _json.loads(resp.json()["choices"][0]["message"]["content"] or "{}")
            if not isinstance(data, dict):
                return {}
            # 合同收口: 缺键补空值, 键面永远 = SANDBOX_WORLD_KEYS
            return {k: data.get(k) if data.get(k) is not None
                    else ([] if k in ("trope_tags", "locations") else "")
                    for k in SANDBOX_WORLD_KEYS}
        except Exception:
            return {}
```

qwen.py —— 分发块（`if prompt.get("gen_progression")` 那两行旁边）加：

```python
        if prompt.get("sandbox_summary"):
            return self._sandbox_summary(prompt)
        if prompt.get("sandbox_world"):
            return self._sandbox_world(prompt)
```

llm.py —— MockLLM 孪生，加在 `if prompt.get("engine_skeleton"):` 之前：

```python
        # 🏜 问卷造沙盒孪生: 确定性修仙小世界 — 组装/形状闸/e2e 链路可测。
        # 键面必须盖满 qwen.SANDBOX_WORLD_KEYS (合同测试执法)。
        if prompt.get("sandbox_summary"):
            return {"summary": "云脊山脉深处的问剑小城，宗门林立而灵脉将枯。"
                               "外来的你在山门前醒来，怀里只有一块认不出来历的旧玉牌。"
                               "三日后就是宗门大比，全城都在赌一个新面孔的命运。"}
        if prompt.get("sandbox_world"):
            return {"title": "问剑小城", "one_liner": "灵脉将枯的山城，剑还悬着。",
                    "synopsis": "云脊山脉深处的问剑小城，三大宗门围着最后一条灵脉过活。"
                                "大比在即，山门前多了一个来历不明的新面孔——你。",
                    "world_long": "云脊山脉深处，问剑小城依灵脉而建。灵脉每月初一枯一分，"
                                  "三大宗门表面共守、私下各挖各的。城中规矩：亥时宵禁，"
                                  "佩剑者不查。三日后宗门大比，胜者入主灵脉井。",
                    "world_facts": "灵脉每月初一枯一分；亥时宵禁；佩剑者免查。",
                    "era": "架空古代", "tech_level": "ancient",
                    "trope_tags": ["修仙", "宗门"],
                    "locations": [
                        {"name": "山门广场", "detail": "青石铺地，剑痕纵横", "exits": ["藏剑阁", "灵脉井"]},
                        {"name": "藏剑阁", "detail": "一层浮尘，剑鞘空了一半", "exits": ["山门广场"]},
                        {"name": "灵脉井", "detail": "井口结着薄霜", "exits": ["山门广场"]}],
                    "style": "仿古典武侠白话：短句起势，动词见筋骨。节奏要求：每一轮必须"
                             "有一件具体的事向前发生。忌华丽堆藻；忌现代词汇；忌心理独白连篇。"}
        if prompt.get("gen_progression"):
            return {"name": "剑心",
                    "ranks": ["淬体", "凝气", "问剑", "御剑", "剑心通明", "化神"]}
```

- [ ] **Step 4: 跑测试看绿 + 全套件抽查**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_sandbox_llm_contract.py -q
./.venv/Scripts/python.exe -m pytest tests -q
```
Expected: 新增 4 passed；全套件零新红。⚠️ MockLLM 新增 `gen_progression` 孪生后，
所有用 MockLLM 开沙盒局的存量测试会**从「无阶梯」变「有剑心阶梯」**——若有用例
断言无阶梯而变红，读它的意图再改断言（阶梯有了是产品变好，不是回归）。

- [ ] **Step 5: 提交**

```bash
cd /c/Users/17745/linguisplay
git add apps/api/app/engine/qwen.py apps/api/app/engine/llm.py apps/api/tests/test_sandbox_llm_contract.py
git commit -m "🏜 沙盒起草 LLM 件: sandbox_summary/sandbox_world prompt + Mock 三孪生 (合同=SANDBOX_WORLD_KEYS)"
```

---

### Task 3: 确定性组装器 `_assemble_sandbox`

**Files:**
- Modify: `apps/api/app/routers/stories.py`（加在 `_strip_all_gates` 之后、`draft_engine` 之前）
- Test: `apps/api/tests/test_sandbox_assemble.py`（新建）

**Interfaces:**
- Consumes: 无外部依赖（纯函数 + 模块级映射表）
- Produces: `_assemble_sandbox(world: dict, chars: list[dict], prog: dict | None, answers: dict, title_override: str = "") -> dict`（StoryInput 形状的 payload；Task 4 管线调它）；`_SANDBOX_ECON: dict[str, tuple[str, int]]`

- [ ] **Step 1: 写失败测试**

```python
# -*- coding: utf-8 -*-
"""🧩 沙盒 payload 组装: 世界件+角色+阶梯+答案 → StoryInput 形状。
确定性部分绝不烧模型: 经济映射/phone 开合/单幕/endings=[] 全是查表和惯例。"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./test_sbasm.db")
os.environ.setdefault("JWT_SECRET", "test")

from app.engine.llm import MockLLM  # noqa: E402
from app.routers.stories import _assemble_sandbox  # noqa: E402
from app.schemas import StoryInput  # noqa: E402

WORLD = MockLLM().generate({"sandbox_world": True, "answers": {}, "summary": "x"})
CHARS = [{"id": "ch_1", "name": "甲", "playable": False, "schedule": [], "ties": []}]
PROG = {"name": "剑心", "ranks": ["淬体", "凝气", "问剑", "御剑", "剑心通明", "化神"]}


def _p(answers=None, prog=PROG):
    return _assemble_sandbox(WORLD, CHARS, prog, answers or {"题材": "修仙"}, "")


def test_payload_passes_story_input_schema():
    StoryInput(**_p())   # 与 studio/draft_engine 共用同一道门, 不许私有格式


def test_sandbox_conventions_hold():
    p = _p()
    assert p["endings"] == [] and len(p["acts"]) == 1, "沙盒惯例: 单幕无结局"
    assert p["visibility"] == "private" and p["language"] == "zh"
    sb = p["sandbox"]
    assert sb["enabled"] is True and sb["real_time"] is True
    assert sb["opening_visitor"] == "ch_1"
    assert sb["start_location"] == "loc_1"
    assert sb["progression"]["name"] == "剑心"


def test_genre_maps_economy_deterministically():
    assert _p({"题材": "修仙"})["sandbox"]["currency"] == "灵石"
    assert _p({"题材": "星际"})["sandbox"]["start_money"] == 200
    assert _p({"题材": "没听过的题材"})["sandbox"]["currency"] == "元"


def test_powers_come_from_answers_one_per_line_clamped():
    p = _p({"题材": "修仙", "金手指": "能看见他人头顶的死期\n" + "长" * 60 + "\nc\nd\ne"})
    ps = p["sandbox"]["default_powers"]
    assert len(ps) == 4 and all(len(x) <= 40 for x in ps)
    assert ps[0] == "能看见他人头顶的死期"


def test_tech_level_drives_phone():
    assert _p()["phone"] == {"enabled": False}   # mock 世界 tech_level=ancient
    modern = dict(WORLD, tech_level="modern")
    p = _assemble_sandbox(modern, CHARS, None, {"题材": "都市异能"}, "")
    assert p["phone"] == {"enabled": True, "device": "手机"}


def test_no_progression_means_no_key_at_all():
    p = _p(prog=None)
    assert "progression" not in p["sandbox"], "留空才轮得到开局 ensure_progression 兜底"


def test_style_and_locations_ride_along():
    p = _p()
    assert "忌" in p["style"]
    assert p["locations"][0]["id"] == "loc_1"
    assert all(l["unlock"]["act_min"] == 0 for l in p["locations"])
```

- [ ] **Step 2: 跑测试看红**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_sandbox_assemble.py -q
```
Expected: FAIL —— `ImportError: cannot import name '_assemble_sandbox'`

- [ ] **Step 3: 实现（stories.py，`_strip_all_gates` 之后）**

```python
# ── 🏜 问卷造沙盒 (spec: docs/superpowers/specs/2026-08-16-survey-sandbox-maker-design.md) ──
_SANDBOX_ECON = {  # 题材 → (货币, 开局钱): 确定性查表, 这种事不烧模型
    "修仙": ("灵石", 20), "都市异能": ("元", 300), "西幻": ("金币", 30),
    "末世": ("物资点", 50), "宫斗": ("两银", 20), "星际": ("星币", 200)}


def _assemble_sandbox(world: dict, chars: list[dict], prog: dict | None,
                      answers: dict, title_override: str = "") -> dict:
    """世界件+角色+阶梯+问卷答案 → StoryInput 形状的沙盒 payload。
    沙盒惯例: 单幕、endings=[] (沙盒没有出口)、私有落库。"""
    locs = [{"id": f"loc_{i+1}", "name": str(l.get("name") or f"地点{i+1}")[:12],
             "detail": str(l.get("detail") or "")[:80],
             "exits": [str(x) for x in (l.get("exits") or [])],
             "unlock": {"act_min": 0, "affinity_min": 0, "required_fragment_ids": []},
             "props": []}
            for i, l in enumerate((world.get("locations") or [])[:4])]
    currency, money = _SANDBOX_ECON.get(str(answers.get("题材") or ""), ("元", 100))
    powers = [str(p).strip()[:40] for p in str(answers.get("金手指") or "").splitlines()
              if str(p).strip()][:4]
    tech = str(world.get("tech_level") or "modern")
    phone = ({"enabled": False} if tech == "ancient"
             else {"enabled": True, "device": "终端" if tech == "future" else "手机"})
    sandbox: dict = {"enabled": True, "real_time": True,
                     "currency": currency, "start_money": money}
    if powers:
        sandbox["default_powers"] = powers
    if prog and str((prog or {}).get("name") or "").strip() and prog.get("ranks"):
        sandbox["progression"] = {"name": str(prog["name"]).strip()[:8],
                                  "ranks": [str(r)[:8] for r in prog["ranks"]][:12]}
    if chars:
        sandbox["opening_visitor"] = chars[0]["id"]
    if locs:
        sandbox["start_location"] = locs[0]["id"]
    era = str(world.get("era") or answers.get("年代感") or "").strip()[:60]
    if era:
        sandbox["era"] = era
    return {
        "title": (title_override or str(world.get("title") or "未命名沙盒"))[:24],
        "language": "zh", "visibility": "private",
        "one_liner": str(world.get("one_liner") or "")[:40],
        "synopsis": str(world.get("synopsis") or "")[:400],
        "world_long": str(world.get("world_long") or "")[:2000],
        "world_facts": str(world.get("world_facts") or "")[:400],
        "style": str(world.get("style") or "")[:600],
        "trope_tags": [str(t)[:8] for t in (world.get("trope_tags") or [])[:4]],
        "characters": chars,
        "acts": [{"index": 1, "title": "自由行", "goal": "", "events": [],
                  "advance": {"required_fragment_ids": [], "required_event_ids": [],
                              "affinity_min": 0}}],
        "locations": locs, "endings": [], "phone": phone, "sandbox": sandbox,
        "tuning": {"_origin": "survey_sandbox"},
    }
```

- [ ] **Step 4: 跑测试看绿**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_sandbox_assemble.py tests/test_sandbox_sanitize.py -q
```
Expected: 全绿

- [ ] **Step 5: 提交**

```bash
cd /c/Users/17745/linguisplay
git add apps/api/app/routers/stories.py apps/api/tests/test_sandbox_assemble.py
git commit -m "🧩 沙盒 payload 组装器: 经济查表/phone开合/单幕惯例, 确定性不烧模型"
```

---

### Task 4: 端点三件 + 配额闸 + 响应模型

**Files:**
- Modify: `apps/api/app/schemas.py`（`ChooseOut` 附近加四个小模型）
- Modify: `apps/api/app/routers/stories.py`（`draft_engine_result` 之后加三个端点）
- Test: `apps/api/tests/test_draft_sandbox.py`（新建）

**Interfaces:**
- Consumes: Task 1 `sanitize_sandbox`、Task 2 三个 LLM 键、Task 3 `_assemble_sandbox`、现有 `_PARSE_JOBS`/`_PARSE_CAP`/`_sanitize_cards`/`_degrade_draft`/`StoryInput`
- Produces（前端 Task 6 依赖，字段名不许漂）:
  - `POST /api/v1/stories/draft_sandbox/summary` body `{answers}` → `{summary}`
  - `POST /api/v1/stories/draft_sandbox` body `{answers, summary, title?}` → `{job}`
  - `GET /api/v1/stories/draft_sandbox/{job_id}` → `{status: working|done|error|gone, story_id?, error?}`

- [ ] **Step 1: 写失败测试**

```python
# -*- coding: utf-8 -*-
"""🏜 问卷→沙盒本 e2e (MockLLM): 答案进, 私有可玩的沙盒本出。
断言全链: 九键形状 / 单幕无结局 / lint 干净 / 玩家真的能开局 / 配额闸。"""
import os
import time
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./test_draft_sandbox.db")
os.environ.setdefault("JWT_SECRET", "test")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import SessionLocal, init_db  # noqa: E402
from app.engine import logic as logic_mod  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Story  # noqa: E402

ANSWERS = {"题材": "修仙", "世界观": "灵脉将枯的山城", "超凡体系": "剑心",
           "金手指": "能看见他人头顶的死期", "分级": "全年龄"}
SUMMARY = "云脊山脉深处的问剑小城，宗门林立而灵脉将枯。" * 3


@pytest.fixture()
def c():
    init_db()
    cl = TestClient(app)
    r = cl.post("/api/v1/auth/signup", json={
        "email": f"sb-{uuid.uuid4().hex[:8]}@survey.com",
        "password": "pw12345678", "dob": "1990-01-01", "accepted_tos": True})
    assert r.status_code in (200, 201), r.text
    yield cl


def _build(cl):
    r = cl.post("/api/v1/stories/draft_sandbox",
                json={"answers": ANSWERS, "summary": SUMMARY, "title": "我的小世界"})
    assert r.status_code == 200, r.text
    jid = r.json()["job"]
    for _ in range(40):   # Mock 秒级完成, 上限 8s 防呆
        st = cl.get(f"/api/v1/stories/draft_sandbox/{jid}").json()
        if st["status"] != "working":
            return st
        time.sleep(0.2)
    raise AssertionError("job 没完成")


def test_summary_endpoint_writes_a_summary(c):
    r = c.post("/api/v1/stories/draft_sandbox/summary", json={"answers": ANSWERS})
    assert r.status_code == 200, r.text
    assert len(r.json()["summary"]) >= 30


def test_survey_builds_a_playable_private_sandbox(c):
    st = _build(c)
    assert st["status"] == "done", st.get("error")
    sid = st["story_id"]
    db = SessionLocal()
    row = db.get(Story, sid)
    try:
        assert row.visibility == "private" and row.title == "我的小世界"
        sb = row.sandbox
        assert sb["enabled"] and sb["currency"] == "灵石" and sb["start_money"] == 20
        assert sb["progression"]["name"] == "剑心" and len(sb["progression"]["ranks"]) == 6
        assert sb["opening_visitor"] == "ch_1" and sb["start_location"] == "loc_1"
        assert sb["default_powers"] == ["能看见他人头顶的死期"]
        assert row.endings == [] and len(row.acts) == 1
        assert row.phone == {"enabled": False}      # mock 世界是 ancient
        assert "忌" in (row.style or "")
        assert (row.tuning or {}).get("_origin") == "survey_sandbox"
        content = {"story": {"title": row.title, "characters": row.characters,
                             "acts": row.acts, "locations": row.locations,
                             "endings": row.endings, "sandbox": row.sandbox},
                   "secrets": []}
        errs = [i for i in logic_mod.lint_story(content) if i.get("severity") == "error"]
        assert not errs, f"起草物过不了发布硬门: {errs}"
    finally:
        db.close()
    # 答完即玩: owner 对自己的私有草稿直接开局 (runs.py:593 放行)
    pid = c.post("/api/v1/personas", json={"name": "铸世者"}).json()["id"]
    rr = c.post("/api/v1/runs", json={"story_id": sid, "persona_id": pid})
    assert rr.status_code == 201, rr.text


def test_thin_summary_is_refused(c):
    r = c.post("/api/v1/stories/draft_sandbox",
               json={"answers": ANSWERS, "summary": "太薄"})
    assert r.status_code == 400


def test_daily_quota_is_three(c):
    for _ in range(3):
        st = _build(c)
        assert st["status"] == "done"
    r = c.post("/api/v1/stories/draft_sandbox",
               json={"answers": ANSWERS, "summary": SUMMARY})
    assert r.status_code == 429, "第 4 次要被拦 — 每日 3 次"


def test_summary_quota_429(c):
    from app.routers import stories as stories_mod
    import time as _t
    # 直接把当日计数打满 — 别真调 10 次浪费秒数
    uidkey = None
    r = c.post("/api/v1/stories/draft_sandbox/summary", json={"answers": ANSWERS})
    assert r.status_code == 200
    for k in list(stories_mod._SANDBOX_SUM_QUOTA):
        stories_mod._SANDBOX_SUM_QUOTA[k] = 10
        uidkey = k
    assert uidkey
    r = c.post("/api/v1/stories/draft_sandbox/summary", json={"answers": ANSWERS})
    assert r.status_code == 429
```

- [ ] **Step 2: 跑测试看红**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_draft_sandbox.py -q
```
Expected: FAIL —— 404（端点不存在）

- [ ] **Step 3: 实现**

schemas.py（`ChooseOut` 之后）：

```python
class SandboxSurveyIn(BaseModel):
    answers: dict = {}


class DraftSandboxIn(BaseModel):
    answers: dict = {}
    summary: str = ""        # 确认环产物 (玩家改过的版本是权威)
    title: Optional[str] = None


class DraftJobOut(BaseModel):
    job: str


class DraftSandboxStatus(BaseModel):
    status: str              # working | done | error | gone
    story_id: Optional[str] = None
    error: Optional[str] = None


class SandboxSummaryOut(BaseModel):
    summary: str
```

stories.py —— 导入行把 `ChooseIn` 同一处的 import 补上新模型（`SandboxSurveyIn,
DraftSandboxIn, DraftJobOut, DraftSandboxStatus, SandboxSummaryOut`），端点加在
`draft_engine_result` 之后：

```python
# ── 🏜 问卷造沙盒 (答完即玩, 满意再公开) ─────────────────────
_SANDBOX_SUM_QUOTA: dict[str, int] = {}   # f"{uid}:{yyyymmdd}" → 当日概要次数
                                          # (进程内, 重启清零 — v1 接受)


@router.post("/draft_sandbox/summary", response_model=SandboxSummaryOut)
def draft_sandbox_summary(body: SandboxSurveyIn, user: User = Depends(current_user)):
    """🏜 确认环: 答案 → 一段世界概要, 创作者可改可重摇。重摇每日 10 次。"""
    import time as _t
    answers = {str(k)[:24]: str(v)[:500] for k, v in (body.answers or {}).items()
               if str(v).strip()}
    if not answers:
        raise HTTPException(400, "先答几道题，概要才有的可写")
    key = f"{user.id}:{_t.strftime('%Y%m%d')}"
    if _SANDBOX_SUM_QUOTA.get(key, 0) >= 10:
        raise HTTPException(429, "今天的重摇次数用完了——直接改文字也一样算数")
    _SANDBOX_SUM_QUOTA[key] = _SANDBOX_SUM_QUOTA.get(key, 0) + 1
    from ..engine.llm import get_llm
    out = get_llm().generate({"sandbox_summary": True, "answers": answers}) or {}
    s = str(out.get("summary") or "").strip()
    if len(s) < 30:
        raise HTTPException(502, "这次没写出来——点重摇再试一次")
    return {"summary": s[:2000]}


@router.post("/draft_sandbox", response_model=DraftJobOut)
def draft_sandbox(body: DraftSandboxIn, user: User = Depends(current_user),
                  db: Session = Depends(get_db)):
    """🏜 问卷 → 沙盒本: 立即返回 {job}; 轮询 GET /stories/draft_sandbox/{job}。
    完成即私有可玩; 公开走工坊发布+可见性两道现有开关。每日 3 次。"""
    import threading
    import time as _t
    import uuid as _uuid
    from datetime import datetime
    answers = {str(k)[:24]: str(v)[:500] for k, v in (body.answers or {}).items()
               if str(v).strip()}
    summary = (body.summary or "").strip()[:2000]
    if len(summary) < 50:
        raise HTTPException(400, "先生成并确认世界概要——它是整个世界的地基")
    day0 = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    mine_today = (db.query(StoryModel)
                  .filter(StoryModel.owner_id == user.id,
                          StoryModel.created_at >= day0).all())
    if sum(1 for s in mine_today
           if (s.tuning or {}).get("_origin") == "survey_sandbox") >= 3:
        raise HTTPException(429, "今天已经铸了 3 个世界——明天再来，或先把今天的打磨好")
    if any(j.get("uid") == user.id and j.get("kind") == "sandbox"
           and j.get("status") == "working" for j in _PARSE_JOBS.values()):
        raise HTTPException(409, "有一个世界正在铸造中——等它完成再开新的")
    jid = _uuid.uuid4().hex[:12]
    _PARSE_JOBS[jid] = {"status": "working", "at": _t.time(), "uid": user.id,
                        "kind": "sandbox"}
    while len(_PARSE_JOBS) > _PARSE_CAP:
        _PARSE_JOBS.pop(next(iter(_PARSE_JOBS)), None)
    uid, utitle = user.id, (body.title or "").strip()[:24]

    def _work():
        import json as _json

        from ..db import SessionLocal
        from ..engine import logic as logic_mod
        from ..engine.llm import get_llm
        job = _PARSE_JOBS.get(jid)
        try:
            llm = get_llm()
            world = llm.generate({"sandbox_world": True, "answers": answers,
                                  "summary": summary}) or {}
            if not (str(world.get("title") or "").strip()
                    and len(str(world.get("world_long") or "")) >= 50):
                raise ValueError("世界没铸出来——概要再具体一点试试")
            cards = _sanitize_cards(llm.generate({
                "char_from_text": True,
                "text": (summary + "\n" + str(world.get("world_long") or ""))[:5000],
                "world": str(world.get("world_long") or ""),
                "language": "zh"}) or {})
            chars = [{**c, "id": f"ch_{i+1}", "playable": False, "schedule": [],
                      "ties": [], "items": c.get("items") or [],
                      "bio_layers": c.get("bio_layers") or []}
                     for i, c in enumerate(cards[:5])]
            prog = None
            wants = str(answers.get("超凡体系") or "").strip()
            if wants and wants != "没有":
                prog = llm.generate({"gen_progression": True,
                                     "world": str(world.get("world_long") or "")[:800],
                                     "title": str(world.get("title") or "")}) or None
            payload = _assemble_sandbox(world, chars, prog, answers, utitle)
            notes = logic_mod.sanitize_sandbox(payload)
            data = StoryInput(**payload)
            content = {"story": data.model_dump(), "secrets": []}
            for _round in range(2):   # 沙盒无秘密, 走一遍以防万一 (dangling_exit 等)
                errs = [i for i in logic_mod.lint_story(content)
                        if i.get("severity") == "error"]
                if not errs:
                    break
                _degrade_draft(content, errs)
            db2 = SessionLocal()
            try:
                st = content["story"]
                st["tuning"]["_draft_size"] = len(_json.dumps(content, ensure_ascii=False))
                if notes:
                    st["tuning"]["_sanitize_notes"] = notes[:6]
                row = StoryModel(
                    owner_id=uid, title=st["title"], language="zh",
                    one_liner=st.get("one_liner"), synopsis=st.get("synopsis"),
                    world_long=st.get("world_long"), world_facts=st.get("world_facts"),
                    style=st.get("style") or "", trope_tags=st.get("trope_tags") or [],
                    visibility="private",
                    characters=st.get("characters") or [], acts=st.get("acts") or [],
                    endings=[], locations=st.get("locations") or [],
                    phone=st.get("phone"), sandbox=st.get("sandbox"),
                    tuning=st.get("tuning") or {})
                db2.add(row)
                db2.commit()
                sid = row.id
            finally:
                db2.close()
            if job is not None:
                job.update({"status": "done", "story_id": sid})
        except Exception as e:
            if job is not None:
                job.update({"status": "error", "error": str(e)[:120] or "铸造失败"})

    threading.Thread(target=_work, daemon=True).start()
    return {"job": jid}


@router.get("/draft_sandbox/{job_id}", response_model=DraftSandboxStatus)
def draft_sandbox_result(job_id: str, user: User = Depends(current_user)):
    job = _PARSE_JOBS.get(job_id)
    if not job or job.get("uid") != user.id:
        return {"status": "gone"}
    if job.get("status") == "working":
        return {"status": "working"}
    if job.get("status") == "error":
        return {"status": "error", "error": job.get("error")}
    return {"status": "done", "story_id": job.get("story_id")}
```

⚠️ 路由顺序：FastAPI 按注册序匹配，`/draft_sandbox/summary` 是静态段、
`/draft_sandbox/{job_id}` 是动态段——**summary 端点必须写在 `{job_id}` 之前**
（上面的顺序已保证；挪动时别弄反，弄反了 summary 会被当 job_id 吃掉）。

- [ ] **Step 4: 跑测试看绿**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_draft_sandbox.py -q
```
Expected: 5 passed

- [ ] **Step 5: 提交**

```bash
cd /c/Users/17745/linguisplay
git add apps/api/app/routers/stories.py apps/api/app/schemas.py apps/api/tests/test_draft_sandbox.py
git commit -m "🏜 draft_sandbox 三端点: 确认环+铸造job+轮询, 每日3次/概要10次闸, 全带响应模型"
```

---

### Task 5: 契约重导

**Files:**
- Modify: `packages/contract/openapi.json`（生成物）

- [ ] **Step 1: 重导 + 确认新端点入契约**

```bash
cd /c/Users/17745/linguisplay/apps/api
PYTHONIOENCODING=utf-8 PYTHONPATH=winshim ./.venv/Scripts/python.exe dump_openapi.py
grep -c "draft_sandbox" ../../packages/contract/openapi.json
```
Expected: 导出成功（138 条路径），grep 计数 ≥ 3

- [ ] **Step 2: 提交**

```bash
cd /c/Users/17745/linguisplay
git add packages/contract/openapi.json
git commit -m "📜 契约重导: draft_sandbox 三端点入册 (响应模型齐, 不添空 schema 债)"
```

---

### Task 6: 前端向导改造（galmaker.html）+ play.html 深链

**Files:**
- Modify: `apps/api/app/static/galmaker.html`（wz* 向导区，143-330 一带）
- Modify: `apps/api/app/static/play.html`（文件末尾 boot IIFE，约 6250 行处）

**Interfaces:**
- Consumes: Task 4 三端点（字段名 `answers/summary/title/job/status/story_id/error`）；现有 `j()` fetch 助手、`$id()`、`wzSaveNow`（PATCH `/gal/{id}/survey`，**概要存进现有 `idea` 槽位**，gal.py 零改动）
- Produces: 玩家可走通「造什么→沙盒题→概要确认→铸造→▶️踏入 / 🛠工坊」全流程

- [ ] **Step 1: 新增题目常量（`const QS = [...]` 之后插入）**

```js
// ── 🏜 沙盒题集 (spec 2026-08-16): 主干6题 + 题材支线 (branch 按题材显隐, 纯前端) ──
const MODEQ = { k: "造什么", q: "想造哪一种？",
  chips: ["🎀 选项式 galgame", "🏜 自由沙盒世界"] };
const SQS_ALL = [
  { k: "题材", q: "想要一个什么题材的世界？",
    chips: ["修仙", "都市异能", "西幻", "末世", "宫斗", "星际"], free: "或自己写一个题材" },
  { k: "世界观", q: "用几句话描述这个世界（越具体越像你想的那样）",
    free: "例：灵脉将枯的山城，三大宗门抢最后一口灵气", area: true },
  { k: "年代感", q: "年代感？", free: "例：1899 清末 / 三千年后的星港 / 盛唐", skip: true },
  { k: "超凡体系", q: "这个世界有超凡力量体系吗？叫什么？",
    chips: ["没有"], free: "例：斗气 / 灵力 / 军衔 / 血统位阶", skip: true },
  { k: "开局处境", q: "主角开局是什么处境？", free: "例：宗门大比前三天被逐出师门", skip: true },
  { k: "金手指", q: "给主角 0~4 条金手指（一行一条，40 字内）",
    free: "例：能看见他人头顶的死期", area: true, skip: true },
  { k: "分级", q: "尺度", chips: ["全年龄", "18+"] },
  { k: "境界命名风格", q: "境界名想要什么风格？", branch: "修仙",
    chips: ["古典雅致", "杀伐直白"], free: "或自己定几个", skip: true },
  { k: "宗门格局", q: "宗门格局？", branch: "修仙",
    free: "例：三大宗门鼎立，散修如蚁", skip: true },
  { k: "异能来源", q: "异能从哪来？", branch: "都市异能",
    chips: ["觉醒", "契约", "科技改造", "血脉"], skip: true },
  { k: "威胁类型", q: "末世的威胁是什么？", branch: "末世",
    chips: ["丧尸", "天灾", "外星文明", "人心"], free: "或自己写", skip: true },
  { k: "朝局", q: "眼下的朝局？", branch: "宫斗",
    free: "例：皇帝病重，两宫争储", skip: true },
];
const wzSandbox = () => (WD.answers["造什么"] || "").includes("沙盒");
function wzPages() {
  if (wzSandbox()) {
    const qs = SQS_ALL.filter(q => !q.branch || (WD.answers["题材"] || "") === q.branch);
    return [{ t: "q", q: MODEQ }, ...qs.map(q => ({ t: "q", q })),
            { t: "summary" }, { t: "sdone" }];
  }
  return [{ t: "q", q: MODEQ }, ...QS.map(q => ({ t: "q", q })),
          { t: "art" }, { t: "idea" }, { t: "outline" }, { t: "done" }];
}
```

- [ ] **Step 2: 改 `wzInit`（老草稿迁移一格）**

`wzInit` 里 `WD = {...}` 赋值之后、`wzRender()` 之前插入：

```js
  // 老草稿迁移: 「造什么」是后加的第 0 题 — 答过题却没答它的老 gal 草稿顺移一格
  if (!WD.answers["造什么"] && WD.step > 0) {
    WD.answers["造什么"] = "🎀 选项式 galgame";
    WD.step += 1;
  }
```

- [ ] **Step 3: 重写 `wzRender` / `wzCollectFree` / `wzGo`（整段替换原三函数）**

```js
function wzRender() {
  const pages = wzPages(), s = Math.min(WD.step, pages.length - 1), pg = pages[s];
  const body = $id("wzBody");
  WD.step = s;
  $id("wzPrev").style.visibility = s > 0 ? "visible" : "hidden";
  $id("wzStep").textContent = `第 ${s + 1} / ${pages.length} 步`;
  $id("wzNext").style.display = "";
  if (pg.t === "q") {
    const q = pg.q, a = WD.answers;
    let h = `<label style="font-size:15px;color:#e7eaf3;margin-top:14px">${q.q}</label>`;
    if (q.chips) h += "<div>" + q.chips.map(c =>
      _chip(c, a[q.chipKey || q.k] === c, `wzPick('${q.chipKey || q.k}','${c}',${!q.free && !q.chips2 && !q.mature})`)).join("") + "</div>";
    if (q.chips2) h += "<div>" + q.chips2.map(c =>
      _chip(c, a[q.chipKey2] === c, `wzPick('${q.chipKey2}','${c}',false)`)).join("") + "</div>";
    if (q.free) h += q.area
      ? `<textarea id="wzFree" style="margin-top:10px;min-height:90px" placeholder="${q.free}">${(a[q.k] && !q.chips ? a[q.k] : (q.chips && a[q.k] && !q.chips.includes(a[q.k]) ? a[q.k] : "")).replace(/"/g, "&quot;")}</textarea>`
      : `<input id="wzFree" style="margin-top:10px" placeholder="${q.free}" value="${(a[q.k] && !q.chips ? a[q.k] : (q.chipKey && a[q.k]) || "").replace(/"/g, "&quot;")}">`;
    if (q.mature) h += `<label style="display:flex;align-items:center;gap:8px;cursor:pointer;margin-top:12px">
      <input type="checkbox" id="wzMature" style="width:auto" ${WD.mature ? "checked" : ""}> 🔞 含成人内容（18+）</label>`;
    body.innerHTML = h;
    $id("wzNext").textContent = q.skip && !(WD.answers[q.k] || "").trim() ? "跳过 ›" : "下一步 ›";
    const f = $id("wzFree");
    if (f && f.tagName === "INPUT") f.onkeydown = e => { if (e.key === "Enter") wzGo(1); };
  } else if (pg.t === "art") {
    body.innerHTML = `<label style="font-size:15px;color:#e7eaf3;margin-top:14px">画风</label><div>`
      + ART.map(([n]) => _chip(n, WD.art === n, `WD.art=WD.answers['画风']='${n}';wzSaveNow();wzRender()`)).join("") + `</div>
      <label style="font-size:15px;color:#e7eaf3;margin-top:14px">文风</label><div>`
      + WSTY.map(([n]) => _chip(n, WD.wsty === n, `WD.wsty=WD.answers['文风']='${n}';wzSaveNow();wzRender()`)).join("") + `</div>`;
  } else if (pg.t === "idea") {
    body.innerHTML = `<label style="font-size:15px;color:#e7eaf3;margin-top:14px">📜 故事梗概——按你的回答写的，可以直接改</label>
      <textarea id="wzIdea" style="min-height:150px">${WD.idea || ""}</textarea>
      <button class="ghost" onclick="wzIdeaGen()">✨ ${WD.idea ? "按答案重写一版" : "生成梗概"}</button>
      <span class="muted" id="wzIdeaMsg" style="font-size:12px;margin-left:8px"></span>`;
    if (!WD.idea) wzIdeaGen();
    $id("wzNext").textContent = "就按这个梗概 ›";
  } else if (pg.t === "summary") {
    body.innerHTML = `<label style="font-size:15px;color:#e7eaf3;margin-top:14px">🏔 世界概要——它是整个世界的地基，可以直接改</label>
      <textarea id="wzIdea" style="min-height:150px">${WD.idea || ""}</textarea>
      <button class="ghost" onclick="wzSummaryGen()">✨ ${WD.idea ? "按答案重铸一版" : "生成概要"}</button>
      <span class="muted" id="wzIdeaMsg" style="font-size:12px;margin-left:8px"></span>`;
    if (!WD.idea) wzSummaryGen();
    $id("wzNext").textContent = "就按这个概要 ›";
  } else if (pg.t === "outline") {
    const ol = WD.outline || [];
    body.innerHTML = `<label style="font-size:15px;color:#e7eaf3;margin-top:14px">📑 章节大纲——拓写跑偏整本报废，这一关值得把好</label>
      <div id="wzOl">${ol.map(x => `<input class="ol" style="margin-bottom:6px" value="${x.replace(/"/g, "&quot;")}">`).join("")}</div>
      <button class="ghost" onclick="wzOutlineGen()">📑 ${ol.length ? "重新生成大纲" : "生成大纲"}</button>
      <span class="muted" id="wzOlMsg" style="font-size:12px;margin-left:8px"></span>`;
    if (!ol.length) wzOutlineGen();
    $id("wzNext").textContent = "就按这个大纲 ›";
  } else if (pg.t === "sdone") {
    body.innerHTML = `<label style="font-size:15px;color:#e7eaf3;margin-top:14px">🏜 铸造</label>
      <div class="muted" style="font-size:12.5px;margin:4px 0 8px">${["题材", "年代感", "超凡体系"]
        .map(k => WD.answers[k] ? `${k}·${WD.answers[k]}` : "").filter(Boolean).join("　")}${WD.answers["分级"] === "18+" ? "　🔞" : ""}</div>
      <label>世界名</label>
      <input id="wzTitle" maxlength="24" placeholder="给这个世界起个名字" value="${(WD.title || "").replace(/"/g, "&quot;")}">
      <div style="display:flex;gap:8px"><button onclick="wzSandboxBuild()">🏜 铸造这个世界</button></div>
      <div class="muted" style="font-size:12px;margin-top:6px">铸好先只有你能玩；玩得满意，去工坊发布并把可见性改公开就能上大厅。</div>`;
    $id("wzNext").style.display = "none";
  } else {   // done (gal 成书站, 原样)
    const a = WD.answers;
    body.innerHTML = `<label style="font-size:15px;color:#e7eaf3;margin-top:14px">🎬 成书</label>
      <div class="muted" style="font-size:12.5px;margin:4px 0 8px">${["题材", "口味", "篇幅", "结局数", "画风", "文风"]
        .map(k => a[k] ? `${k}·${a[k]}` : "").filter(Boolean).join("　")}${WD.mature ? "　🔞" : ""}</div>
      <label>作品标题</label>
      <input id="wzTitle" maxlength="24" placeholder="给它起个名字" value="${(WD.title || "").replace(/"/g, "&quot;")}">
      <div style="display:flex;gap:8px">
        <button onclick="wzBuild()">🎀 开始建造成品本</button>
        <button class="ghost" onclick="wzEngine()">🧩 转成引擎本草稿</button>
      </div>
      <div class="muted" style="font-size:12px;margin-top:6px">成品本：全自动出可玩的选项式 galgame。引擎本：进工坊精修，玩真互动。</div>`;
    $id("wzNext").style.display = "none";
  }
}
function wzCollectFree() {
  const pg = wzPages()[WD.step] || {};
  if (pg.t === "q") {
    const q = pg.q, f = $id("wzFree");
    if (f && f.value.trim()) WD.answers[q.k] = f.value.trim();
    const m = $id("wzMature"); if (m) { WD.mature = m.checked; WD.answers["分级"] = m.checked ? "18+" : "全年龄"; }
  }
  if (pg.t === "idea" || pg.t === "summary") { const t = $id("wzIdea"); if (t) WD.idea = t.value.trim(); }
  if (pg.t === "outline") WD.outline = [...document.querySelectorAll("#wzOl .ol")].map(i => i.value.trim()).filter(Boolean);
}
function wzGo(dir) {
  wzCollectFree();
  const pg = wzPages()[WD.step] || {};
  if (dir > 0 && pg.t === "idea" && (WD.idea || "").length < 50) {
    $id("wzIdeaMsg").textContent = "梗概还太短——先生成或多写两句"; return;
  }
  if (dir > 0 && pg.t === "summary" && (WD.idea || "").length < 50) {
    $id("wzIdeaMsg").textContent = "概要还太薄——它是整个世界的地基"; return;
  }
  if (dir > 0 && pg.t === "outline" && (WD.outline || []).length < 2) {
    $id("wzOlMsg").textContent = "至少要两章"; return;
  }
  WD.step = Math.max(0, Math.min(wzPages().length - 1, WD.step + dir));
  wzSaveNow();
  wzRender();
}
```

（`N_ART`/`N_IDEA`/`N_OUTLINE`/`N_DONE` 四个常量删除。删除前先验证再无别处引用：
`grep -n "N_ART\|N_IDEA\|N_OUTLINE\|N_DONE" apps/api/app/static/galmaker.html`
——替换完三函数后应为 0 处命中；若有残留命中，逐处改成 `wzPages()` 语义。
`wzPick` 原样不动。）

- [ ] **Step 4: 新增 `wzSummaryGen` / `wzSandboxBuild`（放 `wzOutlineGen` 之后）**

```js
async function wzSummaryGen() {
  wzCollectFree();
  $id("wzIdeaMsg").textContent = "在铸了…（十几秒）";
  try {
    const r = await j("/stories/draft_sandbox/summary", { method: "POST",
      body: JSON.stringify({ answers: WD.answers }) });
    WD.idea = r.summary; wzSaveNow(); wzRender();   // 概要住 survey.idea 槽 — 断点续答白送
  } catch (e) { $id("wzIdeaMsg").textContent = "⚠️ " + e.message; }
}
async function wzSandboxBuild() {
  wzCollectFree();
  WD.title = ($id("wzTitle") || {}).value || WD.title;
  try {
    const jb = await j("/stories/draft_sandbox", { method: "POST",
      body: JSON.stringify({ answers: WD.answers, summary: WD.idea || "", title: WD.title }) });
    $id("wzBody").innerHTML = `<div class="muted" style="margin-top:12px">🏜 世界铸造中…（世界→人物→修为体系→自检）</div>`;
    const t = setInterval(async () => {
      try {
        const r = await j(`/stories/draft_sandbox/${jb.job}`);
        if (r.status === "done") {
          clearInterval(t);
          $id("wzBody").innerHTML = `<div style="margin-top:12px">✅ 世界已经立起来了。
            <div style="display:flex;gap:8px;margin-top:10px">
              <button onclick="location.href='/play?story=${r.story_id}'">▶️ 立刻踏入</button>
              <button class="ghost" onclick="location.href='/studio?story=${r.story_id}'">🛠 先去工坊看看</button>
            </div>
            <div class="muted" style="font-size:12px;margin-top:6px">现在只有你能玩。满意了去工坊发布并把可见性改公开，就能上大厅。</div></div>`;
        } else if (r.status === "error" || r.status === "gone") {
          clearInterval(t); alert("⚠️ " + (r.error || "任务丢了，重试一次")); wzRender();
        }
      } catch (e) { clearInterval(t); alert("⚠️ " + e.message); wzRender(); }
    }, 2500);
  } catch (e) { alert("⚠️ " + e.message); }
}
```

- [ ] **Step 5: play.html 深链（文件末尾 boot IIFE 整段替换）**

```js
// 🎬 会话自动恢复 + 🏜 深链: /play?story=<id> 直接落到那本的开局卡
// (私有沙盒不上大厅列表, owner 开自己的本走的是 runs.py:593 的放行)
(async () => {
  try {
    await afterAuth();
    const _sid = new URLSearchParams(location.search).get("story");
    if (_sid) chooseRole(_sid, "");
  } catch (e) {}
})();
```

- [ ] **Step 6: 手动验收（MockLLM 本地跑通全流程）**

```bash
cd /c/Users/17745/linguisplay/apps/api
PYTHONPATH=winshim ./.venv/Scripts/python.exe -m uvicorn app.main:app --port 8100
```
浏览器 `http://localhost:8100/maker` → 问卷 tab：
1. 第 0 题出现「造什么」，选 🏜 → 后续是沙盒题集；选修仙 → 出现「境界命名风格/宗门格局」支线；换成末世 → 支线变「威胁类型」
2. 概要站自动生成（Mock 秒回）、可编辑、重摇按钮工作
3. 铸造 → 完成双按钮 → ▶️ 跳 `/play?story=…` 直落开局卡（世界观问卷块可见 = sandbox 生效）
4. 开一局：班底召唤/开场白正常（Mock）
5. 刷新页面 → `/maker?draft=<id>` 续答，答案与概要都在
6. 老 gal 流程回归：选 🎀 → 原 6 题 + 画风 + 梗概 + 大纲 + 成书站全部照旧

- [ ] **Step 7: 提交**

```bash
cd /c/Users/17745/linguisplay
git add apps/api/app/static/galmaker.html apps/api/app/static/play.html
git commit -m "🏜 问卷向导沙盒分支: 造什么第0题+沙盒题集(题材支线)+概要确认+铸造出口; /play?story= 深链"
```

---

### Task 7: 终验门

**Files:** 无新改动（全量验证 + 推送）

- [ ] **Step 1: 全套件**

```bash
cd /c/Users/17745/linguisplay/apps/api
./.venv/Scripts/python.exe -m pytest tests -q
```
Expected: 全绿（基线 1632+新增 23 上下）。红一个修一个，谁也不许跳。

- [ ] **Step 2: 两道冒烟门**

```bash
PYTHONIOENCODING=utf-8 PYTHONPATH=winshim ./.venv/Scripts/python.exe smoke_stories.py
node smoke_client.js
```
Expected: `N/N stories clean` + `✅ 客户端冒烟门放行`

- [ ] **Step 3: 契约一致性自检**

```bash
PYTHONIOENCODING=utf-8 PYTHONPATH=winshim ./.venv/Scripts/python.exe dump_openapi.py --check
```
Expected: `✓ 契约与代码一致`

- [ ] **Step 4: 推送**

```bash
cd /c/Users/17745/linguisplay
git push origin master
```

- [ ] **Step 5: 部署（需 Yi 放行 ssh）**

```bash
ssh persona "bash /opt/linguisplay/deploy/deploy_from_git.sh"
curl -s http://106.54.1.82:8100/api/v1/health
```
线上抽验：`/maker` 走一遍沙盒问卷（真模型，一次即可），确认铸造完成、能踏入、
背景图开始排队。费用量级：一次铸造 ≈ 3 次文本调用（概要/世界/阶梯）+1 次角色卡。
