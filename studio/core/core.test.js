const test = require("node:test");
const assert = require("node:assert/strict");
const C = require("./continuum-core.js");
const ISO = require("./iso-packs.js");
const { loadSeedWorkspace } = require("./test-helpers.js");
const TODAY = "2026-09-30";

function ws() { const w = loadSeedWorkspace(); C.ensureWorkspace(w, ISO); return w; }

test("ensureWorkspace is idempotent and seeds packs, examples, risks", () => {
  const w = loadSeedWorkspace();
  const ch = C.ensureWorkspace(w, ISO);
  assert.ok(ch.includes("registry-created"));
  assert.equal(Object.values(w.registry.obligations).filter((o) => o.pack === "iso9001").length, 28);
  assert.equal(Object.values(w.registry.obligations).filter((o) => o.pack === "iso9004").length, 33);
  assert.equal(Object.keys(w.registry.risks).length, 4);
  assert.deepEqual(w.processes.proc_onboarding.links.riskIds.length, 2);
  const snap = JSON.stringify(w);
  const ch2 = C.ensureWorkspace(w, ISO);
  assert.deepEqual(ch2, []);
  assert.equal(JSON.stringify(w), snap);
});

test("no ISO verbatim text: every summary is short own wording", () => {
  Object.values(ISO.packs).forEach((pk) => pk.obligations.forEach((o) => {
    assert.ok(o.summary.length < 160, o.id);
    assert.match(o.id, /^obl_iso900[14]_\d+_\d+$/);
  }));
});

test("risk migration keeps riskRefs in sync with linked risk names", () => {
  const w = ws();
  assert.equal(w.processes.proc_onboarding.riskRefs, "Late IT provisioning, Missed compliance training");
  C.removeRefs(w, "rsk_late_it_provisioning");
  assert.equal(w.processes.proc_onboarding.riskRefs, "Missed compliance training");
});

test("every edge points at real nodes", () => {
  const w = ws(); const idx = C.nodeIndex(w);
  const E = C.edges(w);
  assert.ok(E.length > 30);
  E.forEach((e) => { assert.ok(idx[e.s], e.s); assert.ok(idx[e.t], e.t); });
});

test("Ripple: retiring Legacy Helpdesk reaches task, process, capability, control, obligation, risk, KPIs", () => {
  const w = ws();
  const r = C.ripple(w, "app_legacy_helpdesk");
  const ids = r.affected.map((a) => a.id);
  assert.ok(ids.includes("proc_complaint::Task_InvestigateResolve"));
  assert.ok(ids.includes("proc_complaint"));
  assert.ok(ids.includes("cap_case_mgmt"));
  assert.ok(ids.includes("ctl_root_cause"));
  assert.ok(ids.includes("obl_iso9001_10_2"));
  assert.ok(ids.includes("rsk_repeat_unresolved_complaints"));
  assert.ok(r.kpis.length >= 2);
  // an agent on an untouched sibling task is NOT affected
  assert.ok(!ids.includes("agt_triage"));
  // applies_to is not followed from a non-start obligation (no fan-out to onboarding)
  assert.ok(!ids.includes("proc_onboarding"));
  const ctl = r.affected.find((a) => a.id === "ctl_root_cause");
  assert.deepEqual(ctl.path.map((p) => p.verb), ["supports", "hosts control"]);
  assert.match(r.summary, /Legacy Helpdesk reaches/);
});

test("Ripple: an obligation change surfaces processes, controls and the tasks they run in", () => {
  const w = ws();
  const r = C.ripple(w, "obl_iso9001_10_2");
  const ids = r.affected.map((a) => a.id);
  assert.ok(ids.includes("proc_complaint"));
  assert.ok(ids.includes("ctl_root_cause"));
  assert.ok(ids.includes("proc_complaint::Task_InvestigateResolve"));
});

test("Ripple: capability is shown upstream (what it depends on)", () => {
  const w = ws();
  const r = C.ripple(w, "cap_customer");
  assert.equal(r.mode, "upstream");
  const ids = r.affected.map((a) => a.id);
  ["cap_case_mgmt", "proc_complaint", "app_crm_service", "app_legacy_helpdesk"].forEach((x) => assert.ok(ids.includes(x), x));
});

