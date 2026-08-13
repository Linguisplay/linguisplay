from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_user
from ..models import Persona as PersonaModel
from ..models import User
from ..schemas import Persona, PersonaInput

router = APIRouter(prefix="/personas", tags=["personas"])


def _to_schema(p: PersonaModel) -> Persona:
    return Persona(
        id=p.id,
        name=p.name,
        pronouns=p.pronouns,
        pronouns_custom=p.pronouns_custom,
        tagline=p.tagline,
        background=p.background,
        avatar_url=p.avatar_url,
        is_default=p.is_default,
    )


def _own(persona_id: str, user: User, db: Session) -> PersonaModel:
    p = db.get(PersonaModel, persona_id)
    if not p or p.owner_id != user.id:
        raise HTTPException(404, "persona not found")
    return p


@router.get("", response_model=list[Persona])
def list_personas(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.query(PersonaModel).filter(PersonaModel.owner_id == user.id).all()
    return [_to_schema(p) for p in rows]


@router.post("", status_code=201, response_model=Persona)
def create_persona(
    body: PersonaInput, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    first = db.query(PersonaModel).filter(PersonaModel.owner_id == user.id).count() == 0
    p = PersonaModel(owner_id=user.id, is_default=first, **body.model_dump())
    db.add(p)
    db.commit()
    db.refresh(p)
    return _to_schema(p)


@router.get("/{persona_id}", response_model=Persona)
def get_persona(persona_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _to_schema(_own(persona_id, user, db))


@router.patch("/{persona_id}", response_model=Persona)
def update_persona(
    persona_id: str,
    body: PersonaInput,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    p = _own(persona_id, user, db)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(p, k, v)
    db.commit()
    return _to_schema(p)


@router.delete("/{persona_id}", status_code=204)
def delete_persona(
    persona_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    p = _own(persona_id, user, db)
    db.delete(p)
    db.commit()


@router.post("/{persona_id}/set-default")
def set_default(persona_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = _own(persona_id, user, db)
    db.query(PersonaModel).filter(PersonaModel.owner_id == user.id).update(
        {PersonaModel.is_default: False}
    )
    p.is_default = True
    db.commit()
    return {"ok": True}


# ── 🧩 对齐包A: 玩家自己的脸 (设计稿 03_CreateCharacter: add a face / generate) ──
# 上传/生成从前只挂 角色卡·剧本角色·run内涌现 三处, persona 偏偏没有 ——
# 管线全部复用那三处的: 同一张验图、同一个瘦身、同一条生图队列。


@router.post("/{persona_id}/avatar")
async def upload_avatar(persona_id: str, file: UploadFile = File(...),
                        user: User = Depends(current_user), db: Session = Depends(get_db)):
    from ..engine.gal import shrink_jpg
    from .stories import _media_dir, _sniff_image
    p = _own(persona_id, user, db)
    data = await file.read()
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(413, "图片太大（上限 5MB）")
    if not _sniff_image(data):
        raise HTTPException(415, "只支持 JPG / PNG / WebP 图片")
    path = _media_dir("avatar") / f"{persona_id}.jpg"
    path.write_bytes(shrink_jpg(data, quality=82, max_side=1024))
    p.avatar_url = f"/scene/avatar/{persona_id}.jpg"
    db.commit()
    return {"avatar_url": p.avatar_url}


# 🧊 重画冷却 (复审: 生图是计费调用, 一个账号裸 loop 就是无上限烧钱)。进程内
# 账本, 与 run 内背景重画的 60s 冷却同款口径。
_GEN_LAST: dict[str, float] = {}
_GEN_COOLDOWN_S = 60


@router.post("/{persona_id}/gen_avatar")
def gen_avatar(persona_id: str,
               user: User = Depends(current_user), db: Session = Depends(get_db)):
    """AI 画一张玩家小像。没有剧本上下文 → 不吃任何画风圣经, 用中性的肖像口径;
    种子钉在 persona id 上 — 重画不换人。排队后台画, 约十几秒, 前端轮询 URL
    (轮询记得带 cache-buster: /scene 静态带 24h 缓存头)。
    ⚠️ 不先删旧图 — 老脸留到新字节落盘那一刻 (overwrite 旗), 生成失败不丢脸。"""
    import time as _time
    import zlib

    from .runs import _AV_DIR, _enqueue_image
    p = _own(persona_id, user, db)
    now = _time.monotonic()
    if now - _GEN_LAST.get(user.id, -1e9) < _GEN_COOLDOWN_S:
        raise HTTPException(429, "画笔还热着——过一分钟再重画")
    _GEN_LAST[user.id] = now
    # 玩家人设走同一份取景 (无剧本画风/无世界背景 → 两头留空), 卡面字段对位过去
    from ..engine.sprites import portrait_prompt
    prompt = portrait_prompt({"name": p.name, "role": (p.tagline or "")[:80],
                              "persona_text": (p.background or "")[:160]}, "", "")
    path = _AV_DIR / f"{persona_id}.jpg"
    _enqueue_image(prompt, path, "768*768", overwrite=True,
                   seed=zlib.crc32(persona_id.encode("utf-8")) % 2_000_000_000)
    p.avatar_url = f"/scene/avatar/{persona_id}.jpg"
    db.commit()
    return {"queued": True, "avatar_url": p.avatar_url}
