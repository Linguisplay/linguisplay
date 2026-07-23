import copy
import fcntl
import json
import os
import tempfile
import time as _time_mod
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from .. import metrics
from ..config import get_settings
from ..db import SessionLocal, get_db
from ..deps import current_user
from ..engine import director, factions as factions_mod, living, runtime
from ..engine import taste as taste_mod
from ..engine.llm import get_llm
from ..models import Beat as BeatModel
from ..models import Persona as PersonaModel
from ..models import Run as RunModel
from ..models import Story as StoryModel
from ..models import StoryMeta, StorySnapshot, User
from ..schemas import (Beat, ChooseIn, ConfrontIn, FollowIn, MarketBuyIn, MoveIn, PhoneSendIn, RenameIn,
                       SocialCommentIn, SocialLikeIn, TransferIn,
                       PlayIn, RewindIn, Run, RunCreate, RunState, RunSummary, VerdictIn)
from .stories import _to_secret, _to_story

router = APIRouter(prefix="/runs", tags=["runs"])

# 🖼 emergent art (sandbox start place, 涌现地点, conjured characters): rendered OFF the
# request path through ONE serialized worker. DashScope allows very few concurrent image
# tasks — parallel submissions at run creation silently lost every task but the first
# (the "bg rendered, avatars never did" bug) — so a single queue renders jobs in order,
# skips what's already on disk, dedupes, and retries a transient failure once.
_BG_DIR = __import__("pathlib").Path(__file__).resolve().parents[1] / "static" / "scene" / "bg"
_AV_DIR = __import__("pathlib").Path(__file__).resolve().parents[1] / "static" / "scene" / "avatar"
_SNAP_DIR = __import__("pathlib").Path(__file__).resolve().parents[1] / "static" / "scene" / "snap"
_SPRITE_DIR = __import__("pathlib").Path(__file__).resolve().parents[1] / "static" / "scene" / "sprite"
_ITEM_DIR = __import__("pathlib").Path(__file__).resolve().parents[1] / "static" / "scene" / "item"

import queue as _imgqueue  # noqa: E402
import threading as _imgthreading  # noqa: E402

_IMG_Q: "_imgqueue.Queue" = _imgqueue.Queue()
_IMG_PENDING: set = set()
_IMG_LOCK = _imgthreading.Lock()
_IMG_WORKER: list = []

# 🔒 runs with a turn currently streaming — a second /play or /confront on the same
# run is refused (409) instead of racing the first stream's state write.
_TURN_ACTIVE: set = set()
_TURN_GUARD = _imgthreading.Lock()
# ▶ drive 防刷 (⚖️ 无点击不推进): run_id → 上一次接受观剧拍的时刻 (脚本空转拦截)
_DRIVE_LAST: dict = {}
# 🔒 跨进程回合锁: _TURN_ACTIVE 只在本进程有效 — uvicorn 开多 worker 后两个 /play
# 会各自过闸并发碾档。flock 把「一局同时只有一回合」钉在主机级; 进程被杀锁自动释放。
_TURN_LOCK_DIR = os.path.join(tempfile.gettempdir(), "linguisplay-turnlocks")


