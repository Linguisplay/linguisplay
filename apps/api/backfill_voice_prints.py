# -*- coding: utf-8 -*-
"""🗣 存量补票: 给没有语言指纹 (voice_print) 的存量角色批量起草提案。

两步走 (提案必须先给作者验收, 绝不直接落库):
  1. python backfill_voice_prints.py            → 干跑: 每个剧本一次 LLM 起草,
     提案打印成验收单, 【合并】进 voice_print_proposals.json (只更新本轮处理的剧本,
     其他剧本已验收的提案原样保留), 数据库一个字不动
  2. 作者验收/手改 JSON 后:
     python backfill_voice_prints.py --apply    → 只往【仍然为空】的 voice_print 里
     填提案 (作者已手填的绝不覆盖), 缝穿 Story 行 → 快照 → 各 run 的 pinned 副本

覆盖面: 存量角色不只在 Story 行——沙盒开局班底、涌现新角色、找人铸造的角色只活在
run 的 pinned 副本里 (Story 行常为空)。干跑同时扫 Story 行 + 快照 + 所有 run 副本,
按 id 去重, 这些「AI 生成的存量嘴」才补得上。

可选: --story 剧本标题 只处理一个剧本 (合并写, 不影响其他剧本);
      --file 换提案文件路径。
⚠️ --apply 会整列写 run.pinned_content。为避开与活跃对局的读改写竞态, 请在低峰期
   (或临时停服) 执行; 脚本已改为【每个 run 处理完立即 commit】把窗口压到最小。
"""
import argparse
import json
from pathlib import Path

from sqlalchemy.orm.attributes import flag_modified

from app.db import SessionLocal, init_db
from app.models import Run, Story, StorySnapshot

PROPOSALS = Path(__file__).resolve().parent / "voice_print_proposals.json"


def _needs_print(c: dict) -> bool:
    return (isinstance(c, dict)
            and str(c.get("name") or "").strip()
            and not str(c.get("voice_print") or "").strip())


def _richer(a: dict, b: dict) -> dict:
    """Between two copies of the same character id, keep the one with the fuller persona
    (pinned/snapshot copies may hold a richer or staler spec than the Story row)."""
    return a if len(str(a.get("persona_text") or "")) >= len(str(b.get("persona_text") or "")) else b


def _collect(db, s: Story) -> tuple[list[dict], int]:
    """Every character of THIS story that still lacks a voice_print — gathered across the
    Story row, its snapshots, and all its runs' pinned copies, deduped by id (richest
    persona wins). Returns (chars, skipped_idless). id-less legacy chars can't be stitched
    back by id, so they're skipped and counted (reported, never silently dropped)."""
    by_id: dict[str, dict] = {}
    skipped_idless = 0
    pools = [s.characters or []]
    for snap in db.query(StorySnapshot).filter(StorySnapshot.story_id == s.id).all():
        pools.append(((snap.content or {}).get("story") or {}).get("characters") or [])
    for r in db.query(Run).filter(Run.story_id == s.id).all():
        pools.append(((r.pinned_content or {}).get("story") or {}).get("characters") or [])
    for pool in pools:
        for c in pool:
            if not _needs_print(c):
                continue
            cid = str(c.get("id") or "").strip()
            if not cid:
                skipped_idless += 1
                continue
            by_id[cid] = _richer(by_id[cid], c) if cid in by_id else c
    return list(by_id.values()), skipped_idless


def _draft(llm, s: Story, chars: list[dict]) -> list[dict]:
    out = llm.generate({"voice_prints": True,
                        "language": s.language or "zh",
                        "world": (s.world_long or "")[:400],
                        "style": (s.style or "")[:160],
                        "characters": [{"name": c.get("name"), "role": c.get("role"),
                                        "persona": c.get("persona_text"),
                                        "eq_style": c.get("eq_style"),
                                        "examples": c.get("examples") or []}
                                       for c in chars]}) or {}
    # key by STRIPPED name both sides (studio stores names untrimmed); dup names → last wins
    # is unsafe, so drop the whole ambiguous name rather than pin A's print onto B's id.
    seen, dup = {}, set()
    for c in chars:
        nm = str(c.get("name") or "").strip()
        if nm in seen:
            dup.add(nm)
        seen[nm] = c
    prints = []
    for p in out.get("prints") or []:
        nm = str(p.get("name") or "").strip()
        vp = str(p.get("voice_print") or "").strip()[:60]
        if nm in dup:
            print(f"  ⚠ 《{s.title}》有重名角色「{nm}」，提案无法确定归属，跳过")
            continue
        c = seen.get(nm)
        if c and vp:
            prints.append({"id": c.get("id"), "name": nm, "voice_print": vp})
    return prints


