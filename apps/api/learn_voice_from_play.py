# -*- coding: utf-8 -*-
"""🧠 从真实对局台词学角色的声音 (持续学习工作流 · Yi: 聊天方式是灵魂)。

风格库不是死的：角色在真实对局里【实际怎么说话】才是灵魂的真身。这个工具挖出每个
角色真说过的台词 → 让模型提炼 TA【实际】的语言指纹 + 给独特度打分(揪出雷同/大众脸) →
出提案单给作者验收 → --apply 更新回 voice_print。跑得越多、玩得越久，指纹越准。

两步走:
  1. python learn_voice_from_play.py [--story 标题] [--min-lines 6]
     干跑: 挖真实台词→提炼→打独特度分, 存 learned_voice_proposals.json, 库不动。
  2. python learn_voice_from_play.py --apply
     把验收过的学习结果【更新】进 voice_print (会覆盖旧值, 原值先备份)。

与 backfill_voice_prints.py 的分工: backfill 从人设【猜】初始指纹(填空); 本工具从真实
台词【学】真实指纹(refine, 可覆盖)。前者冷启动, 后者持续学习。
"""
import argparse
import json
import sys

sys.path.insert(0, ".")
from sqlalchemy.orm.attributes import flag_modified
from app.db import SessionLocal
from app.engine import qwen
from app.engine.llm import get_llm
from app.models import Beat, Run, Story

PROPOSALS = "learned_voice_proposals.json"
BACKUP = "learned_voice_backup.json"


def _lines_by_char(db, story: Story) -> dict[str, list[str]]:
    """每个具名角色在本剧本所有 run 里真说过的台词 (type=dialogue), 去重。"""
    names = {(c.get("name") or "").strip() for c in (story.characters or []) if (c.get("name") or "").strip()}
    run_ids = [r.id for r in db.query(Run.id).filter(Run.story_id == story.id).all()]
    if not run_ids or not names:
        return {}
    out: dict[str, list[str]] = {n: [] for n in names}
    seen: dict[str, set] = {n: set() for n in names}
    rows = (db.query(Beat.speaker_name, Beat.text)
            .filter(Beat.run_id.in_(run_ids), Beat.type == "dialogue")
            .order_by(Beat.seq.desc()).limit(4000).all())
    for sp, txt in rows:
        sp = (sp or "").strip()
        txt = (txt or "").strip()
        if sp in out and txt and txt not in seen[sp] and len(out[sp]) < 30:
            seen[sp].add(txt)
            out[sp].append(txt)
    return {n: ls for n, ls in out.items() if ls}


def _distill(llm, name: str, persona: str, lines: list[str]) -> dict:
    """让模型从真实台词提炼实际语言指纹 + 独特度分。降级返回 {}。"""
    sys_p = ("你是语言指纹分析师。下面是某角色在游戏里【真实说过的台词】。只输出JSON："
             '{"voice_print":"≤50字 从台词里提炼的说话规律(句长/口头禅/用词癖/标点脾气)，'
             '只从台词来，不发明","distinct":1到5的整数(5=一句就能认出是TA，1=大众脸、'
             '谁都能说、和别人撞腔),"note":"≤20字 一句点评(比如: 口头禅鲜明 / 太扁平没记忆点)"}。'
             "不用破折号。")
    u = json.dumps({"角色": name, "人设": (persona or "")[:120],
                    "真实台词": lines[:30]}, ensure_ascii=False)
    try:
        resp = qwen._post_chat(llm._url, llm._key,
                               {"model": llm._model, "temperature": 0.3, "max_tokens": 300,
                                "messages": [{"role": "system", "content": sys_p},
                                             {"role": "user", "content": u}],
                                "response_format": {"type": "json_object"}},
                               timeout=30, kind="learn_voice")
        d = json.loads(resp.json()["choices"][0]["message"]["content"] or "{}")
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _apply_fill(chars: list, learned: dict[str, str]) -> int:
    n = 0
    for c in chars or []:
        v = learned.get(str(c.get("id") or ""))
        if v:
            c["voice_print"] = v
            n += 1
    return n


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--story", default="")
    ap.add_argument("--min-lines", type=int, default=6, help="至少几句真台词才学(默认6)")
    ap.add_argument("--file", default=PROPOSALS)
    args = ap.parse_args()
    db = SessionLocal()
    try:
        stories = db.query(Story).all()
        if args.story.strip():
            stories = [s for s in stories if s.title == args.story.strip()]

        if not args.apply:
            llm = get_llm()
            sheet = []
            for s in stories:
                by_char = _lines_by_char(db, s)
                by_name = {(c.get("name") or "").strip(): c for c in (s.characters or [])}
                learned = []
                for nm, lines in by_char.items():
                    if len(lines) < args.min_lines:
                        continue
                    c = by_name.get(nm)
                    if not c or not c.get("id"):
                        continue
                    d = _distill(llm, nm, c.get("persona_text"), lines)
                    vp = str(d.get("voice_print") or "").strip()[:60]
                    if not vp:
                        continue
                    learned.append({"id": c["id"], "name": nm,
                                    "current_vp": (c.get("voice_print") or "")[:60],
                                    "learned_vp": vp, "distinct": d.get("distinct"),
                                    "note": str(d.get("note") or "")[:40],
                                    "lines_used": len(lines)})
                if learned:
                    sheet.append({"story_id": s.id, "title": s.title, "learned": learned})
                    print(f"《{s.title}》")
                    for L in learned:
                        flag = "⚠️扁平" if isinstance(L["distinct"], int) and L["distinct"] <= 2 else "  "
                        print(f"  {flag} {L['name']}(独特{L['distinct']}/{L['lines_used']}句): {L['learned_vp'][:38]}  «{L['note']}»")
            json.dump(sheet, open(args.file, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            flat = sum(1 for x in sheet for L in x["learned"] if isinstance(L["distinct"], int) and L["distinct"] <= 2)
            print(f"\n干跑完毕 — {sum(len(x['learned']) for x in sheet)} 个角色已学, 其中 {flat} 个扁平/雷同待救; "
                  f"存 {args.file}, 库未动。验收/手改后 --apply。")
            return

        sheet = json.loads(open(args.file, encoding="utf-8").read())
        by_story = {x["story_id"]: {L["id"]: L["learned_vp"] for L in x["learned"] if L.get("id") and L.get("learned_vp")}
                    for x in sheet}
        backup = {}
        for s in stories:
            want = by_story.get(s.id)
            if not want:
                continue
            for c in (s.characters or []):
                if c.get("id") in want:
                    backup[c["id"]] = c.get("voice_print", "")
            chars = list(s.characters or [])
            if _apply_fill(chars, want):
                s.characters = chars
                flag_modified(s, "characters")
            db.commit()
            hit = 0
            for r in db.query(Run).filter(Run.story_id == s.id).all():
                pc = (r.pinned_content or {}).get("story")
                if pc and pc.get("characters"):
                    if _apply_fill(pc["characters"], want):
                        flag_modified(r, "pinned_content"); hit += 1
                    db.commit()
            print(f"《{s.title}》: 学到的指纹已更新 Story 行 + {hit} 个存档副本")
        json.dump(backup, open(BACKUP, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"落库完成。原 voice_print 已备份 → {BACKUP}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
