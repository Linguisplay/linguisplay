from fastapi import APIRouter, Cookie, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from ..db import get_db
from ..deps import current_user
from ..security import read_session_token
from ..models import Fragment as FragmentModel
from ..models import Secret as SecretModel
from ..models import Story as StoryModel
from ..models import StoryMeta, StorySnapshot, User
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
        language=s.language or "zh",
        cover_url=s.cover_url,
        one_liner=s.one_liner,
        synopsis=s.synopsis,
        world_long=s.world_long,
        relations_overview=s.relations_overview,
        world_facts=s.world_facts,
        style=s.style or "",
        trope_tags=s.trope_tags or [],
        mature=bool(s.mature),
        visibility=s.visibility,
        status=s.status,
        version=s.version,
        characters=s.characters or [],
        acts=s.acts or [],
        endings=s.endings or [],
        locations=s.locations or [],
        tuning=s.tuning or {},
        pressure=s.pressure,
        clock=s.clock,
        phone=s.phone,
        verdict=s.verdict,
        sandbox=s.sandbox,
        completion=_completion(s),
    )


def _to_card(s: StoryModel, secrets_count: int = 0) -> StoryCard:
    return StoryCard(
        id=s.id,
        title=s.title,
        cover_url=s.cover_url,
        one_liner=s.one_liner or (s.synopsis[:120] if s.synopsis else None),
        trope_tags=s.trope_tags or [],
        secrets_count=secrets_count,
        endings_count=len(s.endings or []),
        characters_count=len(s.characters or []),
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
                    "cover": f.cover,
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
    # 🔒 the mystery affordance: how many secrets each story guards (one grouped query)
    from sqlalchemy import func
    counts = dict(db.query(SecretModel.story_id, func.count(SecretModel.id))
                  .filter(SecretModel.story_id.in_([s.id for s in rows] or [""]))
                  .group_by(SecretModel.story_id).all()) if rows else {}
    return StoryCardPage(items=[_to_card(s, counts.get(s.id, 0)) for s in rows],
                         next_cursor=None)


@router.post("", status_code=201, response_model=Story)
def create_story(
    body: StoryInput, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    data = body.model_dump(exclude_unset=True)
    data.pop("characters", None)
    data.pop("acts", None)
    data.pop("endings", None)
    data.pop("locations", None)
    data.pop("tuning", None)
    data.pop("pressure", None)
    data.pop("clock", None)
    data.pop("phone", None)
    data.pop("verdict", None)
    s = StoryModel(
        owner_id=user.id,
        characters=[c.model_dump() for c in (body.characters or [])],
        acts=[a.model_dump() for a in (body.acts or [])],
        endings=[e.model_dump() for e in (body.endings or [])],
        locations=[l.model_dump() for l in (body.locations or [])],
        tuning=body.tuning or {},
        pressure=body.pressure,
        clock=body.clock,
        phone=body.phone,
        verdict=body.verdict,
        **data,
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return _to_story(s)


_PUBLIC_CHAR_KEYS = ("id", "name", "role", "avatar_url", "is_lead", "playable",
                     "presence", "appears_from_act", "relation_default")


def _public_story_view(out: Story) -> Story:
    """SPOILER SHIELD: what a PLAYER may see of a story. The play UI needs names, faces
    and roles — it must never receive the answer key (verdict.correct), ending prose,
    future-act event scripts, or character agendas/bio layers. The pinned run content
    keeps the full story server-side; only this public view is trimmed."""
    out.verdict = None
    out.endings = []
    out.acts = [type(a)(index=a.index, title=a.title) for a in (out.acts or [])]
    out.characters = [type(c)(**{k: getattr(c, k) for k in _PUBLIC_CHAR_KEYS})
                      for c in (out.characters or [])]
    out.pressure = None
    return out


@router.get("/{story_id}", response_model=Story)
def get_story(
    story_id: str,
    db: Session = Depends(get_db),
    lp_session: str | None = Cookie(default=None),
):
    s = db.get(StoryModel, story_id)
    if not s:
        raise HTTPException(404, "story not found")
    viewer_id = read_session_token(lp_session) if lp_session else None
    # Public sees the published story; only the author may view an unpublished draft.
    if s.visibility != "public" or s.status != "published":
        if viewer_id != s.owner_id:
            raise HTTPException(404, "story not found")
    out = _to_story(s)
    if viewer_id != s.owner_id:
        out = _public_story_view(out)
    return out


@router.get("/{story_id}/meta")
def get_story_meta(story_id: str, user: User = Depends(current_user),
                   db: Session = Depends(get_db)):
    """🌱 This player's cross-run progress on one story: the persistent ending gallery,
    earned achievements, and whether NG+ perks are unlocked (any ending reached once)."""
    s = db.get(StoryModel, story_id)
    if not s:
        raise HTTPException(404, "story not found")
    meta = (db.query(StoryMeta)
            .filter(StoryMeta.user_id == user.id, StoryMeta.story_id == story_id).first())
    from ..engine import runtime as _rt
    return {
        "endings_achieved": list(meta.endings_achieved or []) if meta else [],
        "endings_total": len(s.endings or []),
        "achievements": list(meta.achievements or []) if meta else [],
        "runs_ended": int(meta.runs_ended or 0) if meta else 0,
        "ng_plus": bool(meta and (meta.endings_achieved or [])),
        "perks": [{"id": k, **v} for k, v in _rt.PERKS.items()],
        "cards": list(meta.cards or []) if meta else [],
    }


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
    if "tuning" in data:
        s.tuning = data.pop("tuning") or {}
    if "pressure" in data:
        s.pressure = data.pop("pressure")
    if "clock" in data:
        s.clock = data.pop("clock")
    if "phone" in data:
        s.phone = data.pop("phone")
    if "verdict" in data:
        s.verdict = data.pop("verdict")
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


# ── 🧪 story linter: the same logic-rigor checks the seeds run, for the studio ──
@router.get("/{story_id}/lint")
def lint_story_draft(story_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Run the engine's story linter on the CURRENT draft rows (owner only). Returns
    {issues: [{severity, code, where, msg}]} — the studio shows them as a 体检 report."""
    s = _own_story(story_id, user, db)
    from ..engine import logic
    content = {"story": _to_story(s).model_dump(),
               "secrets": [_to_secret(x).model_dump() for x in s.secrets]}
    return {"issues": logic.lint_story(content)}


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
            **({"id": f.id} if f.id else {}),
            layer=f.layer,
            content=f.content,
            retrieval_key=f.retrieval_key,
            known_by_character_ids=f.known_by_character_ids,
            unlock=f.unlock.model_dump(),
            cover=f.cover,
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
            **({"id": f.id} if f.id else {}),
            layer=f.layer,
            content=f.content,
            retrieval_key=f.retrieval_key,
            known_by_character_ids=f.known_by_character_ids,
            unlock=f.unlock.model_dump(),
            cover=f.cover,
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


# ── author media uploads: your own photos for characters, your own backgrounds ──
_MEDIA_ROOT = None


def _media_dir(kind: str):
    """app/static/scene/{avatar|bg} — the SAME paths AI enrichment uses, so the play UI
    needs no changes: uploads simply take precedence by being the file that exists."""
    import pathlib
    global _MEDIA_ROOT
    if _MEDIA_ROOT is None:
        _MEDIA_ROOT = pathlib.Path(__file__).resolve().parents[1] / "static" / "scene"
    d = _MEDIA_ROOT / ("avatar" if kind == "avatar" else "bg")
    d.mkdir(parents=True, exist_ok=True)
    return d


def _sniff_image(data: bytes) -> str | None:
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


@router.post("/{story_id}/upload")
async def upload_media(
    story_id: str,
    kind: str = Form(...),               # "avatar" (character photo) | "bg" (location backdrop)
    target_id: str = Form(...),          # character id / location id in THIS story
    file: UploadFile = File(...),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Author uploads their own image for a character or a location. Validated by magic
    bytes (jpg/png/webp) and size (≤5MB), stored under the id-keyed path the play UI
    already loads; a character upload also writes avatar_url into the story AND its
    latest snapshot so live discovery/new runs show it immediately."""
    s = _own_story(story_id, user, db)
    if kind not in ("avatar", "bg"):
        raise HTTPException(400, "kind 只能是 avatar 或 bg")
    data = await file.read()
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(413, "图片太大（上限 5MB）")
    if not _sniff_image(data):
        raise HTTPException(415, "只支持 JPG / PNG / WebP 图片")
    if kind == "avatar":
        chars = list(s.characters or [])
        c = next((x for x in chars if x.get("id") == target_id), None)
        if not c:
            raise HTTPException(404, "这个剧本里没有该角色")
    else:
        if not any((l.get("id") == target_id) for l in (s.locations or [])):
            raise HTTPException(404, "这个剧本里没有该地点")
    # the play UI loads bg by the fixed `{id}.jpg` convention → always save as .jpg
    # (browsers sniff real content; the extension is just the lookup key)
    path = _media_dir(kind) / f"{target_id}.jpg"
    path.write_bytes(data)
    url = f"/scene/{'avatar' if kind == 'avatar' else 'bg'}/{target_id}.jpg"
    if kind == "avatar":
        c["avatar_url"] = url
        s.characters = chars
        flag_modified(s, "characters")
        snap = (db.query(StorySnapshot).filter(StorySnapshot.story_id == s.id)
                .order_by(StorySnapshot.version.desc()).first())
        if snap and (snap.content or {}).get("story"):
            for sc in snap.content["story"].get("characters", []):
                if sc.get("id") == target_id:
                    sc["avatar_url"] = url
            flag_modified(snap, "content")
        db.commit()
    return {"url": url}
