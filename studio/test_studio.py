"""Offline Studio: build it, then prove it (D53). Group 'studio' (node + playwright).

    python3 studio/test_studio.py

1. build from the ORIGINAL Studio state and compare with the published original
   (regression.js: identical output, byte-identical BPMN export, every field kept);
2. build the published Studio and run the full browser e2e (e2e.js).
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
NODE_ENV = dict(os.environ, NODE_PATH=os.path.join(HERE, "test", "node_modules"))
passed = failed = 0


def node(script):
    global passed, failed
    r = subprocess.run(["node", os.path.join(HERE, "test", script)], env=NODE_ENV, capture_output=True, text=True, timeout=600)
    out = r.stdout + r.stderr
    print(out[-4000:])
    p, f = len(re.findall(r"^\s+✓", out, re.M)), len(re.findall(r"^\s+✗", out, re.M))
    passed += p
    failed += f + (1 if r.returncode and not f else 0)


def build(state=None):
    args = [sys.executable, os.path.join(HERE, "build.py")] + ([state] if state else [])
    subprocess.run(args, check=True, capture_output=True, cwd=HERE)


build(os.path.join(HERE, "state.orig.json"))
shutil.copy(os.path.join(HERE, "dist", "studio.html"), os.path.join(HERE, "dist", "studio-from-original-state.html"))
node("regression.js")
build()
node("e2e.js")
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
