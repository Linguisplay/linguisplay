from fastapi import APIRouter, Depends, HTTPException
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
