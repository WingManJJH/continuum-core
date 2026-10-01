"use strict";
// Enterprise modules (D45) and import review (D51) in the canvas.
// Classic script after app.js; reuses $, esc, state, renderCenter, openProcess.
//   Enterprise view: Atlas · Applications · Obligations (Assure) · Risks & controls · Vitals
//   Imports view:    batches, staged changes with field diffs, accept / reject, revert
//   Ripple:          shown in the right-hand pane for any record

window.CENTER_VIEWS = window.CENTER_VIEWS || {};
var EA = { tab: "atlas", data: null, atlas: null, assure: null, vitals: null, pack: null, imports: null, staged: null };
var EA_TABS = [["atlas", "Atlas"], ["applications", "Applications"], ["obligations", "Obligations"], ["risks", "Risks & controls"], ["vitals", "Vitals"]];

function eaGet(path) { return fetch(path).then(function (r) { return r.json(); }); }
function eaPost(path, body) {
  return fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
    .then(function (r) { return r.json(); });
}
function eaReload() {
  return Promise.all([eaGet("/api/ea"), eaGet("/api/atlas"), eaGet("/api/assure"), eaGet("/api/vitals")]).then(function (r) {
    EA.data = r[0]; EA.atlas = r[1]; EA.assure = r[2]; EA.vitals = r[3];
    if (state.view === "enterprise") renderCenter();
  });
}
function pill(text, cls) { return '<span class="ea-pill ' + esc(cls || "") + '">' + esc(text) + "</span>"; }
function chip(id, label, kind) { return '<a class="ea-chip k-' + esc(kind) + '" data-ripple="' + esc(id) + '" title="' + esc(id) + '">' + esc(label || id) + "</a>"; }
function nameOf(id) {
  var R = EA.data && EA.data.records; if (!R) return id;
  for (var t in R) { var hit = R[t].find(function (x) { return x.id === id; }); if (hit) return hit.name || hit.title || id; }
  var p = (EA.data.processes || []).find(function (x) { return x.id === id; }); if (p) return p.name;
  var tk = (EA.data.tasks || []).find(function (x) { return x.id === id; }); if (tk) return tk.name;
  return id;
}
var canEdit = function () { return typeof isRole !== "function" || isRole("editor"); };

// ------------------------------------------------------------------ shell
CENTER_VIEWS.enterprise = function () {
  var c = $("#canvas");
  var tabs = '<nav class="ea-tabs">' + EA_TABS.map(function (t) {
    return '<button data-ea-tab="' + t[0] + '" class="' + (EA.tab === t[0] ? "active" : "") + '">' + t[1]
      + (t[0] === "vitals" && EA.vitals ? ' <span class="ea-score s-' + scoreBand(EA.vitals.score) + '">' + EA.vitals.score + "</span>" : "") + "</button>";
  }).join("") + "</nav>";
  if (!EA.data) { c.innerHTML = tabs + '<div class="muted pad">loading…</div>'; eaReload(); wireTabs(); return; }
  var body = { atlas: renderAtlasTab, applications: renderAppsTab, obligations: renderOblTab, risks: renderRiskTab, vitals: renderVitalsTab }[EA.tab]();
  c.innerHTML = '<div class="ea">' + tabs + '<div class="ea-body">' + body + "</div></div>";
  wireTabs();
  wireEA();
};
function scoreBand(s) { return s >= 80 ? "good" : s >= 60 ? "warn" : "crit"; }
function wireTabs() {
  document.querySelectorAll("[data-ea-tab]").forEach(function (b) {
    b.addEventListener("click", function () { EA.tab = b.getAttribute("data-ea-tab"); renderCenter(); });
  });
}
function addBtn(type, label) { return canEdit() ? '<button class="add-btn" type="button" data-ea-add="' + type + '">+ ' + esc(label) + "</button>" : ""; }

// ------------------------------------------------------------------ Atlas
function renderAtlasTab() {
  var A = EA.atlas.atlas || [];
  function node(n) {
    return '<div class="cap-card imp-' + esc(n.importance) + '">'
      + '<div class="cap-head"><a class="cap-name" data-ripple="' + esc(n.id) + '">' + esc(n.name) + "</a>"
      + '<span class="cap-meta">L' + esc(n.level) + (n.maturity != null ? " · maturity " + n.maturity : "") + "</span>"
      + (canEdit() ? ' <button class="ea-edit" data-ea-edit="Capability" data-id="' + esc(n.id) + '" title="Edit">✎</button>' : "") + "</div>"
      + (n.processes.length ? '<div class="cap-row">' + n.processes.map(function (p) { return chip(p.id, p.id + " " + p.name, "process"); }).join("") + "</div>" : "")
      + (n.applications.length ? '<div class="cap-row">' + n.applications.map(function (a) { return chip(a.id, a.name, a.kind === "agent" ? "agent" : "app") + (a.lifecycle !== "active" ? pill(a.lifecycle, "lc-" + a.lifecycle) : ""); }).join("") + "</div>" : "")
      + (n.overlap ? '<div class="cap-warn">Overlap: ' + esc(n.overlap.join(", ")) + " serve this directly</div>" : "")
      + (n.children.length ? '<div class="cap-kids">' + n.children.map(node).join("") + "</div>" : "")
      + "</div>";
  }
  var unm = EA.atlas.unmapped || [];
  return '<div class="ea-head"><div><h3>Capability map</h3><p class="muted">What the business must be able to do, the processes that deliver it and the systems that serve it. Click anything to see its Ripple.</p></div>'
    + addBtn("Capability", "Capability") + "</div>"
    + (A.length ? '<div class="atlas">' + A.map(node).join("") + "</div>" : '<div class="ea-empty">No capabilities yet. Start with your level-1 capabilities, then link the processes that realize them.</div>')
    + (unm.length ? '<div class="ea-foot"><b>' + unm.length + " process" + (unm.length === 1 ? "" : "es") + ' not linked to a capability</b> ' + unm.slice(0, 12).map(function (p) { return chip(p.id, p.id, "process"); }).join("") + "</div>" : "");
}

