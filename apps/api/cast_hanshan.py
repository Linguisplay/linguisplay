# -*- coding: utf-8 -*-
"""🎙 《寒山 · 松雪宗》配音选角 (Yi 2026-08-03:「寒山的角色都配上吧」)。

写进角色卡 voice = {"id": 音色, "speed": 语速}。配了音色, 这个角色开口那一下就带
语气音 (「嗯 / 哼 / 诶?!」), 逐句台词也才有得点。

选角两条法度:
  ① 音色管【底色】, 语速管【这个人】。池子里中文男声只有 11 个而寒山有 13 个男角,
     复用的三对一律拉开两档以上语速 —— 同声同速才会串戏, 差两档听着就是两个人。
  ② 语速只用界面上那五档 (0.85 / 0.92 / 1.0 / 1.06 / 1.15), 否则作者一进工坊,
     下拉显示不出他听到的那一档。

幂等: 按角色【名字】认人 (寒山的 id 是种下去的 c_xxx, 但名字才是选角表读得懂的)。
重跑只覆盖 voice 一个字段。跑在服务器上:
    cd /opt/linguisplay/apps/api && set -a && . .env && set +a && .venv/bin/python cast_hanshan.py
"""
import os
import sys

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./dev.db")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

STORY = "寒山 · 松雪宗"

# 角色 → (音色, 语速, 为什么)
CAST: dict[str, tuple[str, float, str]] = {
    # ── 五攻略 (五行) ──
    "裴无咎": ("longtian_v3", 0.92, "金 · 承霜峰大师兄 — 磁性理智压半档, 话少而稳"),
    "楚焕":   ("longanyang", 1.06, "火 · 灼云峰体修 — 阳光大男孩加半档, 藏不住事"),
    "卫长陵": ("longanzhi_v3", 0.92, "木 · 药庐主人 — 睿智轻熟, 医者说话不赶"),
    "沈砚":   ("longshuo_v3", 0.92, "土 · 戒律首座 — 博才干练, 一句是一句"),
    "云疏":   ("longcheng_v3", 1.0, "水 · 阵师 — 智慧青年, 数着步子走路的人语速正常"),
    # ── 十配角 ──
    "谢寒山": ("longshu_v3", 0.85, "掌门病中闭关 — 沉稳青年压到最慢, 病气从速度出"),
    "姜叙":   ("longanzhi_v3", 0.85, "三长老 · 抄宗规十九年 — 与卫长陵同声差两档"),
    "雷九":   ("longze_v3", 1.06, "执事 · 人未到声先到 — 温暖元气加半档"),
    "阿茕":   ("longjielidou_v3", 1.15, "十四五岁小师弟 — 童声路子拉到最快"),
    "老瞎":   ("longfei_v3", 0.85, "剑冢守 · 罪徒出身 — 热血磁性压到最慢, 磨出沙"),
    "石头":   ("longyingxun_v3", 1.0, "外门弟子 · 憨 — 年轻青涩本色"),
    "白栖":   ("longfei_v3", 1.06, "游方修士 · 卖消息 — 与老瞎同声差三档, 江湖气"),
    "冥七":   ("longze_v3", 0.85, "魔道使者 — 与雷九同声差三档, 压下去就冷了"),
    # ── 两个女角 (新扩的女声池) ──
    "苓儿":   ("longhua_v3", 1.06, "药童 · 说话一句压一句 — 元气甜美加半档"),
    "阿婆":   ("longxiaoxia_v3", 0.85, "七十岁掌灶 — 沉稳权威压到最慢"),
}


def main() -> None:
    from app.db import SessionLocal
    from app.models import Story
    dry = "--dry" in sys.argv
    db = SessionLocal()
    s = db.query(Story).filter(Story.title == STORY).first()
    if not s:
        print(f"找不到《{STORY}》")
        return
    chars = list(s.characters or [])
    hit, miss = 0, []
    for c in chars:
        row = CAST.get(c.get("name"))
        if not row:
            miss.append(c.get("name"))
            continue
        vid, speed, why = row
        c["voice"] = {"id": vid, "speed": speed}
        hit += 1
        print(f"  {c.get('name'):　<5} → {vid:<18} ×{speed}  {why}")
    unused = [n for n in CAST if n not in {c.get("name") for c in chars}]
    if miss:
        print(f"⚠️ 剧本里有人没在选角表上: {miss}")
    if unused:
        print(f"⚠️ 选角表上有人不在剧本里: {unused}")
    if dry:
        print(f"[dry] 会配 {hit}/{len(chars)} 人")
        return
    s.characters = chars
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(s, "characters")
    # 📸 最新快照也要跟上 —— 配音是演出层, 在途的档该立刻有声音, 不必等重开
    from app.models import StorySnapshot
    snap = (db.query(StorySnapshot).filter(StorySnapshot.story_id == s.id)
            .order_by(StorySnapshot.version.desc()).first())
    if snap and isinstance(snap.content, dict):
        sc = dict(snap.content)
        st = dict(sc.get("story") or {})
        if st.get("characters"):
            names = {c.get("name"): c.get("voice") for c in chars}
            for c in st["characters"]:
                if c.get("name") in names:
                    c["voice"] = names[c["name"]]
            sc["story"] = st
            snap.content = sc
            flag_modified(snap, "content")
            print(f"  快照 v{snap.version} 同步")
    db.commit()
    print(f"✅ 配了 {hit}/{len(chars)} 人")


if __name__ == "__main__":
    main()
