#!/usr/bin/env bash
# Replace the site-wide password that Caddy asks for on coffee.rowjee.com with
# one shared login. Run from your Mac; it prompts here, so the password never
# appears in chat, shell history, or a process list.
#
#     scripts/change_gate_password.sh            # username "coffee"
#     scripts/change_gate_password.sh friends
#
# On the VPS (scripts/remote/set_gate_login.py): backs up the Caddyfile,
# validates the new one, reloads Caddy, and restores the old one on any failure.
set -euo pipefail
cd "$(dirname "$0")/.."

HOST=${COFFEE_HOST:-root@168.144.126.15}
GATE_USER=${1:-coffee}
[[ "$GATE_USER" =~ ^[A-Za-z0-9_-]+$ ]] || { echo "ERROR: username can only use letters, numbers, - and _" >&2; exit 1; }

read -r -s -p "New site password for '$GATE_USER': " password; echo
read -r -s -p "Same again: " confirm; echo
[ "$password" = "$confirm" ] || { echo "ERROR: those didn't match; nothing changed" >&2; exit 1; }
[ "${#password}" -ge 12 ] || { echo "ERROR: use at least 12 characters; nothing changed" >&2; exit 1; }

# Piped over stdin: caddy reads a non-terminal stdin as the password
hash=$(printf '%s\n' "$password" | ssh -o BatchMode=yes "$HOST" 'caddy hash-password')
unset password confirm
case "$hash" in '$2a$'*) ;; *) echo "ERROR: couldn't hash the password; nothing changed" >&2; exit 1 ;; esac

ssh -o BatchMode=yes "$HOST" "python3 - $(printf '%q' "$GATE_USER") $(printf '%q' "$hash")" < scripts/remote/set_gate_login.py
echo "Done. Sign in with '$GATE_USER' and the new password; the old logins no longer work."
