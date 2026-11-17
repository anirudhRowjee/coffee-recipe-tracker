#!/usr/bin/env bash
# Let /b and /b/<code> (a frozen portion's code page) through Caddy's site password,
# and nothing else. Run once from your Mac, after the code with /b is deployed. On the
# VPS (scripts/remote/open_portion_pages.py): validates the new Caddyfile, keeps a
# backup, reloads Caddy, and restores the old one on any failure.
set -euo pipefail
cd "$(dirname "$0")/.."
HOST=${COFFEE_HOST:-root@168.144.126.15}
ssh -o BatchMode=yes "$HOST" "python3 -" < scripts/remote/open_portion_pages.py
