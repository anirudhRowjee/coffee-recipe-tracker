#!/usr/bin/env bash
# Deploy the pushed main branch to the prod VPS. Run from your Mac:
#
#     scripts/deploy.sh          # asks before touching prod
#     scripts/deploy.sh --yes    # no prompt
#
# 1. local checks: on main, clean, pushed; tests pass
# 2. backs up prod (while running) and copies the backup here (data/backups/)
# 3. rehearses: the full test suite against that prod backup, locally
# 4. ships (scripts/remote/ship.sh on the VPS): stop → backup → update →
#    tests with prod's packages → migrate → start; rolls itself back on failure
# 5. verifies (scripts/remote/verify.sh): pages render, no pre-deploy row lost
#
# Undo with scripts/rollback.sh.
#
# Env: COFFEE_HOST (default root@168.144.126.15; "local" runs the VPS side on
# this machine, for rehearsals), plus APP / BACKUPS / SERVICE / START_CMD /
# STOP_CMD / URL, passed through to the VPS scripts.
set -euo pipefail
cd "$(dirname "$0")/.."

HOST=${COFFEE_HOST:-root@168.144.126.15}
APP=${APP:-/root/coffee-recipe-tracker}
BACKUPS=${BACKUPS:-/root/backups}
YES=${1:-}
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
LOCAL_BACKUP=data/backups/prod-$STAMP-predeploy.db

step() { printf '\n==> %s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

# Pass the VPS-side settings through to the remote shell.
remote_env() {  # "export APP=... URL=...; " for whichever settings are set
    local out="" var
    for var in APP BACKUPS SERVICE START_CMD STOP_CMD URL; do
        [ -n "${!var:-}" ] && out+=" $var=$(printf '%q' "${!var}")"
    done
    if [ -n "$out" ]; then printf 'export%s; ' "$out"; fi
}
on_vps() {  # on_vps 'command'  (stdin is forwarded)
    if [ "$HOST" = local ]; then bash -c "$(remote_env)$1"; else ssh -o BatchMode=yes "$HOST" "$(remote_env)$1"; fi
}
fetch() {  # fetch REMOTE_PATH LOCAL_PATH
    if [ "$HOST" = local ]; then cp "$1" "$2"; else scp -q "$HOST:$1" "$2"; fi
}

step "Local checks"
[ "$(git rev-parse --abbrev-ref HEAD)" = main ] || die "not on main"
[ -z "$(git status --porcelain --untracked-files=no)" ] || die "uncommitted changes:
$(git status --short --untracked-files=no)"
git fetch -q origin
SHA=$(git rev-parse HEAD)
[ "$SHA" = "$(git rev-parse origin/main)" ] || die "main is not pushed (origin/main is $(git rev-parse --short origin/main))"
.venv/bin/pytest -q -p no:warnings tests/ | tail -1

PREV=$(on_vps "git -C $APP rev-parse HEAD" < /dev/null)
[ "$PREV" = "$SHA" ] && die "prod is already at $(git log --oneline -1 "$SHA")"
git merge-base --is-ancestor "$PREV" "$SHA" || die "prod is at $PREV, which is not an ancestor of $SHA"

step "Backing up prod"
on_vps "mkdir -p $BACKUPS && $APP/.venv/bin/python - $APP/data/coffee.db $BACKUPS/coffee-$STAMP-predeploy.db" < scripts/backup.py
mkdir -p data/backups
fetch "$BACKUPS/coffee-$STAMP-predeploy.db" "$LOCAL_BACKUP"
echo "copied to $LOCAL_BACKUP"

step "Rehearsing on the prod backup (locally)"
COFFEE_REFERENCE_DB="$LOCAL_BACKUP" .venv/bin/pytest -q -p no:warnings tests/ | tail -1

step "Ready to deploy to $HOST"
git log --oneline "$PREV..$SHA"
if [ "$YES" != --yes ]; then
    read -r -p "Deploy these commits? [y/N] " answer
    [ "$answer" = y ] || die "aborted; prod untouched"
fi

step "Shipping"
on_vps "bash -s -- $SHA $PREV $STAMP" < scripts/remote/ship.sh

step "Verifying"
if ! on_vps "bash -s -- $BACKUPS/coffee-$STAMP-stopped.db" < scripts/remote/verify.sh; then
    die "verification failed — the new code is running. Look at the output above, then run scripts/rollback.sh if needed"
fi

step "Deployed $(git log --oneline -1 "$SHA")"
echo "Backups: $BACKUPS/coffee-$STAMP-stopped.db on the VPS, $LOCAL_BACKUP here."
