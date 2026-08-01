#!/bin/bash
# 🩺 每日巡检: smoke gate + guard board + service/disk health → daily_check.log
# Installed as a root cron on the server (see crontab). Keeps the last ~800 lines.
cd /opt/linguisplay/apps/api || exit 1
export DATABASE_URL='sqlite+pysqlite:////opt/linguisplay/apps/api/data/linguisplay.db'
export PYTHONIOENCODING=utf-8
LOG=/opt/linguisplay/apps/api/daily_check.log
{
  echo "════════ $(date '+%F %T') ════════"
  echo "· service: $(systemctl is-active linguisplay)"
  echo "· disk: $(df -h / | awk 'NR==2 {print $5\" used, \"$4\" free\"}')"
  echo "· db: $(du -h data/linguisplay.db | cut -f1)"
  echo "── smoke ──"
  .venv/bin/python smoke_stories.py 2>&1 | tail -4
  echo "── guards (24h) ──"
  .venv/bin/python metrics_report.py --hours 24 2>&1 | tail -10
  echo "── 🌙 夜巡 (真玩家路径 × 体验判官, 每晚轮换 2 本 × 2 回合) ──"
  (set -a; . ./.env; set +a; QA_STORIES=2 QA_TURNS=2 timeout 600 .venv/bin/python qa_playtour.py 2>&1 | tail -16)
} >> "$LOG" 2>&1
tail -n 800 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
