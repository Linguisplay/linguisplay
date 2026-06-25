# LinguisPlay · 现有后端 → 新架构 迁移评估

> 配套文档：`SCREENS.md`(MVP 范围与屏幕清单)、`openapi.yaml`(契约 v0)
> 现状参照：线上 demo 后端 `/opt/persona`（FastAPI + SQLite，单体），见根 `backend/`

## 一句话结论

这是一次**重写 `apps/api`**，不是在现有后端上加功能。但现有后端是一个**已验证核心玩法的活原型**，当作"代码素材库 + 参考实现"来挖，而非增量改造的地基。

三个硬伤级理由：

1. **存储引擎换底**：SQLite → Postgres + pgvector + Redis。门控 RAG 的 fragment 语义检索依赖 pgvector，绕不开。
2. **领域模型根本不同**：现有 `persona / world / group / messages` → 目标 `Story → Run → 门控 secrets/fragments`，run 键 = (user, persona, story_version)，发布即快照。
3. **契约先行**：先冻结 `openapi.yaml`，前后端照同一份并行。起点是从契约长出新 `apps/api`。

**现有后端别停**：继续作为线上 demo，新 `apps/api` 在 monorepo 另起，并行直到可切换。

## 资产清单：每块现有代码的去向

| 现有资产 | 去向 | 说明 |
|---|---|---|
| Auth(register/login/JWT/bcrypt) | ✅ 直接搬 | 改 httpOnly cookie + DOB 门 |
| 用户数据隔离(owner 列 + 校验) | ✅ 概念搬 | Postgres 改外键 + row 归属 |
| `_char_history` 多角色身份隔离 | ⭐ 参考，高价值 | "别人台词当场景事件注入"是组 prompt 的现成经验 |
| beat 排版 / `_parse_beat` / reformat | ✅ 直接搬 | 对应 D1 三种排版 |
| prompt 拼装 / OOC_GUARD / 人设字段 | ⭐ 参考 | 会被门控 RAG 的拼装取代 |
| choices(换一批) | ✅ 搬 | 对应 keywords suggestions/accept/skip |
| reminders / 时间承诺 | ✅ 搬概念 | 对应异步消息钩子 |
| game-state(affinity/attrs/achievements) | 🔁 改造 | 并进 Run state |
| scripts(acts/instructions) | 🔁 改造 | 并进 Story Events/Acts |
| plaza(posts/comments/likes) | ⏸ P1 先冻 | Community 已移出 MVP |
| worlds 实体(locations/presence) | ❌ 取代 | Story+Run+小手机替代；多角色聊天经验保留为参考 |
| groups 群聊 | ⏸ 停放 | DM/多人同台后移 |
| voice 克隆(fish/minimax) | ⏸ 停放 | 语音 TTS 停放 |
| SQLite 存储层(models.py) | ❌ 重写 | Postgres + SQLAlchemy + pgvector |

## 完全没有、必须从零做(工作量大头)

1. **门控 RAG 引擎**(差异化核心) — unlock_schema：fragment 分层、按 (act/affinity/flags/解锁) 在语义检索**之前**硬过滤、known_by 边界、guard 三态注入。
2. **Story/Secret 创作系统** — F1–F7 后端：敏感度、分层 fragment、好感滑块 + 幕 + 追问次数 + 事件 AND 触发组合。
3. **小手机子系统** — 每回合引擎把副作用写进 messages/calls/mail/calendar/notes/pay/browser。
4. **SSE 流式输出** + **Story 快照版本**(发布即冻结)。
5. **合规中间件** — 危机检测(988)、AI 披露、DOB 门、举报/DMCA。
6. **Stripe 计费** + 按订阅档位限流。

## 分步走法(对齐 M0–M4)

- **M0**：不动现有线上后端。建 monorepo，冻结 `openapi.yaml v0` + The Hollow Vale 种子数据。
- **M1**：`apps/api` 骨架(FastAPI + Postgres + SQLAlchemy)，落地能直接搬的：Auth、me/persona、Story CRUD(先不门控)。
- **M2**：门控引擎(mock LLM 跑通全链)+ 小手机副作用写入。**成败点**，火力集中于此。喂入 `_char_history`/beat/prompt 经验。
- **M3**：接真模型(Yi)、SSE、合规组件、Stripe 测试模式。
- **M4**：封测，再决定线上从老 demo 切到新版。

## 风险点

1. **门控引擎是唯一"重内容"模块** — 3 人团队集中火力，别被 39 屏 UI 摊薄。
2. **小手机 13 屏 × 每回合写副作用** 易成隐形大工程。MVP 先做 messages/notes/keywords 三个有真引擎联动的，其余静态占位。
3. **快照版本** 要在 M0 定死 —"作者改稿不破坏进行中 run"要求 Story 发布即 immutable 快照，后补很痛。
4. **pgvector retrieval_key 脱敏** — 嵌入脱敏检索键而非秘密原文，做错会从向量层泄露未解锁内容。安全关键。
