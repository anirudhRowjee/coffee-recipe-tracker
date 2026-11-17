"""
Runs ON the VPS (scripts/open_portion_pages.sh streams it over ssh). Lets a frozen
portion's code page, /b and /b/<code>, through Caddy without the site password, and
nothing else. Uses only stock Caddy (the app itself limits lookups and turns bots away).
Idempotent: a Caddyfile that already has it is left alone.

    coffee.rowjee.com {                       coffee.rowjee.com {
        basicauth { ... }               →         @portion path /b /b/*
        reverse_proxy localhost:8000              handle @portion {
    }                                                 reverse_proxy localhost:8000
                                                  }
                                                  handle {
                                                      basicauth { ... }
                                                      reverse_proxy localhost:8000
                                                  }
                                              }

Usage: python3 - < open_portion_pages.py
"""
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

CADDYFILE = Path("/etc/caddy/Caddyfile")
_SITE = re.compile(
    r"coffee\.rowjee\.com\s*\{\s*(basicauth\s*\{[^{}]*\})\s*reverse_proxy\s+localhost:8000\s*\}", re.DOTALL)


def with_portion_pages(caddyfile: str) -> str:
    if "@portion path /b /b/*" in caddyfile:
        return caddyfile
    found = _SITE.findall(caddyfile)
    if len(found) != 1:
        raise ValueError("expected the coffee.rowjee.com block to be basicauth then reverse_proxy, and nothing else")
    auth = "\n".join("    " + line if i else line for i, line in enumerate(found[0].strip().splitlines()))
    block = ("coffee.rowjee.com {\n"
             "    # a frozen portion's code page is for anyone with the code (the app rate-limits it)\n"
             "    @portion path /b /b/*\n"
             "    handle @portion {\n"
             "        reverse_proxy localhost:8000\n"
             "    }\n"
             "    handle {\n"
             f"        {auth}\n"
             "        reverse_proxy localhost:8000\n"
             "    }\n"
             "}")
    return _SITE.sub(lambda m: block, caddyfile)


def run(*args: str) -> None:
    subprocess.run(args, check=True, capture_output=True, text=True)


def main() -> None:
    original = CADDYFILE.read_text()
    updated = with_portion_pages(original)
    if updated == original:
        print("Already open; nothing changed.")
        return
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
    print(f"Caddy reloaded: /b is open, everything else still asks for the password. Previous config: {backup}")


if __name__ == "__main__":
    main()