test("Ripple: guardrails of bound agents are reported with their version", () => {
  const w = ws();
  const r = C.ripple(w, "app_crm_service");
  const g = r.guardrails.find((x) => x.taskId === "proc_complaint::Task_LogComplaint");
  assert.ok(g); assert.deepEqual(g.agents, ["Complaint Triage Agent"]);
  assert.ok(r.affected.some((a) => a.id === "agt_triage" && a.bindingOnly)); assert.equal(g.version, "gr.proc_complaint.v3");
});

test("Assure: statuses follow evidence rules", () => {
  const w = ws();
  const a = C.assure(w, TODAY);
  const p9001 = a.packs.find((p) => p.source === "ISO 9001:2015");
  const row = (c) => p9001.rows.find((r) => r.obligation.clause === c);
  assert.equal(row("7.5").status, "covered");
  assert.equal(row("10.2").status, "covered"); // approved complaint process on record
  assert.equal(row("5.2").status, "gap");
  assert.equal(p9001.total, 28);
  // make the 7.5 control fail → partial
  w.registry.controls.ctl_doc_approval.lastResult = "fail";
  assert.equal(C.assure(w, TODAY).packs.find((p) => p.source === "ISO 9001:2015").rows.find((r) => r.obligation.clause === "7.5").status, "partial");
  // clause order is numeric, not lexical (10.x after 9.x)
  const clauses = p9001.rows.map((r) => r.obligation.clause);
  assert.ok(clauses.indexOf("9.3") < clauses.indexOf("10.1"));
});

test("Vitals: flags the seeded problems and computes a score", () => {
  const w = ws();
  const v = C.vitals(w, TODAY);
  const rules = v.findings.map((f) => f.rule + ":" + f.nodeId);
  assert.ok(rules.includes("app-sunset-in-use:app_legacy_helpdesk"));
  assert.ok(rules.includes("app-owner:app_legacy_helpdesk"));
  assert.ok(rules.includes("control-untested:ctl_root_cause"));
  assert.ok(v.score > 0 && v.score < 100);
  // an agent on a task with no guardrail anywhere is critical
  const p = w.processes.proc_complaint; p.guardrail = { allow: "", deny: "", escalateIf: "" };
  const v2 = C.vitals(w, TODAY);
  assert.ok(v2.findings.some((f) => f.rule === "agent-unguarded" && f.severity === "critical"));
  // retired system still in use is critical
  w.registry.applications.app_legacy_helpdesk.lifecycle = "retired";
  assert.ok(C.vitals(w, TODAY).findings.some((f) => f.rule === "app-retired-in-use" && f.severity === "critical"));
});

test("Atlas: tree, maturity roll-up and overlap detection", () => {
  const w = ws();
  const t = C.atlas(w);
  const cust = t.find((c) => c.id === "cap_customer");
  const cm = cust.children.find((c) => c.id === "cap_case_mgmt");
  assert.equal(cm.maturity, 4);
  assert.equal(cm.overlap, null); // legacy helpdesk is sunset, not active
  w.registry.applications.app_legacy_helpdesk.lifecycle = "active";
  const cm2 = C.atlas(w).find((c) => c.id === "cap_customer").children.find((c) => c.id === "cap_case_mgmt");
  assert.deepEqual(cm2.overlap.sort(), ["Legacy Helpdesk", "Salesforce Service Cloud"]);
});

test("Guardrail actions are structured slugs; task override wins per field", () => {
  const w = ws();
  const g = C.effectiveGuardrail(w.processes.proc_onboarding, "Task_ProvisionAccounts");
  assert.equal(g.source, "task");
  assert.deepEqual(g.allowActions.map((a) => a.id), ["create_standard_accounts_from_the_approved_role_template"]);
  const gp = C.effectiveGuardrail(w.processes.proc_onboarding, "Task_Welcome");
  assert.equal(gp.source, "process");
  assert.equal(gp.allowActions.length, 2);
});

