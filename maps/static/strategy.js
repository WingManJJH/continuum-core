"use strict";
// Strategy views — OKR board, X-matrix, and strategy alignment.
// Classic script after app.js; reuses globals ($, esc, state, renderCenter,
// openProcess, shortRole). Read-only visualisations over /api/strategy.

function kpiStat(k) {
  var cls = k.status === "on_target" ? "good" : k.status === "off_target" ? "crit" : "warn";
  var val = (k.value == null ? "—" : k.value) + (k.unit ? " " + k.unit : "");
  return '<span class="kpi ' + cls + '" data-kpi="' + esc(k.id) + '" title="target ' + esc(String(k.target)) + '">'
    + esc(k.name) + " · <b>" + esc(String(val)) + "</b> / " + esc(String(k.target))
    + (k.status === "off_target" ? " ✗" : k.status === "on_target" ? " ✓" : "") + "</span>";
}
function kpiTree(k, depth) {
  var kids = (k.children || []).map(function (c) { return kpiTree(c, (depth || 0) + 1); }).join("");
  return '<div class="kpirow" style="margin-left:' + ((depth || 0) * 16) + 'px">' + kpiStat(k)
    + ' <button class="strat-edit" data-strat-edit="kpi" data-strat-id="' + esc(k.id) + '" title="Edit KPI">✎</button></div>' + kids;
}

function objCard(o) {
  var procs = (o.processes || []).map(function (p) { return '<a class="pchip" data-open="' + esc(p.id) + '">' + esc(p.id) + "</a>"; }).join("");
  var badge = o.type === "breakthrough" ? '<span class="obadge bt">breakthrough</span>' : '<span class="obadge an">annual</span>';
  var dot = o.fulfilled ? '<span class="gdot good"></span>' : '<span class="gdot ' + (o.off_target_kpis.length ? "warn" : "muted") + '"></span>';
  return '<div class="ocard" data-obj="' + esc(o.id) + '">'
    + '<div class="ohead">' + dot + badge + '<span class="oname">' + esc(o.name) + "</span>"
    + (o.owner ? '<span class="oowner">' + esc(shortRole(o.owner)) + "</span>" : "")
    + ' <button class="strat-edit" data-strat-edit="objective" data-strat-id="' + esc(o.id) + '" title="Edit objective">✎</button></div>'
    + (o.target && o.target.statement ? '<div class="otarget">' + esc(o.target.statement) + "</div>" : "")
    + '<div class="okr-kpis"><div class="lbl2">Key results</div>' + (o.kpis.length ? o.kpis.map(function (k) { return kpiTree(k, 0); }).join("") : '<span class="muted">no KPIs</span>') + "</div>"
    + '<div class="okr-procs"><div class="lbl2">Supporting processes</div>' + (procs || '<span class="muted">none — alignment gap</span>') + "</div></div>";
}

// ---------- OKR board ----------
function renderOKR(S) {
  var by = {}; S.objectives.forEach(function (o) { by[o.id] = o; });
  var bts = S.breakthroughs.map(function (id) { return by[id]; });
  var placed = {};
  var html = bts.map(function (bt) {
    placed[bt.id] = 1;
    var annuals = S.objectives.filter(function (o) { return o.parent_ref === bt.id; });
    annuals.forEach(function (a) { placed[a.id] = 1; });
    return '<div class="btblock">' + objCard(bt)
      + (annuals.length ? '<div class="annuals">' + annuals.map(objCard).join("") + "</div>" : "") + "</div>";
  }).join("");
  var loose = S.objectives.filter(function (o) { return !placed[o.id]; });
  if (loose.length) html += '<div class="btblock">' + loose.map(objCard).join("") + "</div>";
  return '<div class="okr">' + entBanner(S.enterprise) + '<div class="okrhead">Objectives &amp; key results — breakthrough goals, their annual objectives, and the KPIs and processes that deliver them.</div>' + html + "</div>";
}

