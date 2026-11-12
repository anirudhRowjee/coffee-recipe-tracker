#!/usr/bin/env bash
# Runs ON the VPS after ship.sh: is the app up, does every page render for
# every user, and is every pre-deploy row still there?
#
# Usage: verify.sh BACKUP
# Env: APP=/root/coffee-recipe-tracker  URL=http://127.0.0.1:8000
set -euo pipefail

BACKUP=$1
APP=${APP:-/root/coffee-recipe-tracker}
URL=${URL:-http://127.0.0.1:8000}
say() { printf '  [vps] %s\n' "$*"; }

for _ in $(seq 1 40); do
    curl -fsS -o /dev/null "$URL/select-user" 2>/dev/null && break
    sleep 0.5
done
curl -fsS -o /dev/null "$URL/select-user" || { say "app is not answering at $URL"; exit 1; }

cd "$APP"
.venv/bin/python - "$BACKUP" data/coffee.db "$URL" <<'PY'
import hashlib, secrets, sqlite3, sys, urllib.request

backup, live, url = sys.argv[1:4]
b = sqlite3.connect(f"file:{backup}?mode=ro", uri=True)
l = sqlite3.connect(f"file:{live}?mode=ro", uri=True)
problems = []

# every row that existed before the deploy is still there, unchanged
for table in ["user", "bean", "beanbag", "brewer", "grinder", "recipe", "brew", "plannedbrew", "delta"]:
    cols = [r[1] for r in b.execute(f'PRAGMA table_info("{table}")')]
    q = f'SELECT {", ".join(cols)} FROM "{table}" ORDER BY id'
    before, after = b.execute(q).fetchall(), {r[0]: r for r in l.execute(q)}
    changed = [r[0] for r in before if after.get(r[0]) != r]
    # brew 64 is changed on purpose by migrate.py's data fix
    if table == "brew":
        changed = [i for i in changed if i != 64]
    if changed:
        problems.append(f"{table}: {len(changed)} row(s) missing or changed, e.g. id {changed[:5]}")
    print(f"  [vps]   {table}: {len(before)} before, {len(after)} now")

if l.execute("SELECT COUNT(*) FROM recipe WHERE line_id IS NULL").fetchone()[0]:
    problems.append("recipes without a named recipe")

# Check pages as each user with a throwaway session, removed straight after.
w = sqlite3.connect(live)
try:
    for (uid,) in w.execute("SELECT id FROM user").fetchall():
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        w.execute("INSERT INTO usersession (token_hash, user_id, created_at) VALUES (?, ?, datetime('now'))", (token_hash, uid))
        w.commit()
        try:
            for page in ["/", "/?pick=1", "/browse", "/manage", "/help"]:
                req = urllib.request.Request(url + page, headers={"Cookie": f"session={token}"})
                try:
                    status = urllib.request.urlopen(req, timeout=10).status
                except Exception as e:  # noqa: BLE001
                    status = getattr(e, "code", e)
                if status != 200:
                    problems.append(f"GET {page} as user {uid} -> {status}")
        finally:
            w.execute("DELETE FROM usersession WHERE token_hash = ?", (token_hash,))
            w.commit()
finally:
    w.close()

if problems:
    print("  [vps] VERIFY FAILED:\n  [vps]   " + "\n  [vps]   ".join(problems))
    sys.exit(1)
print("  [vps] verified: data intact, every page renders for every user")
PY
