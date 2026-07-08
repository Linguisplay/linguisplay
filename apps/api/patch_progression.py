# -*- coding: utf-8 -*-
"""One-off: hot-patch the progression ladder into the three cultivation sandboxes
(stories.sandbox JSON + latest snapshot + in-flight runs' pinned copies)."""
import json, os, sqlite3

DB = os.environ.get("LP_DB", "data/linguisplay.db")
LADDERS = {
    "斗罗大陆·史莱克学院": {"name": "魂力", "ranks": ["魂士", "魂师", "大魂师", "魂尊", "魂宗",
                                                    "魂王", "魂帝", "魂圣", "斗罗", "封号斗罗"]},
    "斗气大陆·迦南学院": {"name": "斗气", "ranks": ["斗之气九段", "斗者", "斗师", "大斗师", "斗灵",
                                                  "斗王", "斗皇", "斗宗", "斗尊"]},
    "魔法都市·明珠学院": {"name": "魔法修为", "ranks": ["星子初凝", "星轨初成", "星轨娴熟",
                                                      "星云初聚", "星云大成", "星宫初开"]},
}

db = sqlite3.connect(DB)
db.row_factory = sqlite3.Row
for title, ladder in LADDERS.items():
    row = db.execute("select id, sandbox from stories where title=?", (title,)).fetchone()
    if not row:
        print("! not found:", title)
        continue
    sid = row["id"]
    sb = json.loads(row["sandbox"]) if row["sandbox"] else {}
    sb["progression"] = ladder
    db.execute("update stories set sandbox=? where id=?", (json.dumps(sb, ensure_ascii=False), sid))
    snap = db.execute("select id, content from story_snapshots where story_id=? order by version desc limit 1",
                      (sid,)).fetchone()
    if snap:
        c = json.loads(snap["content"])
        ((c.get("story") or {}).setdefault("sandbox", {}))["progression"] = ladder
        db.execute("update story_snapshots set content=? where id=?",
                   (json.dumps(c, ensure_ascii=False), snap["id"]))
    n = 0
    for r in db.execute("select id, pinned_content from runs where story_id=?", (sid,)).fetchall():
        if not r["pinned_content"]:
            continue
        pc = json.loads(r["pinned_content"])
        ((pc.get("story") or {}).setdefault("sandbox", {}))["progression"] = ladder
        db.execute("update runs set pinned_content=? where id=?",
                   (json.dumps(pc, ensure_ascii=False), r["id"]))
        n += 1
    print(f"✓ {title}: story + snapshot + {n} run(s)")
db.commit()
db.close()
