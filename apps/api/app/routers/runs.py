import copy
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from ..db import SessionLocal, get_db
from ..deps import current_user
from ..engine import runtime
from ..models import Beat as BeatModel
from ..models import Persona as PersonaModel
from ..models import Run as RunModel
from ..models import Story as StoryModel
from ..models import StorySnapshot, User
from ..schemas import Beat, ChooseIn, FollowIn, MoveIn, PlayIn, Run, RunCreate, RunState, RunSummary
from .stories import _to_secret, _to_story

router = APIRouter(prefix="/runs", tags=["runs"])


# ── converters / helpers ──────────────────────────────────
def _to_run(r: RunModel) -> Run:
    st = r.state or {}
    mode = st.get("mode", "character")
    pcid = st.get("player_character_id")
    # addressable cast = characters present at the run's CURRENT act (offstage/ghosts and
    # not-yet-arrived excluded); in character mode also drop the embodied character.
    cast = runtime.cast_for(
        r.pinned_content or {}, int(st.get("act", 1)),
        exclude_id=pcid if mode == "character" else None,
    )
    return Run(
        id=r.id,
        story_id=r.story_id,
        story_version=r.story_version,
        persona_id=r.persona_id,
        state=RunState(
            act=st.get("act", 1),
            affinity=st.get("affinity", 0),
            flags=st.get("flags", {}),
            unlocked_fragment_ids=st.get("unlocked_fragment_ids", []),
            scene=st.get("scene"),
            ended=st.get("ended", False),
            ending=st.get("ending"),
            mode=mode,
            player_character_id=pcid,
            goal=st.get("goal", "") or runtime.current_goal(r.pinned_content or {}, int(st.get("act", 1))),
            progress=runtime.act_progress(r.pinned_content or {}, st, int(st.get("act", 1))),
            location=runtime.location_view(r.pinned_content or {}, st),
            relations=runtime.relations_summary(r.pinned_content or {}, st),
            following=list(st.get("following") or []),
            here=runtime.scene_cast(r.pinned_content or {}, st,
                                    exclude_id=pcid if mode == "character" else None),
            pending_choice=st.get("pending_choice"),
        ),
        cast=cast,
        created_at=r.created_at,
    )


def _to_beat(b: BeatModel) -> Beat:
    return Beat(id=b.id, type=b.type, speaker_name=b.speaker_name, text=b.text, author=b.author)


def _persona_dict(p: PersonaModel) -> dict:
    return {
        "name": p.name,
        "pronouns": p.pronouns,
        "pronouns_custom": p.pronouns_custom,
        "background": p.background,
    }


def _pin_content(story: StoryModel, db: Session) -> tuple[int, dict]:
    """Freeze the story for this run: latest published snapshot, else a live snapshot."""
    snap = (
        db.query(StorySnapshot)
        .filter(StorySnapshot.story_id == story.id)
        .order_by(StorySnapshot.version.desc())
        .first()
    )
    if snap:
        return snap.version, snap.content
    # No published version yet — snapshot the live draft so the run stays stable anyway.
    content = {
        "story": _to_story(story).model_dump(),
        "secrets": [_to_secret(s).model_dump() for s in story.secrets],
    }
    return story.version, content


def _own_run(run_id: str, user: User, db: Session) -> RunModel:
    r = db.get(RunModel, run_id)
    if not r or r.owner_id != user.id:
        raise HTTPException(404, "run not found")
    return r


