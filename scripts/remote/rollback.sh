#!/usr/bin/env bash
# Runs ON the VPS (scripts/rollback.sh streams it over ssh). Undoes the last
# deploy recorded in $BACKUPS/last-deploy: previous code + pre-deploy database.
# The current database is kept as coffee-<stamp>-before-rollback.db first, so
# anything logged since the deploy can still be recovered by hand.
#
# Env: APP=/root/coffee-recipe-tracker  BACKUPS=/root/backups  SERVICE=coffee  START_CMD/STOP_CMD (optional)
set -euo pipefail

APP=${APP:-/root/coffee-recipe-tracker}
BACKUPS=${BACKUPS:-/root/backups}
SERVICE=${SERVICE:-coffee}
DB=$APP/data/coffee.db
say() { printf '  [vps] %s\n' "$*"; }
# START_CMD / STOP_CMD override systemd (used by the local rehearsal)
service() { if [ "$1" = start ]; then eval "${START_CMD:-systemctl start $SERVICE}"; else eval "${STOP_CMD:-systemctl stop $SERVICE}"; fi; }

[ -f "$BACKUPS/last-deploy" ] || { say "no $BACKUPS/last-deploy — nothing to roll back"; exit 1; }
# shellcheck disable=SC1091
. "$BACKUPS/last-deploy"   # prev, sha, backup, stamp
[ -f "$backup" ] || { say "backup $backup is missing"; exit 1; }

cd "$APP"
say "stopping $SERVICE"
service stop
KEEP=$BACKUPS/coffee-$stamp-before-rollback.db
mv "$DB" "$KEEP"
say "current database kept at $KEEP"
git reset -q --keep "$prev" 2>/dev/null || git reset -q --hard "$prev"
mkdir -p "$(dirname "$DB")"
cp "$backup" "$DB"
say "code back at $(git log --oneline -1); database restored from $backup"
service start
mv "$BACKUPS/last-deploy" "$BACKUPS/last-deploy.rolled-back-$stamp"
