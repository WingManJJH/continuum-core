"""
Process Maps — Core Model §03 "Canvas View" (in-app, first slice).

Renders every process in the model as a BPMN-style flow diagram: start -> tasks
-> end, with the agent-bound step highlighted, its guardrail escalation branch to
a human, task-level overrides marked, and a per-process header (owner, guardrail
version, KPIs, linked risk). Redrawn from the live graph on each load. Read-only.

Runs alongside governance (:8787) and dashboard (:8788).

    python3 app.py            # http://localhost:8789
    python3 app.py --port N
"""
from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "mcp_server"))
sys.path.insert(0, os.path.join(HERE, "..", "governance"))
import continuum_core as cc  # noqa: E402
from mapdata import all_maps, landscape, roles as role_list, architecture  # noqa: E402
import strategy as strat  # noqa: E402  — OKR / X-matrix / alignment assembly
import layout  # noqa: E402  — decorative node positions (not a model edit)
import portal  # noqa: E402  — read-only share links (operational, not a model edit)
import store as gov  # noqa: E402  — the tested guardrail write path (one source of truth)
sys.path.insert(0, os.path.join(HERE, "..", "bpmn"))
import export as bpmn_export  # noqa: E402  — BPMN 2.0 XML export
import import_bpmn as bpmn_import  # noqa: E402  — BPMN 2.0 XML import
import visio_import as visio  # noqa: E402  — Visio .vsdx import
sys.path.insert(0, os.path.join(HERE, "..", "builder"))
import build as builder  # noqa: E402  — build a process from instructions

STORE = gov.GovernanceStore()

