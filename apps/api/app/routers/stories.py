from typing import Optional

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
from pydantic import BaseModel

from ..schemas import (
    Character,
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
        updated_at=str(s.updated_at) if s.updated_at else None,
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
        threat=s.threat,
        dooms=s.dooms,
        sanity=s.sanity,
        rules=s.rules,
        clock=s.clock,
        phone=s.phone,
        verdict=s.verdict,
        sandbox=s.sandbox,
        creatures=s.creatures or [],
        factions=s.factions or [],
        opening=s.opening,
        completion=_completion(s),
    )


def _auto_cover(s: StoryModel) -> dict[str, str] | None:
    from ..engine import cover as cover_mod
    if not cover_mod.ENABLED:      # 🔌 关着的时候一张也不下发 (卡面退回地点背景图)
        return None
    try:
        return cover_mod.urls(s.id)
    except Exception:
        return None


def _card_art(s: StoryModel) -> str | None:
    """🎬 卡面图: 自动封面的宽幅 → 作者手填的封面 → 第一个有背景图的地点 (兜底)。
    自动封面排在作者封面【前面】的唯一理由: 作者封面这个字段全站没人填过, 而
    自动封面是班底站中间的真门面; 作者哪天真填了, 手点一次"重画封面"即可让位。"""
    auto = _auto_cover(s)
    if auto:
        return auto["wide"]
    if s.cover_url:
        return s.cover_url
    import pathlib
    bg = pathlib.Path(__file__).resolve().parents[1] / "static" / "scene" / "bg"
    for l in (s.locations or []):
        lid = (l or {}).get("id")
        if lid and (bg / f"{lid}.jpg").exists():
            # 🖼 走缩略图 (2026-08-05): 卡片槽位只有 430×237, 而这些是 1600×900~
            # 1024×1536 的原图 —— 线上实测大厅一次冷开要下 1,727,144 字节, 按出口
            # 110KB/s 是 16.6 秒。压不出来时 thumb_url 原样返回, 卡面不会空。
            from ..engine.thumbs import thumb_url
            return thumb_url(f"/scene/bg/{lid}.jpg")
    return None


def _ensure_cover(s: StoryModel) -> None:
    """素材变了就把封面重排一遍 (立绘/头像/背景都是后来才陆续画出来的)。
    排版丢后台队列, 绝不卡住调用它的那个请求。"""
    from ..engine import cover as cover_mod
    if not cover_mod.ENABLED:      # 🔌 关着就一张也不排 (书架不再顺手自愈)
        return
    try:
        story = _to_story(s).model_dump()
        if cover_mod.is_stale(story):
            cover_mod.enqueue(story)
    except Exception:
        pass


