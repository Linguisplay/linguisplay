"""📚 角色卡库 — characters that live OUTSIDE any story (Character.AI-style).

A card is authored once (persona / voice / example lines / avatar), then imported
into any 剧本 from the studio. Import is a COPY performed by the client: the studio
appends the card's portable fields to story.characters with a fresh id and
`source_card_id` provenance — so editing the card later never mutates stories (or
published snapshots) that already imported it. Story-binding fields (schedule,
ties, home location, presence…) are authored after import, per story.
"""

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_user
from ..models import CharacterCard as CardModel
from ..models import User
from ..schemas import CharacterCard, CharacterCardInput
from .stories import _media_dir, _sniff_image

router = APIRouter(prefix="/cards", tags=["cards"])


def _to_schema(c: CardModel) -> CharacterCard:
    body = {k: v for k, v in (c.content or {}).items()
            if k in CharacterCardInput.model_fields}
    return CharacterCard(id=c.id, name=c.name, avatar_url=c.avatar_url,
                         visibility=c.visibility, updated_at=c.updated_at,
                         **{k: v for k, v in body.items() if k not in ("name", "visibility")})


def _own(card_id: str, user: User, db: Session) -> CardModel:
    c = db.get(CardModel, card_id)
    if not c or c.owner_id != user.id:
        raise HTTPException(404, "没有这张角色卡")
    return c


def _content_of(body: CharacterCardInput) -> dict:
    data = body.model_dump()
    data.pop("name", None)
    data.pop("visibility", None)
    return data


@router.get("", response_model=list[CharacterCard])
def list_cards(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = (db.query(CardModel).filter(CardModel.owner_id == user.id)
            .order_by(CardModel.updated_at.desc()).all())
    return [_to_schema(c) for c in rows]


@router.get("/square", response_model=list[CharacterCard])
def card_square(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """🌐 角色卡广场: everyone's PUBLIC cards, newest first. Import/clone is a copy —
    the square never hands out edit rights, and later edits by the author don't
    reach anyone who already took the card."""
    rows = (db.query(CardModel).filter(CardModel.visibility == "public")
            .order_by(CardModel.updated_at.desc()).limit(60).all())
    authors = {u.id: (u.display_name or "匿名作者")
               for u in db.query(User).filter(
                   User.id.in_({c.owner_id for c in rows})).all()} if rows else {}
    out = []
    for c in rows:
        card = _to_schema(c)
        card.author = authors.get(c.owner_id, "匿名作者")
        card.mine = c.owner_id == user.id
        out.append(card)
    return out


@router.post("", status_code=201, response_model=CharacterCard)
def create_card(body: CharacterCardInput,
                user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not (body.name or "").strip():
        raise HTTPException(400, "角色得有个名字")
    c = CardModel(owner_id=user.id, name=body.name.strip()[:120],
                  visibility=body.visibility, content=_content_of(body))
    db.add(c)
    db.commit()
    db.refresh(c)
    return _to_schema(c)


@router.get("/{card_id}", response_model=CharacterCard)
def get_card(card_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Own cards always; anyone's card when it's shared to the 广场 (read-only copy source)."""
    c = db.get(CardModel, card_id)
    if not c or (c.owner_id != user.id and c.visibility != "public"):
        raise HTTPException(404, "没有这张角色卡")
    card = _to_schema(c)
    card.mine = c.owner_id == user.id
    return card


@router.patch("/{card_id}", response_model=CharacterCard)
def update_card(card_id: str, body: CharacterCardInput,
                user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = _own(card_id, user, db)
    if (body.name or "").strip():
        c.name = body.name.strip()[:120]
    c.visibility = body.visibility
    c.content = _content_of(body)
    db.commit()
    db.refresh(c)
    return _to_schema(c)


@router.delete("/{card_id}", status_code=204)
def delete_card(card_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = _own(card_id, user, db)
    db.delete(c)
    db.commit()


@router.post("/{card_id}/avatar")
async def upload_avatar(card_id: str, file: UploadFile = File(...),
                        user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Card portrait. Same validation & id-keyed path as story media; a story character
    imported from this card carries the URL, so the face travels with the import."""
    c = _own(card_id, user, db)
    data = await file.read()
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(413, "图片太大（上限 5MB）")
    if not _sniff_image(data):
        raise HTTPException(415, "只支持 JPG / PNG / WebP 图片")
    from ..engine.gal import shrink_jpg
    path = _media_dir("avatar") / f"{card_id}.jpg"
    path.write_bytes(shrink_jpg(data, quality=82, max_side=1024))
    c.avatar_url = f"/scene/avatar/{card_id}.jpg"
    db.commit()
    return {"avatar_url": c.avatar_url}


@router.post("/{card_id}/enrich", response_model=CharacterCard)
def enrich_card(card_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """智能增强 for a single card: auto-generate the background-lore knowledge block
    (IP detection / era / relations / signature details). No key configured → no-op."""
    from ..engine.qwen import generate_knowledge

    c = _own(card_id, user, db)
    content = dict(c.content or {})
    profile = " ".join(filter(None, [content.get("role"), content.get("persona_text"),
                                     content.get("background")]))
    kn = generate_knowledge(c.name, profile, "")
    if kn:
        content["knowledge"] = kn
        c.content = content
        db.commit()
        db.refresh(c)
    return _to_schema(c)
