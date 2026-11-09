"""
Runs ON the VPS (scripts/change_gate_password.sh streams it over ssh). Replaces
the logins in the coffee.rowjee.com basicauth block with one user.

Usage: python3 - USERNAME BCRYPT_HASH < set_gate_login.py
"""
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

CADDYFILE = Path("/etc/caddy/Caddyfile")
_BLOCK = re.compile(r"(coffee\.rowjee\.com\s*\{.*?basicauth\s*\{)(.*?)(\n\s*\})", re.DOTALL)


def with_single_login(caddyfile: str, user: str, password_hash: str) -> str:
    """The Caddyfile with that site's basicauth block holding only this login."""
    if len(_BLOCK.findall(caddyfile)) != 1:
        raise ValueError("expected exactly one basicauth block for coffee.rowjee.com")
    return _BLOCK.sub(lambda m: f"{m.group(1)}\n        {user} {password_hash}{m.group(3)}", caddyfile)


def run(*args: str) -> None:
    subprocess.run(args, check=True, capture_output=True, text=True)


def main() -> None:
    user, password_hash = sys.argv[1:3]
    original = CADDYFILE.read_text()
    updated = with_single_login(original, user, password_hash)

    with tempfile.NamedTemporaryFile("w", suffix=".Caddyfile", delete=False) as f:
        f.write(updated)
    try:
        run("caddy", "validate", "--config", f.name, "--adapter", "caddyfile")
    except subprocess.CalledProcessError as e:
        sys.exit(f"The new config didn't validate; nothing changed.\n{e.stderr}")

    backup = CADDYFILE.with_name(f"Caddyfile.{time.strftime('%Y%m%dT%H%M%S')}.bak")
    shutil.copy2(CADDYFILE, backup)
    CADDYFILE.write_text(updated)
    try:
        run("systemctl", "reload", "caddy")
    except subprocess.CalledProcessError as e:
        CADDYFILE.write_text(original)
        run("systemctl", "reload", "caddy")
        sys.exit(f"Caddy wouldn't reload, so the old config was restored.\n{e.stderr}")
    print(f"Caddy reloaded; previous config kept at {backup}")


if __name__ == "__main__":
    main()
