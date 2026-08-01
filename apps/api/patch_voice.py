# -*- coding: utf-8 -*-
"""One-off: hot-patch 🎙 配音选角 (characters[].voice) into the pilot stories
WITHOUT reseeding. 按【角色名】对号 — 旗舰《狗笼》的班底是库里长出来的
(id 是 c_xxxxxx 铸造名), seed 的 id 对不上; 名字才是稳定键。
playable=True 的角色自动跳过 (galgame 惯例: 玩家角色不配音)。
三层同步 (patch_style 模式): story 行 + 最新快照 + 在途 run 的钉住副本。

Run ON THE SERVER:
    cd /opt/linguisplay/apps/api && \
      PYTHONIOENCODING=utf-8 LP_DB=data/linguisplay.db .venv/bin/python patch_voice.py
Local dev:  python patch_voice.py   (LP_DB defaults to dev.db)
"""
import json
import os
import sqlite3

DB = os.environ.get("LP_DB", "dev.db")

# story title → {角色名 → voice}。与 seed 选角同步 — 改选角先改 seed 再同步这里。
# 模型全线 cosyvoice-v3-flash (engine/voice.MODEL); 语速是每角色的戏味旋钮。
_KOWLOON = {
    "龙卷风": {"id": "longanyue_v3", "speed": 0.9},     # 唯一粤语男声, 降速出沧桑
    "蓝信一": {"id": "longtian_v3", "speed": 1.0},      # 磁性理智
    "十二少": {"id": "longfei_v3", "speed": 1.05},      # 热血磁性
    "四仔":   {"id": "longjielidou_v3", "speed": 1.0},  # 阳光顽皮
    "蔡妍":   {"id": "longjiayi_v3", "speed": 1.0},     # 知性粤语女 (狗笼里是NPC; 龙头里可扮→自动跳过)
    "王九":   {"id": "longcheng_v3", "speed": 0.95},    # 冷而利落
    "大老板": {"id": "longanzhi_v3", "speed": 0.92},    # 睿智轻熟, 笑里藏刀
    # 狗笼独有的库生角色 (seed 里没有)
    "陈洛军": {"id": "longyingxun_v3", "speed": 1.0},   # 年轻青涩
    "Tiger哥": {"id": "longze_v3", "speed": 1.02},      # 元气大只
    "狄秋":   {"id": "longanyang", "speed": 0.88},      # 情感instruct音色, 压速做狠劲
}
CASTING = {
    "九龙城寨·狗笼": _KOWLOON,   # 旗舰 (Yi 点名的试点)
    "九龙城寨·龙头": _KOWLOON,   # 同班底新种, 顺路同步
    "Golden Hour": {
        "Elias Varda":   {"id": "loongeric_v3", "speed": 0.92},
        "Rafael Cortez": {"id": "loongdavid_v3", "speed": 1.0},
        "Niko Petrides": {"id": "loongandy_v3", "speed": 1.06},
        "Ilya Sørensen": {"id": "longanlang_v3", "speed": 0.95},
        "Marek Duna":    {"id": "loongluca_v3", "speed": 1.0},
    },
}


def _cast(chars, casting) -> int:
    n = 0
    for c in chars or []:
        if c.get("playable"):
            continue
        v = casting.get(str(c.get("name") or "").strip())
        if v and c.get("voice") != v:
            c["voice"] = dict(v)
            n += 1
    return n


def main() -> None:
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    for title, casting in CASTING.items():
        row = db.execute("select id, characters from stories where title=?", (title,)).fetchone()
        if not row:
            print(f"! not found: {title}")
            continue
        sid = row["id"]
        chars = json.loads(row["characters"] or "[]")
        hit = _cast(chars, casting)
        db.execute("update stories set characters=? where id=?",
                   (json.dumps(chars, ensure_ascii=False), sid))
        snap = db.execute("select id, content from story_snapshots where story_id=? "
                          "order by version desc limit 1", (sid,)).fetchone()
        if snap:
            c = json.loads(snap["content"])
            _cast((c.get("story") or {}).get("characters"), casting)
            db.execute("update story_snapshots set content=? where id=?",
                       (json.dumps(c, ensure_ascii=False), snap["id"]))
        n_runs = 0
        for r in db.execute("select id, pinned_content from runs where story_id=?", (sid,)).fetchall():
            if not r["pinned_content"]:
                continue
            pc = json.loads(r["pinned_content"])
            if _cast((pc.get("story") or {}).get("characters"), casting):
                db.execute("update runs set pinned_content=? where id=?",
                           (json.dumps(pc, ensure_ascii=False), r["id"]))
                n_runs += 1
        print(f"✓ {title}: {hit} character(s) cast + snapshot + {n_runs} run(s)")
    db.commit()
    db.close()


if __name__ == "__main__":
    main()
