"""Generic importer + SYSPRO (CSV) + Sunrise (PDF-text) adapter tests. Plain
asserts, hermetic — no spreadsheet, no PDF, no network (parse functions are pure;
model writes go to a temp dir).

    python3 builder/test_importers.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "mcp_server"))
import continuum_core as cc  # noqa: E402
import model_import as mi  # noqa: E402
import syspro_import as sy  # noqa: E402
import sunrise_import as sr  # noqa: E402
from jsonschema import Draft202012Validator  # noqa: E402

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")


SD = os.path.join(HERE, "..", "schema")
PV = Draft202012Validator(json.load(open(os.path.join(SD, "process.schema.json"))))
GV = Draft202012Validator(json.load(open(os.path.join(SD, "process-group.schema.json"))))


def valid(seed):
    e = [x.message for p in seed["Process"] for x in PV.iter_errors(p)]
    e += [x.message for g in seed["ProcessGroup"] for x in GV.iter_errors(g)]
    gids = {g["id"] for g in seed["ProcessGroup"]}
    dangling = [p for p in seed["Process"] if p["parent_ref"] not in gids]
    return not e and not dangling


def test_core():
    items = [
        {"code": "AB", "level": 1, "kind": "group", "name": "Alpha"},
        {"code": "AB.1", "level": 2, "kind": "group", "name": "Area one"},
        {"code": "AB.1.10", "kind": "process", "name": "Do a thing", "description": "<b>Does</b> a thing"},
        {"code": "AB.1.10", "kind": "process", "name": "Do a thing (variant)"},  # duplicate code
        {"code": "AB.2.10", "kind": "process", "name": "Orphan under a missing L2"},  # AB.2 missing
    ]
    seed = mi.build_model_seed(items, "Test model")
    gids = {g["id"]: g for g in seed["ProcessGroup"]}
    pids = {p["id"]: p for p in seed["Process"]}
    check("core: schema-valid + referentially clean", valid(seed))
    check("core: duplicate code disambiguated", "AB.1.10" in pids and "AB.1.10.2" in pids)
    check("core: missing ancestor group synthesized", "AB.2" in gids and gids["AB.2"]["custom"].get("implied"))
    check("core: description stripped of HTML onto the process", pids["AB.1.10"]["custom"]["description"] == "Does a thing")
    check("core: a code with descendants is inferred a group", "AB.1" in gids)
    try:
        mi.build_model_seed([{"code": "123.4", "name": "numeric"}], "bad")
        check("core: numeric (non-alpha) codes rejected", False)
    except ValueError:
        check("core: numeric (non-alpha) codes rejected", True)


def test_syspro():
    with tempfile.TemporaryDirectory() as tmp:
        models_save = cc.MODELS_DIR
        cc.MODELS_DIR = tmp
        try:
            res = sy.import_csv(os.path.join(HERE, "syspro_template.csv"), slug="syspro-test", name="SYSPRO test")
            check("syspro: template CSV imports", res["processes"] >= 6 and res["groups"] >= 3)
            cc.set_active_model("syspro-test")
            check("syspro: model folds with a GL process", cc.Graph().get("Process", "SY.1.10") is not None)
        finally:
            cc.set_active_model("default")
            cc.MODELS_DIR = models_save
    try:
        sy.import_csv("/no/such/file.csv")
        check("syspro: missing export is a clear error", False)
    except FileNotFoundError:
        check("syspro: missing export is a clear error", True)


SUNRISE_TEXT = """1.1 Business Processes
Steering Processes
1. Strategy-to-Market
2. Develop-to-Manage
Core Processes
3. Design to Retire
10. Order-to-Cash
6. Procure-to-Pay
Enabling Processes
15. Record-to-Report
17. Hire to Retire
Process Description
Outcome
The Order-to-Cash process begins with a customer order and ends with cash collected.
The Design to Retire (DTR) process delivers food products and assets.
3.1 Product Planning
3.1.1 Define Product Offering
3.1.2 Assess Feasibility
3.2 Initial Bill of Materials
3.2.1 Define Unit of Measure
19. Not A Chain
19.1 Should Be Ignored
"""


def test_sunrise():
    chains = sr.parse_chains(SUNRISE_TEXT)
    bynum = {c["no"]: c for c in chains}
    check("sunrise: parses the numbered value chains", len(chains) == 7)
    check("sunrise: categories assigned from headings",
          bynum[1]["category"] == "Steering" and bynum[3]["category"] == "Core" and bynum[15]["category"] == "Enabling")
    items = sr.build_items(chains, SUNRISE_TEXT)
    seed = mi.build_model_seed(items, "Sunrise test", sig="sunrise")
    check("sunrise: builds a schema-valid, clean model", valid(seed))
    check("sunrise: has a root SR group and the category groups",
          any(g["id"] == "SR" for g in seed["ProcessGroup"]) and any(g["id"] == "SR.2" for g in seed["ProcessGroup"]))
    otc = next((p for p in seed["Process"] if p["name"] == "Order-to-Cash"), None)
    check("sunrise: name-matched description extracted", otc and "cash collected" in otc["custom"].get("description", ""))
    dtr_txt = sr.chain_description(SUNRISE_TEXT, "Hire to Retire")
    check("sunrise: no wrong description when the name doesn't match", dtr_txt == "")

    # deep body parse: dotted headings become areas (groups) + activities (processes)
    subs = sr.parse_subprocesses(SUNRISE_TEXT, {c["no"] for c in chains})
    check("sunrise: parses body sub-processes", (3, 1, None) in subs and (3, 1, 1) in subs and (3, 2, 1) in subs)
    check("sunrise: ignores dotted headings for non-chain numbers", (19, 1, None) not in subs)
    names = {p["name"] for p in seed["Process"]}
    gnames = {g["name"] for g in seed["ProcessGroup"]}
    check("sunrise: activities became processes", "Define Product Offering" in names and "Assess Feasibility" in names)
    check("sunrise: areas became groups", "Product Planning" in gnames)
    check("sunrise: a chain that decomposes is a group, not a leaf", "Design to Retire" in gnames)


def main():
    test_core()
    test_syspro()
    test_sunrise()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED:", ", ".join(FAIL))
        sys.exit(1)


if __name__ == "__main__":
    main()
