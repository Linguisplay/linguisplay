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
    # 🎯 品味库三列 (Yi: 库的单位是判断不是图): verdict love/reject/空=候选,
    # facets 空格分隔的维度词, comment 一句为什么。幂等迁移。
    cols = {row[1] for row in con.execute("pragma table_info(refs)")}
    for col in ("verdict", "facets", "comment"):
        if col not in cols:
            con.execute(f"alter table refs add column {col} text default ''")
    con.commit()
    return con


def rate(con: sqlite3.Connection, md5: str, verdict: str,
         facets: str = "", comment: str = "") -> bool:
    """落一次判断。verdict 只认 love/reject/'' (清空回候选)。"""
    if verdict not in ("love", "reject", ""):
        return False
    cur = con.execute(
        "update refs set verdict=?, facets=?, comment=? where md5=?",
        (verdict, facets.strip()[:200], comment.strip()[:300], md5))
    con.commit()
    return cur.rowcount > 0


def taste_export() -> str:
    """把全部判断蒸馏成 taste.md: 正面词表 + 忌清单 (按出现频次排序), 附代表例。"""
    con = open_db()
    import collections
    pos: collections.Counter = collections.Counter()
    neg: collections.Counter = collections.Counter()
    pos_c, neg_c = [], []
    for v, f, c, page in con.execute(
            "select verdict, facets, comment, page from refs where verdict != ''"):
        bag = pos if v == "love" else neg
        for w in (f or "").split():
            bag[w] += 1
        if (c or "").strip():
            (pos_c if v == "love" else neg_c).append((c.strip(), page))
    n_love = con.execute("select count(*) from refs where verdict='love'").fetchone()[0]
    n_rej = con.execute("select count(*) from refs where verdict='reject'").fetchone()[0]
    lines = [f"# 🎯 品味库蒸馏 (❤️{n_love} / ❌{n_rej})",
             "", "由品鉴台的判断聚合而来; 喂画风圣经与生图 prompt 用。", "",
             "## 要 (按判断次数)"]
    lines += [f"- {w} ×{n}" for w, n in pos.most_common()] or ["- (还没有正面判断)"]
    lines += ["", "## 忌 (按判断次数)"]
    lines += [f"- {w} ×{n}" for w, n in neg.most_common()] or ["- (还没有反例判断)"]
    lines += ["", "## 好例评语"]
    lines += [f"- {c}  ({p})" for c, p in pos_c[:30]] or ["- 无"]
    lines += ["", "## 反例评语"]
    lines += [f"- {c}  ({p})" for c, p in neg_c[:30]] or ["- 无"]
    out = root() / "taste.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(out)


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
        "insert into refs (md5,source,page,artist,tags,score,width,height,local,note,added_at)"
        " values (?,?,?,?,?,?,?,?,?,?,?)",
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


_FACETS = ["构图", "光影", "脸", "发", "服装质感", "氛围", "色彩", "笔触"]


