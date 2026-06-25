#!/usr/bin/env bash
# Push local code to the server (run from the local machine). Excludes venv/db/caches.
# Server keeps its own data/ (live SQLite) — never overwrite it.
set -e
LOCAL=/c/Users/17745/linguisplay
REMOTE=persona:/opt/linguisplay

rsync -av \
  --exclude='.venv' --exclude='__pycache__' --exclude='*.pyc' \
  --exclude='*.db' --exclude='data/' --exclude='.pytest_cache' \
  --exclude='node_modules' --exclude='dist' --exclude='.env' \
  "$LOCAL/apps/api/" "$REMOTE/apps/api/"

# deploy scripts + env
rsync -av "$LOCAL/deploy/" "$REMOTE/deploy/"
echo "pushed. Next: ssh persona \"bash /opt/linguisplay/deploy/bootstrap.sh\" (first time) then _restart.sh"
