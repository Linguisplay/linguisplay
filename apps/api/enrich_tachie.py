# -*- coding: utf-8 -*-
"""Generate VN standing sprites (立绘三件套 + 表情差分) for a story's ORIGINAL cast.

smart_cast covers characters with real-photo sources (movie IP leads). Original
characters have no photo to convert, so they are BORN in the story's art bible via
t2i — style-first prompt, per-(story,cid) fixed seed (same face on every rerun),
neighboring-style negatives — then run through the standard pipeline:
ingest_upload (透底立绘 + 改脸源图 + 方形头像) → build_expr_pack (微表情差分).

Appearance lives HERE (script-local LOOKS), not in the story schema: the schema
has no looks field and play never needs it — only generation does.

Idempotent: skips a character whose sprite file already exists (--force regenerates,
except HARD_SKIP: cids shared with another story's finished art, e.g. cyclone).
Extra args after the title narrow the run to those cids (targeted redo):
    enrich_tachie.py "九龙城寨·浮生" kf_achoi --force

Run ON THE SERVER (needs DASHSCOPE_API_KEY in .env):
    cd /opt/linguisplay/apps/api && set -a && . .env && set +a && \
        ./.venv/bin/python enrich_tachie.py "九龙城寨·浮生"
"""
import os
import sys

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./dev.db")
os.environ.setdefault("JWT_SECRET", "dev")

from sqlalchemy.orm.attributes import flag_modified  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.engine.gal import FIGURE_MODEL, char_seed, portrait_negative  # noqa: E402
from app.engine.qwen import generate_image  # noqa: E402
from app.engine.sprites import SPRITE_DIR, build_expr_pack, ingest_upload  # noqa: E402
from app.models import Story, StorySnapshot  # noqa: E402

# cids whose art is OWNED by another story (shared face) — never regenerate here
HARD_SKIP = {"cyclone"}

# 生成专用外貌 (八十年代港风): per-cid, story-agnostic engine stays clean
LOOKS: dict[str, str] = {
    "kf_adai": "二十二岁的少女，利落的高马尾，圆眼睛，眉毛英气，脸颊带一点健康的红，"
               "白色汗衫外系着深蓝围裙，围裙口袋鼓鼓的，袖口挽到手肘，手腕上一条红绳",
    # 生成陷阱备忘: 「抱着书」会在书封上长出乱码字, 「脖子搭毛巾」会画成耳机 —
    # 道具描述要挑图像模型不会自作聪明的 (实弹: 文清 v1 书封乱码, 阿彩 v1 戴上了耳机)
    "kf_manching": "二十四岁的温柔女教师，齐肩黑发别着一枚素色发夹，细框圆眼镜，"
                   "杏眼低垂含笑，白衬衫配过膝的米色长裙，双手轻轻交叠在身前，"
                   "气质安静斯文，八十年代香港",
    "kf_achoi": "十九岁的活泼少女，蓬松的棕色烫卷短发，大眼睛亮晶晶，"
                "笑起来露出小虎牙，耳朵上一对彩色塑料圆片耳环，桃红色短袖衬衫，"
                "外面罩一件浅蓝色开襟罩衫，八十年代香港发廊小妹的打扮",
    "kf_saifai": "二十岁的成年男性，市井后生的痞气，清瘦，寸头，眉眼带笑，"
                 "嘴角叼着一根没点的烟，花衬衫敞着最上面两颗扣子，里面是白背心，"
                 "深色长裤，站姿松松垮垮",
}


def tachie_prompt(name: str, looks: str, art: str) -> str:
    # style anchor rides FIRST (art bible doctrine: 画风是 token 体系, 前置才压得住)
    return (f"{art}。单人全身立绘：{name}，{looks}。平静自然的神情，正面站姿微侧，"
            "人物完整（从头顶到脚都在画面内，头顶上方留出空间），画面里只有这一个人。"
            "纯色浅灰背景，柔和顶光，高细节，画面里没有任何文字或水印")


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    force = "--force" in sys.argv
    title = args[0] if args else "九龙城寨·浮生"
    only = set(args[1:])   # targeted redo: limit to these cids
    db = SessionLocal()
    try:
        s = db.query(Story).filter(Story.title == title).first()
        if not s:
            raise SystemExit(f"story not found: {title}")
        art = str((s.tuning or {}).get("art_style") or "")
        if not art:
            raise SystemExit(f"《{title}》 has no tuning.art_style — author the bible first")
        SPRITE_DIR.mkdir(parents=True, exist_ok=True)
        chars = list(s.characters or [])
        changed = False
        for c in chars:
            cid, name = c.get("id"), c.get("name")
            if not cid or not name or (only and cid not in only):
                continue
            url = f"/scene/avatar/{cid}.jpg"
            if cid in HARD_SKIP:
                # shared-face cameo: art already exists under this cid; just wire the url
                if c.get("avatar_url") != url:
                    c["avatar_url"] = url
                    changed = True
                print(f"  skip {name} ({cid}) — shared face, art owned elsewhere")
                continue
            if (SPRITE_DIR / f"{cid}.webp").exists() and not force:
                if c.get("avatar_url") != url:
                    c["avatar_url"] = url
                    changed = True
                print(f"  skip {name} ({cid}) — sprite exists")
                continue
            looks = LOOKS.get(cid) or (c.get("persona_text") or "")[:120]
            print(f"  t2i {name} ({cid})…", end=" ", flush=True)
            img = generate_image(tachie_prompt(name, looks, art), size="720*1280",
                                 model=FIGURE_MODEL, seed=char_seed(s.id, cid),
                                 negative=portrait_negative(art))
            if not img:
                print("FAILED")
                continue
            ingest_upload(cid, img)
            c["avatar_url"] = url
            changed = True
            print(f"OK ({len(img) // 1024} KB)")
            rep = build_expr_pack([cid])
            print(f"    exprs: done={len(rep['done'])} skipped={len(rep['skipped'])} "
                  f"failed={len(rep['failed'])}")
        if changed:
            s.characters = chars
            flag_modified(s, "characters")
            snap = (db.query(StorySnapshot).filter(StorySnapshot.story_id == s.id)
                    .order_by(StorySnapshot.version.desc()).first())
            if snap and snap.content:
                content = dict(snap.content)
                snap_chars = ((content.get("story") or {}).get("characters")) or []
                by_id = {c.get("id"): c for c in chars}
                for sc in snap_chars:
                    src = by_id.get(sc.get("id"))
                    if src and src.get("avatar_url"):
                        sc["avatar_url"] = src["avatar_url"]
                snap.content = content
                flag_modified(snap, "content")
            db.commit()
            print("✅ avatar_url wired into story + latest snapshot")
    finally:
        db.close()


if __name__ == "__main__":
    main()
