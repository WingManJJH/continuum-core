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
  return '<div class="kpirow" style="margin-left:' + ((depth || 0) * 16) + 'px">' + kpiStat(k) + "</div>" + kids;
}

function objCard(o) {
  var procs = (o.processes || []).map(function (p) { return '<a class="pchip" data-open="' + esc(p.id) + '">' + esc(p.id) + "</a>"; }).join("");
  var badge = o.type === "breakthrough" ? '<span class="obadge bt">breakthrough</span>' : '<span class="obadge an">annual</span>';
  var dot = o.fulfilled ? '<span class="gdot good"></span>' : '<span class="gdot ' + (o.off_target_kpis.length ? "warn" : "muted") + '"></span>';
  return '<div class="ocard" data-obj="' + esc(o.id) + '">'
    + '<div class="ohead">' + dot + badge + '<span class="oname">' + esc(o.name) + "</span>"
    + (o.owner ? '<span class="oowner">' + esc(shortRole(o.owner)) + "</span>" : "") + "</div>"
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
  return '<div class="entbanner"><div class="entname">' + esc(e.name) + "</div>"
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
function xGrid(rows, cols, type, abFn, L) {
  var cells = "";
  for (var r = 0; r < rows.length; r++) for (var c = 0; c < cols.length; c++) {
    var ab = abFn(rows[r], cols[c]);
    cells += xCell(L, type, ab[0], ab[1]);
  }
  return '<div class="agrid" style="grid-template-columns:repeat(' + (cols.length || 1) + ',1fr)">' + cells + "</div>";
}
function renderXMatrix(X) {
  var O = X.objectives, G = X.goals, I = X.initiatives, M = X.metrics, W = X.owners, L = X.links;
  var initList = I.map(function (it) { return '<div class="nxitem nx-init">' + esc(it.name) + "</div>"; }).join("");
  var objList = O.map(function (o) { return '<div class="nxitem nx-obj" data-obj="' + esc(o.id) + '">' + esc(o.name) + "</div>"; }).join("");
  var metList = M.map(function (m) {
    var cls = m.status === "on_target" ? "good" : m.status === "off_target" ? "crit" : "";
    return '<div class="nxitem nx-met ' + cls + '" data-kpi="' + esc(m.id) + '">' + esc(m.name)
      + '<span class="nxval">' + (m.value == null ? "—" : esc(String(m.value))) + "/" + esc(String(m.target)) + (m.status === "off_target" ? " ✗" : m.status === "on_target" ? " ✓" : "") + "</span></div>";
  }).join("");
  var ownList = W.map(function (o) { return '<div class="nxitem nx-own">' + esc(o.name) + "</div>"; }).join("");
  var goalList = G.map(function (g) { return '<div class="nxitem nx-goal" data-obj="' + esc(g.id) + '">' + esc(g.name) + "</div>"; }).join("");

  var A = xGrid(I, O, "init_obj", function (it, o) { return [it.id, o.id]; }, L);       // init ↔ obj
  var C = xGrid(I, M, "init_metric", function (it, m) { return [it.id, m.id]; }, L);    // init ↔ metric
  var D = xGrid(I, W, "init_owner", function (it, w) { return [it.id, w.id]; }, L);     // init ↔ owner
  var Icorner = xGrid(G, O, "obj_goal", function (g, o) { return [o.id, g.id]; }, L);   // obj ↔ goal

  var grid = '<div class="nexus"><div class="nexus-grid">'
    + '<div class="nq tl"><span class="clab">A · init × objective</span>' + A + "</div>"
    + '<div class="nq initiatives"><div class="qlab">▲ Change initiatives</div>' + initList + "</div>"
    + '<div class="nq tr"><span class="clab">C · init × metric</span>' + C + "</div>"
    + '<div class="nq tr2"><span class="clab">D · init × owner</span>' + D + "</div>"
    + '<div class="nq objectives"><div class="qlab vert">◄ Objectives</div><div class="qitems">' + objList + "</div></div>"
    + '<div class="nq center"><div class="xcross"><span>X</span></div></div>'
    + '<div class="nq metrics"><div class="qlab vert">Metrics ►</div><div class="qitems">' + metList + "</div></div>"
    + '<div class="nq owners"><div class="qlab vert">Owners</div><div class="qitems">' + ownList + "</div></div>"
    + '<div class="nq bl"><span class="clab">I · objective × goal</span>' + Icorner + "</div>"
    + '<div class="nq goals"><div class="qlab">▼ Organizational goals</div>' + goalList + "</div>"
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
  // click an objective anywhere -> highlight it + its processes across the view
  c.querySelectorAll("[data-obj]").forEach(function (el) {
    el.addEventListener("click", function (e) {
      if (e.target.closest("[data-open]")) return;
      var id = el.getAttribute("data-obj");
      c.querySelectorAll("[data-obj]").forEach(function (x) { x.classList.toggle("objsel", x.getAttribute("data-obj") === id); });
    });
  });
}
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
