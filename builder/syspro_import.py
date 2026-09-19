"""
SYSPRO importer — a normalized-CSV adapter over the generic model importer.

The provided SYSPRO material is a SQL-schema dump and PDF reference guides, not a
process taxonomy — there's nothing to auto-extract a process model from. So the
SYSPRO importer is the universal CSV path: export your SYSPRO process model to the
normalized columns below and it imports into its own governed model.

  code,name,level,kind,parent,description
  SY,SYSPRO,1,group,,ERP process model
  SY.1,Finance,2,group,SY,
  SY.1.10,General Ledger,3,process,SY.1,Post and reconcile the GL

`code` must be alpha-prefixed (^[A-Z]{2}(\\.[0-9]+)*$); `kind`/`level`/`parent`
are optional (inferred from the codes). See builder/syspro_template.csv.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import model_import  # noqa: E402


def import_csv(path: str, slug: str = "syspro", name: str = "SYSPRO") -> dict:
    if not os.path.isfile(path):
        raise FileNotFoundError(
            f"no SYSPRO export at {path}. Export your SYSPRO process model to the "
            "normalized CSV (see builder/syspro_template.csv) and pass it here.")
    items = model_import.read_csv(path)
    if not items:
        raise ValueError("the CSV had no rows with a 'code' column")
    seed = model_import.build_model_seed(items, name, sig="syspro")
    base = model_import.write_model(slug, name, seed, source="SYSPRO export",
                                    description=f"SYSPRO process model imported from {os.path.basename(path)}.")
    return {"base": base, "groups": len(seed["ProcessGroup"]), "processes": len(seed["Process"])}


def main(argv):
    import argparse
    ap = argparse.ArgumentParser(description="Import a SYSPRO process model (normalized CSV)")
    ap.add_argument("csv", help="normalized CSV export (code,name,level,kind,parent,description)")
    ap.add_argument("--slug", default="syspro")
    ap.add_argument("--name", default="SYSPRO")
    args = ap.parse_args(argv)
    res = import_csv(args.csv, args.slug, args.name)
    print(f"imported {res['groups']} groups + {res['processes']} processes -> {res['base']}")


if __name__ == "__main__":
    main(sys.argv[1:])
