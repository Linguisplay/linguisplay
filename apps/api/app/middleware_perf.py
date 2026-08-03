# -*- coding: utf-8 -*-
"""🚚 传输层省字节三件套。

背景 (2026-08-03 Yi 报「整个网站非常卡」的实测):
    服务器本机取 play.html   0.002s
    公网取同一个文件 353KB   3.7 ~ 8.6s
    公网取一张背景图 423KB   9.3 ~ 40s
    → 出口带宽 0.4 ~ 0.8 Mbps
应用一点不慢, 卡的是线。带宽是天花板, 唯一的手段就是【少传字节】。

⚠️ 为什么不用官方 starlette.middleware.gzip.GZipMiddleware:
   0.41.3 的流式分支 (gzip.py, GZipResponder.send_with_gzip) 是
       self.gzip_file.write(body)
       message["body"] = self.gzip_buffer.getvalue()
   write 之后没有 flush —— zlib 会把小分片憋在内部缓冲, 每拍取出来是空的。
   游戏的对白靠 SSE 逐拍推流, 上了它玩家会看到「对话卡死不出字」。
   本文件的 SmartGZipMiddleware 做两件官方版没做的事:
     1. text/event-stream 整条绕过, 一个字节都不碰;
     2. 其余流式响应 (FileResponse 是 64KB 一片) 每片 Z_SYNC_FLUSH, 既压缩又不憋。
   契约钉在 tests/test_transport_perf.py, 其中 test_red_sample_naive_gzip_would_break_sse
   会在 starlette 行为变了的时候提醒重新评估。
"""
from __future__ import annotations

import os
import zlib

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import FileResponse, Response
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# 只压文本类。图片/音频/字体本身已是压缩格式, 再压一遍白烧 CPU 还可能变大。
_COMPRESSIBLE = (
    "text/",
    "application/json",
    "application/javascript",
    "application/xml",
    "application/manifest+json",
    "image/svg+xml",
)

# 🚨 绝对绕过。推流被缓冲 = 游戏对白卡死。
_NEVER = ("text/event-stream",)


def _is_compressible(ctype: str) -> bool:
    c = ctype.split(";")[0].strip().lower()
    if c in _NEVER:
        return False
    return any(c.startswith(p) for p in _COMPRESSIBLE)


class SmartGZipMiddleware:
    """gzip, 但对 SSE 与二进制资源装死。"""

    def __init__(self, app: ASGIApp, minimum_size: int = 1000, compresslevel: int = 6) -> None:
        self.app = app
        self.minimum_size = minimum_size
        # 6 是甜点: 对 play.html 与 9 的体积差 <2%, CPU 却少一大截。
        self.compresslevel = compresslevel

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        accept = Headers(scope=scope).get("accept-encoding", "")
        if "gzip" not in accept.lower():
            return await self.app(scope, receive, send)
        responder = _GZipResponder(self.app, self.minimum_size, self.compresslevel)
        await responder(scope, receive, send)


