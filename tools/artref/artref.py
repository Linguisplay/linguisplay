#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""🎨 审美参考例库 (Yi 2026-08-17: 爬网上的好例子建库存档, 审美对标至关重要)。

定位: 内部审美参考 — 给人眼和画风圣经对标用。三条底线:
  ① 只抓公开 API 的源 (Danbooru 系, 本就为程序调用设计), 限速客气;
  ② 每张图保留来源页与作者, 不再分发、不直接喂进生成管线;
  ③ 手动投喂通道 (add) 比批量爬更值钱 — 你看到好图贴链接即入库。

用法 (从仓库根跑, 用 apps/api 的 venv):
  python tools/artref/artref.py crawl --tags "1boy solo rating:general" --limit 60 --min-score 40
  python tools/artref/artref.py add URL [URL...] --note "恋与深空级卡面构图"
  python tools/artref/artref.py gallery      # 生成 <库>/gallery.html 本地浏览
  python tools/artref/artref.py stats

库位: %ARTREF_ROOT% (默认 ~/artrefs) / artref.db + img/ + gallery.html
"""
import argparse
import hashlib
import json
import os
import pathlib
import sqlite3
import time
import urllib.parse
import urllib.request

UA = "linguisplay-artref/1.0 (internal aesthetic reference; contact: owner)"
API = "https://danbooru.donmai.us/posts.json"
OK_EXT = {".jpg", ".jpeg", ".png", ".webp"}


def root() -> pathlib.Path:
    return pathlib.Path(os.environ.get("ARTREF_ROOT") or (pathlib.Path.home() / "artrefs"))


def open_db() -> sqlite3.Connection:
    r = root()
    (r / "img").mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(r / "artref.db")
    con.execute("""create table if not exists refs(
        md5 text primary key,
        source text,          -- 图源直链
        page text,            -- 来源页 (归属与回查)
        artist text,
        tags text,
        score integer,
        width integer, height integer,
        local text,           -- img/ 下的文件名
        note text,
        added_at text)""")
    return con


def pick_ext(url: str) -> str:
    ext = pathlib.Path(urllib.parse.urlparse(url).path).suffix.lower()
    return ext if ext in OK_EXT else ""


def row_from_post(post: dict, min_score: int) -> dict | None:
    """Danbooru post → 入库行; 不合格返回 None (无直链/分级不对/分低/格式怪)。
    只收 rating=g (全年龄) — 参考库要能大大方方打开。"""
    url = post.get("file_url") or post.get("large_file_url") or ""
    if not url or not pick_ext(url):
        return None
    if post.get("rating") != "g":
        return None
    if int(post.get("score") or 0) < min_score:
        return None
    if not post.get("md5"):
        return None
    return {
        "md5": post["md5"],
        "source": url,
        "page": f"https://danbooru.donmai.us/posts/{post.get('id')}",
        "artist": post.get("tag_string_artist") or "",
        "tags": post.get("tag_string_general") or "",
        "score": int(post.get("score") or 0),
        "width": int(post.get("image_width") or 0),
        "height": int(post.get("image_height") or 0),
    }


def has_tags(post: dict, require: list[str]) -> bool:
    """本地标签过滤: 匿名 API 限 2 个查询标签, 挤不下的条件在这里补刀。"""
    have = set((post.get("tag_string_general") or "").split())
    return all(t in have for t in require)


def insert_ref(con: sqlite3.Connection, row: dict, note: str = "") -> bool:
    """入库 (md5 去重)。已有返回 False。"""
    have = con.execute("select 1 from refs where md5=?", (row["md5"],)).fetchone()
    if have:
        return False
    con.execute(
        "insert into refs values (?,?,?,?,?,?,?,?,?,?,?)",
        (row["md5"], row["source"], row["page"], row["artist"], row["tags"],
         row["score"], row["width"], row["height"], row.get("local") or "",
         note, time.strftime("%Y-%m-%d %H:%M")))
    con.commit()
    return True


def _fetch(url: str, binary: bool = False, timeout: int = 60):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
    return data if binary else json.loads(data.decode("utf-8"))


def _download(con: sqlite3.Connection, row: dict, note: str) -> bool:
    if not insert_ref(con, {**row, "local": ""}, note):
        return False
    name = row["md5"] + pick_ext(row["source"])
    try:
        data = _fetch(row["source"], binary=True)
        (root() / "img" / name).write_bytes(data)
        con.execute("update refs set local=? where md5=?", (name, row["md5"]))
        con.commit()
        return True
    except Exception as e:  # 图挂了不挡整批: 行留着 (page 可回查), local 空
        print(f"  ⚠️ 下载失败 {row['page']}: {e}")
        return True


def crawl(tags: str, limit: int, min_score: int, require: list[str] | None = None,
          start_page: int = 1, max_pages: int = 20) -> None:
    """匿名深页采集法: 最新页分数没长熟, 翻到几百页外(半年前)按 min_score 本地筛。
    产出率约 1%/页, 慢但不求人; 快路是带 API key 的源 (等注册)。"""
    con = open_db()
    added = seen = fails = 0
    for page in range(start_page, start_page + max_pages):
        if added >= limit:
            break
        q = urllib.parse.urlencode({"tags": tags, "limit": 100, "page": page})
        try:
            posts = _fetch(f"{API}?{q}")
            fails = 0
        except Exception as e:
            fails += 1
            print(f"⚠️ 拉列表失败 (page {page}): {e}" + ("" if fails < 5 else " — 连败5页收工"))
            if fails >= 5:
                break
            time.sleep(3)   # 深页 500 是间歇性的, 歇口气跳过这页
            continue
        if not posts:
            break
        for p in posts:
            if added >= limit:
                break
            seen += 1
            if require and not has_tags(p, require):
                continue
            row = row_from_post(p, min_score)
            if row and _download(con, row, note=f"crawl:{tags}"):
                added += 1
                print(f"  + [{row['score']}] {row['artist'] or '?'} {row['page']}")
            time.sleep(0.6)   # 客气: 官方建议 ~1req/s
    print(f"✓ 入库 {added} 张 (扫过 {seen} 条) → {root()}")


def add(urls: list[str], note: str) -> None:
    con = open_db()
    n = 0
    for u in urls:
        try:
            data = _fetch(u, binary=True)
        except Exception as e:
            print(f"⚠️ 取不到 {u}: {e}")
            continue
        md5 = hashlib.md5(data).hexdigest()
        ext = pick_ext(u) or ".jpg"
        row = {"md5": md5, "source": u, "page": u, "artist": "", "tags": "manual",
               "score": 0, "width": 0, "height": 0, "local": md5 + ext}
        if insert_ref(con, row, note or "manual"):
            (root() / "img" / (md5 + ext)).write_bytes(data)
            n += 1
            print(f"  + {u}")
        else:
            print(f"  = 已在库里 {u}")
    print(f"✓ 手动入库 {n} 张 → {root()}")


def gallery() -> None:
    con = open_db()
    rows = con.execute(
        "select local, artist, tags, score, page, note from refs "
        "where local != '' order by added_at desc, score desc").fetchall()
    cards = "\n".join(
        f'<figure data-t="{(a or "") + " " + (t or "") + " " + (n or "")}">'
        f'<img src="img/{l}" loading="lazy">'
        f'<figcaption>[{s}] {a or "?"} · <a href="{p}" target="_blank">来源</a></figcaption></figure>'
        for l, a, t, s, p, n in rows)
    html = f"""<!doctype html><meta charset="utf-8"><title>审美参考库</title>
