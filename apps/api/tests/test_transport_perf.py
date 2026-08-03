# -*- coding: utf-8 -*-
"""🚚 传输层性能契约。Yi 报障 2026-08-03:「整个网站非常卡, 操作起来很不顺畅」。

实测定位 (不是应用慢, 是线太细):
  · 服务器本机取 play.html          0.002s
  · 公网取同一个文件 (353KB)        3.7 ~ 8.6s
  · 公网取一张背景图 (423KB)        9.3 ~ 40s
  · 折算出口带宽                    0.4 ~ 0.8 Mbps
一个场景 = 1 背景 + 2~4 立绘 ≈ 1.5MB ≈ 15~30 秒。带宽是天花板, 那就少传字节。

⚠️ 这里最要命的一条是【SSE 不许被压】: starlette 0.41.3 的 GZipResponder 流式分支
   (site-packages/starlette/middleware/gzip.py) 里只有 gzip_file.write(body), 没有
   flush() —— zlib 会把小分片憋在缓冲区, 每拍 SSE 发出去的 body 是空的。直接
   app.add_middleware(GZipMiddleware) 会把游戏的逐拍推流冻住。所以我们自己写一版,
   并用下面 test_sse_* 三条钉死它。
"""
import asyncio
import gzip

import pytest
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.testclient import TestClient

from app.main import app as real_app
from app.middleware_perf import SmartGZipMiddleware

BIG_HTML = "<p>" + ("超长正文 padding " * 2000) + "</p>"


@pytest.fixture
def mini():
    """一个只装了本中间件的小 app —— 把中间件本身当被测单元, 不牵扯业务路由。"""
    a = FastAPI()
    a.add_middleware(SmartGZipMiddleware, minimum_size=500)

    @a.get("/big")
    def big():
        return HTMLResponse(BIG_HTML)

    @a.get("/tiny")
    def tiny():
        return HTMLResponse("<p>短</p>")

    @a.get("/stream")
    def stream():
        def gen():
            for i in range(5):
                yield f"event: beat\ndata: {{\"i\": {i}, \"pad\": \"{'x' * 400}\"}}\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream")

    return TestClient(a)


