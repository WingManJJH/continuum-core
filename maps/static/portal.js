"use strict";
// Continuum publish portal — read-only shared viewer (Phase E).
// A self-contained, single-pass renderer: it reads /api/portal/view?token=... and
// draws the process (flow / lanes / RACI / checklist / details) or the landscape,
// with no authoring controls. Reuses the canvas node/table CSS classes so a shared
// view looks like the real model. Nothing here writes; it only fetches and draws.

function $(s) { return document.querySelector(s); }
function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) { return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]; }); }
function trunc(s, n) { s = String(s); return s.length > n ? s.slice(0, n - 1) + "…" : s; }
function shortRole(r) { return String(r).replace(/^role\./, "").replace(/^agent\./, ""); }
function lastSeg(r) { return String(r).split(".").pop(); }
function csv(a) { return (a || []).join(", "); }
function wrap(name, max) {
  var words = String(name).split(/\s+/), lines = [], cur = "";
  words.forEach(function (w) {
    if ((cur + " " + w).trim().length > max && cur) { lines.push(cur); cur = w; }
    else { cur = (cur + " " + w).trim(); }
  });
  if (cur) lines.push(cur);
  return lines.slice(0, 2);
}

var PAD = 26, R = 15, NW = 172, NH = 64, GAP = 66, GW = 46, VGAP = 34;
var DATA = null, VIEW = "flow", TOKEN = "";

// ---------- geometry helpers ----------
function rectBorder(cx, cy, hw, hh, tx, ty) {
  var dx = tx - cx, dy = ty - cy; if (!dx && !dy) return { x: cx, y: cy };
  var t = Infinity;
  if (dx) t = Math.min(t, hw / Math.abs(dx));
  if (dy) t = Math.min(t, hh / Math.abs(dy));
  return { x: cx + dx * t, y: cy + dy * t };
}
function circBorder(cx, cy, r, tx, ty) { var dx = tx - cx, dy = ty - cy, d = Math.hypot(dx, dy) || 1; return { x: cx + dx * r / d, y: cy + dy * r / d }; }
function border(n, tx, ty) {
  if (n.shape === "rect") return rectBorder(n.cx, n.cy, n.hw, n.hh, tx, ty);
  return circBorder(n.cx, n.cy, n.r, tx, ty);
}

// ---------- boot ----------
(function () {
  TOKEN = new URLSearchParams(location.search).get("token") || "";
  if (!TOKEN) return showError("No share link", "This page needs a share token in its URL (…/portal?token=…).");
  fetch("/api/portal/view?token=" + encodeURIComponent(TOKEN))
    .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
    .then(function (res) {
      if (!res.ok || !res.j.ok) return showError("Link unavailable", (res.j && res.j.error) || "This share link is unknown, revoked, or expired.");
      DATA = res.j.view;
      document.title = "Continuum · " + (DATA.meta.title || "Shared view");
      render();
    })
    .catch(function (e) { showError("Could not load", String(e)); });
})();

function showError(title, msg) {
  $("#root").innerHTML = '<div class="p-error"><h2>' + esc(title) + "</h2><p>" + esc(msg) + "</p></div>";
}

function render() {
  if (DATA.kind === "gone") return showError("Process removed", "The process this link pointed to has since been retired from the model.");
  if (DATA.kind === "landscape") return renderLandscapePage();
  renderProcessPage();
}

