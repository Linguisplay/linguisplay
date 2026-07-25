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
bash /opt/linguisplay/deploy/_restart.sh
