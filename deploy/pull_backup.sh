#!/usr/bin/env bash
# 🛟 异地备份【拉取】—— 在【本机】跑, 不在服务器上跑。
#
#   bash deploy/pull_backup.sh
#
# 为什么是「拉」不是「推」: 服务器上不放任何能触达异地副本的凭据。服务器被拿下时,
# 攻击者删得掉 /opt/backups (那和生产库在同一块盘), 但删不掉这边的副本。
#
# 服务器侧的 backup.sh 已经在每天 04:30 出一份 db.gz (用 sqlite3 backup API, 正确
# 处理 WAL —— 千万别改成 cp .db, 那样会丢最近未 checkpoint 的写入)。这个脚本只负责
# 把它搬到第二台机器上, 并且【验一遍能不能真的打开】。备份没验过 = 没有备份。
#
# ⚠️ 不拉 scene.tgz: 已经 153MB 且每周涨 25~35MB, 而出口只有 ~110KB/s ——
#    满速也要 23 分钟, 期间游戏基本不可玩。美术资产走 COS 内网同步, 是另一件事。
set -u

REMOTE="${LP_REMOTE:-persona}"
SRC="/opt/backups/linguisplay"
DEST="${LP_BACKUP_DIR:-$HOME/lp-backups}"
KEEP_DAILY=14
KEEP_WEEKLY=8

mkdir -p "$DEST"
STAMP="$(date +%Y%m%d)"
DB="linguisplay-${STAMP}.db.gz"

echo "== 拉取 ${DB} =="
if ! scp -q "${REMOTE}:${SRC}/${DB}" "${DEST}/${DB}.part"; then
  echo "❌ 拉取失败: ${REMOTE}:${SRC}/${DB} 取不到 (服务器的 backup.sh 今天跑了吗?)"
  rm -f "${DEST}/${DB}.part"
  exit 1
fi

# 先验完整性再转正 —— 半截文件绝不许占用正式名字
if ! gzip -t "${DEST}/${DB}.part" 2>/dev/null; then
  echo "❌ gzip 校验不过: 传输中断或源文件损坏"
  rm -f "${DEST}/${DB}.part"
  exit 1
fi
mv -f "${DEST}/${DB}.part" "${DEST}/${DB}"

# 🔍 真的打得开吗: 解出来数一遍行。备份的意义是能恢复, 不是文件在那儿。
TMP="${DEST}/.verify.db"
gzip -dc "${DEST}/${DB}" > "$TMP" 2>/dev/null
# 路径当参数传, 不拼进源码 —— Windows 下的反斜杠/盘符拼进字符串就是一场引号灾难
ROWS="$(python -c '
import sqlite3, sys
try:
    c = sqlite3.connect(sys.argv[1])
    r = c.execute("select count(*) from runs").fetchone()[0]
    b = c.execute("select count(*) from beats").fetchone()[0]
    print(r, b)
except Exception as e:
    print("ERR", e); sys.exit(1)
' "$TMP" 2>&1)"
rm -f "$TMP"
case "$ROWS" in
  ERR*) echo "❌ 备份打不开: $ROWS"; exit 1 ;;
esac
set -- $ROWS
echo "✓ 可恢复: runs=$1 beats=$2  ($(du -h "${DEST}/${DB}" | cut -f1))"
if [ "$1" -lt 1 ] || [ "$2" -lt 1 ]; then
  echo "❌ 库是空的 —— 这不是一份有用的备份"
  exit 1
fi

# 📈 引擎遥测史: 既不在 git、也不在 push.sh、也不在 backup.sh —— 全仓唯一零备份的
# 数据。盘一坏, 所有守卫开枪/成本/回合耗时的历史归零。顺手带上 (才 1.8MB)。
scp -q "${REMOTE}:/opt/linguisplay/apps/api/metrics.jsonl" "${DEST}/metrics-${STAMP}.jsonl" \
  && echo "✓ metrics-${STAMP}.jsonl" || echo "⚠️  metrics.jsonl 没拉到 (不致命)"

# 周日那份留成周备, 与日备分开轮转
if [ "$(date +%u)" = "7" ]; then
  cp -f "${DEST}/${DB}" "${DEST}/weekly-${STAMP}.db.gz"
fi

# 轮转: 日备留 14 份, 周备留 8 份
ls -1t "${DEST}"/linguisplay-*.db.gz 2>/dev/null | tail -n +$((KEEP_DAILY + 1)) | xargs -r rm -f
ls -1t "${DEST}"/weekly-*.db.gz     2>/dev/null | tail -n +$((KEEP_WEEKLY + 1)) | xargs -r rm -f
ls -1t "${DEST}"/metrics-*.jsonl    2>/dev/null | tail -n +$((KEEP_DAILY + 1)) | xargs -r rm -f

# 🕯 新鲜度自查: 手动跑时一眼看到「最近一份是不是今天的」
NEWEST="$(ls -1t "${DEST}"/linguisplay-*.db.gz 2>/dev/null | head -1)"
echo "== 异地副本 $(ls -1 "${DEST}"/linguisplay-*.db.gz 2>/dev/null | wc -l) 份, 最新: $(basename "$NEWEST") =="
