# LinguisPlay 后端对接说明

给独立前端用。**契约本身不要看这份文档，看 `openapi.json`**；这里只写 spec 表达不了、
但一定会绊住你的四件事。

> 契约是生成物，不是手写的。改了路由跑 `cd apps/api && python dump_openapi.py` 重新导出。
> 同目录下的 `openapi.yaml` 是 2026-06-25 的手写旧版（37/135 个接口），**已作废，别参考**。

---

## 0. 连哪里

| | |
|---|---|
| Base URL | `http://106.54.1.82:8100` |
| 路由前缀 | 所有接口都在 `/api/v1` 下 |
| 交互式文档 | http://106.54.1.82:8100/docs |
| 机器可读契约 | http://106.54.1.82:8100/openapi.json （与本目录 `openapi.json` 同源） |
| 健康检查 | `GET /api/v1/health` |

⚠️ **8100 是裸 HTTP，没有 HTTPS。** 服务器上 nginx 的 443 代理到 `127.0.0.1:8000`，
那是另一个应用，不是 LinguisPlay。要上 HTTPS 得单独配一段 nginx，见第 4 节。

接口分布（共 135 个）：

| 前缀 | 数量 | 是什么 |
|---|---|---|
| `/api/v1/runs` | 58 | 游戏主循环：开局、推进、存档、小手机、关系、日志 |
| `/api/v1/stories` | 27 | 剧本读写、工坊、发布、美术 |
| `/api/v1/gal` | 17 | galgame 生成器 |
| `/api/v1/me` | 6 | 当前用户 |
| `/api/v1/personas` | 5 | 玩家人设 |
| `/api/v1/cards` | 5 | 卡牌 |
| `/api/v1/auth` | 4 | 注册 / 登录 / 登出 / 重置 |
| 其余 | 13 | push、reviews、users、packs、wallet、health |

---

## 1. 登录是 cookie，不是 token

```
POST /api/v1/auth/signup   {email, password, accepted_tos}
POST /api/v1/auth/login    {email, password}
POST /api/v1/auth/logout
POST /api/v1/auth/reset
```

登录成功后服务端下发 **httpOnly cookie `lp_session`**（`samesite=lax`、30 天有效）。
没有 Bearer token，也拿不到 token：`httpOnly` 意味着 JS 读不到这个 cookie，
你只能让浏览器自动带。所有需要登录的请求都要：

```js
fetch(url, { credentials: 'include' })
```

## 2. ⚠️ 最大的坑：跨站直连拿不到登录态

cookie 是 `samesite=lax`。**Lax 不会在跨站 XHR/fetch 上发送。**
所以从 `localhost:5173` 直接 fetch `106.54.1.82:8100`，登录能成功、cookie 能种下，
但**下一个请求不会带上它**，你会看到一路 401，而且没有任何报错提示原因。

**解法：走 Vite 的 dev proxy，让浏览器认为是同源。** 这同时把 CORS 也绕过去了。

```js
// vite.config.js
export default {
  server: {
    proxy: {
      '/api': {
        target: 'http://106.54.1.82:8100',
        changeOrigin: true,
      },
      // 立绘 / 头像 / 背景等静态图
      '/scene': { target: 'http://106.54.1.82:8100', changeOrigin: true },
    },
  },
}
```

然后前端一律请求相对路径 `/api/v1/...`，不要写死后端域名。
**这条同时也是上生产的正解**：前端和 API 挂在同一个域下，cookie 和 CORS 两个问题一起消失。

如果坚持要跨站直连，后端得改三处：`cookie_secure=True`、`samesite="none"`、
并且必须有 HTTPS（`secure` cookie 在 http 上根本不会被种下）。找我改。

## 3. CORS 只放行一个来源

`apps/api/app/config.py` 里 `web_origin` 默认 `http://localhost:5173`，服务器上没有 `.env` 覆盖，
所以线上此刻**只接受来自 `localhost:5173` 的浏览器请求**，且 `allow_credentials=True`
（带 cookie 时 origin 不能是 `*`，这是浏览器规定）。

只支持一个来源。你部署到任何别的地址都要我改配置。走第 2 节的同源方案就不用碰它。

## 4. ⚠️ 主循环是 SSE，而且挂在 POST 上

两个接口返回 `text/event-stream`：

```
POST /api/v1/runs/{run_id}/play        ← 游戏主循环，逐拍推流
POST /api/v1/runs/{run_id}/confront
```

**`EventSource` 用不了**，它只支持 GET，也不能带 body。必须用 `fetch` + `ReadableStream`：

```js
const res = await fetch(`/api/v1/runs/${runId}/play`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ text }),
  credentials: 'include',
})
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

配套的坑：

- **别在中间加任何缓冲层。** 后端用的是自家的 `SmartGZipMiddleware` 而不是 FastAPI 官方的
  `GZipMiddleware`，因为官方那版流式分支 write 后不 flush，会把逐拍推流憋死。
  你在 nginx / Vite proxy / CDN 上再加一层 gzip 或 buffer，同样会憋死它。
  nginx 那一段必须写 `proxy_buffering off;`。
- **别自己再压一次。** 响应已经 gzip 过了。

## 5. 带宽是硬天花板

服务器出口实测只有 **0.4~0.8 Mbps**。这不是应用慢，是线细。所以：

- 图片（`/scene/...`）一律懒加载，列表页别一次拉几十张立绘
- 首屏能少拉就少拉，能缓存就缓存
- 感觉"卡"的时候先量传了多少字节，再怀疑接口慢

---

有不清楚的直接问，别对着旧的 `openapi.yaml` 猜。
