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

# 🧹 删掉的文件也要真的消失 (2026-08-04)。tar -x 只覆盖不删除 —— 于是仓库里删掉的
# 文件在服务器上【永生】(实弹: phone_mock.py 靠手动 ssh 清; 体检又查出 30 个孤儿,
# 其中 app/runtime.py 是 439KB 的旧副本, 还有一个嵌套的 app/app/ 包 —— 服务器上同时
# 躺着两份 runtime.py, import 错一次就是找不着北的事故)。
#
# ⚠️ 为什么【不】用 rsync --delete: 服务器上有大量 git 里没有、且绝不能删的东西 ——
# .venv(删了服务当场死)、data/(生产库)、.env(密钥)、metrics.jsonl(全部遥测史)、
# daily_check.last(哨兵)、各种 *_proposals.json。靠排除清单挡, 漏一个就是事故,
# 而且新出现的服务器侧产物没人会想起来加进清单。
#
# 改用【清单比对】: 只删「上一次部署放上去、这一次不再有」的文件。没进过清单的
# 东西一辈子不会被碰 —— 安全性不依赖任何人记得维护排除列表。
MANIFEST=/opt/linguisplay/.deploy-manifest
STAGE=/opt/deploy-staging
rm -rf "$STAGE"; mkdir -p "$STAGE"
git -C /opt/git/linguisplay.git archive master apps/api deploy \
  | tar -x -C "$STAGE" --exclude='apps/api/app/static/scene'

NEW="$(mktemp)"
(cd "$STAGE" && find . -type f | sed 's|^\./||' | sort) > "$NEW"
if [ -f "$MANIFEST" ]; then
  # 上次有、这次没有 = 这次部署删掉的文件
  comm -23 "$MANIFEST" "$NEW" | while IFS= read -r f; do
    [ -n "$f" ] || continue
    case "$f" in apps/api/app/static/scene/*) continue ;; esac   # 铁律: 美术不碰
    if [ -f "/opt/linguisplay/$f" ]; then
      echo "🧹 删除 $f"
      rm -f "/opt/linguisplay/$f"
    fi
  done
else
  echo "ℹ️  首次部署无清单可比 —— 存量孤儿要人工清一次 (之后自动)"
fi

cp -a "$STAGE"/. /opt/linguisplay/
mv -f "$NEW" "$MANIFEST"
rm -rf "$STAGE"
# 🩺 每日巡检必须活着: git archive 按 git 模式覆写文件 — daily_check.sh 若在 git 里
# 不是 100755, 这里每次部署都会剥掉手工 chmod 的 +x (实案: cron 因此静默死 9 天,
# 夜巡从未在生产跑过)。部署即校正 + 哨兵断更就喊。
chmod +x /opt/linguisplay/apps/api/daily_check.sh
LAST=/opt/linguisplay/apps/api/daily_check.last
if [ ! -f "$LAST" ] || [ -n "$(find "$LAST" -mtime +2 2>/dev/null)" ]; then
  echo "⚠️  daily_check 哨兵断更 (${LAST}: $(cat "$LAST" 2>/dev/null || echo 无)) — 查 crontab 与 +x!"
fi
bash /opt/linguisplay/deploy/_restart.sh
