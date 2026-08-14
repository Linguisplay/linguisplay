# LinguisPlay 后端对接说明

给独立前端用。**契约看 `openapi.json`**（164 个操作 / 135 条路径）；这份文档只写
spec 表达不了、但一定会绊住你的东西。

> 契约是生成物。改了路由跑 `cd apps/api && PYTHONPATH=winshim python dump_openapi.py`
> 重新导出（Windows 上必须带 `PYTHONPATH=winshim`，`runs.py` 顶层 `import fcntl`）。
> 线上 `/openapi.json` 和这份文件走的是**同一个函数**（`app/openapi_ext.py`），不会分家。
> 同目录 `openapi.legacy-2026-06-25.yaml` 是作废的手写旧版，别参考。

## 先读这个：契约有 70% 是空的

**164 个操作里 115 个（70%）的 2xx 响应 schema 是字面量 `{}`。** `/gal` 全军覆没 18/18，
`/runs` 52/65。原因是这些接口返回裸 `dict` 而不是 pydantic 模型，FastAPI 推不出形状。

**这意味着：codegen 生成的返回类型大面积是 `any`，你得靠实际调用去摸。**
好消息：金路径（第 4 节那 8 个）已经全部有真形状（最后缺的 `POST /choose`
2026-08-14 补上）。遇到空 schema 的接口，直接打一次看真实响应，或者问后端。

错误体统一是 `{"detail": ...}`（`ErrorEnvelope`）。**`detail` 多数是中文字符串，
少数场合是对象** —— 渲染前判类型，别直接拼，否则会显示 `[object Object]`。
契约里只有 401 和 422 是声明了的；实际 routers 抛了 217 次 `HTTPException`，
覆盖 400/403/404/409/413/415/429/502/503，这些**没有出现在契约里**。

---

## 0. 连哪里

| | |
|---|---|
| Base URL | `http://106.54.1.82:8100` |
| 路由前缀 | 业务接口都在 `/api/v1` 下；静态资源在 `/scene/*`；另有 PWA 三件套在根路径 |
| 健康检查 | `GET /api/v1/health` |
| 实时契约 | `http://106.54.1.82:8100/openapi.json` |
| Swagger | `http://106.54.1.82:8100/docs` ⚠️ 它的前端资源走 `cdn.jsdelivr.net`，**国内大概率打不开**，用本地 `openapi.json` 配 Redoc/Scalar 更稳 |

⚠️ **8100 是裸 HTTP。** nginx 的 443 代理到 `127.0.0.1:8000`，那是另一个应用。
你的前端一旦部署到 HTTPS 页面，混合内容策略会拦掉发往这个 HTTP 接口的请求。
解法见第 2 节的同源方案。

## 1. 登录是 cookie，不是 token

```
POST /api/v1/auth/signup   {email, password, dob, accepted_tos, display_name?, handle?}
POST /api/v1/auth/login    {email, password}
POST /api/v1/auth/logout
POST /api/v1/auth/reset    ⚠️ 空壳：永远返回 202，什么都不做。别做找回密码的 UI
```

⚠️ **`dob` 是必填的**（出生日期），而且有 **18 岁硬校验**，未成年直接拒。
注册表单必须收这个字段。

登录成功后服务端下发 **httpOnly cookie `lp_session`**（`samesite=lax`，30 天）。
没有 Bearer token，也拿不到：`httpOnly` 意味着 JS 读不到它，只能让浏览器自动带。

```js
fetch(url, { credentials: 'include' })
```

契约里 **150 个操作标了必须登录**（会返回 401），另外 3 个是"登录更好"（永不 401，
未登录给公共视图）。codegen 能读到这个信息（`security: cookieAuth`）。

## 2. ⚠️ 跨站直连拿不到登录态

cookie 是 `samesite=lax`，**Lax 不会在跨站 XHR / fetch 上发送**。
从 `localhost:5173` 直接 fetch `106.54.1.82:8100`：登录请求本身能通，但
**浏览器根本不会存下这个 cookie**，后续请求一路 401。
（DevTools 的 Network → Cookies 里会明确标 `SameSiteLax` 被拒，不是完全没提示，
但很容易被忽略。）

**解法：走 Vite 的 dev proxy，让浏览器认为是同源。** 这同时绕过 CORS 和混合内容。
**这也是上生产的正解**：前端和 API 挂同一个域，三个问题一起消失。

```js
// vite.config.js
export default {
  server: {
    proxy: {
      '/api':   { target: 'http://106.54.1.82:8100', changeOrigin: true },
      '/scene': { target: 'http://106.54.1.82:8100', changeOrigin: true },
    },
  },
}
```

前端一律请求相对路径 `/api/v1/...`，不要写死后端域名。

要跨站直连的话后端得改三处：`cookie_secure=True`、`samesite="none"`、且必须有 HTTPS
（`secure` cookie 在 http 上根本不会被种下）。找后端改。

## 3. CORS 只放行一个来源

