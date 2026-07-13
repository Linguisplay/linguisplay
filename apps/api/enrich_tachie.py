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

--restyle: instead of a fresh t2i (which rolls the style dice every time — 实弹:
v3 一批四个人跑出四种画风), EDIT the archived {cid}_photo.jpg into the bible's core
style. Edit preserves identity/pose; the instruction anchors the style — the
smart_cast conversion doctrine applied to our own best historical renders.

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
from app.engine.gal import char_seed, is_anime_style, portrait_negative  # noqa: E402
from app.engine.qwen import edit_image, generate_image  # noqa: E402

# 立绘底模: Seedream 4.0 走火山方舟 (Yi 2026-07-13 定; 阿里欠费 + 阿彩对照实验完胜)。
# 928*1664 高分辨率, char_seed 同脸体系照旧 (Ark 支持 seed)。
TACHIE_MODEL = "doubao-seedream-4-0-250828"
TACHIE_SIZE = "928*1664"
from app.engine.sprites import SPRITE_DIR, build_expr_pack, ingest_upload  # noqa: E402
from app.models import Story, StorySnapshot  # noqa: E402

# cids whose art is OWNED by another story (shared face) — never regenerate here
HARD_SKIP = {"cyclone", "shin", "twelfth", "sei"}   # 龙头共享脸, 永不在浮生重画

# 生成专用外貌 (八十年代港风): per-cid, story-agnostic engine stays clean
LOOKS: dict[str, str] = {
    # 阿娣/阿彩的措辞版本: 同 seed 同词会复现同一次失败 — 返工必须改词 (马尾围裙前置,
    # 全身+鞋写死; 实弹: v5 阿娣丢了马尾围裙、阿彩连续三版半身)
    "kf_adai": "二十二岁的少女全身站姿，扎着利落的高马尾（红色发绳），圆眼睛，眉毛英气，"
               "白色短袖汗衫外系着一条深蓝色长围裙（从胸前罩到膝盖，口袋鼓鼓的），"
               "袖口挽到手肘，手腕上一条红绳，下身长裤，脚上一双黑色布鞋，双脚站在地上",
    # 生成陷阱备忘: 「抱着书」会在书封上长出乱码字, 「脖子搭毛巾」会画成耳机 —
    # 道具描述要挑图像模型不会自作聪明的 (实弹: 文清 v1 书封乱码, 阿彩 v1 戴上了耳机)
    "kf_manching": "二十四岁的温柔女教师，齐肩黑发别着一枚素色发夹，细框圆眼镜，"
                   "杏眼低垂含笑，白衬衫配过膝的米色长裙，双手轻轻交叠在身前，"
                   "气质安静斯文，八十年代香港",
    "kf_achoi": "十九岁的活泼少女站立全身像（从头发到帆布鞋完整入画，人物只占画面中间"
                "三分之一高度也可以）：满头蓬松细密的泡面卷短发（烫过的小卷，绝不是辫子"
                "也不是直发），大眼睛亮晶晶，笑起来露出小虎牙，彩色塑料圆片耳环，"
                "桃红色短袖衬衫外罩浅蓝色开襟背心，高腰牛仔裤，白色帆布鞋，"
                "八十年代香港发廊小妹",
    # 细辉 v1 (seedream) 裁掉了鞋 — 阿彩同款的全身条款是解药 (返工必须改词)
    "kf_saifai": "二十岁的成年男性全身站姿像（从头顶到鞋完整入画，人物只占画面中间"
                 "三分之二高度也可以），市井后生的痞气，清瘦，寸头，眉眼带笑，"
                 "嘴角叼着一根没点的烟，花衬衫敞着最上面两颗扣子，里面是白背心，"
                 "深色长裤配黑色皮鞋，站姿松松垮垮",
}


def tachie_prompt(name: str, looks: str, art: str) -> str:
    # style anchor rides FIRST (art bible doctrine: 画风是 token 体系, 前置才压得住)
    # Seedream 铁律: 圣经按「；舞台」拆分, 立绘只喂画风段 — 舞台段入词必画整条街
    # (阿彩 v1 存证), qwen-image 从前只是碰巧没接住它
    art = art.split("；舞台")[0]
    return (f"{art}。单人全身立绘：{name}，{looks}。平静自然的神情，正面站姿微侧，"
            "双脚站在地上，人物完整（从头顶到鞋都在画面内，头顶上方留出空间），"
            "画面里只有这一个人。纯色浅灰背景，柔和顶光，高细节，画面里没有任何文字或水印")


# 统一画风的负词 (实弹: v1 四个人四种画风 — 文清跑成现代萌系、阿彩跑成 2010s 厚涂):
# portrait_negative 只挡对面阵营, 这里再钉死本阵营内部的邻居风格。写实圣经用
# _REAL_NEG (实弹: 文清两跑掉进 3D 玩偶脸引力井 — 皮克斯/玩偶要点名)
_STYLE_NEG = ",厚涂,现代插画,韩系插画,渐变高光,萌系,Q版,大头,3D渲染,半身像,特写,腿部裁切"
_REAL_NEG = ",CG,玩偶,皮克斯,塑料质感,光滑假皮肤,大头,半身像,特写,腿部裁切"

# 换风格后个别 seed 会掉进坏引力井且改词拽不出 (文清: 3D 玩偶脸两连) —
# 给该 cid 挪一个确定性盐位, 从此就是它的正史 seed
SEED_SALT = {"kf_manching": "kf_manching-film2"}


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    force = "--force" in sys.argv
    restyle = "--restyle" in sys.argv
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
            photo = SPRITE_DIR / f"{cid}_photo.jpg"
            if restyle and photo.exists():
                # 改绘铁律 (smart_cast 同款): 保真条款放最前, 画风只给一句核心
                core = art.split("；")[0][:140]
                print(f"  restyle {name} ({cid})…", end=" ", flush=True)
                img = edit_image(photo.read_bytes(),
                                 "严格保持画面中人物的性别、体格、发型、五官特征、服装、"
                                 f"姿势和构图完全一致，只把画风改绘为：{core}。"
                                 "不改变人物的任何特征，只改画风",
                                 mime="image/jpeg")
            else:
                print(f"  t2i {name} ({cid})…", end=" ", flush=True)
                camp_neg = _STYLE_NEG if is_anime_style(art) else _REAL_NEG
                img = generate_image(tachie_prompt(name, looks, art), size=TACHIE_SIZE,
                                     model=TACHIE_MODEL,
                                     seed=char_seed(s.id, SEED_SALT.get(cid, cid)),
                                     negative=portrait_negative(art) + camp_neg)
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
