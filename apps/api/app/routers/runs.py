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
from ..models import StoryMeta, StorySnapshot, User
from ..schemas import (Beat, ChooseIn, ConfrontIn, FollowIn, MoveIn, PhoneSendIn, PlayIn, Run,
                       RunCreate, RunState, RunSummary, VerdictIn)
from .stories import _to_secret, _to_story

router = APIRouter(prefix="/runs", tags=["runs"])

# 🖼 emergent art (sandbox start place, 涌现地点, conjured characters): rendered OFF the
# request path through ONE serialized worker. DashScope allows very few concurrent image
# tasks — parallel submissions at run creation silently lost every task but the first
# (the "bg rendered, avatars never did" bug) — so a single queue renders jobs in order,
# skips what's already on disk, dedupes, and retries a transient failure once.
_BG_DIR = __import__("pathlib").Path(__file__).resolve().parents[1] / "static" / "scene" / "bg"
_AV_DIR = __import__("pathlib").Path(__file__).resolve().parents[1] / "static" / "scene" / "avatar"

import queue as _imgqueue  # noqa: E402
import threading as _imgthreading  # noqa: E402

_IMG_Q: "_imgqueue.Queue" = _imgqueue.Queue()
_IMG_PENDING: set = set()
_IMG_LOCK = _imgthreading.Lock()
_IMG_WORKER: list = []


def _img_worker():
    from ..engine.qwen import generate_image
    while True:
        prompt, path, size = _IMG_Q.get()
        try:
            if not path.exists():
                img = generate_image(prompt, size=size)
                if not img:      # throttled / transient → one measured retry
                    import time
                    time.sleep(6)
                    img = generate_image(prompt, size=size)
                if img:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(img)
        except Exception:
            pass
        finally:
            with _IMG_LOCK:
                _IMG_PENDING.discard(str(path))
            _IMG_Q.task_done()


def _enqueue_image(prompt: str, path, size: str) -> None:
    with _IMG_LOCK:
        if str(path) in _IMG_PENDING:
            return
        _IMG_PENDING.add(str(path))
        if not _IMG_WORKER:
            t = _imgthreading.Thread(target=_img_worker, daemon=True)
            _IMG_WORKER.append(t)
            t.start()
    _IMG_Q.put((prompt, path, size))


def _spawn_location_bg(content: dict, loc: dict | None) -> None:
    if not loc or not loc.get("id") or not loc.get("generated"):
        return
    path = _BG_DIR / f"{loc['id']}.jpg"
    if path.exists():
        return
    story = content.get("story") or {}
    era = ((story.get("world_long") or story.get("world_facts") or "")
           .strip().replace("\n", " "))[:140]
    prompt = (f"{era} 场景：{loc.get('name', '')}。{(loc.get('detail') or '')[:200]} "
              "电影感写实场景概念图，强烈氛围与光影，景深，电影级调色，横构图宽幅；"
              "空镜，画面里没有任何人物，没有文字、字幕或水印。")
    _enqueue_image(prompt, path, "1280*720")


def _ensure_char_avatars(content: dict) -> bool:
    """Point every generated character at /scene/avatar/{id}.jpg and queue any missing
    portrait. Returns True when an avatar_url was newly written (caller persists)."""
    story = content.get("story") or {}
    world = ((story.get("world_long") or "").strip().replace("\n", " "))[:120]
    changed = False
    for c in story.get("characters") or []:
        cid, name = c.get("id"), c.get("name")
        if not cid or not name or not c.get("generated"):
            continue
        url = f"/scene/avatar/{cid}.jpg"
        if c.get("avatar_url") != url:
            c["avatar_url"] = url
            changed = True
        path = _AV_DIR / f"{cid}.jpg"
        if path.exists():
            continue
        bits = "，".join(b for b in (name, c.get("role") or "",
                                     (c.get("persona_text") or "")[:160]) if b)
        prompt = (f"{bits}。世界背景：{world}。电影质感人物肖像，胸像特写，正面微侧，"
                  "目光看向镜头外，写实风格，柔和的侧光，背景虚化，情绪克制内敛，"
                  "高细节，胶片颗粒感")
        _enqueue_image(prompt, path, "768*768")
    return changed


