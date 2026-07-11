# -*- coding: utf-8 -*-
"""🎀 galgame 生成器 API (docs/galgame-maker.md P0).

POST /gal            — start a build (A 档: paste the story text). Quota: beta 1
                       READY work per user; a failed build never burns the quota.
GET  /gal/mine       — my works (status + progress for the builder console)
GET  /gal/{id}/status— build progress (the progress page polls this)
GET  /gal/{id}/script— the full compiled script + manifest (owner-only in P0)
POST /gal/{id}/rebuild — re-run the build (fills missing art; resumes a failure)
"""
import threading
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import SessionLocal, get_db
from ..deps import current_user
from ..engine import gal as gal_mod
from ..models import Story, User

router = APIRouter(prefix="/gal", tags=["gal"])

_BUILDING: set = set()   # in-process guard: one build thread per work
_BUILD_LOCK = threading.Lock()


class GalCreate(BaseModel):
    title: str = ""
    source_text: str
    art_style: str = ""   # 画风预设文案 (P0: free text; preset menu later)
    mature: bool = False  # 🔞 成人拍编译许可 (adult beats render as bg+textbox)


def _spawn_build(work_id: str) -> bool:
    with _BUILD_LOCK:
        if work_id in _BUILDING:
            return False
        _BUILDING.add(work_id)

    def _run():
        try:
            gal_mod.build_work(work_id, SessionLocal)
        finally:
            with _BUILD_LOCK:
                _BUILDING.discard(work_id)

    threading.Thread(target=_run, daemon=True).start()
    return True


@router.post("", status_code=201)
def create_work(body: GalCreate, user: User = Depends(current_user),
                db: Session = Depends(get_db)):
    text = (body.source_text or "").strip()
    if len(text) < 200:
        raise HTTPException(400, "故事文本太短了——至少给我两百字，我才画得出人和景")
    mine = db.query(Story).filter(Story.owner_id == user.id, Story.kind == "gal").all()
    if any((s.gal or {}).get("status") == "ready" for s in mine):
        raise HTTPException(403, "beta 期间每人限 1 本已完成的作品")
    if any((s.gal or {}).get("status") in ("queued", "parsing", "compiling", "art")
           for s in mine):
        raise HTTPException(409, "你有一本正在建造中——等它完成或失败后再开新的")
    s = Story(
        id=uuid.uuid4().hex,
        owner_id=user.id,
        kind="gal",
        title=(body.title or "").strip()[:24] or "未命名作品",
        visibility="private",
        status="draft",
        tuning=({"art_style": body.art_style.strip()[:200]} if body.art_style.strip() else {}),
        gal={"status": "queued", "progress": "排队中…",
             "mature": bool(body.mature),
             "source_text": text[:gal_mod.MAX_SOURCE_CHARS]},
    )
    db.add(s)
    db.commit()
    _spawn_build(s.id)
    return {"id": s.id, "status": "queued"}


def _own_work(work_id: str, user: User, db: Session) -> Story:
    s = db.get(Story, work_id)
    if not s or s.owner_id != user.id or s.kind != "gal":
        raise HTTPException(404, "work not found")
    return s