def _turn_lock_acquire(run_id: str):
    """Non-blocking per-run flock. Returns the held file object, or None if another
    process is mid-turn on this run. run_id 已过 _own_run 校验, 不含路径花样."""
    os.makedirs(_TURN_LOCK_DIR, exist_ok=True)
    f = open(os.path.join(_TURN_LOCK_DIR, f"{run_id}.lock"), "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return f
    except OSError:
        f.close()
        return None


def _turn_lock_release(f) -> None:
    try:
        fcntl.flock(f, fcntl.LOCK_UN)
        f.close()
    except Exception:
        pass


def _img_worker():
    from ..engine.gal import debg, shrink_jpg, to_webp, trim_alpha
    from ..engine.qwen import generate_image
    while True:
        prompt, path, size, negative, seed = _IMG_Q.get()
        try:
            if not path.exists():
                img = generate_image(prompt, size=size, negative=negative, seed=seed)
                if not img:      # throttled / transient → one measured retry
                    import time
                    time.sleep(6)
                    img = generate_image(prompt, size=size, negative=negative, seed=seed)
                if img:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    if path.suffix == ".webp":
                        # 🎭 透底立绘: 抠底出剪影上台; 源图留在旁边作改脸差分的底
                        path.with_name(path.stem + "_src.jpg").write_bytes(
                            shrink_jpg(img, quality=82, max_side=1280))
                        path.write_bytes(to_webp(trim_alpha(debg(img))))
                    else:
                        # 出生即瘦身: 原始生图 1-3MB, 小水管服务器上手机要下载几十秒
                        path.write_bytes(shrink_jpg(img, quality=80, max_side=1600))
        except Exception:
            pass
        finally:
            with _IMG_LOCK:
                _IMG_PENDING.discard(str(path))
            _IMG_Q.task_done()


def _enqueue_image(prompt: str, path, size: str,
                   negative: str = "", seed: int | None = None) -> None:
    with _IMG_LOCK:
        if str(path) in _IMG_PENDING:
            return
        _IMG_PENDING.add(str(path))
        if not _IMG_WORKER:
            t = _imgthreading.Thread(target=_img_worker, daemon=True)
            _IMG_WORKER.append(t)
            t.start()
    _IMG_Q.put((prompt, path, size, negative, seed))


def _queue_item_icons(state: dict, rows) -> None:
    """🎒 物品配图懒生成 (实体化 第5题): 模板第一次被展示才排队 — 提示词 =
    纯函数(物性卡), tid 定 seed, 同模板永远同图, 生成后永久缓存全服复用。"""
    from ..engine import items as items_engine
    for r in rows or []:
        tid = (r or {}).get("tid")
        if not tid:
            continue
        path = _ITEM_DIR / f"{tid}.jpg"
        if path.exists():
            continue
        card = ((state.get("item_templates") or {}).get(tid)
                or items_engine.rule_card(str(r.get("name") or "")))
        prompt, neg = items_engine.icon_prompt(card)
        _enqueue_image(prompt, path, "1024*1024", neg, items_engine.icon_seed(tid))


def _story_art(content: dict) -> tuple[str, str]:
    """🎨 一世界一画风 (Yi: 角色画风要统一): 统一的风格引导 (开头压阵, gal 实弹教训:
    风格词放尾巴会被人物描述带跑) + 反向词封另一头 (写实店禁二次元, 动漫店禁真人)."""
    from ..engine.gal import is_anime_style
    art = runtime.art_style_of(content) \
        or "电影质感写实，柔和主光，胶片颗粒感，克制的调色，高细节"
    anime = is_anime_style(art)
    # 反向词把【邻近流派】也封死 — 出戏的元凶不是跨阵营(写实vs动漫),
    # 而是同阵营内的流派漂移 (厚涂/剧画/美漫混进赛璐璐, 七个角色五种画风)
    neg = (("写实照片,真人,3D渲染,照片质感,厚涂,油画质感,美漫,欧美卡通,剧画,水墨,儿童简笔画,"
            if anime else "动漫风格,卡通,二次元,赛璐璐,手办,")
           + "低质量,崩坏,变形,畸形,肢体错误,多余的手指,面部扭曲,画面模糊,文字,水印")
    return art, neg


def _char_seed(content: dict, cid: str) -> int:
    """同一个角色每次重画都长同一张脸 — 直接用 gal.char_seed
    (审查实锤: 自己再写一个 crc32 版 = 同角色两条管线两张脸)."""
    from ..engine.gal import char_seed
    return char_seed(str(((content.get("story") or {}).get("id")) or ""), cid)


# 🏞 背景铁律 (Yi 2026-07-21: 背景就是背景, 主体一定要是背景): 正向条款会被地点
# detail 里的「猫咪懒洋洋趴在窗边」这类描写顶翻, 负面提示词必须同时压阵 —
# 三个出图口 (开档补图/游戏内重画/工坊画背景) 共用这一份。
_BG_NEG = "人物，人影，人群，动物，猫，狗，鸟，龙，兽，怪物，生物，宠物"


def _bg_negative(content: dict) -> str:
    return (_story_art(content)[1] + "，" + _BG_NEG).strip("，")


def _bg_prompt(content: dict, loc: dict) -> str:
    story = content.get("story") or {}
    era = ((story.get("world_long") or story.get("world_facts") or "")
           .strip().replace("\n", " "))[:140]
    # 🎨 tuning.bg_style: 背景专用画风 (Yi: 背景就是背景) — 有的本子 art_style 本身
    # 以生物为主体 (猫咪摄影), 直接喂背景就画出猫; 缺省回落统一画风
    art = str((story.get("tuning") or {}).get("bg_style") or "").strip()         or _story_art(content)[0]
    # 空镜铁律放句尾压轴 (地名/描述常自带生物名 — 铁律必须是模型读到的最后一句)
    return (f"{art}。场景概念图，强烈氛围与光影，景深，横构图宽幅。{era} "
            f"场景：{loc.get('name', '')}。{(loc.get('detail') or '')[:200]}"
            f"。铁律：空镜，画面里没有任何人物也没有任何生物——人、兽、龙、猫狗、鸟、"
            f"怪物一概不出现；哪怕场景名或描述里提到了它们，也只画它们不在场时的空舞台"
            f"（住处、痕迹、器物照画，活物本身绝不入画）；没有文字、字幕或水印")


_CRE_DIR = __import__("pathlib").Path(__file__).resolve().parents[1] / "static" / "scene" / "creature"


def _spawn_creature_art(content: dict) -> None:
    """🐲 生物图鉴图: t2i 一次, 全服共用 (授权生物按 id 定种子, 同怪永远同脸)。"""
    _CRE_DIR.mkdir(parents=True, exist_ok=True)
    art, neg = _story_art(content)
    for cr in (content.get("story") or {}).get("creatures") or []:
        crid = cr.get("id")
        if not crid:
            continue
        path = _CRE_DIR / f"{crid}.jpg"
        if not path.exists():   # 📖 图鉴图与立绘各自独立判缺 (曾因 continue 连坐跳过立绘)
            prompt = (f"{art}。怪物图鉴立绘：单体全身，威压构图，环境虚化，"
                      f"{cr.get('kind', '兽')}：{cr.get('name', '')}，{(cr.get('desc') or '')[:120]}")
            _enqueue_image(prompt, path, "1024*1024", negative=neg,
                           seed=_char_seed(content, str(crid)))
        sp_path = _SPRITE_DIR / f"{crid}.webp"
        if not sp_path.exists():   # 🎪 舞台立绘: 透底剪影上台 (worker 见 .webp 自动抠底)
            sp = (f"{art}。生物舞台立绘：画面里只有这一只生物，绝无人类猎人或其它生物同框；"
                  "全身站姿完整不裁切，皮肤鳞甲羽毛完好覆盖躯体——绝不显露内脏、肋骨或肌肉解剖结构；"
                  "威压占满画面，背景为纯粹的极深色（近黑），"
                  f"{cr.get('kind', '兽')}：{cr.get('name', '')}，{(cr.get('desc') or '')[:120]}")
            _enqueue_image(sp, sp_path, "1024*1280",
                           negative=(neg + "，外露的骨骼，肋骨，内脏，肌肉解剖结构，"
                                     "骷髅，腐尸质感，人类，猎人").strip("，"),
                           seed=_char_seed(content, str(crid) + "·v2"))


def _spawn_location_bg(content: dict, loc: dict | None) -> None:
    # authored places deserve art too — the generated-only gate left whole authored
    # stories playing on gradient fallbacks (file-exists check prevents rework)
    if not loc or not loc.get("id"):
        return
    path = _BG_DIR / f"{loc['id']}.jpg"
    if path.exists():
        return
    _enqueue_image(_bg_prompt(content, loc), path, "1280*720",
                   negative=_bg_negative(content))


def _queue_snap(payload: dict | None) -> None:
    """📷 Pop an engine-minted snap off a phone payload and queue its render — the
    message arrives instantly, the photo develops in the background (the client
    keeps retrying the img until the file lands).
    同脸铁律 (Yi 2026-07-15: 自拍也要角色形象稳定): 有底图的角色自拍走 i2i 改绘
    (EDIT_MODEL 保脸, 与表情差分同管线); 无底图回落 char_seed 定种 t2i。"""
    sn = (payload or {}).pop("snap", None)
    if not (sn and sn.get("url") and sn.get("prompt")):
        return
    path = _SNAP_DIR / sn["url"].rsplit("/", 1)[-1]
    if sn.get("selfie") and sn.get("cid"):
        from ..engine.sprites import base_of
        base = base_of(str(sn["cid"]))
        if base is not None:
            scene = str(sn.get("scene") or "")[:100]
            art = str(sn.get("art") or "")[:60]

            def _selfie_work(base=base, path=path, scene=scene, art=art):
                try:
                    if path.exists():
                        return
                    from ..engine.gal import shrink_jpg
                    from ..engine.qwen import edit_image
                    img = edit_image(
                        base.read_bytes(),
                        "严格保持照片中人物的性别、发型、五官、体格与服装特征完全不变，"
                        f"改画成TA自己举着手机拍的一张自拍：所在环境是{scene}。"
                        "手机自拍构图，轻微俯仰角，浅景深，生活抓拍感，无文字水印"
                        # 🎨 画风跟世界走 (混搭实弹: 动漫底图硬套写实质感出半写实)
                        + (f"。画面基调与人物画风保持原图一致：{art}" if art
                           else "。画风质感与原图完全一致"),
                        mime="image/jpeg")
                    if img:
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_bytes(shrink_jpg(img, quality=82, max_side=1024))
                except Exception:
                    pass

            _imgthreading.Thread(target=_selfie_work, daemon=True).start()
            return
    _enqueue_image(sn["prompt"], path, "768*768", seed=sn.get("seed"))


def _ensure_char_avatars(content: dict, vn: bool = False) -> bool:
    """Point every faceless character at /scene/avatar/{id}.jpg and queue any missing
    portrait. Generated cast always follows the convention; an AUTHORED character
    keeps whatever art its author set — only empty faces are filled (寂声 shipped an
    all-authored cast and played faceless for a day). Returns True when an avatar_url
    was newly written (caller persists)."""
    from ..engine.sprites import rank_cast
    story = content.get("story") or {}
    world = ((story.get("world_long") or "").strip().replace("\n", " "))[:120]
    changed = False

    # 🚻 性别/年龄从卡上走 (角色卡 v2): 「武备官/佣兵」这类词会被生图模型脑补成
    # 男性 — 实弹: 女武备官的立绘画成了男骑士, 头像另一条提示词碰巧画对, 同脸法随之破
    def _look_bits(c: dict) -> str:
        sp = (c.get("species") or "").strip()
        g = (c.get("gender") or "").strip()
        if sp and sp not in ("人", "人类"):
            # 🐱 非人角色: 性别词换物种语系, 并硬性排除人类身影
            g = {"男": "公", "女": "母"}.get(g, "")
            return f"{g}{sp}，画面中只有这只{sp}——绝不出现任何人类或人形身影"
        g = {"男": "男性", "女": "女性"}.get(g, g)
        return "，".join(x for x in (g, (c.get("age_band") or "").strip()) if x)

    # 🏅 重要性排序 (Yi: 智能检索要给人物重要性排名): 限流/排队时主角位、恋爱位
    # 的脸先落地; 重要角色哪怕此刻不在场, 立绘也在这条每回合补漏的队里
    for c in rank_cast(story.get("characters") or []):
        cid, name = c.get("id"), c.get("name")
        if not cid or not name:
            continue
        if not c.get("generated") and (c.get("avatar_url") or "").strip() \
                and c.get("avatar_url") != f"/scene/avatar/{cid}.jpg":
            continue  # the author chose this face — never repaint it
        url = f"/scene/avatar/{cid}.jpg"
        if c.get("avatar_url") != url:
            c["avatar_url"] = url
            changed = True
        path = _AV_DIR / f"{cid}.jpg"
        if path.exists():
            continue
        try:   # 📇 同脸捷径: 有立绘底图 → 头像从底图裁 (零成本且与立绘绝对同脸)
            from ..engine.sprites import avatar_from_base
            _av = avatar_from_base(cid)
            if _av:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(_av)
                continue
        except Exception:
            pass
        bits = "，".join(b for b in (name, _look_bits(c), c.get("role") or "",
                                     (c.get("persona_text") or "")[:160]) if b)
        # 🎨 一世界一画风: 风格开头压阵 + 反向词 + 稳定种子 (同角色重画不换脸)
        art, neg = _story_art(content)
        prompt = (f"{art}。人物肖像，胸像特写，正面微侧，目光看向镜头外，"
                  f"柔和的侧光，背景虚化，情绪克制内敛：{bits}。世界背景：{world}")
        _enqueue_image(prompt, path, "768*768", negative=neg,
                       seed=_char_seed(content, cid))
    # 🎀 VN stories also render a TALL standing sprite per character (the galgame 立绘);
    # deep near-black backdrop → worker 抠底成透底剪影 (Yi: 和 galgame 一样要无背景)
    if vn or (story.get("tuning") or {}).get("vn_mode"):
        art, neg = _story_art(content)
        world = ((story.get("world_long") or "").strip().replace("\n", " "))[:120]
        for c in rank_cast(story.get("characters") or []):
            cid, name = c.get("id"), c.get("name")
            if not cid or not name:
                continue
            spath = _SPRITE_DIR / f"{cid}.webp"
            if spath.exists():
                continue
            bits = "，".join(b for b in (name, _look_bits(c), c.get("role") or "",
                                         (c.get("persona_text") or "")[:160]) if b)
            sp = (f"{art}。游戏立绘：单人站姿，全身或及膝，竖构图，正面微侧，"
                  "视线看向观者，人物完整居中不裁切，背景为纯粹的极深色（近黑），"
                  f"人物打柔和主光：{bits}。世界背景：{world}")
            _enqueue_image(sp, spath, "720*1280", negative=neg,
                           seed=_char_seed(content, cid))
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
            goal=st.get("goal", "") or runtime.goal_for(r.pinned_content or {}, st),
            progress=runtime.act_progress(r.pinned_content or {}, st, int(st.get("act", 1))),
            location=runtime.location_view(r.pinned_content or {}, st),
            relations=runtime.relations_summary(r.pinned_content or {}, st),
            following=list(st.get("following") or []),
            beasts=runtime.creatures_here(r.pinned_content or {}, st, mark=False),
            factions=factions_mod.view(r.pinned_content or {}, st),
            taste=taste_mod.view(st),
            here=runtime.scene_cast(r.pinned_content or {}, st,
                                    exclude_id=pcid if mode == "character" else None),
            pending_choice=st.get("pending_choice"),
            player_character_name=(runtime._char_name(r.pinned_content or {}, pcid) if pcid else None),
            pressure=int(st.get("pressure", 0) or 0),
            player_hp=st.get("player_hp", "healthy"),
            money=st.get("money"),
            currency=(runtime.currency_of(r.pinned_content or {})
                      if st.get("money") is not None else None),
            attrs=st.get("attrs"),
            quests=list(st.get("quests") or []),
            can_reincarnate=bool(runtime.sandbox_on(r.pinned_content or {})
                                 and st.get("player_hp") == "dead" and not st.get("ended")),
            powers=list(st.get("powers") or []),
            identity=st.get("identity"),
            inventory=list(st.get("inventory") or []),
            pressure_name=((runtime.pressure_cfg(r.pinned_content or {}) or {}).get("name")),
            threat=runtime.threat_view_of(r.pinned_content or {}, st),
            sanity=runtime.sanity_view_of(r.pinned_content or {}, st),
            clock=runtime.clock_view(r.pinned_content or {}, st),
            promises=runtime.promises_view(r.pinned_content or {}, st),
            phone_unread=runtime.phone_total_unread(r.pinned_content or {}, st),
            phone_on=runtime.phone_enabled(r.pinned_content or {}),
            verdict=runtime.verdict_view(r.pinned_content or {}, st),
            cultivation=runtime.cult_view(r.pinned_content or {}, st),
        ),
        cast=cast,
        created_at=r.created_at,
    )


