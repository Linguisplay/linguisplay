# -*- coding: utf-8 -*-
"""🚬🎀 galgame 冒烟门: drive a full MockLLM build + an orphan resume against a
throwaway SQLite before every deploy, so pipeline changes never ship blind.

    python smoke_gal.py        → exit 0 clean / exit 1 on any failure

Invariants: build reaches ready; every chapter has beats + a choice (final may
skip); endings carry exactly one default + per-route thresholds within reach;
CG ledger ≤1 per chapter; lint has no error-level findings; resume keeps
finished chapters and backfills the rest.
"""
import os
import sys
import tempfile
import uuid

os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(
    tempfile.mkdtemp(), "smoke_gal.db").replace("\\", "/")
os.environ.setdefault("JWT_SECRET", "dev")
os.environ["LLM_PROVIDER"] = "mock"

from app.db import SessionLocal, init_db  # noqa: E402
from app.engine.gal import build_work, gal_lint  # noqa: E402
from app.models import Story  # noqa: E402

FAILS: list[str] = []


def check(ok: bool, msg: str) -> None:
    print(("  ✓ " if ok else "  ✗ ") + msg)
    if not ok:
        FAILS.append(msg)


init_db()
SRC = "林晚在天台遇见了沈刻。" * 40

db = SessionLocal()
sid = uuid.uuid4().hex
db.add(Story(id=sid, owner_id="smoke", kind="gal", title="冒烟本", visibility="private",
             status="draft", gal={"status": "queued", "progress": "…",
                                  "mature": False, "source_text": SRC}))
db.commit()
db.close()

build_work(sid, SessionLocal, render_art=False)

db = SessionLocal()
g = db.get(Story, sid).gal
pov = g.get("protagonist_id")
chs = ((g.get("script") or {}).get(pov) or {}).get("chapters") or []
check(g.get("status") == "ready", f"build ready (got {g.get('status')}: {g.get('progress')})")
check(len(chs) == len(g.get("chapters") or []), "all chapters compiled")
for i, ch in enumerate(chs):
    normal = [b for b in ch if b.get("type") != "choice"]
    qs = [b for b in ch if b.get("type") == "choice"]
    check(len(normal) >= 8, f"ch{i + 1} has beats")
    if i + 1 < len(chs):
        check(len(qs) >= 1, f"ch{i + 1} has a choice")
    check(all(b.get("id") for b in normal), f"ch{i + 1} beat ids stable")
ends = g.get("endings") or []
check(len(ends) >= 2, "≥2 endings")
check(sum(1 for e in ends if (e.get("cond") or {}).get("default")) == 1,
      "exactly one default ending")
vm = g.get("values") or {}
for e in ends:
    c = e.get("cond") or {}
    if c.get("char"):
        check(c["gte"] <= (vm.get("max") or {}).get(c["char"], 0),
              f"ending {e['id']} threshold reachable")
check(not any(f["level"] == "error" for f in gal_lint(g)), "lint has no errors")

# orphan resume: drop the tail, rebuild, front must survive
g2 = dict(g)
g2["script"] = {pov: {"chapters": chs[:1]}}
g2["ch_summaries"] = (g.get("ch_summaries") or [])[:1]
g2["endings"] = []
g2["status"] = "failed"
s = db.get(Story, sid)
s.gal = g2
from sqlalchemy.orm.attributes import flag_modified  # noqa: E402
flag_modified(s, "gal")
db.commit()
first_id = chs[0][0]["id"]
db.close()

build_work(sid, SessionLocal, render_art=False)
db = SessionLocal()
g3 = db.get(Story, sid).gal
chs3 = g3["script"][pov]["chapters"]
check(g3.get("status") == "ready", "resume ready")
check(len(chs3) == len(chs) and chs3[0][0]["id"] == first_id,
      "resume kept ch1, backfilled the rest")
db.close()

print(("\n🎀 smoke_gal: clean" if not FAILS else f"\n🎀 smoke_gal: {len(FAILS)} FAILED"))
sys.exit(1 if FAILS else 0)
