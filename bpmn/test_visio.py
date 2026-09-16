"""Visio (.vsdx) import tests (D35). Plain asserts.

Builds a minimal .vsdx (a zip of Visio XML parts) in memory — a Start -> Receive
-> Decision -> Approve -> End flowchart with a labelled branch — parses it, and
applies it as a new governed process through the shared audited write path.

    python3 test_visio.py
"""
from __future__ import annotations

import io
import os
import sys
import xml.etree.ElementTree as ET
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "mcp_server"))
sys.path.insert(0, os.path.join(HERE, "..", "maps"))
sys.path.insert(0, os.path.join(HERE, "..", "governance"))
sys.path.insert(0, HERE)
import continuum_core as cc  # noqa: E402
import store as gov  # noqa: E402
import mapdata  # noqa: E402
import export as bpmn  # noqa: E402
import import_bpmn as imp  # noqa: E402
import visio_import as vis  # noqa: E402

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")


MASTERS = """<Masters xmlns="http://schemas.microsoft.com/office/visio/2012/main">
  <Master ID="2" NameU="Process"/><Master ID="3" NameU="Decision"/>
  <Master ID="4" NameU="Terminator"/><Master ID="5" NameU="Data"/></Masters>"""

PAGE = """<PageContents xmlns="http://schemas.microsoft.com/office/visio/2012/main">
 <Shapes>
  <Shape ID="1" Master="4"><Cell N="PinX" V="0"/><Text>Start</Text></Shape>
  <Shape ID="2" Master="2"><Cell N="PinX" V="2"/><Text>Receive request</Text></Shape>
  <Shape ID="3" Master="3"><Cell N="PinX" V="4"/><Text>Over 500?</Text></Shape>
  <Shape ID="4" Master="2"><Cell N="PinX" V="6"/><Text>Approve</Text></Shape>
  <Shape ID="5" Master="4"><Cell N="PinX" V="8"/><Text>End</Text></Shape>
  <Shape ID="6" Master="5"><Cell N="PinX" V="4"/><Text>note</Text></Shape>
  <Shape ID="20"><Cell N="PinX" V="1"/></Shape>
  <Shape ID="21"><Cell N="PinX" V="3"/></Shape>
  <Shape ID="22"><Cell N="PinX" V="5"/><Text>yes</Text></Shape>
  <Shape ID="23"><Cell N="PinX" V="7"/></Shape>
 </Shapes>
 <Connects>
  <Connect FromSheet="20" FromCell="BeginX" ToSheet="1"/><Connect FromSheet="20" FromCell="EndX" ToSheet="2"/>
  <Connect FromSheet="21" FromCell="BeginX" ToSheet="2"/><Connect FromSheet="21" FromCell="EndX" ToSheet="3"/>
  <Connect FromSheet="22" FromCell="BeginX" ToSheet="3"/><Connect FromSheet="22" FromCell="EndX" ToSheet="4"/>
  <Connect FromSheet="23" FromCell="BeginX" ToSheet="4"/><Connect FromSheet="23" FromCell="EndX" ToSheet="5"/>
 </Connects>
</PageContents>"""


def make_vsdx() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("visio/masters/masters.xml", MASTERS)
        z.writestr("visio/pages/page1.xml", PAGE)
    return buf.getvalue()


def main():
    cc.reset_log(cc.EDITS_LOG)
    s = gov.GovernanceStore()
    data = make_vsdx()

    # 1. parse
    p = vis.parse_vsdx(data)
    check("2 process shapes -> 2 steps", len(p["tasks"]) == 2)
    check("a Decision shape -> 1 exclusive gateway", len(p["gateways"]) == 1 and p["gateways"][0]["type"] == "exclusive")
    check("4 connectors -> 4 flows", len(p["flows"]) == 4)
    check("terminators classified start vs end", "1" in p["start_ids"] and "5" in p["end_ids"])
    check("a data shape is skipped with a warning", any("skipped" in w for w in p["warnings"]))
    check("a connector label becomes a branch condition", any(f["condition"] == "yes" for f in p["flows"]))

    # 2. dry-run plan
    plan = vis.plan_vsdx(data)
    check("plan counts match the parse", plan["counts"]["steps"] == 2 and plan["counts"]["gateways"] == 1 and plan["counts"]["flows"] == 4)

    # 3. apply -> a real governed process, audited
    res = vis.apply_vsdx(data, code="VS.1.1", actor="role.ops.support_lead", store=s)
    check("apply mints the imported process", res["code"] == "VS.1.1")
    g = cc.Graph()
    check("the Visio process now exists", g.get("Process", "VS.1.1") is not None)
    m = next(x for x in mapdata.all_maps(g) if x["id"] == "VS.1.1")
    check("steps + gateway + flows reconstructed", len(m["tasks"]) == 2 and len(m["gateways"]) == 1 and len(m["flows"]) == 4)
    check("the 'yes' branch condition survived", any(f.get("condition") == "yes" for f in m["flows"]))
    check("the start/end terminators mapped to the process start/end",
          any(f["from"] == "__start__" for f in m["flows"]) and any(f["to"] == "__end__" for f in m["flows"]))
    check("audit chain intact after Visio import", cc.verify_log(cc.EDITS_LOG)["ok"] is True)

    # 4. the imported process re-exports to well-formed BPMN (Visio -> Continuum -> BPMN)
    ET.fromstring(bpmn.export_process("VS.1.1"))
    check("imported Visio process re-exports to BPMN", True)

    # 5. legacy .vsd (not a zip) refused clearly
    try:
        vis.parse_vsdx(b"\xd0\xcf\x11\xe0 legacy OLE binary"); ok = False
    except imp.ImportError_:
        ok = True
    check("legacy binary .vsd is refused", ok)

    cc.reset_log(cc.EDITS_LOG)
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
