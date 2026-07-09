# -*- coding: utf-8 -*-
"""Prune junk runs: a run in which the player never said a single line, older than
--age hours, is a misclick — not a save. (The pre-loading-overlay era minted piles
of them: world-forging took 10+ silent seconds, so players double-clicked new runs.)
Also sweeps orphan beats left behind by old seed wipes (bulk run deletes never
cascaded to beats).

Usage:  python cleanup_runs.py --dry     # report only
        python cleanup_runs.py           # delete (silent runs older than 1h)
        python cleanup_runs.py --age 24  # stricter age guard
"""
import argparse
from datetime import datetime, timedelta

from app.db import SessionLocal, init_db
from app.models import Beat, Run


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--age", type=float, default=1.0,
                    help="hours a silent run must be old before it counts as junk")
    ap.add_argument("--dry", action="store_true", help="report only, delete nothing")
    args = ap.parse_args()
    init_db()
    db = SessionLocal()
    try:
        cutoff = datetime.utcnow() - timedelta(hours=args.age)
        junk = []
        for r in db.query(Run).all():
            if r.created_at and r.created_at > cutoff:
                continue  # someone may literally just have opened it
            if any(b.author == "player" for b in r.beats):
                continue  # a real save — never touch
            junk.append(r)
        print(f"silent runs older than {args.age}h: {len(junk)}")
        for r in junk:
            print(f"  {r.id[:8]}  story={(r.story_id or '')[:8]}  created={r.created_at}")
        if not args.dry:
            for r in junk:
                db.query(Beat).filter(Beat.run_id == r.id).delete()
                db.delete(r)
            db.commit()
        # orphan beats: runs bulk-deleted by seeds never took their beats along
        live = {r.id for r in db.query(Run).all()}
        orphan_q = (db.query(Beat).filter(~Beat.run_id.in_(live)) if live
                    else db.query(Beat))
        n_orph = orphan_q.count()
        print(f"orphan beats: {n_orph}")
        if not args.dry and n_orph:
            orphan_q.delete(synchronize_session=False)
            db.commit()
        print("dry run — nothing deleted" if args.dry else "done")
    finally:
        db.close()


if __name__ == "__main__":
    main()
