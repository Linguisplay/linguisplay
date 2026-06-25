#!/usr/bin/env bash
# Restart LinguisPlay. Now managed by systemd (survives reboot + auto-restart on crash).
# Run after a code push:  ssh persona "bash /opt/linguisplay/deploy/_restart.sh"
set -e
systemctl restart linguisplay
sleep 2
echo "--- status ---"; systemctl --no-pager -l status linguisplay | head -6
echo "--- health ---"; curl -s localhost:8100/api/v1/health || echo 'health failed'
echo
