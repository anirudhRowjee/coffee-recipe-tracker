"""
Consistent backup of a SQLite database, using only the Python standard library
(the VPS has no sqlite3 CLI). Safe while the app is running.

Usage:
    python scripts/backup.py SRC DEST.db              # back up to a file
    python scripts/backup.py SRC DIR [--keep-days N]  # DIR/coffee-YYYY-MM-DD.db; with N, prune older backups

Pruning (the nightly cron, --keep-days 30) removes every backup in DIR older than N days:
the nightly coffee-YYYY-MM-DD.db, deploy's coffee-<stamp>-stopped/-predeploy.db, the manual
coffee-before-*.db, and deploy's pytest-*.log. It never removes the newest backup, or the one
DIR/last-deploy points at (scripts/rollback.sh needs it, however old the last deploy is).

The deploy script streams this file over ssh (`python - SRC DEST < backup.py`),
so it must not import anything from the app.
"""
import sqlite3
import sys
import time
from datetime import date
from pathlib import Path

TABLES = ["user", "bean", "beanbag", "brewer", "grinder", "recipe", "brew", "plannedbrew", "delta"]


def backup(src: Path, dest: Path) -> None:
    if not src.exists():
        sys.exit(f"ERROR: {src} does not exist")
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".partial")
    s = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    d = sqlite3.connect(tmp)
    try:
        s.backup(d)
        ok = d.execute("PRAGMA integrity_check").fetchone()[0]
        counts = {t: d.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in TABLES}
    finally:
        s.close()
        d.close()
    if ok != "ok":
        tmp.unlink()
        sys.exit(f"ERROR: backup failed integrity check: {ok}")
    tmp.replace(dest)
    print(f"backup {dest} ({dest.stat().st_size} bytes) " + " ".join(f"{t}={n}" for t, n in counts.items()))


def _rollback_backup(directory: Path):
    record = directory / "last-deploy"
    if not record.exists():
        return None
    for line in record.read_text().splitlines():
        if line.startswith("backup="):
            return Path(line.split("=", 1)[1].strip()).resolve()
    return None


def prune(directory: Path, keep_days: int) -> None:
    cutoff = time.time() - keep_days * 86400
    backups = sorted(directory.glob("coffee-*.db"), key=lambda f: f.stat().st_mtime)
    keep = {_rollback_backup(directory)}
    if backups:
        keep.add(backups[-1].resolve())  # never the newest, whatever its age
    for f in backups + list(directory.glob("pytest-*.log")):
        if f.stat().st_mtime < cutoff and f.resolve() not in keep:
            f.unlink()
            print(f"pruned {f}")


def main() -> None:
    args = sys.argv[1:]
    keep_days = None
    if "--keep-days" in args:
        i = args.index("--keep-days")
        keep_days = int(args[i + 1])
        del args[i:i + 2]
    if len(args) != 2:
        sys.exit(__doc__)
    src, dest = Path(args[0]), Path(args[1])
    if dest.is_dir():
        directory = dest
        dest = directory / f"coffee-{date.today().isoformat()}.db"
        backup(src, dest)
        if keep_days is not None:
            prune(directory, keep_days)
    else:
        backup(src, dest)


if __name__ == "__main__":
    main()
