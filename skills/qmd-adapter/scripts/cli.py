"""Simple CLI to smoke-check the local QMD MCP HTTP service.

Usage:
  python3 skills/qmd-adapter/scripts/cli.py health
  python3 skills/qmd-adapter/scripts/cli.py search "how to deploy"
"""
import os
import sys

# Ensure local scripts/ dir is importable when running directly
SCRIPT_DIR = os.path.dirname(__file__)
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from qmd_adapter import health, search


def _main(argv):
    if len(argv) < 2:
        print("usage: cli.py health|search <query>")
        return 2

    cmd = argv[1]
    if cmd == "health":
        h = health()
        if not h:
            print("QMD not reachable at http://127.0.0.1:8181")
            return 1
        print(h)
        return 0

    if cmd == "search":
        q = " ".join(argv[2:])
        if not q:
            print("please provide a query")
            return 2
        out = search(q, n=3)
        print(out)
        return 0

    print("unknown command", cmd)
    return 2


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))