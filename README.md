# LinguisPlay

**AI 互动叙事引擎：答一张问卷，铸一个可玩的世界。**

LinguisPlay 是一个由大模型驱动的互动故事平台。玩家用对话推进剧情，引擎负责让故事"讲得住"：角色不失忆、场景不漂移、规则不被 AI 一时兴起推翻。创作者不用写代码，答完一张问卷就能得到一个可以立刻开玩的剧本，满意后一键公开到大厅。

## 核心能力

**叙事引擎（后端 `app/engine/`）**

- 回合制叙事运行时：计划/渲染双拍出字、意图识别、守卫链（越权改设定的输出会被拦下重写）
- 分层记忆系统：史书、场账本、关系账本，长局不失忆、跨时段不重演
- 逻辑严谨性三层闸：剧本静态检查（linter）、运行时校验、推理脚手架
- 剧组模式：导演、班底、开场访客，多角色同台不抢戏

**玩法系统**

- 沙盒本：货币与资产、修为阶梯（修炼/突破/离线温养）、活世界（每日事件、缺席因果）
- 涌现式地图：对话里约好去个新地方，引擎就真的把那个地方造出来并带你过去
- 恐怖主题包：理智值、猎手压迫、规则怪谈，三件套可按剧本开关
- 恋爱向：约定系统、情商调优（角色回复贴人设、会读空气）

**创作工具（UGC）**

- 问卷造本：galgame 向导与沙盒向导，一屏一问、断点续答，答完即得私有可玩本
- 工坊精修：世界观、角色卡、地点、文风（作者腔+忌清单）全部可编辑
- 美术管线：立绘、头像、自动合成封面（不额外生图）、场景背景异步生成
- 语音：角色配音选角与语气系统（CosyVoice）

**质量体系（四层验证）**

1. 单元/集成测试（pytest，MockLLM 与真 prompt 做同构合同测试）
2. `smoke_stories.py`：后端冒烟门，部署前必跑
3. `smoke_client.js`：客户端冒烟门，部署前必跑
4. 夜巡：每晚自动扮演真玩家轮换巡本，体验判官打分出红灯

## 仓库结构

```
linguisplay/
├── apps/api/                 # FastAPI 后端（主体）
│   ├── app/engine/           #   叙事引擎：runtime、逻辑闸、记忆、美术、语音…
│   ├── app/routers/          #   REST + SSE 接口（auth/stories/runs/gal/community…）
│   ├── app/static/           #   玩家端与工坊（play/studio/galmaker 等静态客户端）
│   └── tests/                #   测试套件
├── apps/web/                 # Vite + React + TS 新前端（施工中）
├── packages/contract/        # openapi.yaml 接口契约
├── tools/                    # 辅助工具（美术参考例库等）
├── deploy/                   # 部署脚本与配置
└── docs/                     # 设计文档（引擎全景、玩法设计、场账本合同…）
```

## 技术栈

- **后端**：Python / FastAPI / SQLAlchemy，默认 SQLite（方言兼容 Postgres），SSE 流式输出
- **前端**：静态 HTML 客户端（生产主力）+ Vite/React/TS（新前端）
- **模型**：通过统一 LLM 层接入（`app/engine/llm.py`），prompt 资产集中在 `qwen.py`

## 快速开始

```bash
# 后端
cd apps/api
python -m venv .venv && source .venv/Scripts/activate   # Windows Git Bash
pip install -r requirements.txt
uvicorn app.main:app --reload    # http://localhost:8000，Swagger 在 /docs

# 新前端（可选）
cd apps/web
npm install
npm run dev                      # http://localhost:5173
```

玩家端直接访问后端根路径即可（静态客户端由 FastAPI 托管）。健康检查：`/api/v1/health`。

## 部署前检查单

```bash
cd apps/api
pytest                    # 全套件回归
python smoke_stories.py   # 后端冒烟门
node smoke_client.js      # 客户端冒烟门
```

三关全绿才允许部署。已知问题挂账在 `docs/BUGS.md`。

## 参与开发

本仓库为私有仓，协作走 fork + PR：

1. Fork 本仓库，在自己的 fork 上开分支
2. 改动需带测试，跑过上面的检查单
3. 提 PR 回主仓，说明动机与影响面

设计文档入口：[docs/engine-features.md](docs/engine-features.md)（引擎功能全景，346 条六域清单）、[docs/gameplay-design.md](docs/gameplay-design.md)（玩法设计）。改引擎或播放器后，请以真实玩家路径走查一遍再交付。
