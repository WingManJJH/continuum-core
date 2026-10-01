"""The standard test run — one command for every suite (D44).

    python tests/run_all.py                 # everything available here
    python tests/run_all.py --list          # show the registry
    python tests/run_all.py --only enterprise,storage
    python tests/run_all.py --skip harness

Every suite is a plain script that prints `N passed, M failed` and exits non-zero
on failure (the repo's no-framework convention). This runner is the single
registry: CI calls it, so a suite added here is a suite CI runs.

Optional groups run when their prerequisite is present, and are reported as
SKIPPED (never silently passed) when it is not:
  - `postgres`  needs CONTINUUM_TEST_DATABASE_URL (a throwaway database)
  - `js`        needs `node` on PATH (JS/Python rules parity)
  - `harness`   needs the tiktoken encoding (downloaded on first use)
Set CONTINUUM_REQUIRE_ALL=1 (CI does) to turn any SKIPPED into a failure.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import time

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

# (group, script, extra args). Order matters only for readability of the report.
SUITES: list[tuple[str, str, list[str]]] = [
    ("harness", "mcp_server/token_budget.py", ["--validate"]),
    ("core", "mcp_server/traceability.py", []),
    ("harness", "mcp_server/scenario.py", []),
    ("core", "governance/test_store.py", []),
    ("core", "enforcement/test_enforce.py", []),
    ("core", "signal/test_conformance.py", []),
    ("core", "dashboard/test_rollup.py", []),
    ("core", "audit/test_audit_chain.py", []),
    ("core", "audit/test_anchor.py", []),
    ("core", "audit/test_history.py", []),
    ("core", "governance/test_retention.py", []),
    ("core", "governance/test_taskedit.py", []),
    ("core", "governance/test_authoring.py", []),
    ("core", "governance/test_binding.py", []),
    ("core", "governance/test_flow.py", []),
    ("core", "governance/test_subprocess.py", []),
    ("core", "governance/test_event.py", []),
    ("core", "governance/test_role.py", []),
    ("core", "governance/test_graphedit.py", []),
    ("core", "governance/test_group.py", []),
    ("core", "governance/test_approvals.py", []),
    ("core", "governance/test_approval_policy.py", []),
    ("core", "governance/test_capa.py", []),
    ("core", "governance/test_capa_enrich.py", []),
    ("core", "maps/test_mapdata.py", []),
    ("core", "maps/test_layout.py", []),
    ("core", "maps/test_landscape.py", []),
    ("core", "maps/test_architecture.py", []),
    ("core", "maps/test_strategy.py", []),
    ("core", "maps/test_portal.py", []),
    ("core", "bpmn/test_export.py", []),
    ("core", "bpmn/test_import.py", []),
    ("core", "bpmn/test_visio.py", []),
    ("core", "builder/test_build.py", []),
    ("core", "builder/test_bpc_import.py", []),
    ("core", "builder/test_importers.py", []),
    ("core", "builder/test_bpc_enrich.py", []),
    ("core", "mcp_server/test_typesafe.py", []),
    ("core", "advisor/test_advisor.py", []),
    ("core", "ask/test_agent.py", []),
    ("core", "test_run.py", []),
]

COUNT = re.compile(r"(\d+)\s+passed,\s+(\d+)\s+failed")


def _register_extra():
    """Suites added after D44 register themselves in tests/suites_extra.py so this
    file stays the one place that decides how suites run."""
    path = os.path.join(ROOT, "tests", "suites_extra.py")
    if os.path.isfile(path):
        ns: dict = {}
        with open(path) as f:
            exec(compile(f.read(), path, "exec"), ns)  # noqa: S102 - repo-owned registry
        SUITES.extend(ns.get("SUITES", []))


def _skip_reason(group: str) -> str | None:
    if group == "postgres" and not os.environ.get("CONTINUUM_TEST_DATABASE_URL"):
        return "CONTINUUM_TEST_DATABASE_URL not set"
    if group == "js" and not shutil.which("node"):
        return "node not on PATH"
    if group == "harness":
        try:
            import tiktoken  # noqa: F401
            tiktoken.get_encoding("cl100k_base")
        except Exception as e:  # network-blocked sandboxes cannot fetch the encoding
            return f"tiktoken encoding unavailable ({type(e).__name__})"
    return None


def main(argv=None) -> int:
    _register_extra()
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="comma-separated groups or script paths")
    ap.add_argument("--skip", help="comma-separated groups or script paths")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("-q", "--quiet", action="store_true", help="only print failures + summary")
    a = ap.parse_args(argv)

    def sel(spec):
        return {s.strip() for s in spec.split(",") if s.strip()} if spec else set()

    only, skip = sel(a.only), sel(a.skip)
    chosen = [s for s in SUITES
              if (not only or s[0] in only or s[1] in only)
              and not (s[0] in skip or s[1] in skip)]
    if a.list:
        for g, p, extra in chosen:
            print(f"{g:9s} {p} {' '.join(extra)}")
        return 0

    require_all = os.environ.get("CONTINUUM_REQUIRE_ALL") == "1"
    total_p = total_f = 0
    failed, skipped = [], []
    t0 = time.time()
    reasons: dict[str, str | None] = {}
    for group, path, extra in chosen:
        if group not in reasons:
            reasons[group] = _skip_reason(group)
        if reasons[group]:
            skipped.append((path, reasons[group]))
            print(f"SKIP  {path}  ({reasons[group]})")
            continue
        cmd = ["node", os.path.join(ROOT, path)] if path.endswith((".js", ".mjs")) else \
              [sys.executable, os.path.join(ROOT, path), *extra]
        r = subprocess.run(cmd, cwd=ROOT,
                           capture_output=True, text=True)
        out = r.stdout + r.stderr
        m = COUNT.findall(out)
        p_, f_ = (int(m[-1][0]), int(m[-1][1])) if m else (0, 0)
        ok = r.returncode == 0 and f_ == 0
        total_p += p_
        total_f += f_
        if not ok:
            failed.append(path)
            print(f"FAIL  {path}  ({p_} passed, {f_} failed, exit {r.returncode})")
            print("      " + "\n      ".join(out.strip().splitlines()[-25:]))
        elif not a.quiet:
            print(f"ok    {path}  ({p_} passed)" if m else f"ok    {path}")

    secs = time.time() - t0
    print()
    print(f"{len(chosen) - len(skipped)} suites run, {len(skipped)} skipped, {len(failed)} failed "
          f"— {total_p} assertions passed, {total_f} failed ({secs:.1f}s)")
    if skipped and require_all:
        print("CONTINUUM_REQUIRE_ALL=1: skipped suites count as failures")
        return 1
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
