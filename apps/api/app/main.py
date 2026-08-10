import os
from contextlib import asynccontextmanager

from fastapi import Body, FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .middleware_perf import CachedStaticFiles, SmartGZipMiddleware, conditional_file

_STATIC = os.path.join(os.path.dirname(__file__), "static")
_SCENE = os.path.join(_STATIC, "scene")
for _sub in ("bg", "bgm", "sfx", "creature"):
    os.makedirs(os.path.join(_SCENE, _sub), exist_ok=True)

from .config import get_settings
from .db import init_db
from .routers import auth, cards, community, gal, me, packs, personas, push, runs, stories

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    # 🌍 活世界心跳: 服务端后台扫描, 到点的存档跳一次世界心跳 —
    # 玩家不在, 剧情照样往前走 (Yi 2026-07-11 的长期战略地基)
    import asyncio

    from .routers.runs import living_heartbeat_pass
    stop = asyncio.Event()

    async def _heartbeat_loop():
        while not stop.is_set():
            try:
                await asyncio.to_thread(living_heartbeat_pass)
            except Exception:
                pass
            try:
                await asyncio.wait_for(stop.wait(), timeout=600)
            except asyncio.TimeoutError:
                pass

    task = asyncio.create_task(_heartbeat_loop())
    yield
    stop.set()
    task.cancel()


app = FastAPI(
    title="LinguisPlay API",
    version="0.1.0",
    description="M2 — gated-RAG engine over the M1 skeleton (Auth/me/personas/stories/runs/play).",
    lifespan=lifespan,
)

# 🧾 422 must name the field in the LOG, not just the response — five mystery
# "PATCH /stories 422" lines cost a debugging session (实弹 2026-07-19: a player's
# save kept failing and the journal said nothing about why).
@app.exception_handler(RequestValidationError)
async def _log_validation_422(request, exc: RequestValidationError):
    import logging
    errs = exc.errors()
    logging.getLogger("uvicorn.error").warning(
        "422 %s %s :: %s", request.method, request.url.path,
        "; ".join("→".join(str(x) for x in e.get("loc", [])) + ": " + (e.get("msg") or "")
                  for e in errs[:5]))
    return JSONResponse(status_code=422, content={"detail": jsonable_encoder(errs)})


app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.web_origin],
    allow_credentials=True,  # required so the browser sends the httpOnly cookie
    allow_methods=["*"],
    allow_headers=["*"],
)

# 🚚 出口带宽实测只有 0.4~0.8 Mbps (服务器本机取 play.html 0.002s, 走公网 3.7~8.6s)。
# 应用不慢, 线细 —— 唯一的解是少传字节。gzip 后 play.html 353KB → 119KB。
# ⚠️ 用的是自家的 SmartGZipMiddleware 而非官方 GZipMiddleware: 官方那版流式分支
#    write 后不 flush, 会把游戏的 SSE 逐拍推流憋死。契约见 tests/test_transport_perf.py。
app.add_middleware(SmartGZipMiddleware, minimum_size=1000)

API = "/api/v1"
app.include_router(auth.router, prefix=API)
app.include_router(me.router, prefix=API)
app.include_router(personas.router, prefix=API)
app.include_router(cards.router, prefix=API)  # 📚 角色卡库 (cross-story characters)
app.include_router(stories.router, prefix=API)
app.include_router(community.router, prefix=API)  # 🧩 平台社区层 (赞/藏/关注/评论/作者主页)
app.include_router(packs.router, prefix="/api/v1")
app.include_router(runs.router, prefix=API)
# 🪦 phone_mock 已删 (2026-07-30): 它的每条路由都被 runs.router 的 /{run_id}/phone/{char_id}
# 抢先匹配 (挂载顺序在前), 一条都到不了; 而它对任何 run 都返回硬编码的假通讯录。
# 手机的真实现在 runs.py:/{run_id}/phone*, 位置口径统一走 runtime.char_position。
app.include_router(gal.router, prefix=API)  # 🎀 galgame 生成器 (docs/galgame-maker.md)
app.include_router(push.router, prefix=API)  # 🔔 Web Push 订阅 (活世界 P3)


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/play")


