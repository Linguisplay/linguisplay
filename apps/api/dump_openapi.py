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


def build() -> dict:
    """⚠️ 直接吃 app.openapi() —— 增强逻辑住在 app/openapi_ext.py, 线上那个端点走的
    是同一个函数。以前这里私藏过一份增强, 结果线上 /openapi.json 和这个文件分了家,
    而交接文档还写着「两者同源」(2026-08-14 对抗性核查实锤)。别再在这里加逻辑。"""
    from app.main import app
    return app.openapi()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只比对, 不写盘")
    a = ap.parse_args()
    spec = build()
    text = json.dumps(spec, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    from app.openapi_ext import sse_catalog
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
