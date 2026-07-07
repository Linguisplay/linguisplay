# -*- coding: utf-8 -*-
"""One-off: add the stories.style column and hot-patch 文风 into the four fan sandboxes
WITHOUT reseeding (existing runs keep their progress; their pinned copies get the style
too, so the voice change reaches runs already in flight).

Run ON THE SERVER:
    cd /opt/linguisplay/apps/api && \
      export DATABASE_URL='sqlite+pysqlite:////opt/linguisplay/apps/api/data/linguisplay.db' && \
      PYTHONIOENCODING=utf-8 .venv/bin/python patch_style.py
"""
import json
import os
import sqlite3

DB = os.environ.get("LP_DB", "data/linguisplay.db")

STYLES = {
    "斗罗大陆·史莱克学院": (
        "网文热血流，唐门暗器与武魂大陆的少年成长腔。短句直给，节奏快，"
        "招式名与魂技要朗声报出来（「三环齐出！」）；战斗一板一眼讲章法：魂力差距、魂环年限、"
        "配合走位说得清清楚楚，数值感就是仪式感。感情戏青涩纯真，点到即止；同伴之间讲义气、"
        "爱打趣。旁白可在紧要处直白点题（这一刻，他忽然明白了什么叫强者）。"
        "忌欧化长句，忌华丽堆藻，忌阴郁文艺腔。"),
    "斗气大陆·迦南学院": (
        "玄幻爽文流，扮猪吃虎与打脸节奏的爽文腔。气势渲染要足"
        "（一股无形威压铺开，全场骤然一静），等级压制写出实感；主角被轻视时先蓄势，"
        "再一鸣惊人，打脸那一下要脆。斗气、丹药、异火术语自然挂嘴边；长者高深莫测，"
        "少年锋芒暗藏。关键处用短句砸。忌温吞拖沓，忌文艺腔冲淡爽感。"),
    "魔法都市·明珠学院": (
        "都市魔法热血流，现代口语加吐槽感的都市异能腔。角色说话像今天的年轻人"
        "（有梗、损友互怼），旁白利落带点幽默；一进战斗立刻收紧：星图、元素、魔兽的压迫感"
        "写得又快又狠，生死关头不开玩笑。城市烟火气与魔法并置是底色（奶茶店隔壁就是猎者工会）。"
        "忌古风腔，忌翻译腔，忌一本正经到底。"),
    "战锤40K·科瓦兹蜂巢": (
        "哥特暗黑史诗腔，庄重压抑带宗教仪式感的战锤 grimdark 腔。旁白像风琴与祷文："
        "机油、熏香、锈与血的意象层层压下来；帝国语汇成体系（帝皇保佑、异端、净化、机魂），"
        "人物开口带着阶级与信仰的烙印。残酷不煽情，死亡写得冷，偶尔一丝黑色幽默从缝里漏出来更冷。"
        "宏大与卑微并置：万年帝国之下，一个人的命薄如祷纸。忌轻快，忌现代网络语，忌热血少年腔。"),
}


def main() -> None:
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    cols = [c[1] for c in db.execute("pragma table_info(stories)")]
    if "style" not in cols:
        db.execute("alter table stories add column style text")
        print("+ column stories.style")
    for title, style in STYLES.items():
        row = db.execute("select id from stories where title=?", (title,)).fetchone()
        if not row:
            print(f"! not found: {title}")
            continue
        sid = row["id"]
        db.execute("update stories set style=? where id=?", (style, sid))
        # latest snapshot content
        snap = db.execute("select id, content from story_snapshots where story_id=? "
                          "order by version desc limit 1", (sid,)).fetchone()
        if snap:
            c = json.loads(snap["content"])
            (c.get("story") or {})["style"] = style
            db.execute("update story_snapshots set content=? where id=?",
                       (json.dumps(c, ensure_ascii=False), snap["id"]))
        # runs in flight: their pinned copies pick the voice up too
        n = 0
        for r in db.execute("select id, pinned_content from runs where story_id=?", (sid,)).fetchall():
            if not r["pinned_content"]:
                continue
            pc = json.loads(r["pinned_content"])
            (pc.get("story") or {})["style"] = style
            db.execute("update runs set pinned_content=? where id=?",
                       (json.dumps(pc, ensure_ascii=False), r["id"]))
            n += 1
        print(f"✓ {title}: story + snapshot + {n} run(s)")
    db.commit()
    db.close()


if __name__ == "__main__":
    main()