// ------------------------------------------------------------------ Applications
function renderAppsTab() {
  var apps = EA.data.records.Application || [];
  return '<div class="ea-head"><div><h3>Applications &amp; agents</h3><p class="muted">Systems and AI agents in the portfolio, what they serve and what still depends on them.</p></div>' + addBtn("Application", "Application") + "</div>"
    + (apps.length ? '<table class="ea-table"><thead><tr><th>Name</th><th>Kind</th><th>Lifecycle</th><th>Criticality</th><th>Owner</th><th>Serves</th><th>Supports</th><th></th></tr></thead><tbody>'
      + apps.map(function (a) {
        var sup = (a.process_refs || []).concat(a.task_refs || []);
        return "<tr><td>" + chip(a.id, a.name, a.kind === "agent" ? "agent" : "app") + '<div class="muted small">' + esc(a.vendor || "") + "</div></td>"
          + "<td>" + pill(a.kind, "k-" + a.kind) + "</td><td>" + pill(a.lifecycle, "lc-" + a.lifecycle) + (a.sunset_date ? '<div class="muted small">' + esc(a.sunset_date) + "</div>" : "") + "</td>"
          + "<td>" + esc(a.criticality || "") + "</td><td>" + esc(a.owner || "—") + "</td>"
          + "<td>" + (a.capability_refs || []).map(function (c) { return chip(c, nameOf(c), "cap"); }).join("") + "</td>"
          + "<td>" + (sup.length ? sup.length + " step" + (sup.length === 1 ? "" : "s") : '<span class="muted">—</span>') + (a.agent_binding_refs && a.agent_binding_refs.length ? '<div class="muted small">' + esc(a.agent_binding_refs.join(", ")) + "</div>" : "") + "</td>"
          + "<td>" + rowActions("Application", a.id) + "</td></tr>";
      }).join("") + "</tbody></table>" : '<div class="ea-empty">No applications yet. Add the systems your processes run on — and your AI agents — to see what a change or a retirement touches.</div>');
}
function rowActions(type, id) {
  if (!canEdit()) return "";
  return '<button class="ea-edit" data-ea-edit="' + type + '" data-id="' + esc(id) + '" title="Edit">✎</button>'
    + '<button class="ea-edit" data-ea-retire="' + type + '" data-id="' + esc(id) + '" title="Retire (kept in history)">⊘</button>';
}

