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

// ---------- X-matrix ----------
function renderXMatrix(X) {
  var annuals = X.annuals, bts = X.breakthroughs, kpis = X.kpis, inits = X.initiatives, corr = X.correlations;
  function has(pred) { return corr.some(pred); }
  var head = '<tr><th class="xcorner">X-matrix</th>' + annuals.map(function (a) { return '<th class="xtop" data-obj="' + esc(a.id) + '">' + esc(a.name) + "</th>"; }).join("") + "</tr>";
  var btRows = bts.map(function (b) {
    var cells = annuals.map(function (a) {
      var on = has(function (c) { return c.kind === "obj_obj" && c.row === b.id && c.col === a.id; });
      return '<td class="' + (on ? "xon" : "") + '">' + (on ? "●" : "") + "</td>";
    }).join("");
    return '<tr><th class="xleft" data-obj="' + esc(b.id) + '">' + esc(b.name) + "</th>" + cells + "</tr>";
  }).join("");
  var kpiRows = kpis.map(function (k) {
    var cells = annuals.map(function (a) {
      var on = has(function (c) { return c.kind === "obj_kpi" && c.col === a.id && c.kpi === k.id; });
      var cls = on ? (k.status === "off_target" ? "xon crit" : k.status === "on_target" ? "xon good" : "xon") : "";
      return '<td class="' + cls + '">' + (on ? (k.status === "off_target" ? "✗" : "●") : "") + "</td>";
    }).join("");
    return '<tr><th class="xkpi" data-kpi="' + esc(k.id) + '">' + esc(k.name) + ' <span class="muted">' + (k.value == null ? "" : k.value) + "/" + esc(String(k.target)) + "</span></th>" + cells + "</tr>";
  }).join("");
  var initRows = inits.map(function (it) {
    var cells = annuals.map(function (a) {
      var on = has(function (c) { return c.kind === "init_obj" && c.col === a.id && c.init === it.id; });
      return '<td class="' + (on ? "xon" : "") + '">' + (on ? "●" : "") + "</td>";
    }).join("");
    return '<tr><th class="xinit">' + esc(it.name) + "</th>" + cells + "</tr>";
  }).join("");
  return '<div class="xmatrix">' + entBanner(X.enterprise)
    + '<div class="okrhead">Hoshin X-matrix — breakthrough ▲, annual objectives ►, KPIs/results, and improvement initiatives, correlated. ✗ marks an off-target KPI.</div>'
    + '<div class="xwrap"><table class="xtable"><thead>' + head + "</thead><tbody>"
    + btRows + '<tr class="xsplit"><td colspan="' + (annuals.length + 1) + '">Key results (KPIs)</td></tr>' + kpiRows
    + '<tr class="xsplit"><td colspan="' + (annuals.length + 1) + '">Improvement initiatives</td></tr>' + initRows
    + "</tbody></table></div>" + gapsPanel(X.gaps) + "</div>";
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
function wireStrategy() {
  var c = document.getElementById("canvas"); if (!c) return;
  c.querySelectorAll("[data-stab]").forEach(function (b) {
    b.addEventListener("click", function () { state.stratTab = b.getAttribute("data-stab"); renderCenter(); });
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
