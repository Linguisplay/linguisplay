# -*- coding: utf-8 -*-
"""One-shot hot-patch: the asylum's sharpened horror PROSE style + its new ART
direction (tuning.art_style), stitched through all three layers (Story row →
snapshots → runs' pinned copies) so existing saves feel it immediately — no
re-seed, no lost saves. Pair with `backfill_avatars.py --redo 寂声疗养院` to
re-render the book's portraits and backdrops under the new art."""
from sqlalchemy.orm.attributes import flag_modified

from app.db import SessionLocal, init_db
from app.models import Run, Story, StorySnapshot

TITLE = "寂声疗养院"

STYLE = ("贴身的恐怖：恐惧来自声音与光，不来自血浆——脚步声停在门外的三秒，"
         "比任何嘶吼都可怕。短句，多留白，能不解释就不解释；黑暗里先写听见的，"
         "再写看见的。忌一惊一乍连发，忌形容词堆叠，忌超自然直给"
         "（一切恐怖必须可以被解释为人祸）。对白少而钝，疯话要有可破译的芯。"
         "恐怖的笔从这里下：写听见的（压缩机的嗡鸣忽然停了、布料蹭过墙面）、"
         "写皮肤的（后颈的凉、汗把掌心黏住）、写日常物的错位（摆得太整齐的拖鞋、"
         "观察窗内侧的一枚指印、还温着的半杯茶）；长句铺垫，短句落刀；"
         "人物的恐惧只写行为——阿枝数石子越数越快、温以宁把已经很直的病历敲得更直——"
         "不写「害怕」「恐惧」这类标签词。"
         "铁松两条铁律：他的每次现身必须先声后形——先写声音/气味/影子，最后才见形；"
         "他离开必须留下痕迹——门缝下停了三秒才移开的影子、一股散不掉的旧棉被味。")

ART = ("阴郁冷调的恐怖片美术：低饱和青绿与病态的荧光灯白，深重阴影吃掉画面边缘，"
       "胶片噪点，潮湿剥落的墙皮与发黄旧瓷砖质感，构图冷静对称、留出令人不安的空旷，"
       "绝不出现血浆与怪物")


def patch_story_dict(st: dict) -> None:
    st["style"] = STYLE
    tun = dict(st.get("tuning") or {})
    tun["art_style"] = ART
    st["tuning"] = tun


def main() -> None:
    init_db()
    db = SessionLocal()
    try:
        stories = db.query(Story).filter(Story.title == TITLE).all()
        for s in stories:
            s.style = STYLE
            tun = dict(s.tuning or {})
            tun["art_style"] = ART
            s.tuning = tun
            flag_modified(s, "tuning")
            n_snap = n_run = 0
            for snap in db.query(StorySnapshot).filter(StorySnapshot.story_id == s.id).all():
                if snap.content and snap.content.get("story"):
                    patch_story_dict(snap.content["story"])
                    flag_modified(snap, "content")
                    n_snap += 1
            for r in db.query(Run).filter(Run.story_id == s.id).all():
                if r.pinned_content and r.pinned_content.get("story"):
                    patch_story_dict(r.pinned_content["story"])
                    flag_modified(r, "pinned_content")
                    n_run += 1
            print(f"story {s.id[:8]}: style+art patched, snapshots={n_snap}, runs={n_run}")
        db.commit()
        print("done" if stories else "story not found")
    finally:
        db.close()


if __name__ == "__main__":
    main()
