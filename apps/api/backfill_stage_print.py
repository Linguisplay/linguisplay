# -*- coding: utf-8 -*-
"""🎬 存量补表演指纹: 给没有表演指纹的角色批量起草 (行动节奏/感官侧重/情感表达形式)。

和 backfill_voice_prints.py 同构、同哲学: 引擎从角色人设【自动】起草表演指纹三维,
提案先给作者验收, 再 --apply 落库。让"配表演指纹"从"手做"变成"引擎做"。
(同一套 _stage_prints 引擎方法也给 Studio「AI补全表演指纹」按钮用。)

两步走:
  1. python backfill_stage_print.py [--story 标题]
     干跑: 每剧本一次 LLM 起草 → 验收单 → 合并进 stage_print_proposals.json, 库不动。
  2. python backfill_stage_print.py --apply
     只往【仍为空】的三维填提案 (作者已填的不覆盖), 缝穿 Story行→快照→各 run 副本。
"""
import argparse
import json
from pathlib import Path

from sqlalchemy.orm.attributes import flag_modified

from app.db import SessionLocal
from app.models import Run, Story, StorySnapshot

PROPOSALS = Path(__file__).resolve().parent / "stage_print_proposals.json"
DIMS = ("act_pace", "sense_focus", "emote_form")


def _needs_print(c: dict) -> bool:
    return (isinstance(c, dict) and str(c.get("name") or "").strip()
            and not any(str(c.get(d) or "").strip() for d in DIMS))


def _richer(a: dict, b: dict) -> dict:
    return a if len(str(a.get("persona_text") or "")) >= len(str(b.get("persona_text") or "")) else b


def _collect(db, s: Story) -> tuple[list[dict], int]:
    """每个仍缺表演指纹的具名角色 — Story行+快照+所有 run 副本, 按 id 去重 (人设最全者胜)。
    id-less 老角色无法按 id 缝合, 跳过并计数 (报出来, 不静默)。"""
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
    # 全集去重名 (重名无法确定归属, 整个弃)
    seen, dup = {}, set()
    for c in chars:
        nm = str(c.get("name") or "").strip()
        if nm in seen:
            dup.add(nm)
        seen[nm] = c
    prints = []
    # 分批 (每次≤8, 覆盖大于 8 人的班底; 单批内互不撞已由合同约束)
    for i in range(0, len(chars), 8):
        batch = chars[i:i + 8]
        out = llm.generate({"stage_prints": True,
                            "language": s.language or "zh",
                            "world": (s.world_long or "")[:400],
                            "style": (s.style or "")[:160],
                            "characters": [{"name": c.get("name"), "role": c.get("role"),
                                            "persona": c.get("persona_text"),
                                            "voice_print": c.get("voice_print"),
                                            "examples": c.get("examples") or []}
                                           for c in batch]}) or {}
        for p in out.get("prints") or []:
            nm = str(p.get("name") or "").strip()
            dims = {d: str(p.get(d) or "").strip()[:40] for d in DIMS}
            if nm in dup:
                print(f"  ⚠ 《{s.title}》有重名角色「{nm}」，无法确定归属，跳过")
                continue
            c = seen.get(nm)
            if c and any(dims.values()):
                prints.append({"id": c.get("id"), "name": nm, **dims})
    return prints


def _fill(chars: list, wanted: dict[str, dict]) -> int:
    """按 id 填【仍为空】的三维, 且提案名与目标现名一致才填 (改过名的历史副本不误盖)。
    逐维独立: 已填的维度不动, 只补空维。返回改动的角色数。"""
    n = 0
    for c in chars or []:
        want = wanted.get(str(c.get("id") or ""))
        if not want:
            continue
        if str(c.get("name") or "").strip() != str(want.get("name") or "").strip():
            print(f"  ⚠ id={c.get('id')} 现名「{c.get('name')}」与提案名「{want.get('name')}」不符，跳过")
            continue
        changed = False
        for d in DIMS:
            if want.get(d) and not str(c.get(d) or "").strip():
                c[d] = want[d]
                changed = True
        if changed:
            n += 1
    return n


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--story", default="")
    ap.add_argument("--file", default=str(PROPOSALS))
    args = ap.parse_args()
    db = SessionLocal()
    try:
        stories = db.query(Story).all()
        if args.story.strip():
            stories = [s for s in stories if s.title == args.story.strip()]

        if not args.apply:
            from app.engine.llm import get_llm
            llm = get_llm()
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
                    print(f"《{s.title}》: {skipped} 个角色缺 id，无法缝合，已跳过")
                if not need:
                    continue
                prints = _draft(llm, s, need[:8])
                if not prints:
                    print(f"《{s.title}》: {len(need)} 个缺表演指纹, 这轮没起出 (重跑可重试, 不覆盖其他剧本)")
                    continue
                existing[s.id] = {"story_id": s.id, "title": s.title, "prints": prints}
                total += len(prints)
                print(f"《{s.title}》")
                for p in prints:
                    print(f"  {p['name']}: 节奏={p.get('act_pace','')} | 感官={p.get('sense_focus','')} | 表达={p.get('emote_form','')}")
            fp.write_text(json.dumps(list(existing.values()), ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"\n干跑完毕 — 本轮 {total} 个角色已起草, 合并进 {args.file}, 库未动。验收/手改后 --apply。")
            return

        sheet = json.loads(Path(args.file).read_text(encoding="utf-8"))
        by_story = {x["story_id"]: {p["id"]: {**{d: p.get(d, "") for d in DIMS}, "name": p.get("name", "")}
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
            db.commit()
            for snap in db.query(StorySnapshot).filter(StorySnapshot.story_id == s.id).all():
                if snap.content and snap.content.get("story"):
                    if _fill(snap.content["story"].get("characters") or [], wanted):
                        flag_modified(snap, "content")
                    db.commit()
            hit = 0
            for r in db.query(Run).filter(Run.story_id == s.id).all():
                if r.pinned_content and r.pinned_content.get("story"):
                    if _fill(r.pinned_content["story"].get("characters") or [], wanted):
                        flag_modified(r, "pinned_content"); hit += 1
                    db.commit()
            print(f"《{s.title}》: 表演指纹已缝入 Story行 + 快照 + {hit} 个存档副本")
        print("落库完成。")
    finally:
        db.close()


if __name__ == "__main__":
    main()