def _to_beat(b: BeatModel) -> Beat:
    return Beat(id=b.id, seq=b.seq, type=b.type, speaker_name=b.speaker_name, text=b.text,
                author=b.author, mood=b.mood)


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
def list_runs(archived: bool = False,
              user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Default = the continue list (hidden runs excluded); ?archived=1 = the hidden shelf."""
    rows = (
        db.query(RunModel)
        .filter(RunModel.owner_id == user.id,
                RunModel.archived == (1 if archived else 0))
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
    # 💎 门票 (P1 收费包): 有 access 包且一张没买 → 拦在门外 (作者自动全通行)
    from .packs import access_blocked
    if access_blocked(db, user.id, story.id, story.owner_id == user.id):
        raise HTTPException(403, "这本剧本需要通行包——先在剧本页购入门票")

    version, content = _pin_content(story, db)
    # own a private copy — this run may grow its own map (bootstrap start place, emergent
    # locations), and we must never mutate the shared published snapshot.
    content = copy.deepcopy(content)

    # 🔞 decided up front so the conjured cast can carry the tone from birth. The player's
    # run-start toggle works on EVERY story (the platform age-gates at signup); a
    # story-level mature flag is simply always-on regardless of the toggle.
    mature_run = bool((content.get("story") or {}).get("mature")) or bool(body.mature)

    # 🏖 sandbox: the player DEFINES the world at run start — their private copy runs on
    # that worldview, and opens with a small cast conjured from it (grows forever in play)
    if runtime.sandbox_on(content):
        if (body.worldview or "").strip():
            wv = body.worldview.strip()[:2000]
            content["story"]["world_long"] = wv
            content["story"]["world_facts"] = wv[:400]
        runtime.seed_sandbox_cast(content, mature=mature_run)
        # 🌱 开局立法: no authored ladder → generate one that FITS this worldview
        # (每个世界都该有自己的升级之路); lands in the run's private pinned copy.
        try:
            runtime.ensure_progression(content)
        except Exception:
            pass

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
    state["goal"] = runtime.goal_for(content, state, 1)
    # 🧭 口味温启动: 账号级风格先验 (只学风格不带剧透) — 换个本子世界依然懂你
    _seed_taste = taste_mod.seed_from_account(getattr(user, "taste", None))
    if _seed_taste:
        state["taste"] = _seed_taste
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
    _spawn_creature_art(content)   # 🐲 图鉴图: 每只生物一张 (画风圣经+定种子, 幂等)
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
    # 💎 收费包发货 (确定性, run 创建时一次结算): 开局钱/金手指位/开局物件
    from .packs import owned_grants
    for _g in owned_grants(db, user.id, story.id, story.owner_id == user.id):
        _b = int(_g.get("start_money_bonus") or 0)
        if _b and runtime.sandbox_on(content):
            state["money"] = int(state.get("money") or 0) + _b
        for _pw in (_g.get("powers") or []):
            if _pw and _pw not in (state.get("powers") or []):
                state.setdefault("powers", []).append(str(_pw)[:40])
        for _it in (_g.get("items") or []):
            state.setdefault("inventory", []).append(
                {"name": str(_it.get("name") or "")[:16],
                 "detail": str(_it.get("detail") or "")[:60]})
    if state.get("powers"):
        state["powers"] = state["powers"][:6]
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
    # 🌌 跨存档残响 (活世界 P4): 同一剧本的上一段人生留下回声 — 当时暖过的角色
    # 在新时间线里带着说不清的既视感; 玩家习惯档案跟人走 (角色印象不带 —
    # 他们没见证这条线, 认知边界不破)
    prev = (db.query(RunModel)
            .filter(RunModel.owner_id == user.id, RunModel.story_id == story.id)
            .order_by(RunModel.created_at.desc()).first())
    if prev is not None and isinstance(prev.state, dict):
        pst = prev.state or {}
        facts = [str(f) for f in ((pst.get("profile") or {}).get("facts") or [])][:6]
        warm = [cid for cid, sc in (pst.get("rel") or {}).items()
                if isinstance(sc, dict)
                and (int(sc.get("closeness", 0) or 0) >= 30
                     or int(sc.get("romance", 0) or 0) >= 25)]
        if warm:
            state["echo"] = {"from_run": prev.id, "chars": warm[:6]}
        if facts:
            state["profile"] = {"facts": facts, "by_char": {}, "turns": 0}

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
    # (新档的 pinned content 自带现行 tuning, 函数内部自己识别 vn_mode)
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
    # 保真落库 (Yi: 进沙盒要有开场白) — 钩子里主角开口那句是 dialogue+speaker,
    # 压成无名旁白的话, VN 里整个开场没有人亮、没有人说话
    opening = runtime.build_opening(content, state)
    run.beats = [
        BeatModel(seq=i, type=b.get("type", "description"),
                  speaker_name=b.get("speaker_name"), text=b.get("text", ""),
                  author="engine")
        for i, b in enumerate(opening)
    ]
    db.add(run)
    db.commit()
    db.refresh(run)
    return _to_run(run)


@router.get("/{run_id}", response_model=Run)
def get_run(run_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    r = _own_run(run_id, user, db)
    out = _to_run(r)
    # 🖼 丢单自愈: 图片队列在内存里, 重启会吞掉在途的背景渲染 (实弹: 领航塔永远
    # 停在关键词兜底图)。恢复存档时补一枪当前地点 — 幂等, 文件在就直接返回
    try:
        _spawn_location_bg(r.pinned_content or {},
                           runtime.current_location(r.pinned_content or {}, r.state or {}))
        _spawn_creature_art(r.pinned_content or {})   # 🐲 生物图/立绘同样自愈
    except Exception:
        pass
    # 竖屏 App 常驻件: 恢复存档时建议 chips 必须在。新档回合会把它们写进 state；
    # 老档缺这一份就现算一次（含确定性兜底），下一回合起自然走持久化通路。
    st = r.state or {}
    saved = st.get("suggestions") or []
    if saved:
        out.suggestions = saved
    elif not st.get("ended"):
        try:
            out.suggestions = runtime.arrival_suggestions(r.pinned_content or {}, st)
        except Exception:
            pass
    return out


@router.delete("/{run_id}", status_code=204)
def delete_run(run_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.delete(_own_run(run_id, user, db))
    db.commit()


@router.get("/{run_id}/market")
def get_market(run_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """🛒 今日集市: world-true goods, re-stocked each in-story day (generated once/day)."""
    r = _own_run(run_id, user, db)
    st = dict(r.state or {})
    try:
        view = runtime.market_view(r.pinned_content or {}, st)
    except ValueError as e:
        raise HTTPException(400, str(e))
    r.state = st
    flag_modified(r, "state")
    db.commit()
    _queue_item_icons(st, view.get("items"))   # 🎒 摊上的货第一次亮相 → 排队出图
    return view


@router.post("/{run_id}/market/buy")
def buy_market(run_id: str, body: MarketBuyIn,
               user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Buying is a ledger op: money down, item into the run's inventory, audited."""
    r = _own_run(run_id, user, db)
    st = dict(r.state or {})
    try:
        view = runtime.market_buy(r.pinned_content or {}, st, body.item_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    r.state = st
    flag_modified(r, "state")
    db.commit()
    return view


@router.post("/{run_id}/archive")
def archive_run(run_id: str, archived: bool = True,
                user: User = Depends(current_user), db: Session = Depends(get_db)):
    """🙈 隐藏而非删除: leave the continue list, keep every beat. ?archived=0 restores."""
    r = _own_run(run_id, user, db)
    r.archived = 1 if archived else 0
    db.commit()
    return {"id": r.id, "archived": bool(r.archived)}


@router.post("/{run_id}/rewind", response_model=Run)
def rewind_run(run_id: str, body: RewindIn,
               user: User = Depends(current_user), db: Session = Depends(get_db)):
    """重说/回溯 (docs/ux-design.md P1): restore the run to how it stood BEFORE a player
    turn and drop everything from that turn on. seq omitted = the latest player turn
    (the 重说 button); explicit seq = that turn (长按回溯). The client then either
    re-sends the same input (重说) or lets the player type anew (回溯). Emergent
    content minted after the rewind point stays in the world — the ledger of what
    exists only grows; only what HAPPENED is unwound."""
    r = _own_run(run_id, user, db)
    with _TURN_GUARD:
        if run_id in _TURN_ACTIVE:
            raise HTTPException(409, "回合进行中，等它说完再重来")
    q = db.query(BeatModel).filter(BeatModel.run_id == run_id,
                                   BeatModel.author == "player",
                                   BeatModel.state_before.isnot(None))
    b = (q.filter(BeatModel.seq == body.seq).first() if body.seq is not None
         else q.order_by(BeatModel.seq.desc()).first())
    if not b:
        raise HTTPException(400, "没有可回溯的落点（这局更早的回合没有留存档快照）")
    r.state = b.state_before
    # 内容也回卷 (Yi: 重说要清记忆): the FIRST content snapshot at/after the rewind point
    # is the story copy as it stood back then — everything the erased timeline minted
    # (characters, places, world facts) vanishes with the timeline that made it.
    cb = (db.query(BeatModel)
          .filter(BeatModel.run_id == run_id, BeatModel.seq >= b.seq,
                  BeatModel.content_before.isnot(None))
          .order_by(BeatModel.seq.asc()).first())
    if cb is not None:
        r.pinned_content = cb.content_before
        flag_modified(r, "pinned_content")
    db.query(BeatModel).filter(BeatModel.run_id == run_id,
                               BeatModel.seq >= b.seq).delete()
    db.commit()
    db.refresh(r)
    return _to_run(r)


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
    # ▶ drive 防刷 (⚖️ 无点击不推进): 观剧拍零输入, 一段脚本就能空转无人值守地刷剧情
    # 刷账单 — 服务端强制两拍最小间隔, 不信任客户端的节流
    if body.channel == "drive":
        _dnow = _time_mod.time()
        if _dnow - float(_DRIVE_LAST.get(run_id, 0.0)) < get_settings().drive_min_seconds:
            raise HTTPException(429, "看得太快了，喘口气再往下")
        _DRIVE_LAST[run_id] = _dnow
    # 🎫 幂等键: 客户端每次点击带唯一 client_turn_id — 网络层重放/重试 bug 重复送达的
    # 同一次点击, 不再推进第二次剧情 (无点击不推进的服务端底线)
    if (body.client_turn_id
            and str((r.state or {}).get("last_client_turn_id") or "") == body.client_turn_id):
        raise HTTPException(409, "这一拍已经演过了（重复提交）")
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
            state_before=(r.state or {}),  # 重说/回溯: this turn is a rewind point
        ))
        next_seq += 1
    db.commit()

    # snapshot everything the stream needs, so it doesn't touch the request session
    state0 = r.state or {}
    if body.client_turn_id:   # 🎫 随 final state 落库 — 重放的同一键在上面被 409
        state0["last_client_turn_id"] = body.client_turn_id
    persona_dict = _persona_dict(persona) if persona else {}
    start_seq = next_seq
    # pre-turn content snapshot: only PERSISTED if this turn ends up mutating content —
    # then a rewind can erase everything the erased timeline created (Yi: 重说要清记忆)
    content_snapshot = copy.deepcopy(content)
    turn_first_seq = start_seq - 1 if (body.input or "").strip() else start_seq

    # 🔒 one turn at a time per run: a double-submit (double click / two tabs) would race
    # two streams over the same state and silently clobber it — refuse the second.
    # 双层闸: 进程内 set 快拒, flock 兜住多 worker/多进程 (见 _turn_lock_acquire)。
    # Acquired here (nothing below raises before the stream starts); released in sse().
    with _TURN_GUARD:
        if run_id in _TURN_ACTIVE:
            raise HTTPException(409, "上一回合还在进行中，等它说完")
        _turn_lockf = _turn_lock_acquire(run_id)
        if _turn_lockf is None:
            raise HTTPException(409, "上一回合还在进行中，等它说完")
        _TURN_ACTIVE.add(run_id)
    _turn_t0 = _time_mod.perf_counter()

    # 2. stream the engine turn on a FRESH session, persisting + flushing per beat
    def sse():
        db2 = SessionLocal()
        try:
            run = db2.get(RunModel, run_id)
            seq = start_seq
            final = None
            stage = director.TurnStage()   # 🎬 本回合的演出记忆 (音效去重/单次白闪)
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
                    _queue_snap(payload)  # 📷 render the attached photo off-path
                    yield _event({"event": "phone", "message": payload})
                    continue
                if kind == "token":
                    # 双拍合同的渲染拍逐 token 直出 — not persisted; the assembled beats
                    # follow as normal "beat" events and are the durable record.
                    yield _event({"event": "token", "t": payload})
                    continue
                if kind == "peek":
                    # 📱 查TA的设备: 结构化视图直达手机壳, 正文拍照旧落库
                    yield _event({"event": "peek", "peek": payload})
                    continue
                if kind == "sugg":
                    yield _event({"event": "sugg", "suggestions": payload})
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
                    bd = _to_beat(eb).model_dump()
                    try:   # 🎬 导演注记 (sfx/flash/expr/act) 只随流走, 不进库
                        bd.update(stage.beat_fx(payload.get("text", ""), payload.get("mood"),
                                                payload.get("act")))
                    except Exception:
                        pass
                    yield _event({"event": "beat", "beat": bd})
                else:
                    final = payload
            # persist final state + emit the trailing meta events
            if final is not None:
                run.state = final["state"]
                try:   # 🧭 口味沉淀: 档内分布慢混进账号 (纯风格, 零剧情内容)
                    _rt = (final["state"] or {}).get("taste") or {}
                    if _rt:
                        _uu = db2.get(User, run.owner_id)
                        if _uu is not None:
                            _uu.taste = taste_mod.blend_account(_uu.taste or {}, _rt)
                except Exception:
                    pass
                # 🖼 every turn is a backfill chance: runs from before portraits shipped
                # (or whose renders got throttled) pick their faces up here
                av_changed = False
                try:
                    # vn 旗以【现行 story】为准: 老档的 pinned content 钉在 vn_mode
                    # 加进剧本之前, 只看 pinned 的话这些档永远长不出立绘 (疗养院实锤)。
                    # 五分钟小缓存 — 别为一个几乎不变的旗每回合取一次 Story 行 (审查实锤)
                    _now_ts = _time_mod.time()
                    _hit = _VN_FLAG_CACHE.get(run.story_id)
                    if _hit and _now_ts - _hit[1] < 300:
                        _vn = _hit[0]
                    else:
                        _srow = db2.get(StoryModel, run.story_id)
                        _vn = bool(((_srow.tuning if _srow is not None else {}) or {})
                                   .get("vn_mode"))
                        _VN_FLAG_CACHE[run.story_id] = (_vn, _now_ts)
                    av_changed = _ensure_char_avatars(content, vn=_vn)
                except Exception:
                    pass
                if final.get("content_mutated") or av_changed:
                    # the run grew an emergent character or location (or gained avatar
                    # urls) — persist its private story copy
                    run.pinned_content = content
                    flag_modified(run, "pinned_content")
                    # 🧭 a moved_to may have generated the place mid-turn: queue its bg
                    _spawn_location_bg(content, runtime.current_location(content, final["state"]))
                if final.get("content_mutated"):
                    # pin the pre-turn content to this turn's first beat: the rewind
                    # anchor that lets an erased timeline take its creations with it
                    fb = (db2.query(BeatModel)
                          .filter(BeatModel.run_id == run_id,
                                  BeatModel.seq == turn_first_seq).first())
                    if fb is not None and fb.content_before is None:
                        fb.content_before = content_snapshot
                db2.commit()
                yield _event({"event": "state", "state": _to_run(run).state.model_dump()})
                yield _event({"event": "scene", "scene": final.get("scene")})
                yield _event({"event": "cast", "cast": final.get("cast", [])})
                yield _event({"event": "here", "here": final.get("here", []),
                              "beasts": final.get("beasts", []),
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
                if final.get("threat_view"):
                    yield _event({"event": "threat", "threat": final["threat_view"]})
                if final.get("sanity_view"):
                    yield _event({"event": "sanity", "sanity": final["sanity_view"]})
                yield _event({"event": "place", "location": final.get("location")})
                try:   # 🎬 回合演出单: BGM 选曲 + 色调 (danger>frail>night>none)
                    yield _event({"event": "direct", "direct": director.stage_turn(final)})
                except Exception:
                    pass
                if final.get("new_day"):
                    # 🌅 新的一天: 过场卡+输入锁+自由活动菜单 (菜单已在 suggestions 里)
                    yield _event({"event": "newday", "day": final["new_day"]})
                yield _event({"event": "promises", "promises": final.get("promises", [])})
                yield _event({"event": "verdict", "verdict": final.get("verdict")})
                if final.get("pending_choice"):
                    yield _event({"event": "choice", "choice": final["pending_choice"]})
                if final.get("move_request"):
                    yield _event({"event": "move_request", "move_request": final["move_request"]})
                if final.get("audit"):
                    # 📋 the turn's event audit (accepts + rejections with reasons) — the
                    # playtest debugging sheet; the client logs it to the console
                    yield _event({"event": "audit", "audit": final["audit"]})
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
                # 📈 one line per turn: duration, beats, dice, what the audit decided
                metrics.log("turn", run=run_id[:8],
                            ms=int((_time_mod.perf_counter() - _turn_t0) * 1000),
                            beats=seq - start_seq,
                            dice=((final.get("dice") or {}).get("outcome") or ""),
                            audit=",".join(sorted({(e.get("e") or "") + ("" if e.get("ok") else "!")
                                                   for e in (final.get("audit") or [])})))
            yield _event({"event": "done"})
        except (Exception, GeneratorExit) as e:  # never leave the client hanging
            # 🔒 P0 文实分家兜底 (审计实弹: 回合中途异常/客户端断流时, 已入库的
            # 移动/收物/死亡旁白, 其 state 变更全丢 → 恢复档时文与实永久分家)。
            # 引擎就地改 state0, 崩前的账本变更都在它上面 — 无论如何都落库, 与已
            # commit 的 beats 对齐。GeneratorExit (客户端断开) 也走这条, 保住半程账本。
            try:
                run = db2.get(RunModel, run_id)
                if run is not None and isinstance(state0, dict):
                    run.state = state0
                    flag_modified(run, "state")
                    db2.commit()
            except Exception:
                pass
            if isinstance(e, GeneratorExit):
                raise
            yield _event({"event": "beat", "beat": {"id": "", "type": "description",
                          "speaker_name": None, "text": f"[出错] {type(e).__name__}", "author": "engine"}})
            yield _event({"event": "done"})
        finally:
            with _TURN_GUARD:
                _TURN_ACTIVE.discard(run_id)
            _turn_lock_release(_turn_lockf)
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
            if new_loc is None:
                raise HTTPException(400, {"not_a_place": "这不像一个具体的去处"})
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
    _enc = runtime.creature_arrival_beat(content, st)   # 🐲 走进了它的领地
    if _enc:
        discoveries = discoveries + [{"text": _enc.get("text", "")}]
    if discoveries:
        seq = (r.beats[-1].seq + 1) if r.beats else 0
        present_ids = [c.get("id") for c in runtime.scene_characters(content, st) if c.get("id")]
        for i, d in enumerate(discoveries):
            db.add(BeatModel(run_id=r.id, seq=seq + i, type="description", speaker_name=None,
                             text=d.get("text", ""), author="engine", present_ids=present_ids))
    # the scene just changed under the player's feet — regenerate the next-step chips
    # for THIS place and THESE people (the old ones point at who's no longer here);
    # persisted so a resume shows these, not the pre-move set
    sugg = runtime.arrival_suggestions(content, st)
    st["suggestions"] = sugg
    r.state = st
    if generated:
        r.pinned_content = content
        flag_modified(r, "pinned_content")
    db.commit()
    db.refresh(r)
    out = _to_run(r)
    out.discoveries = discoveries
    out.suggestions = sugg
    return out


@router.get("/{run_id}/map")
def get_map(run_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """The discovered world: unlocked places, current position, who stands where.
    Locked places appear only as an unnamed count."""
    r = _own_run(run_id, user, db)
    view = runtime.map_view(r.pinned_content or {}, r.state or {})
    # 🖼 地图缩略图补枪: 地图会展示所有已发现地点的缩略图, 但背景只在玩家亲临时
    # 生成 (实弹: 枢纽地点 404×27)。每次开图最多补 2 张, 排队不阻塞
    _missing = 0
    for n in (view.get("nodes") or []):
        if _missing >= 2:
            break
        lid = n.get("id")
        if lid and not (_BG_DIR / f"{lid}.jpg").exists():
            loc = runtime._location_by_id(r.pinned_content or {}, lid)
            if loc:
                _spawn_location_bg(r.pinned_content or {}, loc)
                _missing += 1
    return view


@router.post("/{run_id}/bg/regen")
def regen_bg(run_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """🖼 玩家对当前地点的背景不满意 → 删掉旧图、重新排队生成一张。
    Run-private places (sandbox start/emergent) are the player's own art — free to redo.
    Authored places share their art with every run of the story, so only the story's
    author may redraw those. One request per run per minute keeps the queue sane."""
    r = _own_run(run_id, user, db)
    st = dict(r.state or {})
    content = r.pinned_content or {}
    loc = runtime.current_location(content, st)
    if not loc or not loc.get("id"):
        raise HTTPException(404, "此刻不在任何有背景的地点")
    lid = loc["id"]
    story_row = db.get(StoryModel, r.story_id)
    authored = {l.get("id") for l in ((story_row.locations if story_row else None) or [])}
    if lid in authored and (not story_row or story_row.owner_id != user.id):
        raise HTTPException(403, "这个地点的背景是剧本作者的美术，只有作者能重画")
    import time as _time
    now = _time.time()
    if now - float(st.get("last_bg_regen") or 0) < 60:
        raise HTTPException(429, "刚提交过重画，稍等一分钟再试")
    st["last_bg_regen"] = now
    r.state = st
    db.commit()
    path = _BG_DIR / f"{lid}.jpg"
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
    _enqueue_image(_bg_prompt(content, loc), path, "1280*720",
                   negative=_bg_negative(content))
    return {"queued": True, "location_id": lid, "url": f"/scene/bg/{lid}.jpg"}


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


@router.patch("/{run_id}/beat/{beat_id}")
def edit_beat(run_id: str, beat_id: str, body: dict = Body(...),
              user: User = Depends(current_user), db: Session = Depends(get_db)):
    """✏️ 编辑对话正史 (Yi 2026-07-23: 自己的话/角色台词/旁白都能改): 只改文本,
    不重算账本 (好感/解锁/位置都是当时的裁决, 重算走撤回)。改动会进入后续回合的
    记忆窗口 — 这正是编辑的意义: 把别扭的一句修顺, 故事从更好的文本继续。
    说话人与拍型不可改 (名单与账本的完整性)。"""
    r = _own_run(run_id, user, db)
    text = str(body.get("text") or "").strip()
    if not text or len(text) > 600:
        raise HTTPException(400, "内容不能为空，也别超过600字")
    b = db.query(BeatModel).filter(BeatModel.id == beat_id,
                                   BeatModel.run_id == r.id).first()
    if b is None:
        raise HTTPException(404, "没有这一拍")
    if b.author != "player":
        text = runtime.dedash(text)   # 引擎侧文本继续吃标点守卫; 玩家的话保持原样
    b.text = text
    db.commit()
    db.refresh(b)
    return _to_beat(b)


@router.post("/{run_id}/character/{char_id}/rename")
def rename_character(run_id: str, char_id: str, body: RenameIn,
                     user: User = Depends(current_user), db: Session = Depends(get_db)):
    """🪪 rename an EMERGENT character in this run's private copy (fix bad births
    like「谁看见」). Authored characters keep their author-given names; the new
    name passes the same guard births do, and promise snapshots follow along."""
    r = _own_run(run_id, user, db)
    content = dict(r.pinned_content or {})
    chars = (content.get("story") or {}).get("characters") or []
    c = next((x for x in chars if x.get("id") == char_id), None)
    if not c:
        raise HTTPException(404, "没有这个人")
    if not c.get("generated"):
        raise HTTPException(403, "这是作者写定的角色，名字不能改")
    nm = (body.name or "").strip().strip("「」\"'")[:12]
    if not runtime.npc_name_ok(nm):
        raise HTTPException(400, "这个名字不像人名，换一个吧")
    if any(x.get("name") == nm and x.get("id") != char_id for x in chars):
        raise HTTPException(409, "已有同名角色")
    was = c.get("name") or ""
    c["name"] = nm
    r.pinned_content = content
    flag_modified(r, "pinned_content")
    st = dict(r.state or {})
    touched = False
    for p in st.get("promises") or []:   # 🤝 promises carry a name snapshot
        if p.get("char_id") == char_id and p.get("char_name") != nm:
            p["char_name"] = nm
            touched = True
    if touched:
        r.state = st
        flag_modified(r, "state")
    db.commit()
    return {"ok": True, "name": nm, "was": was}


@router.post("/{run_id}/location/{loc_id}/rename")
def rename_location(run_id: str, loc_id: str, body: RenameIn,
                    user: User = Depends(current_user), db: Session = Depends(get_db)):
    """📍 给涌现地点改名 (首次落成时的机会, Yi: 生成的名字乱)。授权地图不许改;
    出口按地名字符串连的 — 改名级联同步全图。"""
    r = _own_run(run_id, user, db)
    content = dict(r.pinned_content or {})
    locs = (content.get("story") or {}).get("locations") or []
    loc = next((l for l in locs if l.get("id") == loc_id), None)
    if not loc:
        raise HTTPException(404, "没有这个地方")
    if not (loc.get("generated") or str(loc_id).startswith("loc_")):
        raise HTTPException(403, "这是作者写定的地点，名字不能改")
    nm = (body.name or "").strip().strip("「」\"'")[:12]
    if not runtime.npc_name_ok(nm):
        raise HTTPException(400, "这个名字不像地名，换一个吧")
    if any(l.get("name") == nm and l.get("id") != loc_id for l in locs):
        raise HTTPException(409, "已有同名地点")
    was = loc.get("name") or ""
    loc["name"] = nm
    for l in locs:   # 🏷 级联: 出口按地名连的
        l["exits"] = [nm if e == was else e for e in (l.get("exits") or [])]
    r.pinned_content = content
    flag_modified(r, "pinned_content")
    db.commit()
    return {"ok": True, "name": nm, "was": was}


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
    # 📇 联系方式要靠剧情挣 (Yi): 没交换过, 你压根拨不通TA
    if not runtime.has_contact(st, char_id):
        raise HTTPException(403, "你还没有TA的联系方式。见面聊出交情，或者直接开口要一个。")
    persona = db.get(PersonaModel, r.persona_id)
    # 📱↔🎭 线上线下通气: 把TA亲历的最近正文喂给短信/来电 (per-char过滤在引擎侧)
    _cut = int(st.get("history_cut_seq") or 0)
    _bl = [{"author": b.author, "type": b.type, "text": b.text,
            "speaker_name": b.speaker_name, "present_ids": b.present_ids}
           for b in r.beats if b.seq >= _cut][-40:]
    try:
        view = runtime.phone_send(r.pinned_content or {}, st, _persona_dict(persona) if persona else {},
                                  char_id, body.text, beat_log=_bl)
    except ValueError as e:
        raise HTTPException(400, str(e))
    _queue_snap(view)  # 📷 the reply may carry a photo — render it off-path
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
    # 📱↔🎭 线上线下通气: 把TA亲历的最近正文喂给短信/来电 (per-char过滤在引擎侧)
    _cut = int(st.get("history_cut_seq") or 0)
    _bl = [{"author": b.author, "type": b.type, "text": b.text,
            "speaker_name": b.speaker_name, "present_ids": b.present_ids}
           for b in r.beats if b.seq >= _cut][-40:]
    try:
        view = runtime.phone_call(r.pinned_content or {}, st, _persona_dict(persona) if persona else {},
                                  char_id, body.text, beat_log=_bl)
    except ValueError as e:
        raise HTTPException(400, str(e))
    r.state = st
    flag_modified(r, "state")
    db.commit()
    return view


@router.get("/{run_id}/bestiary")
def get_bestiary(run_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """📖 生物图鉴: 见过的生物 (血阶/部位伤/习性/图鉴图), 没见过的只给个数。"""
    r = _own_run(run_id, user, db)
    if "bestiary" not in runtime.phone_apps(r.pinned_content or {}):
        raise HTTPException(404, "这个世界没有图鉴")
    return runtime.bestiary_view(r.pinned_content or {}, r.state or {})


@router.get("/{run_id}/bank")
def get_bank(run_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """🏦 银行 app: 余额 + 流水 + 可转账的联系人。现代设定 (device=手机) 默认开。"""
    r = _own_run(run_id, user, db)
    if "bank" not in runtime.phone_apps(r.pinned_content or {}):
        raise HTTPException(404, "这个世界没有这种 app")
    return runtime.bank_view(r.pinned_content or {}, r.state or {})


@router.post("/{run_id}/bank/transfer")
def bank_transfer(run_id: str, body: TransferIn,
                  user: User = Depends(current_user), db: Session = Depends(get_db)):
    """💸 给角色转账 — 真钱落账, TA 的记忆和短信都会知道这件事。"""
    r = _own_run(run_id, user, db)
    if "bank" not in runtime.phone_apps(r.pinned_content or {}):
        raise HTTPException(404, "这个世界没有这种 app")
    if (r.state or {}).get("ended"):
        raise HTTPException(409, "这局已经结束了")
    st = dict(r.state or {})
    persona = db.get(PersonaModel, r.persona_id)
    try:
        out = runtime.bank_transfer(r.pinned_content or {}, st,
                                    _persona_dict(persona) if persona else {},
                                    body.char_id, body.amount)
    except ValueError as e:
        raise HTTPException(400, str(e))
    r.state = st
    flag_modified(r, "state")
    db.commit()
    return out


@router.get("/{run_id}/social")
def get_social(run_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """📸 动态 app: 已认识角色的朋友圈 (账本指纹变了才出新帖, 渲染一次永久缓存)。"""
    r = _own_run(run_id, user, db)
    if "social" not in runtime.phone_apps(r.pinned_content or {}):
        raise HTTPException(404, "这个世界没有这种 app")
    st = dict(r.state or {})
    out = runtime.social_feed(r.pinned_content or {}, st)
    r.state = st
    flag_modified(r, "state")
    db.commit()
    return out


@router.post("/{run_id}/social/like")
def social_like(run_id: str, body: SocialLikeIn,
                user: User = Depends(current_user), db: Session = Depends(get_db)):
    r = _own_run(run_id, user, db)
    st = dict(r.state or {})
    try:
        out = runtime.social_like(r.pinned_content or {}, st, body.post_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    r.state = st
    flag_modified(r, "state")
    db.commit()
    return out


@router.post("/{run_id}/social/comment")
def social_comment(run_id: str, body: SocialCommentIn,
                   user: User = Depends(current_user), db: Session = Depends(get_db)):
    """💬 评论TA的动态 — TA 用自己的声音回一句 (每游戏日限5条)。"""
    r = _own_run(run_id, user, db)
    st = dict(r.state or {})
    persona = db.get(PersonaModel, r.persona_id)
    try:
        out = runtime.social_comment(r.pinned_content or {}, st,
                                     _persona_dict(persona) if persona else {},
                                     body.post_id, body.text)
    except ValueError as e:
        raise HTTPException(400, str(e))
    r.state = st
    flag_modified(r, "state")
    db.commit()
    return out


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
    st = r.state or {}
    # 🎒 背包/收纳里的物件第一次被翻看 → 配图排队 (懒生成, tid 永久缓存)
    _queue_item_icons(st, list(st.get("inventory") or [])
                      + [i for rows in (st.get("stashes") or {}).values() for i in rows])
    return runtime.journal(r.pinned_content or {}, st)


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
    # 🔒 a confrontation is a turn too — same one-at-a-time rule as /play (双层闸同款)
    with _TURN_GUARD:
        if run_id in _TURN_ACTIVE:
            raise HTTPException(409, "上一回合还在进行中，等它说完")
        _turn_lockf = _turn_lock_acquire(run_id)
        if _turn_lockf is None:
            raise HTTPException(409, "上一回合还在进行中，等它说完")
        _TURN_ACTIVE.add(run_id)

    def sse():
        db2 = SessionLocal()
        try:
            run = db2.get(RunModel, run_id)
            seq = start_seq
            final = None
            stage = director.TurnStage()   # 🎬 本回合的演出记忆 (音效去重/单次白闪)
            for kind, payload in gen:
                if kind == "dice":
                    yield _event({"event": "dice", "dice": payload})
                elif kind == "token":
                    yield _event({"event": "token", "t": payload})
                elif kind == "peek":
                    yield _event({"event": "peek", "peek": payload})
                elif kind == "sugg":
                    yield _event({"event": "sugg", "suggestions": payload})
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
                    bd = _to_beat(eb).model_dump()
                    try:   # 🎬 导演注记 (sfx/flash/expr/act) 只随流走, 不进库
                        bd.update(stage.beat_fx(payload.get("text", ""), payload.get("mood"),
                                                payload.get("act")))
                    except Exception:
                        pass
                    yield _event({"event": "beat", "beat": bd})
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
                if final.get("threat_view"):
                    yield _event({"event": "threat", "threat": final["threat_view"]})
                if final.get("sanity_view"):
                    yield _event({"event": "sanity", "sanity": final["sanity_view"]})
                if final.get("pending_choice"):
                    yield _event({"event": "choice", "choice": final["pending_choice"]})
            yield _event({"event": "done"})
        except Exception as e:
            yield _event({"event": "beat", "beat": {"id": "", "type": "description",
                          "speaker_name": None, "text": f"[出错] {type(e).__name__}", "author": "engine"}})
            yield _event({"event": "done"})
        finally:
            with _TURN_GUARD:
                _TURN_ACTIVE.discard(run_id)
            _turn_lock_release(_turn_lockf)
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
    content = r.pinned_content or {}
    try:
        res = runtime.apply_choice(content, st, body.option_id)
    except ValueError as e:
        raise HTTPException(400, {"no pending choice": "现在没有待决定的抉择",
                                  "unknown option": "没有这个选项"}.get(str(e), "不行"))
    r.state = st
    if res.pop("content_mutated", False):
        # ⚖️ a fate move conjured a brand-new place → persist the run's private copy + bg
        r.pinned_content = content
        flag_modified(r, "pinned_content")
        _spawn_location_bg(content, runtime.current_location(content, st))
    db.commit()
    return {"label": res.get("label", ""), "flag": res.get("flag"),
            "killed": res.get("killed"), "moved_to": res.get("moved_to")}


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
    """悬念离场: the player is leaving mid-run (page hide / back button beacon).
    ⚖️ 无点击不推进 (Yi 2026-07-14 定): beacon 不是点击 — 这里只暂存「TA走了」这个
    事实 (不跑 LLM 不落拍), 悬念钩由下一次玩家亲手点开的回合回放上台 (runtime 的
    parting_pending 消费点). 顺带修掉了旧版 beacon 与流式回合竞态插拍的隐患。
    Idempotent — repeated beacons within the window add nothing."""
    r = _own_run(run_id, user, db)
    st = dict(r.state or {})
    if st.get("ended") or not r.beats:
        return
    # 📵 mobile visibility events spam beacons — at most one staging per 10 minutes
    now_ts = _time_mod.time()
    if now_ts - float(st.get("parting_ts") or 0) < 600:
        return
    if not any(b.author == "player" for b in r.beats):
        return  # no conversation yet — nothing to hang a hook on
    st["parting_pending"] = {"ts": now_ts, "act": int(st.get("act", 1) or 1)}
    st["parting_ts"] = now_ts
    r.state = st
    db.commit()


@router.get("/{run_id}/relweb")
def get_relweb(run_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """🕸 关系网视图 (Yi 2026-07-18): 已认识的角色为节点, npc_rel 立场为边 (带演变
    日志 = 随时间变化可见), 外加玩家↔各角色的关系模式。只读, 不动账本。"""
    from ..engine import relationships as rel_mod
    r = _own_run(run_id, user, db)
    content, st = r.pinned_content or {}, r.state or {}
    met = set(st.get("met_ids") or [])
    pcid = st.get("player_character_id")
    dead = runtime._dead_ids(st)
    chars = [c for c in runtime._characters(content)
             if c.get("id") and c["id"] in met and c["id"] != pcid]
    nodes = [{"id": c["id"], "name": c.get("name") or "", "avatar_url": c.get("avatar_url"),
              "dead": c["id"] in dead} for c in chars]
    ids = {n["id"] for n in nodes}
    edges = []
    for key, e in (st.get("npc_rel") or {}).items():
        a, _, b = key.partition("|")
        stance = int(e.get("stance") or 0)
        if a in ids and b in ids and stance:
            edges.append({"a": a, "b": b, "stance": stance,
                          "label": e.get("label")
                          or runtime._STANCE_LABEL.get(stance, ""),
                          "log": list(e.get("log") or [])[-4:]})
    tun = runtime.tuning_for(content)
    rel_all = st.get("rel") or {}
    player = []
    for c in chars:
        sc = rel_all.get(c["id"])
        if not sc:
            continue
        view = rel_mod.state_for(c, sc, tun, lang=runtime.lang_of(content)) or {}
        player.append({"id": c["id"], "mode_name": view.get("mode_name") or "",
                       "closeness": int(sc.get("closeness", 0) or 0),
                       "romance": int(sc.get("romance", 0) or 0)})
    return {"nodes": nodes, "edges": edges, "player": player,
            "player_name": (st.get("player_character_id") and
                            runtime._char_name(content, pcid)) or None}


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


# ── 🌍 活世界 (living world): 开关 + 手动心跳 + 调度入口 ──────────────────────────
@router.post("/{run_id}/living")
def living_switch(run_id: str, body: dict = Body(default={}),
                  user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Flip a run's living-world switch (on/off + heartbeat interval in real hours).
    While ON, the server ticks the world even when the player is away: the clock
    turns, stood-up promises commit their consequences, and characters propose new
    dated meetings into the 小手机."""
    r = _own_run(run_id, user, db)
    st = dict(r.state or {})
    lc = living.set_living(st, bool(body.get("on")), body.get("hours"))
    r.state = st
    db.commit()
    return {"living": lc}


@router.post("/{run_id}/living/tick")
def living_tick_now(run_id: str, user: User = Depends(current_user),
                    db: Session = Depends(get_db)):
    """Owner-triggered immediate heartbeat (testing / 手动推一天). Same tick the
    scheduler runs, minus the due() wait."""
    r = _own_run(run_id, user, db)
    st = dict(r.state or {})
    out = living.world_tick(r.pinned_content or {}, st)
    r.state = st
    db.commit()
    return {"tick": out, "living": living.cfg(st),
            "clock": (st.get("clock") or {}),
            "news": [n for n in (st.get("living_news") or []) if not n.get("told")]}


@router.post("/{run_id}/character/{char_id}/image")
def upload_character_image(run_id: str, char_id: str, file: UploadFile = File(...),
                           user: User = Depends(current_user),
                           db: Session = Depends(get_db)):
    """🖼 玩家给角色换形象 (Yi: 玩家也可以自己上传人物图, 智能裁剪):
    一张图进来, rembg 找人 → 透底立绘 + 方形头像 + 改脸源图三件套;
    旧表情差分作废 (可再跑 /sprites/exprs 按新脸重做)。"""
    from ..engine import sprites as sprites_mod
    from .stories import _sniff_image
    r = _own_run(run_id, user, db)
    content = r.pinned_content or {}
    c = next((x for x in (content.get("story") or {}).get("characters", [])
              if x.get("id") == char_id), None)
    if not c:
        raise HTTPException(404, "这个剧本里没有该角色")
    # 同步处理器 = FastAPI 丢进线程池跑 — rembg/PIL 这几秒不冻事件循环 (审查实锤)
    data = file.file.read()
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(413, "图片太大（上限 5MB）")
    if not _sniff_image(data):
        raise HTTPException(415, "只支持 JPG / PNG / WebP 图片")
    out = sprites_mod.ingest_upload(char_id, data)
    c["avatar_url"] = out["avatar"]
    c["generated"] = False   # 玩家亲选的脸 — 引擎回填不许再重画它
    r.pinned_content = content
    flag_modified(r, "pinned_content")
    db.commit()
    return out


@router.post("/{run_id}/sprites/smart")
def smart_cast_sprites(run_id: str, body: dict = Body(default={}),
                       user: User = Depends(current_user),
                       db: Session = Depends(get_db)):
    """🔍 主角智能搜图 (Yi): 全员按「故事+角色」搜真实剧照 → 按剧本画风改绘 →
    立绘/头像/差分底三件套。后台线程; 玩家亲选的脸不动。"""
    from ..engine import sprites as sprites_mod
    r = _own_run(run_id, user, db)
    content = copy.deepcopy(r.pinned_content or {})
    cids = [str(x) for x in (body.get("chars") or [])] or None
    with _IMG_LOCK:
        if run_id in _EXPR_BUILDING:
            return {"queued": False, "busy": True}
        _EXPR_BUILDING.add(run_id)

    def _work():
        try:
            sprites_mod.smart_cast(content, cids)
        finally:
            with _IMG_LOCK:
                _EXPR_BUILDING.discard(run_id)

    _imgthreading.Thread(target=_work, daemon=True).start()
    return {"queued": True,
            "chars": cids or [c.get("id") for c in
                              (content.get("story") or {}).get("characters", [])]}


_EXPR_BUILDING: set = set()
_VN_FLAG_CACHE: dict = {}   # story_id → (vn_mode, ts) — 旗几乎不变, 五分钟一取


@router.post("/{run_id}/sprites/exprs")
def build_expr_sprites(run_id: str, body: dict = Body(default={}),
                       user: User = Depends(current_user),
                       db: Session = Depends(get_db)):
    """🎭 差分包: 给这局已登场的角色生成 喜/怒/哀/惊 改脸差分 + 挥手/抱臂/低头/伸手
    动作差分 (后台线程, 编辑既有底图不重画, 幂等可重跑补齐; 崩-gate 拦截变形差分).
    body.force=true 全部重做 (调整幅度标准后重刷用). 客户端按 beat.expr 换图."""
    r = _own_run(run_id, user, db)
    content = r.pinned_content or {}
    st = r.state or {}
    met = set(st.get("met_ids") or [])
    from ..engine import sprites as sprites_mod
    _cast = [c for c in runtime._characters(content)
             if c.get("id") and (not met or c.get("id") in met)
             and c.get("id") != st.get("player_character_id")
             and sprites_mod.base_of(c.get("id"))][:6]
    cids = [c.get("id") for c in _cast]
    # 🐾 非人形角色不做人类肢体动作差分 (布偶猫抱臂 = 崩), 表情照做
    no_pose = {c.get("id") for c in _cast if str(c.get("species") or "").strip()}
    if not cids:
        raise HTTPException(400, "还没有可用的角色底图")
    with _IMG_LOCK:
        if run_id in _EXPR_BUILDING:
            return {"queued": [], "busy": True}
        _EXPR_BUILDING.add(run_id)

    _force = bool(body.get("force"))

    def _work():
        try:
            sprites_mod.build_expr_pack(cids, force=_force, no_pose_cids=no_pose)
        finally:
            with _IMG_LOCK:
                _EXPR_BUILDING.discard(run_id)

    _imgthreading.Thread(target=_work, daemon=True).start()
    return {"queued": cids, "exprs": list(sprites_mod.DIFFS.keys())}


def _push_heartbeat_news(db, run, tick_out: dict) -> None:
    """🔔 一次心跳至多敲一次窗: 邀约优先 (角色亲笔的那句), 其次缺席留言."""
    if not tick_out or not (tick_out.get("anniv") or tick_out.get("event")
                            or tick_out.get("absent")):
        return   # 心跳空转不碰推送层也不查库 (审查实锤: 全架扫描 × 每 run 一查)
    from .. import webpush
    if webpush.quiet_now():
        return
    tag = f"lp-{run.id[:8]}"
    an = tick_out.get("anniv")
    if an:   # 纪念日最优先: 这一天的敲窗只为这一件事
        webpush.push_to_user(db, run.owner_id, an.get("name") or "有人",
                             f"今天，是我们认识满{an.get('months', 1)}个月的日子。",
                             url="/play", tag=tag)
        return
    ev = tick_out.get("event")
    if ev:
        # ⚖️ 邀约本体是词债还没写 (无点击不生成) — 推送只报人名, 用模板句
        webpush.push_to_user(db, run.owner_id, ev.get("name") or "有人找你",
                             "给你捎了句话，进来看看。", url="/play", tag=tag)
        return
    ab = tick_out.get("absent") or []
    if ab:
        webpush.push_to_user(db, run.owner_id, ab[0].get("name") or "有人",
                             "你没来。TA给你留了话。", url="/play", tag=tag)


def _state_fingerprint(st: dict) -> tuple:
    """轻量指纹: 检测玩家在心跳的 LLM 窗口内是否动过档 (回合数/时钟/历史长度)。
    只用于乐观并发比对, 不求密码学强度。"""
    clock = st.get("clock") or {}
    # _last_text 每回合结束都会重写, turns_in_act 每回合自增 — 玩家动过档必变
    return (str(st.get("_last_text") or "")[:80], int(st.get("turns_in_act", 0) or 0),
            int(st.get("act", 0) or 0), int(clock.get("day", 0) or 0),
            str(clock.get("slot", "")))


def living_heartbeat_pass() -> int:
    """Scheduler entry (main.py lifespan): one pass over the shelf, tick what's due.
    Own session, per-run commit — one bad run never stalls the others."""
    db = SessionLocal()
    ticked = 0
    try:
        rows = db.query(RunModel).filter(RunModel.archived == 0).all()
        for r in rows:
            st0 = r.state or {}
            if not living.is_on(st0) or not living.due(st0):
                continue
            st = copy.deepcopy(st0)
            rid = r.id
            try:
                # ⚖️ 无点击不推进: world_tick 只做状态数学, 不跑 LLM (词债押后到玩家
                # 回归的回合由 settle_pending 补演)。窗口虽小仍防覆盖: 写回前重读并
                # 比对指纹, 玩家在 tick 期间动过档就丢弃本次 tick (下轮重排)。
                fp0 = _state_fingerprint(st0)
                out = living.world_tick(r.pinned_content or {}, st)
                db.expire_all()
                fresh = db.get(RunModel, rid)
                if fresh is None or _state_fingerprint(fresh.state or {}) != fp0:
                    continue   # 玩家在 tick 期间动过档 — 放弃这次心跳, 不覆盖
                fresh.state = st
                flag_modified(fresh, "state")
                db.commit()
                r = fresh
                ticked += 1
                try:   # 🔔 P3 破壁: 心跳产出敲到现实; 静默时段不敲窗 (消息本体在小手机)
                    _push_heartbeat_news(db, r, out)
                except Exception:
                    pass
            except Exception:
                db.rollback()
    finally:
        db.close()
    return ticked