`web_origin` 默认 `http://localhost:5173`。服务器上 `.env` **是存在的**（被 systemd 的
`EnvironmentFile` 加载，里面是生产密钥），但**里面没有 `WEB_ORIGIN`**，所以线上确实
只认 `localhost:5173`，且 `allow_credentials=True`（带 cookie 时 origin 不能是 `*`）。

只支持一个来源，部署到别的地址都要后端改。走第 2 节的同源方案就不用碰它。

## 4. 主循环

### 金路径（跑通一局的最小集）

```
POST   /api/v1/personas              ① 先建人设 —— 没有它开不了局
GET    /api/v1/stories               ② 列剧本（游标分页，见下）
POST   /api/v1/runs                  ③ 开局：story_id + persona_id 都是必填
GET    /api/v1/runs/{run_id}         ④ 进档必调：scene/cast/here/state/clock/direct 全在这
GET    /api/v1/runs/{run_id}/play    ⑤ 回放历史 beats（非流式）
POST   /api/v1/runs/{run_id}/play    ⑥ 推进一拍 ← SSE
POST   /api/v1/runs/{run_id}/choose  ⑦ 流里来了 choice 事件时交选择（body: {option_id}）
GET    /api/v1/runs                  ⑧ 存档列表
```

⚠️ **④ 和 ⑤ 是两回事，都要调。** `/play` 的 GET 只给一串裸 beats，
屏幕上除对白外的一切（背景、在场角色、时钟、当前目标、待答选择、BGM）
**只存在于 `GET /api/v1/runs/{run_id}`**。刷新页面只调 GET `/play` 会得到一堆没有场景的对白。

⚠️ **`POST /runs` 有 11 个字段**，不止 `story_id`：`persona_id`（必填）、
`mode`（`character` / `god` 旁观）、`player_character_id`（选演已有角色）、
`player_name`、`worldview`、`era`、`powers`、`mature`、`perk`、`carry_card_id`。
线上 8 个可玩剧本**全是 sandbox**，开局是一整屏"定义世界"问卷，这些字段就是问卷的答案。
另外：没有作者写好修为阶梯的沙盒剧本，`POST /runs` 会**同步等一次 LLM**（线上 8 个里有 3 个），
开局接口会卡几秒，这是正常的。

`GET /stories` 游标分页真实生效（2026-08-14 起）：每页 50 条；`next_cursor` 非空就把它
原样回传到 `cursor` 翻下一页，翻完为 `null`。乱传 `cursor` 会得到 400。

### 推进请求的 body

```js
POST /api/v1/runs/{run_id}/play
{ input: "我看向她", channel: "say" }
```

⚠️ 字段叫 **`input`**，不是 `text`。`channel` 四个值是**四种输入模式，要做成 UI**：

| channel | 含义 |
|---|---|
| `say` | 说（默认） |
| `think` | 想 |
| `do` | 做 |
| `drive` | 导演推进 |

还可选 `target_character_id`（对谁说）、`client_turn_id`（幂等用）。

### ⚠️ 读流之前必须先判 `res.ok`

`POST /play` 有 **5 种不同的 409、1 种 429、以及 401**，它们是**普通 JSON 响应**，
不是 SSE。不判 `res.ok` 直接读流 → 把错误体当 SSE 解析 → 永远等不到 `done` →
**输入框永久锁死**。

而引擎中途挂掉是**带内**传递的：HTTP 仍然是 200，错误伪装成一条正文以 `[出错]` 开头的
beat 送出来。前端要识别这个前缀，否则会把 `[出错] TimeoutError` 当正文演给玩家看。

⚠️ **这一拍很慢**：线上实测 p50 **10.5 秒**、p99 **38 秒**、最长 **68.6 秒**。
如果你在中间放 nginx，`proxy_read_timeout` 默认 60 秒**会砍断长回合**，必须调大。

```js
const res = await fetch(`/api/v1/runs/${runId}/play`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ input: text, channel: 'say' }),
  credentials: 'include',
})
if (!res.ok) {                      // 401 / 409 / 429 是 JSON，不是 SSE
  const { detail } = await res.json()
  return showError(typeof detail === 'string' ? detail : JSON.stringify(detail))
}

const reader = res.body.getReader()
const dec = new TextDecoder()
let buf = ''
while (true) {
  const { value, done } = await reader.read()
  if (done) break
  buf += dec.decode(value, { stream: true })
  let i
  while ((i = buf.indexOf('\n\n')) >= 0) {   // SSE 以空行分帧
    const frame = buf.slice(0, i); buf = buf.slice(i + 2)
    for (const line of frame.split('\n')) {
      if (line.startsWith('data:')) handle(JSON.parse(line.slice(5).trim()))
    }
  }
}
```

### ⚠️⚠️ `token` 事件：载荷是对象，text 是增量，说话人会中途翻转

**这是最高频的事件，也最容易写错。**

```json
{"event":"token","t":{"speaker":"阿岚","kind":"speech","text":"接着说。"}}
```

