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
        "唐家三少式网文白描：大白话，短句，干净直给，描写大多一笔带过，绝不堆形容。剧情靠感情（亲情/友情/纯爱）和目标驱动，等级与魂技设定清晰入戏，招式名朗声报出；对话与动作扛起全部叙事。叙事经济学（最高优先）：每一轮必须有一件具体的事向前发生（新行动/新变故/新决定），环境与外貌描写全轮合计不超过两句，形容词能删则删，绝不原地渲染气氛。忌欧化长句，忌文艺腔，忌氛围铺陈。"),
    "斗气大陆·迦南学院": (
        "天蚕土豆式爽文节奏：小白文直给，事件链永远向前（蓄势、受挫、打脸、升级），描写只为气势服务且一笔带过；等级压制写实感，关键处短句砸。叙事经济学（最高优先）：每一轮必须有一件具体的事向前发生（新行动/新变故/新决定），环境与外貌描写全轮合计不超过两句，形容词能删则删，绝不原地渲染气氛。忌温吞，忌华丽堆藻，忌文艺腔冲淡爽感。"),
    "魔法都市·明珠学院": (
        "都市网文快节奏：现代口语带吐槽，事件推进为王，战斗一进入立刻收紧写快写狠；城市烟火气用一笔点到即止。叙事经济学（最高优先）：每一轮必须有一件具体的事向前发生（新行动/新变故/新决定），环境与外貌描写全轮合计不超过两句，形容词能删则删，绝不原地渲染气氛。忌古风腔，忌翻译腔，忌大段景物描写。"),
    "战锤40K·科瓦兹蜂巢": (
        "Black Library 式电影感叙事：动作与决断推进剧情，镜头利落，人物用行为立起来；哥特与宗教氛围一两笔点睛即可（机油、祷文、双头鹰），不铺满；残酷冷峻不煽情，帝国语汇自然入话。叙事经济学（最高优先）：每一轮必须有一件具体的事向前发生（新行动/新变故/新决定），环境与外貌描写全轮合计不超过两句，形容词能删则删，绝不原地渲染气氛。忌轻快，忌现代网络语，忌大段意象堆叠。"),
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