// ------------------------------------------------------------------ Obligations / Assure
function renderOblTab() {
  var packs = (EA.assure.packs || []);
  if (!EA.pack && packs.length) EA.pack = packs[0].source;
  var pk = packs.find(function (p) { return p.source === EA.pack; }) || packs[0];
  var have = {}; packs.forEach(function (p) { have[p.pack] = 1; });
  var seedBtns = (EA.data.packs || []).filter(function (p) { return !have[p.id]; }).map(function (p) {
    return canEdit() ? '<button class="add-btn ghost-btn" type="button" data-seed-pack="' + esc(p.id) + '">Add ' + esc(p.label.split(" ").slice(0, 2).join(" ")) + " (" + p.count + " clauses)</button>" : "";
  }).join(" ");
  var head = '<div class="ea-head"><div><h3>Obligations — Assure</h3><p class="muted">Clause-by-clause evidence for each standard: covered by an approved process or an in-date passing control, partial, or a gap. Summaries are Continuum\'s own wording, not the standard\'s text.</p></div>'
    + '<div class="ea-actions">' + seedBtns + " " + addBtn("Obligation", "Obligation") + "</div></div>";
  if (!pk) return head + '<div class="ea-empty">No obligations yet. Add the ISO 9001 or ISO 9004 pack to start mapping evidence.</div>';
  var sel = '<div class="pack-sel">' + packs.map(function (p) {
    return '<button data-pack="' + esc(p.source) + '" class="' + (p.source === pk.source ? "active" : "") + '">' + esc(p.source) + ' <span class="muted">' + p.coverage + "%</span></button>";
  }).join("") + "</div>";
  var bar = '<div class="cov"><div class="cov-bar"><span class="c-covered" style="width:' + pct(pk.covered, pk.total) + '%"></span><span class="c-partial" style="width:' + pct(pk.partial, pk.total) + '%"></span></div>'
    + '<div class="cov-legend">' + pill(pk.covered + " covered", "st-covered") + pill(pk.partial + " partial", "st-partial") + pill(pk.gap + " gap", "st-gap") + "</div></div>";
  var procOpts = (EA.data.processes || []).map(function (p) { return '<option value="' + esc(p.id) + '">' + esc(p.id + " " + p.name) + "</option>"; }).join("");
  var rows = pk.rows.map(function (r) {
    var o = r.obligation;
    return '<tr class="st-row-' + r.status + '"><td class="mono">' + esc(o.clause) + "</td><td><b>" + esc(o.title) + '</b><div class="muted small">' + esc(o.summary || "") + "</div></td>"
      + "<td>" + pill(r.status, "st-" + r.status) + '<div class="muted small">' + esc(r.reason) + "</div></td>"
      + "<td>" + r.evidence.map(function (e) { return '<div class="ev ' + (e.good ? "good" : e.failing ? "bad" : "") + '">' + chip(e.id, e.label, e.kind === "process" ? "process" : "ctl") + "</div>"; }).join("")
      + (canEdit() ? '<div class="map-row"><select data-map-sel="' + esc(o.id) + '"><option value="">map a process…</option>' + procOpts + "</select></div>" : "") + "</td></tr>";
  }).join("");
  return head + sel + bar + '<table class="ea-table assure"><thead><tr><th>Clause</th><th>Requirement</th><th>Status</th><th>Evidence</th></tr></thead><tbody>' + rows + "</tbody></table>";
}
function oblShort(id) {
  var m = /^obl\.(iso900[14])\.(.+)$/.exec(id);
  return m ? m[1].replace("iso", "ISO ") + " §" + m[2].replace(/_/g, ".") : nameOf(id);
}
function pct(a, b) { return b ? Math.round(a / b * 100) : 0; }

// ------------------------------------------------------------------ Risks & controls
function renderRiskTab() {
  var risks = EA.data.records.Risk || [], ctls = EA.data.records.Control || [], legacy = EA.data.legacy_risk_controls || [];
  var grid = {}; risks.forEach(function (r) { var k = r.likelihood + "," + r.impact; (grid[k] = grid[k] || []).push(r); });
  var heat = '<div class="heat"><div class="heat-y">Likelihood</div><div class="heat-grid">';
  for (var l = 5; l >= 1; l--) for (var i = 1; i <= 5; i++) {
    var cell = grid[l + "," + i] || [], sc = l * i;
    heat += '<div class="hc ' + (sc >= 15 ? "h-crit" : sc >= 8 ? "h-warn" : "h-ok") + '" title="likelihood ' + l + " × impact " + i + '">' + cell.map(function (r) { return '<a class="hdot" data-ripple="' + esc(r.id) + '" title="' + esc(r.name) + '">' + esc((r.name || "").slice(0, 1)) + "</a>"; }).join("") + "</div>";
  }
  heat += '</div><div class="heat-x">Impact →</div></div>';
  var mitigated = {}; ctls.forEach(function (c) { (c.risk_refs || []).forEach(function (r) { mitigated[r] = 1; }); });
  var rlist = risks.map(function (r) {
    return "<tr><td>" + chip(r.id, r.name, "risk") + "</td><td class=\"mono\">" + r.likelihood + "×" + r.impact + " = <b>" + (r.likelihood * r.impact) + "</b></td><td>" + esc(r.treatment) + "</td>"
      + "<td>" + (mitigated[r.id] ? pill("mitigated", "st-covered") : r.treatment === "accept" ? pill("accepted", "") : pill("no control", "st-gap")) + "</td><td>" + (r.process_refs || []).map(function (p) { return chip(p, p, "process"); }).join("") + "</td><td>" + rowActions("Risk", r.id) + "</td></tr>";
  }).join("");
  var clist = ctls.map(function (c) {
    return "<tr><td>" + chip(c.id, c.name, "ctl") + '<div class="muted small">' + esc(c.type) + " · " + esc(c.frequency) + "</div></td>"
      + "<td>" + pill(c.last_result.replace("_", " "), "res-" + c.last_result) + '<div class="muted small">' + esc(c.last_tested || "never tested") + "</div></td>"
      + "<td>" + (c.obligation_refs || []).map(function (o) { return chip(o, oblShort(o), "obl"); }).join("") + "</td>"
      + "<td>" + (c.risk_refs || []).map(function (r) { return chip(r, nameOf(r), "risk"); }).join("") + "</td>"
      + "<td>" + (canEdit() ? '<button class="add-btn ghost-btn" data-test="pass" data-id="' + esc(c.id) + '">Passed</button> <button class="add-btn ghost-btn" data-test="fail" data-id="' + esc(c.id) + '">Failed</button> ' : "") + rowActions("Control", c.id) + "</td></tr>";
  }).join("");
  var leg = legacy.length ? '<div class="ea-foot"><b>Phase 1 risk &amp; control entries</b> — still valid; split one into a Risk and a Control to share it across processes and record its tests. '
    + legacy.map(function (r) { return '<span class="leg">' + chip(r.id, r.risk, "risk") + (canEdit() ? '<button class="add-btn ghost-btn" data-split="' + esc(r.id) + '">Split</button>' : "") + "</span>"; }).join("") + "</div>" : "";
  return '<div class="ea-head"><div><h3>Risks &amp; controls</h3><p class="muted">Risks and the controls that mitigate them, with each control\'s test record (ISO 9001 §6.1, §9.1).</p></div><div class="ea-actions">' + addBtn("Risk", "Risk") + " " + addBtn("Control", "Control") + "</div></div>"
    + '<div class="risk-layout">' + heat + '<div class="risk-lists">'
    + (risks.length ? '<table class="ea-table"><thead><tr><th>Risk</th><th>Score</th><th>Treatment</th><th>Status</th><th>Affects</th><th></th></tr></thead><tbody>' + rlist + "</tbody></table>" : '<div class="ea-empty">No risks registered yet.</div>')
    + (ctls.length ? '<table class="ea-table"><thead><tr><th>Control</th><th>Last test</th><th>Satisfies</th><th>Mitigates</th><th></th></tr></thead><tbody>' + clist + "</tbody></table>" : "")
    + "</div></div>" + leg;
}

