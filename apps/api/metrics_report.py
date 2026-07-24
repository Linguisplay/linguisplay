# -*- coding: utf-8 -*-
"""📈 metrics.jsonl 一页报表: LLM 调用量/成功率/延迟分位 + 回合时长/beats + 审计事件榜.

Run:  python metrics_report.py [metrics.jsonl] [--hours N]
"""
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

path = Path(sys.argv[1]) if len(sys.argv) > 1 and not sys.argv[1].startswith("-") \
    else Path(__file__).parent / "metrics.jsonl"
hours = 0
if "--hours" in sys.argv:
    hours = int(sys.argv[sys.argv.index("--hours") + 1])
cutoff = time.time() - hours * 3600 if hours else 0

llm = defaultdict(list)   # kind -> [ms...]
llm_fail = Counter()
turns_ms, turns_beats = [], []
dice = Counter()
audit = Counter()

if not path.exists():
    sys.exit(f"no metrics file at {path}")
for ln in path.open(encoding="utf-8"):
    try:
        r = json.loads(ln)
    except ValueError:
        continue
    if cutoff and r.get("ts", 0) < cutoff:
        continue
    if r.get("e") == "llm":
        (llm[r.get("kind", "?")] if r.get("ok") else llm_fail).__class__  # noqa
        if r.get("ok"):
            llm[r.get("kind", "?")].append(int(r.get("ms", 0)))
        else:
            llm_fail[r.get("kind", "?")] += 1
    elif r.get("e") == "track":
        audit["track.conflict!"] += int(r.get("conflict") or 0)
        audit["track.update"] += 1 if r.get("booked") else 0
    elif r.get("e") == "turn":
        turns_ms.append(int(r.get("ms", 0)))
        turns_beats.append(int(r.get("beats", 0)))
        if r.get("dice"):
            dice[r["dice"]] += 1
        for a in (r.get("audit") or "").split(","):
            if a:
                audit[a] += 1


def pct(xs, p):
    if not xs:
        return 0
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(len(xs) * p / 100))]


span = f"最近{hours}小时" if hours else "全量"
print(f"── LLM 调用（{span}）──")
for k in sorted(llm):
    xs = llm[k]
    fails = llm_fail.get(k, 0)
    total = len(xs) + fails
    print(f"  {k:<10} {total:>5} 次  成功率 {len(xs) * 100 // max(1, total):>3}%  "
          f"p50 {pct(xs, 50)}ms  p95 {pct(xs, 95)}ms")
for k, v in llm_fail.items():
    if k not in llm:
        print(f"  {k:<10} {v:>5} 次  成功率   0%")

print(f"── 回合（{len(turns_ms)} 个）──")
if turns_ms:
    print(f"  时长 p50 {pct(turns_ms, 50)}ms  p95 {pct(turns_ms, 95)}ms   "
          f"beats 平均 {sum(turns_beats) / max(1, len(turns_beats)):.1f}")
if dice:
    print("  骰子:", "  ".join(f"{k}×{v}" for k, v in dice.most_common()))
if audit:
    print("── 审计事件榜（! = 驳回）──")
    for k, v in audit.most_common(16):
        print(f"  {k:<24} {v}")

# 🌱 生长三数 (Yi 拍板的验收标准): 产出率 5-8 回合/个、填无率、判官否决率 <30%。
# 否决率高 = 模型在预算压力下产垃圾, 判官在替节拍器擦屁股。
growth_ev = Counter()
for _gl in path.open(encoding="utf-8"):
    try:
        _gd = json.loads(_gl)
    except Exception:
        continue
    if _gd.get("e") == "growth" and _gd.get("ts", 0) >= cutoff:
        growth_ev[_gd.get("ev", "?")] += 1
if growth_ev:
    mints = growth_ev.get("mint", 0)
    blanks = growth_ev.get("blank", 0)
    rejects = growth_ev.get("reject", 0)
    dues = growth_ev.get("due", 0)
    print("── 🌱 生长三数 ──")
    print(f"  新实体 {mints} 个"
          + (f"（每 {len(turns_ms) / mints:.1f} 回合一个，目标 5-8）" if mints and turns_ms else ""))
    print(f"  填无率 {blanks * 100 // max(1, dues)}%（{blanks}/{dues} 次到期）")
    print(f"  判官否决率 {rejects * 100 // max(1, mints + rejects)}%（目标 <30%）")

# 🎼 节奏三数 (Spec 验收): 句长方差要散开、沉默率每十几轮一次量级、手机形状四档皆有
pace_ev = []
shape_ev = Counter()
for _pl in path.open(encoding="utf-8"):
    try:
        _pd = json.loads(_pl)
    except Exception:
        continue
    if _pd.get("ts", 0) < cutoff:
        continue
    if _pd.get("e") == "pace":
        pace_ev.append(_pd)
    elif _pd.get("e") == "phone_shape":
        shape_ev[_pd.get("shape", "?")] += 1
if pace_ev:
    import statistics
    _alld = [d for r in pace_ev for d in (r.get("dlens") or [])]
    _sil = sum(1 for r in pace_ev if r.get("silence"))
    _bands = Counter(r.get("band", "?") for r in pace_ev)
    print("── 🎼 节奏三数 ──")
    if len(_alld) > 1:
        print(f"  台词字数 均值 {statistics.mean(_alld):.0f}  标准差 {statistics.pstdev(_alld):.1f}"
              "（目标: 显著散开）")
    print(f"  沉默率 {_sil * 100 // max(1, len(pace_ev))}%（{_sil}/{len(pace_ev)}轮, 目标每十几轮一次）")
    print("  节奏带分布:", "  ".join(f"{k}×{v}" for k, v in _bands.most_common()))
if shape_ev:
    print("  手机形状:", "  ".join(f"{k}×{v}" for k, v in shape_ev.most_common()),
          "（目标: 四档皆有）")

# 🔫 守卫开枪榜: how often each engine LAW had to fire against the model. High rates
# name the law the model still breaks most — that's the next thing to strengthen.
GUARDS = ("pov.enforced", "heat.enforced", "power.enforced", "fate.forced",
          "move.narrated!", "frame.set!", "pos.set!", "track.conflict!")
fired = {g: audit.get(g, 0) for g in GUARDS if audit.get(g, 0)}
if fired and turns_ms:
    print("── 守卫开枪榜（次数 / 每百回合）──")
    for k, v in sorted(fired.items(), key=lambda x: -x[1]):
        print(f"  {k:<24} {v:>4}  {v * 100 / max(1, len(turns_ms)):.1f}/100turn")
