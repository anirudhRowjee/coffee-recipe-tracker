"""
scripts/backup.py: the nightly backup on the VPS (cron, --keep-days 30) prunes every old
backup and test log, but never the newest backup or the one a rollback would restore.
"""
import os
import subprocess
import sys
import time
from pathlib import Path

from conftest import ROOT, copy_db

SCRIPT = ROOT / "scripts" / "backup.py"
OLD = time.time() - 40 * 86400


def test_pruning_keeps_the_rollback_backup_and_the_newest(tmp_path: Path, reference_db):
    src = tmp_path / "live.db"
    copy_db(reference_db, src)
    backups = tmp_path / "backups"
    backups.mkdir()
    old = ["coffee-2026-09-01.db", "coffee-20260901T000000Z-stopped.db", "coffee-20260901T000000Z-predeploy.db",
           "coffee-before-cafes-20260901.db", "pytest-20260901T000000Z.log"]
    rollback = backups / "coffee-20260902T000000Z-stopped.db"
    for name in old + [rollback.name, "coffee-2026-11-14.db", "notes.txt"]:
        (backups / name).write_text("x")
    for name in old + [rollback.name, "notes.txt"]:
        os.utime(backups / name, (OLD, OLD))
    (backups / "last-deploy").write_text(f"prev=a\nsha=b\nbackup={rollback}\nstamp=x\n")

    out = subprocess.run([sys.executable, str(SCRIPT), str(src), str(backups), "--keep-days", "30"],
                         capture_output=True, text=True, check=True).stdout
    left = {p.name for p in backups.iterdir()}
    assert not left & set(old), out
    assert {rollback.name, "coffee-2026-11-14.db", "notes.txt", "last-deploy"} <= left
    assert any(n.startswith("coffee-20") and n.endswith(".db") and n != "coffee-2026-11-14.db" and n != rollback.name for n in left)


def test_a_lone_old_backup_is_never_pruned(tmp_path: Path, reference_db):
    """With nothing newer (a failed nightly run), the newest backup stays, however old."""
    backups = tmp_path / "backups"
    backups.mkdir()
    only = backups / "coffee-20260901T000000Z-stopped.db"
    only.write_text("x")
    os.utime(only, (OLD, OLD))
    sys.path.insert(0, str(SCRIPT.parent))
    try:
        import backup
        backup.prune(backups, 30)
    finally:
        sys.path.pop(0)
    assert only.exists()
