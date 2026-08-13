# -*- coding: utf-8 -*-
"""🎭 给某个剧本的角色换一批新 id（两个剧本共用立绘时用）。

背景（Yi 2026-08-12 报障，九龙城寨·狗笼）：
立绘/头像/封面全都按 `{cid}.webp` 存盘，**按角色 id 分文件，不按剧本分**。
而狗笼直接沿用了龙头的四个角色 id（cyclone/shin/twelfth/sei），于是两本共用同一批
图片文件。两本的 art_style 恰好是相反的两套：

    龙头  九十年代日式赛璐璐（细线稿、平涂、菱形高光、七头身）
    狗笼  港片写实胶片（35mm 扫描、柯达色调、皮肤织物质感真实）

谁先渲染，另一本就只能用谁的画风。结果狗笼一屏上二次元和真人照片并排站着。
（渲染判据是「文件在不在」，不是「画风对不对」，所以整个流程认为这活干过了。）

Yi 的裁定：「这是两个剧本，就按照两个剧本来就好了。」
=> 换 id，不换路径。所有取图的地方都按 cid 找文件，角色有了自己的 id，
   立绘/头像/封面/客户端自然就分开了，一行路径代码都不用动。

改动范围（先用 --dry 看清楚再落）：
  · stories 行：只替换【引号包住的整个 id】，不做子串替换（"sei" 这种短 id 尤其危险）
  · 最新一版 story_snapshot：新开局是从它 pin 的（见 runs.py::_freeze），不改这里等于没改
  · 旧快照与已有存档【一律不动】：它们各自自洽，图也都在，改了反而破坏历史

跑完那四个角色没有图（新 id 没有文件）。客户端有降级链（expr → base → _extra），
不会白屏；接着跑 backfill_avatars.py / backfill_sprites.py 用本剧本的画风重渲染。

用法:
    python rename_char_ids.py "九龙城寨·狗笼" cyclone=gl_cyclone shin=gl_shin --dry
    python rename_char_ids.py "九龙城寨·狗笼" cyclone=gl_cyclone shin=gl_shin --commit
"""
import argparse
import json
import re
import sys

from sqlalchemy.orm.attributes import flag_modified

from app.db import SessionLocal, init_db
from app.models import Story, StorySnapshot


def swap(text: str, mapping: dict[str, str]) -> tuple[str, int]:
    """只替换 JSON 里【被引号完整包住】的 id。

    ⚠️ 绝不做裸子串替换：id 短的时候（sei/shin）会打中正文里的普通词，
    把剧本正文改坏，而且改坏了不报错。
    """
    n = 0
    for old, new in mapping.items():
        pat = '"' + re.escape(old) + '"'
        hits = len(re.findall(pat, text))
        if hits:
            text = re.sub(pat, '"' + new + '"', text)
            n += hits
    return text, n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("title", help="剧本标题（完整匹配）")
    ap.add_argument("pairs", nargs="+", help="旧id=新id，可多个")
    ap.add_argument("--commit", action="store_true", help="真的写库（缺省只报告）")
    a = ap.parse_args()

    mapping = {}
    for p in a.pairs:
        if "=" not in p:
            print(f"✗ 参数要写成 旧id=新id：{p}")
            return 2
        old, new = p.split("=", 1)
        mapping[old.strip()] = new.strip()

    init_db()
    db = SessionLocal()
    try:
        s = db.query(Story).filter(Story.title == a.title).first()
        if not s:
            print(f"✗ 没有这个剧本：{a.title}")
            return 2

        total = 0
        # — 剧本行：逐列处理，只碰 JSON 列 —
        for col in ("characters", "sandbox", "acts", "locations", "endings",
                    "world_facts", "relations_overview"):
            val = getattr(s, col, None)
            if val is None:
                continue
            raw = json.dumps(val, ensure_ascii=False) if not isinstance(val, str) else val
            out, n = swap(raw, mapping)
            if not n:
                continue
            total += n
            print(f"  stories.{col:<20} {n} 处")
            if a.commit:
                setattr(s, col, out if isinstance(val, str) else json.loads(out))
                flag_modified(s, col)

        # — 最新快照：新开局从它 pin，不改这里等于没改 —
        snap = (db.query(StorySnapshot)
                .filter(StorySnapshot.story_id == s.id)
                .order_by(StorySnapshot.version.desc()).first())
        if snap and snap.content:
            raw = json.dumps(snap.content, ensure_ascii=False)
            out, n = swap(raw, mapping)
            if n:
                total += n
                print(f"  snapshot v{snap.version:<18} {n} 处")
                if a.commit:
                    snap.content = json.loads(out)
                    flag_modified(snap, "content")

        if not a.commit:
            db.rollback()
            print(f"\ndry run —— 共 {total} 处，什么都没写。加 --commit 才真改。")
            return 0
        db.commit()
        print(f"\n✅ 已写库，共 {total} 处。")
        print("接下来：backfill_avatars.py / backfill_sprites.py 用本剧本画风重渲染这几位。")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
