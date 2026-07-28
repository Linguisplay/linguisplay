# -*- coding: utf-8 -*-
"""🔎 批量智能增强: 给一本剧本的所有角色跑联网检索, 把设定(含外貌)写进 knowledge。

为什么单独做成脚本 (Yi 2026-07-28): 生图要画「网上常见的那个形象」, 靠一句
「请画经典形象」指望画图模型自己认得是不够的 —— 真正可靠的做法是把联网检索到的
外貌描述喂进提示词。而 knowledge 正是 qwen.generate_knowledge 的落点(它会判 is_ip、
生成检索词、跑 Tavily、再把结果整理成【人物设定】等结构块)。Studio 里那个「智能增强」
按钮做的就是这件事, 但只能一本一本点; 这里给命令行一个入口, 顺便打印抓到的外貌,
好在生图之前先肉眼确认抓对了人。

Run:  python enrich_knowledge.py "<剧本标题>" [--force] [--only cid1,cid2]
"""

import os
import sys

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./dev.db")
os.environ.setdefault("JWT_SECRET", "dev")

from app.db import SessionLocal  # noqa: E402
from app.engine import ipface  # noqa: E402
from app.models import Story, StorySnapshot  # noqa: E402
from app.routers.stories import _to_story  # noqa: E402


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    force = "--force" in sys.argv
    only = set()
    for a in sys.argv[1:]:
        if a.startswith("--only"):
            only = {x.strip() for x in a.split("=", 1)[-1].split(",") if x.strip()}
    if not args:
        print('usage: python enrich_knowledge.py "<剧本标题>" [--force] [--only=cid1,cid2]')
        sys.exit(1)
    title = args[0]

    from app.engine.qwen import generate_knowledge

    db = SessionLocal()
    try:
        s = (db.query(Story).filter(Story.title == title, Story.visibility == "public").first()
             or db.query(Story).filter(Story.title == title).first())
        if not s:
            raise SystemExit(f"story not found: {title}")
        ip = ipface.ip_of(s)
        print(f"《{title}》 {'IP=' + ip if ip else '（原创本）'}")
        world = " ".join(filter(None, [s.world_long, s.synopsis, s.one_liner]))[:600]
        chars = [dict(c) for c in (s.characters or [])]
        done = 0
        for c in chars:
            cid, name = c.get("id"), c.get("name")
            if not cid or not name or (only and cid not in only):
                continue
            if c.get("knowledge") and not force:
                print(f"  skip {name} ({cid}) — 已有 knowledge")
                continue
            profile = " ".join(filter(None, [c.get("role"), c.get("persona_text"),
                                             c.get("background")]))
            print(f"  搜 {name} ({cid})…", end=" ", flush=True)
            kn = generate_knowledge(name, profile, world)
            if not kn:
                print("空（检索失败或无结果）")
                continue
            c["knowledge"] = kn
            done += 1
            # 🎨 同人角色再单跑一路专搜外貌 —— 通用检索词问的是武魂/剧情/关系,
            # 外貌常常一个字都没有, 而生图要的恰恰只有外貌 (Yi 2026-07-28)
            looks = ipface.looks_from_knowledge(kn)
            if ip:
                canon = ipface.fetch_canon_looks(ip, name, c.get("persona_text") or "")
                if canon:
                    looks = canon
                    c["looks"] = canon
            print(f"OK {len(kn)}字 | 外貌: {looks[:70] or '（没搜到外貌，生图只能靠经典形象条款）'}")
        s.characters = chars
        if s.status == "published" and s.version:
            snap = (db.query(StorySnapshot)
                    .filter(StorySnapshot.story_id == s.id,
                            StorySnapshot.version == s.version).first())
            if snap:
                content = dict(snap.content or {})
                content["story"] = _to_story(s).model_dump()
                content["story"]["version"] = s.version
                snap.content = content
        db.commit()
        print(f"✅ {done} 个角色写入 knowledge（快照已同步）")
    finally:
        db.close()


if __name__ == "__main__":
    main()