def _to_card(s: StoryModel, secrets_count: int = 0, *,
             likes: int = 0, plays: int = 0, author: dict | None = None) -> StoryCard:
    sandbox = bool((s.sandbox or {}).get("enabled"))
    ranks = ((s.sandbox or {}).get("progression") or {}).get("ranks") or []
    ladder = " → ".join(str(r) for r in ranks if r) if sandbox else ""
    return StoryCard(
        id=s.id,
        title=s.title,
        cover_url=s.cover_url,
        one_liner=s.one_liner or (s.synopsis[:120] if s.synopsis else None),
        trope_tags=s.trope_tags or [],
        secrets_count=secrets_count,
        endings_count=len(s.endings or []),
        characters_count=len(s.characters or []),
        sandbox=sandbox,
        acts_count=len(s.acts or []),
        progression=ladder[:60] or None,
        art_url=_card_art(s),
        poster_url=(_auto_cover(s) or {}).get("poster"),
        opening_tease=((s.opening or "").strip().splitlines() or [""])[0][:64] or None,
        # 🧩 对齐包B: 卡面的社区数据 (只长在卡上, Story 对象不许长 — 快照红线)
        likes=likes,
        plays=plays,
        author=author,
        mature=bool(s.mature),
        featured=bool(getattr(s, "featured", False)),
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


# 🤝 共享创作库 (Yi 2026-08-02:「让所有账号都可以看见编辑剧本和沙盒」)。
# True = 任何登录用户都能打开并编辑任何一本剧本/沙盒。
#
# 这是 2026-06-19 那次「用户数据隔离」的一处【有意】反转, 不是回退 —— 隔离仍然管着
# 存档、人格、卡库、gal 作品; 放开的只有剧本本体, 因为剧本是要合写的。
# 删除【不在】放开之列: 它连存档带快照一起抹, 不可逆, 仍然只有主人能做。
SHARED_LIBRARY = True


def _own_story(story_id: str, user: User, db: Session) -> StoryModel:
    """能不能编辑这一本。共享库打开时, 谁都能编 (删除除外, 见 _my_story)。"""
    s = db.get(StoryModel, story_id)
    if not s or (s.owner_id != user.id and not SHARED_LIBRARY):
        raise HTTPException(404, "story not found")
    return s


def _my_story(story_id: str, user: User, db: Session) -> StoryModel:
    """只有主人能做的事 (删除)。共享库开着也不放行 —— 删掉是找不回来的。"""
    s = db.get(StoryModel, story_id)
    if not s or s.owner_id != user.id:
        raise HTTPException(404 if not s else 403,
                            "只有这本的作者能删除它" if s else "story not found")
    return s


# ── discover + CRUD ───────────────────────────────────────
@router.get("", response_model=StoryCardPage)
def discover(
    tags: list[str] = Query(default=[]),
    cursor: str | None = None,
    q: str | None = None,
    sort: str = "new",
    featured: bool = False,
    db: Session = Depends(get_db),
):
    """🧩 对齐包B 重构: 先在【轻列】(id/tags/updated_at) 上选完候选, 再按需吃重行。
    tags 是 JSON 列只能进程内筛, 但轻列全表也只是 id+标签, 不再像旧写法那样把
    每本的全部剧本 JSON 都灌进内存 (复审抓的最热端点性能坑, 这版连 tags 路径一起治)。
    sort=hot: 赞×3+游玩数; q: 标题/一句话/简介检索; featured: 运营精选位。"""
    from datetime import datetime as _dt

    from sqlalchemy import func, or_
    base = (db.query(StoryModel.id, StoryModel.trope_tags, StoryModel.updated_at)
            .filter(StoryModel.visibility == "public",
                    StoryModel.status == "published"))
    if featured:
        base = base.filter(StoryModel.featured.is_(True))
    if q and q.strip():
        needle = f"%{q.strip()[:60]}%"
        base = base.filter(or_(StoryModel.title.ilike(needle),
                               StoryModel.one_liner.ilike(needle),
                               StoryModel.synopsis.ilike(needle)))
    cand = base.all()
    if tags:
        cand = [c for c in cand if set(tags) & set(c[1] or [])]
    ids = [c[0] for c in cand]
    from .community import social_counts
    upd = {c[0]: (c[2] or _dt.min) for c in cand}
    # 计数只在需要的范围上算 (复审: 默认 sort=new 时全候选的计数一格都用不上,
    # 而 plays 那次分组扫的是只增不减的 runs 表 —— 最热端点不背这个成本)
    if sort == "hot":
        likes, plays = social_counts(db, ids)
        ids.sort(key=lambda i: (likes.get(i, 0) * 3 + plays.get(i, 0), upd[i]),
                 reverse=True)
        top = ids[:50]
    else:
        ids.sort(key=lambda i: upd[i], reverse=True)
        top = ids[:50]
        likes, plays = social_counts(db, top)
    by_id = ({s.id: s for s in db.query(StoryModel)
              .filter(StoryModel.id.in_(top)).all()} if top else {})
    rows = [by_id[i] for i in top if i in by_id]
    # 🔒 the mystery affordance: how many secrets each story guards (one grouped query)
    counts = dict(db.query(SecretModel.story_id, func.count(SecretModel.id))
                  .filter(SecretModel.story_id.in_([s.id for s in rows] or [""]))
                  .group_by(SecretModel.story_id).all()) if rows else {}
    # 🖋 卡面署名: 作者一次分组取齐 (设计稿卡上的 by @handle)
    from ..models import User as UserModel
    owners = {s.owner_id for s in rows}
    authors = ({u.id: u for u in db.query(UserModel)
                .filter(UserModel.id.in_(owners)).all()} if owners else {})
    # 🎴 书架顺手自愈: 谁的封面缺了/素材换了就排队重画。判缺只是几次 stat, 排版在后台
    for s in rows:
        _ensure_cover(s)

    def _author(s):
        u = authors.get(s.owner_id)
        # avatar 出库消毒: author 是 dict 字段, AssetUrl 验证器管不到 (08-02 家法)
        from ..schemas import _safe_asset_url
        return ({"id": u.id, "name": u.display_name or "玩家",
                 "handle": getattr(u, "handle", None),
                 "avatar_url": _safe_asset_url(u.avatar_url)} if u else None)

    return StoryCardPage(
        items=[_to_card(s, counts.get(s.id, 0), likes=likes.get(s.id, 0),
                        plays=plays.get(s.id, 0), author=_author(s)) for s in rows],
        next_cursor=None)


class CharBlobInput(BaseModel):
    title: Optional[str] = None   # ✍️ draft_engine 用: 作者填了标题就尊重 (AI 不再自作主张)
    text: str = ""
    world: str = ""    # 剧本世界观随行, 解析出的卡贴世界的年代与口吻
    style: str = ""
    # 🌐 演出语言随行: 起草曾写死 "zh", 英文题材起草进编辑器语言就"消失"回中文
    # (Yi 实弹 2026-07-31)。留空 = 按素材文字自动判。
    language: Optional[str] = None


def _guess_lang(text: str) -> str:
    """素材大半是 ASCII 就当英文本子起草。只在作者没明说时兜底。"""
    t = (text or "").strip()
    if not t:
        return "zh"
    ascii_n = sum(1 for ch in t if ord(ch) < 128)
    return "en" if ascii_n / len(t) > 0.6 else "zh"


def _sanitize_cards(out: dict) -> list[dict]:
    cards = []
    for c in (out.get("characters") or [])[:6]:
        if not isinstance(c, dict) or not str(c.get("name") or "").strip():
            continue
        c.pop("id", None)          # id 由编辑器现场铸造
        c["generated"] = False     # 作者亲写的卡: 智能搜图不会乱动它的脸
        # 🗣 唯一没有代码侧硬截的出生点: 啰嗦模型会把整段性格散文塞进 voice_print,
        # 其余出生点都 [:60] — 这里对齐, 免得几百字垃圾入库并回显进 studio 表单
        if c.get("voice_print"):
            c["voice_print"] = str(c["voice_print"]).strip()[:60]
        try:
            cards.append(Character(**c).model_dump(exclude_none=True))
        except Exception:
            # 单张卡的野字段/坏类型不拖累整批 — 丢弃并继续
            continue
    return cards


# 🪄 解析任务台账: 解析要等模型 10~60 秒, 手机网络/webview 会掐长连接
# (实弹: Yi 的 POST 压根没到服务器) — 改成 提交秒回任务号 + 短轮询取结果
_PARSE_JOBS: dict = {}
_PARSE_CAP = 40


@router.post("/parse_characters")
def parse_characters(body: CharBlobInput, user: User = Depends(current_user)):
    """🪄 一大段文字 → 角色卡 (Yi: 制作角色时能直接扔一大段文字自动处理)。
    立即返回 {job}; 客户端轮询 GET /stories/parse_characters/{job} 取结果。
    注意: 本路由必须注册在 /{story_id} 之前, 否则路径被当剧本 id 吞掉。"""
    import threading
    import time as _t
    import uuid as _uuid
    text = (body.text or "").strip()[:6000]
    if len(text) < 8:   # 「一句话加角色」也走这条路, 8 字就够起一张卡
        raise HTTPException(400, "文字太短，至少给一句描述")
    jid = _uuid.uuid4().hex[:12]
    _PARSE_JOBS[jid] = {"status": "working", "at": _t.time(), "uid": user.id}
    while len(_PARSE_JOBS) > _PARSE_CAP:   # 台账限容: 最老的先走
        _PARSE_JOBS.pop(next(iter(_PARSE_JOBS)), None)
    world, style = (body.world or "")[:400], (body.style or "")[:160]
    lang = (body.language or "").strip() or _guess_lang(text)

    def _work():
        from ..engine.llm import get_llm
        try:
            out = get_llm().generate({"char_from_text": True, "text": text,
                                      "world": world, "style": style,
                                      "language": lang}) or {}
        except Exception:
            out = {}
        cards = _sanitize_cards(out)
        job = _PARSE_JOBS.get(jid)
        if job is not None:
            if cards:
                job.update({"status": "done", "characters": cards})
            else:
                job.update({"status": "error",
                            "error": "没解析出角色，换一段更具体的文字试试"})

    threading.Thread(target=_work, daemon=True).start()
    return {"job": jid}


@router.get("/parse_characters/{job_id}")
def parse_characters_result(job_id: str, user: User = Depends(current_user)):
    job = _PARSE_JOBS.get(job_id)
    if not job or job.get("uid") != user.id:
        raise HTTPException(404, "任务不存在或已过期")
    if job.get("status") == "working":
        return {"status": "working"}
    if job.get("status") == "error":
        return {"status": "error", "error": job.get("error")}
    return {"status": "done", "characters": job.get("characters") or []}


# ── ✍️ 引擎本起草 (创作 UX 首期 A): 想法/全文 → AI 起草引擎本 draft → 工坊精修 ──
# 铁律 (Yi 2026-07-18 拍板): ①门控只起草 act_min 单维 ②生成→lint→确定性降级闭环,
# 落地草稿必须「打得通但保守」 ③与 studio 共用 StoryInput/SecretInput 同一套 schema
# (本路由不维护私有输出格式) ④ai_draft 埋点给质量分层留抓手。
def _degrade_draft(content: dict, issues: list) -> None:
    """确定性降级 (不过 LLM): 修不好的门控一律降保守 — gate_deadlock 的碎片
    act_min 归 1; 悬空引用就地拆除。原地修改 content。"""
    story = content.get("story") or {}
    frags = {f.get("id"): f for sec in content.get("secrets") or []
             for f in sec.get("fragments") or []}
    for i in issues:
        code, where = str(i.get("code")), str(i.get("where") or "")
        if code == "gate_deadlock":
            for f in frags.values():   # 保守到底: 所有碎片解锁降为第一幕
                (f.setdefault("unlock", {}))["act_min"] = 1
        elif code in ("dangling_frag", "dangling_event"):
            for a in story.get("acts") or []:
                adv = a.get("advance") or {}
                adv["required_fragment_ids"] = [x for x in adv.get("required_fragment_ids") or []
                                                if x in frags]
                adv["required_event_ids"] = []
            for e in story.get("endings") or []:
                cond = e.get("condition") or {}
                cond["required_fragment_ids"] = [x for x in cond.get("required_fragment_ids") or []
                                                 if x in frags]
        elif code == "dangling_exit":
            names = {l.get("name") for l in story.get("locations") or []}
            for l in story.get("locations") or []:
                l["exits"] = [x for x in l.get("exits") or [] if x in names]
        elif code == "frag_bad_event":
            for f in frags.values():
                (f.get("unlock") or {}).pop("trigger_event_ids", None)


def _strip_all_gates(content: dict) -> None:
    """最终保底: 全部门控拆除 — 宁可平铺直叙, 不许一个死锁上架。"""
    for sec in content.get("secrets") or []:
        for f in sec.get("fragments") or []:
            f["unlock"] = {"act_min": 1}
    for a in (content.get("story") or {}).get("acts") or []:
        a["advance"] = {"required_fragment_ids": [], "required_event_ids": [],
                        "affinity_min": 0}


@router.post("/draft_engine")
def draft_engine(body: CharBlobInput, user: User = Depends(current_user)):
    """✍️ AI 起草引擎本: 立即返回 {job}; 轮询 GET /stories/draft_engine/{job}。
    完成后返回 story_id, 客户端跳 /studio?story=id 精修。"""
    import threading
    import time as _t
    import uuid as _uuid
    text = (body.text or "").strip()[:5000]
    if len(text) < 10:
        raise HTTPException(400, "多给一点素材：一个想法的几句话，或整段原文")
    jid = _uuid.uuid4().hex[:12]
    _PARSE_JOBS[jid] = {"status": "working", "at": _t.time(), "uid": user.id}
    while len(_PARSE_JOBS) > _PARSE_CAP:
        _PARSE_JOBS.pop(next(iter(_PARSE_JOBS)), None)
    uid = user.id
    utitle = (body.title or "").strip()[:24]   # 作者填了标题就尊重
    lang = (body.language or "").strip() or _guess_lang(text)

    def _work():
        import json as _json

        from ..db import SessionLocal
        from ..engine import logic as logic_mod
        from ..engine.llm import get_llm
        job = _PARSE_JOBS.get(jid)
        try:
            llm = get_llm()
            sk = llm.generate({"engine_skeleton": True, "text": text,
                               "language": lang}) or {}
            if not (sk.get("title") and sk.get("acts")):
                raise ValueError("骨架没起出来，换一段更具体的素材试试")
            cards = _sanitize_cards(llm.generate({"char_from_text": True, "text": text,
                                                  "world": sk.get("world_long") or "",
                                                  "language": lang}) or {})
            # id 铸造 (服务端确定性), 名字→id 映射供秘密归属
            chars = []
            for i, c in enumerate(cards[:5]):
                chars.append({**c, "id": f"ch_{i+1}", "playable": False,
                              "schedule": [], "ties": [], "items": c.get("items") or [],
                              "bio_layers": c.get("bio_layers") or []})
            by_name = {str(c.get("name") or ""): c["id"] for c in chars}
            acts = [{"index": i + 1, "title": str(a.get("title") or f"第{i+1}幕")[:16],
                     "goal": str(a.get("goal") or "")[:60],
                     "events": [], "advance": {"required_fragment_ids": [],
                                               "required_event_ids": [], "affinity_min": 0}}
                    for i, a in enumerate((sk.get("acts") or [])[:4])]
            locs = [{"id": f"loc_{i+1}", "name": str(l.get("name") or f"地点{i+1}")[:12],
                     "detail": str(l.get("detail") or "")[:80],
                     "exits": [str(x) for x in (l.get("exits") or [])],
                     "unlock": {"act_min": 0, "affinity_min": 0, "required_fragment_ids": []},
                     "props": []}
                    for i, l in enumerate((sk.get("locations") or [])[:4])]
            sec_out = llm.generate({"engine_secrets": True,
                                    "synopsis": sk.get("synopsis") or "",
                                    "characters": chars,
                                    "acts": [a["title"] for a in acts],
                                    "language": lang}) or {}
            n_acts = max(1, len(acts))
            secrets, fi = [], 0
            for si, s in enumerate((sec_out.get("secrets") or [])[:3]):
                owner = by_name.get(str(s.get("character_name") or "")) \
                    or (chars[0]["id"] if chars else None)
                if not owner:
                    continue
                frags = []
                for f in (s.get("fragments") or [])[:2]:
                    fi += 1
                    try:   # ⚖️ act_min 夹逼进合法幕数 (Mock 埋了越界靶子)
                        amin = max(1, min(n_acts, int(f.get("act_min", 1))))
                    except (TypeError, ValueError):
                        amin = 1
                    frags.append({"id": f"frag_d{fi}", "layer": int(f.get("layer", 1) or 1),
                                  "content": str(f.get("content") or "")[:160],
                                  "cover": str(f.get("cover") or "")[:80],
                                  "retrieval_key": str(f.get("retrieval_key") or "")[:20],
                                  "known_by_character_ids": [owner],
                                  "unlock": {"act_min": amin}})
                if frags:
                    secrets.append({"id": f"sec_d{si+1}", "character_id": owner,
                                    "title": str(s.get("title") or "秘密")[:20],
                                    "sensitivity": "medium", "fragments": frags})
            # 最后一层碎片作为末幕推进与结局条件 (act_min 单维世界里的最保守连线)
            last_fids = [s["fragments"][-1]["id"] for s in secrets][:1]
            if last_fids and len(acts) >= 2:
                acts[-1]["advance"]["required_fragment_ids"] = []
                acts[-2]["advance"]["required_fragment_ids"] = last_fids
            endings = []
            for ei, e in enumerate((sec_out.get("endings") or [])[:2]):
                endings.append({"id": f"end_d{ei+1}",
                                # schema 枚举是 true/normal/bad/death — good 映射为 true
                                "kind": "bad" if str(e.get("kind")) == "bad" else "true",
                                "title": str(e.get("title") or "结局")[:12],
                                "trigger": "condition",
                                "text": str(e.get("text") or "")[:300],
                                "condition": {"affinity_min": 0, "act_min": n_acts,
                                              "required_fragment_ids": last_fids,
                                              "required_flags": {}}})
            payload = {
                "title": utitle or str(sk.get("title") or "未命名草稿")[:24],
                "language": lang, "visibility": "private",
                "one_liner": str(sk.get("one_liner") or "")[:40],
                "synopsis": str(sk.get("synopsis") or "")[:400],
                "world_long": str(sk.get("world_long") or "")[:600],
                "world_facts": str(sk.get("world_facts") or "")[:200],
                "trope_tags": [str(t)[:8] for t in (sk.get("trope_tags") or [])[:4]],
                "characters": chars, "acts": acts, "locations": locs,
                "endings": endings,
                "tuning": {"_origin": "ai_draft"},
            }
            # ③ 共用 schema: 起草物必须过 StoryInput/SecretInput 这两道门 —
            # maker 无私有格式 (实弹: sensitivity 写成数字曾绕过枚举直落库)
            data = StoryInput(**payload)
            secrets = [{**SecretInput(**{k: v for k, v in s.items() if k != "id"}).model_dump(),
                        "id": s.get("id")} for s in secrets]
            content = {"story": data.model_dump(), "secrets": secrets}
            # ② 生成→lint→确定性降级 (≤2 轮), 再不干净就拆光门控保底
            for _round in range(2):
                errs = [i for i in logic_mod.lint_story(content)
                        if i.get("severity") == "error"]
                if not errs:
                    break
                _degrade_draft(content, errs)
            if [i for i in logic_mod.lint_story(content) if i.get("severity") == "error"]:
                _strip_all_gates(content)
            # 落库: 与 create_story 同构 (owner + JSON 块), 秘密走 SecretModel
            db = SessionLocal()
            try:
                st = content["story"]
                st["tuning"]["_draft_size"] = len(_json.dumps(content, ensure_ascii=False))
                row = StoryModel(
                    owner_id=uid,
                    title=st["title"], language=st.get("language") or "zh",
                    one_liner=st.get("one_liner"), synopsis=st.get("synopsis"),
                    world_long=st.get("world_long"), world_facts=st.get("world_facts"),
                    trope_tags=st.get("trope_tags") or [],
                    visibility="private",
                    characters=st.get("characters") or [],
                    acts=st.get("acts") or [], endings=st.get("endings") or [],
                    locations=st.get("locations") or [], tuning=st.get("tuning") or {},
                )
                db.add(row)
                db.flush()
                for s in content["secrets"]:
                    sec = SecretModel(story_id=row.id, character_id=s["character_id"],
                                      title=s["title"], sensitivity=s.get("sensitivity", 2))
                    sec.fragments = [FragmentModel(
                        id=f["id"], layer=f["layer"], content=f["content"],
                        retrieval_key=f.get("retrieval_key") or "",
                        known_by_character_ids=f.get("known_by_character_ids") or [],
                        unlock=f.get("unlock") or {}, cover=f.get("cover") or "")
                        for f in s["fragments"]]
                    db.add(sec)
                db.commit()
                sid = row.id
            finally:
                db.close()
            if job is not None:
                job.update({"status": "done", "story_id": sid})
        except Exception as e:
            if job is not None:
                job.update({"status": "error", "error": str(e)[:120] or "起草失败"})

    threading.Thread(target=_work, daemon=True).start()
    return {"job": jid}


@router.get("/draft_engine/{job_id}")
def draft_engine_result(job_id: str, user: User = Depends(current_user)):
    job = _PARSE_JOBS.get(job_id)
    if not job or job.get("uid") != user.id:
        raise HTTPException(404, "任务不存在或已过期")
    if job.get("status") == "working":
        return {"status": "working"}
    if job.get("status") == "error":
        return {"status": "error", "error": job.get("error")}
    return {"status": "done", "story_id": job.get("story_id")}


@router.post("", status_code=201, response_model=Story)
def create_story(
    body: StoryInput, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    data = body.model_dump(exclude_unset=True)
    data.pop("if_rev", None)   # 乐观锁字段, 不是 Story 列 (新建无需比对; 漏 pop 会 **data 崩)
    data.pop("characters", None)
    data.pop("acts", None)
    data.pop("endings", None)
    data.pop("locations", None)
    data.pop("tuning", None)
    data.pop("pressure", None)
    data.pop("threat", None)
    data.pop("dooms", None)
    data.pop("sanity", None)
    data.pop("rules", None)
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
        threat=body.threat,
        dooms=body.dooms,
        sanity=body.sanity,
        rules=body.rules,
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
                     "presence", "appears_from_act", "relation_default",
                     "voice")   # 🎙 配音选角是演出层不是剧透 (实弹: 白名单漏了它, 玩家全程无声)


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
    # 🗺 locations carry the answer key too: unlock.required_fragment_ids is the
    # walkthrough map, props.fragment_id/event_id are the evidence keys, and a locked
    # place's very NAME is a spoiler (map_view ships a count, not names). The play UI
    # reads map data exclusively from /runs/{id}/map — it never touches story.locations.
    out.locations = []
    out.threat = None  # 🦇 the hunter's rules are the answer key of a horror story
    out.dooms = None   # 🚪 who gets taken, when, and how to stop it — never leaks
    out.sanity = None  # 🧠 the break threshold is mechanics, not lore
    # 📜 rules are DIEGETIC (posted on the wall) — the text shows, the teeth don't
    out.rules = [{"id": r.get("id"), "text": r.get("text")}
                 for r in (out.rules or [])] or None
    return out


@router.get("/{story_id}", response_model=Story)
def get_story(
    story_id: str,
    edit: bool = False,
    db: Session = Depends(get_db),
    lp_session: str | None = Cookie(default=None),
):
    """一条路由两种读法, 靠 ?edit=1 分开 —— 这一格错了就是剧透事故。

    · 不带 edit (播放页 chooseRole 走的就是这条): 非作者一律吃剧透盾, 结局、答案、
      幕内事件、角色小传全抹掉。
    · 带 edit=1 (只有工坊会带): 给全量。共享创作库开着时, 任何登录用户都算作者。

    ⚠️ 曾经想省事: 把"登录用户"直接当作者。结果是【每个玩家一打开剧本就看到结局和
    答案】—— tests/test_sweep 当场红。开放编辑与开放剧透是同一件事的两面, 所以只在
    明确要编辑时才掀盖子。
    """
    s = db.get(StoryModel, story_id)
    if not s:
        raise HTTPException(404, "story not found")
    viewer_id = read_session_token(lp_session) if lp_session else None
    is_owner = bool(viewer_id) and viewer_id == s.owner_id
    may_edit = is_owner or (bool(viewer_id) and SHARED_LIBRARY)
    # 主人照旧【无条件】拿全量 (老契约不动); 合写者要全量必须明确说 ?edit=1
    as_author = is_owner or (may_edit and edit)
    # 草稿只有能编辑的人看得见 (它还没上架, 对玩家而言不存在)
    if s.visibility != "public" or s.status != "published":
        if not may_edit:
            raise HTTPException(404, "story not found")
    out = _to_story(s)
    if not as_author:
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
    # 🔒 乐观锁: 客户端载入时的 updated_at 与库里不一致 = 别处已改过 — 拒绝整本覆盖
    if body.if_rev is not None and str(s.updated_at or "") != str(body.if_rev):
        raise HTTPException(409, "这本剧本在别的窗口或设备被改过——先刷新页面拿最新版再改；"
                                 "直接保存会把那边的改动埋掉。")
    data = body.model_dump(exclude_unset=True)
    data.pop("if_rev", None)
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
    if "threat" in data:
        s.threat = data.pop("threat")
    if "dooms" in data:
        s.dooms = data.pop("dooms")
    if "sanity" in data:
        s.sanity = data.pop("sanity")
    if "rules" in data:
        s.rules = data.pop("rules")
    if "clock" in data:
        s.clock = data.pop("clock")
    if "phone" in data:
        s.phone = data.pop("phone")
    if "verdict" in data:
        s.verdict = data.pop("verdict")
    if "creatures" in data:
        s.creatures = data.pop("creatures") or []
    if "factions" in data:
        s.factions = data.pop("factions") or []
    if "opening" in data:
        s.opening = data.pop("opening") or None
    for k, v in data.items():
        setattr(s, k, v)
    db.commit()
    return _to_story(s)


@router.delete("/{story_id}", status_code=204)
def delete_story(story_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    # 🔒 共享库放开的是【编辑】, 不是删除 —— 删掉连存档带快照一起没, 找不回来
    s = _my_story(story_id, user, db)
    db.delete(s)
    db.commit()


@router.post("/{story_id}/publish", response_model=PublishResult)
def publish(story_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    s = _own_story(story_id, user, db)
    snapshot_content = {
        "story": _to_story(s).model_dump(),
        "secrets": [_to_secret(sec).model_dump() for sec in s.secrets],
    }
    # ✍️ lint 硬门 (创作 UX 首期, 与 AI 起草绑定的安全包): 错误清零才许发布 —
    # 坏本 (死锁/悬空引用) 不再能一键上架。warn 不拦; 文案人话化 (手写模板)。
    from ..engine import logic as logic_mod
    _errs = [i for i in logic_mod.lint_story(snapshot_content)
             if i.get("severity") == "error"]
    if _errs:
        raise HTTPException(422, {
            "lint_errors": [logic_mod.humanize_issue(i) for i in _errs[:8]],
            "count": len(_errs)})
    # ✍️ 质量信号 (与 A 同期埋, Yi 定): AI 起草本的人工编辑痕迹 = 草稿与发布版的
    # 体量差 — 「起草即发布」的同质本 _edit_ratio≈0, 给公共库推荐排序留抓手
    _tun = dict(s.tuning or {})
    if _tun.get("_origin") == "ai_draft" and _tun.get("_draft_size"):
        import json as _json
        _now = len(_json.dumps(snapshot_content, ensure_ascii=False))
        _tun["_edit_ratio"] = round(
            abs(_now - int(_tun["_draft_size"])) / max(1, int(_tun["_draft_size"])), 3)
        s.tuning = _tun
        flag_modified(s, "tuning")
    new_version = s.version + 1
    snapshot_content["story"]["version"] = new_version
    db.add(
        StorySnapshot(story_id=s.id, version=new_version, content=snapshot_content)
    )
    s.version = new_version
    s.status = "published"
    db.commit()
    # 🎴 上架即有脸 (Yi 2026-08-01: 玩家自己做的剧本也要自动出封面)。
    # 此刻多半还没有立绘 —— 先出一张只有底子和版式的, 等美术陆续落地, 书架会自己重排。
    _ensure_cover(s)
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


@router.get("/bgm/list")
def bgm_list():
    """🎵 配乐面板的两张表: 十一种情绪 + 曲库里真的存在的曲子。
    注意: 本路由是两段路径, 与 /{story_id} 不冲突; 但必须在 /{story_id}/xxx 之前注册。"""
    from ..engine import director
    return {"cues": director.cue_menu(), "moods": director.mood_menu(),
            "tracks": director.list_bgm()}


@router.get("/sfx/list")
def sfx_list():
    """🔊 音效面板的两张表: 库里【真的存在】的音效文件 + 内置自动词表。

    问磁盘, 不问表 —— 手写一份清单迟早和 /scene/sfx 里的东西对不上, 作者点了名
    却没有文件, 玩家那边就是一片静默 (BGM 的 variants 已经栽过这一跤)。"""
    import pathlib as _pl

    from ..engine.scene import _SFX
    d = _pl.Path(__file__).resolve().parents[1] / "static" / "scene" / "sfx"
    have = sorted(p.stem for p in d.glob("*.mp3")) if d.is_dir() else []
    kw: dict[str, list[str]] = {}
    for k, name in _SFX:
        kw.setdefault(name, []).append(k)
    return {"sfx": [{"name": n, "label": SFX_LABEL.get(n, n), "keywords": kw.get(n, [])}
                    for n in have]}


@router.get("/voice/list")
def voice_list():
    """🎙 预置音色表 (角色卡的选角下拉)。

    只列【语气音精灵排齐了的】音色 —— 精灵是角色开口那一下的「嗯 / 哼 / 诶?!」,
    它才是配音的常态; 逐句台词是玩家点播放键才合成的锦上添花。精灵没排齐就选,
    玩家听到的是一片静默。同样问磁盘不问表。"""
    import pathlib as _pl

    from ..engine.voice import SPRITES
    d = _pl.Path(__file__).resolve().parents[1] / "static" / "scene" / "voice"
    need = sum(len(v) for v in SPRITES["zh"].values())   # 5 类 × 2 段
    out = []
    for vid, meta in VOICE_CAST.items():
        n = len(list((d / vid).glob("*.mp3"))) if (d / vid).is_dir() else 0
        if n >= need:
            out.append({"id": vid, **meta})
    return {"voices": out, "speeds": [0.85, 0.92, 1.0, 1.06, 1.15]}


# 预置音色的人话名。
#
# ⚠️ label 写的是【这个音色本身】什么味道, 抄自阿里官方音色表; like 写的是我们哪个
# 角色用过它。第一版把两者混了 —— 拿 patch_voice.py 的注释当音色描述, 结果
# 「冷而利落」其实是王九这个人、「沧桑」其实是龙卷风压到 0.9 的效果, 音色本身是
# 「欢脱粤语」。作者照着选就会选歪。改标签前先回官方表核, 别照角色写。
# 加新音色: gen_voice.py 加一行 → 跑一次排精灵 → 补这里 (守卫测试盯着两边不许分家)。
VOICE_CAST: dict[str, dict] = {
    # 中文男
    "longtian_v3":     {"label": "磁性理智 · 男", "lang": "zh", "like": "蓝信一"},
    "longfei_v3":      {"label": "热血磁性 · 男", "lang": "zh", "like": "十二少"},
    "longcheng_v3":    {"label": "智慧青年 · 男", "lang": "zh", "like": "王九"},
    "longanzhi_v3":    {"label": "睿智轻熟 · 男", "lang": "zh", "like": "大老板"},
    "longyingxun_v3":  {"label": "年轻青涩 · 男", "lang": "zh", "like": "陈洛军"},
    "longze_v3":       {"label": "温暖元气 · 男", "lang": "zh", "like": "Tiger哥"},
    "longanyang":      {"label": "阳光大男孩 · 男", "lang": "zh", "like": "狄秋"},
    "longjielidou_v3": {"label": "阳光顽皮 · 男（童声路子）", "lang": "zh", "like": "四仔"},
    "longshu_v3":      {"label": "沉稳青年 · 男", "lang": "zh"},
    "longshuo_v3":     {"label": "博才干练 · 男", "lang": "zh"},
    "longlaotie_v3":   {"label": "东北直率 · 男（方言音色，古装慎用）", "lang": "zh"},
    # 中文女
    "longwan_v3":      {"label": "细腻柔声 · 女", "lang": "zh"},
    "longxiaochun_v3": {"label": "知性积极 · 女", "lang": "zh"},
    "longxiaoxia_v3":  {"label": "沉稳权威 · 女", "lang": "zh"},
    "longmiao_v3":     {"label": "抑扬顿挫 · 女", "lang": "zh"},
    "longyue_v3":      {"label": "温暖磁性 · 女", "lang": "zh"},
    "longyuan_v3":     {"label": "温暖治愈 · 女", "lang": "zh"},
    "longhua_v3":      {"label": "元气甜美 · 女", "lang": "zh"},
    # 粤语 (仍然只有一男一女 — 粤语本子的硬限制照旧)
    "longanyue_v3":    {"label": "欢脱 · 粤语男", "lang": "yue", "like": "龙卷风（压到0.9出沧桑）"},
    "longjiayi_v3":    {"label": "知性 · 粤语女", "lang": "yue", "like": "蔡妍"},
    # 英文
    "loongeric_v3":    {"label": "UK male", "lang": "en", "like": "Elias"},
    "loongluca_v3":    {"label": "UK male · plain", "lang": "en", "like": "Marek"},
    "loongdavid_v3":   {"label": "US male", "lang": "en", "like": "Rafael"},
    "loongandy_v3":    {"label": "US male · bright", "lang": "en", "like": "Niko"},
    "longanlang_v3":   {"label": "EN male · slight accent", "lang": "en", "like": "Ilya"},
}


# 内置音效的人话名 — 作者在下拉里读的是这个, 不是 creak / laser
SFX_LABEL = {
    "knock": "敲门", "door": "开关门", "footsteps": "脚步", "rain": "下雨",
    "wind": "风声", "buzz": "手机震动", "thunder": "打雷", "waves": "海浪",
    "heartbeat": "心跳", "ringtone": "电话铃", "draw": "拔刀出鞘", "sword": "挥剑破空",
    "clash": "金铁交击", "coin": "钱币", "glass": "玻璃碎裂", "punch": "拳脚落肉",
    "explosion": "爆炸", "laser": "枪响 / 能量束", "magic": "施法", "bell": "钟声",
    "book": "翻书", "creak": "吱呀 (门轴 / 木板)",
}


@router.get("/{story_id}/cover")
def get_cover(story_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """🎴 这本的封面现在长什么样 + 还差什么 (工坊用)。"""
    from ..engine import cover as cover_mod
    s = _own_story(story_id, user, db)
    if not cover_mod.ENABLED:
        return {"enabled": False, "poster": None, "wide": None, "cast": [], "with_art": []}
    story = _to_story(s).model_dump()
    cast = cover_mod._cast_ids(story)[:cover_mod.MAX_CAST]
    have = [cid for cid in cast if cover_mod.figure_ready(cid)]
    return {"enabled": True, **(cover_mod.urls(s.id) or {"poster": None, "wide": None}),
            "cast": cast, "with_art": have, "stale": cover_mod.is_stale(story),
            "background": bool(cover_mod._pick_bg(story))}


@router.post("/{story_id}/cover")
def make_cover(story_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """🎴 重画封面 (作者主动): 拿这本自己的立绘/头像/背景现排, 秒级, 不花生图钱。"""
    from ..engine import cover as cover_mod
    s = _own_story(story_id, user, db)
    if not cover_mod.ENABLED:
        return {"queued": False, "enabled": False}
    cover_mod.enqueue(_to_story(s).model_dump(), force=True)
    return {"queued": True}


@router.post("/{story_id}/gen_avatar/{cid}")
def gen_avatar(story_id: str, cid: str,
               user: User = Depends(current_user), db: Session = Depends(get_db)):
    """🎨 工坊里给角色画头像 (创作 UX: 角色卡要有照片): 与运行时补脸同一管线 —
    同 char_seed 同画风, 以后游戏里生成的立绘/自拍不会换脸。排队后台画, 约十几秒。"""
    s = _own_story(story_id, user, db)
    c = next((x for x in (s.characters or []) if x.get("id") == cid), None)
    if not c:
        raise HTTPException(404, "这个剧本里没有该角色")
    from .runs import _AV_DIR, _char_seed, _enqueue_image, _story_art
    content = {"story": _to_story(s).model_dump()}
    art, neg = _story_art(content)
    world = ((s.world_long or "").strip().replace("\n", " "))[:120]
    bits = "，".join(b for b in (c.get("name"), c.get("role") or "",
                                 (c.get("persona_text") or "")[:160]) if b)
    prompt = (f"{art}。人物肖像，胸像特写，正面微侧，目光看向镜头外，"
              f"柔和的侧光，背景虚化，情绪克制内敛：{bits}。世界背景：{world}")
    path = _AV_DIR / f"{cid}.jpg"
    if path.exists():
        path.unlink()   # 作者主动重画 — 旧脸让位
    _enqueue_image(prompt, path, "768*768", negative=neg,
                   seed=_char_seed(content, cid))
    chars = list(s.characters or [])
    for x in chars:
        if x.get("id") == cid:
            x["avatar_url"] = f"/scene/avatar/{cid}.jpg"
    s.characters = chars
    flag_modified(s, "characters")
    db.commit()
    return {"queued": True, "url": f"/scene/avatar/{cid}.jpg"}


def _studio_bg_seed(content: dict) -> int:
    """工坊画背景用的种 —— 直接借运行时那一颗, 不许自己再算一版。
    作者在工坊看到的图必须就是玩家在游戏里看到的图 (两条管线两颗种 = 作者调好的
    图一进游戏就换了样, 正是 char_seed 当年踩过的坑)。"""
    from .runs import _bg_seed
    return _bg_seed(content)


@router.post("/{story_id}/gen_bg/{loc_id}")
def gen_bg(story_id: str, loc_id: str,
           user: User = Depends(current_user), db: Session = Depends(get_db)):
    """🎨 工坊里给地点画背景 (创作 UX: 地点也要有脸): 与运行时补图同一管线同画风 —
    游戏里这个地点就用这张图。排队后台画, 约十几秒。"""
    s = _own_story(story_id, user, db)
    from ..engine.gal import safe_asset_key
    try:
        loc_id = safe_asset_key(loc_id)
    except ValueError:
        raise HTTPException(400, "非法的地点 id")
    loc = next((l for l in (s.locations or []) if l.get("id") == loc_id), None)
    if not loc:
        raise HTTPException(404, "这个剧本里没有该地点")
    from .runs import _BG_DIR, _bg_negative, _bg_prompt, _enqueue_image
    content = {"story": _to_story(s).model_dump()}
    path = _BG_DIR / f"{loc_id}.jpg"
    # 🎲 头一次画用这本剧本的种 (与游戏里自动补的那张一模一样 —— 作者看到什么,
    # 玩家就看到什么); 再点一次是"我不满意, 换一张", 在同族里位移一格。
    redraw = path.exists()
    if redraw:
        path.unlink()   # 作者主动重画 — 旧图让位
    import time as _time
    seed = _studio_bg_seed(content) + (int(_time.time()) % 991 + 1 if redraw else 0)
    _enqueue_image(_bg_prompt(content, loc), path, "1280*720",
                   negative=_bg_negative(content), seed=seed)
    return {"queued": True, "url": f"/scene/bg/{loc_id}.jpg"}


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
    if kind not in ("avatar", "bg", "sprite"):
        raise HTTPException(400, "kind 只能是 avatar / bg / sprite")
    # 🔒 P0 路径穿越: target_id 是作者可控的角色/地点 id, 未消毒会拼出 ../ 覆盖他人的图
    from ..engine.gal import safe_asset_key
    try:
        target_id = safe_asset_key(target_id)
    except ValueError:
        raise HTTPException(400, "非法的 target_id")
    data = await file.read()
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(413, "图片太大（上限 5MB）")
    if not _sniff_image(data):
        raise HTTPException(415, "只支持 JPG / PNG / WebP 图片")
    if kind in ("avatar", "sprite"):
        chars = list(s.characters or [])
        c = next((x for x in chars if x.get("id") == target_id), None)
        if not c:
            raise HTTPException(404, "这个剧本里没有该角色")
    else:
        if not any((l.get("id") == target_id) for l in (s.locations or [])):
            raise HTTPException(404, "这个剧本里没有该地点")
    if kind == "sprite":
        # 🎭 作者上传立绘 (Yi: 建剧本时可以上传立绘): 走玩家上传同一条 ingest 三件套 —
        # 透底立绘 + 改脸源图 + 方形头像一次全得, 原图留档以后换画风不糊脸
        from ..engine.sprites import ingest_upload
        out = ingest_upload(target_id, data, keep_photo=data)
        url = out["avatar"]
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
        return {"url": out["sprite"], "avatar": out["avatar"]}
    # the play UI loads bg by the fixed `{id}.jpg` convention → always save as .jpg;
    # shrink_jpg also converts real PNG/WebP bytes into true JPEG at web weight
    from ..engine.gal import shrink_jpg
    path = _media_dir(kind) / f"{target_id}.jpg"
    path.write_bytes(shrink_jpg(data, quality=82, max_side=1600 if kind == "bg" else 1024))
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


# 🎙 声音克隆 (Yi: 编辑剧本一定要能自己上传声音) ────────────────────────────
def _sniff_audio(data: bytes) -> str | None:
    """magic bytes → 扩展名; 认不出就拒 (声音样本只收 wav/mp3/m4a)."""
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "wav"
    if data[:3] == b"ID3" or (len(data) > 1 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0):
        return "mp3"
    if data[4:8] == b"ftyp":
        return "m4a"
    return None


_VOICE_PREVIEW = {"zh": "你来啦。我还以为要再等一会儿呢。",
                  "en": "There you are. I was starting to wonder."}


def _story_lang(s: StoryModel) -> str:
    return "en" if str(s.language or "zh").lower().startswith("en") else "zh"


@router.post("/{story_id}/voice_clone")
async def voice_clone(
    story_id: str,
    target_id: str = Form(...),
    file: UploadFile = File(...),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Author uploads a voice sample (10~30s 清晰人声) → CosyVoice 克隆专属声线。
    成功即写进角色卡与最新快照 (配音是演出层, 在途 run 立刻换声);
    语气音精灵后台自动生成; 返回 preview_url 供编辑器当场试听。"""
    import asyncio
    import threading

    s = _own_story(story_id, user, db)
    from ..engine.gal import safe_asset_key
    try:
        target_id = safe_asset_key(target_id)
    except ValueError:
        raise HTTPException(400, "非法的 target_id")
    chars = list(s.characters or [])
    c = next((x for x in chars if x.get("id") == target_id), None)
    if not c:
        raise HTTPException(404, "这个剧本里没有该角色")
    data = await file.read()
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(413, "音频太大（上限 10MB，10~30 秒足够）")
    ext = _sniff_audio(data)
    if not ext:
        raise HTTPException(415, "只支持 WAV / MP3 / M4A 音频")
    from ..engine import voice as voice_engine
    try:
        voice_id = await asyncio.to_thread(voice_engine.enroll, data, ext)
    except voice_engine.TTSError as e:
        raise HTTPException(502, f"克隆失败: {e}")
    v = {"id": voice_id, "speed": 1.0, "model": voice_engine.CLONE_MODEL, "cloned": True}
    c["voice"] = v
    s.characters = chars
    flag_modified(s, "characters")
    snap = (db.query(StorySnapshot).filter(StorySnapshot.story_id == s.id)
            .order_by(StorySnapshot.version.desc()).first())
    if snap and (snap.content or {}).get("story"):
        for sc in snap.content["story"].get("characters", []):
            if sc.get("id") == target_id:
                sc["voice"] = dict(v)
        flag_modified(snap, "content")
    db.commit()
    lang = _story_lang(s)
    # 语气音精灵后台补齐 (十几秒); 缺的期间客户端静默降级, 不挡返回
    threading.Thread(target=voice_engine.gen_sprites_for,
                     args=(voice_id, lang, voice_engine.CLONE_MODEL), daemon=True).start()
    preview_url = None
    try:
        preview_url = await voice_engine.tts_line_cached(
            _VOICE_PREVIEW[lang], voice_id, 1.0, model=voice_engine.CLONE_MODEL)
    except voice_engine.TTSError:
        pass   # 试听失败不吞掉克隆成果
    return {"voice": v, "preview_url": preview_url}


@router.post("/{story_id}/voice_preview")
async def voice_preview(
    story_id: str,
    target_id: str = Form(...),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """编辑器试听: 用该角色当前音色 (克隆或预置) 合成一句固定台词, 缓存复用."""
    s = _own_story(story_id, user, db)
    c = next((x for x in (s.characters or []) if x.get("id") == target_id), None)
    if not c:
        raise HTTPException(404, "这个剧本里没有该角色")
    v = c.get("voice") or {}
    if not v.get("id"):
        raise HTTPException(404, "这个角色还没有配音")
    from ..engine import voice as voice_engine
    try:
        url = await voice_engine.tts_line_cached(
            _VOICE_PREVIEW[_story_lang(s)], str(v["id"]),
            float(v.get("speed") or 1.0),
            model=str(v["model"]) if v.get("model") else None)
    except voice_engine.TTSError as e:
        raise HTTPException(502, f"试听失败: {e}")
    return {"url": url}
