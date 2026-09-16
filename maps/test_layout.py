"""Canvas layout-layer tests (D26, Phase A). Plain asserts.

Uses a temp layout file so it never touches real data/layout.json.

    python3 test_layout.py
"""
from __future__ import annotations

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "mcp_server"))
sys.path.insert(0, HERE)
import layout  # noqa: E402
import mapdata  # noqa: E402

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")


def main():
    tmp = tempfile.mkdtemp()
    layout.LAYOUT_PATH = os.path.join(tmp, "layout.json")

    # 1. save + load roundtrip
    layout.save_process("CO.3.2.7", {"CO.3.2.7.t1": {"x": 120, "y": 40}, "CO.3.2.7.t2": {"x": 360, "y": 40}})
    got = layout.load_process("CO.3.2.7")
    check("save + load roundtrip", got["CO.3.2.7.t1"] == {"x": 120.0, "y": 40.0} and len(got) == 2)
    check("unknown process loads empty", layout.load_process("NOPE") == {})

    # 2. sanitization: non-numeric / malformed entries dropped
    layout.save_process("P", {"a": {"x": 1, "y": 2}, "b": {"x": "nope", "y": 3}, "c": "junk", "d": {"x": 5}})
    p = layout.load_process("P")
    check("bad coordinates are dropped", set(p.keys()) == {"a"})

    # 3. clamping to the sane canvas bound
    layout.save_process("Q", {"a": {"x": -50, "y": 999999}})
    q = layout.load_process("Q")
    check("coordinates clamped to [0, MAX]", q["a"]["x"] == 0.0 and q["a"]["y"] == layout._MAX)

    # 4. reset forgets a process (auto-layout fallback)
    layout.reset_process("CO.3.2.7")
    check("reset clears saved positions", layout.load_process("CO.3.2.7") == {})
    check("reset leaves other processes intact", layout.load_process("P") == {"a": {"x": 1.0, "y": 2.0}})

    # 5. empty process id is rejected (can't scribble a blank key)
    try:
        layout.save_process("", {"a": {"x": 1, "y": 1}}); ok = False
    except ValueError:
        ok = True
    check("empty process id rejected", ok)

    # 6. mapdata attaches a layout dict to every process (decorative, from this file)
    layout.save_process("CO.3.2.7", {"CO.3.2.7.t1": {"x": 200, "y": 80}})
    maps = mapdata.all_maps()
    check("every process carries a layout key", all("layout" in m for m in maps))
    co = next(m for m in maps if m["id"] == "CO.3.2.7")
    check("saved position surfaces in the map payload", co["layout"].get("CO.3.2.7.t1") == {"x": 200.0, "y": 80.0})

    # 7. layout never touches the governed model (no seed/edit-log mutation)
    import continuum_core as cc
    g = cc.Graph()
    t1 = g.get("Task", "CO.3.2.7.t1")
    check("layout does not add x/y to the Task entity", "x" not in t1 and "y" not in t1)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
