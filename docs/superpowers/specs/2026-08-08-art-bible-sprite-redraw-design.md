# 画风圣经 + 立绘两式重画（编辑器）设计稿

日期：2026-08-08 ｜ 状态：Yi 已拍板方案一 ｜ 前置调研：本文全部落点均已对照现有代码核实

## 要解决什么

1. 编辑剧本（studio.html）里立绘只能上传，没有 AI 重画入口；生立绘只能上服务器手跑 enrich_tachie.py。
2. 角色和背景画风不咬合（樱见坂实锤：四个角色三种画风、背景另一种）。现有一致性机制是文字级的一条画风串 + 固定种子，缺圣经分段和外貌钉死两味药——这两味在浮生的离线脚本里已验证有效，但编辑器和剧本数据层没有。

## 机制总纲

咬合的机制 = 全剧本一本「画风圣经」，所有出图口从同一本圣经取词：

- 圣经住 `tuning.art_style`（不加新字段），沿浮生法统一条字符串按 `；舞台` 分两段。
- 立绘/头像口吃画风段（`art.split("；舞台")[0]`，enrich_tachie 已是此协议）。
- 背景口优先吃舞台段，没有则回落整条（`_bg_prompt` 改造，运行时补图/玩家重画/工坊手点三条路共用此函数，改一处全生效）。
- 引擎只认 `；舞台` 分隔协议，不认具体内容（story-agnostic 家规）。
- `art_style_of` 现有 200 字截断会拦腰砍圣经：生图路径改为先取段再限长。

## 改动清单

### 1. 数据层

- `schemas.py` Character 加 `looks: Optional[str]`（外貌，纯生成用，play 永不读）
  和 `face_salt: Optional[int]`（种子位移，见改动清单 3；同为生成专用）。
  ⚠️ 这条有时效压力：schema 不认识的键会在编辑器保存时被 Pydantic 剥掉。
  2026-08-08 已经往樱见坂四个角色的 DB 数据里写了 looks，schema 不补字段，
  Yi 在 studio 里一保存这四条就蒸发。**此项应最先落地。**
- 编辑器角色卡「更多」里加 looks 小文本框（占位提示：发型/服装/道具，写长相不写性格）。

### 2. 圣经生成

- `POST /stories/{id}/gen_bible`：LLM 从 world_long + 现有 art_style 产出
  「画风段；舞台：舞台段」写回 `tuning.art_style`。
- studio 画风输入框旁加「✨ 生成画风圣经」，已有内容时点击 = 重写，弹确认。

### 3. 立绘两式（studio 立绘区每行两键）

- `POST /stories/{id}/gen_sprite/{cid}`，body `{mode: "fresh" | "restyle"}`：
  - **fresh**：t2i 出生。Seedream 928*1664（enrich_tachie 同款 TACHIE_MODEL/SIZE）、
    圣经画风段前置 + looks（缺 looks 时回落 persona_text 前 120 字并在响应里提示
    「建议先写外貌」）、邻近流派负词（enrich_tachie 的 _STYLE_NEG / _REAL_NEG
    搬进引擎共用）。
  - **种子纪律（浮生 SEED_SALT 的数据化）**：角色加持久化字段 `face_salt: int`
    （默认 0，不存在视为 0）。每次 fresh 重画 salt+1，种子 =
    `char_seed(sid, cid + (salt and f"-r{salt}"))`——确定性、可复现，且每次重画
    真的换一张（治「同种同词原样重印」）。新 salt 即该角色新正史：引擎所有拿
    char_seed 的口（工坊头像、运行时补脸）一律经同一个助手 `char_seed_of(story, char)`
    取种，杜绝两条管线两张脸。restyle 不动 salt（它以现图为底，无种子参与）。
  - **restyle**：现有底图（sprite _src 优先，enrich_tachie 的 base_of 顺位）走
    `edit_image` 改进圣经画风段，保脸保姿势只换风格（--restyle 的按钮化，
    改绘铁律措辞照抄：保真条款最前，画风只给一句核心）。
- 落图：进图片队列后 → `ingest_upload`（透底立绘 + 改脸源图 + 方形头像三件套，
  旧表情差分自动作废），差分照旧懒生成，不在重画请求里同步做。
- 队列：`_IMG_Q` 队列项加可选 base 图路径字段支持 restyle；`_IMG_PENDING` 去重照旧。
- 共享脸保护：cid 在 ipface 共享清单（cyclone 那批）时 endpoint 拒绝 + 按钮置灰。

### 4. 背景咬合

- `_bg_prompt` 改读舞台段（见总纲）。`tuning.bg_style` 仍然最高优先（背景专用画风
  的既有约定不动）。

### 5. 守门与限流

- 鉴权沿用 `_own_story`。
- 每角色每分钟一次重画（防连点烧钱），排队中再点返回「已在排队」。

### 6. 测试

- 纯函数单测：圣经分段（有`；舞台`取段/无则回落/截断不砍圣经）、fresh/restyle
  提示词组装、looks 回落链、负词组装。
- endpoint 单测：404/鉴权/共享脸拒绝/限流/去重。
- schema 单测：looks 字段 round-trip（编辑器保存不丢）。
- 部署前三道门照过，最后 linguisplay:verify 真机点一遍编辑器两键。

## 不做（YAGNI）

人景互喂 i2i、每地点独立画风、圣经版本管理、批量全员一键重画、表情差分改动。

## 实弹依据（2026-08-08 樱见坂重生成的教训，实现时别再踩）

- 没有 looks 时 enrich_tachie 拿 persona_text 凑数，画笔要的是长相不是性格——
  looks 字段是质量的一半。
- 立绘 seed 固定：不改词 --force 等于原样重印（白花钱）。fresh 模式的 face_salt
  纪律（见改动清单 3）就是为此设的；背景的 `time % 991 + 1` 手法不适用于角色，
  因为那是非确定性的，而脸必须可复现。
- 背景乱码假字：圣经尾部的「没有文字」铁律必须保留在 `_bg_prompt` 句尾。