# ── CRUD ──────────────────────────────────────────────────
@router.get("", response_model=list[RunSummary])
def list_runs(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = (
        db.query(RunModel)
        .filter(RunModel.owner_id == user.id)
        .order_by(RunModel.updated_at.desc())
        .all()
    )
    out = []
    for r in rows:
        story = (r.pinned_content or {}).get("story", {})
        last = r.beats[-1].text if r.beats else None
        out.append(
            RunSummary(
                id=r.id,
                story_id=r.story_id,
                story_title=story.get("title", ""),
                cover_url=story.get("cover_url"),
                persona_id=r.persona_id,
                last_beat_preview=last,
                unread=False,
                updated_at=r.updated_at,
            )
        )
    return out


@router.post("", status_code=201, response_model=Run)
def create_run(body: RunCreate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    persona = db.get(PersonaModel, body.persona_id)
    if not persona or persona.owner_id != user.id:
        raise HTTPException(404, "persona not found")
    story = db.get(StoryModel, body.story_id)
    if not story:
        raise HTTPException(404, "story not found")
    # Public published stories, or the author's own draft (dev testing), are runnable.
    if (story.visibility != "public" or story.status != "published") and story.owner_id != user.id:
        raise HTTPException(403, "story not available")

    version, content = _pin_content(story, db)
    # own a private copy — this run may grow its own map (bootstrap start place, emergent
    # locations), and we must never mutate the shared published snapshot.
    content = copy.deepcopy(content)

    # validate the chosen role (character mode) against the story's PLAYABLE characters —
    # the story is authored from the protagonist's POV; embodying an antagonist/late-arrival
    # breaks the plot, so only author-designated roles are allowed.
    pcid = body.player_character_id if body.mode == "character" else None
    if pcid:
        playable_ids = {c.get("id") for c in runtime.playable_roles(content)}
        if pcid not in playable_ids:
            raise HTTPException(400, "这个角色不能扮演——换一个主角，或用旁观模式看 TA")

    state = {**runtime.default_state(), "scene": runtime.opening_scene(content),
             "mode": body.mode, "player_character_id": pcid}
    state["goal"] = runtime.current_goal(content, 1)
    # 18+ permission pinned at run start (story is mature AND player is age-gated 18+ at
    # signup). Stored on the run so the engine can permit adult content this playthrough.
    state["mature"] = bool((content.get("story") or {}).get("mature"))
    # ARCHITECTURAL INVARIANT: every run has a current location, so the spatial system (place
    # anchor / movement / emergent locations) works for ALL stories — map-less ones get a
    # starting place synthesized from their opening setting.
    runtime.ensure_start_location(content, state)
    # an authored key-moment decision on act 1 greets the player at the door
    state["pending_choice"] = runtime.choice_for_act(content, state, 1)
    run = RunModel(
        owner_id=user.id,
        story_id=story.id,
        persona_id=persona.id,
        story_version=version,
        pinned_content=content,
        state=state,
    )
    # Opening: a detailed intro (who you are / where / what's happening / first goal).
    opening = runtime.build_opening(content, state)
    run.beats = [
        BeatModel(seq=i, type="description", text=b.get("text", ""), author="engine")
        for i, b in enumerate(opening)
    ]
    db.add(run)
    db.commit()
    db.refresh(run)
    return _to_run(run)


@router.get("/{run_id}", response_model=Run)
def get_run(run_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _to_run(_own_run(run_id, user, db))


@router.delete("/{run_id}", status_code=204)
def delete_run(run_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.delete(_own_run(run_id, user, db))
    db.commit()


# ── play ──────────────────────────────────────────────────
@router.get("/{run_id}/play", response_model=list[Beat])
def replay(run_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    r = _own_run(run_id, user, db)
    return [_to_beat(b) for b in r.beats]


def _channel_beat_type(channel: str) -> str:
    return {"say": "dialogue", "think": "think", "do": "description"}.get(channel, "dialogue")


@router.post("/{run_id}/play")
def play(
    run_id: str,
    body: PlayIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Submit player input; respond as SSE, STREAMING each beat as it's computed.

    The player's turn is persisted up front with the request session. The engine then
    runs inside the streaming generator on a FRESH session (decoupled from the request
    lifecycle), persisting + flushing each beat the moment a responder finishes — so the
    first character speaks in ~2-3s and the rest arrive one by one.
    """
    r = _own_run(run_id, user, db)
    if (r.state or {}).get("ended"):
        raise HTTPException(409, "这局已经结束了，开一局新的吧")
    persona = db.get(PersonaModel, r.persona_id)
    next_seq = (r.beats[-1].seq + 1) if r.beats else 0

    st = r.state or {}
    content = r.pinned_content or {}
    # who is in the player's scene THIS turn — stamped on every beat so each character later
    # gets a per-witness view of history (they only recall scenes they were in).
    present_ids = [c.get("id") for c in runtime.scene_characters(content, st) if c.get("id")]

    # 0. raw beat log (with each beat's witnesses) — the engine builds a FILTERED history per
    #    responder from this, so info never silently leaks between characters/scenes.
    beat_log = [{"author": b.author, "type": b.type, "text": b.text,
                 "speaker_name": b.speaker_name, "present_ids": b.present_ids}
                for b in r.beats]

    # RETURN detection (回归问候): the player has been away long enough that this turn is a
    # comeback → the primary speaker greets them and picks up the last thread. Only counts
    # once a real conversation exists (some player beat on record).
    returning = False
    if r.beats and any(b.author == "player" for b in r.beats):
        last_at = r.beats[-1].created_at
        if last_at is not None:
            now = datetime.now(timezone.utc)
            if last_at.tzinfo is None:
                now = now.replace(tzinfo=None)
            gap_h = runtime.tuning_for(content).get("return_gap_hours", 6)
            returning = (now - last_at).total_seconds() > gap_h * 3600

    # 1. persist the player's own turn. In character mode the player speaks AS the chosen
    #    character; in god mode the input is an unseen director's cue (no speaker).
    mode = st.get("mode", "character")
    pcid = st.get("player_character_id")
    if mode == "god":
        player_name = None
    elif pcid:
        player_name = runtime._char_name(r.pinned_content or {}, pcid) or (persona.name if persona else None)
    else:
        player_name = persona.name if persona else None
    # empty input (god "keep watching" / "look around") → nothing to echo as a player beat
    if (body.input or "").strip():
        db.add(BeatModel(
            run_id=r.id,
            seq=next_seq,
            type="description" if mode == "god" else _channel_beat_type(body.channel),
            speaker_name=player_name,
            text=("（旁观指引）" + body.input) if mode == "god" else body.input,
            author="player",
            present_ids=present_ids,
        ))
        next_seq += 1
    db.commit()

    # snapshot everything the stream needs, so it doesn't touch the request session
    state0 = r.state or {}
    persona_dict = _persona_dict(persona) if persona else {}
    start_seq = next_seq

    # 2. stream the engine turn on a FRESH session, persisting + flushing per beat
    def sse():
        db2 = SessionLocal()
        try:
            run = db2.get(RunModel, run_id)
            seq = start_seq
            final = None
            for kind, payload in runtime.run_turn_stream(
                content=content, state=state0, persona=persona_dict,
                player_input=body.input, channel=body.channel,
                beat_log=beat_log, target_character_id=body.target_character_id,
                returning=returning,
            ):
                if kind == "beat":
                    eb = BeatModel(
                        run_id=run_id, seq=seq, type=payload.get("type", "description"),
                        speaker_name=payload.get("speaker_name"), text=payload.get("text", ""),
                        author="engine", present_ids=present_ids,
                    )
                    db2.add(eb)
                    db2.commit()
                    db2.refresh(eb)
                    seq += 1
                    yield _event({"event": "beat", "beat": _to_beat(eb).model_dump()})
                else:
                    final = payload
            # persist final state + emit the trailing meta events
            if final is not None:
                run.state = final["state"]
                db2.commit()
                yield _event({"event": "state", "state": _to_run(run).state.model_dump()})
                yield _event({"event": "scene", "scene": final.get("scene")})
                yield _event({"event": "cast", "cast": final.get("cast", [])})
                yield _event({"event": "here", "here": final.get("here", []),
                              "relations": final.get("relations", {}),
                              "following": final.get("following", [])})
                if final.get("moments") or final.get("rel_deltas"):
                    yield _event({"event": "moments", "moments": final.get("moments", []),
                                  "rel_deltas": final.get("rel_deltas", {})})
                yield _event({"event": "goal", "goal": final.get("goal", "")})
                yield _event({"event": "progress", "progress": final.get("progress")})
                yield _event({"event": "hint", "hint": final.get("hint", "")})
                yield _event({"event": "place", "location": final.get("location")})
                if final.get("pending_choice"):
                    yield _event({"event": "choice", "choice": final["pending_choice"]})
                if final.get("move_request"):
                    yield _event({"event": "move_request", "move_request": final["move_request"]})
                yield _event({"event": "suggest", "suggestions": final.get("suggestions", [])})
                if final.get("ending"):
                    yield _event({"event": "ending", "ending": final["ending"]})
            yield _event({"event": "done"})
        except Exception as e:  # never leave the client hanging
            yield _event({"event": "beat", "beat": {"id": "", "type": "description",
                          "speaker_name": None, "text": f"[出错] {type(e).__name__}", "author": "engine"}})
            yield _event({"event": "done"})
        finally:
            db2.close()

    return StreamingResponse(sse(), media_type="text/event-stream")


def _event(obj: dict) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


# ── move / follow (the explore + companion mechanics) ─────────────────────────
@router.post("/{run_id}/move", response_model=Run)
def move(run_id: str, body: MoveIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Walk the player to a connected location. Followers come along. Returns the updated
    run (new location, new in-scene cast, relations)."""
    r = _own_run(run_id, user, db)
    if (r.state or {}).get("ended"):
        raise HTTPException(409, "这局已经结束了")
    st = dict(r.state or {})
    content = r.pinned_content or {}
    generated = False
    try:
        if body.generate:
            # emergent place: create it for real, wire it in, and move there. This mutates the
            # run's content, so we persist pinned_content below.
            runtime.generate_and_move(content, st, body.location)
            generated = True
        else:
            runtime.apply_move(content, st, body.location)
    except ValueError as e:
        raise HTTPException(400, {"unknown location": "去不了这个地方",
                                  "not reachable from here": "从这里没法直接过去",
                                  "not yet available": "你还不知道有这么个地方——先打听清楚"}.get(str(e), "去不了"))
    # a character who led the player here travels along (so they're present at the destination)
    if body.with_character_id:
        foll = list(st.get("following") or [])
        if body.with_character_id not in foll:
            foll.append(body.with_character_id)
        st["following"] = foll
    # 到达即发现: truths gated on BEING here reveal the moment the player arrives
    discoveries = runtime.discover_on_arrival(content, st)
    if discoveries:
        seq = (r.beats[-1].seq + 1) if r.beats else 0
        present_ids = [c.get("id") for c in runtime.scene_characters(content, st) if c.get("id")]
        for i, d in enumerate(discoveries):
            db.add(BeatModel(run_id=r.id, seq=seq + i, type="description", speaker_name=None,
                             text=d.get("text", ""), author="engine", present_ids=present_ids))
    r.state = st
    if generated:
        r.pinned_content = content
        flag_modified(r, "pinned_content")
    db.commit()
    db.refresh(r)
    out = _to_run(r)
    out.discoveries = discoveries
    return out


@router.get("/{run_id}/map")
def get_map(run_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """The discovered world: unlocked places, current position, who stands where.
    Locked places appear only as an unnamed count."""
    r = _own_run(run_id, user, db)
    return runtime.map_view(r.pinned_content or {}, r.state or {})


@router.get("/{run_id}/journal")
def get_journal(run_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """The run's dossier: unlocked truths (full text), layers still locked (counts only),
    the ending gallery (achieved vs ？？？), decisions made. Locked bodies never leave."""
    r = _own_run(run_id, user, db)
    return runtime.journal(r.pinned_content or {}, r.state or {})


@router.post("/{run_id}/choose")
def choose(run_id: str, body: ChooseIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Answer the run's pending key-moment decision (VN 抉择). Effects are applied
    deterministically (flag / 好感 / relationship deltas); the picked label is returned so
    the client plays it as the player's own next line — the cast then reacts to it."""
    r = _own_run(run_id, user, db)
    if (r.state or {}).get("ended"):
        raise HTTPException(409, "这局已经结束了")
    st = dict(r.state or {})
    try:
        res = runtime.apply_choice(r.pinned_content or {}, st, body.option_id)
    except ValueError as e:
        raise HTTPException(400, {"no pending choice": "现在没有待决定的抉择",
                                  "unknown option": "没有这个选项"}.get(str(e), "不行"))
    r.state = st
    db.commit()
    return {"label": res.get("label", ""), "flag": res.get("flag")}


@router.post("/{run_id}/leave", status_code=204)
def leave(run_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """悬念离场: the player is leaving mid-run (page hide / back button beacon). Append ONE
    cliffhanger narration so the run's last beat is an unfinished hook that pulls them back.
    Idempotent per leave point — repeated beacons with no new turns add nothing."""
    r = _own_run(run_id, user, db)
    st = dict(r.state or {})
    if st.get("ended") or not r.beats:
        return
    if int(st.get("parting_seq") or -1) == len(r.beats):
        return  # the last beat is already this leave's hook
    if not any(b.author == "player" for b in r.beats):
        return  # no conversation yet — nothing to hang a hook on
    persona = db.get(PersonaModel, r.persona_id)
    content = r.pinned_content or {}
    present_ids = [c.get("id") for c in runtime.scene_characters(content, st) if c.get("id")]
    for b in runtime.build_parting_hook(content, st, _persona_dict(persona) if persona else {}):
        db.add(BeatModel(run_id=r.id, seq=r.beats[-1].seq + 1, type="description",
                         speaker_name=None, text=b.get("text", ""), author="engine",
                         present_ids=present_ids))
    r.state = {**st, "parting_seq": len(r.beats) + 1}
    db.commit()


@router.post("/{run_id}/follow", response_model=Run)
def follow(run_id: str, body: FollowIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Invite a character in the current scene to travel with the player, or part ways.
    A character whose relationship has soured to ENEMY refuses (409 with the reason)."""
    r = _own_run(run_id, user, db)
    if (r.state or {}).get("ended"):
        raise HTTPException(409, "这局已经结束了")
    st = dict(r.state or {})
    try:
        res = runtime.set_follow(r.pinned_content or {}, st, body.character_id, body.follow)
    except ValueError as e:
        raise HTTPException(400, {"unknown character": "没有这个人",
                                  "character not here": "这个人不在你身边"}.get(str(e), "不行"))
    if not res.get("ok"):
        raise HTTPException(409, res.get("reason") or "对方不愿意跟你走")
    r.state = st
    db.commit()
    db.refresh(r)
    return _to_run(r)
