from fastapi import APIRouter, Cookie, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_user
from ..security import read_session_token
from ..models import Fragment as FragmentModel
from ..models import Secret as SecretModel
from ..models import Story as StoryModel
from ..models import StorySnapshot, User
from ..schemas import (
    PublishResult,
    Secret,
    SecretInput,
    Story,
    StoryCard,
    StoryCardPage,
    StoryInput,
)

router = APIRouter(prefix="/stories", tags=["stories"])


# ── converters ────────────────────────────────────────────
def _completion(s: StoryModel) -> float:
    checks = [
        bool(s.title and s.title != "Untitled"),
        bool(s.synopsis),
        bool(s.characters),
        bool(s.acts),
        bool(s.secrets),
    ]
    return round(sum(checks) / len(checks), 2)


def _to_story(s: StoryModel) -> Story:
    return Story(
        id=s.id,
        title=s.title,
        cover_url=s.cover_url,
        one_liner=s.one_liner,
        synopsis=s.synopsis,
        world_long=s.world_long,
        relations_overview=s.relations_overview,
        world_facts=s.world_facts,
        trope_tags=s.trope_tags or [],
        mature=bool(s.mature),
        visibility=s.visibility,
        status=s.status,
        version=s.version,
        characters=s.characters or [],
        acts=s.acts or [],
        endings=s.endings or [],
        locations=s.locations or [],
        completion=_completion(s),
    )


def _to_card(s: StoryModel) -> StoryCard:
    return StoryCard(
        id=s.id,
        title=s.title,
        cover_url=s.cover_url,
        one_liner=s.one_liner or (s.synopsis[:120] if s.synopsis else None),
        trope_tags=s.trope_tags or [],
    )


def _to_secret(sec: SecretModel) -> Secret:
    return Secret.model_validate(
        {
            "id": sec.id,
            "character_id": sec.character_id,
            "title": sec.title,
            "sensitivity": sec.sensitivity,
            "fragments": [
                {
                    "id": f.id,
                    "layer": f.layer,
                    "content": f.content,
                    "retrieval_key": f.retrieval_key,
                    "known_by_character_ids": f.known_by_character_ids or [],
                    "unlock": f.unlock or {},
                }
                for f in sec.fragments
            ],
        }
    )


def _own_story(story_id: str, user: User, db: Session) -> StoryModel:
    s = db.get(StoryModel, story_id)
    if not s or s.owner_id != user.id:
        raise HTTPException(404, "story not found")
    return s


# ── discover + CRUD ───────────────────────────────────────
@router.get("", response_model=StoryCardPage)
def discover(
    tags: list[str] = Query(default=[]),
    cursor: str | None = None,
    db: Session = Depends(get_db),
):
    q = db.query(StoryModel).filter(
        StoryModel.visibility == "public", StoryModel.status == "published"
    )
    rows = q.order_by(StoryModel.updated_at.desc()).limit(50).all()
    if tags:
        rows = [s for s in rows if set(tags) & set(s.trope_tags or [])]
    return StoryCardPage(items=[_to_card(s) for s in rows], next_cursor=None)


