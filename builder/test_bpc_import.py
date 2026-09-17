"""BPC importer + multi-model tests. Plain asserts, hermetic (temp models dir).

    python3 builder/test_bpc_import.py
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
import bpc_import as bpc  # noqa: E402
from jsonschema import Draft202012Validator  # noqa: E402

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")


# a tiny synthetic BPC slice (no spreadsheet needed): E2E 65, with an L3 whose
# row is MISSING (only scenarios) to exercise ancestor synthesis + a duplicate
# scenario sequence to exercise collision handling.
ROWS = [
    {"type": "End to end", "seq": "65.00.000.000", "title": "65 Order to cash"},
    {"type": "Process area", "seq": "65.05.000.000", "title": "65.05 Develop sales policies"},
    {"type": "Process", "seq": "65.05.010.000", "title": "65.05.010 Develop order management policies"},
    {"type": "Scenario", "seq": "65.05.010.100", "title": "65.05.010.100 Define order policies", "product": "Finance"},
    {"type": "Scenario", "seq": "65.05.010.100", "title": "65.05.010.100 Define call center policies", "product": "Commerce"},
    # a scenario whose L3 (65.05.020) has NO explicit Process row -> must be synthesized
    {"type": "Scenario", "seq": "65.05.020.100", "title": "65.05.020.100 Create retail stores", "product": "Commerce"},
]


def main():
    # --- id mapping (numeric BPC seq -> alpha-prefixed Continuum id + level) ---
    check("L1 maps to bare prefix", bpc.map_id("OC", "65.00.000.000") == ("OC", 1))
    check("L2 maps to prefix.area", bpc.map_id("OC", "65.05.000.000") == ("OC.5", 2))
    check("L3 maps to prefix.area.proc", bpc.map_id("OC", "65.05.010.000") == ("OC.5.10", 3))
    check("L4 maps to full path", bpc.map_id("OC", "65.05.010.100") == ("OC.5.10.100", 4))

    seed = bpc.build_seed(ROWS, "OC", "Order to cash")
    groups = {x["id"]: x for x in seed["ProcessGroup"]}
    procs = {p["id"]: p for p in seed["Process"]}

    check("scenarios became processes", len(procs) == 3)
    check("duplicate scenario seq is disambiguated", "OC.5.10.100" in procs and "OC.5.10.100.2" in procs)
    check("the missing L3 group was synthesized", "OC.5.20" in groups and groups["OC.5.20"]["custom"].get("implied"))
    check("collision-suffixed process still parents to its L3", procs["OC.5.10.100.2"]["parent_ref"] == "OC.5.10")
    check("product kept in custom metadata", procs["OC.5.10.100"]["custom"]["product"] == "Finance")

    # referential integrity: every parent resolves to a group
    gids = set(groups)
    check("no dangling process parents", all(p["parent_ref"] in gids for p in procs.values()))
    check("no dangling group parents", all(g["parent_ref"] in gids for g in groups.values() if g["parent_ref"]))

    # schema validity against the locked schemas
    SD = os.path.join(HERE, "..", "schema")
    pv = Draft202012Validator(json.load(open(os.path.join(SD, "process.schema.json"))))
    gv = Draft202012Validator(json.load(open(os.path.join(SD, "process-group.schema.json"))))
    check("every process is schema-valid", not [e for p in procs.values() for e in pv.iter_errors(p)])
    check("every group is schema-valid", not [e for g in groups.values() for e in gv.iter_errors(g)])
    grv = Draft202012Validator(json.load(open(os.path.join(SD, "guardrail-policy.schema.json"))))
    check("the shared default guardrail is schema-valid",
          not list(grv.iter_errors(seed["GuardrailPolicy"][0])))

    # --- full catalog: prefix is a {e2e -> prefix} map, per-row resolution -----
    multi = bpc.build_seed(
        [{"type": "End to end", "seq": "65.00.000.000", "title": "65 Order to cash"},
         {"type": "Scenario", "seq": "65.05.010.100", "title": "65.05.010.100 A"},
         {"type": "End to end", "seq": "75.00.000.000", "title": "75 Source to pay"},
         {"type": "Scenario", "seq": "75.05.010.100", "title": "75.05.010.100 B"}],
        bpc.E2E_PREFIX, "full")
    mids = {p["id"] for p in multi["Process"]}
    check("full-catalog import prefixes each chain distinctly",
          "OC.5.10.100" in mids and "SP.5.10.100" in mids)

    # --- multi-model: write it as a model, fold it, toggle back ---------------
    with tempfile.TemporaryDirectory() as tmp:
        models_save, root_save = cc.MODELS_DIR, cc.DATA_ROOT
        cc.MODELS_DIR = tmp
        try:
            bpc.write_model("oc-test", "OC test", seed, "unit test", "synthetic")
            check("model.json registered", "oc-test" in [m["slug"] for m in cc.list_models()])
            cc.set_active_model("oc-test")
            g = cc.Graph()
            check("active model folds the imported processes", len(g.all("Process")) == 3)
            check("active model marker reflects the switch", cc.ACTIVE_MODEL == "oc-test")
        finally:
            cc.set_active_model("default")
            cc.MODELS_DIR = models_save
        check("switching back restores the default model", cc.ACTIVE_MODEL == "default"
              and len(cc.Graph().all("Process")) == 8)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED:", ", ".join(FAIL))
        sys.exit(1)


if __name__ == "__main__":
    main()
