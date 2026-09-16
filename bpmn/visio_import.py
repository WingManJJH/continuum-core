"""
Visio (.vsdx) import (extends the import feature).

Reads a modern Visio drawing — a `.vsdx` is an Open-Packaging-Convention ZIP of
XML parts — and turns its flowchart into the same parsed graph the BPMN importer
applies, so a Visio process lands in the governed model through the exact same
audited write path (`import_bpmn.apply_parsed`).

Mapping (Visio flowchart shapes -> Continuum):
  a shape whose master name says "Decision"                 -> exclusive gateway
  a "Terminator" / "Start/End" shape                        -> the process start/end
  any other flow shape (Process, Subprocess, Operation, ...) -> a step
  a connector (a shape that is the FromSheet of a Connect)  -> a sequence flow;
        its begin/end endpoints come from the BeginX/EndX Connect rows, and its
        text (if any) becomes the branch condition/label
Data shapes, off-page references, and pages past the first are skipped with a
warning — never silently dropped. Legacy binary `.vsd` (pre-2013 OLE) is not a ZIP
and is refused with a clear message (re-save as .vsdx in Visio).

Only reads bytes and returns a structure; the write happens in import_bpmn.
"""
from __future__ import annotations

import io
import os
import re
import sys
import xml.etree.ElementTree as ET
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import import_bpmn as _imp  # noqa: E402  — shared apply/plan

V = "http://schemas.microsoft.com/office/visio/2012/main"


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _text(shape) -> str:
    el = shape.find(f"{{{V}}}Text")
    if el is None:
        return ""
    return re.sub(r"\s+", " ", "".join(el.itertext())).strip()


def _pinx(shape) -> float:
    for c in shape.findall(f"{{{V}}}Cell"):
        if c.get("N") == "PinX":
            try:
                return float(c.get("V"))
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def _classify(master_name: str) -> str:
    n = (master_name or "").lower()
    if "decision" in n:
        return "gateway"
    if "terminator" in n or "start/end" in n or n in ("start", "end", "begin", "terminate", "start/ end"):
        return "terminator"
    if any(k in n for k in ("data", "document", "database", "card", "off-page", "off page", "annotation")):
        return "skip"
    return "task"


def parse_vsdx(data: bytes) -> dict:
    """Parse a .vsdx byte string into {name, tasks, gateways, events, flows,
    start_ids, end_ids, warnings}. Raises ImportError_ if it isn't a .vsdx."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise _imp.ImportError_("not a .vsdx file — legacy binary .vsd isn't supported; "
                                "open it in Visio and Save As .vsdx, then import that")
    names = zf.namelist()

    # master id -> name (for shape classification)
    masters: dict[str, str] = {}
    for mp in [n for n in names if n.endswith("masters/masters.xml")]:
        try:
            root = ET.fromstring(zf.read(mp))
        except ET.ParseError:
            continue
        for m in root.iter(f"{{{V}}}Master"):
            mid = m.get("ID")
            if mid:
                masters[mid] = m.get("NameU") or m.get("Name") or ""

    pages = sorted(n for n in names if re.search(r"visio/pages/page[0-9]+\.xml$", n))
    if not pages:
        raise _imp.ImportError_("no drawing pages found in the .vsdx")

    warnings: list[str] = []
    if len(pages) > 1:
        warnings.append(f"{len(pages)} pages found — only the first page was imported")

    root = ET.fromstring(zf.read(pages[0]))
    shapes = {}
    for sh in root.iter(f"{{{V}}}Shape"):
        sid = sh.get("ID")
        if sid is not None:
            shapes[sid] = sh

    # connectors are the shapes that appear as FromSheet in a Connect row
    connects = list(root.iter(f"{{{V}}}Connect"))
    conn_ids = {c.get("FromSheet") for c in connects if c.get("FromSheet")}

    tasks, gateways, flows = [], [], []
    start_ids, end_ids = set(), set()
    terminators = []
    indeg, outdeg = {}, {}

    # edges first (so we can classify terminators as start vs end)
    by_conn: dict[str, dict] = {}
    for c in connects:
        cid, cell, to = c.get("FromSheet"), c.get("FromCell", ""), c.get("ToSheet")
        if not cid or not to:
            continue
        slot = by_conn.setdefault(cid, {})
        if cell.startswith("Begin"):
            slot["source"] = to
        elif cell.startswith("End"):
            slot["target"] = to
    for cid, ends in by_conn.items():
        src, tgt = ends.get("source"), ends.get("target")
        if not src or not tgt:
            continue
        cond = _text(shapes[cid]) if cid in shapes else ""
        flows.append({"bpmn_id": cid, "source": src, "target": tgt, "condition": cond or None})
        outdeg[src] = outdeg.get(src, 0) + 1
        indeg[tgt] = indeg.get(tgt, 0) + 1

    for sid, sh in shapes.items():
        if sid in conn_ids:
            continue  # it's a connector, handled as a flow
        kind = _classify(masters.get(sh.get("Master", ""), ""))
        name = _text(sh)
        x = _pinx(sh)
        if kind == "gateway":
            gateways.append({"bpmn_id": sid, "type": "exclusive", "name": name, "x": x})
        elif kind == "terminator":
            terminators.append((sid, x))
        elif kind == "skip":
            warnings.append(f"shape {sid} '{name or '(no text)'}' skipped (data/annotation shape)")
        else:
            tasks.append({"bpmn_id": sid, "name": name or "Step", "agent": False, "x": x})

    # classify terminators: source-only -> start, sink-only -> end; ambiguous ->
    # earliest by x is start, latest is end
    for sid, x in terminators:
        has_in, has_out = indeg.get(sid, 0) > 0, outdeg.get(sid, 0) > 0
        if has_out and not has_in:
            start_ids.add(sid)
        elif has_in and not has_out:
            end_ids.add(sid)
    unresolved = [(sid, x) for sid, x in terminators if sid not in start_ids and sid not in end_ids]
    if unresolved:
        unresolved.sort(key=lambda t: t[1])
        start_ids.add(unresolved[0][0])
        if len(unresolved) > 1:
            end_ids.add(unresolved[-1][0])

    tasks.sort(key=lambda t: t["x"])
    gateways.sort(key=lambda g: g["x"])
    return {"name": _page_name(root) or "Imported from Visio", "tasks": tasks, "gateways": gateways,
            "events": [], "flows": flows, "start_ids": start_ids, "end_ids": end_ids, "warnings": warnings}


def _page_name(root) -> str | None:
    # the page element carries a Name; the PageContents part usually doesn't, so
    # this is best-effort and falls back to a default at the call site.
    nm = root.get("Name") or root.get("NameU")
    return nm


def plan_vsdx(data: bytes) -> dict:
    return _imp.plan_from_parsed(parse_vsdx(data))


def apply_vsdx(data: bytes, code=None, owner=None, actor=_imp.DEFAULT_OWNER,
               reason: str = "imported from Visio (.vsdx)", store=None) -> dict:
    return _imp.apply_parsed(parse_vsdx(data), code=code, owner=owner,
                             actor=actor, reason=reason, store=store)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        import json
        with open(sys.argv[1], "rb") as f:
            print(json.dumps(plan_vsdx(f.read()), indent=2))
    else:
        print("usage: python visio_import.py <file.vsdx>   # dry-run plan")