// ------------------------------------------------------------------ Vitals
function renderVitalsTab() {
  var V = EA.vitals;
  var ring = '<div class="vring s-' + scoreBand(V.score) + '"><div class="vnum">' + V.score + '</div><div class="vlbl">' + V.passed + " of " + V.checks + " checks pass</div></div>";
  var sev = '<div class="vsev">' + ["critical", "warning", "info"].map(function (s) { return pill(V.bySeverity[s] + " " + s, "sev-" + s); }).join("") + "</div>";
  var list = V.findings.map(function (f) {
    return '<li class="vf sev-' + f.severity + '"><span class="vf-sev">' + esc(f.severity) + '</span><div><div>' + (f.nodeId ? chip(f.nodeId, f.name, f.nodeType) : "<b>" + esc(f.name) + "</b>") + " " + esc(f.message) + '</div><div class="muted small">' + esc(f.hint) + "</div></div></li>";
  }).join("");
  return '<div class="ea-head"><div><h3>Vitals — model health</h3><p class="muted">Governance checks across the model: owners, review dates, unguarded agents, failing or overdue controls, unmitigated risks, unmapped clauses (ISO 9004 §11 learning).</p></div></div>'
    + '<div class="vitals">' + ring + sev + "</div>" + (list ? '<ul class="vfind">' + list + "</ul>" : '<div class="ea-empty">No findings — every check passes.</div>');
}

// ------------------------------------------------------------------ Ripple (right pane)
function showRipple(id) {
  eaGet("/api/ripple?id=" + encodeURIComponent(id)).then(function (d) {
    var r = d.ripple, el = document.getElementById("props");
    if (!r || !r.start) { el.innerHTML = '<div class="muted">Nothing to show for ' + esc(id) + ".</div>"; return; }
    var groups = {};
    r.affected.forEach(function (a) { (groups[a.type] = groups[a.type] || []).push(a); });
    var order = ["task", "process", "capability", "application", "agent", "control", "obligation", "risk"];
    var label = { task: "Steps", process: "Processes", capability: "Capabilities", application: "Systems", agent: "Agents", control: "Controls", obligation: "Obligations", risk: "Risks" };
    el.innerHTML = '<div class="ripple"><div class="lbl2">' + (r.mode === "upstream" ? "Depends on" : "Ripple") + "</div><h3>" + esc(r.start.name) + '</h3><div class="muted small mono">' + esc(r.start.type + " · " + r.start.id) + "</div>"
      + '<p class="rsum">' + esc(r.summary) + "</p>"
      + order.filter(function (t) { return groups[t]; }).map(function (t) {
        return '<div class="rgrp"><div class="lbl2">' + label[t] + " (" + groups[t].length + ")</div>" + groups[t].map(function (a) {
          var via = a.path.length ? a.path.map(function (s) { return s.verb; }).join(" → ") : "";
          return '<div class="ritem">' + chip(a.id, a.name, t === "application" ? "app" : t) + (via ? '<div class="muted small">' + esc(via) + "</div>" : "") + "</div>";
        }).join("") + "</div>";
      }).join("")
      + (r.kpis.length ? (function () {
          var seen = {}, uniq = [];
          r.kpis.forEach(function (k) { var key = k.name + "|" + k.procId; if (!seen[key]) { seen[key] = { k: k, n: 0 }; uniq.push(seen[key]); } seen[key].n++; });
          return '<div class="rgrp"><div class="lbl2">KPI touchpoints (' + r.kpis.length + ")</div>" + uniq.map(function (u) {
            return '<div class="ritem">' + esc(u.k.name) + ' <span class="muted small">· ' + esc(u.k.procName) + (u.n > 1 ? " · ×" + u.n + " (process and steps)" : "") + "</span></div>"; }).join("") + "</div>";
        })() : "")
      + (r.guardrails.length ? '<div class="rgrp"><div class="lbl2">Agents acting under a guardrail</div>' + r.guardrails.map(function (g) { return '<div class="ritem ' + (g.blank ? "bad" : "") + '"><b>' + esc(g.agents.join(", ")) + "</b> on " + esc(g.task) + '<div class="muted small mono">' + esc(g.version || "no guardrail") + (g.blank ? " · unguarded" : "") + "</div></div>"; }).join("") + "</div>" : "")
      + "</div>";
    wireChips(el);
  });
}
function wireChips(root) {
  (root || document).querySelectorAll("[data-ripple]").forEach(function (a) {
    a.addEventListener("click", function (e) {
      e.preventDefault();
      var id = a.getAttribute("data-ripple");
      showRipple(id);
    });
  });
}

