#!/usr/bin/env bash
# Deploy code to /opt/linguisplay from the bare repo (run ON the server):
#   ssh persona "bash /opt/linguisplay/deploy/deploy_from_git.sh"
#
# ⚠️ 铁律: NEVER let a code deploy touch app/static/scene — curated art (立绘验收图/
# 画风C背景) is uploaded straight to the server by ingest_tachie and git's copies are
# STALE BY DESIGN. 实弹 2026-07-25: a bare `git archive | tar -x` reverted cyclone/
# kf_* sprites to月前旧脸, 表情差分对不上底图, 玩家立刻看出"立绘乱了"。
# (Same rule as push.sh's data/ exclusion: server-curated truth never gets overwritten.)
set -e
git -C /opt/git/linguisplay.git archive master apps/api deploy \
  | tar -x -C /opt/linguisplay --exclude='apps/api/app/static/scene'
# 🩺 每日巡检必须活着: git archive 按 git 模式覆写文件 — daily_check.sh 若在 git 里
# 不是 100755, 这里每次部署都会剥掉手工 chmod 的 +x (实案: cron 因此静默死 9 天,
# 夜巡从未在生产跑过)。部署即校正 + 哨兵断更就喊。
chmod +x /opt/linguisplay/apps/api/daily_check.sh
LAST=/opt/linguisplay/apps/api/daily_check.last
if [ ! -f "$LAST" ] || [ -n "$(find "$LAST" -mtime +2 2>/dev/null)" ]; then
  echo "⚠️  daily_check 哨兵断更 (${LAST}: $(cat "$LAST" 2>/dev/null || echo 无)) — 查 crontab 与 +x!"
fi
bash /opt/linguisplay/deploy/_restart.sh