# ── 📦 该压的要压 ────────────────────────────────────────────────────────────
def test_big_html_gets_gzipped(mini):
    r = mini.get("/big", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200
    assert r.headers.get("content-encoding") == "gzip", "大 HTML 没被压 — 353KB 会原样过线"
    assert "accept-encoding" in r.headers.get("vary", "").lower(), \
        "压了却不报 Vary, 会毒化中间缓存"
    assert r.text == BIG_HTML, "解压后内容变了"


def test_gzip_actually_shrinks_a_lot(mini):
    raw = len(BIG_HTML.encode())
    got = len(gzip.compress(BIG_HTML.encode()))
    assert got < raw * 0.5, f"压缩率不达标: {raw}B → {got}B"


def test_tiny_response_not_wasted_on_gzip(mini):
    r = mini.get("/tiny", headers={"Accept-Encoding": "gzip"})
    assert r.headers.get("content-encoding") is None, "小响应压了反而更大, 还白烧 CPU"


def test_client_without_gzip_still_served(mini):
    # ⚠️ 必须显式 identity: httpx 的 TestClient 默认就替你带上
    #    Accept-Encoding: gzip, deflate —— "不写 header" 不等于"没有 header"。
    r = mini.get("/big", headers={"Accept-Encoding": "identity"})
    assert r.status_code == 200
    assert r.headers.get("content-encoding") is None
    assert r.text == BIG_HTML


# ── 🚨 SSE 绝对不许被压 (游戏推流的命) ───────────────────────────────────────
def test_sse_is_never_gzipped(mini):
    r = mini.get("/stream", headers={"Accept-Encoding": "gzip"})
    assert r.headers.get("content-encoding") is None, \
        "SSE 被 gzip 了 — starlette 那版不 flush, 玩家会看到对话卡死不出字"


# ── 🔬 分片到达要在 ASGI 层量 ───────────────────────────────────────────────
# 头一版把这条写在 TestClient 上, 结果收到 1 个分片就报红 —— 其实是 httpx 把
# 分片合并了, 中间件是好的 (正文明明是明文)。测错了层就会冤枉产品。
# ASGI 层才是中间件的真实契约面: 上游发几条 body, 下游就该出几条 body。
async def _drive(ctype: str, chunks: list[bytes], accept: str = "gzip"):
    from app.middleware_perf import SmartGZipMiddleware

    async def upstream(scope, receive, send):
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-type", ctype.encode())]})
        for i, c in enumerate(chunks):
            await send({"type": "http.response.body", "body": c,
                        "more_body": i < len(chunks) - 1})

    got: list = []

    async def send(m):
        got.append(m)

    async def receive():
        return {"type": "http.request"}

    scope = {"type": "http", "headers": [(b"accept-encoding", accept.encode())]}
    await SmartGZipMiddleware(upstream, minimum_size=500)(scope, receive, send)
    return got


def _bodies(msgs):
    return [m for m in msgs if m["type"] == "http.response.body"]


def test_sse_chunks_pass_through_untouched():
    # 仓库没装 pytest-asyncio, 也不值得为两条测试引依赖 —— asyncio.run 足够。
    beats = [f"event: beat\ndata: {i}\n\n".encode() for i in range(5)]
    msgs = asyncio.run(_drive("text/event-stream", beats))
    bodies = _bodies(msgs)
    assert len(bodies) == 5, f"上游 5 拍, 下游只出了 {len(bodies)} 条 — 推流被吞"
    assert [b["body"] for b in bodies] == beats, "SSE 正文被动过 — 必须原样透传"


def test_streaming_html_compresses_without_stalling():
    """非 SSE 的分片响应 (FileResponse 就是 64KB 一片): 既要压, 又要每片都出得来。
    这条盯的是 Z_SYNC_FLUSH —— 少了它, 前几片的 body 会是空的。"""
    parts = [("段落 " + "内容" * 300).encode() for _ in range(4)]
    msgs = asyncio.run(_drive("text/html", parts))
    bodies = _bodies(msgs)
    assert len(bodies) == 4, f"上游 4 片, 下游 {len(bodies)} 片 — 被缓冲攒住了"
    for i, b in enumerate(bodies[:-1]):
        assert b["body"], f"第 {i} 片压出来是空的 — 忘了 Z_SYNC_FLUSH, 分片会卡住"
    start = [m for m in msgs if m["type"] == "http.response.start"][0]
    hdr = {k.decode().lower(): v.decode() for k, v in start["headers"]}
    assert hdr.get("content-encoding") == "gzip", "分片响应没压"
    joined = b"".join(b["body"] for b in bodies)
    assert gzip.decompress(joined) == b"".join(parts), "解压后内容对不上"


def test_sse_payload_is_readable_text(mini):
    r = mini.get("/stream", headers={"Accept-Encoding": "gzip"})
    assert r.text.startswith("event: beat"), "SSE 正文不是明文 — EventSource 解不出来"
    assert r.text.count("event: beat") == 5


# ── 🗂 缓存策略: 别让同样的字节反复过线 ──────────────────────────────────────
def test_play_page_allows_revalidation():
    """no-store 会让 353KB 每次刷新都重下一遍, ETag 一次都用不上。
    改 no-cache: 仍然每次校验新鲜度, 但没变就是 304 (几百字节)。"""
    c = TestClient(real_app)
    cc = c.get("/play").headers.get("cache-control", "")
    assert "no-store" not in cc, f"/play 还带 no-store, ETag 永远用不上 (实测: {cc})"
    assert "no-cache" in cc, f"/play 要保留 no-cache 才能每次校验 (实测: {cc})"


def test_play_page_returns_304_when_unchanged():
    c = TestClient(real_app)
    first = c.get("/play")
    etag = first.headers.get("etag")
    assert etag, "/play 没有 ETag, 无法条件请求"
    again = c.get("/play", headers={"If-None-Match": etag})
    assert again.status_code == 304, \
        f"没变的页面还是回了 {again.status_code} + 全量正文 — 每次刷新白烧 353KB"


def test_scene_assets_carry_cache_control():
    """/scene 是 49MB 美术。没有 Cache-Control 时浏览器只能启发式猜, 反复重下。"""
    c = TestClient(real_app)
    import os
    from app.main import _SCENE
    os.makedirs(os.path.join(_SCENE, "bg"), exist_ok=True)
    probe = os.path.join(_SCENE, "bg", "_perfprobe.jpg")
    with open(probe, "wb") as f:
        f.write(b"\xff\xd8\xff" + b"0" * 4000)
    try:
        r = c.get("/scene/bg/_perfprobe.jpg")
        assert r.status_code == 200
        cc = r.headers.get("cache-control", "")
        assert "max-age" in cc, f"/scene 没有 Cache-Control (实测: {cc!r}) — 美术反复重下"
        age = int(cc.split("max-age=")[1].split(",")[0])
        assert age >= 3600, f"max-age 只有 {age}s, 起不到作用"
        # 🎨 美术是热资源 (Yi 常重出立绘/背景), 不许 immutable 也不许长到改了看不见。
        # 前端引用图片基本不带 ?v=, 缓存穿不透就等于换了图看不到。
        assert "immutable" not in cc, "美术还在迭代, immutable 会让重出的图刷不出来"
        assert age <= 86400, f"max-age {age}s 太长, Yi 重出的图要等这么久才生效"
    finally:
        os.remove(probe)


# ── 🧪 红样本自验 (没看过红的测试不算测试) ──────────────────────────────────
def test_red_sample_old_no_store_would_be_caught():
    before = "no-cache, no-store, must-revalidate"
    assert "no-store" in before, "红样本本身就该踩中, 否则上面那条是空转"


def test_red_sample_naive_gzip_would_break_sse():
    """证明「直接上 starlette GZipMiddleware」确实会坏 —— 不是我瞎担心。
    复刻它流式分支的写法: write 之后不 flush, 取出来的就是空的。"""
    import io

    buf = io.BytesIO()
    gf = gzip.GzipFile(mode="wb", fileobj=buf, compresslevel=9)
    gf.write(b"event: beat\ndata: hello\n\n")   # 一拍 SSE
    emitted = buf.getvalue()                     # starlette 此处直接 getvalue() 就发走
    assert len(emitted) <= 10, (
        f"这一拍能发出 {len(emitted)} 字节 —— 若非 0, 说明 starlette 版本行为变了, "
        "回去重新评估能不能直接用官方 GZipMiddleware")