function entBanner(e) {
  if (!e) return "";
  var vals = (e.values || []).map(function (v) { return '<span class="val">' + esc(v) + "</span>"; }).join("");
  return '<div class="entbanner"><div class="entname">' + esc(e.name)
    + ' <button class="strat-edit" data-strat-edit="enterprise" title="Edit mission / vision / values">✎</button></div>'
    + (e.mission ? '<div class="entrow"><b>Mission</b> ' + esc(e.mission) + "</div>" : "")
    + (e.vision ? '<div class="entrow"><b>Vision</b> ' + esc(e.vision) + "</div>" : "")
    + (vals ? '<div class="entvals">' + vals + "</div>" : "") + "</div>";
}

// ---------- X-matrix (ISOX Nexus Hoshin layout, governed data) ----------
function xCell(L, type, a, b) {
  var m = L.find(function (x) { return x.type === type && x.a === a && x.b === b; });
  var strength = m ? m.strength : "";                 // "" = derived-empty; "none" = manual-empty
  var manual = m && m.manual;
  var state = manual ? strength : "derived";
  var cls = (strength && strength !== "none" ? strength : "empty") + (manual ? " manual" : "");
  return '<div class="agc ' + cls + '" data-ct="' + esc(type) + '" data-a="' + esc(a) + '" data-b="' + esc(b)
    + '" data-state="' + esc(state) + '" title="' + esc(strength || "none") + (manual ? " (manual — click to change)" : " (derived — click to pin)") + '"></div>';
}
// intersection grid: fixed 16px cells at 22px pitch so it lines up with the axis cards
var XCELL = 16, XGAP = 6, XAXIS = 210;   // cell px, gap px, vertical-card length px
function xGrid(rows, cols, type, abFn, L, justify) {
  var cells = "";
  for (var r = 0; r < rows.length; r++) for (var c = 0; c < cols.length; c++) {
    var ab = abFn(rows[r], cols[c]);
    cells += xCell(L, type, ab[0], ab[1]);
  }
  return '<div class="agrid" style="grid-template-columns:repeat(' + (cols.length || 1) + ',' + XCELL + 'px);'
    + 'grid-template-rows:repeat(' + (rows.length || 1) + ',' + XCELL + 'px);gap:' + XGAP + 'px;'
    + (justify === "end" ? "justify-content:flex-end;" : "") + '">' + cells + "</div>";
}
function _xPen(kind, id) {
  return kind ? ' <button class="strat-edit sx" data-strat-edit="' + kind + '" data-strat-id="' + esc(id) + '" title="Edit">✎</button>' : "";
}
// a vertical (rotated) axis card — objectives / metrics / owners
function vCard(id, label, cls, extra, editKind) {
  return '<div class="vcard ' + cls + '" ' + (extra || "") + ' style="height:' + XAXIS + 'px"><span class="vtext">' + esc(label) + _xPen(editKind, id) + "</span></div>";
}
// a horizontal axis card — initiatives / goals
function hCard(id, label, cls, extra, editKind) {
  return '<div class="hcard ' + cls + '" ' + (extra || "") + "><span>" + esc(label) + _xPen(editKind, id) + "</span></div>";
}
function renderXMatrix(X) {
  var O = X.objectives, G = X.goals, I = X.initiatives, M = X.metrics, W = X.owners, L = X.links;
  var objCards = O.map(function (o) { return vCard(o.id, o.name, "nx-obj rot", 'data-obj="' + esc(o.id) + '"', "objective"); }).join("");
  var metCards = M.map(function (m) {
    var st = m.status === "on_target" ? "good" : m.status === "off_target" ? "crit" : "";
    var lbl = m.name + " · " + (m.value == null ? "—" : m.value) + "/" + m.target + (m.status === "off_target" ? " ✗" : m.status === "on_target" ? " ✓" : "");
    return vCard(m.id, lbl, "nx-met " + st, 'data-kpi="' + esc(m.id) + '"', "kpi");
  }).join("");
  var ownCards = W.map(function (o) { return vCard(o.id, o.name, "nx-own rot", "", "role"); }).join("");
  var initCards = I.map(function (it) { return hCard(it.id, it.name, "nx-init", "", "initiative"); }).join("")
    + '<button class="nx-addinit" data-strat-add="initiative" title="Add an initiative">+</button>';
  var goalCards = G.map(function (g) { return hCard(g.id, g.name, "nx-goal", 'data-obj="' + esc(g.id) + '"', "objective"); }).join("");

  var A = xGrid(I, O, "init_obj", function (it, o) { return [it.id, o.id]; }, L);              // init(rows) × obj(cols)
  var C = xGrid(I, M, "init_metric", function (it, m) { return [it.id, m.id]; }, L);           // init × metric
  var D = xGrid(I, W, "init_owner", function (it, w) { return [it.id, w.id]; }, L);            // init × owner
  var Icorner = xGrid(G, O, "obj_goal", function (g, o) { return [o.id, g.id]; }, L);          // goal(rows) × obj(cols)

  var grid = '<div class="nexus"><div class="nexus-grid">'
    + '<div class="nq tl"><span class="clab">A · init × objective</span>' + A + "</div>"
    + '<div class="nq initiatives"><span class="alab">▲ Change initiatives</span><div class="haxis">' + initCards + "</div></div>"
    + '<div class="nq tr"><span class="clab">C · init × metric</span>' + C + "</div>"
    + '<div class="nq tr2"><span class="clab">D · init × owner</span>' + D + "</div>"
    + '<div class="nq objectives"><span class="alab vleft">◄ Objectives</span><div class="vaxis">' + objCards + "</div></div>"
    + '<div class="nq center"><div class="xcross"><span>X</span></div></div>'
    + '<div class="nq metrics"><span class="alab vright">Metrics ►</span><div class="vaxis">' + metCards + "</div></div>"
    + '<div class="nq owners"><span class="alab vright">Owners</span><div class="vaxis">' + ownCards + "</div></div>"
    + '<div class="nq bl"><span class="clab">I · objective × goal</span>' + Icorner + "</div>"
    + '<div class="nq goals"><span class="alab">▼ Organizational goals</span><div class="haxis">' + goalCards + "</div></div>"
    + "</div></div>";

  var key = '<div class="nxkey"><b>Correlation</b> <span class="agc primary"></span> primary '
    + '<span class="agc secondary"></span> secondary <span class="agc leading"></span> leading '
    + '<span class="agc supporting"></span> supporting · <span class="agc manual empty" style="border:1px solid #14425a"></span> manual override · '
    + '<span class="kpi crit" style="padding:0 6px">✗</span> KPI off target &nbsp;—&nbsp; <b>click a cell</b> to cycle its strength (audited).</div>';
  return '<div class="xmatrix">' + entBanner(X.enterprise)
    + '<div class="okrhead">Hoshin X-matrix (ISOX Nexus layout), live over the governed model — objectives roll up to goals, initiatives drive objectives / metrics / owners, and the metrics are the process KPIs (✗ = off target). Derived from the graph; click any corner cell to set a manual strength.</div>'
    + '<div class="nxwrap">' + grid + "</div>" + key + gapsPanel(X.gaps) + "</div>";
}

