#!/usr/bin/env bash
# One-time server setup, run on the server after the first rsync:
#   ssh persona "bash /opt/linguisplay/deploy/bootstrap.sh"
set -e
APP_DIR=/opt/linguisplay/apps/api
cd "$APP_DIR"

# venv + deps (server system python3 is 3.6; use 3.11 explicitly)
if [ ! -d .venv ]; then python3.11 -m venv .venv; fi
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt

# production env (no clobber — keeps any manual server edits)
cp -n /opt/linguisplay/deploy/.env.production "$APP_DIR/.env"

# data dir for sqlite
mkdir -p data

# seed the two demo stories (idempotent). Source .env first so seeds hit the
# SAME db the server reads (else seed's default ./dev.db diverges from data/...).
set -a; . "$APP_DIR/.env"; set +a
PYTHONIOENCODING=utf-8 .venv/bin/python seed_blackout.py
PYTHONIOENCODING=utf-8 .venv/bin/python seed_lasttrain.py

echo "bootstrap done."
