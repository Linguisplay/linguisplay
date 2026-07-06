# -*- coding: utf-8 -*-
"""📈 引擎观测层: append-only JSONL metrics — every LLM call and every turn leaves one
line, so "how is the engine behaving this week" is a query, not a feeling.

Lines:  {"ts": ..., "e": "llm",  "kind": "director|aux", "ok": true, "ms": 843, ...}
        {"ts": ..., "e": "turn", "run": "3e08fd61", "ms": 12040, "beats": 5, ...}

Fail-open by design: metrics must never break a turn (OSError swallowed); writes are
skipped entirely under pytest. Report: python metrics_report.py
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

PATH = Path(os.environ.get("LP_METRICS") or
            Path(__file__).resolve().parents[1] / "metrics.jsonl")


def log(event: str, **fields) -> None:
    if "PYTEST_CURRENT_TEST" in os.environ:
        return
    try:
        with open(PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": int(time.time()), "e": event, **fields},
                               ensure_ascii=False) + "\n")
    except OSError:
        pass