function gapsPanel(g) {
  function line(label, arr, cls) { return '<div class="gapline"><span class="gaplbl ' + (cls || "") + '">' + label + "</span> " + (arr.length ? arr.map(function (x) { return '<span class="pchip">' + esc(x) + "</span>"; }).join("") : '<span class="muted">none</span>') + "</div>"; }
  return '<div class="gaps"><div class="lbl2">Alignment gaps (honest, from the graph)</div>'
    + line("Objectives with no process", g.objectives_no_process, "warn")
    + line("Processes with no objective", g.processes_no_objective, "warn")
    + line("KPIs off target", g.kpis_off_target, "crit") + "</div>";
}

// ---------- Strategy alignment ----------
function renderAlignment(S) {
  var rows = S.objectives.map(function (o) {
    var procs = (o.processes || []).map(function (p) { return '<a class="pchip" data-open="' + esc(p.id) + '">' + esc(p.id) + " · " + esc(p.name) + "</a>"; }).join("");
    return '<div class="alrow" data-obj="' + esc(o.id) + '"><div class="alobj">'
      + (o.type === "breakthrough" ? '<span class="obadge bt">BT</span>' : '<span class="obadge an">A</span>')
      + '<b>' + esc(o.name) + "</b>" + (o.fulfilled ? ' <span class="gdot good"></span>' : ' <span class="gdot warn"></span>') + "</div>"
      + '<div class="alarrow">→</div><div class="alprocs">' + (procs || '<span class="muted">no supporting process (gap)</span>') + "</div></div>";
  }).join("");
  return '<div class="align">' + entBanner(S.enterprise)
    + '<div class="okrhead">Strategy alignment — every objective and the processes that support it (at any level 1–5). Click a process to open it.</div>'
    + rows + gapsPanel(S.gaps) + "</div>";
}