def serve(port: int = 8787) -> None:
    """🎯 品鉴台: 本地网页一张张过图。← 淘汰 / → 收藏, 点维度, 写一句为什么。
    判断直接落 SQLite; 判完自动出下一张 (未判定的先来)。"""
    import http.server
    import socketserver

    con = open_db()

    def queue() -> list[dict]:
        rows = con.execute(
            "select md5, local, artist, tags, score, page, verdict, facets, comment "
            "from refs where local != '' order by (verdict != ''), added_at desc").fetchall()
        keys = ("md5", "local", "artist", "tags", "score", "page",
                "verdict", "facets", "comment")
        return [dict(zip(keys, r)) for r in rows]

    page_html = """<!doctype html><meta charset="utf-8"><title>品鉴台</title>
<style>body{background:#14141c;color:#dde;font:15px/1.6 sans-serif;margin:0;display:flex;height:100vh}
#stage{flex:1;display:flex;align-items:center;justify-content:center;background:#0d0d13}
#stage img{max-width:100%;max-height:100vh}
#side{width:340px;padding:18px;display:flex;flex-direction:column;gap:10px}
button{background:#1e1e2a;color:#dde;border:1px solid #333;padding:8px 12px;border-radius:6px;cursor:pointer}
button.on{border-color:#ffd479;color:#ffd479}
#love{background:#2a3a1e}#reject{background:#3a1e1e}
textarea{background:#1e1e2a;color:#dde;border:1px solid #333;min-height:70px;padding:8px}
.muted{color:#889;font-size:12px}a{color:#8ea2ff}</style>
<div id="stage"><img id="im"></div>
<div id="side">
  <div id="meta" class="muted"></div>
  <div id="facets"></div>
  <textarea id="cm" placeholder="一句为什么 (可空)"></textarea>
  <div style="display:flex;gap:8px">
    <button id="reject" onclick="judge('reject')">❌ 淘汰 (←)</button>
    <button id="love" onclick="judge('love')">❤️ 收藏 (→)</button>
    <button onclick="skip()">跳过 (↓)</button>
  </div>
  <div id="prog" class="muted"></div>
  <div class="muted">键盘: ←❌ →❤️ ↓跳过 · 数字键 1~8 点维度 · 判断落库即生效</div>
</div>
<script>
const FACETS = %FACETS%;
let Q = [], i = 0, picked = new Set();
function render(){
  const it = Q[i]; if(!it){ document.getElementById('meta').textContent='都判完了 🎉'; return; }
  document.getElementById('im').src = '/img/' + it.local;
  document.getElementById('meta').innerHTML =
    `[${it.score}] ${it.artist||'?'} · <a href="${it.page}" target="_blank">来源</a>` +
    (it.verdict ? ` · 已判:${it.verdict==='love'?'❤️':'❌'}` : '');
  picked = new Set((it.facets||'').split(' ').filter(Boolean));
  document.getElementById('cm').value = it.comment || '';
  document.getElementById('facets').innerHTML = FACETS.map((f,n) =>
    `<button class="${picked.has(f)?'on':''}" onclick="tog('${f}')">${n+1} ${f}</button>`).join(' ');
  document.getElementById('prog').textContent =
    `第 ${i+1}/${Q.length} 张 · 待判 ${Q.filter(x=>!x.verdict).length}`;
}
function tog(f){ picked.has(f) ? picked.delete(f) : picked.add(f); render0(); }
function render0(){ const it=Q[i]; it.facets=[...picked].join(' '); render(); }
async function judge(v){
  const it = Q[i]; if(!it) return;
  it.verdict = v; it.facets = [...picked].join(' ');
  it.comment = document.getElementById('cm').value;
  await fetch('/rate', {method:'POST', body: JSON.stringify(it)});
  skip();
}
function skip(){ i = Math.min(i+1, Q.length); render(); }
document.addEventListener('keydown', e => {
  if(e.target.tagName === 'TEXTAREA') return;
  if(e.key === 'ArrowLeft') judge('reject');
  else if(e.key === 'ArrowRight') judge('love');
  else if(e.key === 'ArrowDown') skip();
  else if(e.key >= '1' && e.key <= '8') tog(FACETS[+e.key-1]);
});
fetch('/queue').then(r=>r.json()).then(d=>{ Q=d; render(); });
</script>"""

    class H(http.server.BaseHTTPRequestHandler):
        def _send(self, body: bytes, ctype: str = "text/html; charset=utf-8"):
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/":
                self._send(page_html.replace("%FACETS%", json.dumps(_FACETS)).encode())
            elif self.path == "/queue":
                self._send(json.dumps(queue()).encode(), "application/json")
            elif self.path.startswith("/img/"):
                f = root() / "img" / pathlib.Path(self.path[5:]).name
                if f.exists():
                    self._send(f.read_bytes(), "image/jpeg")
                else:
                    self.send_error(404)
            else:
                self.send_error(404)

        def do_POST(self):
            if self.path != "/rate":
                return self.send_error(404)
            d = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            ok = rate(con, d.get("md5") or "", d.get("verdict") or "",
                      d.get("facets") or "", d.get("comment") or "")
            self._send(json.dumps({"ok": ok}).encode(), "application/json")

        def log_message(self, *a):
            pass

    with socketserver.TCPServer(("127.0.0.1", port), H) as srv:
        print(f"🎯 品鉴台开在 http://127.0.0.1:{port} — Ctrl+C 收摊")
        srv.serve_forever()


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
    s = sub.add_parser("serve", help="品鉴台 (本地网页判图)")
    s.add_argument("--port", type=int, default=8787)
    sub.add_parser("taste", help="判断蒸馏成 taste.md")
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
    elif args.cmd == "serve":
        serve(args.port)
    elif args.cmd == "taste":
        print("✓", taste_export())


if __name__ == "__main__":
    main()