# ── converters / helpers ──────────────────────────────────
def _to_run(r: RunModel) -> Run:
    st = r.state or {}
    mode = st.get("mode", "character")
    pcid = st.get("player_character_id")
    # addressable cast = characters present at the run's CURRENT act (offstage/ghosts and
    # not-yet-arrived excluded); in character mode also drop the embodied character.
    cast = runtime.cast_for(
        r.pinned_content or {}, int(st.get("act", 1)),
        exclude_id=pcid if mode == "character" else None, state=st,
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
            player_character_name=(runtime._char_name(r.pinned_content or {}, pcid) if pcid else None),
            pressure=int(st.get("pressure", 0) or 0),
            player_hp=st.get("player_hp", "healthy"),
            money=st.get("money"),
            currency=(runtime.currency_of(r.pinned_content or {})
                      if st.get("money") is not None else None),
            quests=list(st.get("quests") or []),
            can_reincarnate=bool(runtime.sandbox_on(r.pinned_content or {})
                                 and st.get("player_hp") == "dead" and not st.get("ended")),
            powers=list(st.get("powers") or []),
            identity=st.get("identity"),
            inventory=list(st.get("inventory") or []),
            pressure_name=((runtime.pressure_cfg(r.pinned_content or {}) or {}).get("name")),
            clock=runtime.clock_view(r.pinned_content or {}, st),
            promises=runtime.promises_view(r.pinned_content or {}, st),
            phone_unread=runtime.phone_total_unread(r.pinned_content or {}, st),
            verdict=runtime.verdict_view(r.pinned_content or {}, st),
        ),
        cast=cast,
        created_at=r.created_at,
    )