@router.post("", status_code=201, response_model=Story)
def create_story(
    body: StoryInput, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    data = body.model_dump(exclude_unset=True)
    data.pop("characters", None)
    data.pop("acts", None)
    data.pop("endings", None)
    data.pop("locations", None)
    s = StoryModel(
        owner_id=user.id,
        characters=[c.model_dump() for c in (body.characters or [])],
        acts=[a.model_dump() for a in (body.acts or [])],
        endings=[e.model_dump() for e in (body.endings or [])],
        locations=[l.model_dump() for l in (body.locations or [])],
        **data,
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return _to_story(s)


@router.get("/{story_id}", response_model=Story)
def get_story(
    story_id: str,
    db: Session = Depends(get_db),
    lp_session: str | None = Cookie(default=None),
):
    s = db.get(StoryModel, story_id)
    if not s:
        raise HTTPException(404, "story not found")
    # Public sees the published story; only the author may view an unpublished draft.
    if s.visibility != "public" or s.status != "published":
        viewer_id = read_session_token(lp_session) if lp_session else None
        if viewer_id != s.owner_id:
            raise HTTPException(404, "story not found")
    return _to_story(s)


@router.patch("/{story_id}", response_model=Story)
def update_story(
    story_id: str,
    body: StoryInput,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    s = _own_story(story_id, user, db)
    data = body.model_dump(exclude_unset=True)
    if "characters" in data:
        s.characters = [c if isinstance(c, dict) else c.model_dump() for c in data.pop("characters")]
    if "acts" in data:
        s.acts = [a if isinstance(a, dict) else a.model_dump() for a in data.pop("acts")]
    if "endings" in data:
        s.endings = [e if isinstance(e, dict) else e.model_dump() for e in data.pop("endings")]
    if "locations" in data:
        s.locations = [l if isinstance(l, dict) else l.model_dump() for l in data.pop("locations")]
    for k, v in data.items():
        setattr(s, k, v)
    db.commit()
    return _to_story(s)


@router.delete("/{story_id}", status_code=204)
def delete_story(story_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    s = _own_story(story_id, user, db)
    db.delete(s)
    db.commit()


@router.post("/{story_id}/publish", response_model=PublishResult)
def publish(story_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    s = _own_story(story_id, user, db)
    new_version = s.version + 1
    snapshot_content = {
        "story": _to_story(s).model_dump(),
        "secrets": [_to_secret(sec).model_dump() for sec in s.secrets],
    }
    snapshot_content["story"]["version"] = new_version
    db.add(
        StorySnapshot(story_id=s.id, version=new_version, content=snapshot_content)
    )
    s.version = new_version
    s.status = "published"
    db.commit()
    return PublishResult(story_id=s.id, version=new_version)


@router.post("/{story_id}/enrich")
def enrich(story_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """智能增强: auto-generate a background-lore block for each character (detects IP /
    fills in era & world knowledge) and store it on the story. If the story is already
    published, the latest snapshot's content is refreshed so new runs pick it up.
    Sourced from the model (no live web search until a search key is configured)."""
    from ..engine.qwen import generate_knowledge

    s = _own_story(story_id, user, db)
    world = " ".join(filter(None, [s.world_long, s.synopsis, s.one_liner]))[:600]
    chars = [dict(c) for c in (s.characters or [])]
    enriched = 0
    for c in chars:
        profile = " ".join(filter(None, [c.get("role"), c.get("persona_text"), c.get("background")]))
        kn = generate_knowledge(c.get("name", ""), profile, world)
        if kn:
            c["knowledge"] = kn
            enriched += 1
    s.characters = chars
    # keep the published snapshot in sync so live runs see the new knowledge
    if s.status == "published" and s.version:
        snap = (
            db.query(StorySnapshot)
            .filter(StorySnapshot.story_id == s.id, StorySnapshot.version == s.version)
            .first()
        )
        if snap:
            content = dict(snap.content or {})
            content["story"] = _to_story(s).model_dump()
            content["story"]["version"] = s.version
            snap.content = content
    db.commit()
    return {"story_id": s.id, "characters": len(chars), "enriched": enriched}


# ── secrets ───────────────────────────────────────────────
@router.get("/{story_id}/secrets", response_model=list[Secret])
def list_secrets(story_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    s = _own_story(story_id, user, db)
    return [_to_secret(sec) for sec in s.secrets]


@router.post("/{story_id}/secrets", status_code=201, response_model=Secret)
def create_secret(
    story_id: str,
    body: SecretInput,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    s = _own_story(story_id, user, db)
    sec = SecretModel(
        story_id=s.id,
        character_id=body.character_id,
        title=body.title,
        sensitivity=body.sensitivity,
    )
    sec.fragments = [
        FragmentModel(
            layer=f.layer,
            content=f.content,
            retrieval_key=f.retrieval_key,
            known_by_character_ids=f.known_by_character_ids,
            unlock=f.unlock.model_dump(),
        )
        for f in body.fragments
    ]
    db.add(sec)
    db.commit()
    db.refresh(sec)
    return _to_secret(sec)


def _own_secret(story_id: str, secret_id: str, user: User, db: Session) -> SecretModel:
    s = _own_story(story_id, user, db)
    sec = db.get(SecretModel, secret_id)
    if not sec or sec.story_id != s.id:
        raise HTTPException(404, "secret not found")
    return sec


@router.patch("/{story_id}/secrets/{secret_id}", response_model=Secret)
def update_secret(
    story_id: str,
    secret_id: str,
    body: SecretInput,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    sec = _own_secret(story_id, secret_id, user, db)
    sec.character_id = body.character_id
    sec.title = body.title
    sec.sensitivity = body.sensitivity
    # Replace fragments wholesale (M1 simplicity).
    sec.fragments = [
        FragmentModel(
            layer=f.layer,
            content=f.content,
            retrieval_key=f.retrieval_key,
            known_by_character_ids=f.known_by_character_ids,
            unlock=f.unlock.model_dump(),
        )
        for f in body.fragments
    ]
    db.commit()
    db.refresh(sec)
    return _to_secret(sec)


@router.delete("/{story_id}/secrets/{secret_id}", status_code=204)
def delete_secret(
    story_id: str,
    secret_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    sec = _own_secret(story_id, secret_id, user, db)
    db.delete(sec)
    db.commit()
