#!/usr/bin/env bash
# Runs ON the VPS (scripts/deploy.sh streams it over ssh). Ships commit SHA:
# stop app → backup → fast-forward → tests with prod's packages → migrate → start.
# Any failure restores the backup, returns to PREV and restarts the old app.
#
# Usage: ship.sh SHA PREV STAMP
# Env (defaults are prod; overridden for local rehearsal):
#   APP=/root/coffee-recipe-tracker  BACKUPS=/root/backups  SERVICE=coffee  START_CMD/STOP_CMD (optional)
set -Eeuo pipefail

SHA=$1 PREV=$2 STAMP=$3
APP=${APP:-/root/coffee-recipe-tracker}
BACKUPS=${BACKUPS:-/root/backups}
SERVICE=${SERVICE:-coffee}
DB=$APP/data/coffee.db
BACKUP=$BACKUPS/coffee-$STAMP-stopped.db
HOLD=$BACKUPS/coffee-$STAMP-held.db

say() { printf '  [vps] %s\n' "$*"; }
# START_CMD / STOP_CMD override systemd (used by the local rehearsal)
service() { if [ "$1" = start ]; then eval "${START_CMD:-systemctl start $SERVICE}"; else eval "${STOP_CMD:-systemctl stop $SERVICE}"; fi; }

rollback() {
    trap - ERR
    say "FAILED at line $1 — restoring backup and previous code"
    cd "$APP"
    # --keep refuses if an untracked live DB sits where PREV tracks one; the
    # backup is copied over it next anyway
    git reset -q --keep "$PREV" 2>/dev/null || git reset -q --hard "$PREV"
    mkdir -p "$(dirname "$DB")"
    cp "$BACKUP" "$DB"
    service start || true
    say "rolled back to $PREV with $BACKUP; the app is running the old code"
    exit 1
}

cd "$APP"
mkdir -p "$BACKUPS"

say "stopping $SERVICE"
service stop
# No writers now, so a plain copy is consistent. This is the copy we restore
# from: it has every write up to the moment the app stopped.
cp "$DB" "$BACKUP"
printf 'prev=%s\nsha=%s\nbackup=%s\nstamp=%s\n' "$PREV" "$SHA" "$BACKUP" "$STAMP" > "$BACKUPS/last-deploy"
say "backed up to $BACKUP"
trap 'rollback $LINENO' ERR

git fetch -q origin
[ "$(git rev-parse HEAD)" = "$PREV" ] || { say "HEAD is $(git rev-parse --short HEAD), expected $PREV"; false; }
git merge-base --is-ancestor "$PREV" "$SHA" || { say "$SHA is not ahead of $PREV"; false; }

if git ls-files --error-unmatch data/coffee.db >/dev/null 2>&1; then
    # data/coffee.db is still tracked at this commit: move the live file out of
    # git's way, update, then put it back (the new commit stops tracking it).
    say "moving the live DB out of git's way for the update"
    mv "$DB" "$HOLD"
    git checkout -q -- data/coffee.db
    git merge -q --ff-only "$SHA"
    # if the DB was the only file in data/, git just removed the empty folder
    mkdir -p "$(dirname "$DB")"
    mv -f "$HOLD" "$DB"
else
    git merge -q --ff-only "$SHA"
fi
say "code now at $(git log --oneline -1)"

if ! git diff --quiet "$PREV" "$SHA" -- requirements.txt; then
    say "requirements.txt changed — installing"
    .venv/bin/pip install -q -r requirements.txt
fi

say "running tests with prod's packages against the backup"
TEST_LOG=$BACKUPS/pytest-$STAMP.log
if ! COFFEE_REFERENCE_DB="$BACKUP" .venv/bin/python -m pytest -q -p no:warnings -p no:cacheprovider tests/ > "$TEST_LOG" 2>&1; then
    grep -E '^(FAILED|ERROR) ' "$TEST_LOG" | sed 's/^/  [vps]   /' || true
    say "$(tail -1 "$TEST_LOG") — full output in $TEST_LOG"
    false
fi
say "$(tail -1 "$TEST_LOG")"

say "migrating"
.venv/bin/python scripts/migrate.py | sed 's/^/  [vps]   /'

trap - ERR
say "starting $SERVICE"
service start
