import os
from contextlib import asynccontextmanager

from fastapi import Body, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

_STATIC = os.path.join(os.path.dirname(__file__), "static")
_SCENE = os.path.join(_STATIC, "scene")
for _sub in ("bg", "bgm", "sfx"):
    os.makedirs(os.path.join(_SCENE, _sub), exist_ok=True)

from .config import get_settings
from .db import init_db
from .routers import auth, cards, gal, me, personas, phone_mock, runs, stories

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="LinguisPlay API",
    version="0.1.0",
    description="M2 — gated-RAG engine over the M1 skeleton (Auth/me/personas/stories/runs/play).",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.web_origin],
    allow_credentials=True,  # required so the browser sends the httpOnly cookie
    allow_methods=["*"],
    allow_headers=["*"],
)

API = "/api/v1"
app.include_router(auth.router, prefix=API)
app.include_router(me.router, prefix=API)
app.include_router(personas.router, prefix=API)
app.include_router(cards.router, prefix=API)  # 📚 角色卡库 (cross-story characters)
app.include_router(stories.router, prefix=API)
app.include_router(runs.router, prefix=API)
app.include_router(phone_mock.router, prefix=API)  # MOCK: phone domain skeleton
app.include_router(gal.router, prefix=API)  # 🎀 galgame 生成器 (docs/galgame-maker.md)


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/play")


# the play/studio HTML changes often during dev — serve it with no-cache so the browser
# ALWAYS fetches the latest (no more "I deployed a UI fix but you still see the old page").
_NO_CACHE = {"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache", "Expires": "0"}


@app.get("/play", include_in_schema=False)
def play_page():
    return FileResponse(os.path.join(_STATIC, "play.html"), headers=_NO_CACHE)


@app.get("/studio", include_in_schema=False)
def studio_page():
    return FileResponse(os.path.join(_STATIC, "studio.html"), headers=_NO_CACHE)


@app.get("/gal", include_in_schema=False)
def gal_shelf_page():
    """🎀 galgame 书架: 所有本子一屏见封面 — 玩/建/进度的统一入口."""
    return FileResponse(os.path.join(_STATIC, "galshelf.html"), headers=_NO_CACHE)


@app.get("/maker", include_in_schema=False)
def maker_page():
    """🎀 galgame 生成器: 贴故事 → 建造 → 游玩 (docs/galgame-maker.md)."""
    return FileResponse(os.path.join(_STATIC, "galmaker.html"), headers=_NO_CACHE)


@app.get("/galplay", include_in_schema=False)
def galplay_page():
    return FileResponse(os.path.join(_STATIC, "galplay.html"), headers=_NO_CACHE)


# Scene assets (background images / BGM / SFX). Drop files here per SCENE_ASSETS.md;
# missing files 404 and the client degrades to gradient background + silence.
app.mount("/scene", StaticFiles(directory=_SCENE), name="scene")


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