test("taskContext stays compact and includes EA/GRC links", () => {
  const w = ws();
  const ctx = C.taskContext(w, "proc_onboarding", "Task_ProvisionAccounts");
  assert.deepEqual(ctx.systems, ["app_entra", "app_itsm"]);
  assert.deepEqual(ctx.controls, ["ctl_access_review"]);
  const approxTokens = JSON.stringify(ctx).length / 4;
  assert.ok(approxTokens < 150 * 1.6, "context package size " + approxTokens);
});

/* ---- regressions from the independent review ---- */

test("review: guardrail phrases keep thousands separators", () => {
  assert.deepEqual(C.parseGuardrailActions("Issue refunds up to $1,000, log complaint").map((a) => a.id), ["issue_refunds_up_to_1_000", "log_complaint"]);
});

test("review: a future test date is not evidence", () => {
  const w = ws();
  w.registry.controls.ctl_doc_approval.lastTested = "2027-01-01";
  const r = C.assure(w, TODAY).packs.find((p) => p.source === "ISO 9001:2015").rows.find((x) => x.obligation.clause === "7.5");
  assert.equal(r.status, "partial");
});

test("review: capability parent cycles never hide a subtree", () => {
  const w = ws();
  w.registry.capabilities.cap_workforce.parentId = "cap_talent_onboarding";
  const ids = []; (function walk(n) { n.forEach((c) => { ids.push(c.id); walk(c.children); }); })(C.atlas(w));
  ["cap_workforce", "cap_talent_onboarding", "cap_learning"].forEach((id) => assert.ok(ids.includes(id), id));
  C.ripple(w, "cap_workforce"); // terminates
});

test("review: deleting a parent capability promotes its children to level 1", () => {
  const w = ws();
  C.removeRefs(w, "cap_customer"); delete w.registry.capabilities.cap_customer;
  assert.equal(w.registry.capabilities.cap_case_mgmt.parentId, "");
  assert.equal(w.registry.capabilities.cap_case_mgmt.level, 1);
});

test("review: an agent bound to a process with no guardrail is critical", () => {
  const w = ws();
  w.processes.proc_onboarding.links.applicationIds.push("agt_triage");
  w.processes.proc_onboarding.guardrail = { allow: "", deny: "", escalateIf: "" };
  assert.ok(C.vitals(w, TODAY).findings.some((f) => f.rule === "agent-unguarded" && f.nodeId === "agt_triage"));
});

test("review: Ripple from a task lists the agent bound to it", () => {
  const w = ws();
  const r = C.ripple(w, "proc_onboarding::Task_ScheduleOrientation");
  assert.ok(r.affected.some((a) => a.id === "agt_onboarding"));
});

test("review: capability upstream includes systems used by its processes' tasks", () => {
  const w = ws();
  const ids = C.ripple(w, "cap_talent_onboarding").affected.map((a) => a.id);
  assert.ok(ids.includes("app_entra") && ids.includes("app_itsm"));
});

test("review: task context refuses tasks that do not exist", () => {
  const w = ws();
  assert.equal(C.taskContext(w, "proc_onboarding", "DoesNotExist"), null);
});

test("review: obligation labels never print undefined", () => {
  const w = ws();
  w.registry.obligations.obl_x = { id: "obl_x", title: "Retain records 7y" };
  assert.equal(C.nodeIndex(w).obl_x.name, "Retain records 7y");
});

test("review: commas between items split, thousands do not, both orders", () => {
  assert.deepEqual(C.splitList("Close case,2nd-line review; refunds to $1,000"), ["Close case", "2nd-line review", "refunds to $1,000"]);
});

test("review: only cycle members are promoted; descendants keep their parent", () => {
  const w = ws();
  w.registry.capabilities.cap_workforce.parentId = "cap_talent_onboarding";
  const P = C.capabilityParents(w.registry.capabilities);
  assert.equal(P.cap_learning, "cap_workforce");
  assert.equal(P.cap_workforce, "");
  assert.equal(P.cap_talent_onboarding, "");
});

test("tasksFromBpmnXml matches the browser's task derivation", () => {
  const w = ws();
  const t = C.tasksFromBpmnXml(w.processes.proc_onboarding.bpmnXml).map((x) => x.id).sort();
  assert.deepEqual(t, w.processes.proc_onboarding.tasks.map((x) => x.id).sort());
});
