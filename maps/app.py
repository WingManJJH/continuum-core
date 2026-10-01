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
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "mcp_server"))
sys.path.insert(0, os.path.join(HERE, "..", "governance"))
import continuum_core as cc  # noqa: E402
from mapdata import all_maps, landscape, roles as role_list, architecture  # noqa: E402
import strategy as strat  # noqa: E402  — OKR / X-matrix / alignment assembly
sys.path.insert(0, os.path.join(HERE, "..", "audit"))
import history as hist  # noqa: E402  — version history & compare
import layout  # noqa: E402  — decorative node positions (not a model edit)
import portal  # noqa: E402  — read-only share links (operational, not a model edit)
import store as gov  # noqa: E402  — the tested guardrail write path (one source of truth)
import approvals as approvals_mod  # noqa: E402  — approval-gate workflow (Phase 3)
import approval_policy as policy_mod  # noqa: E402  — which changes need approval (Phase 3)
import capa as capa_mod  # noqa: E402  — CAPA corrective/preventive action register (Phase 3)
import capa_enrich  # noqa: E402  — Jev (System One) enrichment of the CAPA insights
sys.path.insert(0, os.path.join(HERE, "..", "bpmn"))
import export as bpmn_export  # noqa: E402  — BPMN 2.0 XML export
import import_bpmn as bpmn_import  # noqa: E402  — BPMN 2.0 XML import
import visio_import as visio  # noqa: E402  — Visio .vsdx import
sys.path.insert(0, os.path.join(HERE, "..", "builder"))
import build as builder  # noqa: E402  — build a process from instructions
import bpc_enrich  # noqa: E402  — Jev (System One) governance enrichment
import typesafe  # noqa: E402  — the Jev seam (availability check)
sys.path.insert(0, os.path.join(HERE, "..", "web"))
import guard  # noqa: E402  — sign-in, workspaces, roles (D52); no-op when CONTINUUM_AUTH=off
import enterprise_api as ea_api  # noqa: E402  — EA / GRC modules + import review (D45/D51)
import versioned_import as vimport  # noqa: E402

STORE = gov.GovernanceStore()
QUEUE = approvals_mod.ApprovalQueue(STORE)  # change requests over the same store
POLICY = policy_mod.ApprovalPolicy()        # which entity types must be gated
CAPA = capa_mod.CAPAStore()                 # corrective/preventive action register (ISO 9001 §10.2)

# Active model persists across restarts (data/active_model.txt); the whole stack
# folds whichever model is active (default / an imported BPC model / SYSPRO / …).
_ACTIVE_FILE = os.path.join(cc.DATA_ROOT, "active_model.txt")
def _restore_active_model():
    try:
        with open(_ACTIVE_FILE) as f:
            slug = f.read().strip()
        if slug and slug in {m["slug"] for m in cc.list_models()}:
            cc.set_active_model(slug)
    except OSError:
        pass
