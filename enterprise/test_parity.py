"""JS / Python rules parity (D46). Runs the browser JS core and the Python engine
on the same fixture and requires the same answers for every Ripple start node,
Assure, Vitals and Atlas. Needs `node` (group 'js' in tests/run_all.py).

    python3 enterprise/test_parity.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "mcp_server"))
sys.path.insert(0, os.path.join(HERE, ".."))

import continuum_core as cc  # noqa: E402
from enterprise import rules  # noqa: E402
from enterprise.parity.convert import workspace_to_seed  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}" + (f"  — {detail}" if (detail and not cond) else ""))


def ripple_sig(r):
    return {
        "start": r["start"] and (r["start"]["id"], r["start"]["type"], r["start"]["name"]),
        "mode": r.get("mode"),
        "affected": sorted((a["id"], a["type"], a["name"], a["depth"], len(a["path"]), bool(a.get("bindingOnly")))
                           for a in r["affected"]),
        "kpis": sorted((k["name"], k["procId"], k.get("task") or "") for k in r["kpis"]),
        "guardrails": sorted((gd["taskId"], gd["source"], gd["blank"], tuple(sorted(gd["agents"])))
                             for gd in r["guardrails"]),
        "counts": r.get("counts", {}),
        "summary": r["summary"],
    }


def assure_sig(a):
    return [(pk["source"], pk["pack"], pk["total"], pk["covered"], pk["partial"], pk["gap"], pk["coverage"],
             [(row["obligation"]["id"], row["status"], row["reason"],
               sorted(x["id"] for x in row["processes"]), sorted(x["id"] for x in row["applications"]),
               sorted(x["id"] for x in row["controls"]),
               sorted((e["kind"], e["id"], e["good"], bool(e.get("failing"))) for e in row["evidence"]))
              for row in pk["rows"]])
            for pk in a["packs"]]


def vitals_sig(v):
    return {"score": v["score"], "checks": v["checks"], "passed": v["passed"], "bySeverity": v["bySeverity"],
            "findings": sorted((f["severity"], f["rule"], f["nodeId"] or "", f["nodeType"], f["name"], f["message"],
                                f["hint"]) for f in v["findings"])}


def atlas_sig(nodes):
    return [(n["id"], n["name"], n["level"], n["importance"], n["owner"], n["depth"],
             sorted((p["id"], p["maturity"]) for p in n["processes"]),
             sorted((a["id"], a["kind"], a["lifecycle"]) for a in n["applications"]),
             n["maturity"], sorted(n["overlap"]) if n["overlap"] else None, atlas_sig(n["children"]))
            for n in nodes]


def main():
    try:
        raw = subprocess.run(["node", os.path.join(HERE, "parity", "dump.js")], capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError) as e:
        check("node runs the JS core", False, str(e))
        return finish()
    js = json.loads(raw)
    seed = workspace_to_seed(js["ws"])
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "seed.json")
        with open(path, "w") as f:
            json.dump(seed, f)
        g = cc.Graph(path, apply_edits=False)
    v = rules.View(g)
    today = js["today"]

    check("same node set in both engines", set(v.idx) == set(js["ripple"]),
          f"py-only {sorted(set(v.idx) - set(js['ripple']))[:5]} js-only {sorted(set(js['ripple']) - set(v.idx))[:5]}")
    py_edges = sorted((e["s"], e["t"], e["type"]) for e in v.edges)
    check("fixture is non-trivial (>100 nodes, >40 edges)", len(v.idx) > 100 and len(py_edges) > 40)

    mismatches = []
    for nid, jr in js["ripple"].items():
        pr = rules.ripple(v, nid)
        if ripple_sig(pr) != ripple_sig(jr):
            a, b = ripple_sig(pr), ripple_sig(jr)
            diff = [k for k in a if a[k] != b[k]]
            mismatches.append((nid, diff))
    check(f"Ripple identical for all {len(js['ripple'])} start nodes", not mismatches, str(mismatches[:3]))

    pa, ja = rules.assure(v, today), js["assure"]
    check("Assure: same packs, statuses, coverage and evidence", assure_sig(pa) == assure_sig(ja))
    check("Assure covers both ISO packs (28 + 33 clauses)",
          sorted(pk["total"] for pk in pa["packs"]) == [28, 33])

    pv, jv = rules.vitals(v, today), js["vitals"]
    sp, sj = vitals_sig(pv), vitals_sig(jv)
    check("Vitals: same score, checks and findings", sp == sj,
          f"py {sp['score']}/{sp['checks']} js {sj['score']}/{sj['checks']}; "
          f"py-only {[f for f in sp['findings'] if f not in sj['findings']][:2]} "
          f"js-only {[f for f in sj['findings'] if f not in sp['findings']][:2]}")
    rules_hit = {f["rule"] for f in pv["findings"]}
    check("fixture exercises failing control, retired-in-use, review overdue",
          {"control-failed", "app-retired-in-use", "process-review-overdue"} <= rules_hit, str(sorted(rules_hit)))

    check("Atlas: same capability tree, links, maturity and overlap", atlas_sig(rules.atlas(v)) == atlas_sig(js["atlas"]))
    check("Atlas keeps a capability cycle visible (both loop nodes present)",
          {"cap_loop_a", "cap_loop_b"} <= {n["id"] for n in _flat(rules.atlas(v))})
    return finish()


def _flat(nodes):
    for n in nodes:
        yield n
        yield from _flat(n["children"])


def finish():
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