- `t` 是**对象**，不是字符串。`draft += ev.t` 会得到满屏 `[object Object]`。
- `t.text` 是**增量片段**，append 不是替换。
- `t.kind` 是 `narration` / `speech`，**会在一次推流中途翻转**，`speaker` 跟着变。

所以**必须按 `(kind, speaker)` 分气泡各自维护草稿**。用一个扁平字符串往下拼，
会把旁白和台词糊进同一个气泡、多人同场串名 —— 而且它**看起来像正常文本**，
不会自曝，是会直接上线的正确性 bug。

`beat` 事件到达时，用完整的 `beat` 替换掉刚才拼的草稿。

### SSE 事件目录（30 种）

字段明细在 `sse-events.json`（`dump_openapi.py` 从代码 AST 抽取，不是手写）。
⚠️ **它只给外层键名**，`choice` / `ending` / `move_request` / `state` / `clock`
这些要交互要渲染的载荷，内部结构没有 —— 得看参考实现或问后端。

先做对这三个，游戏就能跑起来：

| 事件 | 载荷 | 干什么 |
|---|---|---|
| `token` | `t: {speaker, kind, text}` | 逐字推流，见上面的警告 |
| `beat` | `beat` | 一拍落地，替换草稿 |
| `done` | 无 | 这轮结束，放开输入框 |

其余 27 种：

| 用途 | 事件 |
|---|---|
| 场面 | `scene` `cast` `here` `place` `state` `clock` `newday` |
| 等玩家操作 | `choice` `move_request` `suggest` `sugg` |
| 演出指令（不等玩家） | `direct`（BGM / 色调）`dice` `peek` |
| 进度与结算 | `goal` `progress` `hint` `promises` `verdict` `moments` `achievements` `ending` |
| 主题包（恐怖等） | `pressure` `threat` `sanity` |
| 其他 | `phone` `audit` |

- **未知事件一律静默忽略**，别抛错：后端会加新事件，加了不通知你。
- `sugg` 和 `suggest` 是**两个不同的事件**（流中途 vs 最终），载荷键同名，历史遗留。
- `beat` 对象里还有**没进契约的演出键** `sfx` / `fx` / `expr`（音效 / 特效 / 立绘表情差分）。
  要做演出层就得用它们。
- `/confront` 只发 30 种里的 **14 种**，不是全部。

## 5. 静态资源：URL 靠约定拼，404 不代表没有

**没有任何接口返回图片和音频的 URL**，全靠路径约定：

| 资源 | 路径 | 典型体积 |
|---|---|---|
| 背景 | `/scene/bg/{state.location.id}.jpg`，无 location 时用 `/scene/bg/{state.scene.bg}.jpg` | ~175 KB |
| 夜间背景 | 先试 `/scene/bg/{bg}_night.jpg`，404 回落白天版 | ~175 KB |
| BGM | `/scene/bgm/{direct.bgm}.mp3` | ~375 KB |
| 头像 | 直接用 `cast[].avatar_url` / `here[].avatar_url`（已是完整路径，**别自己拼**） | ~55 KB |

⚠️ **404 = 还在生图，不是没有。** 图是服务端异步渲染的（开局时才排队）。
参考实现的做法：先画关键词兜底图，然后 **22 秒后重试，最多 8 次**。
背景带 `?v=` cache-buster 用于重画后刷新。

## 6. 带宽是硬天花板

服务器出口实测 **0.4 ~ 0.8 Mbps**。同一份 `play.html`，服务器本机取用 0.002 秒，
走公网要 3.7 ~ 8.6 秒。按这个速率：一张背景 2~3.5 秒，一首 BGM 4~7 秒。

- 图片一律懒加载，列表页别一次拉几十张
- 感觉"卡"的时候**先量传了多少字节**，再怀疑接口慢
- 注意 `GET /runs/{id}/play` **无分页**，一次吐这一局全部 beats

⚠️ 响应默认 gzip，**但 SSE 流被显式排除在 gzip 之外**（官方 `GZipMiddleware` 会把
逐拍推流憋死，后端换了自家的 `SmartGZipMiddleware`）。你在 nginx / proxy / CDN 上
再加一层 gzip 或 buffer，同样会憋死它 —— nginx 那段必须 `proxy_buffering off;`。

## 7. 先看参考实现，别从零发明

现网已经有一份**完整的参考前端**：`apps/api/app/static/play.html`，6253 行，
线上直接 `GET /play` 就能打开。它消费了 30 种事件里的 29 种，
背景/BGM/头像的全部拼串规则、重试策略、SSE 分帧都在里面。

**动手前先读它。** 这份文档里所有"约定"的原始出处都是它。

## 8. 你还需要一个测试账号

自助注册是通的（`POST /auth/signup`，记得带 `dob`），但新号是空的：
没有人设、没有存档，主循环没东西可测。

找后端要一个**播过种的测试账号**（有进度的存档、有立绘的角色、跑起来的关系网）。
别拿生产账号调试。

---

有不清楚的直接问后端。这份文档里每一条都是 2026-08-14 实测或从代码核对过的；
再往下的细节以 `play.html` 为准。
