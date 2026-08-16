# 问卷造沙盒本（UGC）设计

日期：2026-08-16 ｜ 状态：已批准（Yi 拍板：玩家 UGC / 固定骨架+题材支线 / 答完即可玩、满意再公开 / 方案 A）

## 背景

玩家在工坊答一张问卷，引擎按答案铸出一个**可玩的沙盒本**（私有），玩家立刻开局；
玩得满意再一键公开上大厅。

侦察底账（2026-08-16，5 读者并行核实过的现状）：

- galmaker 问卷向导（paneC/wz* 系列）已全量在线：一屏一问、chips 快选、350ms 防抖
  PATCH 落库、断点续答、梗概确认环。`answers` 是自由 dict，**前端加题后端零改动**
  （gal.py:189-213, galmaker.html:143-324）
- 现有「🧩 转引擎本」出口**有损**：只传 idea+title，结构化答案全丢（galmaker.html:313-314）
- `draft_engine` 三个 prompt **都不产 sandbox 字段**，起草物永远是作者本（stories.py:525-536）
- 沙盒九键由引擎读法定义：`enabled / real_time / currency / start_money / era /
  progression{name,ranks} / default_powers / opening_visitor / start_location`；
  **linter 对 sandbox 零校验**，形状错=修为系统静默失效（runtime.py:9023-9028）
- 修为阶梯已有现成生成 prompt `_gen_progression`（qwen.py:5303-5327）
- 落库 private + 作者手动公开是现状机制 —— 「先玩后发」几乎白送（stories.py:234）

## 方案（已拍板 A）

长在 galmaker 问卷向导上：加一套**沙盒题目集**（QS 配置表）+ 一个**「🏜 建造沙盒」出口**。
不新建向导页（无组件可复用，抄一遍是纯重复劳动）；不走「只修有损出口」的最小改
（gal 题目问不出沙盒的魂）。

## 1. 问卷（前端 galmaker.html）

**主干 6 题**（固定）：

1. 题材：修仙 / 都市异能 / 西幻 / 末世 / 宫斗 / 星际 + 自由填（chips）
2. 世界观：一段话（textarea，给足 placeholder 示范）
3. 年代感：自由填 ≤60 字（「1899 清末 / 三千年后的星港 / 盛唐」）
4. 超凡体系：无 / 有+叫什么（斗气、灵力、军衔……）
5. 主角开局处境 + 金手指 0~4 条（一行一条）
6. 尺度：🔞 开关

**题材支线 2~3 题**：QS 数组加 `branch` 字段，wzRender 按第 1 题答案过滤显示。
纯前端配置表，**不烧 LLM**。示例：修仙→境界命名风格/宗门格局；末世→威胁类型；
宫斗→朝局派系。

**确认环**：答完生成「世界概要」，可改可重摇（复用梗概站交互模式，走新 prompt）。

**末步三出口**：🎀 gal 成品本（现状）/ 🧩 转引擎本（现状）/ **🏜 建造沙盒（新）**。

问卷草稿沿用 gal 域存储（Story kind=gal, gal.status='survey'，断点续答照旧）；
「建造沙盒」出口产出的是**一个新的引擎本 Story 行**，与 wzEngine 同构但**无损**：
结构化 answers 全量随行。

## 2. API（新）

```
POST /api/v1/stories/draft_sandbox   {answers: dict, title?: str}  → {job}
GET  /api/v1/stories/draft_sandbox/{job_id}                        → {status, story_id?}
```

job 沿用 `_PARSE_JOBS` 内存台账（单进程局限照旧接受，见非目标）。

## 3. 生成管线（服务端，engine 侧新增 sandbox 起草步骤）

1. **世界铸造**（新 prompt `sandbox_world`）：answers → title / one_liner / synopsis /
   world_long / world_facts(≤400) / era(≤60) / **style**。style 严格按结构约定：
   **作者腔在头 + 长度条款与忌清单在尾**（qwen.py:63-93 靠此布局保头保尾截断）
2. **角色与地点**：复用 `char_from_text`（喂世界铸造产物）出 4~6 张卡；
   地点 3~4 个 + `start_location`；指定其一角色为 `opening_visitor`
3. **沙盒件组装**（确定性映射，不烧 LLM 的部分不烧）：
   - `enabled=True`，`real_time=True`（默认）
   - `currency` / `start_money`：按题材+答案映射（修仙→灵石，都市→元…）
   - `progression`：超凡体系答「有」→ 复用 `_gen_progression`；答「无」→ 不写
     （开局 `ensure_progression` 的兜底逻辑保持不动）
   - `default_powers`：金手指答案**每条压 ≤40 字**（runs.py:676-679 开档截断），
     长解释挪进 world_facts
4. **沙盒惯例**：单幕 ONE_ACT、`endings=[]`、
   phone 按年代确定性映射：现代/近未来 → `{enabled:True, device:'手机'}`，
   古代/异界无通讯设定 → `{enabled:False}`（世界铸造 prompt 顺带产一个
   `tech_level: modern|ancient|future` 枚举供映射，不再单独烧一步）、
   `tuning._origin='survey_sandbox'` + `_draft_size` 埋点
5. **sandbox 形状校验器**（新，放 engine/logic.py）：linter 对 sandbox 零校验是坑，
   这道闸生成器自己立 —— progression 必须 name 非空 + 4≤ranks≤12 每级≤8字；
   `opening_visitor` 必须指向真角色；`start_location` 必须存在；`default_powers`
   ≤4 条各≤40字。**违规确定性修剪**（裁掉/回落），不报错不打断
6. lint → 确定性降级闭环（复用 draft_engine 现有 ≤2 轮）→ 落库 `visibility='private'`

v1 **只做中文本**：修炼指令识别正则只认中文（runtime.py:9006-9020），
英文沙盒修为练不动，不给自己埋雷。

## 4. 交付体验

job 完成 → 前端给两个按钮：**▶️ 立刻开玩**（跳 /play 进开局卡）/ 🛠 去工坊精修。
沙盒开局的班底召唤/开场白/背景排队全是现成管线，零新做。
美术：背景照现有开局异步排队；封面自动合成（不生图）；**立绘不自动生成**（省钱，
作者可在工坊手动 gen_avatar）。

## 5. 闸门

- 每人每日 `draft_sandbox` **3 次**，超出 429（按 owner 当日计数）
- 同人同时在建 1 个 job
- 问卷草稿不占 gal beta 配额（现状不变）
- `_edit_ratio` 起草即发布降权照旧生效

## 6. 测试（TDD）

- 形状校验器单测（先红：喂坏 progression/悬空 visitor，断言修剪结果）
- `draft_sandbox` 端点 MockLLM e2e：落库形状全断言（九键、单幕、endings=[]、
  private、lint 零 error、powers ≤40字）
- 配额 429 用例；MockLLM 孪生与真 prompt **同构合同**测试
  （侦察实锤：两边曾不同构 → 测试绿真机歪）
- 全套件回归 + smoke_stories + smoke_client 放行后才部署

## 非目标

- 英文沙盒、立绘自动生成、AI 动态追问（支线=配置表）、多视角
- `_PARSE_JOBS` 多进程改造（沿用现状与其局限：重启丢 job、cap=40 逐出）

## 风险

- style 结构不守 → 截断切丢忌清单：prompt 里写死输出格式并在组装层校验
- mock/真 prompt 漂移：合同测试双向断言字段面
- 同质本灌水：private 默认 + 每日 3 次 + `_edit_ratio` 三重压制，先观察再加闸
