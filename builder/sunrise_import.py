"""
Sunrise Farms importer — best-effort extraction from the PDF process model.

The Sunrise model is a 685-page PDF (marked DRAFT). Its clean, reliably-extractable
structure is a value-chain map: Steering / Core / Enabling processes, each a
numbered end-to-end chain (Strategy-to-Market, Order-to-Cash, Procure-to-Pay, …),
with a descriptive paragraph in the body. This adapter pulls that into a governed
model. It is a SCAFFOLD: the deep sub-processes live in hundreds of pages of prose
and are not reconstructed here — refine with a structured export (the SYSPRO CSV
shape works) or by authoring beneath each chain.

Parsing is pure (text in) so it's testable without the PDF; reading the PDF needs
the `pdftotext` CLI and is used only by the CLI.
"""
from __future__ import annotations

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import model_import  # noqa: E402

# category heading -> (prefix segment, label)
CATEGORIES = [("Steering", 1, "Steering processes"), ("Core", 2, "Core processes"),
              ("Enabling", 3, "Enabling processes"), ("Support", 4, "Support processes")]
_CAT_RE = re.compile(r"^(Steering|Core|Enabling|Support)\s+Processes\b", re.I)
_CHAIN_RE = re.compile(r"^\s*(\d+)\.\s+([A-Za-z][A-Za-z0-9 /&'\-]+?(?:[- ]to[- ][A-Za-z].*)?)\s*$")
_STOP_RE = re.compile(r"^Process Description\b")


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def parse_chains(text: str) -> list[dict]:
    """Pull the numbered value chains and their category from the Business
    Processes section. Returns [{no, name, category}] deduped by chain number."""
    lines = text.splitlines()
    # bound to the Business Processes region: first category heading .. first stop
    start = next((i for i, ln in enumerate(lines) if _CAT_RE.match(ln.strip())), None)
    if start is None:
        return []
    cat, out, seen = None, [], set()
    for ln in lines[start:start + 120]:
        s = ln.strip()
        m = _CAT_RE.match(s)
        if m:
            cat = m.group(1).title()
            continue
        if _STOP_RE.match(s) and out:
            break
        cm = _CHAIN_RE.match(s)
        if cm and cat and "to" in cm.group(2).lower():
            no = int(cm.group(1))
            name = re.sub(r"\s*-\s*", "-", cm.group(2).strip()).replace("- ", "-")
            if no in seen:
                continue
            seen.add(no)
            out.append({"no": no, "name": name, "category": cat})
    return out


def chain_description(text: str, name: str) -> str:
    """Best-effort: the body sentence 'The <chain> … process …'. Returns "" rather
    than a wrong match — never attribute one chain's description to another."""
    key = re.escape(name.replace("-to-", " to ").replace("-To-", " to ").split(" to ")[0][:14])
    m = re.search(r"(The " + key + r"[^.]*?process[^.]*\.)", text, re.I)
    return m.group(1).strip() if m else ""


def build_items(chains: list[dict], text: str = "") -> list[dict]:
    catseg = {c[0]: (c[1], c[2]) for c in CATEGORIES}
    items, counters = [], {}
    made_cat = set()
    for ch in chains:
        seg, label = catseg.get(ch["category"], (4, ch["category"] + " processes"))
        if seg not in made_cat:
            items.append({"code": f"SR.{seg}", "level": 2, "kind": "group", "name": label,
                          "custom": {"source": "Sunrise Farms"}})
            made_cat.add(seg)
        counters[seg] = counters.get(seg, 0) + 1
        code = f"SR.{seg}.{counters[seg]}"
        items.append({"code": code, "kind": "process", "name": ch["name"],
                      "description": chain_description(text, ch["name"]),
                      "custom": {"source": "Sunrise Farms", "sunrise_no": ch["no"],
                                 "category": ch["category"]}})
    if items:  # the model root
        items.insert(0, {"code": "SR", "level": 1, "kind": "group", "name": "Sunrise Farms",
                         "custom": {"source": "Sunrise Farms"}})
    return items


def read_pdf(path: str) -> str:
    import subprocess
    try:
        return subprocess.run(["pdftotext", path, "-"], capture_output=True, text=True,
                              timeout=120, check=True).stdout
    except FileNotFoundError:
        raise RuntimeError("pdftotext not found — install poppler, or pass extracted text")


def import_pdf(path: str, slug: str = "sunrise", name: str = "Sunrise Farms") -> dict:
    text = read_pdf(path)
    chains = parse_chains(text)
    items = build_items(chains, text)
    if not items:
        raise ValueError("no value chains found — the PDF layout may have changed")
    seed = model_import.build_model_seed(items, name, sig="sunrise")
    base = model_import.write_model(slug, name, seed, source="Sunrise Farms PDF process model",
                                    description="Value-chain scaffold extracted from the Sunrise Farms PDF; "
                                                "deep sub-processes are not reconstructed.")
    return {"base": base, "chains": len(chains),
            "groups": len(seed["ProcessGroup"]), "processes": len(seed["Process"])}


def main(argv):
    import argparse
    ap = argparse.ArgumentParser(description="Import the Sunrise Farms PDF process model (scaffold)")
    ap.add_argument("pdf")
    ap.add_argument("--slug", default="sunrise")
    ap.add_argument("--name", default="Sunrise Farms")
    args = ap.parse_args(argv)
    res = import_pdf(args.pdf, args.slug, args.name)
    print(f"parsed {res['chains']} value chains -> {res['groups']} groups + {res['processes']} processes @ {res['base']}")


if __name__ == "__main__":
    main(sys.argv[1:])