def _to_beat(b: BeatModel) -> Beat:
    return Beat(id=b.id, type=b.type, speaker_name=b.speaker_name, text=b.text, author=b.author,
                mood=b.mood)


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
        st = r.state or {}
        pcid = st.get("player_character_id")
        out.append(
            RunSummary(
                id=r.id,
                story_id=r.story_id,
                story_title=story.get("title", ""),
                cover_url=story.get("cover_url"),
                persona_id=r.persona_id,
                last_beat_preview=last,
                unread=False,
                act=int(st.get("act", 1) or 1),
                mode=st.get("mode", "character"),
                player_character_name=(runtime._char_name(r.pinned_content or {}, pcid) if pcid else None),
                ended=bool(st.get("ended")),
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

    # 🔞 decided up front so the conjured cast can carry the tone from birth
    mature_run = bool((content.get("story") or {}).get("mature")) \
        or (runtime.sandbox_on(content) and body.mature)

    # 🏖 sandbox: the player DEFINES the world at run start — their private copy runs on
    # that worldview, and opens with a small cast conjured from it (grows forever in play)
    if runtime.sandbox_on(content):
        if (body.worldview or "").strip():
            wv = body.worldview.strip()[:2000]
            content["story"]["world_long"] = wv
            content["story"]["world_facts"] = wv[:400]
        runtime.seed_sandbox_cast(content, mature=mature_run)

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
    if runtime.sandbox_on(content) and (body.worldview or "").strip():
        state["worldview"] = body.worldview.strip()[:2000]
    # 💰 the sandbox runs a real cash ledger: start with the authored pocket money
    if runtime.sandbox_on(content):
        sb_cfg = (content.get("story") or {}).get("sandbox") or {}
        state["money"] = runtime._to_int(sb_cfg.get("start_money"), 0, 99999) or 100
        # ✨ 金手指: the player's declared powers are REAL in their world (engine-honored);
        # blank falls back to the story's authored default powers
        declared = [ln.strip()[:40] for ln in (body.powers or "").replace("；", "\n").splitlines()
                    if ln.strip()][:4]
        state["powers"] = declared or [str(p).strip()[:40]
                                       for p in (sb_cfg.get("default_powers") or []) if str(p).strip()][:4]
    # ⏰ 现实同步 runs open at the player's real hour
    if runtime.real_time_on(content):
        runtime.sync_real_clock(content, state)
    # 18+ permission pinned at run start (story is mature AND player is age-gated 18+ at
    # signup). Stored on the run so the engine can permit adult content this playthrough.
    # 🔞 pinned per-run (story-authored, or the sandbox per-run opt-in — decided above)
    state["mature"] = mature_run
    # ARCHITECTURAL INVARIANT: every run has a current location, so the spatial system (place
    # anchor / movement / emergent locations) works for ALL stories — map-less ones get a
    # starting place synthesized from their opening setting.
    start_loc = runtime.ensure_start_location(content, state)
    _spawn_location_bg(content, start_loc)
    # 🏖 sandbox spatial rigor: the conjured cast LIVES at the start place (not
    # everywhere); the map decides who you can meet, movement means something
    if runtime.sandbox_on(content) and start_loc and start_loc.get("id"):
        runtime.anchor_homeless_cast(content, start_loc["id"])
    # an authored key-moment decision on act 1 greets the player at the door
    state["pending_choice"] = runtime.choice_for_act(content, state, 1)
    # 🎒 the embodied character's authored pocket items start the run with the player
    if pcid:
        pc = next((c for c in (content.get("story") or {}).get("characters", [])
                   if c.get("id") == pcid), None)
        state["inventory"] = [dict(i) for i in ((pc or {}).get("items") or []) if i.get("name")]
    # 🌱 NG+ perk: earned by reaching any ending of THIS story once; applied at the start
    if body.perk:
        if body.perk not in runtime.PERKS:
            raise HTTPException(400, "没有这种开局优势")
        meta = (db.query(StoryMeta)
                .filter(StoryMeta.user_id == user.id, StoryMeta.story_id == story.id).first())
        if not meta or not (meta.endings_achieved or []):
            raise HTTPException(403, "先走到一个结局，才解锁二周目优势")
        state["perk"] = body.perk
        if body.perk == "veteran":
            base = runtime.relationships.new_scores()
            state["rel"] = {c["id"]: {**base, "closeness": base["closeness"] + runtime.VETERAN_CLOSENESS}
                            for c in (content.get("story") or {}).get("characters", []) if c.get("id")}
    # 🃏 carry a minted character card in: they join the cast at the starting place
    if body.carry_card_id:
        meta = (db.query(StoryMeta)
                .filter(StoryMeta.user_id == user.id, StoryMeta.story_id == story.id).first())
        if not meta or not (meta.endings_achieved or []):
            raise HTTPException(403, "先走到一个结局，才解锁二周目携带")
        card = next((c for c in (meta.cards or [])
                     if c.get("id") == body.carry_card_id and c.get("kind") == "character"), None)
        if not card:
            raise HTTPException(400, "没有这张可携带的人物卡")
        p = card.get("payload") or {}
        import uuid as _uuid
        (content.get("story") or {}).setdefault("characters", []).append({
            "id": f"gen_{_uuid.uuid4().hex[:8]}",
            "name": p.get("name") or card.get("name") or "旧识",
            "role": (p.get("role") or "上一世的旧识")[:24],
            "persona_text": p.get("persona_text") or card.get("text") or "",
            "relation_default": "friend",
            "generated": True,
        })
    # 🖼 conjured cast (sandbox opening people, carried-in 旧识) get portraits rendering
    _ensure_char_avatars(content)
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


@router.post("/{run_id}/reincarnate", response_model=Run)
def reincarnate_run(run_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """🔄 沙盒转生: a dead sandbox player returns as a new face in the same world.
    The world's ledgers survive; the player's side (body/money/ties/name) restarts,
    and character memory is cut at this seam — nobody remembers the former life's talks."""
    r = _own_run(run_id, user, db)
    st = dict(r.state or {})
    content = r.pinned_content or {}
    if not runtime.sandbox_on(content):
        raise HTTPException(400, "只有无尽沙盒才能转生")
    if st.get("player_hp") != "dead":
        raise HTTPException(400, "你还活着")
    beats = runtime.reincarnate(content, st)
    seq = (r.beats[-1].seq + 1) if r.beats else 0
    st["history_cut_seq"] = seq
    for i, b in enumerate(beats):
        db.add(BeatModel(run_id=r.id, seq=seq + i, type="description",
                         text=b.get("text", ""), author="engine"))
    r.state = st
    db.commit()
    db.refresh(r)
    return _to_run(r)


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
    #    🔄 after a rebirth, history starts over: nobody remembers talking to the former life.
    _cut = int(st.get("history_cut_seq") or 0)
    beat_log = [{"author": b.author, "type": b.type, "text": b.text,
                 "speaker_name": b.speaker_name, "present_ids": b.present_ids}
                for b in r.beats if b.seq >= _cut]

    # RETURN detection (回归问候): the player has been away long enough that this turn is a
    # comeback → the primary speaker greets them and picks up the last thread. Only counts
    # once a real conversation exists (some player beat on record).
    returning = False
    away_hours = 0.0
    if r.beats and any(b.author == "player" for b in r.beats):
        last_at = r.beats[-1].created_at
        if last_at is not None:
            now = datetime.now(timezone.utc)
            if last_at.tzinfo is None:
                now = now.replace(tzinfo=None)
            gap_h = runtime.tuning_for(content).get("return_gap_hours", 6)
            away_hours = (now - last_at).total_seconds() / 3600
            returning = away_hours > gap_h

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
                returning=returning, away_hours=away_hours,
            ):
                if kind == "dice":
                    # the roll streams BEFORE the narration so the UI can animate it
                    yield _event({"event": "dice", "dice": payload})
                    continue
                if kind == "clock":
                    yield _event({"event": "clock", "clock": payload})
                    continue
                if kind == "phone":
                    yield _event({"event": "phone", "message": payload})
                    continue
                if kind == "beat":
                    eb = BeatModel(
                        run_id=run_id, seq=seq, type=payload.get("type", "description"),
                        speaker_name=payload.get("speaker_name"), text=payload.get("text", ""),
                        author="engine", present_ids=present_ids, mood=payload.get("mood"),
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
                # 🖼 every turn is a backfill chance: runs from before portraits shipped
                # (or whose renders got throttled) pick their faces up here
                av_changed = False
                try:
                    av_changed = _ensure_char_avatars(content)
                except Exception:
                    pass
                if final.get("content_mutated") or av_changed:
                    # the run grew an emergent character (or gained avatar urls) —
                    # persist its private story copy
                    run.pinned_content = content
                    flag_modified(run, "pinned_content")
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
                if final.get("pressure_view"):
                    yield _event({"event": "pressure", "pressure": final["pressure_view"]})
                yield _event({"event": "place", "location": final.get("location")})
                yield _event({"event": "promises", "promises": final.get("promises", [])})
                yield _event({"event": "verdict", "verdict": final.get("verdict")})
                if final.get("pending_choice"):
                    yield _event({"event": "choice", "choice": final["pending_choice"]})
                if final.get("move_request"):
                    yield _event({"event": "move_request", "move_request": final["move_request"]})
                yield _event({"event": "suggest", "suggestions": final.get("suggestions", [])})
                if final.get("ending"):
                    yield _event({"event": "ending", "ending": final["ending"]})
                    # 🌱 the ending outlives the run: cross-run gallery + achievements
                    try:
                        new_ach = _bump_story_meta(db2, run, content, final)
                        if new_ach:
                            yield _event({"event": "achievements", "achievements": new_ach})
                    except Exception:
                        pass
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


def _bump_story_meta(db2: Session, run: RunModel, content: dict, final: dict) -> list[dict]:
    """🌱 Fold a just-fired ending into the player's per-story meta (cross-run gallery,
    achievements, NG+ unlock). Returns the achievements newly earned THIS moment."""
    meta = (db2.query(StoryMeta)
            .filter(StoryMeta.user_id == run.owner_id, StoryMeta.story_id == run.story_id)
            .first())
    if not meta:
        meta = StoryMeta(user_id=run.owner_id, story_id=run.story_id)
        db2.add(meta)
    eid = (final.get("ending") or {}).get("id")
    state = final.get("state") or {}
    if len(state.get("achieved_endings") or []) <= 1:
        meta.runs_ended = int(meta.runs_ended or 0) + 1  # this run's FIRST ending
    if eid:
        meta.endings_achieved = sorted(set(meta.endings_achieved or []) | {eid})
    have = {a.get("id") for a in (meta.achievements or [])}
    new = [a for a in runtime.compute_achievements(content, state) if a["id"] not in have]
    if new:
        meta.achievements = list(meta.achievements or []) + new
    # 🃏 mint this run's cards into the permanent collection (dedup by id, capped)
    got = {c.get("id") for c in (meta.cards or [])}
    got_named = {(c.get("kind"), c.get("name")) for c in (meta.cards or [])}
    minted = [c for c in runtime.mint_cards(content, state)
              if c["id"] not in got
              and not (c["kind"] == "character" and (c["kind"], c["name"]) in got_named)]
    if minted:
        meta.cards = (list(meta.cards or []) + minted)[-60:]
    db2.commit()
    return new


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
            new_loc = runtime.generate_and_move(content, st, body.location)
            _spawn_location_bg(content, new_loc)
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
    # 到达旁白: a vivid pan of the place just entered — the space, what each person here
    # is doing right now, who notices first. Rides ahead of the arrival discoveries.
    persona = db.get(PersonaModel, r.persona_id)
    arrival = runtime.arrival_narration(content, st, _persona_dict(persona) if persona else {})
    # 到达即发现: truths gated on BEING here reveal the moment the player arrives
    discoveries = runtime.discover_on_arrival(content, st)
    if arrival:
        discoveries = [{"text": arrival}] + discoveries
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
    # the scene just changed under the player's feet — regenerate the next-step chips
    # for THIS place and THESE people (the old ones point at who's no longer here)
    out.suggestions = runtime.arrival_suggestions(content, st)
    return out


@router.get("/{run_id}/map")
def get_map(run_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """The discovered world: unlocked places, current position, who stands where.
    Locked places appear only as an unnamed count."""
    r = _own_run(run_id, user, db)
    return runtime.map_view(r.pinned_content or {}, r.state or {})


@router.get("/{run_id}/character/{char_id}")
def get_character(run_id: str, char_id: str,
                  user: User = Depends(current_user), db: Session = Depends(get_db)):
    """The 档案卡 for one character: what the player knows, how the relationship stands,
    the shared timeline. 404 for unknown ids; locked content stays server-side."""
    r = _own_run(run_id, user, db)
    prof = runtime.character_profile(r.pinned_content or {}, r.state or {}, char_id)
    if not prof:
        raise HTTPException(404, "没有这个人")
    return prof


@router.get("/{run_id}/phone")
def get_phone(run_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """📱 the 信息 app's inbox: one row per thread + total unread + the story's device name."""
    r = _own_run(run_id, user, db)
    return runtime.phone_threads_view(r.pinned_content or {}, r.state or {})


@router.get("/{run_id}/phone/{char_id}")
def get_phone_thread(run_id: str, char_id: str,
                     user: User = Depends(current_user), db: Session = Depends(get_db)):
    """One full thread; opening it marks it read."""
    r = _own_run(run_id, user, db)
    st = dict(r.state or {})
    view = runtime.phone_thread(r.pinned_content or {}, st, char_id)
    if not view:
        raise HTTPException(404, "没有这个人")
    r.state = st
    flag_modified(r, "state")
    db.commit()
    return view


@router.post("/{run_id}/phone/{char_id}")
def send_phone(run_id: str, char_id: str, body: PhoneSendIn,
               user: User = Depends(current_user), db: Session = Depends(get_db)):
    """📱 text a character from anywhere. They answer in voice under the same gate as a
    scene turn — or leave the player on read (replied=false)."""
    r = _own_run(run_id, user, db)
    if (r.state or {}).get("ended"):
        raise HTTPException(409, "这局已经结束了")
    st = dict(r.state or {})
    persona = db.get(PersonaModel, r.persona_id)
    try:
        view = runtime.phone_send(r.pinned_content or {}, st, _persona_dict(persona) if persona else {},
                                  char_id, body.text)
    except ValueError as e:
        raise HTTPException(400, str(e))
    r.state = st
    flag_modified(r, "state")
    db.commit()
    return view


@router.post("/{run_id}/phone/{char_id}/call")
def call_phone(run_id: str, char_id: str, body: PhoneSendIn,
               user: User = Depends(current_user), db: Session = Depends(get_db)):
    """📞 CALL a character who isn't in the scene. Live voice under the same gate:
    spoken lines + one line of what's audible down the line; probing on a call counts.
    A character whose 作息 says they're unreachable right now doesn't pick up."""
    r = _own_run(run_id, user, db)
    if (r.state or {}).get("ended"):
        raise HTTPException(409, "这局已经结束了")
    st = dict(r.state or {})
    persona = db.get(PersonaModel, r.persona_id)
    try:
        view = runtime.phone_call(r.pinned_content or {}, st, _persona_dict(persona) if persona else {},
                                  char_id, body.text)
    except ValueError as e:
        raise HTTPException(400, str(e))
    r.state = st
    flag_modified(r, "state")
    db.commit()
    return view


@router.get("/{run_id}/mail")
def get_mail(run_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """📮 the 信箱: letters characters have written the player (subjects only + unread)."""
    r = _own_run(run_id, user, db)
    return runtime.mail_view(r.pinned_content or {}, r.state or {})


@router.get("/{run_id}/mail/{mail_id}")
def read_mail(run_id: str, mail_id: str,
              user: User = Depends(current_user), db: Session = Depends(get_db)):
    """One full letter; opening it marks it read."""
    r = _own_run(run_id, user, db)
    st = dict(r.state or {})
    m = runtime.mail_open(st, mail_id)
    if not m:
        raise HTTPException(404, "没有这封信")
    r.state = st
    flag_modified(r, "state")
    db.commit()
    return m


@router.get("/{run_id}/journal")
def get_journal(run_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """The run's dossier: unlocked truths (full text), layers still locked (counts only),
    the ending gallery (achieved vs ？？？), decisions made. Locked bodies never leave."""
    r = _own_run(run_id, user, db)
    return runtime.journal(r.pinned_content or {}, r.state or {})


@router.post("/{run_id}/confront")
def confront(run_id: str, body: ConfrontIn, user: User = Depends(current_user),
             db: Session = Depends(get_db)):
    """🃏 证据对峙: present an unlocked clue to the character it belongs to, face to face.
    Validates first (400 with a readable reason), then streams the /play SSE contract:
    the visible opposed roll, the confrontation beats, and the state that follows."""
    r = _own_run(run_id, user, db)
    if (r.state or {}).get("ended"):
        raise HTTPException(409, "这局已经结束了")
    persona = db.get(PersonaModel, r.persona_id)
    content = r.pinned_content or {}
    state0 = r.state or {}
    persona_dict = _persona_dict(persona) if persona else {}
    present_ids = [c.get("id") for c in runtime.scene_characters(content, state0) if c.get("id")]
    beat_log = [{"author": b.author, "type": b.type, "text": b.text,
                 "speaker_name": b.speaker_name, "present_ids": b.present_ids}
                for b in r.beats]
    try:
        gen = runtime.confront_stream(content, state0, persona_dict,
                                      body.fragment_id, body.character_id, beat_log=beat_log)
    except ValueError as e:
        raise HTTPException(400, str(e))
    start_seq = (r.beats[-1].seq + 1) if r.beats else 0

    def sse():
        db2 = SessionLocal()
        try:
            run = db2.get(RunModel, run_id)
            seq = start_seq
            final = None
            for kind, payload in gen:
                if kind == "dice":
                    yield _event({"event": "dice", "dice": payload})
                elif kind == "beat":
                    eb = BeatModel(run_id=run_id, seq=seq, type=payload.get("type", "description"),
                                   speaker_name=payload.get("speaker_name"),
                                   text=payload.get("text", ""),
                                   author="engine", present_ids=present_ids,
                                   mood=payload.get("mood"))
                    db2.add(eb)
                    db2.commit()
                    db2.refresh(eb)
                    seq += 1
                    yield _event({"event": "beat", "beat": _to_beat(eb).model_dump()})
                else:
                    final = payload
            if final is not None:
                run.state = final["state"]
                db2.commit()
                yield _event({"event": "state", "state": _to_run(run).state.model_dump()})
                if final.get("moments") or final.get("rel_deltas"):
                    yield _event({"event": "moments", "moments": final.get("moments", []),
                                  "rel_deltas": final.get("rel_deltas", {})})
                yield _event({"event": "goal", "goal": final.get("goal", "")})
                yield _event({"event": "progress", "progress": final.get("progress")})
                if final.get("pressure_view"):
                    yield _event({"event": "pressure", "pressure": final["pressure_view"]})
                if final.get("pending_choice"):
                    yield _event({"event": "choice", "choice": final["pending_choice"]})
            yield _event({"event": "done"})
        except Exception as e:
            yield _event({"event": "beat", "beat": {"id": "", "type": "description",
                          "speaker_name": None, "text": f"[出错] {type(e).__name__}", "author": "engine"}})
            yield _event({"event": "done"})
        finally:
            db2.close()

    return StreamingResponse(sse(), media_type="text/event-stream")


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


@router.post("/{run_id}/verdict")
def verdict(run_id: str, body: VerdictIn, user: User = Depends(current_user),
            db: Session = Depends(get_db)):
    """🔍 指认结案: the player formally commits to a conclusion (limited attempts).
    Correct sets flags.verdict_solved (endings gate on it); the last wrong attempt
    fires the authored fail ending. The verdict scene is appended as beats."""
    r = _own_run(run_id, user, db)
    if (r.state or {}).get("ended"):
        raise HTTPException(409, "这局已经结束了")
    st = dict(r.state or {})
    content = r.pinned_content or {}
    try:
        res = runtime.submit_verdict(content, st, body.option_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    seq = (r.beats[-1].seq + 1) if r.beats else 0
    present_ids = [c.get("id") for c in runtime.scene_characters(content, st) if c.get("id")]
    opt = next((o for o in (runtime.verdict_cfg(content) or {}).get("options", [])
                if o.get("id") == body.option_id), {})
    db.add(BeatModel(run_id=r.id, seq=seq, type="dialogue", speaker_name=None,
                     text=f"（你正式指认：{opt.get('label', '')}）", author="player",
                     present_ids=present_ids))
    db.add(BeatModel(run_id=r.id, seq=seq + 1, type="description", speaker_name=None,
                     text=res.get("text", ""), author="engine", present_ids=present_ids))
    if res.get("ending"):
        e = res["ending"]
        head = "—— 你死了 ——" if e.get("kind") == "death" else "—— 坏结局 ——"
        db.add(BeatModel(run_id=r.id, seq=seq + 2, type="description", speaker_name=None,
                         text=f"{head}  {e.get('title', '')}".strip(), author="engine",
                         present_ids=present_ids))
        if e.get("text"):
            db.add(BeatModel(run_id=r.id, seq=seq + 3, type="description", speaker_name=None,
                             text=e["text"], author="engine", present_ids=present_ids))
    r.state = st
    flag_modified(r, "state")
    db.commit()
    if res.get("ending"):
        try:
            _bump_story_meta(db, r, content, {"ending": res["ending"], "state": st})
        except Exception:
            pass
    return {**res, "verdict": runtime.verdict_view(content, st)}


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