class _GZipResponder:
    def __init__(self, app: ASGIApp, minimum_size: int, compresslevel: int) -> None:
        self.app = app
        self.minimum_size = minimum_size
        self.compresslevel = compresslevel
        self.send: Send = None  # type: ignore[assignment]
        self.start: Message | None = None
        self.mode: str | None = None      # None=未决 / "skip" / "stream"
        self.co: "zlib._Compress | None" = None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        self.send = send
        await self.app(scope, receive, self._send)

    def _new_compressor(self):
        # 16 + MAX_WBITS = 输出 gzip 容器 (而非裸 deflate)
        return zlib.compressobj(self.compresslevel, zlib.DEFLATED, 16 + zlib.MAX_WBITS)

    async def _flush_start(self) -> None:
        if self.start is not None:
            await self.send(self.start)
            self.start = None

    async def _send(self, message: Message) -> None:
        if message["type"] == "http.response.start":
            self.start = message
            headers = Headers(raw=message["headers"])
            status = message.get("status", 200)
            ctype = headers.get("content-type", "")
            if (
                "content-encoding" in headers          # 别人已经压过了
                or status < 200                        # 1xx 没正文
                or status in (204, 304)                # 本来就无正文
                or not _is_compressible(ctype)         # SSE / 图片 / 音频都落这
            ):
                self.mode = "skip"
            return  # 先扣住 start, 等看到正文才知道要不要改头

        if message["type"] != "http.response.body":
            await self._flush_start()
            return await self.send(message)

        body = message.get("body", b"")
        more = message.get("more_body", False)

        if self.mode == "skip":
            await self._flush_start()
            return await self.send(message)

        if self.mode is None:
            # 第一片正文决定走法
            if not more and len(body) < self.minimum_size:
                # 一次发完且很短: 压了反而更大
                self.mode = "skip"
                await self._flush_start()
                return await self.send(message)
            self.mode = "stream"
            self.co = self._new_compressor()
            headers = MutableHeaders(raw=self.start["headers"])  # type: ignore[index]
            headers["Content-Encoding"] = "gzip"
            headers.add_vary_header("Accept-Encoding")
            if more:
                # 分片发: 压完多大事先不知道, 只能去掉 Content-Length 走 chunked
                del headers["Content-Length"]

        assert self.co is not None
        if more:
            # ⚠️ 命门: Z_SYNC_FLUSH 把这一片彻底吐出来, 不留在 zlib 缓冲里。
            # 少了它, 分片响应就会攒到流结束才到达 —— 正是官方版坑 SSE 的原因。
            out = self.co.compress(body) + self.co.flush(zlib.Z_SYNC_FLUSH)
            await self._flush_start()
            return await self.send({**message, "body": out, "more_body": True})

        out = self.co.compress(body) + self.co.flush(zlib.Z_FINISH)
        if self.start is not None:
            # 整条一次发完 —— 压后长度是确定的, 给回 Content-Length 更省事
            MutableHeaders(raw=self.start["headers"])["Content-Length"] = str(len(out))
        await self._flush_start()
        await self.send({**message, "body": out, "more_body": False})


class CachedStaticFiles(StaticFiles):
    """给静态资源盖 Cache-Control。

    /scene 是 49MB 美术, 原本只有 ETag 没有 Cache-Control, 浏览器只能启发式猜,
    结果同样的立绘反复过线。给一天的 max-age: 一天内零请求, 过期后 ETag 换个
    304 (几百字节) 而不是重下 400KB。

    ⚠️ 不用 immutable、也不给更长的 max-age: 前端引用图片基本不带 ?v=,
    Yi 重出立绘/背景是常事, 缓存穿不透 = 换了图看不见。一天是「够省」与
    「改了能看见」的折中。
    """

    def __init__(self, *args, max_age: int = 86400, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._max_age = max_age

    def file_response(self, *args, **kwargs) -> Response:
        resp = super().file_response(*args, **kwargs)
        resp.headers["Cache-Control"] = f"public, max-age={self._max_age}"
        return resp


def conditional_file(request, path: str, headers: dict | None = None) -> Response:
    """带条件请求的 FileResponse。

    Starlette 的 304 判定长在 StaticFiles 里, 裸 FileResponse 没有 —— 所以
    /play /studio 这些直接 FileResponse 的页面, 无论变没变都回全量正文。
    353KB × 每次刷新, 在 0.5Mbps 的线上就是每次 6 秒。
    """
    st = os.stat(path)
    etag_base = f"{st.st_mtime}-{st.st_size}"
    etag = '"' + __import__("hashlib").md5(etag_base.encode()).hexdigest() + '"'
    out = dict(headers or {})
    out["ETag"] = etag

    inm = request.headers.get("if-none-match", "") if request is not None else ""
    if inm and any(t.strip() in (etag, "*") for t in inm.split(",")):
        return Response(status_code=304, headers=out)
    return FileResponse(path, headers=out)