// ------------------------------------------------------------------ record editor
var EA_FIELDS = {
  Capability: [["name", "Name", "text", 1], ["level", "Level (1–5)", "int", 1], ["parent_ref", "Parent capability", "ref:Capability"], ["importance", "Importance", "enum:low,medium,high,critical"], ["owner", "Owner", "text"], ["process_refs", "Realized by processes", "refs:Process"], ["description", "Description", "area"]],
  Application: [["name", "Name", "text", 1], ["kind", "Kind", "enum:system,agent"], ["vendor", "Vendor", "text"], ["owner", "Owner", "text"], ["lifecycle", "Lifecycle", "enum:plan,active,sunset,retired"], ["sunset_date", "Sunset date", "date"], ["criticality", "Criticality", "enum:low,medium,high,critical"], ["data_class", "Data class", "enum:public,internal,confidential,restricted"], ["capability_refs", "Serves capabilities", "refs:Capability"], ["process_refs", "Supports processes", "refs:Process"], ["task_refs", "Supports steps", "refs:Task"], ["agent_binding_refs", "Agent bindings (agents only)", "refs:Binding"], ["description", "Description", "area"]],
  Obligation: [["title", "Title", "text", 1], ["source", "Source (standard, law, contract, policy)", "text", 1], ["clause", "Clause", "text"], ["summary", "Summary (your own words)", "area"], ["process_refs", "Applies to processes", "refs:Process"]],
  Control: [["name", "Name", "text", 1], ["type", "Type", "enum:preventive,detective,corrective"], ["frequency", "Test frequency", "enum:daily,weekly,monthly,quarterly,semiannual,annual"], ["owner", "Owner", "text"], ["obligation_refs", "Satisfies obligations", "refs:Obligation"], ["risk_refs", "Mitigates risks", "refs:Risk"], ["task_refs", "Runs in steps", "refs:Task"], ["process_refs", "Runs in processes", "refs:Process"], ["description", "Description", "area"]],
  Risk: [["name", "Name", "text", 1], ["likelihood", "Likelihood (1–5)", "int", 1], ["impact", "Impact (1–5)", "int", 1], ["treatment", "Treatment", "enum:mitigate,accept,transfer,avoid"], ["owner", "Owner", "text"], ["process_refs", "Affects processes", "refs:Process"], ["description", "Description", "area"]]
};
function refOptions(kind) {
  var D = EA.data;
  if (kind === "Process") return D.processes.map(function (p) { return [p.id, p.id + " " + p.name]; });
  if (kind === "Task") return D.tasks.map(function (t) { return [t.id, t.id + " " + (t.name || "")]; });
  if (kind === "Binding") return (D.bindings || []).map(function (b) { return [b, b]; });
  return (D.records[kind] || []).map(function (r) { return [r.id, r.name || r.title || r.id]; });
}
function openEditor(type, id) {
  var rec = id ? (EA.data.records[type] || []).find(function (r) { return r.id === id; }) : null;
  var m = document.getElementById("ea-modal");
  var f = EA_FIELDS[type].map(function (fd) {
    var key = fd[0], v = rec ? rec[key] : (fd[2] === "int" ? (key === "level" ? 1 : 3) : null), kind = fd[2];
    var input;
    if (kind.indexOf("enum:") === 0) input = '<select name="' + key + '">' + kind.slice(5).split(",").map(function (o) { return "<option" + (o === v ? " selected" : "") + ">" + o + "</option>"; }).join("") + "</select>";
    else if (kind.indexOf("refs:") === 0) input = '<select name="' + key + '" multiple size="5">' + refOptions(kind.slice(5)).map(function (o) { return '<option value="' + esc(o[0]) + '"' + ((v || []).indexOf(o[0]) >= 0 ? " selected" : "") + ">" + esc(o[1]) + "</option>"; }).join("") + "</select>";
    else if (kind.indexOf("ref:") === 0) input = '<select name="' + key + '"><option value="">— none —</option>' + refOptions(kind.slice(4)).filter(function (o) { return !rec || o[0] !== rec.id; }).map(function (o) { return '<option value="' + esc(o[0]) + '"' + (o[0] === v ? " selected" : "") + ">" + esc(o[1]) + "</option>"; }).join("") + "</select>";
    else if (kind === "area") input = '<textarea name="' + key + '" rows="2">' + esc(v || "") + "</textarea>";
    else input = '<input name="' + key + '" type="' + (kind === "int" ? "number" : kind === "date" ? "date" : "text") + '"' + (kind === "int" ? ' min="1" max="5"' : "") + ' value="' + esc(v == null ? "" : v) + '"' + (fd[3] ? " required" : "") + ">";
    return "<label>" + esc(fd[1]) + input + "</label>";
  }).join("");
  m.querySelector(".modal-head h2").textContent = (rec ? "Edit " : "New ") + type.toLowerCase();
  document.getElementById("ea-form-body").innerHTML = f + '<label>Why <span class="hint">recorded in the change history (ISO 9001 §7.5)</span><input name="__reason" required placeholder="e.g. mapped during the Q4 architecture review"></label>';
  var msg = document.getElementById("ea-msg"); msg.hidden = true;
  m.hidden = false;
  var form = document.getElementById("ea-form");
  form.onsubmit = function (e) {
    e.preventDefault();
    var out = {};
    EA_FIELDS[type].forEach(function (fd) {
      var el = form.elements[fd[0]], kind = fd[2], val;
      if (kind.indexOf("refs:") === 0) val = Array.prototype.filter.call(el.options, function (o) { return o.selected; }).map(function (o) { return o.value; });
      else if (kind === "int") val = el.value === "" ? null : parseInt(el.value, 10);
      else val = el.value === "" ? (kind.indexOf("ref:") === 0 || kind === "date" ? null : "") : el.value;
      if (val === null && !rec) return;
      if (rec && JSON.stringify(rec[fd[0]] == null ? null : rec[fd[0]]) === JSON.stringify(val)) return;
      out[fd[0]] = val;
    });
    var body = rec ? { op: "edit", type: type, id: rec.id, changes: out } : { op: "add", type: type, fields: out };
    body.reason = form.elements.__reason.value;
    eaPost("/api/ea", body).then(function (res) {
      if (!res.ok) { msg.textContent = res.error; msg.className = "msg err"; msg.hidden = false; return; }
      m.hidden = true;
      eaReload();
      ccToast((rec ? "Saved " : "Added ") + (res.result.name || res.result.title || res.result.id) + " · v" + res.result.version, "ok");
    });
  };
}

