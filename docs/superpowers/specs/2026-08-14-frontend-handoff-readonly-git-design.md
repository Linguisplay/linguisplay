# 前端同事对接交付：git 只读访问 + 测试账号 + 开工指引

日期：2026-08-14 ｜ 状态：已批准（Yi 拍板方案 A）

## 背景与范围

前端同事独立开发新前端，后端仍由我方维护（**只做对接，不移交后端**）。
对接文档已就位：`packages/contract/FRONTEND.md`（2026-08-14 对抗性核查后重写）+
`openapi.json` + `sse-events.json`，本次不改动它们。

本次交付三件东西：

1. 仓库 **git 只读访问**（Yi 选定，替代 zip / 线上 URL 方案）
2. 一个**播过种的测试账号**（FRONTEND.md §8 明确要求）
3. 一页**开工指引**（微信可发，不入库）

## 1. git 只读访问（方案 A：服务器受限账号）

服务器：`106.54.1.82`（SSH 别名 `persona`），裸仓库 `/opt/git/linguisplay.git`。

做法：

- 新建 Unix 用户 `lpread`，无密码登录，仅密钥认证
- 同事公钥写入 `/home/lpread/.ssh/authorized_keys`，行首加限制：
  - forced command：只放行 `git-upload-pack '/opt/git/linguisplay.git'`（clone/fetch 的服务端命令），其余一律拒绝
  - `no-port-forwarding,no-X11-forwarding,no-agent-forwarding,no-pty`
- 文件权限兜底：`lpread` 对 `/opt/git/linguisplay.git` 只读（属主不变，目录 o+rx / 文件 o+r 已满足即可，不给写位）
- 同事侧 clone 地址：`lpread@106.54.1.82:/opt/git/linguisplay.git`

**验收（三条都要真机跑）：**

| # | 动作 | 期望 |
|---|---|---|
| 1 | 用同事公钥对应私钥 `git clone` | 成功，能看到 master 最新提交 |
| 2 | 同一身份 `git push` | 被拒（forced command 不放行 receive-pack） |
| 3 | 同一身份 `ssh lpread@… ` 要交互 shell | 被拒 / 直接断开 |

安全前提（已核查通过）：`.env` 从未入库；历史中无 key 形状字符串
（`git log --all -G'sk-[A-Za-z0-9]{24,}'` 零命中）；仓库可整库暴露给只读方。

## 2. 播种测试账号

- `POST /api/v1/auth/signup` 注册新账号（专用测试邮箱 + 随机密码，`dob` 满 18）
- 播种：建 1 个人设 → 开 1 局（选一个有立绘的剧本，如浮生）→ 推 3~5 拍出进度，
  让 `GET /runs/{id}` 里 scene/cast/here/clock 都有真东西
- 账号密码只通过私聊发同事，**不写进任何入库文件**

验收：用该账号登录后，存档列表非空，进档能看到场景与角色立绘。

## 3. 开工指引（一页，发微信）

内容顺序：

1. clone 命令 + 公钥怎么给（`ssh-keygen -t ed25519`，发 `.pub` 内容）
2. 先读 `packages/contract/FRONTEND.md`（对接的一切坑都在里面）
3. 参考实现：`apps/api/app/static/play.html`（线上 `GET /play` 可直接打开）
4. 测试账号（占位，账号密码单发）
5. 遇到不明白的直接找 Yi

产出为纯文本，交给 Yi 转发；不进仓库（含账号信息）。

## 前置输入与顺序

- **同事的 SSH 公钥**是第 1 项的硬前置。公钥未到时：服务器侧先把用户、权限、
  authorized_keys 模板都架好，公钥一到贴一行即完成
- 第 2、3 项不依赖公钥，可先做

## 非目标

- 不改 FRONTEND.md / 契约文件
- 不做 key 轮换（另案：`docs/key-rotation.md` 首轮至今未执行，已提醒 Yi 尽快）
- 不动仓库里并行会话的未追踪文件；提交只暂存本任务自己的文件

## 风险

- 同事可见整库（docs 设计文档全家当）：Yi 知情选择
- forced command 写错会把同事锁在门外或放开过多：靠三条验收兜住
- 服务器 sshd 若有 `AllowUsers` 白名单，需同步加 `lpread`（执行时现场确认）