<style>body{{background:#14141c;color:#dde;font:14px/1.5 sans-serif;margin:16px}}
input{{width:100%;padding:8px;margin-bottom:12px;background:#1e1e2a;color:#dde;border:1px solid #333}}
main{{columns:4 260px;gap:10px}}figure{{break-inside:avoid;margin:0 0 10px}}
img{{width:100%;border-radius:6px}}figcaption{{font-size:11px;color:#889}}a{{color:#8ea2ff}}</style>
<input id="q" placeholder="按 标签/作者/备注 过滤, 空格分词" oninput="
  const ws=this.value.toLowerCase().split(/\\s+/).filter(Boolean);
  document.querySelectorAll('figure').forEach(f=>{{
    const t=f.dataset.t.toLowerCase();
    f.style.display=ws.every(w=>t.includes(w))?'':'none'}})">
<main>{cards}</main>
<p style="color:#667">共 {len(rows)} 张 · 内部审美参考, 不再分发 · 每张保留来源与作者</p>"""
    out = root() / "gallery.html"
    out.write_text(html, encoding="utf-8")
    print(f"✓ {out} ({len(rows)} 张)")


def stats() -> None:
    con = open_db()
    total = con.execute("select count(*) from refs").fetchone()[0]
    artists = con.execute(
        "select artist, count(*) c from refs where artist!='' "
        "group by artist order by c desc limit 10").fetchall()
    print(f"库里 {total} 张 · 位置 {root()}")
    for a, c in artists:
        print(f"  {c:3d}  {a}")


def main() -> None:
    ap = argparse.ArgumentParser(description="审美参考例库")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("crawl")
    c.add_argument("--tags", required=True,
                   help='查询标签, 匿名限2个可数标签, 如 "1boy order:score"')
    c.add_argument("--limit", type=int, default=60)
    c.add_argument("--min-score", type=int, default=40)
    c.add_argument("--require", default="",
                   help='本地必含标签(空格分隔), 挤不进查询的条件放这里, 如 "solo"')
    c.add_argument("--start-page", type=int, default=1, help="深页采集起始页")
    c.add_argument("--max-pages", type=int, default=20)
    a = sub.add_parser("add")
    a.add_argument("urls", nargs="+")
    a.add_argument("--note", default="")
    sub.add_parser("gallery")
    sub.add_parser("stats")
    args = ap.parse_args()
    if args.cmd == "crawl":
        crawl(args.tags, args.limit, args.min_score, args.require.split() or None,
              args.start_page, args.max_pages)
    elif args.cmd == "add":
        add(args.urls, args.note)
    elif args.cmd == "gallery":
        gallery()
    elif args.cmd == "stats":
        stats()


if __name__ == "__main__":
    main()
