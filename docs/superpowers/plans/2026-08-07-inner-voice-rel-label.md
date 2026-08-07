# 心声深度 + 关系名牌 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 心象仪 `self_state` 随关系三轴升档为心声断片/独白并升格演出；给既有 rel_read 关系重判补变迁史、离场回归强制重判、relweb 主位名牌。

**Architecture:** 心声折在主拍（零新增调用）：relationships 出档位函数 → runtime 双钳子按档放宽并随拍下发 `mood_tier` → qwen 按档换征收描述（档 0 逐字节不变）→ Beat 落库（mood 列加宽）→ 客户端心声气泡/VN 心声框。名牌复用 rel_read 判官，只加 log、回归触发、relweb 字段。

**Tech Stack:** FastAPI + SQLAlchemy(SQLite dev / Postgres prod) + 原生 JS 单文件客户端 + pytest。

**Spec:** `docs/superpowers/specs/2026-08-07-inner-voice-rel-label-design.md`（含 ⚠️ 落地修正段）。

## Global Constraints

- 引擎源码（apps/api/app/engine/**）注释禁止出现具体剧本内容/角色名（test_engine_agnostic 守卫）。
- 档 0 的 self_state 征收描述必须与现状**逐字节一致**（前缀缓存 + 旧本零影响）。
- en 本 schema 槽位描述用英文（lang 合同）；玩家可见文案少用破折号。
- 全程 TDD：先写测试看红再实现；每任务独立提交。
- 并行会话共用工作树：**绝不 git stash**，提交只 `git add` 本任务文件。
- 本地测试命令：`cd C:/Users/17745/linguisplay/apps/api && .venv/Scripts/python.exe -m pytest`。
- **绝不 git push**（Yi 亲推）；部署=scp 改动文件 + `systemctl restart linguisplay`（Task 9 统一做）。

---

### Task 1: 档位函数 `relationships.mood_tier`

**Files:**
- Modify: `apps/api/app/engine/relationships.py`（在 `LOVER_CLOSE_MIN = 35`，~322 行后加常量；在 `new_scores` 附近加函数）
- Test: `apps/api/tests/test_inner_voice.py`（新建）

**Interfaces:**
- Produces: `relationships.mood_tier(scores: dict|None, tuning: dict|None = None) -> int`（0/1/2）；常量 `TIER1_CLOSE=60`、`TIER2_CLOSE=85`。后续任务全部以此为准。
- Consumes: 既有 `_tv(tuning, key, default)`、`FLIRT_T=25`、`LOVER_T=60`。

- [ ] **Step 1: 写失败测试**

```python
# apps/api/tests/test_inner_voice.py
"""📟 心声深度: 心象仪随关系三轴升档 (spec 2026-08-07-inner-voice-rel-label)。
档位驱动读调过的 flirt_t/lover_t (与机械门同源, 慢热本不分叉); 亲近线为深厚
非恋情关系开深档。"""
from app.engine import relationships as rel


def test_mood_tier_boundaries():
    t = rel.mood_tier
    assert t(None) == 0
    assert t({"closeness": 5, "romance": 0, "trust": 10}) == 0
    assert t({"closeness": 0, "romance": 25, "trust": 0}) == 1   # flirt_t 默认 25
    assert t({"closeness": 60, "romance": 0, "trust": 0}) == 1   # TIER1_CLOSE
    assert t({"closeness": 0, "romance": 60, "trust": 0}) == 2   # lover_t 默认 60
    assert t({"closeness": 85, "romance": 0, "trust": 0}) == 2   # TIER2_CLOSE
    assert t({"closeness": 59, "romance": 24, "trust": 99}) == 0  # 信任不开档


def test_mood_tier_respects_tuned_thresholds():
    # 慢热本调高 flirt_t/lover_t → 心声档随之慢热, 不与机械门分叉
    slow = {"flirt_t": 50, "lover_t": 90}
    assert rel.mood_tier({"closeness": 0, "romance": 25}, slow) == 0
    assert rel.mood_tier({"closeness": 0, "romance": 50}, slow) == 1
    assert rel.mood_tier({"closeness": 0, "romance": 60}, slow) == 1
    assert rel.mood_tier({"closeness": 0, "romance": 90}, slow) == 2
```

- [ ] **Step 2: 跑测试确认红**

Run: `.venv/Scripts/python.exe -m pytest tests/test_inner_voice.py -q`
Expected: FAIL `AttributeError: ... has no attribute 'mood_tier'`

- [ ] **Step 3: 实现**

在 `relationships.py` 的 `LOVER_CLOSE_MIN = 35` 之后加：

```python
# 📟 心声深度档的亲近线 (spec 2026-08-07): 挚友/生死之交这类深厚非恋情关系
# 也该有心里话 — 心动阈值走调过的 flirt_t/lover_t, 亲近线是本设计自己的常量
TIER1_CLOSE, TIER2_CLOSE = 60, 85
```

在 `new_scores_for` 之后加：

```python
def mood_tier(scores: dict[str, int] | None, tuning: dict | None = None) -> int:
    """📟 心象仪深度档: 0=短语(现状) / 1=断片 / 2=独白。只升演出深度, 不碰机械门。"""
    if not scores:
        return 0
    rom = int(scores.get("romance", 0) or 0)
    clo = int(scores.get("closeness", 0) or 0)
    if rom >= _tv(tuning, "lover_t", LOVER_T) or clo >= TIER2_CLOSE:
        return 2
    if rom >= _tv(tuning, "flirt_t", FLIRT_T) or clo >= TIER1_CLOSE:
        return 1
    return 0
```

- [ ] **Step 4: 跑测试确认绿**

Run: `.venv/Scripts/python.exe -m pytest tests/test_inner_voice.py -q` → PASS

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/engine/relationships.py apps/api/tests/test_inner_voice.py
git commit -m "📟 心声深度档位函数: 三轴→0/1/2, 心动阈值走调过的值"
```

---

### Task 2: runtime 双钳子按档 + 回喂/表情恒档 0 截断

**Files:**
- Modify: `apps/api/app/engine/runtime.py`（三处：`_carried_mood` 附近加helper；主路钳子 ~12157-12168；对质路 ~9670-9675）
- Modify: `apps/api/app/engine/director.py`（`expr_of`，~261）
- Test: `apps/api/tests/test_inner_voice.py`（追加）

**Interfaces:**
- Consumes: Task 1 的 `relationships.mood_tier`。
- Produces: `runtime.MOOD_CAPS = {0:(12,40),1:(30,80),2:(60,120)}`；`runtime._clip_mood(text, tier, en) -> str`；beat dict 新键 `b["mood_tier"]`（与 `b["mood"]` 同时下发）。`_sim(state,cid)["mood"]["text"]` 恒为档 0 截断（`_carried_mood` 因此天然短，不动它本体）。

- [ ] **Step 1: 写失败测试（追加到 test_inner_voice.py）**

```python
from app.engine import runtime


def test_clip_mood_caps_by_tier():
    long_zh = "强装镇定但心跳漏拍" * 8   # 80 字
    assert len(runtime._clip_mood(long_zh, 0, False)) == 12
    assert len(runtime._clip_mood(long_zh, 1, False)) == 30
    assert len(runtime._clip_mood(long_zh, 2, False)) == 60
    long_en = "forcing calm but heart skipping every beat " * 6
    assert len(runtime._clip_mood(long_en, 2, True)) == 120
    assert runtime._clip_mood("", 2, False) == ""
    assert runtime._clip_mood(long_zh, 99, False) == long_zh[:12]  # 未知档回落档0


def test_expr_of_reads_head_only():
    # 表情差分只认前 12 字 — 60 字独白尾部的情绪词不许误触发表情
    from app.engine import director
    calm_head = "平静地把茶杯排整齐，" + "心里翻来覆去，" * 5 + "有点怕"
    assert director.expr_of(calm_head) == director.expr_of(calm_head[:12])
```

- [ ] **Step 2: 跑测试确认红**

Run: `.venv/Scripts/python.exe -m pytest tests/test_inner_voice.py -q`
Expected: FAIL（`_clip_mood` 不存在；expr_of 断言可能红——若 `expr_of(calm_head)` 恰好等值则把尾巴换成必中词「骤然暴怒」再验红）

- [ ] **Step 3: 实现 runtime helper**

在 `_carried_mood`（~1708）上方加：

```python
# 📟 心声深度钳 (spec 2026-08-07): tier → (zh, en) 字数上限。档 0 与旧钳等值。
MOOD_CAPS = {0: (12, 40), 1: (30, 80), 2: (60, 120)}


def _clip_mood(text: str, tier: int, en: bool) -> str:
    caps = MOOD_CAPS.get(int(tier or 0), MOOD_CAPS[0])
    return (text or "").strip()[:caps[1] if en else caps[0]]
```

- [ ] **Step 4: 改主路钳子（~12157）**

把：

```python
        mood = (directed.get("self_state") or "").strip()[:40 if lang_of(content) == "en" else 12]
```

改为（`sp_id`/`tun`/`observer` 均在该循环作用域内；`relationships` 已 import）：

```python
        # 📟 按关系档放宽 (spec 2026-08-07): 观察拍恒档 0
        _mtier = 0 if observer else relationships.mood_tier(
            (state.get("rel") or {}).get(sp_id), tun)
        mood = _clip_mood(directed.get("self_state") or "", _mtier,
                          lang_of(content) == "en")
```

紧随其后的 char_sim 存续携（~12162）改为**恒档 0 截断**（深档独白永不回喂 prompt，防泄合同+模板措辞是短语式）：

```python
            _sim(state, sp_id)["mood"] = {"text": _clip_mood(mood, 0, lang_of(content) == "en"),
                                          "at": _time_index(state),
                                          "scene": _scene_tag(state)}
```

mind_reader 块（~12164）里 `b["mood"] = mood` 后同拍带档：

```python
                    b["mood"] = mood
                    b["mood_tier"] = _mtier
```

- [ ] **Step 5: 改对质路钳子（~9670，顺修既有 en 漏）**

把：

```python
    mood = (directed.get("self_state") or "").strip()[:12]
```

改为（该作用域的说话者 id 是 `char_id`）：

```python
    _mtier = relationships.mood_tier((state.get("rel") or {}).get(char_id), tun)
    mood = _clip_mood(directed.get("self_state") or "", _mtier, lang_of(content) == "en")
```

其下 `b["mood"] = mood` 后加 `b["mood_tier"] = _mtier`。

- [ ] **Step 6: director.expr_of 截断**

`director.py` `expr_of` 函数体第一行加：

```python
    mood = (mood or "")[:12]   # 📟 只认头部: 深档独白尾部的情绪词不许误触发表情
```

- [ ] **Step 7: 跑测试确认绿 + 全量回归**

Run: `.venv/Scripts/python.exe -m pytest tests/test_inner_voice.py tests/test_mindreader.py tests/test_poses.py tests/test_director.py -q` → PASS

- [ ] **Step 8: Commit**

```bash
git add apps/api/app/engine/runtime.py apps/api/app/engine/director.py apps/api/tests/test_inner_voice.py
git commit -m "📟 心声双钳按档放宽+随拍下发档位; 回喂与表情恒档0截断; 顺修对质路 en 钳漏"
```

---

### Task 3: qwen 征收描述按档分支（档 0 逐字节不变）

**Files:**
- Modify: `apps/api/app/engine/qwen.py`（`_render_tool` 的 self_state 块，~1592-1598）
- Modify: `apps/api/app/engine/runtime.py`（per-speaker prompt payload，`"relation_read"` 行 ~11841 旁加一键）
- Test: `apps/api/tests/test_inner_voice.py`（追加）

**Interfaces:**
- Consumes: prompt 新键 `mood_tier`（int，runtime 侧算好；观察拍 0）。
- Produces: 档 1/2 的 zh/en 征收描述（含真话合同、第一人称、防泄底牌条款）。

- [ ] **Step 1: 写失败测试（追加）**

```python
from app.engine import qwen

TIER0_ZH = ("三五个字：这句话说完，你【内心真实】的状态（可与表面相反），"
            "如：强装镇定、心里发虚、被戳中了、动了真情、起了杀心；平静无波就填空字符串")


def _self_state_desc(prompt):
    tool = qwen._render_tool(prompt, "甲", False, None, "say", "x")
    props = tool["function"]["parameters"]["properties"] if "function" in tool else \
        tool["parameters"]["properties"]
    return props["self_state"]["description"]


def test_tier0_description_byte_identical():
    # 🔒 回归钉: 未到档 1 的本子 prompt 逐字节不变 (前缀缓存 + 旧本零影响)
    assert _self_state_desc({"place": "巷"}) == TIER0_ZH
    assert _self_state_desc({"place": "巷", "mood_tier": 0}) == TIER0_ZH


def test_tier12_descriptions():
    d1 = _self_state_desc({"place": "巷", "mood_tier": 1})
    d2 = _self_state_desc({"place": "巷", "mood_tier": 2})
    assert "没说出口" in d1 and "真实" in d1
    assert "第一人称" in d2 and "独白" in d2
    for d in (d1, d2):
        assert "还瞒着的具体事实" in d      # 防泄底牌条款
    en = _self_state_desc({"place": "lane", "mood_tier": 2, "language": "en"})
    assert "first person" in en and "secrets" in en
```

- [ ] **Step 2: 跑测试确认红**

Run: `.venv/Scripts/python.exe -m pytest tests/test_inner_voice.py -q`
Expected: 新增三条 FAIL（现状不认 mood_tier）。若 `_render_tool` 返回结构与取法不符，按实际结构修 `_self_state_desc` 的取法（用 `str(tool)` 包含断言兜底也可），先保证红得其所。

- [ ] **Step 3: 实现 qwen 分支**

把 self_state 块（保留原 `if not is_think:` 门与 `self_intent` 不动）改为：

```python
    if not is_think:
        _mt = int(prompt.get("mood_tier") or 0)
        if _mt >= 2:
            props["self_state"] = {"type": "string", "description":
                ("First person, up to 25 English words: the true inner monologue "
                 "under this line — what you actually feel and want but keep off "
                 "your face (may contradict the surface). Stay in your own voice. "
                 "Feelings and urges only — never reveal concrete facts or secrets "
                 "you are still hiding; empty string if unruffled" if en else
                 "一小段第一人称内心独白（60字内）：这句话底下你真实的心绪——想要什么、"
                 "怕什么、没说出口的那句是什么，可与表面完全相反，用你自己的口吻写。"
                 "只写感受与冲动，绝不把你还瞒着的具体事实/秘密写进来；平静无波就填空字符串")}
        elif _mt == 1:
            props["self_state"] = {"type": "string", "description":
                ("One or two short sentences (≤18 English words): the words under "
                 "your words — the true feeling you keep to yourself this line "
                 "(may contradict the surface). Feelings only — never reveal "
                 "concrete facts or secrets you are still hiding; empty string "
                 "if unruffled" if en else
                 "一两句没说出口的话（30字内）：这句话底下你真实的心声，可与表面相反"
                 "（嘴上拒绝心里舍不得）。只写感受，绝不把你还瞒着的具体事实/秘密写进来；"
                 "平静无波就填空字符串")}
        else:
            props["self_state"] = {"type": "string", "description":
                ("3-6 English words: your TRUE inner state after this line (may "
                 "contradict the surface), e.g. forcing calm, caught off guard, "
                 "genuinely moved; empty string if unruffled" if en else
                 "三五个字：这句话说完，你【内心真实】的状态（可与表面相反），"
                 "如：强装镇定、心里发虚、被戳中了、动了真情、起了杀心；平静无波就填空字符串")}
```

⚠️ 档 0 两段文案**从现文件原样复制**，一个字节都不许动（测试钉着）。关系风味不在这里注入——系统 prompt 的 relation_read 块（qwen ~1405-1417）已带「你跟TA现在是【X】」。

- [ ] **Step 4: runtime 侧供 mood_tier**

per-speaker payload（`"relation_read"` 行 ~11841 旁）加：

```python
            # 📟 心声深度档 (spec 2026-08-07): 观察拍恒 0
            "mood_tier": 0 if observer else relationships.mood_tier(
                rel_all.get(sp_id), tun),
```

（对质路 llm.generate payload ~9631 同样加 `"mood_tier": relationships.mood_tier((state.get("rel") or {}).get(char_id), tun),`。）

- [ ] **Step 5: 跑测试确认绿 + 全量**

Run: `.venv/Scripts/python.exe -m pytest tests/test_inner_voice.py tests/test_plan_render.py tests/test_language.py -q` → PASS

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/engine/qwen.py apps/api/app/engine/runtime.py apps/api/tests/test_inner_voice.py
git commit -m "📟 心声征收描述按档分支(zh/en, 防泄条款), 档0逐字节回归钉"
```

---

### Task 4: Beat 落库（mood 加宽 + mood_tier 列）

**Files:**
- Modify: `apps/api/app/models.py`（Beat.mood ~322）
- Modify: `apps/api/app/schemas.py`（Beat schema ~671-678）
- Modify: `apps/api/app/db.py`（`_ensure_columns` ~105-115 后加加宽段）
- Modify: `apps/api/app/routers/runs.py`（两处 BeatModel 写入：~1103-1107 与 ~1996-2000）
- Test: `apps/api/tests/test_inner_voice.py`（追加）

**Interfaces:**
- Produces: `Beat.mood: String(160)`；`Beat.mood_tier: SmallInteger|None`；schemas.Beat 新字段 `mood_tier`；SSE beat 事件与回想重建自动携带（`_to_beat` 走 ORM→schema）。

- [ ] **Step 1: 写失败测试（追加）**

```python
def test_beat_mood_column_wide_and_tier(tmp_path):
    from app import models
    assert models.Beat.__table__.c.mood.type.length >= 160, \
        "深档独白 60 字 UTF-8 下 String(24) 必炸 Postgres"
    assert "mood_tier" in models.Beat.__table__.c
    from app import schemas
    assert "mood_tier" in schemas.Beat.model_fields
```

- [ ] **Step 2: 跑测试确认红** → FAIL（length 24 / 无列）

- [ ] **Step 3: 实现**

models.py Beat：`mood` 列 `String(24)` → `String(160)`；其下加：

```python
    mood_tier: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
```

（`SmallInteger` 从 sqlalchemy import，文件顶部已有的 import 行追加。）

schemas.py Beat（mood 字段旁）加：

```python
    mood_tier: Optional[int] = None
```

db.py `_ensure_columns` 加列循环之后（仍在 `for table` 循环体内，与加列平级）追加：

```python
            # 📟 2026-08-07 心声深档: beats.mood 24→160。SQLite 不校验长度可不管;
            # Postgres 必须显式加宽, 否则深档插入 StringDataRightTruncation。幂等。
            if table.name == "beats" and "mood" in existing \
                    and engine.dialect.name.startswith("postgres"):
                try:
                    conn.execute(text(
                        "ALTER TABLE beats ALTER COLUMN mood TYPE VARCHAR(160)"))
                except Exception as e:
                    print(f"[schema] cannot widen beats.mood: {e}", file=sys.stderr)
```

runs.py 两处 `BeatModel(...)` 构造（~1103 与 ~1996）各加一参：

```python
                        mood_tier=payload.get("mood_tier"),
```

- [ ] **Step 4: 跑测试确认绿 + 全量**

Run: `.venv/Scripts/python.exe -m pytest tests/test_inner_voice.py -q && .venv/Scripts/python.exe -m pytest -q` → PASS

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/models.py apps/api/app/schemas.py apps/api/app/db.py apps/api/app/routers/runs.py apps/api/tests/test_inner_voice.py
git commit -m "📟 Beat.mood 24→160 + mood_tier 列/schema字段/双写入点; Postgres 幂等加宽"
```

---

### Task 5: 客户端演出（心声气泡 + VN 心声框）

**Files:**
- Modify: `apps/api/app/static/play.html`（CSS `.mood` 定义 ~646 旁；`attachMood` ~2487 旁加 helper；两处 attachMood 调用点：renderBeat ~2378 区、流式路 ~5535 区；`playBeatVN` ~5416）

**Interfaces:**
- Consumes: beat JSON 的 `mood` + `mood_tier`（Task 4 起流上与回想都带）。
- Produces: `attachInner(node, name, mood)`；`#vniv` 心声框；CSS `.ivrow`/`.vniv`。

- [ ] **Step 1: CSS（`.mood` 规则旁追加）**

```css
.ivrow{margin:2px 8px 8px 44px;padding:7px 10px;border-radius:10px;background:rgba(140,140,180,.13);font-style:italic;opacity:.85;font-size:12.5px;line-height:1.55;white-space:pre-wrap}
.ivrow .ivtag{opacity:.6;font-style:normal;font-size:10.5px;margin-right:4px}
.vniv{position:relative;margin:6px 12px 0;padding:8px 12px;border-radius:10px;background:rgba(20,20,34,.55);font-style:italic;opacity:.9;font-size:13px;line-height:1.55}
.vniv .ivtag{opacity:.65;font-style:normal;font-size:10.5px;margin-right:4px}
```

- [ ] **Step 2: helper（attachMood 函数后）**

```js
// 💭 心声气泡 (spec 2026-08-07): 深档独白升格为独立行, 与台词视觉分开
function attachInner(node, name, mood) {
  const d = document.createElement("div"); d.className = "ivrow";
  d.innerHTML = `<span class="ivtag">💭 ${escapeHtml(name || "")}的心声</span>${escapeHtml(mood)}`;
  node.insertAdjacentElement("afterend", d);
}
```

- [ ] **Step 3: 两处调用点分流**

Grep `attachMood(` 找到两处调用（回想重建 renderBeat 内、流式路 ~5535）。每处把
`attachMood(<node>, <mood>)` 改为：

```js
if (((b.mood_tier | 0) >= 1)) attachInner(<node>, b.speaker_name, b.mood);
else attachMood(<node>, <mood>);
```

（`<node>`/`<mood>`/`b` 用各调用点实际变量名，别照抄。）

- [ ] **Step 4: VN 心声框（playBeatVN）**

在 `playBeatVN` NPC 分支的正文渲染完成处（函数末段，台词/旁白已上屏后）追加；同时在玩家分支（`b.author === "player"` 早退前）与 NPC 分支开头都先清旧框：

```js
  const _oiv = document.getElementById("vniv"); if (_oiv) _oiv.remove();
```

NPC 台词拍（`!isNarr`）渲染完后：

```js
  if (!isNarr && b.mood && ((b.mood_tier | 0) >= 1)) {
    const iv = document.createElement("div"); iv.id = "vniv"; iv.className = "vniv";
    iv.innerHTML = `<span class="ivtag">💭 心声</span>${escapeHtml(b.mood)}`;
    document.getElementById("vnbox").appendChild(iv);
  }
```

- [ ] **Step 5: 客户端冒烟门**

Run: `cd apps/api && node smoke_client.js` → 27/27 放行且零 JS 报错（若门里有 DOM 快照类断言被新行影响，按报错修断言而不是删功能）。

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/static/play.html
git commit -m "💭 心声气泡+VN心声框: mood_tier>=1 升格独立行, 档0维持现状小字"
```

---

### Task 6: rel_read 变迁史（名牌 log）

**Files:**
- Modify: `apps/api/app/engine/runtime.py`（`apply_relation_read` ~13406-13425）
- Test: `apps/api/tests/test_inner_voice.py`（追加）

**Interfaces:**
- Produces: `state["rel_label_log"][cid] = [{"at","old","new","why"}]`（capped 10）。**旁账本**——绝不放进 `state["rel"][cid]`（`apply_deltas` 每拍整槽重建那个 dict，放那必丢）。

- [ ] **Step 1: 写失败测试（追加）**

```python
def test_rel_read_mode_change_logs_history():
    st = runtime.default_state()
    st["met_ids"] = ["c9"]
    runtime.apply_relation_read(st, "c9", {"mode": "点头之交", "feeling": "还行", "why": "递过烟"}, at=3)
    runtime.apply_relation_read(st, "c9", {"mode": "点头之交", "feeling": "熟了", "why": "又聊过"}, at=9)
    runtime.apply_relation_read(st, "c9", {"mode": "欢喜冤家", "feeling": "嘴硬", "why": "斗嘴三回"}, at=15)
    log = st["rel_label_log"]["c9"]
    assert [e["new"] for e in log] == ["点头之交", "欢喜冤家"]   # 同名不重复记
    assert log[0]["old"] == "" and log[1]["old"] == "点头之交"
    # 🔒 apply_deltas 整槽重建 rel[cid] 也抹不掉旁账本 (对抗性核查抓过的雷)
    from app.engine import relationships as rel
    st["rel"] = {"c9": rel.new_scores()}
    st["rel"]["c9"] = rel.apply_deltas(st["rel"]["c9"], 5, 2, {})
    assert st["rel_label_log"]["c9"] == log


def test_rel_label_log_capped_10():
    st = runtime.default_state()
    st["met_ids"] = ["c9"]
    for i in range(14):
        runtime.apply_relation_read(st, "c9", {"mode": f"阶段{i}", "feeling": "x", "why": "y"}, at=i)
    assert len(st["rel_label_log"]["c9"]) == 10
    assert st["rel_label_log"]["c9"][-1]["new"] == "阶段13"
```

- [ ] **Step 2: 跑测试确认红** → FAIL（无 rel_label_log）

（若 `apply_deltas` 实参形状不符——它的签名按 relationships.py 实文件为准——只调测试里那两行调用方式，断言不变。）

- [ ] **Step 3: 实现**

`apply_relation_read` 在 `state.setdefault("rel_read", {})[cid] = row` 之前加：

```python
    # 🏷 名牌变迁史 (spec 2026-08-07): 判读换了名才记一笔; 旁账本, apply_deltas 抹不到
    prev = str(((state.get("rel_read") or {}).get(cid) or {}).get("mode") or "")
    if mode and mode != prev:
        lg = state.setdefault("rel_label_log", {}).setdefault(cid, [])
        lg.append({"at": row["at"], "old": prev, "new": mode, "why": row["why"]})
        del lg[:-10]
```

- [ ] **Step 4: 跑测试确认绿** → PASS

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/engine/runtime.py apps/api/tests/test_inner_voice.py
git commit -m "🏷 关系名牌变迁史: rel_read 换名记旁账本, cap 10, apply_deltas 抹不掉"
```

---

### Task 7: 离场回归强制重判

**Files:**
- Modify: `apps/api/app/engine/runtime.py`（常量区 ~13356；due 过滤 ~12968-12972）
- Test: `apps/api/tests/test_inner_voice.py`（追加）

**Interfaces:**
- Produces: `runtime.LABEL_GAP_H = 0.5`；`relation_read_due_now(state, cid, turn, away_hours) -> bool`。
- Consumes: run_turn_stream 作用域内已有的 `away_hours`（路由 ~1004 算好传入；在 12968 附近 Grep `away_hours` 绑定实际局部名）。

- [ ] **Step 1: 写失败测试（追加）**

```python
def test_return_turn_forces_relation_read():
    st = runtime.default_state()
    st["met_ids"] = ["c9"]
    st["rel_read"] = {"c9": {"mode": "点头之交", "at": 10}}
    # 节奏未到期 (RELREAD_EVERY=6, turn=12 距 10 只差 2) → 平时不判
    assert runtime.relation_read_due_now(st, "c9", 12, away_hours=0.0) is False
    # 离开 ≥ 0.5h 回来 → 强制到期 (Yi: 离开/久不发消息作为总结)
    assert runtime.relation_read_due_now(st, "c9", 12, away_hours=0.6) is True
    # 从没判过的照旧走首判节奏
    assert runtime.relation_read_due_now(st, "cX", 3, away_hours=0.0) is False  # 没 met
```

- [ ] **Step 2: 跑测试确认红** → FAIL（函数不存在）

- [ ] **Step 3: 实现**

常量区（`RELREAD_EVERY` 旁）加：

```python
LABEL_GAP_H = 0.5   # 🏷 离场超过这个时长回来 → 关系重判强制到期 (Yi: 离开即总结)
```

`relation_read_due` 之后加：

```python
def relation_read_due_now(state: dict[str, Any], cid: str | None, turn: int,
                          away_hours: float = 0.0) -> bool:
    """🏷 到期判定带回归触发: 离场 ≥ LABEL_GAP_H 小时后的第一拍, 聊过的人一律重判
    (那一段的账该结了); 平时走 relation_read_due 的节奏。"""
    if not cid or cid not in set(state.get("met_ids") or []):
        return False
    if float(away_hours or 0) >= LABEL_GAP_H:
        return True
    return relation_read_due(state, cid, turn)
```

due 过滤（~12969-12970）把 `relation_read_due(state, cid, _n)` 换成
`relation_read_due_now(state, cid, _n, away_hours=<该作用域的 away_hours 局部名>)`
（Grep 确认局部名；若该作用域确实没有，就近从 run_turn_stream 形参线程过来——路由已传）。

- [ ] **Step 4: 跑测试确认绿 + 全量** → PASS

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/engine/runtime.py apps/api/tests/test_inner_voice.py
git commit -m "🏷 离场≥0.5h回归拍强制关系重判: 离开那段的账回来即结"
```

---

### Task 8: relweb 名牌主位 + 变迁史下发/渲染

**Files:**
- Modify: `apps/api/app/routers/runs.py`（relweb 玩家边 view 组装 ~2182-2196）
- Modify: `apps/api/app/static/play.html`（玩家边展示点：Grep `mode_name`，约 5211/5259/5303/5364 四处；边详情渲染 `p.recent` 处追加变迁史）
- Test: `apps/api/tests/test_inner_voice.py`（追加）

**Interfaces:**
- Produces: relweb player edge 新字段 `label`（str，判读 mode 优先，回落 mode_name）、`label_log`（尾 4 条）。

- [ ] **Step 1: 写失败测试（追加；relweb 有既有测试文件的话挂那边同款夹具更省）**

```python
def test_relweb_player_edge_carries_label(client_with_run):
    # client_with_run: 项目既有 relweb 测试的夹具名为准 (Grep tests/ 里 "relweb")。
    # 断言目标: 有 rel_read.mode 的角色 label==judged mode; 没有的回落 mode_name;
    # label_log 是 rel_label_log 尾 4 条。夹具铺法:
    #   st["rel_read"] = {"c1": {"mode": "欢喜冤家", "at": 5}}
    #   st["rel_label_log"] = {"c1": [{"at":5,"old":"","new":"欢喜冤家","why":"斗嘴"}]}
    r = client_with_run.get(f"/api/v1/runs/{run_id}/relweb").json()
    edge = next(e for e in r["player"] if e["id"] == "c1")
    assert edge["label"] == "欢喜冤家"
    assert edge["label_log"][-1]["new"] == "欢喜冤家"
```

（以 `apps/api/tests/` 中既有 relweb 测试的夹具与响应形状为准改写：Grep `relweb` 先看有没有现成测试文件，有就追加用例，没有就照它们的 client 夹具惯例新建。红了再进下一步。）

- [ ] **Step 2: 跑测试确认红**

- [ ] **Step 3: runs.py 实现**

relweb 玩家边循环里，`view["read_mode"]` 判断之后加：

```python
        # 🏷 名牌主位 (spec 2026-08-07): 开放词汇的判读盖过枚举词, 没判过回落枚举
        view["label"] = (_rr.get("mode") or view.get("mode_name") or "")
        view["label_log"] = list((st.get("rel_label_log") or {}).get(c["id"]) or [])[-4:]
```

- [ ] **Step 4: play.html 实现**

Grep `mode_name` 的玩家边渲染点（约四处），显示表达式改为 `(p.label || p.mode_name)`；
边详情渲染 `p.recent` 的地方之后追加：

```js
if (p.label_log && p.label_log.length) {
  const h = p.label_log.map(e => `${escapeHtml(e.old || "初识")} → ${escapeHtml(e.new)}${e.why ? `（${escapeHtml(e.why)}）` : ""}`).join("<br>");
  box.insertAdjacentHTML("beforeend", `<div class="rl-hist">🏷 ${h}</div>`);
}
```

（`box` 用该渲染点实际容器变量名；`.rl-hist` CSS：`opacity:.7;font-size:11px;margin-top:4px;line-height:1.5`。）

- [ ] **Step 5: 跑测试确认绿 + 客户端门**

Run: pytest 全量 + `node smoke_client.js` → PASS/27绿

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/routers/runs.py apps/api/app/static/play.html apps/api/tests/test_inner_voice.py
git commit -m "🏷 relweb 名牌主位+变迁史下发渲染: 开放词汇盖枚举, 回落有底"
```

---

### Task 9: 门禁、部署、真机验收

**Files:** 无新改动（只跑门与部署）

- [ ] **Step 1: 全量门**

```bash
cd apps/api
.venv/Scripts/python.exe -m pytest -q          # 全绿（基线 1331+，允许既有 3 skip）
.venv/Scripts/python.exe smoke_stories.py      # 5/5
node smoke_client.js                            # 27/27
```

任何红都先修再往下走（superpowers 铁律：完成前验证）。

- [ ] **Step 2: 部署（scp + restart，不 push）**

```bash
cd C:/Users/17745/linguisplay
scp apps/api/app/engine/runtime.py apps/api/app/engine/relationships.py apps/api/app/engine/qwen.py apps/api/app/engine/director.py root@106.54.1.82:/opt/linguisplay/apps/api/app/engine/
scp apps/api/app/models.py apps/api/app/schemas.py apps/api/app/db.py root@106.54.1.82:/opt/linguisplay/apps/api/app/
scp apps/api/app/routers/runs.py root@106.54.1.82:/opt/linguisplay/apps/api/app/routers/
scp apps/api/app/static/play.html root@106.54.1.82:/opt/linguisplay/apps/api/app/static/
ssh root@106.54.1.82 "systemctl restart linguisplay && sleep 4 && curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8100/api/v1/health"
```

部署后立刻查启动日志有无 `[schema]` 报警（列加宽/加列失败必须喊）：
`ssh root@106.54.1.82 "journalctl -u linguisplay -n 40 | grep -i schema"`（无输出=干净）。

- [ ] **Step 3: 真机验收（linguisplay:verify 配方）**

- 测试号专用档（复用 pw/ harness）：进档、发一拍、断言零 JS 报错、档 0 心象仪照旧。
- 深档演出：用自己的专用档，服务器上只读查出 run id 后把**自己档**的
  `state.rel[主角色id]` 的 romance 置 70（sqlite UPDATE 只动自己的验证档一行），
  发一拍，断言 beat 带 `mood_tier=2`、聊天流出现 `.ivrow`、VN 模式出 `#vniv`。
- 名牌：同档等 rel_read 判官落账后开 relweb，断言边上 `label` 非枚举词兜底、
  变迁史行出现；再造一次 ≥0.5h 间隔（改 beats 最后一条 created_at 往前拨 1 小时，
  同样只动自己的验证档）回归发拍，断言 rel_read 被强制重判（audit/日志或 at 变化）。
- 全程 `journalctl -u linguisplay | grep CLIENT-JS` 零报错。

- [ ] **Step 4: 收尾**

BUGS.md 无新增欠账则不动；更新记忆（linguisplay 相关条目）；向 Yi 汇报（含成本）。
**不 push——Yi 亲推。**

---

## Self-Review 已跑

- Spec 覆盖：§2 全部落在 Task 1-5；§3 差量落在 Task 6-8（判官/异步/风味复用既有 rel_read，见 spec ⚠️ 修正段）；§4 验收=各任务 Step + Task 9；§5/§6 无需代码。
- 占位符扫描：Task 8 Step 1 的夹具名依赖既有测试惯例，已注明「Grep relweb 先看现成夹具」并给出铺数据与断言目标——是探查指令不是 TBD。
- 类型一致性：`mood_tier` int 贯穿（schema prompt 键 → beat dict → ORM SmallInteger → schemas Optional[int] → 客户端 `|0`）；`_clip_mood(text, tier, en)` 与 `MOOD_CAPS` 各任务签名一致；`rel_label_log` 结构 Task 6/8 一致。
