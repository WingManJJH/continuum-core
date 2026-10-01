"""
Canvas layout layer (Phase A of the visual modeler).

Node positions for the free-form process canvas. Deliberately **separate from the
governed model**: per Core Model §08, decorative properties (x/y, waypoints) are
kept out of the agent-facing schema and out of the versioned/audited write path.
So this is plain runtime state in data/layout.json — not an event, not a model
edit. Moving a box on the canvas never changes what an agent reads or what the
audit trail records; it only changes where the box is drawn.

    { "<process_id>": { "<task_id>": {"x": <num>, "y": <num>}, ... }, ... }
"""
from __future__ import annotations

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
LAYOUT_PATH = None  # None -> per model: <model dir>/layout.json (D49). Tests may pin a path.


def _path() -> str:
    if LAYOUT_PATH:
        return LAYOUT_PATH
    import continuum_core as cc
    return os.path.join(os.path.dirname(cc.DATA), "layout.json")


def _store():
    import continuum_core as cc
    return cc.storage.get()

_MAX = 20000  # clamp coordinates to a sane canvas so a bad client can't wander off


def load_all() -> dict:
    try:
        data = _store().read_json(_path(), {})
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def load_process(pid: str) -> dict:
    return load_all().get(pid, {})


def _clean(positions: dict) -> dict:
    out = {}
    for tid, xy in (positions or {}).items():
        if not isinstance(xy, dict):
            continue
        try:
            x, y = float(xy["x"]), float(xy["y"])
        except (KeyError, TypeError, ValueError):
            continue
        out[str(tid)] = {"x": max(0.0, min(_MAX, x)), "y": max(0.0, min(_MAX, y))}
    return out


def save_process(pid: str, positions: dict) -> dict:
    if not pid:
        raise ValueError("process id required")
    allp = load_all()
    allp[str(pid)] = _clean(positions)
    _store().write_json(_path(), allp)
    return allp[str(pid)]


def reset_process(pid: str) -> None:
    """Forget saved positions for a process (client falls back to auto-layout)."""
    allp = load_all()
    if str(pid) in allp:
        del allp[str(pid)]
        _store().write_json(_path(), allp)
