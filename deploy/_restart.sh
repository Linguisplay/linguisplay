#!/usr/bin/env bash
# Restart LinguisPlay. Now managed by systemd (survives reboot + auto-restart on crash).
# Run after a code push:  ssh persona "bash /opt/linguisplay/deploy/_restart.sh"
set -e
systemctl restart linguisplay
sleep 2
echo "--- status ---"; systemctl --no-pager -l status linguisplay | head -6
# 🩺 轮询, 别用固定 sleep。实案 2026-08-06: 应用在 restart 后第 3 秒才 startup complete,
# 而 sleep 2 的 curl 第 2 秒就打过去被拒 → 报 "health failed", 生产其实一直是好的。
# 假警报比没有警报更坏: 下次真挂了会被当成又一次狼来了。
echo "--- health ---"
for i in $(seq 1 20); do
  OUT="$(curl -s -m 3 localhost:8100/api/v1/health || true)"
  case "$OUT" in *'"ok"'*) echo "$OUT (${i}s)"; echo; exit 0 ;; esac
  sleep 1
done
echo "health failed — 20 秒内没等到 /api/v1/health 返回 ok"
echo
exit 1