# the play/studio HTML changes often during dev — serve it with no-cache so the browser
# ALWAYS revalidates (no more "I deployed a UI fix but you still see the old page").
#
# 🚚 2026-08-03: 原来这里还带 no-store, 那等于禁掉缓存 —— ETag 一次都用不上,
# play.html 353KB 每次刷新都整个重下。在 0.5Mbps 的出口上就是每次白等 6 秒
# (Yi 报「整个网站非常卡」的头号成因)。改成只留 no-cache: 浏览器照旧每次问
# 服务器"变了吗", 没变就是 304 几百字节, 变了才给新的 —— 既不会看到旧页面,
# 也不用反复搬同样的字节。
_NO_CACHE = {"Cache-Control": "no-cache, must-revalidate", "Pragma": "no-cache", "Expires": "0"}


def _page(request: Request, filename: str):
    """伺服一个 HTML 页面, 认 If-None-Match (裸 FileResponse 不认, 详见 middleware_perf)."""
    return conditional_file(request, os.path.join(_STATIC, filename), _NO_CACHE)


@app.get("/play", include_in_schema=False)
def play_page(request: Request):
    return _page(request, "play.html")


@app.get("/studio", include_in_schema=False)
def studio_page(request: Request):
    return _page(request, "studio.html")


@app.get("/gal", include_in_schema=False)
def gal_shelf_page(request: Request):
    """🎀 galgame 书架: 所有本子一屏见封面 — 玩/建/进度的统一入口."""
    return _page(request, "galshelf.html")


@app.get("/galedit", include_in_schema=False)
def gal_edit_page(request: Request):
    """🛠 修订台: 重画/重编/改字/换画风 (blueprint §5 制作台)."""
    return _page(request, "galedit.html")


@app.get("/maker", include_in_schema=False)
def maker_page(request: Request):
    """🎀 galgame 生成器: 贴故事 → 建造 → 游玩 (docs/galgame-maker.md)."""
    return _page(request, "galmaker.html")


@app.get("/galplay", include_in_schema=False)
def galplay_page(request: Request):
    return _page(request, "galplay.html")


# 🔔 PWA 三件套 (活世界 P3): service worker 必须从根作用域伺服, 否则控不住 /play
@app.get("/sw.js", include_in_schema=False)
def service_worker():
    return FileResponse(os.path.join(_STATIC, "sw.js"),
                        media_type="application/javascript",
                        headers={**_NO_CACHE, "Service-Worker-Allowed": "/"})


@app.get("/manifest.json", include_in_schema=False)
def manifest():
    return FileResponse(os.path.join(_STATIC, "manifest.json"),
                        media_type="application/manifest+json")


@app.get("/icon-192.png", include_in_schema=False)
def icon_192():
    return FileResponse(os.path.join(_STATIC, "icon-192.png"), media_type="image/png")


@app.get("/icon-512.png", include_in_schema=False)
def icon_512():
    return FileResponse(os.path.join(_STATIC, "icon-512.png"), media_type="image/png")


# Scene assets (background images / BGM / SFX). Drop files here per SCENE_ASSETS.md;
# missing files 404 and the client degrades to gradient background + silence.
# 🚚 带 Cache-Control 挂载: /scene 是 49MB 美术, 原本只有 ETag 没有 Cache-Control,
# 浏览器只能启发式猜, 同一张立绘反复过线 (0.5Mbps 上一张 400KB 背景要 9~40 秒)。
# 一天的 max-age: 一天内零请求, 过期后 ETag 换 304 而不是重下。不上 immutable —
# 前端引图基本不带 ?v=, Yi 重出立绘是常事, 穿不透缓存就等于改了看不见。
app.mount("/scene", CachedStaticFiles(directory=_SCENE, max_age=86400), name="scene")


@app.get(f"{API}/health", tags=["health"])
def health():
    return {"status": "ok"}


@app.post(f"{API}/client-log", include_in_schema=False)
def client_log(body: dict = Body(default={})):
    """🩺 Field telemetry: the play page reports browser-side JS crashes here — beta
    players can't open devtools for us. Truncated hard; never errors out."""
    import logging
    try:
        msg = str(body.get("msg") or "")[:500]
        src = str(body.get("src") or "")[:120]
        logging.getLogger("uvicorn.error").warning("CLIENT-JS [%s] %s", src, msg)
    except Exception:
        pass
    return {"ok": True}