@router.get("/mine")
def my_works(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = (db.query(Story)
            .filter(Story.owner_id == user.id, Story.kind == "gal")
            .order_by(Story.updated_at.desc()).all())
    return [{"id": s.id, "title": s.title,
             "status": (s.gal or {}).get("status"),
             "progress": (s.gal or {}).get("progress", ""),
             "chapters": len((((s.gal or {}).get("script") or {})
                              .get((s.gal or {}).get("protagonist_id")) or {})
                             .get("chapters") or []),
             "endings": len((s.gal or {}).get("endings") or []),
             "cgs": len((((s.gal or {}).get("manifest") or {}).get("cgs")) or []),
             "cover": f"/scene/gal/{s.id}/cover.jpg"
             if ((s.gal or {}).get("manifest") or {}).get("cover") else None}
            for s in rows]


@router.get("/{work_id}/status")
def work_status(work_id: str, user: User = Depends(current_user),
                db: Session = Depends(get_db)):
    s = _own_work(work_id, user, db)
    g = s.gal or {}
    return {"id": s.id, "title": s.title, "status": g.get("status"),
            "progress": g.get("progress", ""),
            "missing": (g.get("manifest") or {}).get("missing", [])}


@router.get("/{work_id}/script")
def work_script(work_id: str, user: User = Depends(current_user),
                db: Session = Depends(get_db)):
    s = _own_work(work_id, user, db)
    g = s.gal or {}
    if g.get("status") != "ready":
        raise HTTPException(409, "还在建造中")
    return {"id": s.id, "title": s.title,
            "protagonist_id": g.get("protagonist_id"),
            "characters": [{"id": c["id"], "name": c["name"]}
                           for c in g.get("characters") or []],
            "scenes": [{"id": x["id"], "name": x["name"]}
                       for x in g.get("scenes") or []],
            "chapters": g.get("chapters") or [],
            "script": g.get("script") or {},
            "endings": g.get("endings") or [],
            "values": g.get("values") or {},
            "mature": bool(g.get("mature")),
            "manifest": g.get("manifest") or {}}


# ── 制作台修订 (blueprint §5): 重画/重编/改字/换画风 ─────────────────────────────
class Redraw(BaseModel):
    kind: str          # sprite | bg | cg | cover
    key: str = ""      # sprite: "c2_喜" / bg: "s1" / cg: beat id / cover: ignored


class Rechapter(BaseModel):
    i: int


class Retext(BaseModel):
    edits: dict        # {beat_id: new_text}


class Restyle(BaseModel):
    art_style: str


def _bump_limit(g: dict, bucket: str, key: str, cap: int) -> None:
    used = (g.setdefault(bucket, {})).get(key, 0)
    if used >= cap:
        raise HTTPException(403, f"这一项的修订次数用完了（上限 {cap} 次）")
    g[bucket][key] = used + 1


@router.post("/{work_id}/redraw")
def redraw(body: Redraw, work_id: str, user: User = Depends(current_user),
           db: Session = Depends(get_db)):
    """重画单张: delete the file, art backfill regenerates only what's missing."""
    s = _own_work(work_id, user, db)
    g = dict(s.gal or {})
    if g.get("status") != "ready":
        raise HTTPException(409, "还在建造中")
    from ..engine.gal import GAL_DIR
    wdir = GAL_DIR / work_id
    files = {"sprite": [wdir / f"{body.key}.webp"],
             "bg": [wdir / f"bg_{body.key}.jpg"],
             "cg": [wdir / f"cg_{body.key}.jpg"],
             "cover": [wdir / "cover.jpg"]}.get(body.kind)
    if not files:
        raise HTTPException(400, "unknown kind")
    _bump_limit(g, "redraws", f"{body.kind}:{body.key}", 3)
    for p in files:
        p.unlink(missing_ok=True)
    g["status"], g["progress"] = "art", "重画中…"
    s.gal = g
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(s, "gal")
    db.commit()
    if not _spawn_build(s.id):
        raise HTTPException(409, "正在建造中")
    return {"ok": True}


@router.post("/{work_id}/rechapter")
def rechapter(body: Rechapter, work_id: str, user: User = Depends(current_user),
              db: Session = Depends(get_db)):
    """重编某章 (保持大纲); values 与结局阈值随之重算。"""
    s = _own_work(work_id, user, db)
    g = dict(s.gal or {})
    if g.get("status") != "ready":
        raise HTTPException(409, "还在建造中")
    _bump_limit(g, "reedits", str(body.i), 2)
    s.gal = g
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(s, "gal")
    db.commit()
    with _BUILD_LOCK:
        if work_id in _BUILDING:
            raise HTTPException(409, "正在建造中")
        _BUILDING.add(work_id)

    def _run():
        try:
            gal_mod.rechapter_work(work_id, SessionLocal, body.i)
        finally:
            with _BUILD_LOCK:
                _BUILDING.discard(work_id)

    threading.Thread(target=_run, daemon=True).start()
    return {"ok": True}


@router.post("/{work_id}/retext")
def retext(body: Retext, work_id: str, user: User = Depends(current_user),
           db: Session = Depends(get_db)):
    """改字零成本: the script is data."""
    s = _own_work(work_id, user, db)
    g = dict(s.gal or {})
    n = 0
    for bid, text in (body.edits or {}).items():
        if gal_mod.set_beat_text(g, str(bid), str(text)):
            n += 1
    if n:
        s.gal = g
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(s, "gal")
        db.commit()
    return {"updated": n}


@router.post("/{work_id}/restyle")
def restyle(body: Restyle, work_id: str, user: User = Depends(current_user),
            db: Session = Depends(get_db)):
    """全本换画风: 一键重刷所有美术 (贵, 限 2 次)。"""
    s = _own_work(work_id, user, db)
    g = dict(s.gal or {})
    if g.get("status") != "ready":
        raise HTTPException(409, "还在建造中")
    _bump_limit(g, "redraws", "restyle", 2)
    s.tuning = {**(s.tuning or {}), "art_style": (body.art_style or "").strip()[:200]}
    from ..engine.gal import GAL_DIR
    wdir = GAL_DIR / work_id
    if wdir.exists():
        for p in wdir.iterdir():
            p.unlink(missing_ok=True)
    g["manifest"] = {"sprites": {}, "bgs": [], "cover": False, "missing": [], "cgs": []}
    g["status"], g["progress"] = "art", "按新画风重绘全部美术…"
    s.gal = g
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(s, "gal")
    db.commit()
    if not _spawn_build(s.id):
        raise HTTPException(409, "正在建造中")
    return {"ok": True}


@router.post("/{work_id}/rebuild")
def rebuild(work_id: str, user: User = Depends(current_user),
            db: Session = Depends(get_db)):
    """Resume/refill: parse+compile results are kept; only missing pieces re-run.
    (build_work skips art files already on disk — the backfill doctrine.)"""
    s = _own_work(work_id, user, db)
    g = dict(s.gal or {})
    # the THREAD guard below is the real lock — a mid-build status with no live
    # thread is an orphan (service restarted mid-build) and must be resumable
    if not (g.get("script") or {}):
        g["status"], g["progress"] = "queued", "重新排队…"   # hard failure → full re-run
    elif (len((g.get("script") or {}).get(g.get("protagonist_id"), {}).get("chapters") or [])
          < len(g.get("chapters") or []) or not g.get("endings")):
        g["status"], g["progress"] = "compiling", "从断点续写章节…"   # text resume
    else:
        g["status"], g["progress"] = "art", "补齐缺失的美术…"
    s.gal = g
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(s, "gal")
    db.commit()
    if not _spawn_build(s.id):
        raise HTTPException(409, "正在建造中")
    return {"id": s.id, "status": g["status"]}
