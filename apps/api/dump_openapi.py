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

OUT = Path(__file__).resolve().parents[2] / "packages" / "contract" / "openapi.json"


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
    return spec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只比对, 不写盘")
    a = ap.parse_args()
    spec = build()
    text = json.dumps(spec, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    n = len(spec.get("paths") or {})
    if a.check:
        old = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if old != text:
            print(f"✗ 契约与代码不一致 —— 跑 python dump_openapi.py 重新导出 ({n} 个接口)")
            return 1
        print(f"✓ 契约与代码一致 ({n} 个接口)")
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    print(f"✓ {OUT.relative_to(OUT.parents[2])} 已导出 —— {n} 个接口, "
          f"{len((spec.get('components') or {}).get('schemas') or {})} 个 schema")
    return 0


if __name__ == "__main__":
    sys.exit(main())