// ------------------------------------------------------------------ wiring
function reasonPrompt(btn, label, cb) {
  var row = document.createElement("div");
  row.className = "reason-row";
  row.innerHTML = '<input placeholder="' + esc(label) + '"><button class="add-btn" type="button">OK</button>';
  btn.parentNode.appendChild(row);
  var inp = row.querySelector("input"); inp.focus();
  row.querySelector("button").addEventListener("click", function () { if (inp.value.trim()) { cb(inp.value.trim()); row.remove(); } else inp.focus(); });
}
function wireEA() {
  var c = $("#canvas");
  wireChips(c);
  c.querySelectorAll("[data-ea-add]").forEach(function (b) { b.addEventListener("click", function () { openEditor(b.getAttribute("data-ea-add")); }); });
  c.querySelectorAll("[data-ea-edit]").forEach(function (b) { b.addEventListener("click", function () { openEditor(b.getAttribute("data-ea-edit"), b.getAttribute("data-id")); }); });
  c.querySelectorAll("[data-ea-retire]").forEach(function (b) {
    b.addEventListener("click", function () {
      reasonPrompt(b, "Why retire it?", function (why) {
        eaPost("/api/ea", { op: "retire", type: b.getAttribute("data-ea-retire"), id: b.getAttribute("data-id"), reason: why })
          .then(function (res) { if (!res.ok) ccToast(res.error, "err"); else { ccToast("Retired — it stays in the history.", "ok"); eaReload(); } });
      });
    });
  });
  c.querySelectorAll("[data-pack]").forEach(function (b) { b.addEventListener("click", function () { EA.pack = b.getAttribute("data-pack"); renderCenter(); }); });
  c.querySelectorAll("[data-seed-pack]").forEach(function (b) {
    b.addEventListener("click", function () {
      b.disabled = true;
      eaPost("/api/ea", { op: "seed_pack", pack: b.getAttribute("data-seed-pack"), reason: "added obligation pack" })
        .then(function (res) { if (!res.ok) { ccToast(res.error, "err"); b.disabled = false; } else { ccToast("Added " + res.result.added + " clauses.", "ok"); eaReload(); } });
    });
  });
  c.querySelectorAll("[data-map-sel]").forEach(function (s) {
    s.addEventListener("change", function () {
      if (!s.value) return;
      eaPost("/api/ea", { op: "link", type: "Obligation", id: s.getAttribute("data-map-sel"), field: "process_refs", ref: s.value, reason: "mapped clause to process" })
        .then(function (res) { if (!res.ok) ccToast(res.error, "err"); else eaReload(); });
    });
  });
  c.querySelectorAll("[data-test]").forEach(function (b) {
    b.addEventListener("click", function () {
      eaPost("/api/ea", { op: "test", type: "Control", id: b.getAttribute("data-id"), result: b.getAttribute("data-test"), reason: "recorded control test" })
        .then(function (res) { if (!res.ok) ccToast(res.error, "err"); else { ccToast("Test recorded: " + res.result.last_result + (res.result.last_result === "fail" ? " — raise a corrective action (ISO 9001 §10.2)" : ""), res.result.last_result === "fail" ? "warn" : "ok"); eaReload(); } });
    });
  });
  c.querySelectorAll("[data-split]").forEach(function (b) {
    b.addEventListener("click", function () {
      reasonPrompt(b, "Why split it?", function (why) {
        eaPost("/api/ea", { op: "split_rc", id: b.getAttribute("data-split"), reason: why })
          .then(function (res) { if (!res.ok) ccToast(res.error, "err"); else { ccToast("Split into " + res.result.risk.id + " and " + res.result.control.id, "ok"); eaReload(); } });
      });
    });
  });
}
(function () {
  var b = document.getElementById("enterprise-btn");
  if (b) b.addEventListener("click", function () {
    state.view = "enterprise";
    document.querySelectorAll(".views button").forEach(function (x) { x.classList.remove("active"); });
    renderCenter();
    eaReload();
  });
  var m = document.getElementById("ea-modal");
  if (m) {
    document.getElementById("ea-close").addEventListener("click", function () { m.hidden = true; });
    m.addEventListener("click", function (e) { if (e.target === m) m.hidden = true; });
  }
})();

