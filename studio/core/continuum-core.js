/* ==========================================================================
   Continuum core — the one model behind Studio and the Postgres platform.

   Pure functions over a "workspace" object:
     { processes: { [id]: Process }, order: [id], registry: Registry }
   Process.tasks = [{ id, name, type }] is supplied by the caller (Studio
   derives it from the BPMN XML; the platform from task nodes).

   Edge storage is canonical — each relationship lives in exactly one place
   (see edges()) so there is never a second copy to drift:
     process.links.capabilityIds   process  —realizes→     capability
     process.links.applicationIds  app      —supports→     process
     process.links.obligationIds   obligation —applies_to→ process
     process.links.riskIds         risk     —affects→      process
     elementGovernance[el].links.applicationIds  app —supports→ task
     elementGovernance[el].links.controlIds      control —implemented_in→ task
     application.capabilityIds     app      —serves→       capability
     application.obligationIds     obligation —applies_to→ app
     application.riskIds           risk     —affects→      app
     control.obligationIds         control  —satisfies→    obligation
     control.riskIds               control  —mitigates→    risk
     capability.parentId           capability —part_of→    capability
   ========================================================================== */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.ContinuumCore = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  var REGISTRY_KEYS = ["capabilities", "applications", "obligations", "controls", "risks"];
  var TYPE_OF_KEY = { capabilities: "capability", applications: "application", obligations: "obligation", controls: "control", risks: "risk" };
  var KEY_OF_TYPE = { capability: "capabilities", application: "applications", obligation: "obligations", control: "controls", risk: "risks" };
  var PROC_LINK_KEYS = ["capabilityIds", "applicationIds", "obligationIds", "riskIds"];
  var EL_LINK_KEYS = ["applicationIds", "controlIds"];

  var LIFECYCLE = ["plan", "active", "sunset", "retired"];
  var STATUS_LABEL = { draft: "Draft", in_review: "In review", approved: "Approved", effective: "Effective", superseded: "Superseded" };
  var FREQ_DAYS = { daily: 1, weekly: 7, monthly: 31, quarterly: 92, semiannual: 183, annual: 366 };

  /* ---------------- small helpers ---------------- */

  function own(o, k) { return Object.prototype.hasOwnProperty.call(o, k); }
  function vals(o) { return o ? Object.keys(o).map(function (k) { return o[k]; }) : []; }
  function arr(a) { return Array.isArray(a) ? a : []; }
  function uniq(a) { var s = {}, out = []; a.forEach(function (x) { if (!s[x]) { s[x] = 1; out.push(x); } }); return out; }
  function splitList(str) {
    // commas separate items, except between digits ("refunds up to $1,000")
    return String(str || "").split(/[;\n]|(?<!\d),|,(?!\d)/).map(function (s) { return s.trim(); }).filter(Boolean);
  }
  function slug(str) {
    return String(str || "").toLowerCase().replace(/&amp;/g, "and").replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 64).replace(/_+$/, "") || "item";
  }
  function dayNum(iso) { var t = Date.parse(String(iso || "").slice(0, 10)); return isNaN(t) ? null : Math.floor(t / 864e5); }
  function taskNodeId(procId, elId) { return procId + "::" + elId; }
  function parseTaskNodeId(id) { var i = String(id).indexOf("::"); return i < 0 ? null : { procId: id.slice(0, i), elementId: id.slice(i + 2) }; }
  function decodeEntities(s) { return String(s || "").replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&#39;/g, "'"); }

  function emptyRegistry() {
    return { capabilities: {}, applications: {}, obligations: {}, controls: {}, risks: {} };
  }

  /* ---------------- guardrails ---------------- */

  /** Structured action taxonomy (E1): each comma/semicolon/newline-separated
   *  phrase in a guardrail field becomes an action with a stable slug id.
   *  The prose stays the editing surface; agents match on ids. */
  function parseGuardrailActions(text) {
    return splitList(text).map(function (label) { return { id: slug(label), label: label }; });
  }

  function isBlankGuardrail(g) {
    return !g || (!String(g.allow || "").trim() && !String(g.deny || "").trim() && !String(g.escalateIf || "").trim());
  }

  /** Task override wins field-by-field; blank fields inherit the process default. */
  function effectiveGuardrail(proc, elementId) {
    var pg = proc.guardrail || {};
    var eg = elementId && proc.elementGovernance && proc.elementGovernance[elementId] ? proc.elementGovernance[elementId].guardrail || {} : {};
    function pick(k) { return String(eg[k] || "").trim() ? eg[k] : pg[k] || ""; }
    var g = { allow: pick("allow"), deny: pick("deny"), escalateIf: pick("escalateIf") };
    g.source = String(eg.allow || eg.deny || eg.escalateIf || "").trim() ? "task" : "process";
    g.allowActions = parseGuardrailActions(g.allow);
    g.denyActions = parseGuardrailActions(g.deny);
    return g;
  }

  /* ---------------- workspace shape & migration ---------------- */

  function ensureProcLinks(proc) {
    if (!proc.links) proc.links = {};
    PROC_LINK_KEYS.forEach(function (k) { if (!Array.isArray(proc.links[k])) proc.links[k] = []; });
    if (proc.elementGovernance) {
      Object.keys(proc.elementGovernance).forEach(function (el) {
        var eg = proc.elementGovernance[el];
        if (!eg.links) eg.links = {};
        EL_LINK_KEYS.forEach(function (k) { if (!Array.isArray(eg.links[k])) eg.links[k] = []; });
      });
    }
  }

  function ensureElementLinks(proc, elementId) {
    if (!proc.elementGovernance) proc.elementGovernance = {};
    if (!proc.elementGovernance[elementId]) {
      proc.elementGovernance[elementId] = { ownerRole: "", inputs: "", outputs: "", kpiRefs: "", guardrail: { allow: "", deny: "", escalateIf: "" } };
    }
    var eg = proc.elementGovernance[elementId];
    if (!eg.links) eg.links = {};
    EL_LINK_KEYS.forEach(function (k) { if (!Array.isArray(eg.links[k])) eg.links[k] = []; });
    return eg;
  }

  /** Converts free-text riskRefs into real risk objects (E1 acceptance:
   *  "migration converts existing risk_refs"). riskRefs is kept, and
   *  afterwards re-derived from linked risk names, so older exports and the
   *  reference MCP server keep working. Returns the number of risks created. */
  function migrateRiskRefs(ws) {
    var created = 0;
    var byName = {};
    vals(ws.registry.risks).forEach(function (r) { byName[r.name.toLowerCase()] = r.id; });
    vals(ws.processes).forEach(function (proc) {
      ensureProcLinks(proc);
      if (proc.links.riskIds.length) return;
      splitList(proc.riskRefs).forEach(function (name) {
        var key = name.toLowerCase();
        var id = byName[key];
        if (!id) {
          id = "rsk_" + slug(name);
          var n = 2;
          while (ws.registry.risks[id]) id = "rsk_" + slug(name) + "_" + n++;
          ws.registry.risks[id] = { id: id, name: name, owner: proc.ownerRole || "", likelihood: 3, impact: 3, treatment: "mitigate", notes: "Migrated from the process's free-text risk references." };
          byName[key] = id;
          created++;
        }
        if (proc.links.riskIds.indexOf(id) < 0) proc.links.riskIds.push(id);
      });
    });
    return created;
  }

  function syncRiskRefs(ws, proc) {
    proc.riskRefs = arr(proc.links && proc.links.riskIds).map(function (id) { return ws.registry.risks[id] && ws.registry.risks[id].name; }).filter(Boolean).join(", ");
  }

  function seedObligationPack(ws, pack) {
    var added = 0;
    pack.obligations.forEach(function (o) {
      if (!ws.registry.obligations[o.id]) { ws.registry.obligations[o.id] = JSON.parse(JSON.stringify(o)); added++; }
    });
    return added;
  }

  /** Example enterprise records for the two seeded example processes, so a
   *  new workspace shows every module working. Only applied when those
   *  example processes exist and the registry is brand new. */
  function seedExamples(ws) {
    var R = ws.registry;
    var onb = ws.processes.proc_onboarding, cmp = ws.processes.proc_complaint;
    if (!onb && !cmp) return false;
    var EX = "Seeded example — edit or delete.";
    function cap(id, name, level, parentId, importance, owner) { R.capabilities[id] = { id: id, name: name, level: level, parentId: parentId || "", importance: importance, owner: owner || "", description: EX }; }
    cap("cap_workforce", "Workforce management", 1, "", "high", "Chief People Officer");
    cap("cap_talent_onboarding", "Talent onboarding", 2, "cap_workforce", "high", "HR Business Partner");
    cap("cap_learning", "Learning and development", 2, "cap_workforce", "medium", "L&D Lead");
    cap("cap_customer", "Customer service", 1, "", "critical", "VP Customer");
    cap("cap_case_mgmt", "Case management", 2, "cap_customer", "critical", "Customer Service Manager");
    cap("cap_feedback", "Customer feedback and insight", 2, "cap_customer", "medium", "Customer Insights Lead");
    cap("cap_quality", "Quality management", 1, "", "high", "Quality Manager");
    cap("cap_doc_control", "Document control", 2, "cap_quality", "high", "Quality Manager");
    cap("cap_capa", "Corrective and preventive action", 2, "cap_quality", "high", "Quality Manager");
    cap("cap_it", "IT services", 1, "", "high", "IT Director");
    cap("cap_identity", "Identity and access", 2, "cap_it", "critical", "IT Security Lead");
    cap("cap_itsm", "IT service management", 2, "cap_it", "high", "IT Service Desk Lead");

    function app(o) { o.notes = EX; o.obligationIds = o.obligationIds || []; o.riskIds = o.riskIds || []; R.applications[o.id] = o; }
    app({ id: "app_hris", name: "Workday HCM", kind: "system", vendor: "Workday", owner: "HRIS Manager", lifecycle: "active", criticality: "high", dataClass: "confidential", capabilityIds: ["cap_talent_onboarding", "cap_learning"] });
    app({ id: "app_entra", name: "Microsoft Entra ID", kind: "system", vendor: "Microsoft", owner: "IT Security Lead", lifecycle: "active", criticality: "critical", dataClass: "restricted", capabilityIds: ["cap_identity"] });
    app({ id: "app_itsm", name: "ServiceNow ITSM", kind: "system", vendor: "ServiceNow", owner: "IT Service Desk Lead", lifecycle: "active", criticality: "high", dataClass: "internal", capabilityIds: ["cap_itsm"] });
    app({ id: "app_crm_service", name: "Salesforce Service Cloud", kind: "system", vendor: "Salesforce", owner: "CRM Product Owner", lifecycle: "active", criticality: "critical", dataClass: "confidential", capabilityIds: ["cap_case_mgmt", "cap_feedback"] });
    app({ id: "app_legacy_helpdesk", name: "Legacy Helpdesk", kind: "system", vendor: "In-house", owner: "", lifecycle: "sunset", criticality: "medium", dataClass: "confidential", capabilityIds: ["cap_case_mgmt"], sunsetDate: "2026-12-31" });
    app({ id: "app_qms_docs", name: "SharePoint QMS library", kind: "system", vendor: "Microsoft", owner: "Quality Manager", lifecycle: "active", criticality: "high", dataClass: "internal", capabilityIds: ["cap_doc_control"] });
    app({ id: "agt_onboarding", name: "Onboarding Assistant", kind: "agent", vendor: "Continuum agent", owner: "HR Business Partner", lifecycle: "active", criticality: "medium", dataClass: "confidential", capabilityIds: ["cap_talent_onboarding"], agent: { model: "Configured per workspace", autonomy: "act_with_approval" } });
    app({ id: "agt_triage", name: "Complaint Triage Agent", kind: "agent", vendor: "Continuum agent", owner: "Customer Service Manager", lifecycle: "plan", criticality: "high", dataClass: "confidential", capabilityIds: ["cap_case_mgmt"], agent: { model: "Configured per workspace", autonomy: "assist" } });

    function ctl(o) { o.description = EX; R.controls[o.id] = o; }
    ctl({ id: "ctl_access_review", name: "New-hire access review within 5 days", type: "detective", owner: "IT Security Lead", frequency: "monthly", lastTested: "2026-09-15", lastResult: "pass", obligationIds: ["obl_iso9001_7_1"], riskIds: [] });
    ctl({ id: "ctl_training_check", name: "Compliance training completion check", type: "detective", owner: "L&D Lead", frequency: "quarterly", lastTested: "2026-05-20", lastResult: "pass", obligationIds: ["obl_iso9001_7_2", "obl_iso9001_7_3"], riskIds: [] });
    ctl({ id: "ctl_severity_triage", name: "Complaint severity triage within 4 hours", type: "preventive", owner: "Customer Service Manager", frequency: "monthly", lastTested: "2026-09-10", lastResult: "pass", obligationIds: ["obl_iso9001_9_1", "obl_iso9001_8_7"], riskIds: [] });
    ctl({ id: "ctl_root_cause", name: "Root-cause review of repeat complaints", type: "corrective", owner: "Quality Manager", frequency: "monthly", lastTested: "", lastResult: "not_tested", obligationIds: ["obl_iso9001_10_2"], riskIds: [] });
    ctl({ id: "ctl_doc_approval", name: "Process document approval before release", type: "preventive", owner: "Quality Manager", frequency: "quarterly", lastTested: "2026-08-28", lastResult: "pass", obligationIds: ["obl_iso9001_7_5", "obl_iso9001_4_4"], riskIds: [] });

    // risks come from migrateRiskRefs(); wire controls to them afterwards
    migrateRiskRefs(ws);
    function linkRisk(ctlId, name) { var id = "rsk_" + slug(name); if (R.risks[id] && R.controls[ctlId].riskIds.indexOf(id) < 0) R.controls[ctlId].riskIds.push(id); }
    linkRisk("ctl_access_review", "Late IT provisioning");
    linkRisk("ctl_training_check", "Missed compliance training");
    linkRisk("ctl_severity_triage", "Regulatory complaint mishandling");
    linkRisk("ctl_root_cause", "Repeat unresolved complaints");
    if (R.risks.rsk_regulatory_complaint_mishandling) { R.risks.rsk_regulatory_complaint_mishandling.likelihood = 3; R.risks.rsk_regulatory_complaint_mishandling.impact = 5; }
    if (R.risks.rsk_repeat_unresolved_complaints) { R.risks.rsk_repeat_unresolved_complaints.likelihood = 4; R.risks.rsk_repeat_unresolved_complaints.impact = 4; }

    if (onb) {
      ensureProcLinks(onb);
      onb.links.capabilityIds = ["cap_talent_onboarding"];
      onb.links.applicationIds = ["app_hris"];
      onb.links.obligationIds = uniq(onb.links.obligationIds.concat(["obl_iso9001_7_2", "obl_iso9001_7_3", "obl_iso9001_4_4"]));
      var pa = ensureElementLinks(onb, "Task_ProvisionAccounts");
      pa.links.applicationIds = ["app_entra", "app_itsm"];
      pa.links.controlIds = ["ctl_access_review"];
      var so = ensureElementLinks(onb, "Task_ScheduleOrientation");
      so.links.applicationIds = ["agt_onboarding", "app_hris"];
      so.links.controlIds = ["ctl_training_check"];
    }
    if (cmp) {
      ensureProcLinks(cmp);
      cmp.links.capabilityIds = ["cap_case_mgmt", "cap_feedback"];
      cmp.links.applicationIds = ["app_crm_service"];
      cmp.links.obligationIds = uniq(cmp.links.obligationIds.concat(["obl_iso9001_9_1", "obl_iso9001_10_2", "obl_iso9001_8_7"]));
      var lc = ensureElementLinks(cmp, "Task_LogComplaint");
      lc.links.applicationIds = ["app_crm_service", "agt_triage"];
      lc.links.controlIds = ["ctl_severity_triage"];
      var ir = ensureElementLinks(cmp, "Task_InvestigateResolve");
      ir.links.applicationIds = ["app_legacy_helpdesk"];
      ir.links.controlIds = ["ctl_root_cause"];
    }
    return true;
  }

  /** Idempotent. Brings any workspace (old Studio state included) up to the
   *  EA/GRC shape. Returns a list of what changed, for the decision log. */
  function ensureWorkspace(ws, isoPacks, opts) {
    opts = opts || {};
    var changes = [];
    if (!ws.processes) ws.processes = {};
    if (!ws.order) ws.order = Object.keys(ws.processes);
    var fresh = !ws.registry;
    if (fresh) { ws.registry = emptyRegistry(); changes.push("registry-created"); }
    REGISTRY_KEYS.forEach(function (k) { if (!ws.registry[k]) ws.registry[k] = {}; });
    vals(ws.processes).forEach(ensureProcLinks);
    if (isoPacks && !(ws.meta && ws.meta.packsSeeded)) {
      var a = seedObligationPack(ws, isoPacks.packs.iso9001);
      var b = seedObligationPack(ws, isoPacks.packs.iso9004);
      if (a || b) changes.push("obligation-packs-seeded:" + (a + b));
      ws.meta = ws.meta || {};
      ws.meta.packsSeeded = ["iso9001", "iso9004"];
    }
    if (fresh && opts.examples !== false && seedExamples(ws)) changes.push("examples-seeded");
    var migrated = migrateRiskRefs(ws);
    if (migrated) changes.push("risks-migrated:" + migrated);
    vals(ws.processes).forEach(function (p) { if (p.links.riskIds.length) syncRiskRefs(ws, p); });
    vals(ws.registry.applications).forEach(function (a) {
      ["capabilityIds", "obligationIds", "riskIds"].forEach(function (k) { if (!Array.isArray(a[k])) a[k] = []; });
      if (!a.kind) a.kind = "system";
      if (LIFECYCLE.indexOf(a.lifecycle) < 0) a.lifecycle = "active";
    });
    vals(ws.registry.controls).forEach(function (c) { ["obligationIds", "riskIds"].forEach(function (k) { if (!Array.isArray(c[k])) c[k] = []; }); });
    return changes;
  }

  /** Removes every reference to a registry id (used on delete). */
  function removeRefs(ws, id) {
    vals(ws.processes).forEach(function (p) {
      ensureProcLinks(p);
      PROC_LINK_KEYS.forEach(function (k) { p.links[k] = p.links[k].filter(function (x) { return x !== id; }); });
      vals(p.elementGovernance).forEach(function (eg) {
        if (!eg.links) return;
        EL_LINK_KEYS.forEach(function (k) { eg.links[k] = arr(eg.links[k]).filter(function (x) { return x !== id; }); });
      });
      syncRiskRefs(ws, p);
    });
    vals(ws.registry.applications).forEach(function (a) { ["capabilityIds", "obligationIds", "riskIds"].forEach(function (k) { a[k] = arr(a[k]).filter(function (x) { return x !== id; }); }); });
    vals(ws.registry.controls).forEach(function (c) { ["obligationIds", "riskIds"].forEach(function (k) { c[k] = arr(c[k]).filter(function (x) { return x !== id; }); }); });
    vals(ws.registry.capabilities).forEach(function (c) { if (c.parentId === id) { c.parentId = ""; c.level = 1; } });
  }

  /* ---------------- graph ---------------- */

  function tasksOf(proc) {
    var list = arr(proc.tasks).slice();
    var seen = {};
    list.forEach(function (t) { seen[t.id] = 1; });
    Object.keys(proc.elementGovernance || {}).forEach(function (el) { if (!seen[el]) list.push({ id: el, name: el, type: "bpmn:Task" }); });
    return list;
  }

  function nodeIndex(ws) {
    var idx = {};
    vals(ws.processes).forEach(function (p) {
      idx[p.id] = { id: p.id, type: "process", name: p.name, data: p };
      tasksOf(p).forEach(function (t) {
        var id = taskNodeId(p.id, t.id);
        idx[id] = { id: id, type: "task", name: decodeEntities(t.name || t.id), data: t, procId: p.id, elementId: t.id };
      });
    });
    REGISTRY_KEYS.forEach(function (k) {
      vals(ws.registry && ws.registry[k]).forEach(function (o) {
        var type = TYPE_OF_KEY[k];
        if (type === "application" && o.kind === "agent") type = "agent";
        var name = type === "obligation" ? obligationLabel(o) : (o.name || o.id);
        idx[o.id] = { id: o.id, type: type, name: name, data: o };
      });
    });
    return idx;
  }

  function obligationLabel(o) {
    var head = [o.source, o.clause ? "§" + o.clause : ""].filter(Boolean).join(" ");
    return [head, o.title].filter(Boolean).join(" ") || o.id;
  }

  /** Parent ids with cycles broken: a capability whose ancestor chain loops
   *  back to itself is treated as top-level, so nothing disappears. */
  function capabilityParents(caps) {
    // only capabilities that are themselves on a cycle lose their parent;
    // their descendants keep theirs and hang off the promoted node
    function onCycle(id) {
      var cur = caps[id].parentId, steps = 0;
      while (cur && caps[cur] && steps++ < 1000) { if (cur === id) return true; cur = caps[cur].parentId; }
      return false;
    }
    var out = {};
    Object.keys(caps).forEach(function (id) {
      var p = caps[id].parentId;
      out[id] = p && caps[p] && !onCycle(id) ? p : "";
    });
    return out;
  }

  /** Flow nodes that carry governance, read from BPMN 2.0 XML without a DOM
   *  (the platform's fallback when an export carries no tasks list). */
  function tasksFromBpmnXml(xml) {
    var out = [], seen = {};
    var re = /<(?:bpmn2?:)?(task|userTask|serviceTask|manualTask|scriptTask|sendTask|receiveTask|businessRuleTask|subProcess|adHocSubProcess|callActivity|exclusiveGateway|parallelGateway|inclusiveGateway|eventBasedGateway|complexGateway)\b([^>]*)>/g;
    var m;
    while ((m = re.exec(String(xml || "")))) {
      var id = /\bid="([^"]+)"/.exec(m[2]); if (!id || seen[id[1]]) continue;
      var name = /\bname="([^"]*)"/.exec(m[2]);
      seen[id[1]] = 1;
      out.push({ id: id[1], name: decodeEntities(name ? name[1] : id[1]), type: "bpmn:" + m[1].charAt(0).toUpperCase() + m[1].slice(1) });
    }
    return out;
  }

  function edges(ws) {
    var out = [];
    var R = ws.registry || emptyRegistry();
    function e(s, t, type) { if (s && t) out.push({ s: s, t: t, type: type }); }
    vals(ws.processes).forEach(function (p) {
      var L = p.links || {};
      arr(L.capabilityIds).forEach(function (c) { e(p.id, c, "realizes"); });
      arr(L.applicationIds).forEach(function (a) { e(a, p.id, "supports"); });
      arr(L.obligationIds).forEach(function (o) { e(o, p.id, "applies_to"); });
      arr(L.riskIds).forEach(function (r) { e(r, p.id, "affects"); });
      tasksOf(p).forEach(function (t) {
        var tid = taskNodeId(p.id, t.id);
        e(tid, p.id, "belongs_to");
        var eg = p.elementGovernance && p.elementGovernance[t.id];
        var EL = eg && eg.links || {};
        arr(EL.applicationIds).forEach(function (a) { e(a, tid, "supports"); });
        arr(EL.controlIds).forEach(function (c) { e(c, tid, "implemented_in"); });
      });
    });
    vals(R.applications).forEach(function (a) {
      arr(a.capabilityIds).forEach(function (c) { e(a.id, c, "serves"); });
      arr(a.obligationIds).forEach(function (o) { e(o, a.id, "applies_to"); });
      arr(a.riskIds).forEach(function (r) { e(r, a.id, "affects"); });
    });
    vals(R.controls).forEach(function (c) {
      arr(c.obligationIds).forEach(function (o) { e(c.id, o, "satisfies"); });
      arr(c.riskIds).forEach(function (r) { e(c.id, r, "mitigates"); });
    });
    var parents = capabilityParents(R.capabilities || {});
    vals(R.capabilities).forEach(function (c) { if (parents[c.id]) e(c.id, parents[c.id], "part_of"); });
    var idx = nodeIndex(ws);
    return out.filter(function (x) { return idx[x.s] && idx[x.t]; });
  }

  /* ---------------- Ripple (E5) ---------------- */

  // Impact flows along these edges (s → t unless marked rev). applies_to and
  // affects are only followed from the start node: reaching an obligation
  // through a failing control must not fan out to every process that
  // obligation applies to — that would bury the real impact in noise.
  var VERB = {
    "supports>": "supports", "belongs_to>": "is a step in", "realizes>": "realizes", "serves>": "serves",
    "part_of>": "rolls up to", "implemented_in<": "hosts control", "implemented_in>": "runs in",
    "satisfies>": "satisfies", "satisfies<": "is satisfied by", "mitigates>": "mitigates",
    "applies_to>": "applies to", "affects>": "affects", "realizes<": "is realized by",
    "serves<": "is served by", "part_of<": "includes", "supports<": "is supported by", "belongs_to<": "contains"
  };

  function ripple(ws, startId, opts) {
    opts = opts || {};
    var maxDepth = opts.maxDepth || 6;
    var idx = nodeIndex(ws);
    var start = idx[startId];
    if (!start) return { start: null, affected: [], kpis: [], guardrails: [], summary: "Unknown item." };
    var E = edges(ws);
    var outF = {}, outR = {};
    E.forEach(function (x) { (outF[x.s] = outF[x.s] || []).push(x); (outR[x.t] = outR[x.t] || []).push(x); });

    var upstream = start.type === "capability";
    function steps(node, isStart) {
      var res = [];
      function fwd(types) { arr(outF[node.id]).forEach(function (x) { if (types.indexOf(x.type) >= 0) res.push({ to: x.t, key: x.type + ">" }); }); }
      function rev(types) { arr(outR[node.id]).forEach(function (x) { if (types.indexOf(x.type) >= 0) res.push({ to: x.s, key: x.type + "<" }); }); }
      if (upstream) {
        rev(["realizes", "serves", "part_of"]);
        if (node.type === "process") rev(["belongs_to", "supports"]);
        if (node.type === "task") rev(["supports"]);
        return res;
      }
      fwd(["supports", "belongs_to", "realizes", "serves", "part_of", "satisfies", "mitigates"]);
      rev(["implemented_in"]);
      if (isStart) {
        fwd(["applies_to", "affects"]);
        if (node.type === "control") fwd(["implemented_in"]);
        if (node.type === "obligation") rev(["satisfies"]);
        if (node.type === "process") rev(["belongs_to"]);
      }
      // controls reached from an obligation start: show where they run
      if (node.type === "control" && node._viaObligation) fwd(["implemented_in"]);
      return res;
    }

    var seen = {}; seen[start.id] = { depth: 0, parent: null, key: null };
    var queue = [start.id];
    while (queue.length) {
      var id = queue.shift();
      var meta = seen[id];
      if (meta.depth >= maxDepth) continue;
      var node = idx[id];
      steps(node, id === start.id).forEach(function (s) {
        if (seen[s.to] || !idx[s.to]) return;
        seen[s.to] = { depth: meta.depth + 1, parent: id, key: s.key };
        if (id === start.id && start.type === "obligation" && idx[s.to].type === "control") idx[s.to]._viaObligation = true;
        queue.push(s.to);
      });
    }
    vals(idx).forEach(function (n) { delete n._viaObligation; });

    function pathTo(id) {
      var p = [];
      var cur = id;
      while (cur && seen[cur] && seen[cur].parent) {
        p.unshift({ id: cur, name: idx[cur].name, type: idx[cur].type, verb: VERB[seen[cur].key] || seen[cur].key });
        cur = seen[cur].parent;
      }
      return p;
    }

    var affected = Object.keys(seen).filter(function (id) { return id !== start.id; }).map(function (id) {
      var n = idx[id];
      return { id: id, type: n.type, name: n.name, depth: seen[id].depth, path: pathTo(id), procId: n.procId || null };
    });

    // Agents bound to any impacted task or process are affected too: their
    // task context and guardrail change underneath them.
    if (!upstream) {
      var hit = {}; affected.forEach(function (a) { hit[a.id] = 1; }); hit[start.id] = 1;
      var scan = affected.slice();
      if (start.type === "task" || start.type === "process") scan.unshift({ id: start.id, type: start.type, depth: 0, path: [] });
      scan.forEach(function (a) {
        if (a.type !== "task" && a.type !== "process") return;
        arr(outR[a.id]).forEach(function (x) {
          if (x.type !== "supports" || hit[x.s]) return;
          var n = idx[x.s];
          if (!n || n.type !== "agent") return;
          hit[x.s] = 1;
          affected.push({ id: x.s, type: "agent", name: n.name, depth: a.depth + 1, path: a.path.concat([{ id: x.s, name: n.name, type: "agent", verb: "is bound to it" }]), procId: null, bindingOnly: true });
        });
      });
    }

    var procIds = uniq(affected.filter(function (a) { return a.type === "process"; }).map(function (a) { return a.id; }).concat(start.type === "process" ? [start.id] : []));
    var taskHits = affected.filter(function (a) { return a.type === "task"; }).concat(start.type === "task" ? [{ id: start.id }] : []);
    var kpis = [];
    if (!upstream) {
      procIds.forEach(function (pid) { var p = ws.processes[pid]; splitList(p.kpiRefs).forEach(function (k) { kpis.push({ name: k, procId: pid, procName: p.name }); }); });
      taskHits.forEach(function (t) {
        var ref = parseTaskNodeId(t.id); if (!ref) return;
        var p = ws.processes[ref.procId]; var eg = p && p.elementGovernance && p.elementGovernance[ref.elementId];
        if (eg) splitList(eg.kpiRefs).forEach(function (k) { kpis.push({ name: k, procId: ref.procId, procName: p.name, task: idx[t.id] && idx[t.id].name }); });
      });
    }
    var guardrails = [];
    if (!upstream) {
      taskHits.forEach(function (t) {
        var ref = parseTaskNodeId(t.id); if (!ref) return;
        var p = ws.processes[ref.procId];
        var agents = arr(outR[t.id]).filter(function (x) { return x.type === "supports" && idx[x.s] && idx[x.s].type === "agent"; }).map(function (x) { return idx[x.s].name; });
        if (!agents.length) return;
        var g = effectiveGuardrail(p, ref.elementId);
        guardrails.push({ taskId: t.id, task: idx[t.id].name, procName: p.name, agents: agents, source: g.source, version: "gr." + p.id + ".v" + (p.version || 1), blank: isBlankGuardrail(g) });
      });
    }

    var counts = {};
    affected.forEach(function (a) { counts[a.type] = (counts[a.type] || 0) + 1; });
    return { start: { id: start.id, type: start.type, name: start.name }, mode: upstream ? "upstream" : "impact", affected: affected, kpis: kpis, guardrails: guardrails, counts: counts, summary: summarize(start, counts, kpis, upstream) };
  }

  function plural(n, one, many) { return n + " " + (n === 1 ? one : many); }
  function summarize(start, c, kpis, upstream) {
    if (upstream) {
      var parts = [];
      if (c.process) parts.push(plural(c.process, "process", "processes"));
      if (c.application) parts.push(plural(c.application, "system", "systems"));
      if (c.agent) parts.push(plural(c.agent, "agent", "agents"));
      if (c.capability) parts.push(plural(c.capability, "sub-capability", "sub-capabilities"));
      return parts.length ? start.name + " depends on " + parts.join(", ") + "." : start.name + " has nothing mapped to it yet.";
    }
    var bits = [];
    if (c.task) bits.push(plural(c.task, "task", "tasks"));
    if (c.process) bits.push(plural(c.process, "process", "processes"));
    if (c.capability) bits.push(plural(c.capability, "capability", "capabilities"));
    if (kpis.length) bits.push(plural(kpis.length, "KPI", "KPIs"));
    if (c.control) bits.push(plural(c.control, "control", "controls"));
    if (c.obligation) bits.push(plural(c.obligation, "obligation", "obligations"));
    if (c.risk) bits.push(plural(c.risk, "risk", "risks"));
    if (c.application) bits.push(plural(c.application, "system", "systems"));
    if (c.agent) bits.push(plural(c.agent, "agent", "agents"));
    if (!bits.length) return "Nothing else in the model depends on " + start.name + ".";
    var last = bits.pop();
    return "A change to " + start.name + " reaches " + (bits.length ? bits.join(", ") + " and " + last : last) + ".";
  }

  /* ---------------- Assure (E2) ---------------- */

  function controlInDate(c, today) {
    var d = dayNum(c.lastTested);
    if (d === null || d > today) return false; // a future test date is not evidence
    var f = FREQ_DAYS[c.frequency] || 366;
    return today - d <= f;
  }

  function procApproved(p, today) {
    if (p.status !== "approved" && p.status !== "effective") return false;
    var due = dayNum(p.nextReviewDue);
    return due === null || due >= today;
  }

  function assure(ws, todayIso) {
    var today = dayNum(todayIso) || Math.floor(Date.now() / 864e5);
    var R = ws.registry || emptyRegistry();
    var byObl = {};
    function row(oid) { return byObl[oid] || (byObl[oid] = { processes: [], applications: [], controls: [] }); }
    vals(ws.processes).forEach(function (p) { arr(p.links && p.links.obligationIds).forEach(function (o) { row(o).processes.push(p); }); });
    vals(R.applications).forEach(function (a) { arr(a.obligationIds).forEach(function (o) { row(o).applications.push(a); }); });
    vals(R.controls).forEach(function (c) { arr(c.obligationIds).forEach(function (o) { row(o).controls.push(c); }); });

    var packs = {};
    vals(R.obligations).forEach(function (o) {
      var key = o.source || "Custom";
      var pk = packs[key] || (packs[key] = { source: key, pack: o.pack || "custom", rows: [], covered: 0, partial: 0, gap: 0 });
      var r = byObl[o.id] || { processes: [], applications: [], controls: [] };
      var evidence = [];
      r.processes.forEach(function (p) {
        evidence.push({ kind: "process", id: p.id, label: p.name + " v" + (p.version || 1) + " · " + (STATUS_LABEL[p.status] || p.status) + (p.approvedDate ? " · approved " + p.approvedDate : "") + (p.nextReviewDue ? " · review due " + p.nextReviewDue : ""), good: procApproved(p, today) });
      });
      r.controls.forEach(function (c) {
        var good = c.lastResult === "pass" && controlInDate(c, today);
        evidence.push({ kind: "control", id: c.id, label: c.name + " · " + (c.lastTested ? "tested " + c.lastTested + " · " + c.lastResult : "never tested"), good: good, failing: c.lastResult === "fail" });
      });
      var linked = r.processes.length + r.applications.length + r.controls.length;
      var status, reason;
      if (!linked) { status = "gap"; reason = "No process, system or control is mapped to this clause."; }
      else if (evidence.some(function (e) { return e.failing; })) { status = "partial"; reason = "A mapped control failed its last test."; }
      else if (evidence.some(function (e) { return e.good; })) { status = "covered"; reason = "Approved process or in-date passing control on record."; }
      else { status = "partial"; reason = "Mapped, but no approved process or in-date passing control yet."; }
      pk[status]++;
      pk.rows.push({ obligation: o, processes: r.processes.map(function (p) { return { id: p.id, name: p.name }; }), applications: r.applications.map(function (a) { return { id: a.id, name: a.name }; }), controls: r.controls.map(function (c) { return { id: c.id, name: c.name }; }), evidence: evidence, status: status, reason: reason });
    });
    var list = vals(packs);
    list.forEach(function (pk) {
      pk.total = pk.rows.length;
      pk.coverage = pk.total ? Math.round((pk.covered / pk.total) * 100) : 0;
      pk.rows.sort(function (a, b) { return clauseCmp(a.obligation.clause, b.obligation.clause); });
    });
    list.sort(function (a, b) { return a.source < b.source ? -1 : 1; });
    return { packs: list };
  }

  function clauseCmp(a, b) {
    var x = String(a || "").split(".").map(Number), y = String(b || "").split(".").map(Number);
    for (var i = 0; i < Math.max(x.length, y.length); i++) { var d = (x[i] || 0) - (y[i] || 0); if (d) return d; }
    return 0;
  }

  /* ---------------- Vitals (E10) ---------------- */

  function vitals(ws, todayIso) {
    var today = dayNum(todayIso) || Math.floor(Date.now() / 864e5);
    var R = ws.registry || emptyRegistry();
    var E = edges(ws);
    var idx = nodeIndex(ws);
    var checks = 0, passed = 0, findings = [];
    function check(ok, f) { checks++; if (ok) passed++; else findings.push(f); }
    function into(id, type) { return E.filter(function (x) { return x.t === id && (!type || x.type === type); }); }
    function from(id, type) { return E.filter(function (x) { return x.s === id && (!type || x.type === type); }); }

    vals(ws.processes).forEach(function (p) {
      var ref = { nodeId: p.id, nodeType: "process", name: p.name };
      check(!!String(p.ownerRole || "").trim(), mk("critical", "process-owner", ref, "Process has no accountable owner.", "Set a process owner — ISO 9001 §4.4 and §5.3 expect one per process."));
      check(!!p.apqcCode, mk("info", "process-apqc", ref, "Process is not classified against APQC.", "Pick an APQC category so KPIs and guardrails share a join key."));
      var due = dayNum(p.nextReviewDue);
      if (due !== null) check(due >= today, mk("warning", "process-review-overdue", ref, "Review was due " + p.nextReviewDue + ".", "Review the process and record the new review date (ISO 9001 §7.5)."));
      else check(false, mk("info", "process-review-unset", ref, "No next-review date is set.", "Set a review cadence so the record cannot silently go stale."));
      check(arr(p.links && p.links.capabilityIds).length > 0, mk("warning", "process-capability", ref, "Process is not linked to any capability.", "Link the capability it realizes so it appears in Atlas and strategy roll-ups."));
      check(splitList(p.kpiRefs).length > 0, mk("info", "process-kpi", ref, "Process has no KPI.", "Add at least one measure (ISO 9001 §9.1)."));
    });

    vals(R.applications).forEach(function (a) {
      var isAgent = a.kind === "agent";
      var ref = { nodeId: a.id, nodeType: isAgent ? "agent" : "application", name: a.name };
      check(!!String(a.owner || "").trim(), mk(isAgent ? "critical" : "warning", "app-owner", ref, (isAgent ? "Agent" : "System") + " has no owner.", "Assign an accountable owner."));
      var uses = from(a.id, "supports");
      if (a.lifecycle === "retired") check(!uses.length, mk("critical", "app-retired-in-use", ref, "Retired, but still supports " + plural(uses.length, "process or task", "processes or tasks") + ".", "Open Ripple to see what breaks, then move those steps to an active system."));
      else if (a.lifecycle === "sunset") check(!uses.length, mk("warning", "app-sunset-in-use", ref, "Sunsetting" + (a.sunsetDate ? " on " + a.sunsetDate : "") + ", but still supports " + plural(uses.length, "process or task", "processes or tasks") + ".", "Plan the migration before the sunset date; Ripple shows the full impact."));
      if (!isAgent && a.lifecycle === "active") check(arr(a.capabilityIds).length > 0, mk("info", "app-capability", ref, "Active system serves no capability.", "Map it in Atlas, or confirm it is a retirement candidate."));
      if (isAgent) {
        check(uses.length > 0, mk("info", "agent-unbound", ref, "Agent is not bound to any task.", "Bind it to the task it performs so its guardrail applies."));
        uses.forEach(function (u) {
          var t = parseTaskNodeId(u.t);
          var p = t ? ws.processes[t.procId] : ws.processes[u.t];
          if (!p) return;
          check(!isBlankGuardrail(effectiveGuardrail(p, t ? t.elementId : null)), mk("critical", "agent-unguarded", ref, "Bound to “" + (idx[u.t] && idx[u.t].name) + "” with no guardrail.", "Add allow / deny / escalate rules on the task or its process before the agent acts."));
        });
      }
    });

    vals(R.controls).forEach(function (c) {
      var ref = { nodeId: c.id, nodeType: "control", name: c.name };
      check(c.lastResult !== "fail", mk("critical", "control-failed", ref, "Failed its last test.", "Raise a corrective action (ISO 9001 §10.2) and re-test."));
      if (!c.lastTested) check(false, mk("warning", "control-untested", ref, "Has never been tested.", "Test it and record the result."));
      else check(controlInDate(c, today), mk("warning", "control-test-overdue", ref, "Test is overdue (" + (c.frequency || "annual") + ", last " + c.lastTested + ").", "Re-test and record the result."));
      check(arr(c.obligationIds).length + arr(c.riskIds).length > 0, mk("info", "control-orphan", ref, "Satisfies no obligation and mitigates no risk.", "Link it, or retire it."));
    });

    vals(R.risks).forEach(function (r) {
      var ref = { nodeId: r.id, nodeType: "risk", name: r.name };
      var score = (Number(r.likelihood) || 0) * (Number(r.impact) || 0);
      var mitigated = into(r.id, "mitigates").length > 0;
      if (r.treatment !== "accept") check(mitigated, mk(score >= 15 ? "critical" : "warning", "risk-unmitigated", ref, "Risk score " + score + " with no mitigating control.", "Link a control, or record the treatment as accepted."));
    });

    var capParents = capabilityParents(R.capabilities || {});
    vals(R.capabilities).forEach(function (c) {
      var hasChildren = vals(R.capabilities).some(function (x) { return capParents[x.id] === c.id; });
      if (hasChildren) return;
      var ref = { nodeId: c.id, nodeType: "capability", name: c.name };
      check(into(c.id, "realizes").length > 0, mk("info", "capability-unrealized", ref, "No process realizes this capability.", "Link the process that delivers it, or mark it as planned."));
    });

    assure(ws, todayIso).packs.forEach(function (pk) {
      var guidance = pk.pack === "iso9004";
      check(pk.gap === 0, mk(guidance ? "info" : "warning", "assure-gaps", { nodeId: null, nodeType: "pack", name: pk.source }, pk.gap + " of " + pk.total + " " + pk.source + " clauses have nothing mapped.", "Open Assure and map processes or controls to the open clauses."));
    });

    findings = findings.filter(Boolean);
    var order = { critical: 0, warning: 1, info: 2 };
    findings.sort(function (a, b) { return order[a.severity] - order[b.severity] || (a.name < b.name ? -1 : 1); });
    var bySev = { critical: 0, warning: 0, info: 0 };
    findings.forEach(function (f) { bySev[f.severity]++; });
    return { score: checks ? Math.round((passed / checks) * 100) : 100, checks: checks, passed: passed, bySeverity: bySev, findings: findings };
  }

  function mk(severity, rule, ref, message, hint) {
    return { severity: severity, rule: rule, nodeId: ref.nodeId, nodeType: ref.nodeType, name: ref.name, message: message, hint: hint };
  }

  /* ---------------- Atlas (E3) ---------------- */

  function atlas(ws) {
    var R = ws.registry || emptyRegistry();
    var caps = vals(R.capabilities);
    var parents = capabilityParents(R.capabilities || {});
    var children = {};
    caps.forEach(function (c) { var pid = parents[c.id] || ""; (children[pid] = children[pid] || []).push(c); });
    Object.keys(children).forEach(function (k) { children[k].sort(function (a, b) { return a.name < b.name ? -1 : 1; }); });
    var realizes = {}, serves = {};
    vals(ws.processes).forEach(function (p) { arr(p.links && p.links.capabilityIds).forEach(function (c) { (realizes[c] = realizes[c] || []).push(p); }); });
    vals(R.applications).forEach(function (a) { arr(a.capabilityIds).forEach(function (c) { (serves[c] = serves[c] || []).push(a); }); });
    function build(c, depth) {
      var kids = (children[c.id] || []).map(function (k) { return build(k, depth + 1); });
      var procs = (realizes[c.id] || []).slice();
      var apps = (serves[c.id] || []).slice();
      kids.forEach(function (k) { procs = procs.concat(k.allProcesses); apps = apps.concat(k.allApps); });
      procs = uniqBy(procs, "id"); apps = uniqBy(apps, "id");
      var scored = procs.filter(function (p) { return p.maturityScore; });
      var direct = (serves[c.id] || []).filter(function (a) { return a.kind !== "agent" && a.lifecycle === "active"; });
      return {
        id: c.id, name: c.name, level: c.level || depth, importance: c.importance || "medium", owner: c.owner || "", depth: depth,
        processes: (realizes[c.id] || []).map(function (p) { return { id: p.id, name: p.name, maturity: p.maturityScore || 0 }; }),
        applications: (serves[c.id] || []).map(function (a) { return { id: a.id, name: a.name, kind: a.kind, lifecycle: a.lifecycle }; }),
        allProcesses: procs, allApps: apps,
        maturity: scored.length ? Math.round((scored.reduce(function (s, p) { return s + p.maturityScore; }, 0) / scored.length) * 10) / 10 : null,
        overlap: direct.length >= 2 ? direct.map(function (a) { return a.name; }) : null,
        children: kids
      };
    }
    return (children[""] || []).map(function (c) { return build(c, 1); });
  }

  function uniqBy(list, k) { var s = {}; return list.filter(function (x) { if (s[x[k]]) return false; s[x[k]] = 1; return true; }); }

  /* ---------------- task context (MCP shape) ---------------- */

  function hasTask(proc, elementId) { return tasksOf(proc).some(function (t) { return t.id === elementId; }); }

  function taskContext(ws, procId, elementId) {
    var p = ws.processes[procId];
    if (!p || !hasTask(p, elementId)) return null;
    var idx = nodeIndex(ws);
    var tid = taskNodeId(procId, elementId);
    var eg = (p.elementGovernance && p.elementGovernance[elementId]) || {};
    var L = eg.links || {};
    var g = effectiveGuardrail(p, elementId);
    function names(ids) { return arr(ids).map(function (id) { return idx[id] ? id : null; }).filter(Boolean); }
    var apps = arr(L.applicationIds).map(function (id) { return ws.registry.applications[id]; }).filter(Boolean);
    var ctlIds = names(L.controlIds);
    var obl = uniq(ctlIds.reduce(function (acc, c) { return acc.concat(arr(ws.registry.controls[c].obligationIds)); }, []).concat(arr(p.links && p.links.obligationIds)));
    // Budget: < 150 tokens (core model §08). Empty fields are omitted and
    // obligations are cited as short clause refs ("9001:7.2").
    var shortObl = obl.map(function (o) { var x = ws.registry.obligations[o]; return x ? String(x.source || "").replace(/^ISO\s*/, "").replace(/:\d{4}$/, "") + ":" + x.clause : o; });
    var out = {
      proc: p.apqcCode || procId, task: elementId, name: idx[tid] ? idx[tid].name : elementId,
      owner: eg.ownerRole || p.ownerRole || "",
      in: splitList(eg.inputs || p.inputs), out: splitList(eg.outputs || p.outputs),
      kpi: splitList(eg.kpiRefs || p.kpiRefs),
      systems: apps.filter(function (a) { return a.kind !== "agent"; }).map(function (a) { return a.id; }),
      agents: apps.filter(function (a) { return a.kind === "agent"; }).map(function (a) { return a.id; }),
      controls: ctlIds, obligations: shortObl,
      guardrail: { ref: "gr." + procId + ".v" + (p.version || 1), allow: g.allowActions.map(function (a) { return a.id; }), deny: g.denyActions.map(function (a) { return a.id; }), escalate_if: g.escalateIf },
      model_sig: (p.updatedAt || "").slice(0, 10) + "-v" + (p.version || 1)
    };
    Object.keys(out).forEach(function (k) { if (out[k] === "" || (Array.isArray(out[k]) && !out[k].length)) delete out[k]; });
    ["allow", "deny", "escalate_if"].forEach(function (k) { var v = out.guardrail[k]; if (v === "" || (Array.isArray(v) && !v.length)) delete out.guardrail[k]; });
    return out;
  }

  /* ---------------- export ---------------- */

  function graphExport(ws) {
    var idx = nodeIndex(ws);
    return {
      schema: "continuum.graph.v1",
      nodes: vals(idx).map(function (n) { return { id: n.id, type: n.type, name: n.name, procId: n.procId || null }; }),
      edges: edges(ws)
    };
  }

  return {
    REGISTRY_KEYS: REGISTRY_KEYS, TYPE_OF_KEY: TYPE_OF_KEY, KEY_OF_TYPE: KEY_OF_TYPE, LIFECYCLE: LIFECYCLE, FREQ_DAYS: FREQ_DAYS,
    emptyRegistry: emptyRegistry, ensureWorkspace: ensureWorkspace, ensureProcLinks: ensureProcLinks, ensureElementLinks: ensureElementLinks,
    migrateRiskRefs: migrateRiskRefs, syncRiskRefs: syncRiskRefs, seedObligationPack: seedObligationPack, removeRefs: removeRefs,
    splitList: splitList, slug: slug, taskNodeId: taskNodeId, parseTaskNodeId: parseTaskNodeId, decodeEntities: decodeEntities,
    parseGuardrailActions: parseGuardrailActions, effectiveGuardrail: effectiveGuardrail, isBlankGuardrail: isBlankGuardrail,
    nodeIndex: nodeIndex, edges: edges, tasksOf: tasksOf, ripple: ripple, assure: assure, vitals: vitals, atlas: atlas,
    taskContext: taskContext, graphExport: graphExport, clauseCmp: clauseCmp,
    hasTask: hasTask, obligationLabel: obligationLabel, capabilityParents: capabilityParents, tasksFromBpmnXml: tasksFromBpmnXml
  };
});
