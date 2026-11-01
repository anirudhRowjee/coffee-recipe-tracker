#!/usr/bin/env bash
# Undo the last deploy on the prod VPS: previous code + the database as it was
# when the app stopped for the deploy. The current database is kept on the VPS
# (coffee-<stamp>-before-rollback.db) so later brews can be recovered by hand.
#
#     scripts/rollback.sh          # asks first
#     scripts/rollback.sh --yes
#
# Env: same as scripts/deploy.sh.
set -euo pipefail
cd "$(dirname "$0")/.."

HOST=${COFFEE_HOST:-root@168.144.126.15}
APP=${APP:-/root/coffee-recipe-tracker}
BACKUPS=${BACKUPS:-/root/backups}
URL=${URL:-http://127.0.0.1:8000}

remote_env() {  # "export APP=... URL=...; " for whichever settings are set
    local out="" var
    for var in APP BACKUPS SERVICE START_CMD STOP_CMD URL; do
        [ -n "${!var:-}" ] && out+=" $var=$(printf '%q' "${!var}")"
    done
    if [ -n "$out" ]; then printf 'export%s; ' "$out"; fi
}
on_vps() {
    if [ "$HOST" = local ]; then bash -c "$(remote_env)$1"; else ssh -o BatchMode=yes "$HOST" "$(remote_env)$1"; fi
}

echo "Last deploy on $HOST:"
on_vps "cat $BACKUPS/last-deploy" < /dev/null || exit 1
if [ "${1:-}" != --yes ]; then
    read -r -p "Roll back to the previous code and that backup? [y/N] " answer
    [ "$answer" = y ] || { echo "aborted"; exit 1; }
fi

on_vps "bash -s" < scripts/remote/rollback.sh
on_vps "for i in \$(seq 1 40); do curl -fsS -o /dev/null $URL/select-user 2>/dev/null && exit 0; sleep 0.5; done; exit 1" < /dev/null \
    && echo "App is answering again." || { echo "ERROR: app is not answering at $URL" >&2; exit 1; }