// ---------- dispatch + wiring ----------
function renderStrategy(data, tab) {
  var tabs = [["okr", "OKR board"], ["xmatrix", "X-matrix"], ["align", "Alignment"]];
  var bar = '<div class="strat-tabs">' + tabs.map(function (t) { return '<button data-stab="' + t[0] + '"' + (t[0] === tab ? ' class="active"' : "") + ">" + t[1] + "</button>"; }).join("") + "</div>";
  var body = tab === "xmatrix" ? renderXMatrix(data.xmatrix) : tab === "align" ? renderAlignment(data.strategy) : renderOKR(data.strategy);
  return bar + '<div class="strat-body">' + body + "</div>";
}
function postCorrelation(body) { return fetch("/api/correlation", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).then(function (r) { return r.json(); }); }
var CORR_CYCLE = { derived: "primary", primary: "secondary", secondary: "leading", leading: "supporting", supporting: "none", none: "__clear__" };
function wireStrategy() {
  var c = document.getElementById("canvas"); if (!c) return;
  c.querySelectorAll("[data-stab]").forEach(function (b) {
    b.addEventListener("click", function () { state.stratTab = b.getAttribute("data-stab"); renderCenter(); });
  });
  // click an X-matrix cell to cycle its strength (derived → primary → … → off → derived)
  c.querySelectorAll(".agc[data-ct]").forEach(function (cell) {
    cell.addEventListener("click", function (e) {
      e.stopPropagation();
      var ct = cell.getAttribute("data-ct"), a = cell.getAttribute("data-a"), b = cell.getAttribute("data-b");
      var next = CORR_CYCLE[cell.getAttribute("data-state") || "derived"] || "primary";
      var body = next === "__clear__"
        ? { op: "clear", type: ct, a: a, b: b, actor: ACTOR, reason: "cleared X-matrix cell (revert to derived)" }
        : { type: ct, a: a, b: b, strength: next, actor: ACTOR, reason: "set X-matrix cell strength via canvas" };
      postCorrelation(body).then(function (res) {
        if (!res.ok) { alert("Rejected: " + res.error); return; }
        fetch("/api/strategy").then(function (r) { return r.json(); }).then(function (d) { state.strategy = d; renderCenter(); });
      });
    });
  });
  c.querySelectorAll("[data-open]").forEach(function (el) {
    el.addEventListener("click", function () { openProcess(el.getAttribute("data-open")); });
  });
  // pencil → open the right editor (gated like every other edit). Owners are
  // roles, so they open the role drawer; everything else the strategy editor.
  c.querySelectorAll(".strat-edit").forEach(function (b) {
    b.addEventListener("click", function (e) {
      e.stopPropagation();
      var kind = b.getAttribute("data-strat-edit"), id = b.getAttribute("data-strat-id") || "";
      if (kind === "role") { if (typeof openRoleDrawer === "function") openRoleDrawer(id); }
      else openStratEdit(kind, id);
    });
  });
  c.querySelectorAll("[data-strat-add]").forEach(function (b) {
    b.addEventListener("click", function (e) { e.stopPropagation(); openStratEdit(b.getAttribute("data-strat-add"), ""); });
  });
  // click an objective anywhere -> highlight it + its processes across the view
  c.querySelectorAll("[data-obj]").forEach(function (el) {
    el.addEventListener("click", function (e) {
      if (e.target.closest("[data-open]") || e.target.closest(".strat-edit")) return;
      var id = el.getAttribute("data-obj");
      c.querySelectorAll("[data-obj]").forEach(function (x) { x.classList.toggle("objsel", x.getAttribute("data-obj") === id); });
    });
  });
}