// ---------- shared header ----------
function metaBadge() {
  var m = DATA.meta;
  return m.current
    ? '<span class="p-badge current" title="The model has not changed since this link was shared.">up to date</span>'
    : '<span class="p-badge stale" title="The model has changed since this link was shared; you are seeing the current version.">model updated since shared</span>';
}
function fmtDate(iso) { try { return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" }); } catch (e) { return iso; } }

function header(titleExtra) {
  var m = DATA.meta;
  return '<div class="p-head"><h1>' + esc(m.title) + (titleExtra || "") + "</h1>"
    + '<div class="p-sub"><span>Shared ' + esc(fmtDate(m.published_at)) + " by " + esc(shortRole(m.published_by)) + "</span>"
    + metaBadge()
    + '<span class="p-copy"><button id="copyBtn" type="button">Copy link</button></span></div></div>';
}
function wireCopy() {
  var b = $("#copyBtn"); if (!b) return;
  b.addEventListener("click", function () {
    var url = location.href;
    var done = function () { b.textContent = "Copied ✓"; setTimeout(function () { b.textContent = "Copy link"; }, 1600); };
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(url).then(done, done);
    else done();
  });
}

// ================= process page =================
function renderProcessPage() {
  var p = DATA.process;
  var tabs = [["flow", "Flowchart"], ["lanes", "Lanes"], ["raci", "RACI"], ["checklist", "Checklist"], ["details", "Details"]];
  var html = header(' <span class="p-sub" style="font-weight:400">' + esc(p.id) + "</span>")
    + chipRow(p)
    + '<div class="p-tabs">' + tabs.map(function (t) {
        return '<button data-tab="' + t[0] + '"' + (t[0] === VIEW ? ' class="active"' : "") + ">" + t[1] + "</button>";
      }).join("") + "</div>"
    + '<div class="p-view" id="pview"></div>'
    + footer();
  $("#root").innerHTML = html;
  wireCopy();
  document.querySelectorAll(".p-tabs button").forEach(function (b) {
    b.addEventListener("click", function () {
      VIEW = b.getAttribute("data-tab");
      document.querySelectorAll(".p-tabs button").forEach(function (x) { x.classList.toggle("active", x === b); });
      drawView();
    });
  });
  drawView();
}

function chipRow(p) {
  var chips = [];
  chips.push('<span class="p-chip">owner <b>' + esc(shortRole(p.owner)) + "</b></span>");
  chips.push('<span class="p-chip">guardrail <b>' + esc(p.guardrail ? p.guardrail.replace(/^gr\./, "") : "none") + "</b></span>");
  chips.push('<span class="p-chip">steps <b>' + p.tasks.length + "</b></span>");
  var ai = p.tasks.filter(function (t) { return t.agents.length; }).length;
  if (ai) chips.push('<span class="p-chip">agent steps <b>' + ai + "</b></span>");
  if (p.kpis && p.kpis.length) chips.push('<span class="p-chip">KPIs <b>' + p.kpis.length + "</b></span>");
  if (p.risks && p.risks.length) chips.push('<span class="p-chip">risks <b>' + p.risks.length + "</b></span>");
  return '<div class="p-chips">' + chips.join("") + "</div>";
}

function drawView() {
  var host = $("#pview"), p = DATA.process;
  if (VIEW === "flow") host.innerHTML = flowSVG(p);
  else if (VIEW === "lanes") host.innerHTML = lanesHTML(p);
  else if (VIEW === "raci") host.innerHTML = raciHTML(p);
  else if (VIEW === "checklist") { host.innerHTML = checklistHTML(p); wireChecklist(); }
  else if (VIEW === "details") host.innerHTML = detailsHTML(p);
}

// ---------- flowchart (static single-pass SVG) ----------
function buildFlow(p) {
  var nodes = {}, edges = [];
  var explicit = p.explicit && p.flows && p.flows.length;
  var midY = PAD + NH / 2 + 120;
  var colStep = NW + GAP, rowStep = NH + VGAP;

  function taskNode(t) {
    return { id: t.id, kind: "task", task: t, shape: "rect", hw: NW / 2, hh: NH / 2 };
  }
  if (!explicit) {
    var seq = p.tasks.slice().sort(function (a, b) { return a.seq - b.seq; });
    var chain = [{ id: "__start__", kind: "start", shape: "circle", r: R }]
      .concat(seq.map(taskNode))
      .concat([{ id: "__end__", kind: "end", shape: "circle", r: R }]);
    chain.forEach(function (n, i) { n.cx = PAD + NW / 2 + i * colStep; n.cy = midY; nodes[n.id] = n; });
    for (var i = 0; i < chain.length - 1; i++) edges.push({ from: chain[i].id, to: chain[i + 1].id, condition: null });
    return { nodes: nodes, edges: edges };
  }

  // explicit graph: layered by longest path from __start__
  nodes["__start__"] = { id: "__start__", kind: "start", shape: "circle", r: R };
  nodes["__end__"] = { id: "__end__", kind: "end", shape: "circle", r: R };
  p.tasks.forEach(function (t) { nodes[t.id] = taskNode(t); });
  (p.gateways || []).forEach(function (gw) { nodes[gw.id] = { id: gw.id, kind: "gateway", gw: gw, shape: "circle", r: GW / 2 }; });
  edges = (p.flows || []).map(function (f) { return { from: f.from, to: f.to, condition: f.condition }; });
  // keep only edges whose endpoints exist
  edges = edges.filter(function (e) { return nodes[e.from] && nodes[e.to]; });

  var depth = {}; Object.keys(nodes).forEach(function (id) { depth[id] = 0; });
  depth["__start__"] = 0;
  for (var pass = 0; pass < Object.keys(nodes).length + 2; pass++) {
    edges.forEach(function (e) { if (depth[e.to] <= depth[e.from]) depth[e.to] = depth[e.from] + 1; });
  }
  // any node with no path stays at 0; push __end__ to the far right
  var maxd = 0; Object.keys(depth).forEach(function (id) { if (id !== "__end__") maxd = Math.max(maxd, depth[id]); });
  if (depth["__end__"] <= maxd) depth["__end__"] = maxd + 1;

  var cols = {};
  Object.keys(nodes).forEach(function (id) { (cols[depth[id]] = cols[depth[id]] || []).push(id); });
  Object.keys(cols).forEach(function (d) {
    cols[d].sort(function (a, b) {
      var na = nodes[a], nb = nodes[b];
      var ka = na.kind === "task" ? na.task.seq : (na.kind === "gateway" ? 500 : (na.kind === "start" ? -1 : 999));
      var kb = nb.kind === "task" ? nb.task.seq : (nb.kind === "gateway" ? 500 : (nb.kind === "start" ? -1 : 999));
      return ka - kb;
    });
    cols[d].forEach(function (id, r) {
      nodes[id].cx = PAD + NW / 2 + (+d) * colStep;
      nodes[id].cy = midY + (r - (cols[d].length - 1) / 2) * rowStep;
    });
  });
  return { nodes: nodes, edges: edges };
}

function flowSVG(p) {
  if (!p.tasks.length) return '<div class="muted" style="padding:24px">This process has no steps yet.</div>';
  var built = buildFlow(p), nodes = built.nodes, edges = built.edges;
  var uid = p.id.replace(/[^A-Za-z0-9]/g, "_");
  var parts = ['<svg xmlns="http://www.w3.org/2000/svg" class="flow-svg">'];
  parts.push('<defs><marker id="ah_' + uid + '" markerWidth="7" markerHeight="7" refX="6" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6 z" class="arrow"/></marker></defs>');
  var minX = 1e9, minY = 1e9, maxX = -1e9, maxY = -1e9;
  function ext(x, y) { minX = Math.min(minX, x); minY = Math.min(minY, y); maxX = Math.max(maxX, x); maxY = Math.max(maxY, y); }

  edges.forEach(function (e) {
    var A = nodes[e.from], B = nodes[e.to]; if (!A || !B) return;
    var p1 = border(A, B.cx, B.cy), p2 = border(B, A.cx, A.cy);
    parts.push('<line class="conn" x1="' + p1.x + '" y1="' + p1.y + '" x2="' + p2.x + '" y2="' + p2.y + '" marker-end="url(#ah_' + uid + ')"/>');
    if (e.condition) {
      var mx = (p1.x + p2.x) / 2, my = (p1.y + p2.y) / 2, tx = trunc(e.condition, 22), w = tx.length * 6.1 + 12;
      parts.push('<g class="flabel"><rect x="' + (mx - w / 2) + '" y="' + (my - 9) + '" width="' + w + '" height="17" rx="4"/><text x="' + mx + '" y="' + (my + 3) + '" text-anchor="middle">' + esc(tx) + "</text></g>");
    }
  });

  Object.keys(nodes).forEach(function (id) {
    var n = nodes[id];
    if (n.kind === "start" || n.kind === "end") {
      parts.push('<circle class="tip" cx="' + n.cx + '" cy="' + n.cy + '" r="' + R + '"/><text class="tip" x="' + n.cx + '" y="' + (n.cy + 3) + '" text-anchor="middle">' + n.kind + "</text>");
      ext(n.cx - R, n.cy - R); ext(n.cx + R, n.cy + R);
    } else if (n.kind === "gateway") {
      var c = GW / 2, x = n.cx - c, y = n.cy - c;
      parts.push('<g transform="translate(' + x + ',' + y + ')">');
      parts.push('<rect class="gw" x="7" y="7" width="' + (GW - 14) + '" height="' + (GW - 14) + '" transform="rotate(45 ' + c + " " + c + ')"/>');
      parts.push('<text class="gwglyph" x="' + c + '" y="' + (c + 6) + '" text-anchor="middle">' + (n.gw.type === "parallel" ? "+" : "×") + "</text>");
      if (n.gw.name) parts.push('<text class="gwname" x="' + c + '" y="' + (GW + 13) + '" text-anchor="middle">' + esc(trunc(n.gw.name, 16)) + "</text>");
      parts.push("</g>");
      ext(n.cx - c, n.cy - c); ext(n.cx + c, n.cy + c + 16);
    } else {
      var t = n.task, x2 = n.cx - NW / 2, y2 = n.cy - NH / 2;
      var ncls = "node" + (t.agents.length ? " agent" : "") + (t.override ? " override" : "");
      parts.push('<g transform="translate(' + x2 + ',' + y2 + ')">');
      parts.push('<rect class="' + ncls + '" x="0" y="0" width="' + NW + '" height="' + NH + '" rx="9"/>');
      parts.push('<text class="tseq" x="9" y="15">t' + t.seq + "</text>");
      if (t.agents.length) parts.push('<rect class="badge-bg" x="' + (NW - 26) + '" y="-7" width="24" height="15" rx="3.5"/><text class="badge" x="' + (NW - 14) + '" y="3.5" text-anchor="middle">AI</text>');
      if (t.subprocess) parts.push('<rect class="subbadge" x="' + (NW - 32) + '" y="' + (NH - 17) + '" width="30" height="14" rx="3"/><text class="subbadge" x="' + (NW - 17) + '" y="' + (NH - 7) + '" text-anchor="middle">SUB</text>');
      var lines = wrap(t.name, 22), sy = lines.length === 2 ? 24 : 31;
      lines.forEach(function (ln, k) { parts.push('<text class="tname" x="10" y="' + (sy + k * 14) + '">' + esc(ln) + "</text>"); });
      var who = t.agents.length ? (t.roles[0] ? lastSeg(t.roles[0]) + " + agent" : "agent") : (t.roles[0] ? lastSeg(t.roles[0]) : "");
      parts.push('<text class="tperf" x="10" y="' + (NH - 9) + '">' + esc(trunc(who, 24)) + "</text>");
      parts.push("</g>");
      ext(x2, y2); ext(x2 + NW, y2 + NH);
    }
  });
  parts.push("</svg>");
  var vx = minX - PAD, vy = minY - PAD, W = (maxX - minX) + 2 * PAD, H = (maxY - minY) + 2 * PAD;
  var svg = parts.join("").replace('class="flow-svg">',
    'class="flow-svg" viewBox="' + vx + " " + vy + " " + W + " " + H + '" width="' + W + '" height="' + H + '">');
  return svg;
}

// ---------- lanes (read-only swimlane strip) ----------
function laneOf(t) { return t.roles[0] || (t.agents.length ? "__agent__" : "__none__"); }
function laneLabel(id) { return id === "__agent__" ? "Automated (agent)" : id === "__none__" ? "Unassigned" : shortRole(id); }
function lanesHTML(p) {
  if (!p.tasks.length) return '<div class="muted" style="padding:24px">No steps to lay out yet.</div>';
  var order = [], seen = {};
  p.tasks.slice().sort(function (a, b) { return a.seq - b.seq; }).forEach(function (t) {
    var l = laneOf(t); if (!seen[l]) { seen[l] = []; order.push(l); } seen[l].push(t);
  });
  var rows = order.map(function (l) {
    var steps = seen[l].map(function (t) {
      return '<div class="rstep' + (t.agents.length ? " agent" : "") + '"><div class="rs-seq">t' + t.seq
        + (t.agents.length ? ' <span class="rs-ai">AI</span>' : "") + '</div><div class="rs-nm">' + esc(t.name) + "</div></div>";
    }).join("");
    return '<div class="rlane"><div class="rl-name">' + esc(laneLabel(l)) + '</div><div class="rl-steps">' + steps + "</div></div>";
  }).join("");
  return '<div class="muted" style="font-size:12px;margin-bottom:10px">Steps grouped by the role that performs them, in sequence order.</div>' + rows;
}

// ---------- RACI ----------
function raciHTML(p) {
  if (!p.tasks.length) return '<div class="muted" style="padding:24px">No steps to chart yet.</div>';
  var roles = [p.owner];
  p.tasks.forEach(function (t) {
    t.roles.forEach(function (r) { if (roles.indexOf(r) < 0) roles.push(r); });
    if (t.escalation_path && roles.indexOf(t.escalation_path) < 0) roles.push(t.escalation_path);
  });
  var seq = p.tasks.slice().sort(function (a, b) { return a.seq - b.seq; });
  var head = '<tr><th class="role">Role</th>' + seq.map(function (t) { return "<th>t" + t.seq + (t.agents.length ? " ᴬᴵ" : "") + "</th>"; }).join("") + "</tr>";
  var body = roles.map(function (r) {
    var cells = seq.map(function (t) {
      var parts = [];
      if (r === p.owner) parts.push('<span class="a">A</span>');
      if (t.roles.indexOf(r) >= 0) parts.push('<span class="r">R</span>');
      if (t.escalation_path === r) parts.push('<span class="c">C</span>');
      return "<td>" + parts.join(" ") + "</td>";
    }).join("");
    return '<tr><td class="role">' + esc(shortRole(r)) + "</td>" + cells + "</tr>";
  }).join("");
  return '<table class="raci"><thead>' + head + "</thead><tbody>" + body + "</tbody></table>"
    + '<div class="raci-legend"><b class="r" style="color:var(--accent)">R</b> responsible · '
    + '<b style="color:var(--crit)">A</b> accountable (process owner) · '
    + '<b style="color:var(--warn)">C</b> consulted on escalation · derived from the model</div>';
}

// ---------- checklist (viewer can tick along; stored per-link in their browser) ----------
function checklistHTML(p) {
  var seq = p.tasks.slice().sort(function (a, b) { return a.seq - b.seq; });
  return '<ul class="chklist">' + seq.map(function (t) {
    var key = "cc-portal-" + TOKEN + "-" + t.id, done = false;
    try { done = localStorage.getItem(key) === "1"; } catch (e) {}
    var who = t.roles.map(shortRole).join(", ") + (t.agents.length ? " + agent" : "");
    var gr = t.guardrail_full ? ("allow: " + csv(t.allow) + (t.escalate_if ? " · escalate if " + t.escalate_if : "")) : "no guardrail";
    return '<li class="' + (done ? "done" : "") + '" data-t="' + esc(t.id) + '">'
      + '<input type="checkbox" ' + (done ? "checked" : "") + ">"
      + '<div><div class="cnm">t' + t.seq + " · " + esc(t.name) + "</div>"
      + '<div class="cmeta">' + esc(who) + "</div>"
      + '<div class="cgr">' + esc(gr) + "</div></div></li>";
  }).join("") + "</ul>";
}
function wireChecklist() {
  var host = $("#pview");
  host.addEventListener("change", function (e) {
    var li = e.target.closest("li[data-t]"); if (!li) return;
    try { localStorage.setItem("cc-portal-" + TOKEN + "-" + li.getAttribute("data-t"), e.target.checked ? "1" : "0"); } catch (err) {}
    li.classList.toggle("done", e.target.checked);
  });
}

// ---------- details (guardrails + refs, read-only) ----------
function detailsHTML(p) {
  var seq = p.tasks.slice().sort(function (a, b) { return a.seq - b.seq; });
  var rows = seq.map(function (t) {
    var who = t.roles.map(shortRole).join(", ") + (t.agents.length ? (t.roles.length ? " + agent" : "agent") : "");
    var gr = t.guardrail_full
      ? '<div class="mono">allow: ' + esc(csv(t.allow) || "—") + "</div>"
        + '<div class="mono">deny: ' + esc(csv(t.deny) || "—") + "</div>"
        + (t.escalate_if ? '<div class="mono">escalate if ' + esc(t.escalate_if) + " → " + esc(shortRole(t.escalation_path || "")) + "</div>" : "")
      : '<span class="muted">no guardrail</span>';
    return "<tr><td>t" + t.seq + "</td><td>" + esc(t.name) + (t.subprocess ? ' <span class="p-chip">→ ' + esc(t.subprocess) + "</span>" : "")
      + "</td><td>" + esc(who || "—") + "</td><td>" + gr + "</td></tr>";
  }).join("");
  var risks = (p.risks || []).map(function (r) { return '<li><b>' + esc(r.id) + "</b> — " + esc(r.risk) + "</li>"; }).join("");
  var kpis = (p.kpis || []).map(function (k) { return '<span class="p-chip">' + esc(k) + "</span>"; }).join("");
  return '<table class="dtable"><thead><tr><th>Step</th><th>Name</th><th>Performed by</th><th>Guardrail</th></tr></thead><tbody>'
    + rows + "</tbody></table>"
    + (kpis ? '<h3 style="font-size:14px;margin:18px 0 6px">KPIs</h3><div class="p-chips">' + kpis + "</div>" : "")
    + (risks ? '<h3 style="font-size:14px;margin:18px 0 6px">Linked risks</h3><ul style="font-size:13px;line-height:1.6">' + risks + "</ul>" : "");
}

// ================= landscape page =================
function renderLandscapePage() {
  var L = DATA.landscape;
  var house = L.domains.map(function (d) {
    var cards = d.processes.map(function (p) {
      var ai = p.agent_steps ? p.agent_steps + " AI · " : "";
      return '<div class="pcard">'
        + '<div class="pcid">' + esc(p.id) + "</div>"
        + '<div class="pcname">' + esc(p.name) + "</div>"
        + '<div class="pcmeta">' + p.steps + " steps · " + ai + "owner " + esc(shortRole(p.owner)) + "</div>"
        + '<div class="pcbadges"><span class="gdot ' + (p.reviewed ? "good" : "warn") + '"></span>'
        + (p.reviewed ? "reviewed guardrail" : "default guardrail")
        + (p.risks ? ' · <span class="rtag">' + p.risks + " risk</span>" : "")
        + (p.kpis ? " · " + p.kpis + " KPI" : "") + "</div></div>";
    }).join("");
    return '<section class="domain"><h3><span class="dcode">' + esc(d.code) + "</span> " + esc(d.name)
      + ' <span class="dcount">' + d.processes.length + '</span></h3><div class="pcards">' + cards + "</div></section>";
  }).join("");
  var C = L.catalogs;
  function chips(ids) { return ids.map(function (id) { return '<span class="pchip">' + esc(id) + "</span>"; }).join(""); }
  function col(title, rows) { return '<div class="catcol"><h4>' + title + "</h4>" + rows + "</div>"; }
  var roleRows = C.roles.map(function (r) { return '<div class="catrow"><div class="catmain"><span class="catname">' + esc(r.name) + '</span><span class="catcount">' + r.count + '</span></div><div class="catprocs">' + chips(r.processes) + "</div></div>"; }).join("");
  var kpiRows = C.kpis.map(function (k) { return '<div class="catrow"><div class="catmain"><span class="catname">' + esc(k.name) + '</span><span class="catcount">' + k.count + '</span></div><div class="catprocs">' + chips(k.processes) + "</div></div>"; }).join("");
  var riskRows = C.risks.map(function (x) { return '<div class="catrow"><div class="catmain"><span class="catname" title="' + esc(x.risk) + '">' + esc(x.id) + '</span></div><div class="catprocs">' + chips([x.process]) + "</div></div>"; }).join("");
  $("#root").innerHTML = header("")
    + '<div class="landscape"><div class="lshead">Process landscape — <b>' + L.processes_total + "</b> processes across <b>" + L.domains.length + "</b> APQC domains.</div>"
    + '<div class="house">' + house + "</div>"
    + '<div class="catalogs"><div class="catshead">Catalogs — what threads across the org</div><div class="catgrid">'
    + col("Roles (" + C.roles.length + ")", roleRows) + col("KPIs (" + C.kpis.length + ")", kpiRows) + col("Risks (" + C.risks.length + ")", riskRows)
    + "</div></div></div>" + footer();
  wireCopy();
}

function footer() {
  return '<div class="p-foot">This is a <b>read-only shared view</b> of a governed process model, published with '
    + '<b>Continuum</b>. It always reflects the current model. The link is an unguessable capability URL — anyone who has it can view this; it can be revoked by its author.</div>';
}
