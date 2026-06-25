#!/usr/bin/env bash
# One-time: install the systemd unit and take port 8100 over from any nohup instance.
# Runs as a script file (cmdline = "bash install_systemd.sh"), and kills by PID (not
# pkill pattern), so it can't SIGKILL itself the way an ssh one-liner pkill would.
set -e

cp /opt/linguisplay/deploy/linguisplay.service /etc/systemd/system/linguisplay.service
systemctl daemon-reload
systemctl enable linguisplay

# free port 8100 if a manual nohup uvicorn is holding it
pid=$(ss -ltnp 2>/dev/null | grep ':8100' | grep -oP 'pid=\K[0-9]+' | head -1 || true)
if [ -n "$pid" ]; then echo "killing nohup uvicorn pid=$pid"; kill "$pid" 2>/dev/null || true; sleep 2; fi

systemctl restart linguisplay
sleep 2
echo "--- enabled? ---"; systemctl is-enabled linguisplay
echo "--- active? ---";  systemctl is-active linguisplay
echo "--- health ---";   curl -s localhost:8100/api/v1/health || echo 'health failed'
echo