def _fill(chars: list, wanted: dict[str, dict]) -> int:
    """Fill EMPTY voice_print by id, but only when the proposal's name still matches the
    target char's name — a pinned/snapshot copy the author later renamed (same id) must not
    be stamped with today's fingerprint for a now-different character. Authored/hand-fixed
    values are never touched. Returns count filled."""
    n = 0
    for c in chars or []:
        want = wanted.get(str(c.get("id") or ""))
        if not want or str(c.get("voice_print") or "").strip():
            continue
        if str(c.get("name") or "").strip() != str(want.get("name") or "").strip():
            print(f"  ⚠ id={c.get('id')} 现名「{c.get('name')}」与提案名「{want.get('name')}」不符，跳过")
            continue
        c["voice_print"] = want["voice_print"]
        n += 1
    return n


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="落库已验收的提案文件")
    ap.add_argument("--story", default="", help="只处理这个标题的剧本")
    ap.add_argument("--file", default=str(PROPOSALS), help="提案文件路径")
    args = ap.parse_args()
    init_db()
    db = SessionLocal()
    try:
        stories = db.query(Story).all()
        if args.story.strip():
            stories = [s for s in stories if s.title == args.story.strip()]

        if not args.apply:
            from app.engine.llm import get_llm
            llm = get_llm()
            # 🛡 合并不覆盖: 载入既有提案, 本轮只更新处理到的剧本, 其他剧本原样保留
            existing = {}
            fp = Path(args.file)
            if fp.exists():
                try:
                    existing = {x["story_id"]: x for x in json.loads(fp.read_text(encoding="utf-8"))}
                except Exception:
                    existing = {}
            total = 0
            for s in stories:
                need, skipped = _collect(db, s)
                if skipped:
                    print(f"《{s.title}》: {skipped} 个角色缺 id，无法按 id 缝合，已跳过")
                if not need:
                    continue
                prints = _draft(llm, s, need[:8])
                if not prints:
                    print(f"《{s.title}》: {len(need)} 张嘴缺指纹, 这轮没起出提案 (重跑可重试，不会覆盖其他剧本)")
                    continue
                existing[s.id] = {"story_id": s.id, "title": s.title, "prints": prints}
                total += len(prints)
                print(f"《{s.title}》")
                for p in prints:
                    print(f"  {p['name']}: {p['voice_print']}")
            fp.write_text(json.dumps(list(existing.values()), ensure_ascii=False, indent=1),
                          encoding="utf-8")
            print(f"\n干跑完毕 — 本轮 {total} 条新提案已合并进 {args.file}, 数据库未动。"
                  "验收/手改后用 --apply 落库。")
            return

        sheet = json.loads(Path(args.file).read_text(encoding="utf-8"))
        by_story = {x["story_id"]: {p["id"]: {"voice_print": p["voice_print"], "name": p.get("name", "")}
                                    for p in x["prints"] if p.get("id")}
                    for x in sheet}
        for s in stories:
            wanted = by_story.get(s.id)
            if not wanted:
                continue
            chars = list(s.characters or [])
            if _fill(chars, wanted):
                s.characters = chars
                flag_modified(s, "characters")
            db.commit()   # 🛡 每层落库即提交, 压缩与活跃对局的读改写竞态窗口
            for snap in db.query(StorySnapshot).filter(StorySnapshot.story_id == s.id).all():
                if snap.content and snap.content.get("story"):
                    if _fill(snap.content["story"].get("characters") or [], wanted):
                        flag_modified(snap, "content")
                    db.commit()
            filled_runs = 0
            for r in db.query(Run).filter(Run.story_id == s.id).all():
                if r.pinned_content and r.pinned_content.get("story"):
                    if _fill(r.pinned_content["story"].get("characters") or [], wanted):
                        flag_modified(r, "pinned_content")
                        filled_runs += 1
                    db.commit()   # 每个 run 独立提交 (#竞态窗口最小化)
            print(f"《{s.title}》: 指纹已缝入 Story 行 + 快照 + {filled_runs} 个存档副本")
        print("落库完成。")
    finally:
        db.close()


if __name__ == "__main__":
    main()