STATIC = os.path.join(HERE, "static")
CONTENT = {".html": "text/html", ".js": "text/javascript", ".css": "text/css"}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj):
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _static(self, path):
        fname = "index.html" if path in ("/", "") else path.lstrip("/")
        full = os.path.normpath(os.path.join(STATIC, fname))
        if not full.startswith(STATIC) or not os.path.isfile(full):
            return self.send_error(404)
        with open(full, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", CONTENT.get(os.path.splitext(full)[1], "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json_code(self, obj, code):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/api/maps":
            g = cc.Graph()
            return self._json({"model_sig": g.model_sig, "processes": all_maps(g)})
        if u.path == "/api/landscape":
            return self._json({"landscape": landscape(cc.Graph())})
        if u.path == "/api/roles":
            return self._json({"roles": role_list(cc.Graph())})
        if u.path == "/api/architecture":
            return self._json({"architecture": architecture(cc.Graph())})
        if u.path == "/api/strategy":
            g = cc.Graph()
            return self._json({"strategy": strat.strategy(g), "xmatrix": strat.xmatrix(g)})
        if u.path == "/api/portal":
            # the author's manage list — every minted share link + its status
            return self._json({"links": portal.all_links(cc.Graph())})
        if u.path == "/api/portal/view":
            token = parse_qs(u.query).get("token", [""])[0]
            view = portal.portal_view(token, cc.Graph())
            if view is None:
                return self._json_code({"ok": False, "error": "This share link is unknown, "
                                        "revoked, or expired."}, 404)
            return self._json({"ok": True, "view": view})
        if u.path in ("/portal", "/portal.html"):
            return self._static("/portal.html")
        if u.path == "/api/export/bpmn":
            pid = parse_qs(u.query).get("process", [""])[0]
            try:
                xml = bpmn_export.export_process(pid, cc.Graph())
            except ValueError as e:
                return self._json_code({"ok": False, "error": str(e)}, 404)
            body = xml.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/xml; charset=utf-8")
            self.send_header("Content-Disposition",
                             'attachment; filename="' + pid.replace(".", "_") + '.bpmn"')
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        return self._static(u.path)

    def do_PUT(self):
        # edit a guardrail from the canvas — same tested write path as governance,
        # so the edit is versioned, on the §7.5 trail, and live for the redraw.
        u = urlparse(self.path)
        if u.path != "/api/guardrail":
            return self.send_error(404)
        length = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length) or b"{}")
        try:
            new = STORE.edit_guardrail(
                parse_qs(u.query).get("id", [""])[0],
                changes=payload.get("changes", {}), actor=payload.get("actor", "role.unknown"),
                reason=payload.get("reason", ""), reviewer=payload.get("reviewer", ""))
            return self._json({"ok": True, "guardrail": new})
        except gov.EditError as e:
            return self._json_code({"ok": False, "error": str(e)}, 400)
        except Exception as e:  # noqa: BLE001
            return self._json_code({"ok": False, "error": repr(e)}, 500)

    def do_POST(self):
        # author / edit process STRUCTURE from the canvas — create a process, or
        # add / rename / reorder / remove a step — all through the versioned,
        # hash-chained governance write path.
        u = urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0))
        b = json.loads(self.rfile.read(length) or b"{}")
        actor = b.get("actor", "role.ops.support_lead")
        reason = b.get("reason", "")
        try:
            if u.path == "/api/layout":
                # decorative node positions only — NOT a model edit, so it does not
                # go through the governance store, the version chain, or the audit log.
                if b.get("op") == "reset":
                    layout.reset_process(b.get("process", ""))
                    return self._json({"ok": True, "layout": {}})
                saved = layout.save_process(b.get("process", ""), b.get("positions", {}))
                return self._json({"ok": True, "layout": saved})
            if u.path == "/api/portal":
                # mint / revoke a read-only share link — operational, NOT a model
                # edit, so (like layout) it bypasses the governance write path.
                try:
                    if b.get("op") == "revoke":
                        return self._json({"ok": True, "revoked": portal.revoke(b.get("token", ""))})
                    rec = portal.publish(b.get("target", ""), b.get("title", ""), actor,
                                         g=cc.Graph(), ttl_days=b.get("ttl_days"))
                    return self._json({"ok": True, "link": rec})
                except ValueError as e:
                    return self._json_code({"ok": False, "error": str(e)}, 400)
            if u.path == "/api/build":
                # build a process from instructions. op=plan is a write-free
                # dry-run (returns the deduced plan + assumptions); op=apply creates
                # it via the audited write path from the parsed plan the client previewed.
                try:
                    if b.get("op") == "apply":
                        res = builder.apply_build(b.get("parsed", {}), code=(b.get("code") or None),
                                                  owner=(b.get("owner") or None), actor=actor,
                                                  reason=reason or "built from instructions", store=STORE)
                        return self._json({"ok": True, "result": res})
                    return self._json({"ok": True, **builder.plan_build(b.get("text", ""),
                                                                        use_llm=bool(b.get("use_llm")))})
                except (ValueError, gov.EditError) as e:
                    return self._json_code({"ok": False, "error": str(e)}, 400)
            if u.path == "/api/import/bpmn":
                # bring a BPMN 2.0 XML file OR a Visio .vsdx into the model. op=plan
                # is a write-free dry-run; op=apply creates a new process via the
                # audited write path. format="vsdx" carries the file as base64.
                try:
                    apply = b.get("op") == "apply"
                    if b.get("format") == "vsdx":
                        import base64
                        data = base64.b64decode(b.get("data_b64", ""))
                        if apply:
                            res = visio.apply_vsdx(data, code=(b.get("code") or None),
                                                   owner=(b.get("owner") or None), actor=actor,
                                                   reason=reason or "imported from Visio", store=STORE)
                            return self._json({"ok": True, "result": res})
                        return self._json({"ok": True, "plan": visio.plan_vsdx(data)})
                    if apply:
                        res = bpmn_import.apply_import(b.get("xml", ""), code=(b.get("code") or None),
                                                       owner=(b.get("owner") or None), actor=actor,
                                                       reason=reason or "imported from BPMN 2.0", store=STORE)
                        return self._json({"ok": True, "result": res})
                    return self._json({"ok": True, "plan": bpmn_import.plan_import(b.get("xml", ""))})
                except (bpmn_import.ImportError_, gov.EditError) as e:
                    return self._json_code({"ok": False, "error": str(e)}, 400)
            if u.path == "/api/process":
                r = STORE.add_process(b.get("code", ""), b.get("name", ""),
                                      b.get("owner", ""), actor, reason)
            elif u.path == "/api/task":
                op = b.get("op")
                if op == "edit":
                    r = STORE.edit_task(b["id"], b.get("changes", {}), actor, reason)
                elif op == "add":
                    r = STORE.add_task(b["process"], b.get("name", ""), actor, reason,
                                       after=b.get("after"))
                elif op == "move":
                    r = STORE.move_task(b["id"], b.get("dir", "up"), actor, reason or "reorder step")
                elif op == "remove":
                    r = STORE.remove_task(b["id"], actor, reason)
                elif op == "bind":
                    r = STORE.bind_agent(b["id"], actor, reason or "make step agent-run")
                elif op == "unbind":
                    r = STORE.unbind_agent(b["id"], actor, reason or "make step human-only")
                else:
                    return self._json_code({"ok": False, "error": f"unknown op {op}"}, 400)
            elif u.path == "/api/gateway":
                op = b.get("op")
                if op == "add":
                    r = STORE.add_gateway(b["process"], b.get("gtype", "exclusive"), actor,
                                          reason or "added gateway via canvas", name=b.get("name", ""))
                elif op == "edit":
                    r = STORE.edit_gateway(b["id"], b.get("changes", {}), actor,
                                           reason or "edited gateway via canvas")
                elif op == "remove":
                    r = STORE.remove_gateway(b["id"], actor, reason or "removed gateway via canvas")
                else:
                    return self._json_code({"ok": False, "error": f"unknown op {op}"}, 400)
            elif u.path == "/api/group":
                op = b.get("op")
                if op == "add":
                    r = STORE.add_group(b.get("id", ""), b.get("name", ""), b.get("level", 1), actor,
                                        reason or "added process group", parent_ref=b.get("parent_ref"),
                                        owner_role=b.get("owner_role"), objective_refs=b.get("objective_refs"),
                                        description=b.get("description", ""))
                elif op == "edit":
                    r = STORE.edit_group(b["id"], b.get("changes", {}), actor, reason or "edited process group")
                elif op == "remove":
                    r = STORE.remove_group(b["id"], actor, reason or "retired process group")
                else:
                    return self._json_code({"ok": False, "error": f"unknown op {op}"}, 400)
            elif u.path == "/api/process/edit":
                r = STORE.edit_process(b["id"], b.get("changes", {}), actor, reason or "edited process header")
            elif u.path == "/api/enterprise":
                r = STORE.edit_enterprise(b.get("changes", {}), actor, reason or "edited enterprise")
            elif u.path == "/api/objective":
                r = STORE.edit_objective(b["id"], b.get("changes", {}), actor, reason or "edited objective")
            elif u.path == "/api/kpi":
                r = STORE.edit_kpi(b["id"], b.get("changes", {}), actor, reason or "edited KPI")
            elif u.path == "/api/initiative":
                op = b.get("op")
                if op == "add":
                    r = STORE.add_initiative(b.get("id", ""), b.get("name", ""), actor, reason or "added initiative",
                                             objective_refs=b.get("objective_refs"), process_refs=b.get("process_refs"),
                                             owner_role=b.get("owner_role"), description=b.get("description", ""))
                elif op == "edit":
                    r = STORE.edit_initiative(b["id"], b.get("changes", {}), actor, reason or "edited initiative")
                elif op == "remove":
                    r = STORE.remove_initiative(b["id"], actor, reason or "retired initiative")
                else:
                    return self._json_code({"ok": False, "error": f"unknown op {op}"}, 400)
            elif u.path == "/api/role":
                op = b.get("op")
                if op == "add":
                    r = STORE.add_role(b.get("id", ""), b.get("name", ""), actor,
                                       reason or "added role via canvas",
                                       raci=b.get("raci"), skills=b.get("skills"))
                elif op == "edit":
                    r = STORE.edit_role(b["id"], b.get("changes", {}), actor,
                                        reason or "edited role via canvas")
                elif op == "remove":
                    r = STORE.remove_role(b["id"], actor, reason or "retired role via canvas")
                else:
                    return self._json_code({"ok": False, "error": f"unknown op {op}"}, 400)
            elif u.path == "/api/event":
                op = b.get("op")
                if op == "add":
                    r = STORE.add_event(b["process"], b.get("kind", "intermediate"),
                                        b.get("trigger", "timer"), actor,
                                        reason or "added event via canvas", name=b.get("name", ""),
                                        timer=b.get("timer"), message_ref=b.get("message_ref"))
                elif op == "edit":
                    r = STORE.edit_event(b["id"], b.get("changes", {}), actor,
                                         reason or "edited event via canvas")
                elif op == "remove":
                    r = STORE.remove_event(b["id"], actor, reason or "removed event via canvas")
                else:
                    return self._json_code({"ok": False, "error": f"unknown op {op}"}, 400)
            elif u.path == "/api/flow":
                op = b.get("op")
                if op == "add":
                    r = STORE.add_flow(b["process"], b["from"], b["to"], actor,
                                       reason or "drew flow via canvas", condition=b.get("condition"))
                elif op == "edit":
                    r = STORE.edit_flow(b["id"], b.get("changes", {}), actor,
                                        reason or "edited flow via canvas")
                elif op == "remove":
                    r = STORE.remove_flow(b["id"], actor, reason or "removed flow via canvas")
                elif op == "enable":
                    r = STORE.enable_branching(b["process"], actor, reason or "enabled branching via canvas")
                else:
                    return self._json_code({"ok": False, "error": f"unknown op {op}"}, 400)
            else:
                return self.send_error(404)
            return self._json({"ok": True, "result": r})
        except gov.EditError as e:
            return self._json_code({"ok": False, "error": str(e)}, 400)
        except Exception as e:  # noqa: BLE001
            return self._json_code({"ok": False, "error": repr(e)}, 500)


def main():
    port = 8789
    if "--port" in sys.argv:
        port = int(sys.argv[sys.argv.index("--port") + 1])
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    print("Continuum Process Maps on http://localhost:8789")
    main()
