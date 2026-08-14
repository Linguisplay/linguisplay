# -*- coding: utf-8 -*-
"""📜 契约增强 —— FastAPI 自动生成的那份不够前端施工，这里补齐。

⚠️ 为什么这段代码在 app 里而不在导出脚本里 (Yi 2026-08-14 追问「确定没问题是吧」，
对抗性核查实锤):
增强本来写在 apps/api/dump_openapi.py 里，于是 **线上 /openapi.json 和仓库里那份
不是同一个东西** —— 线上没有 cookieAuth、没有 SSE media type，而交接文档写着「两者
同源」。前端顺手用线上那份就拿回未修复版。现在两条路都走这一个函数，物理上不可能分家。

补的四件事，全部由代码推导，没有手写清单:
① security + 401: 走 **依赖树内省** 精确区分「必须登录 (current_user)」和
   「登录更好 (current_user_optional)」—— 靠路径前缀猜会猜错。
② 摘掉泄漏的 lp_session 参数: 它是 httpOnly cookie，客户端根本传不了，
   却被 FastAPI 当成 154 个操作的可填 cookie 参数暴露出去，codegen 产物是坏的。
③ 两个流式接口的响应: StreamingResponse 推不出模型，FastAPI 填的是
   application/json + 空 schema，而整个游戏就在那条流里。
④ servers: 缺了它 codegen 出来的客户端 baseURL 是空的。
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

_ROUTERS = Path(__file__).resolve().parent / "routers"
_ENGINE = Path(__file__).resolve().parent / "engine"

SSE_PATHS = ("/api/v1/runs/{run_id}/play", "/api/v1/runs/{run_id}/confront")

_METHODS = ("get", "post", "put", "patch", "delete", "head", "options")


# ── ① SSE 事件目录 ────────────────────────────────────────────────────────────
def sse_catalog() -> list[dict[str, Any]]:
    """把主循环推的 SSE 事件抽成目录 (AST，不走正则 —— 保证抽全且不误伤同名字符串)。"""
    src = _ROUTERS / "runs.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    found: dict[str, dict] = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and getattr(node.func, "id", "") == "_event"
                and node.args and isinstance(node.args[0], ast.Dict)):
            continue
        d = node.args[0]
        name = next((v.value for k, v in zip(d.keys, d.values)
                     if isinstance(k, ast.Constant) and k.value == "event"
                     and isinstance(v, ast.Constant)), None)
        if not name:
            continue
        e = found.setdefault(name, {"event": name, "payload_keys": [], "lines": []})
        for k in d.keys:
            if isinstance(k, ast.Constant) and isinstance(k.value, str) \
                    and k.value != "event" and k.value not in e["payload_keys"]:
                e["payload_keys"].append(k.value)
        e["lines"].append(node.lineno)
    for e in found.values():
        e["lines"] = sorted(e["lines"])
    # 🔴 token 是最高频的事件, 而它的载荷是**嵌套对象**不是字符串 —— 只给外层键名
    #    会让前端写出 draft += ev.t, 屏幕上满是 [object Object]。把内层形状也抽出来。
    inner = _token_shape()
    if inner and "token" in found:
        found["token"]["payload_shape"] = {"t": inner}
    return [found[k] for k in sorted(found)]


def _token_shape() -> dict[str, Any] | None:
    """从引擎里的 `yield ("token", {...})` 抽出 token 载荷的真实字段。"""
    keys: set[str] = set()
    for f in ("runtime.py", "qwen.py", "llm.py"):
        p = _ENGINE / f
        if not p.exists():
            continue
        for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if not (isinstance(node, ast.Yield) and isinstance(node.value, ast.Tuple)
                    and len(node.value.elts) == 2):
                continue
            tag, payload = node.value.elts
            if not (isinstance(tag, ast.Constant) and tag.value == "token"):
                continue
            if isinstance(payload, ast.Dict):
                keys |= {k.value for k in payload.keys
                         if isinstance(k, ast.Constant) and isinstance(k.value, str)}
    if not keys:
        return None
    return {
        "type": "object",
        "description": "⚠️ 是对象不是字符串。text 是**增量片段**(append 不是替换); "
                       "kind/speaker 会在一次推流中途翻转 —— 前端必须按 (kind, speaker) "
                       "分气泡各自维护草稿。beat 事件到达时用完整 beat 替换该段草稿。",
        "properties": {
            "text": {"type": "string", "description": "增量文本片段"},
            "kind": {"type": "string", "enum": ["narration", "speech"],
                     "description": "旁白 / 台词，流中途会翻转"},
            "speaker": {"type": "string", "description": "说话人名，旁白时为空串"},
        },
        "x-extracted-keys": sorted(keys),
    }


# ── ② 依赖树内省: 谁必须登录, 谁登录更好 ──────────────────────────────────────
def _auth_kind(route: Any) -> str | None:
    """返回 'required' / 'optional' / None —— 走 dependant 树, 不靠路径猜。"""
    from .deps import current_user, current_user_optional
    seen, stack = set(), [getattr(route, "dependant", None)]
    kinds = set()
    while stack:
        d = stack.pop()
        if d is None or id(d) in seen:
            continue
        seen.add(id(d))
        call = getattr(d, "call", None)
        if call is current_user:
            kinds.add("required")
        elif call is current_user_optional:
            kinds.add("optional")
        stack.extend(getattr(d, "dependencies", []) or [])
    return "required" if "required" in kinds else ("optional" if kinds else None)


def _route_auth_map(app: Any) -> dict[tuple[str, str], str]:
    """{(path, method): 'required'|'optional'} —— method 小写。"""
    out: dict[tuple[str, str], str] = {}
    for r in getattr(app, "routes", []):
        if not hasattr(r, "dependant") or not getattr(r, "methods", None):
            continue
        kind = _auth_kind(r)
        if not kind:
            continue
        for m in r.methods:
            out[(r.path, m.lower())] = kind
    return out


# ── ③ 主入口 ─────────────────────────────────────────────────────────────────
def enrich(spec: dict[str, Any], app: Any, cookie_name: str = "lp_session",
           base_url: str = "") -> dict[str, Any]:
    comp = spec.setdefault("components", {})
    comp.setdefault("securitySchemes", {})["cookieAuth"] = {
        "type": "apiKey", "in": "cookie", "name": cookie_name,
        "description": f"登录/注册后服务端下发的 httpOnly 会话 cookie ({cookie_name})。"
                       "httpOnly 意味着 JS 读不到它，只能靠浏览器自动带："
                       "浏览器端 fetch 必须写 credentials:'include'。"
                       "samesite=lax → 跨站 fetch 不会带上它，见 FRONTEND.md。",
    }
    comp.setdefault("schemas", {})["ErrorEnvelope"] = {
        "type": "object", "title": "ErrorEnvelope",
        "description": "全站错误体。detail 多数是给玩家看的中文短句，"
                       "少数场合是结构化对象 —— 前端渲染前要判类型，别直接当字符串拼。",
        "properties": {"detail": {"description": "字符串或对象"}},
    }
    if base_url:
        spec["servers"] = [{"url": base_url, "description": "生产 (裸 HTTP)"}]

    auth = _route_auth_map(app)
    cat = sse_catalog()
    names = ", ".join(e["event"] for e in cat)

    for path, item in (spec.get("paths") or {}).items():
        for method, op in list(item.items()):
            if method not in _METHODS or not isinstance(op, dict):
                continue
            # ② 摘掉泄漏的会话 cookie 参数
            params = op.get("parameters")
            if params:
                kept = [p for p in params if p.get("name") != cookie_name]
                if kept:
                    op["parameters"] = kept
                else:
                    op.pop("parameters", None)
            # ① security + 401
            kind = auth.get((path, method))
            if kind:
                op["security"] = [{"cookieAuth": []}]
                if kind == "required":
                    op.setdefault("responses", {}).setdefault("401", {
                        "description": "未登录 / 会话失效。body 是 ErrorEnvelope。",
                        "content": {"application/json": {
                            "schema": {"$ref": "#/components/schemas/ErrorEnvelope"}}},
                    })
                else:
                    op["x-auth"] = "optional — 未登录返回公共视图，永不 401"
            # ③ 流式接口的响应
            if path in SSE_PATHS and method == "post":
                op["responses"]["200"] = {
                    "description": (
                        f"SSE 逐拍推流。每帧一行 `data: {{...}}`，空行分帧，"
                        f"帧内 `event` 字段区分类型；共 {len(cat)} 种：{names}。"
                        "字段明细见 packages/contract/sse-events.json。\n\n"
                        "⚠️ EventSource 用不了（只支持 GET 且不能带 body），"
                        "须 fetch + ReadableStream 自己分帧。\n"
                        "⚠️ 这条流**不压缩**（SSE 被显式排除在 gzip 之外）。\n"
                        "⚠️ 出错是**带内**传递的：引擎中途挂掉仍然是 HTTP 200，"
                        "错误会伪装成一条正文以 `[出错]` 开头的 beat 送出来。"
                        "而 401/409/429 则是普通 JSON 响应 —— "
                        "所以读流之前必须先判 `res.ok`，否则会把错误体当 SSE 解析、"
                        "永远等不到 done、输入框永久锁死。"),
                    "content": {"text/event-stream": {"schema": {"type": "string"}}},
                }
                op["x-sse-events"] = [e["event"] for e in cat]
    return spec


def install(app: Any, cookie_name: str = "lp_session", base_url: str = "") -> None:
    """把增强挂到 app.openapi 上 —— 线上 /openapi.json 与导出的文件从此同一个函数。"""
    from fastapi.openapi.utils import get_openapi

    def _custom() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema
        spec = get_openapi(title=app.title, version=app.version,
                           description=app.description, routes=app.routes)
        app.openapi_schema = enrich(spec, app, cookie_name, base_url)
        return app.openapi_schema

    app.openapi = _custom
