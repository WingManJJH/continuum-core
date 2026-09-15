"""Launcher tests (D21). Plain asserts.

    python3 test_run.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run  # noqa: E402

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")


def main():
    # registry integrity: five apps, unique names, unique ports in the 8787-8791 band
    names = [a[0] for a in run.APPS]
    ports = [a[2] for a in run.APPS]
    check("five apps registered", len(run.APPS) == 5)
    check("app names are unique", len(set(names)) == 5)
    check("ports are unique", len(set(ports)) == 5)
    check("ports are the documented 8787-8791", sorted(ports) == [8787, 8788, 8789, 8790, 8791])
    check("every app path exists", all(os.path.isfile(os.path.join(run.HERE, a[1])) for a in run.APPS))

    # selection
    check("no filter -> all five", len(run.select_apps(None)) == 5)
    check("subset selects the named apps", [a[0] for a in run.select_apps("ask,advisor")] == ["advisor", "ask"])
    check("whitespace tolerated", len(run.select_apps(" ask , dashboard ")) == 2)
    try:
        run.select_apps("nope"); bad = False
    except ValueError as e:
        bad = "nope" in str(e)
    check("unknown app raises ValueError naming it", bad)

    # port_busy: a port we just bound reads busy; a closed one reads free
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    s.listen(1)
    bound = s.getsockname()[1]
    check("port_busy true for a listening port", run.port_busy(bound))
    s.close()
    check("port_busy false for a free port", not run.port_busy(bound))

    # --list returns 0 without starting anything
    check("--list exits 0", run.main(["--list"]) == 0)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
