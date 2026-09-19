"""
Microsoft Business Process Catalog importer (multi-model).

The Microsoft BPC is a 4-level taxonomy keyed by a decimal Process Sequence ID
(LL.AA.PPP.SSS): L1 End-to-end, L2 Process area, L3 Process, L4 Scenario. This
maps it onto Continuum as a self-contained MODEL (its own data/models/<slug>/
seed) so it lives alongside — and toggles against — the default model, SYSPRO,
Sunrise, etc.

Mapping:
  - the BPC's numeric E2E code (e.g. 65) → a 2-letter Continuum prefix (e.g. OC),
    because our id scheme requires an alpha prefix (^[A-Z]{2}\\.[0-9.]+$);
  - L1/L2/L3 → ProcessGroup (levels 1/2/3);
  - L4 Scenario → Process (a governed leaf), sharing one default guardrail;
  - id = prefix + the non-zero sequence segments (05.010.100 → .5.10.100);
  - source metadata (seq, product, module, learn-url) kept in `custom{}`.

Parsing is pure-stdlib so it is testable without the spreadsheet; reading the
.xlsx needs openpyxl and is only used by the CLI.
"""
from __future__ import annotations

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "mcp_server"))
import continuum_core as cc  # noqa: E402
import model_import  # noqa: E402  — the generic normalized-rows -> model core

BIZ_TYPES = {"End to end", "Process area", "Process", "Scenario"}
DEFAULT_GUARDRAIL = "gr.DEFAULT"
DEFAULT_ROLE = "role.unassigned"

# The 15 BPC end-to-end value chains -> a distinct 2-letter Continuum prefix
# (our id scheme requires an alpha prefix; the BPC's E2E number is numeric).
E2E_PREFIX = {
    "10": "AD",  # Acquire to dispose
    "20": "CR",  # Case to resolution
    "30": "CM",  # Concept to market
    "40": "DR",  # Design to retire
    "50": "FP",  # Forecast to plan
    "55": "HR",  # Hire to retire
    "60": "IV",  # Inventory to deliver
    "65": "OC",  # Order to cash
    "70": "PP",  # Plan to produce
    "75": "SP",  # Source to pay
    "80": "PJ",  # Project to profit
    "85": "PQ",  # Prospect to quote
    "90": "RR",  # Record to report
    "95": "SD",  # Service to deliver
    "99": "AO",  # Administer to operate
}


def _strip_html(s: str) -> str:
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", " ", str(s))
    s = s.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    return re.sub(r"\s+", " ", s).strip()


def _first_url(s: str):
    m = re.search(r'https?://[^\s"<)]+', str(s or ""))
    return m.group(0) if m else None


def _seg(seq: str):
    """Return the sequence parts as ints: '65.05.010.100' -> [65,5,10,100]."""
    return [int(x) for x in str(seq).split(".") if x != ""]


def map_id(prefix: str, seq: str):
    """(id, level) for a BPC sequence under `prefix`. Levels 1..4 by the deepest
    non-zero segment; id keeps only the non-zero tail segments."""
    parts = _seg(seq)
    if not parts:
        return None, 0
    tail = parts[1:]                       # drop the E2E number; prefix replaces it
    depth = 0
    for i, v in enumerate(tail):
        if v != 0:
            depth = i + 1
    kept = tail[:depth]
    idv = prefix if not kept else prefix + "." + ".".join(str(v) for v in kept)
    return idv, depth + 1                  # level 1 = E2E group ... 4 = scenario


def _parent(idv: str):
    return idv.rsplit(".", 1)[0] if "." in idv else None


def build_seed(rows: list[dict], prefix, model_name: str) -> dict:
    """Map parsed BPC rows to normalized items and hand them to the generic
    importer. `prefix` is either a single 2-letter prefix (one E2E) or a
    {e2e_number: prefix} map (full catalog)."""
    def prefix_for(seq):
        if isinstance(prefix, str):
            return prefix
        parts = _seg(seq)
        return prefix.get(str(parts[0])) if parts else None

    items = []
    for r in rows:
        if r.get("type") not in BIZ_TYPES:
            continue
        pfx = prefix_for(r.get("seq", ""))
        if not pfx:
            continue
        code, level = map_id(pfx, r.get("seq", ""))
        if not code or level == 0:
            continue
        custom = {"bpc_seq": str(r.get("seq", "")), "source": "Microsoft BPC"}
        if r.get("product"):
            custom["product"] = r["product"]
        if r.get("module"):
            custom["module"] = r["module"]
        learn = _first_url(r.get("learn"))
        if learn:
            custom["learn_url"] = learn
        items.append({
            "code": code, "level": level,
            "kind": "group" if level <= 3 else "process",
            "name": re.sub(r"^[\d.]+\s*", "", str(r.get("title", "")).strip()) or code,
            "description": _strip_html(r.get("desc", "")), "custom": custom,
        })
    sig = "bpc-" + (prefix.lower() if isinstance(prefix, str) else "full")
    return model_import.build_model_seed(items, model_name, sig=sig)


# write_model lives in the generic importer; re-exported so callers/tests keep working
write_model = model_import.write_model


# ---- optional xlsx reader (CLI only; needs openpyxl) ---------------------
def read_xlsx(path: str, e2e_code: str) -> list[dict]:
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    it = ws.iter_rows(values_only=True)
    hdr = next(it)
    idx = {h: i for i, h in enumerate(hdr)}

    def g(row, name):
        i = idx.get(name)
        return row[i] if i is not None and i < len(row) else None

    def title(row):
        for L in range(1, 6):
            t = g(row, f"Title {L}")
            if t:
                return str(t).strip()
        return None

    out = []
    for row in it:
        seq = str(g(row, "Process Sequence ID") or "")
        if e2e_code and not seq.startswith(e2e_code + "."):
            continue
        if not seq:
            continue
        out.append({"type": g(row, "Work Item Type"), "seq": seq, "title": title(row),
                    "product": g(row, "Product"), "module": g(row, "Module"),
                    "desc": g(row, "Description"), "learn": g(row, "Microsoft Learn URL")})
    return out


def main(argv):
    import argparse
    ap = argparse.ArgumentParser(description="Import the Microsoft BPC into a Continuum model")
    ap.add_argument("xlsx")
    ap.add_argument("--full", action="store_true", help="import all 15 end-to-end chains")
    ap.add_argument("--e2e", help="a single BPC end-to-end code, e.g. 65 (omit with --full)")
    ap.add_argument("--prefix", help="2-letter Continuum prefix for a single --e2e, e.g. OC")
    ap.add_argument("--slug", required=True, help="model slug (dir under data/models/)")
    ap.add_argument("--name", required=True)
    args = ap.parse_args(argv)
    if args.full:
        rows = read_xlsx(args.xlsx, None)
        seed = build_seed(rows, E2E_PREFIX, args.name)
    else:
        if not (args.e2e and args.prefix):
            ap.error("either --full, or both --e2e and --prefix")
        rows = read_xlsx(args.xlsx, args.e2e)
        seed = build_seed(rows, args.prefix.upper(), args.name)
    base = write_model(args.slug, args.name, seed,
                       source="Microsoft Business Process Catalog",
                       description=("Full Microsoft BPC (15 end-to-end chains)." if args.full
                                    else f"BPC end-to-end {args.e2e}.") + f" Model '{args.slug}'.")
    print(f"imported {len(seed['ProcessGroup'])} groups + {len(seed['Process'])} processes -> {base}")


if __name__ == "__main__":
    main(sys.argv[1:])