_restore_active_model()

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

    def _gate_guard(self, entity_type):
        """Refuse a DIRECT edit whose entity type is policy-required — it must be
        submitted for approval instead. The gate's own approve path applies via the
        store directly and never passes through here, so approvals are unaffected."""
        if POLICY.requires_gate(entity_type):
            raise gov.EditError(
                f"Changes to {policy_mod.ENTITY_LABEL.get(entity_type, entity_type)} "
                "require approval — submit this change for review instead of saving directly.")

    def _ea(self, method, u, b=None):
        try:
            if method == "GET":
                return self._json(ea_api.get(STORE, u.path, parse_qs(u.query)))
            return self._json(ea_api.post(STORE, u.path, b or {}, self._gate_guard))
        except cc.ConflictError as e:
            return self._json_code({"ok": False, "conflict": True, "error": str(e)}, 409)
        except vimport.StaleError as e:
            return self._json_code({"ok": False, "conflict": True, "error": str(e)}, 409)
        except (gov.EditError, vimport.ImportError_, policy_mod.PolicyError, ValueError) as e:
            return self._json_code({"ok": False, "error": str(e)}, 400)

    def do_GET(self):
        u = urlparse(self.path)
        if ea_api.handles("GET", u.path):
            return self._ea("GET", u)
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
        if u.path == "/api/approvals":
            status = parse_qs(u.query).get("status", [None])[0] or None
            crs = QUEUE.list(status)
            if any(c["op"] == approvals_mod.IMPORT_OP for c in crs):   # D56: show the import diff in the inbox
                st = {x["sid"]: x for x in vimport.staged(cc.ACTIVE_MODEL, "all")}
                for c in crs:
                    if c["op"] == approvals_mod.IMPORT_OP:
                        x = st.get((c.get("args") or {}).get("sid"))
                        if x:
                            c["import"] = {k: x[k] for k in ("sid", "batch", "source", "etype", "id", "change",
                                                             "diff", "reasons", "status", "based_on_version")}
            return self._json({"approvals": crs,
                               "pending": QUEUE.pending_count(),
                               "ops": sorted(approvals_mod.PROPOSABLE_OPS)})
        if u.path == "/api/approval-policy":
            return self._json({"entities": POLICY.entities(), "modes": list(policy_mod.MODES),
                               "op_entity": policy_mod.OP_ENTITY})
        if u.path == "/api/models":
            return self._json({"models": cc.list_models(), "active": cc.ACTIVE_MODEL,
                               "jev": typesafe.available()})
        if u.path == "/api/capa":
            # the corrective-action register + owner notifications + AI insights,
            # all from the active model's folded graph (one source of truth).
            g = cc.Graph()
            q = parse_qs(u.query)
            proc = q.get("process", [None])[0]
            if proc:
                return self._json({"process": proc, "cars": CAPA.for_process(proc, g)})
            insights = CAPA.insights(g)
            jev_on = typesafe.available()
            if jev_on:
                # Jev only ADDS advisory findings; a hiccup never breaks the register.
                try:
                    insights = insights + capa_enrich.jev_insights(CAPA.open_cars(g))
                except Exception:  # noqa: BLE001
                    pass
            return self._json({"register": CAPA.register(g), "summary": CAPA.summary(g),
                               "notifications": CAPA.notifications(g),
                               "insights": insights, "jev": jev_on})
        if u.path == "/api/changes":
            return self._json({"changes": hist.model_changes()})
        if u.path == "/api/history":
            q = parse_qs(u.query)
            return self._json({"history": hist.entity_history(q.get("type", [""])[0], q.get("id", [""])[0])})
        if u.path == "/api/portal":
            # the author's manage list — every minted share link + its status
            return self._json({"links": portal.all_links(cc.Graph())})
        if u.path == "/api/portal/view":
            token = parse_qs(u.query).get("token", [""])[0]
            rec = portal.get(token)
            with cc.use_model((rec or {}).get("workspace") or cc.ACTIVE_MODEL, cc.current_user()):
                view = portal.portal_view(token, cc.Graph())
            if view is None:
                return self._json_code({"ok": False, "error": "This share link is unknown, "
                                        "revoked, or expired."}, 404)
            return self._json({"ok": True, "view": view})
        if u.path == "/api/stream":
            # Server-Sent Events: watch the three governance logs and push a typed
            # event when any grows, so every open board/canvas reflects a model
            # edit ("changed"), a new/decided change request ("approvals"), or an
            # approval-policy change ("policy") live. Each connection runs in its
            # own thread (ThreadingHTTPServer).
            def _size(p):
                try:
                    return cc.storage.get().size(p)   # file bytes or Postgres sequence: grows on every append
                except Exception:  # noqa: BLE001
                    return 0
            base = os.path.dirname(cc.EDITS_LOG)   # this request's model (per-user in multi-user mode)
            watched = [("changed", cc.EDITS_LOG), ("approvals", QUEUE.log_path),
                       ("policy", POLICY.log_path), ("imports", os.path.join(base, "staged.log.jsonl"))]
            try:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.end_headers()
                last = {name: _size(p) for name, p in watched}
                self.wfile.write(b"retry: 3000\ndata: hello\n\n")
                self.wfile.flush()
                while True:
                    time.sleep(1.5)
                    emitted = False
                    for name, p in watched:
                        cur = _size(p)
                        if cur != last[name]:
                            last[name] = cur
                            self.wfile.write(("data: %s\n\n" % name).encode())
                            emitted = True
                    if not emitted:
                        self.wfile.write(b": ping\n\n")   # comment heartbeat keeps the socket alive
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                return
            return
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
            self._gate_guard("GuardrailPolicy")
            new = STORE.edit_guardrail(
                parse_qs(u.query).get("id", [""])[0],
                changes=payload.get("changes", {}), actor=payload.get("actor", "role.unknown"),
                reason=payload.get("reason", ""), reviewer=payload.get("reviewer", ""))
            return self._json({"ok": True, "guardrail": new})
        except cc.ConflictError as e:
            return self._json_code({"ok": False, "conflict": True, "error": str(e)}, 409)
        except (gov.EditError, policy_mod.PolicyError) as e:
            return self._json_code({"ok": False, "error": str(e)}, 400)
        except Exception as e:  # noqa: BLE001
            return self._json_code({"ok": False, "error": repr(e)}, 500)

    def do_POST(self):
        # author / edit process STRUCTURE from the canvas — create a process, or
        # add / rename / reorder / remove a step — all through the versioned,
        # hash-chained governance write path.
        u = urlparse(self.path)
        try:
            length = max(0, int(self.headers.get("Content-Length", 0) or 0))
            b = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, RecursionError, UnicodeDecodeError):
            return self._json_code({"ok": False, "error": "invalid JSON body"}, 400)
        if not isinstance(b, dict):
            return self._json_code({"ok": False, "error": "the request body must be a JSON object"}, 400)
        if ea_api.handles("POST", u.path):
            return self._ea("POST", u, b)
        actor = b.get("actor", "role.ops.support_lead")
        reason = b.get("reason", "")
        try:
            if u.path == "/api/approvals":
                # the approval gate — propose a change (does not touch the model),
                # or approve (apply through the audited store) / reject / withdraw.
                op = b.get("op")
                if op == "propose":
                    cr = QUEUE.propose(b.get("target_op", ""), b.get("args", {}) or {},
                                       proposed_by=actor, reason=reason,
                                       title=b.get("title", ""), target=b.get("target", ""),
                                       assignee=b.get("assignee", ""))
                elif op == "assign":
                    cr = QUEUE.assign(b.get("id", ""), b.get("assignee", ""), actor=actor,
                                      reason=reason or "reassigned change request")
                elif op == "approve":
                    cr = QUEUE.approve(b.get("id", ""), reviewer=b.get("reviewer", actor),
                                       decision_reason=b.get("decision_reason", ""))
                elif op == "reject":
                    cr = QUEUE.reject(b.get("id", ""), reviewer=b.get("reviewer", actor),
                                      decision_reason=b.get("decision_reason", ""))
                elif op == "withdraw":
                    cr = QUEUE.withdraw(b.get("id", ""), actor=actor,
                                        decision_reason=b.get("decision_reason", ""))
                else:
                    return self._json_code({"ok": False, "error": f"unknown op {op}"}, 400)
                return self._json({"ok": True, "cr": cr, "pending": QUEUE.pending_count()})
            if u.path == "/api/approval-policy":
                pol = POLICY.set(b.get("entity", ""), b.get("mode", ""), actor,
                                 reason or "changed approval policy")
                return self._json({"ok": True, "entities": POLICY.entities()})
            if u.path == "/api/models":
                # switch the active model (default / an imported model). Whole stack
                # then folds that model; the choice persists across restarts.
                slug = b.get("slug", "default")
                if slug not in {m["slug"] for m in cc.list_models()}:
                    return self._json_code({"ok": False, "error": f"unknown model {slug}"}, 400)
                cc.set_active_model(slug)
                try:
                    with open(_ACTIVE_FILE, "w") as f:
                        f.write(cc.ACTIVE_MODEL)
                except OSError:
                    pass
                return self._json({"ok": True, "active": cc.ACTIVE_MODEL, "models": cc.list_models()})
            if u.path == "/api/capa":
                # corrective-action register writes — raise a CAR for a reported
                # error, edit its investigation/action fields, or move it through
                # the lifecycle. All via the versioned, hash-chained store (§7.5).
                op = b.get("op")
                if op == "raise":
                    r = CAPA.raise_car(b.get("title", ""), b.get("nonconformance", ""),
                                       b.get("source", "other"), b.get("severity", "minor"),
                                       b.get("owner_role", ""), b.get("affected_process_refs", []) or [],
                                       actor, reason or "raised a corrective action",
                                       date_due=b.get("date_due"), containment=b.get("containment", ""),
                                       risk_refs=b.get("risk_refs"))
                elif op == "edit":
                    r = CAPA.edit_car(b.get("id", ""), b.get("changes", {}) or {}, actor,
                                      reason or "updated the corrective action")
                elif op == "transition":
                    r = CAPA.transition(b.get("id", ""), b.get("to_state", ""), actor,
                                        reason or "advanced the corrective action")
                else:
                    return self._json_code({"ok": False, "error": f"unknown op {op}"}, 400)
                return self._json({"ok": True, "car": r})
            if u.path == "/api/enrich":
                # Jev (System One) governance enrichment of the ACTIVE model's
                # processes — advisory typed classifications written via the store.
                if not typesafe.available():
                    return self._json_code({"ok": False, "error":
                        "Jev isn't configured — set CONTINUUM_TYPESAFE_API_KEY to enable enrichment."}, 400)
                res = bpc_enrich.enrich(STORE, limit=b.get("limit"), dry=bool(b.get("dry")),
                                        actor=actor)
                return self._json({"ok": True, "model": cc.ACTIVE_MODEL, **res})
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
                        self._gate_guard("Process")
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
                    if apply:
                        self._gate_guard("Process")
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
                self._gate_guard("Process")
                r = STORE.add_process(b.get("code", ""), b.get("name", ""),
                                      b.get("owner", ""), actor, reason)
            elif u.path == "/api/task":
                self._gate_guard("Task")
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
                self._gate_guard("Structural")
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
                self._gate_guard("ProcessGroup")
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
                self._gate_guard("Process")
                r = STORE.edit_process(b["id"], b.get("changes", {}), actor, reason or "edited process header")
            elif u.path == "/api/correlation":
                self._gate_guard("Correlation")
                if b.get("op") == "clear":
                    r = STORE.clear_correlation(b["type"], b["a"], b["b"], actor, reason or "cleared X-matrix cell")
                else:
                    r = STORE.set_correlation(b["type"], b["a"], b["b"], b.get("strength", "primary"),
                                              actor, reason or "set X-matrix cell")
            elif u.path == "/api/enterprise":
                self._gate_guard("Enterprise")
                r = STORE.edit_enterprise(b.get("changes", {}), actor, reason or "edited enterprise")
            elif u.path == "/api/objective":
                self._gate_guard("StrategicObjective")
                r = STORE.edit_objective(b["id"], b.get("changes", {}), actor, reason or "edited objective")
            elif u.path == "/api/kpi":
                self._gate_guard("KPI")
                r = STORE.edit_kpi(b["id"], b.get("changes", {}), actor, reason or "edited KPI")
            elif u.path == "/api/initiative":
                self._gate_guard("Initiative")
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
                self._gate_guard("HumanRole")
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
                self._gate_guard("Structural")
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
                self._gate_guard("Structural")
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
        except cc.ConflictError as e:
            return self._json_code({"ok": False, "conflict": True, "error": str(e)}, 409)
        except (gov.EditError, approvals_mod.ApprovalError, policy_mod.PolicyError) as e:
            return self._json_code({"ok": False, "error": str(e)}, 400)
        except Exception as e:  # noqa: BLE001
            return self._json_code({"ok": False, "error": repr(e)}, 500)


def main():
    port = 8789
    if "--port" in sys.argv:
        port = int(sys.argv[sys.argv.index("--port") + 1])
    ThreadingHTTPServer((guard.host(), port), guard.protect(Handler, "canvas")).serve_forever()


if __name__ == "__main__":
    print("Continuum Process Maps on http://localhost:8789")
    main()
