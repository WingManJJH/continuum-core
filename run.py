#!/usr/bin/env python3
"""
run.py — start all five Continuum web apps at once.

    python3 run.py                    # start every app
    python3 run.py --only ask,advisor # start a subset
    python3 run.py --list             # list apps and exit

Each app runs as a subprocess; its output is line-prefixed with the app name, and
Ctrl-C stops them all. A port already in use is reported and skipped (the app is
probably already running), so re-running is safe.

Set CONTINUUM_LLM_API_KEY (or ANTHROPIC_API_KEY) before running to light up the
ask planner and the advisor reviewer; the launcher forwards the environment.
"""
from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))

# name, app path (relative to this file), port, one-line description
APPS = [
    ("governance", "governance/app.py", 8787, "edit guardrails (versioned, no deploy)"),
    ("dashboard",  "dashboard/app.py",  8788, "strategy-to-execution standing report"),
    ("canvas",     "maps/app.py",       8789, "interactive process canvas"),
    ("advisor",    "advisor/app.py",    8790, "analyze anything vs standards"),
    ("ask",        "ask/app.py",        8791, "plain-English question over the graph"),
]

_COLORS = {"governance": "36", "dashboard": "32", "canvas": "35", "advisor": "33", "ask": "34"}
_RESET = "\033[0m"


def _color(name: str, s: str) -> str:
    if not sys.stdout.isatty():
        return s
    return f"\033[{_COLORS.get(name, '37')}m{s}{_RESET}"


def select_apps(only: str | None):
    """Return the APPS to run. `only` is a comma list of names; raises ValueError
    naming any unknown app."""
    if not only:
        return list(APPS)
    want = {x.strip() for x in only.split(",") if x.strip()}
    known = {a[0] for a in APPS}
    unknown = want - known
    if unknown:
        raise ValueError(f"unknown app(s): {', '.join(sorted(unknown))}. "
                         f"Known: {', '.join(sorted(known))}")
    return [a for a in APPS if a[0] in want]


def port_busy(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _pump(name: str, stream) -> None:
    tag = _color(name, f"{name:>10} |")
    for line in iter(stream.readline, ""):
        print(f"{tag} {line.rstrip()}", flush=True)
    stream.close()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Start all five Continuum web apps.")
    ap.add_argument("--only", help="comma-separated subset, e.g. ask,advisor")
    ap.add_argument("--list", action="store_true", help="list apps and exit")
    args = ap.parse_args(argv)

    try:  # stream output even when piped/backgrounded, not just to a TTY
        sys.stdout.reconfigure(line_buffering=True)
    except (AttributeError, ValueError):
        pass

    if args.list:
        for name, _path, port, desc in APPS:
            print(f"  {name:>10}  http://localhost:{port}  {desc}")
        return 0

    try:
        apps = select_apps(args.only)
    except ValueError as e:
        print(e)
        return 2

    print("Starting Continuum apps... (Ctrl-C to stop all)\n")
    procs = []
    for name, path, port, desc in apps:
        if port_busy(port):
            print(f"  {_color(name, name + ' skipped')} -- port {port} already in use "
                  f"(already running?)  http://localhost:{port}")
            continue
        p = subprocess.Popen(
            [sys.executable, "-u", os.path.join(HERE, path)],  # -u: child streams its output
            cwd=HERE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, env=os.environ.copy())
        threading.Thread(target=_pump, args=(name, p.stdout), daemon=True).start()
        procs.append([name, port, p])
        print(f"  {_color(name, name + ' up')}  ->  http://localhost:{port}   {desc}")

    if not procs:
        print("\nNothing started (all selected ports were busy).")
        return 1

    have_key = bool(os.environ.get("CONTINUUM_LLM_API_KEY") or os.environ.get("ANTHROPIC_API_KEY"))
    print(f"\n  LLM planner + advisor reviewer: {'ON' if have_key else 'off'}"
          f"{'' if have_key else '  (set CONTINUUM_LLM_API_KEY to enable)'}\n")

    try:
        while procs:
            for entry in list(procs):
                name, port, p = entry
                if p.poll() is not None:
                    print(f"  {_color(name, name + ' exited')} (code {p.returncode})")
                    procs.remove(entry)
            time.sleep(0.5)
        print("All apps have exited.")
        return 1
    except KeyboardInterrupt:
        print("\nStopping all apps...")
        for _name, _port, p in procs:
            p.terminate()
        deadline = time.time() + 5
        for _name, _port, p in procs:
            try:
                p.wait(timeout=max(0.0, deadline - time.time()))
            except subprocess.TimeoutExpired:
                p.kill()
        print("Stopped.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