// ---------- strategy entity editor (enterprise / objective / KPI) ----------
function _findKpi(kpis, id) {
  for (var i = 0; i < (kpis || []).length; i++) {
    if (kpis[i].id === id) return kpis[i];
    var f = _findKpi(kpis[i].children, id); if (f) return f;
  }
  return null;
}
function _stratEntity(kind, id) {
  var S = state.strategy && state.strategy.strategy; if (!S) return null;
  if (kind === "enterprise") return S.enterprise || {};
  if (kind === "objective") return (S.objectives || []).find(function (o) { return o.id === id; }) || null;
  if (kind === "initiative") {
    var X = state.strategy && state.strategy.xmatrix;
    return (X && X.initiatives || []).find(function (it) { return it.id === id; }) || null;
  }
  if (kind === "kpi") {
    for (var i = 0; i < (S.objectives || []).length; i++) {
      var f = _findKpi(S.objectives[i].kpis, id); if (f) return f;
    }
  }
  return null;
}
var STRAT_META = {
  enterprise: { entity: "Enterprise", op: "edit_enterprise", label: "Enterprise" },
  objective:  { entity: "StrategicObjective", op: "edit_objective", label: "Objective" },
  kpi:        { entity: "KPI", op: "edit_kpi", label: "KPI" },
  initiative: { entity: "Initiative", op: "edit_initiative", label: "Initiative" },
};
function openStratEdit(kind, id) {
  var meta = STRAT_META[kind]; if (!meta) return;
  var adding = kind === "initiative" && !id;   // + Add initiative (no id yet)
  var e = adding ? { name: "", description: "" } : _stratEntity(kind, id);
  if (!e) { alert("Could not find that item — try reloading the strategy view."); return; }
  var modal = document.getElementById("strat-modal"), body = document.getElementById("strat-body");
  document.getElementById("strat-title").textContent = (adding ? "Add " : "Edit ") + meta.label + (id ? " · " + id : "");
  var fields = "";
  if (kind === "enterprise") {
    fields = '<label>Mission<textarea id="se-mission" rows="2">' + esc(e.mission || "") + "</textarea></label>"
      + '<label>Vision<textarea id="se-vision" rows="2">' + esc(e.vision || "") + "</textarea></label>"
      + '<label>Values <span class="hint">comma-separated</span><input id="se-values" value="' + esc((e.values || []).join(", ")) + '"></label>';
  } else if (kind === "objective") {
    fields = '<label>Name<input id="se-name" value="' + esc(e.name || "") + '"></label>';
  } else if (kind === "initiative") {
    fields = '<label>Name<input id="se-name" value="' + esc(e.name || "") + '"></label>'
      + '<label>Description<textarea id="se-desc" rows="2">' + esc(e.description || "") + "</textarea></label>";
  } else {  // kpi
    fields = '<label>Name<input id="se-name" value="' + esc(e.name || "") + '"></label>'
      + '<label>Target<input id="se-target" value="' + esc(e.target == null ? "" : String(e.target)) + '"></label>';
  }
  body.innerHTML = '<form id="strat-form">' + fields
    + '<label>Reason for change <span class="hint">required · §7.5</span><input id="se-reason" placeholder="why?"></label>'
    + (typeof gateControlHTML === "function" ? gateControlHTML(meta.entity) : "")
    + '<div id="strat-msg" class="msg" hidden></div>'
    + '<div class="actions"><button type="button" id="se-cancel" class="ghost">Cancel</button><button type="submit" class="save">Save new version</button></div></form>';
  modal.hidden = false;
  document.getElementById("se-cancel").onclick = function () { modal.hidden = true; };
  document.getElementById("strat-form").onsubmit = function (ev) {
    ev.preventDefault();
    var changes = {}, newId = id;
    if (kind === "enterprise") {
      changes = { mission: document.getElementById("se-mission").value.trim(),
                  vision: document.getElementById("se-vision").value.trim(),
                  values: parseCsv(document.getElementById("se-values").value) };
    } else if (kind === "objective") {
      changes = { name: document.getElementById("se-name").value.trim() };
    } else if (kind === "initiative") {
      changes = { name: document.getElementById("se-name").value.trim(),
                  description: document.getElementById("se-desc").value.trim() };
      if (adding) {
        if (!changes.name) { alert("An initiative needs a name."); return; }
        newId = "init." + changes.name.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "");
      }
    } else {
      changes = { name: document.getElementById("se-name").value.trim() };
      var tv = document.getElementById("se-target").value.trim();
      if (tv !== "") changes.target = isNaN(Number(tv)) ? tv : Number(tv);
    }
    var reason = document.getElementById("se-reason").value.trim();
    var msg = document.getElementById("strat-msg");
    // build the gated proposal args to match each store method's signature
    var gateOp = adding ? "add_initiative" : meta.op;
    var args = kind === "enterprise" ? { changes: changes }
             : kind === "objective" ? { obj_id: id, changes: changes }
             : kind === "initiative" ? (adding ? { init_id: newId, name: changes.name, description: changes.description }
                                               : { init_id: id, changes: changes })
             : { kpi_id: id, changes: changes };
    if (typeof routeThroughGate === "function" && routeThroughGate(
        meta.entity, document.getElementById("strat-form"), gateOp, args,
        (adding ? "New " : "") + meta.label + (id ? " · " + id : ""), reason, msg)) {
      return;
    }
    // direct save
    var endpoint = kind === "enterprise" ? "/api/enterprise" : kind === "objective" ? "/api/objective"
                 : kind === "initiative" ? "/api/initiative" : "/api/kpi";
    var payload = kind === "enterprise" ? { changes: changes, actor: ACTOR, reason: reason }
                : kind === "initiative" ? (adding
                    ? { op: "add", id: newId, name: changes.name, description: changes.description, actor: ACTOR, reason: reason }
                    : { op: "edit", id: id, changes: changes, actor: ACTOR, reason: reason })
                : { id: id, changes: changes, actor: ACTOR, reason: reason };
    fetch(endpoint, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) })
      .then(function (r) { return r.json(); }).then(function (res) {
        if (!res.ok) { msg.textContent = "Rejected: " + res.error; msg.className = "msg err"; msg.hidden = false; return; }
        modal.hidden = true;
        fetch("/api/strategy").then(function (r) { return r.json(); }).then(function (d) { state.strategy = d; if (state.view === "strategy") renderCenter(); });
      });
  };
}
(function () {
  var cl = document.getElementById("strat-close");
  if (cl) cl.addEventListener("click", function () { document.getElementById("strat-modal").hidden = true; });
  var m = document.getElementById("strat-modal");
  if (m) m.addEventListener("click", function (e) { if (e.target === m) m.hidden = true; });
})();
(function () {
  var sb = document.getElementById("strategy-btn");
  if (sb) sb.addEventListener("click", function () {
    state.view = "strategy"; state.stratTab = state.stratTab || "okr";
    document.querySelectorAll(".views button").forEach(function (x) { x.classList.remove("active"); });
    renderCenter();
    if (!state.strategy) fetch("/api/strategy").then(function (r) { return r.json(); })
      .then(function (d) { state.strategy = d; if (state.view === "strategy") renderCenter(); });
  });
})();
