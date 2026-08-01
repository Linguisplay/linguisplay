# -*- coding: utf-8 -*-
"""One-off: 场账本试点开旗 (docs/scene-ledger.md) — tuning.scene_ledger=1 打进狗笼三层
(patch_tuning 模式: Story 行 + 最新快照 + 在途 run 钉住副本; run 内容创建时冻结,
光改 Story 行对老存档无效)。回滚 = SCENE_LEDGER=0 重跑本脚本。

Run ON THE SERVER:
    cd /opt/linguisplay/apps/api && \
      PYTHONIOENCODING=utf-8 LP_DB=data/linguisplay.db .venv/bin/python patch_scene_pilot.py
Local dry-run:  LP_DB=<copy.db> python patch_scene_pilot.py
"""
import json
import os
import sqlite3

DB = os.environ.get("LP_DB", "dev.db")
VALUE = int(os.environ.get("SCENE_LEDGER", "1"))
TITLES = ["九龙城寨·狗笼"]   # 试点面窄一点: 先旗舰, 数据说话再扩


def _set(tun):
    tun = dict(tun or {})
    tun["scene_ledger"] = VALUE
    return tun


def main() -> None:
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    for title in TITLES:
        row = db.execute("select id, tuning from stories where title=?", (title,)).fetchone()
        if not row:
            print(f"! not found: {title}")
            continue
        sid = row["id"]
        db.execute("update stories set tuning=? where id=?",
                   (json.dumps(_set(json.loads(row["tuning"] or "{}")), ensure_ascii=False), sid))
        snap = db.execute("select id, content from story_snapshots where story_id=? "
                          "order by version desc limit 1", (sid,)).fetchone()
        if snap:
            c = json.loads(snap["content"])
            story = c.get("story") or {}
            story["tuning"] = _set(story.get("tuning"))
            db.execute("update story_snapshots set content=? where id=?",
                       (json.dumps(c, ensure_ascii=False), snap["id"]))
        n = 0
        for r in db.execute("select id, pinned_content from runs where story_id=?", (sid,)).fetchall():
            if not r["pinned_content"]:
                continue
            pc = json.loads(r["pinned_content"])
            story = pc.get("story") or {}
            story["tuning"] = _set(story.get("tuning"))
            db.execute("update runs set pinned_content=? where id=?",
                       (json.dumps(pc, ensure_ascii=False), r["id"]))
            n += 1
        print(f"✓ {title}: scene_ledger={VALUE} → story + snapshot + {n} run(s)")
    db.commit()
    db.close()


if __name__ == "__main__":
    main()
