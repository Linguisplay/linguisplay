# -*- coding: utf-8 -*-
"""One-off 加餐 (拆向, Yi 拍板): 存量 run 的 npc_rel 从 ties 恢复方向。
懒升级只会把老档对称复制 (两方向同值同词), 作者在 ties 里写的不对等
(情同父子 vs 亲信眼线) 恢复不回来 — 本补丁对【没演化过 (log 空)】的边,
按钉住内容里的 ties 重写方向视图; 演化过的边一律不碰。

Run ON THE SERVER:
    cd /opt/linguisplay/apps/api && \
      PYTHONIOENCODING=utf-8 LP_DB=data/linguisplay.db .venv/bin/python patch_npc_dir.py
"""
import json
import os
import sqlite3

DB = os.environ.get("LP_DB", "dev.db")
TITLES = ["九龙城寨·狗笼", "九龙城寨·龙头"]


def _key(a, b):
    return "|".join(sorted([a or "", b or ""]))


def _fix(state, chars) -> int:
    web = state.get("npc_rel") or {}
    ids = {c.get("id") for c in chars}
    fixed = 0
    for c in chars:
        cid = c.get("id")
        for t in (c.get("ties") or []):
            other = t.get("char_id")
            if not cid or other not in ids or other == cid:
                continue
            k = _key(cid, other)
            e = web.get(k)
            if not e or (e.get("log") or []):
                continue   # 没这条边不造 / 演化过不碰
            try:
                stance = max(-2, min(2, int(t.get("stance") or 0)))
            except (TypeError, ValueError):
                continue
            if "ab" not in e:   # 老形状先升双向
                v = {"stance": int(e.get("stance") or 0), "label": e.get("label")}
                e = {"ab": dict(v), "ba": dict(v), "log": list(e.get("log") or [])}
            dk = "ab" if cid == k.split("|", 1)[0] else "ba"
            want = {"stance": stance, "label": (t.get("label") or "").strip() or None}
            if e.get(dk) != want:
                e[dk] = want
                fixed += 1
            web[k] = e
    state["npc_rel"] = web
    return fixed


def main() -> None:
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    for title in TITLES:
        row = db.execute("select id from stories where title=?", (title,)).fetchone()
        if not row:
            print(f"! not found: {title}")
            continue
        n_runs = n_fix = 0
        for r in db.execute("select id, state, pinned_content from runs where story_id=?",
                            (row["id"],)).fetchall():
            if not r["state"] or not r["pinned_content"]:
                continue
            st = json.loads(r["state"])
            chars = ((json.loads(r["pinned_content"]) or {}).get("story") or {}).get("characters") or []
            fixed = _fix(st, chars)
            if fixed:
                db.execute("update runs set state=? where id=?",
                           (json.dumps(st, ensure_ascii=False), r["id"]))
                n_runs += 1
                n_fix += fixed
        print(f"✓ {title}: {n_runs} run(s), {n_fix} direction(s) restored")
    db.commit()
    db.close()


if __name__ == "__main__":
    main()
