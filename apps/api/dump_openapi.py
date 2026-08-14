# -*- coding: utf-8 -*-
"""📜 把当前代码的 OpenAPI 契约导出到 packages/contract/openapi.json。

为什么要有这个脚本 (Yi 2026-08-14):
前端要对接, 最自然的动作是「把契约文件发过去」。而仓库里那份手写的
packages/contract/openapi.yaml 停在 2026-06-25 的初始提交, 37 个接口,
线上真实是 135 个 —— 手写契约必然漂, 且漂了不报错。

所以契约改成**生成物**: 它由代码推导, 不由人维护。改了路由就重跑这个脚本,
diff 会把接口变更摆在 code review 里 (手写文件做不到这件事)。

用法:
    python dump_openapi.py            # 写入 packages/contract/openapi.json
    python dump_openapi.py --check    # 只校验是否与代码一致 (CI/提交前用, 不写盘)
"""
import argparse
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./dev.db")
os.environ.setdefault("JWT_SECRET", "dev")

_CONTRACT = Path(__file__).resolve().parents[2] / "packages" / "contract"
OUT = _CONTRACT / "openapi.json"
SSE_OUT = _CONTRACT / "sse-events.json"


def sse_catalog() -> list[dict]:
    """🔴 把主循环推的 SSE 事件抽成目录。

    为什么必须单独抽 (Yi 2026-08-14 追问「确定这样就可以吗」):
    /play 和 /confront 是 StreamingResponse, FastAPI 推不出响应模型 —— 生成的契约里
    这两个接口写着 `application/json` + `schema: {}`, 既是错的 content-type 又没有
    任何字段。**整个游戏就在这条流里**, 前端照契约施工等于拿到一片空白。

    走 AST 而不是正则: 事件是 `_event({"event": "beat", "beat": ...})` 这种字面量,
    AST 能保证抽全且不误伤字符串里的同名词。
    """
    import ast
    src = Path(__file__).resolve().parent / "app" / "routers" / "runs.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    found: dict[str, dict] = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and getattr(node.func, "id", "") == "_event"
                and node.args and isinstance(node.args[0], ast.Dict)):
            continue
        d = node.args[0]
        keys = [k.value for k in d.keys
                if isinstance(k, ast.Constant) and isinstance(k.value, str)]
        name = next((v.value for k, v in zip(d.keys, d.values)
                     if isinstance(k, ast.Constant) and k.value == "event"
                     and isinstance(v, ast.Constant)), None)
        if not name:
            continue
        e = found.setdefault(name, {"event": name, "payload_keys": [], "lines": []})
        for k in keys:
            if k != "event" and k not in e["payload_keys"]:
                e["payload_keys"].append(k)
        e["lines"].append(node.lineno)
    return [found[k] for k in sorted(found)]


def build() -> dict:
    from app.main import app
    spec = app.openapi()
    # 🔑 cookie 认证补进 spec: FastAPI 不会从 Cookie(...) 依赖自动推出 securityScheme,
    # 于是生成的契约里 securitySchemes 是空的 —— 前端和 codegen 都看不出要怎么登录。
    comp = spec.setdefault("components", {})
    comp.setdefault("securitySchemes", {})["cookieAuth"] = {
        "type": "apiKey", "in": "cookie", "name": "lp_session",
        "description": "登录/注册后由服务端下发的 httpOnly 会话 cookie (samesite=lax, 30 天)。"
                       "浏览器端 fetch 必须带 credentials:'include'。",
    }
    # 🔴 把两个流式接口的响应改对: FastAPI 给 StreamingResponse 填的是
    # application/json + 空 schema, 前端照着建不出游戏。
    cat = sse_catalog()
    names = ", ".join(e["event"] for e in cat)
    for p in ("/api/v1/runs/{run_id}/play", "/api/v1/runs/{run_id}/confront"):
        op = ((spec.get("paths") or {}).get(p) or {}).get("post")
        if not op:
            continue
        op["responses"]["200"] = {
            "description": f"SSE 逐拍推流。每帧一行 `data: {{...}}`，空行分帧；"
                           f"帧内 `event` 字段区分类型，共 {len(cat)} 种：{names}。"
                           "字段明细见 packages/contract/sse-events.json。"
                           "⚠️ EventSource 用不了（只支持 GET），须 fetch + ReadableStream。",
            "content": {"text/event-stream": {"schema": {"type": "string"}}},
        }
        op["x-sse-events"] = [e["event"] for e in cat]
    return spec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只比对, 不写盘")
    a = ap.parse_args()
    spec = build()
    text = json.dumps(spec, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    cat = sse_catalog()
    sse_text = json.dumps(cat, ensure_ascii=False, indent=2) + "\n"
    n = len(spec.get("paths") or {})
    if a.check:
        bad = [f for f, t in ((OUT, text), (SSE_OUT, sse_text))
               if (f.read_text(encoding="utf-8") if f.exists() else "") != t]
        if bad:
            print("✗ 契约与代码不一致 —— 跑 python dump_openapi.py 重新导出: "
                  + "、".join(f.name for f in bad))
            return 1
        print(f"✓ 契约与代码一致 ({n} 个接口, {len(cat)} 种 SSE 事件)")
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    SSE_OUT.write_text(sse_text, encoding="utf-8")
    print(f"✓ {OUT.name} —— {n} 个接口, "
          f"{len((spec.get('components') or {}).get('schemas') or {})} 个 schema")
    print(f"✓ {SSE_OUT.name} —— {len(cat)} 种 SSE 事件")
    return 0


if __name__ == "__main__":
    sys.exit(main())