// ------------------------------------------------------------------ Imports view
CENTER_VIEWS.imports = function () {
  var c = $("#canvas");
  if (!EA.imports) { c.innerHTML = '<div class="muted pad">loading…</div>'; loadImports(); return; }
  var B = EA.imports.batches || [], S = EA.staged || [];
  var canDecide = typeof isRole !== "function" || isRole("approver"), canAdmin = typeof isRole !== "function" || isRole("admin");
  var staged = S.length ? S.map(function (s) {
    return '<div class="stg"><div class="stg-head">' + pill(s.change === "delete" ? "retire" : "update", s.change === "delete" ? "st-gap" : "st-partial")
      + " <b>" + esc(s.etype) + " " + esc(s.id) + '</b> <span class="muted small">' + esc(s.sid) + " · from " + esc(s.batch) + " · staged against v" + s.based_on_version + "</span></div>"
      + '<div class="muted small">' + esc((s.reasons || []).join("; ")) + "</div>"
      + (s.diff && s.diff.length ? '<table class="ea-table diff"><thead><tr><th>Field</th><th>In Continuum now</th><th>Incoming</th></tr></thead><tbody>' + s.diff.map(function (d) {
        return '<tr><td class="mono">' + esc(d.field) + '</td><td class="d-cur">' + esc(fmtVal(d.current)) + '</td><td class="d-inc">' + esc(fmtVal(d.incoming)) + "</td></tr>";
      }).join("") + "</tbody></table>" : "")
      + (canDecide ? '<div class="stg-act"><button class="add-btn" data-accept="' + esc(s.sid) + '" data-v="' + s.based_on_version + '">Accept incoming</button> <button class="add-btn ghost-btn" data-reject="' + esc(s.sid) + '">Keep ours</button></div>' : '<div class="muted small">An approver decides staged changes.</div>')
      + "</div>";
  }).join("") : '<div class="ea-empty">Nothing waiting for review. Imports that would overwrite a record edited here are held for review in this list.</div>';
  var batches = B.length ? '<table class="ea-table"><thead><tr><th>Batch</th><th>When</th><th>Who</th><th>Source</th><th>Created</th><th>Updated</th><th>Retired</th><th>Staged</th><th></th></tr></thead><tbody>' + B.map(function (b) {
    return '<tr><td class="mono">' + esc(b.batch) + (b.kind !== "import" ? " " + pill(b.kind, "") : "") + "</td><td>" + esc((b.ts || "").slice(0, 16).replace("T", " ")) + "</td><td>" + esc(b.user || b.actor || "") + "</td><td>" + esc(b.source || b.reason || "") + "</td>"
      + "<td>" + (b.created || 0) + "</td><td>" + (b.updated || 0) + "</td><td>" + (b.retired || 0) + "</td><td>" + (b.staged || 0) + "</td>"
      + "<td>" + (canAdmin && b.kind === "import" && !B.some(function (x) { return x.kind === "revert" && x.batch === b.batch; }) ? '<button class="add-btn ghost-btn" data-revert="' + esc(b.batch) + '">Revert</button>' : "") + "</td></tr>";
  }).join("") + "</tbody></table>" : '<div class="ea-empty">No imports yet.</div>';
  c.innerHTML = '<div class="ea"><div class="ea-head"><div><h3>Imports</h3><p class="muted">Every import is a numbered batch. An import never overwrites a record edited in Continuum: the incoming version waits here for review.</p></div>'
    + (canAdmin ? '<label class="add-btn ghost-btn filebtn">Import a model export (.json)…<input id="imp-file" type="file" accept=".json,application/json" hidden></label>' : "") + "</div>"
    + '<div id="imp-preview"></div><h3 class="sub-h">Waiting for review (' + S.length + ")</h3>" + staged + '<h3 class="sub-h">Batches</h3>' + batches + "</div>";
  wireImports();
};
function fmtVal(v) { return v == null ? "—" : typeof v === "object" ? JSON.stringify(v) : String(v); }
function loadImports() {
  return Promise.all([eaGet("/api/imports"), eaGet("/api/staged")]).then(function (r) {
    EA.imports = r[0]; EA.staged = r[1].staged || [];
    setImpBadge(EA.staged.length);
    if (state.view === "imports") renderCenter();
  });
}
function setImpBadge(n) { var b = document.getElementById("imp-badge"); if (b) { b.textContent = n; b.hidden = !n; } }
function wireImports() {
  var c = $("#canvas");
  c.querySelectorAll("[data-accept]").forEach(function (b) {
    b.addEventListener("click", function () {
      eaPost("/api/staged", { op: "accept", sid: b.getAttribute("data-accept"), expected_version: parseInt(b.getAttribute("data-v"), 10), reason: "accepted incoming version" })
        .then(function (res) { if (res.ok) { ccToast("Accepted — saved as v" + res.result.version, "ok"); load(); } else if (!res.conflict) ccToast(res.error, "err"); loadImports(); });
    });
  });
  c.querySelectorAll("[data-reject]").forEach(function (b) {
    b.addEventListener("click", function () {
      reasonPrompt(b, "Why keep ours?", function (why) {
        eaPost("/api/staged", { op: "reject", sid: b.getAttribute("data-reject"), reason: why })
          .then(function (res) { if (!res.ok) ccToast(res.error, "err"); else ccToast("Kept ours. It won't be raised again unless the source changes it.", "ok"); loadImports(); });
      });
    });
  });
  c.querySelectorAll("[data-revert]").forEach(function (b) {
    b.addEventListener("click", function () {
      reasonPrompt(b, "Why revert this import?", function (why) {
        eaPost("/api/imports/revert", { batch: b.getAttribute("data-revert"), reason: why }).then(function (res) {
          if (!res.ok) { ccToast(res.error, "err"); return; }
          ccToast("Reverted " + res.result.reverted + " change(s)" + (res.result.skipped.length ? "; skipped " + res.result.skipped.length + " edited since" : ""), "ok");
          load(); loadImports();
        });
      });
    });
  });
  var f = document.getElementById("imp-file");
  if (f) f.addEventListener("change", function () {
    var file = f.files[0]; if (!file) return;
    file.text().then(function (txt) {
      var seed; try { seed = JSON.parse(txt); } catch (e) { ccToast("That file is not JSON.", "err"); return; }
      var pv = document.getElementById("imp-preview");
      pv.innerHTML = '<div class="imp-box"><label>Source name <input id="imp-src" placeholder="e.g. SYSPRO export" value="' + esc(file.name.replace(/\.json$/, "")) + '"></label>'
        + '<button class="add-btn" id="imp-plan" type="button">Preview</button><div id="imp-out"></div></div>';
      document.getElementById("imp-plan").addEventListener("click", function () {
        var src = document.getElementById("imp-src").value.trim();
        eaPost("/api/imports", { seed: seed, source: src, dry: true }).then(function (res) {
          var out = document.getElementById("imp-out");
          if (!res.ok) { out.innerHTML = '<div class="msg err">' + esc(res.error) + "</div>"; return; }
          var p = res.plan;
          out.innerHTML = '<div class="imp-plan">' + pill(p.created + " new", "st-covered") + pill(p.updated + " updated", "st-covered") + pill(p.retired + " retired", "") + pill(p.unchanged + " unchanged", "") + pill(p.staged + " held for review", p.staged ? "st-partial" : "")
            + '</div><button class="add-btn" id="imp-go" type="button">Import</button>';
          document.getElementById("imp-go").addEventListener("click", function () {
            eaPost("/api/imports", { seed: seed, source: src, reason: "imported via canvas" }).then(function (r2) {
              if (!r2.ok) { ccToast(r2.error, "err"); return; }
              ccToast("Import " + r2.result.batch + " done — " + r2.result.staged + " held for review.", "ok");
              load(); loadImports();
            });
          });
        });
      });
    });
  });
}
(function () {
  var b = document.getElementById("imports-btn");
  if (b) b.addEventListener("click", function () {
    state.view = "imports";
    document.querySelectorAll(".views button").forEach(function (x) { x.classList.remove("active"); });
    EA.imports = null;
    renderCenter();
  });
  // live: a staged change or a decision anywhere refreshes the badge (via app.js's stream)
  eaGet("/api/staged").then(function (d) { if (d && d.ok) setImpBadge((d.staged || []).length); }).catch(function () {});
})();

// called by app.js's single EventSource for messages it doesn't handle itself
function onStreamExtra(msg) {
  if (msg === "imports") loadImports();
  if (msg === "changed" && state.view === "enterprise") eaReload();
}
