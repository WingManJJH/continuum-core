"use strict";
var $ = function (s) { return document.querySelector(s); };
function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) { return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]; }); }
function trunc(s, n) { s = String(s); return s.length > n ? s.slice(0, n - 1) + "…" : s; }
function shortRole(r) { return String(r).replace(/^role\./, "").replace(/^agent\./, ""); }
function lastSeg(r) { return String(r).split(".").pop(); }
function csv(a) { return (a || []).join(", "); }
function parseCsv(s) { return s.split(",").map(function (x) { return x.trim(); }).filter(Boolean); }

var state = { procs: [], sel: null, task: null, view: "flow" };

function getProc() { return state.procs.find(function (p) { return p.id === state.sel; }); }
function getTask() { var p = getProc(); return p && state.task ? p.tasks.find(function (t) { return t.id === state.task; }) : null; }
function taskById(id) { var p = getProc(); return p ? p.tasks.find(function (t) { return t.id === id; }) : null; }
// update selection highlight IN PLACE (re-rendering would kill a pending dblclick)
function markSel() {
  var svg = $("#canvas svg"); if (!svg) return;
  svg.querySelectorAll("g.tnode").forEach(function (g) { var r = g.querySelector("rect.node"); if (r) r.classList.toggle("selrect", g.getAttribute("data-task") === state.task); });
  svg.querySelectorAll("g.gwnode").forEach(function (g) { var r = g.querySelector("rect.gw"); if (r) r.classList.toggle("selrect", g.getAttribute("data-node") === state.gwsel); });
  svg.querySelectorAll("g.evnode").forEach(function (g) { var c = g.querySelector("circle.ev"); if (c) c.classList.toggle("selrect", g.getAttribute("data-node") === state.evsel); });
}
// drill-down "SUB" badge (local node coords) — a step that expands into another process
function subBadge(t) {
  return t.subprocess ? '<rect class="subbadge" x="' + (NW - 32) + '" y="' + (NH - 17) + '" width="30" height="14" rx="3"/><text class="subbadge" x="' + (NW - 17) + '" y="' + (NH - 7) + '" text-anchor="middle">SUB</text>' : "";
}

// ---------- load ----------
function load() {
  return Promise.all([
    fetch("/api/maps").then(function (r) { return r.json(); }),
    loadRoles(true),   // role master data — so role names + click-through are ready to render
  ]).then(function (res) {
    var d = res[0];
    state.procs = d.processes;
    state.landscape = null;  // model changed — refetch the house next time it's opened
    if (!state.sel && state.procs.length) state.sel = state.procs[0].id;
    renderNav();
    renderTitle();
    renderCenter();
    renderProps();
  });
}
load().catch(function (e) { $("#canvas").innerHTML = '<div class="muted">failed to load: ' + esc(e) + "</div>"; });

function renderNav() {
  $("#proc-list").innerHTML = state.procs.map(function (p) {
    return '<li data-p="' + esc(p.id) + '" class="' + (p.id === state.sel ? "active" : "") + '">'
      + '<div class="pid">' + esc(p.id) + '</div><div class="pnm">' + esc(p.name) + "</div></li>";
  }).join("");
}
$("#proc-list").addEventListener("click", function (e) {
  var li = e.target.closest("li[data-p]"); if (!li) return;
  state.sel = li.getAttribute("data-p"); state.task = null; state.gwsel = null; state.nav = [];
  renderNav(); renderTitle(); renderCenter(); renderProps();
});

function renderTitle() {
  var p = getProc(); if (!p) return;
  $("#proc-title").innerHTML = '<span class="pid">' + esc(p.id) + "</span> " + esc(p.name);
}

// ---------- view switch ----------
document.querySelectorAll(".views button").forEach(function (b) {
  b.addEventListener("click", function () {
    state.view = b.getAttribute("data-view");
    document.querySelectorAll(".views button").forEach(function (x) { x.classList.toggle("active", x === b); });
    renderCenter();
  });
});

function toggleProcTools(hide) {
  ["add-step", "tidy", "enable-branch", "connect"].forEach(function (id) { var b = document.getElementById(id); if (b) b.style.display = hide ? "none" : ""; });
}
function renderCenter() {
  var landB = document.getElementById("landscape-btn"); if (landB) landB.classList.toggle("active", state.view === "landscape");
  toggleProcTools(state.view === "landscape");
  if (state.view === "landscape") {
    renderCrumbs();
    $("#canvas").innerHTML = state.landscape ? renderLandscape(state.landscape) : '<div class="muted" style="padding:24px">loading…</div>';
    wireLandscape();
    return;
  }
  var p = getProc(); if (!p) return;
  renderCrumbs();
  if (state.view === "raci") $("#canvas").innerHTML = renderRaci(p);
  else if (state.view === "checklist") $("#canvas").innerHTML = renderChecklist(p);
  else if (state.view === "lanes") { $("#canvas").innerHTML = renderLanes(p); wireLanes(p); }
  else if (p.explicit) { $("#canvas").innerHTML = renderGraph(p); wireGraph(p); }
  else { $("#canvas").innerHTML = renderLinear(p); if (p.tasks.length) wireFlow(p); }
  syncFlowBar(p);
}
// --- sub-process drill-down breadcrumb ---
function renderCrumbs() {
  var c = $("#crumbs"); if (!c) return;
  if (!state.nav || !state.nav.length) { c.hidden = true; c.innerHTML = ""; return; }
  c.hidden = false;
  var trail = state.nav.concat([state.sel]);
  c.innerHTML = trail.map(function (id, i) {
    var pr = state.procs.find(function (x) { return x.id === id; });
    var nm = pr ? pr.name : id;
    return (i ? '<span class="csep">›</span>' : "") + (i < trail.length - 1
      ? '<a class="crumb" data-i="' + i + '">' + esc(nm) + "</a>"
      : '<span class="crumb cur">' + esc(nm) + "</span>");
  }).join("");
}
function drillInto(pid) {
  if (!state.procs.find(function (x) { return x.id === pid; })) return;
  state.nav = (state.nav || []).concat([state.sel]);
  state.sel = pid; state.task = null; state.gwsel = null;
  renderNav(); renderTitle(); renderCenter(); renderProps();
}
$("#crumbs").addEventListener("click", function (e) {
  var a = e.target.closest("a.crumb[data-i]"); if (!a) return;
  var i = +a.getAttribute("data-i");
  var trail = state.nav.concat([state.sel]);
  state.nav = trail.slice(0, i);
  state.sel = trail[i]; state.task = null; state.gwsel = null;
  renderNav(); renderTitle(); renderCenter(); renderProps();
});
// show "Enable branching" only for a linear process with steps; "Connect" only in explicit mode
function syncFlowBar(p) {
  var eb = document.getElementById("enable-branch"), cn = document.getElementById("connect");
  if (eb) eb.hidden = !(state.view === "flow" && !p.explicit && p.tasks.length);
  if (cn) { cn.hidden = !(state.view === "flow" && p.explicit); if (cn.hidden) setConnect(false); }
}

// ---------- flowchart (free-form, draggable SVG) ----------
var PAD = 24, R = 15, NW = 172, NH = 64, GAP = 58, LANE = 26, AY = 44;
function wrap(name, max) {
  var words = String(name).split(" "), lines = [], cur = "";
  for (var i = 0; i < words.length; i++) { var t = cur ? cur + " " + words[i] : words[i]; if (t.length > max && cur) { lines.push(cur); cur = words[i]; } else { cur = t; } }
  if (cur) lines.push(cur);
  if (lines.length > 2) lines = [lines[0], trunc(lines.slice(1).join(" "), max)];
  return lines.slice(0, 2);
}
function renderEmptyFlow(m) {
  var uid = m.id.replace(/[^A-Za-z0-9]/g, "_"), cy = LANE + NH / 2;
  var sx = PAD + R, ex = sx + 200, W = ex + R + PAD, H = LANE + NH + 18;
  return '<svg viewBox="0 0 ' + W + ' ' + H + '" width="' + W + '" height="' + H + '" xmlns="http://www.w3.org/2000/svg">'
    + '<defs><marker id="ah_' + uid + '" markerWidth="7" markerHeight="7" refX="6" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6 z" class="arrow"/></marker></defs>'
    + '<circle class="tip" cx="' + sx + '" cy="' + cy + '" r="' + R + '"/><text class="tip" x="' + sx + '" y="' + (cy + 3) + '" text-anchor="middle">start</text>'
    + '<line class="conn" x1="' + (sx + R) + '" y1="' + cy + '" x2="' + (ex - R) + '" y2="' + cy + '" marker-end="url(#ah_' + uid + ')"/>'
    + '<text class="hintmsg" x="' + ((sx + ex) / 2) + '" y="' + (cy - 12) + '" text-anchor="middle">drag a step here</text>'
    + '<circle class="tip" cx="' + ex + '" cy="' + cy + '" r="' + R + '"/><text class="tip" x="' + ex + '" y="' + (cy + 3) + '" text-anchor="middle">end</text></svg>';
}
// resolve each task's position: saved layout, else an auto left-to-right flow
function nodePos(m) {
  var lay = m.layout || {}, pos = {};
  m.tasks.forEach(function (t, i) {
    var s = lay[t.id];
    pos[t.id] = (s && isFinite(s.x) && isFinite(s.y))
      ? { x: +s.x, y: +s.y } : { x: 70 + i * (NW + GAP), y: AY };
  });
  return pos;
}
function ctr(pt) { return { x: pt.x + NW / 2, y: pt.y + NH / 2 }; }
// border point of a rect (half-width hw, hh) in the direction of (tx,ty)
function edgePt(cx, cy, hw, hh, tx, ty) {
  var dx = tx - cx, dy = ty - cy; if (!dx && !dy) return { x: cx, y: cy };
  var t = Infinity;
  if (dx) t = Math.min(t, hw / Math.abs(dx));
  if (dy) t = Math.min(t, hh / Math.abs(dy));
  return { x: cx + dx * t, y: cy + dy * t };
}
function circPt(cx, cy, r, tx, ty) { var dx = tx - cx, dy = ty - cy, d = Math.hypot(dx, dy) || 1; return { x: cx + dx * r / d, y: cy + dy * r / d }; }

function renderLinear(m) {
  var uid = m.id.replace(/[^A-Za-z0-9]/g, "_"), tasks = m.tasks;
  if (!tasks.length) return renderEmptyFlow(m);
  var pos = nodePos(m); state.flowPos = pos;
  var p = ['<svg xmlns="http://www.w3.org/2000/svg">'];  // viewBox/size set by updateGeom
  p.push('<defs><marker id="ah_' + uid + '" markerWidth="7" markerHeight="7" refX="6" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6 z" class="arrow"/></marker>'
    + '<marker id="eh_' + uid + '" markerWidth="7" markerHeight="7" refX="3" refY="6" orient="auto"><path d="M0,0 L6,0 L3,6 z" class="esc-arrow"/></marker></defs>');
  // sequence connectors — endpoints filled in live by updateGeom
  var chain = ["start"].concat(tasks.map(function (t) { return t.id; })).concat(["end"]);
  for (var i = 0; i < chain.length - 1; i++) {
    p.push('<line class="conn" data-a="' + esc(chain[i]) + '" data-b="' + esc(chain[i + 1]) + '" marker-end="url(#ah_' + uid + ')"/>');
  }
  p.push('<g id="tip-start"><circle class="tip" r="' + R + '"/><text class="tip" y="3" text-anchor="middle">start</text></g>');
  p.push('<g id="tip-end"><circle class="tip" r="' + R + '"/><text class="tip" y="3" text-anchor="middle">end</text></g>');
  tasks.forEach(function (t) {
    var ncls = "node" + (t.agents.length ? " agent" : "") + (t.override ? " override" : "");
    p.push('<g class="tnode' + (t.id === state.task ? " sel" : "") + '" data-task="' + esc(t.id) + '" transform="translate(' + pos[t.id].x + ',' + pos[t.id].y + ')">');
    p.push('<rect class="' + ncls + '" x="0" y="0" width="' + NW + '" height="' + NH + '" rx="9"/>');
    p.push('<text class="tseq" x="9" y="15">t' + t.seq + '</text>');
    if (t.agents.length) { p.push('<rect class="badge-bg" x="' + (NW - 26) + '" y="-7" width="24" height="15" rx="3.5"/><text class="badge" x="' + (NW - 14) + '" y="3.5" text-anchor="middle">AI</text>'); }
    if (t.override) p.push('<text class="tag" x="' + (NW - 6) + '" y="-4" text-anchor="end">override</text>');
    var lines = wrap(t.name, 22), sy = lines.length === 2 ? 24 : 31;
    lines.forEach(function (ln, k) { p.push('<text class="tname" x="10" y="' + (sy + k * 14) + '">' + esc(ln) + "</text>"); });
    var who = t.agents.length ? ((t.roles[0] ? lastSeg(t.roles[0]) + " + agent" : "agent")) : (t.roles[0] ? lastSeg(t.roles[0]) : "");
    var rAttr = t.roles[0] ? ' class="tperf rolelink-svg" data-role="' + esc(t.roles[0]) + '"' : ' class="tperf"';
    p.push('<text' + rAttr + ' x="10" y="' + (NH - 9) + '">' + esc(trunc(who, 24)) + "</text>" + subBadge(t));
    if (t.agents.length && t.escalate_if) {  // escalation branch travels with the node
      var bx = NW / 2, by = NH + 26, pw = 172, pxx = bx - pw / 2;
      p.push('<line class="esc-line" x1="' + bx + '" y1="' + NH + '" x2="' + bx + '" y2="' + by + '" marker-end="url(#eh_' + uid + ')"/>');
      p.push('<rect class="esc" x="' + pxx + '" y="' + by + '" width="' + pw + '" height="34" rx="7"/>');
      p.push('<text class="esc" x="' + (pxx + 10) + '" y="' + (by + 14) + '">escalate → ' + esc(shortRole(t.escalation_path || "")) + "</text>");
      p.push('<text class="esc-cond" x="' + (pxx + 10) + '" y="' + (by + 27) + '">if ' + esc(trunc(t.escalate_if, 26)) + "</text>");
    }
    p.push("</g>");
  });
  p.push("</svg>");
  return p.join("");
}

// recompute every connector + tip + the viewBox from the current node positions
function updateGeom(m) {
  var svg = $("#canvas svg"); if (!svg) return;
  var pos = state.flowPos, tasks = m.tasks; if (!tasks.length) return;
  var first = tasks[0].id, last = tasks[tasks.length - 1].id;
  var startP = { x: pos[first].x - GAP, y: pos[first].y + NH / 2 };
  var endP = { x: pos[last].x + NW + GAP, y: pos[last].y + NH / 2 };
  var ts = svg.querySelector("#tip-start"), te = svg.querySelector("#tip-end");
  if (ts) ts.setAttribute("transform", "translate(" + startP.x + "," + startP.y + ")");
  if (te) te.setAttribute("transform", "translate(" + endP.x + "," + endP.y + ")");
  svg.querySelectorAll("line.conn").forEach(function (ln) {
    var a = ln.getAttribute("data-a"), b = ln.getAttribute("data-b");
    var A = a === "start" ? startP : ctr(pos[a]);
    var B = b === "end" ? endP : ctr(pos[b]);
    var p1 = a === "start" ? circPt(A.x, A.y, R, B.x, B.y) : edgePt(A.x, A.y, NW / 2, NH / 2, B.x, B.y);
    var p2 = b === "end" ? circPt(B.x, B.y, R, A.x, A.y) : edgePt(B.x, B.y, NW / 2, NH / 2, A.x, A.y);
    ln.setAttribute("x1", p1.x); ln.setAttribute("y1", p1.y); ln.setAttribute("x2", p2.x); ln.setAttribute("y2", p2.y);
  });
  var minX = 1e9, minY = 1e9, maxX = -1e9, maxY = -1e9;
  tasks.forEach(function (t) {
    var pp = pos[t.id];
    minX = Math.min(minX, pp.x); minY = Math.min(minY, pp.y);
    maxX = Math.max(maxX, pp.x + NW);
    maxY = Math.max(maxY, pp.y + NH + (t.agents.length && t.escalate_if ? 62 : 0));
  });
  minX = Math.min(minX, startP.x - R); maxX = Math.max(maxX, endP.x + R);
  minY = Math.min(minY, startP.y - R); maxY = Math.max(maxY, endP.y + R);
  var vx = minX - PAD, vy = minY - PAD, W = (maxX - minX) + 2 * PAD, H = (maxY - minY) + 2 * PAD;
  svg.setAttribute("viewBox", vx + " " + vy + " " + W + " " + H);
  svg.setAttribute("width", W); svg.setAttribute("height", H);
}

// drag a node to reposition it (decorative only — never reorders the process)
function wireFlow(m) {
  var svg = $("#canvas svg"); if (!svg) return;
  state.flowPos = nodePos(m);
  updateGeom(m);
  var drag = null;
  svg.querySelectorAll("g.tnode").forEach(function (g) {
    var tid = g.getAttribute("data-task");
    g.addEventListener("pointerdown", function (e) {
      if (e.button !== 0) return;
      drag = { sx: e.clientX, sy: e.clientY, ox: state.flowPos[tid].x, oy: state.flowPos[tid].y, moved: false };
      g.setPointerCapture(e.pointerId); g.classList.add("dragging"); e.preventDefault();
    });
    g.addEventListener("pointermove", function (e) {
      if (!drag) return;
      var dx = e.clientX - drag.sx, dy = e.clientY - drag.sy;
      if (Math.abs(dx) > 3 || Math.abs(dy) > 3) drag.moved = true;
      var nx = Math.max(0, drag.ox + dx), ny = Math.max(0, drag.oy + dy);
      state.flowPos[tid] = { x: nx, y: ny };
      g.setAttribute("transform", "translate(" + nx + "," + ny + ")");
      updateGeom(m);
    });
    g.addEventListener("pointerup", function (e) {
      if (!drag) return;
      try { g.releasePointerCapture(e.pointerId); } catch (err) {}
      g.classList.remove("dragging");
      var moved = drag.moved; drag = null;
      if (moved) saveLayout(m);
      else { state.task = tid; state.gwsel = null; markSel(); renderProps(); }
    });
    g.addEventListener("dblclick", function () { var t = taskById(tid); if (t && t.subprocess) drillInto(t.subprocess); });
  });
}
function saveLayout(m) {
  getProc().layout = JSON.parse(JSON.stringify(state.flowPos));  // keep across re-renders
  fetch("/api/layout", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ process: m.id, positions: state.flowPos }) })
    .then(function (r) { return r.json(); }).catch(function () {});
}
var tidyBtn = document.getElementById("tidy");
if (tidyBtn) tidyBtn.addEventListener("click", function () {
  var p = getProc(); if (!p) return;
  fetch("/api/layout", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ op: "reset", process: p.id }) })
    .then(function (r) { return r.json(); }).then(function () { load(); });
});

// ================= Phase B: explicit flow graph (gateways + drawn flows) =========
var GW = 46;  // gateway diamond size
var EV = 38;  // event circle size
function gwset(m) { var s = {}; (m.gateways || []).forEach(function (g) { s[g.id] = g; }); return s; }
function evset(m) { var s = {}; (m.events || []).forEach(function (e) { s[e.id] = e; }); return s; }
function nodePosGraph(m) {
  var lay = m.layout || {}, pos = {}, sv = gwset(m), rx = 120;
  m.tasks.forEach(function (t, i) { var s = lay[t.id]; pos[t.id] = (s && isFinite(s.x) && isFinite(s.y)) ? { x: +s.x, y: +s.y } : { x: 130 + i * (NW + GAP), y: AY }; });
  (m.gateways || []).forEach(function (g, i) { var s = lay[g.id]; pos[g.id] = (s && isFinite(s.x) && isFinite(s.y)) ? { x: +s.x, y: +s.y } : { x: 130 + m.tasks.length * (NW + GAP), y: AY + i * (GW + 34) }; });
  (m.events || []).forEach(function (ev, i) { var s = lay[ev.id]; pos[ev.id] = (s && isFinite(s.x) && isFinite(s.y)) ? { x: +s.x, y: +s.y } : { x: 60 + m.tasks.length * (NW + GAP), y: AY + ((m.gateways || []).length + i) * (EV + 40) }; });
  m.tasks.forEach(function (t) { rx = Math.max(rx, pos[t.id].x + NW); });
  Object.keys(sv).forEach(function (id) { rx = Math.max(rx, pos[id].x + GW); });
  (m.events || []).forEach(function (ev) { rx = Math.max(rx, pos[ev.id].x + EV); });
  var s0 = lay["__start__"], s1 = lay["__end__"];
  pos["__start__"] = (s0 && isFinite(s0.x)) ? { x: +s0.x, y: +s0.y } : { x: 20, y: AY + NH / 2 - R };
  pos["__end__"] = (s1 && isFinite(s1.x)) ? { x: +s1.x, y: +s1.y } : { x: rx + 60, y: AY + NH / 2 - R };
  return pos;
}
function nodeGeo(m, id) {
  var pos = state.flowPos[id]; if (!pos) return null;
  if (id === "__start__" || id === "__end__") return { cx: pos.x + R, cy: pos.y + R, hw: R, hh: R, circle: true };
  if (state.ev && state.ev[id]) return { cx: pos.x + EV / 2, cy: pos.y + EV / 2, hw: EV / 2, hh: EV / 2, circle: true };
  if (state.gw && state.gw[id]) return { cx: pos.x + GW / 2, cy: pos.y + GW / 2, hw: GW / 2, hh: GW / 2 };
  return { cx: pos.x + NW / 2, cy: pos.y + NH / 2, hw: NW / 2, hh: NH / 2 };
}
function renderGraph(m) {
  var uid = m.id.replace(/[^A-Za-z0-9]/g, "_");
  state.flowPos = nodePosGraph(m); state.gw = gwset(m); state.ev = evset(m);
  var p = ['<svg xmlns="http://www.w3.org/2000/svg">'];
  p.push('<defs><marker id="ah_' + uid + '" markerWidth="7" markerHeight="7" refX="6" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6 z" class="arrow"/></marker></defs>');
  (m.flows || []).forEach(function (f) {
    p.push('<line class="conn flow" data-flow="' + esc(f.id) + '" data-a="' + esc(f.from) + '" data-b="' + esc(f.to) + '" marker-end="url(#ah_' + uid + ')"/>');
    if (f.condition) {
      p.push('<g class="flabel" data-flow="' + esc(f.id) + '"><rect rx="4"/><text>' + esc(trunc(f.condition, 22)) + "</text></g>");
    }
  });
  p.push('<g class="tip-node" data-node="__start__"><circle class="tip" cx="' + R + '" cy="' + R + '" r="' + R + '"/><text class="tip" x="' + R + '" y="' + (R + 3) + '" text-anchor="middle">start</text></g>');
  p.push('<g class="tip-node" data-node="__end__"><circle class="tip" cx="' + R + '" cy="' + R + '" r="' + R + '"/><text class="tip" x="' + R + '" y="' + (R + 3) + '" text-anchor="middle">end</text></g>');
  m.tasks.forEach(function (t) {
    var x = state.flowPos[t.id].x, y = state.flowPos[t.id].y;
    var ncls = "node" + (t.agents.length ? " agent" : "") + (t.override ? " override" : "");
    p.push('<g class="tnode" data-node="' + esc(t.id) + '" data-kind="task" data-task="' + esc(t.id) + '"' + (t.id === state.task ? ' data-sel="1"' : "") + ' transform="translate(' + x + ',' + y + ')">');
    p.push('<rect class="' + ncls + (t.id === state.task ? " selrect" : "") + '" x="0" y="0" width="' + NW + '" height="' + NH + '" rx="9"/>');
    p.push('<text class="tseq" x="9" y="15">t' + t.seq + '</text>');
    if (t.agents.length) p.push('<rect class="badge-bg" x="' + (NW - 26) + '" y="-7" width="24" height="15" rx="3.5"/><text class="badge" x="' + (NW - 14) + '" y="3.5" text-anchor="middle">AI</text>');
    var lines = wrap(t.name, 22), sy = lines.length === 2 ? 24 : 31;
    lines.forEach(function (ln, k) { p.push('<text class="tname" x="10" y="' + (sy + k * 14) + '">' + esc(ln) + "</text>"); });
    var who = t.agents.length ? ((t.roles[0] ? lastSeg(t.roles[0]) + " + agent" : "agent")) : (t.roles[0] ? lastSeg(t.roles[0]) : "");
    var rAttr = t.roles[0] ? ' class="tperf rolelink-svg" data-role="' + esc(t.roles[0]) + '"' : ' class="tperf"';
    p.push('<text' + rAttr + ' x="10" y="' + (NH - 9) + '">' + esc(trunc(who, 24)) + "</text>" + subBadge(t) + "</g>");
  });
  (m.gateways || []).forEach(function (gw) {
    var x = state.flowPos[gw.id].x, y = state.flowPos[gw.id].y, c = GW / 2;
    p.push('<g class="gwnode" data-node="' + esc(gw.id) + '" data-kind="gateway"' + (gw.id === state.gwsel ? ' data-sel="1"' : "") + ' transform="translate(' + x + ',' + y + ')">');
    p.push('<rect class="gw' + (gw.id === state.gwsel ? " selrect" : "") + '" x="7" y="7" width="' + (GW - 14) + '" height="' + (GW - 14) + '" transform="rotate(45 ' + c + ' ' + c + ')"/>');
    p.push('<text class="gwglyph" x="' + c + '" y="' + (c + 6) + '" text-anchor="middle">' + (gw.type === "parallel" ? "+" : "×") + "</text>");
    if (gw.name) p.push('<text class="gwname" x="' + c + '" y="' + (GW + 13) + '" text-anchor="middle">' + esc(trunc(gw.name, 16)) + "</text>");
    p.push("</g>");
  });
  (m.events || []).forEach(function (ev) {
    var x = state.flowPos[ev.id].x, y = state.flowPos[ev.id].y, c = EV / 2;
    p.push('<g class="evnode" data-node="' + esc(ev.id) + '" data-kind="event"' + (ev.id === state.evsel ? ' data-sel="1"' : "") + ' transform="translate(' + x + ',' + y + ')">');
    p.push('<circle class="ev ev-' + esc(ev.kind) + (ev.id === state.evsel ? " selrect" : "") + '" cx="' + c + '" cy="' + c + '" r="' + (c - 3) + '"/>');
    if (ev.kind === "intermediate") p.push('<circle class="ev-inner" cx="' + c + '" cy="' + c + '" r="' + (c - 7) + '"/>');
    var glyph = ev.trigger === "timer" ? "⏱" : ev.trigger === "message" ? "✉" : "";
    if (glyph) p.push('<text class="evglyph" x="' + c + '" y="' + (c + 5) + '" text-anchor="middle">' + glyph + "</text>");
    var lbl = ev.name || (ev.trigger === "timer" ? (ev.timer || "timer") : ev.trigger === "message" ? (ev.message_ref || "message") : ev.kind);
    p.push('<text class="evname" x="' + c + '" y="' + (EV + 13) + '" text-anchor="middle">' + esc(trunc(lbl, 16)) + "</text>");
    p.push("</g>");
  });
  p.push("</svg>");
  return p.join("");
}
function updateGeomGraph(m) {
  var svg = $("#canvas svg"); if (!svg) return;
  svg.querySelector('.tip-node[data-node="__start__"]').setAttribute("transform", "translate(" + state.flowPos["__start__"].x + "," + state.flowPos["__start__"].y + ")");
  svg.querySelector('.tip-node[data-node="__end__"]').setAttribute("transform", "translate(" + state.flowPos["__end__"].x + "," + state.flowPos["__end__"].y + ")");
  (m.flows || []).forEach(function (f) {
    var A = nodeGeo(m, f.from), B = nodeGeo(m, f.to); if (!A || !B) return;
    var p1 = A.circle ? circPt(A.cx, A.cy, A.hw, B.cx, B.cy) : edgePt(A.cx, A.cy, A.hw, A.hh, B.cx, B.cy);
    var p2 = B.circle ? circPt(B.cx, B.cy, B.hw, A.cx, A.cy) : edgePt(B.cx, B.cy, B.hw, B.hh, A.cx, A.cy);
    var ln = svg.querySelector('line.flow[data-flow="' + f.id + '"]');
    if (ln) { ln.setAttribute("x1", p1.x); ln.setAttribute("y1", p1.y); ln.setAttribute("x2", p2.x); ln.setAttribute("y2", p2.y); }
    var lab = svg.querySelector('g.flabel[data-flow="' + f.id + '"]');
    if (lab) {
      var mx = (p1.x + p2.x) / 2, my = (p1.y + p2.y) / 2, txt = lab.querySelector("text"), rect = lab.querySelector("rect");
      txt.setAttribute("x", mx); txt.setAttribute("y", my + 3); txt.setAttribute("text-anchor", "middle");
      var w = (txt.textContent.length * 6.2) + 12;
      rect.setAttribute("x", mx - w / 2); rect.setAttribute("y", my - 9); rect.setAttribute("width", w); rect.setAttribute("height", 17);
    }
  });
  var minX = 1e9, minY = 1e9, maxX = -1e9, maxY = -1e9;
  Object.keys(state.flowPos).forEach(function (id) {
    var g = nodeGeo(m, id);
    minX = Math.min(minX, g.cx - g.hw); minY = Math.min(minY, g.cy - g.hh);
    maxX = Math.max(maxX, g.cx + g.hw); maxY = Math.max(maxY, g.cy + g.hh + (state.gw[id] ? 16 : 0));
  });
  var vx = minX - PAD, vy = minY - PAD, W = (maxX - minX) + 2 * PAD, H = (maxY - minY) + 2 * PAD;
  svg.setAttribute("viewBox", vx + " " + vy + " " + W + " " + H); svg.setAttribute("width", W); svg.setAttribute("height", H);
}
function wireGraph(m) {
  var svg = $("#canvas svg"); if (!svg) return;
  updateGeomGraph(m);
  // click empty canvas: leave connect mode, else clear the selection
  svg.addEventListener("pointerdown", function (e) {
    if (e.target !== svg) return;
    if (state.connect) { setConnect(false); return; }
    if (state.task || state.gwsel || state.evsel) { state.task = null; state.gwsel = null; state.evsel = null; markSel(); renderProps(); }
  });
  var drag = null;
  svg.querySelectorAll("g[data-node]").forEach(function (g) {
    var id = g.getAttribute("data-node");
    g.addEventListener("pointerdown", function (e) {
      if (e.button !== 0 || state.connect) return;
      drag = { sx: e.clientX, sy: e.clientY, ox: state.flowPos[id].x, oy: state.flowPos[id].y, moved: false };
      g.setPointerCapture(e.pointerId); g.classList.add("dragging"); e.preventDefault();
    });
    g.addEventListener("pointermove", function (e) {
      if (!drag) return;
      var dx = e.clientX - drag.sx, dy = e.clientY - drag.sy;
      if (Math.abs(dx) > 3 || Math.abs(dy) > 3) drag.moved = true;
      var nx = Math.max(0, drag.ox + dx), ny = Math.max(0, drag.oy + dy);
      state.flowPos[id] = { x: nx, y: ny };
      g.setAttribute("transform", "translate(" + nx + "," + ny + ")");
      updateGeomGraph(m);
    });
    g.addEventListener("pointerup", function (e) {
      if (!drag) return;
      try { g.releasePointerCapture(e.pointerId); } catch (err) {}
      g.classList.remove("dragging");
      var moved = drag.moved; drag = null;
      if (moved) saveLayout(m);
      else nodeClick(m, id, g);
    });
    // in connect mode drag is disabled, so selection/connect comes via click
    g.addEventListener("click", function () { if (state.connect) nodeClick(m, id, g); });
    g.addEventListener("dblclick", function () { var t = taskById(id); if (t && t.subprocess) drillInto(t.subprocess); });
  });
  svg.querySelectorAll("line.flow").forEach(function (ln) {
    ln.addEventListener("click", function () {
      if (state.connect) return;
      var fid = ln.getAttribute("data-flow");
      if (!confirm("Remove this flow? (deprecated on the audit trail, not destroyed)")) return;
      postFlow({ op: "remove", id: fid, actor: ACTOR, reason: "removed flow via canvas" }).then(reloadIf);
    });
  });
}
function nodeClick(m, id, g) {
  if (state.connect) {
    if (!state.connectFrom) { state.connectFrom = id; g.classList.add("connsrc"); return; }
    if (state.connectFrom === id) { state.connectFrom = null; renderCenter(); return; }
    var from = state.connectFrom, to = id, cond = null;
    var src = state.gw && state.gw[from];
    if (src && src.type === "exclusive") cond = prompt("Condition for this branch (optional), e.g. risk_score > 0.7:") || null;
    state.connectFrom = null;
    postFlow({ op: "add", process: m.id, from: from, to: to, condition: cond, actor: ACTOR, reason: "drew flow via canvas" }).then(reloadIf);
    return;
  }
  if (id === "__start__" || id === "__end__") { state.task = null; state.gwsel = null; state.evsel = null; markSel(); renderProps(); return; }
  if (state.ev && state.ev[id]) { state.evsel = id; state.task = null; state.gwsel = null; markSel(); renderProps(); return; }
  if (state.gw && state.gw[id]) { state.gwsel = id; state.task = null; state.evsel = null; markSel(); renderProps(); return; }
  state.task = id; state.gwsel = null; state.evsel = null; markSel(); renderProps();
}
function postFlow(body) { return fetch("/api/flow", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).then(function (r) { return r.json(); }); }
function postGateway(body) { return fetch("/api/gateway", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).then(function (r) { return r.json(); }); }
function postEvent(body) { return fetch("/api/event", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).then(function (r) { return r.json(); }); }
function reloadIf(res) { if (res && res.ok) load(); else if (res) alert("Rejected: " + res.error); }
function setConnect(on) {
  state.connect = on; state.connectFrom = null;
  var cn = document.getElementById("connect");
  if (cn) { cn.classList.toggle("active", on); cn.textContent = on ? "Done connecting" : "Connect"; }
  var c = $("#canvas"); if (c) c.classList.toggle("connecting", on);
  var banner = document.getElementById("connect-banner"); if (banner) banner.hidden = !on;
  if (!on) { var s = $("#canvas .connsrc"); if (s) s.classList.remove("connsrc"); }
}
// Esc always leaves connect mode — no way to get stuck in a hidden mode
document.addEventListener("keydown", function (e) { if (e.key === "Escape" && state.connect) setConnect(false); });
var connBtn = document.getElementById("connect");
if (connBtn) connBtn.addEventListener("click", function () { setConnect(!state.connect); });
var connDone = document.getElementById("connect-done");
if (connDone) connDone.addEventListener("click", function () { setConnect(false); });
var ebBtn = document.getElementById("enable-branch");
if (ebBtn) ebBtn.addEventListener("click", function () {
  var p = getProc(); if (!p) return;
  postFlow({ op: "enable", process: p.id, actor: ACTOR, reason: "enabled branching via canvas" }).then(reloadIf);
});

// ================= Phase C: swimlane view (steps grouped by performer) =========
var LW = 168, LH = 110;  // lane label column width, lane row height
function laneOf(t) { return t.roles[0] || (t.agents.length ? "__agent__" : "__none__"); }
function laneLabel(id) { return id === "__agent__" ? "Automated (agent)" : id === "__none__" ? "Unassigned" : shortRole(id); }
function laneOrder(m) {
  var seen = {}, order = [];
  m.tasks.forEach(function (t) { var l = laneOf(t); if (!seen[l]) { seen[l] = 1; order.push(l); } });
  return order.length ? order : ["__none__"];
}
function renderLanes(m) {
  if (!m.tasks.length) return '<div class="muted" style="padding:24px">No steps yet — add one from the palette, then switch to Lanes.</div>';
  var uid = m.id.replace(/[^A-Za-z0-9]/g, "_");
  var lanes = laneOrder(m), li = {}; lanes.forEach(function (l, i) { li[l] = i; });
  var CW = NW + GAP, padX = LW + 20, top = 8;
  var W = padX + m.tasks.length * CW + 40, H = lanes.length * LH + top + 4;
  state.lanes = { order: lanes, LH: LH, top: top };
  var pos = {};
  m.tasks.forEach(function (t, i) { var cy = top + li[laneOf(t)] * LH + LH / 2; pos[t.id] = { x: padX + i * CW, y: cy - NH / 2, cy: cy }; });
  var p = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ' + W + ' ' + H + '" width="' + W + '" height="' + H + '">'];
  p.push('<defs><marker id="ah_' + uid + '" markerWidth="7" markerHeight="7" refX="6" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6 z" class="arrow"/></marker></defs>');
  lanes.forEach(function (l, i) {
    p.push('<rect class="lane' + (i % 2 ? " alt" : "") + '" x="0" y="' + (top + i * LH) + '" width="' + W + '" height="' + (LH - 4) + '"/>');
    p.push('<line class="lanediv" x1="' + LW + '" y1="' + (top + i * LH) + '" x2="' + LW + '" y2="' + (top + i * LH + LH - 4) + '"/>');
    var lblAttr = l.indexOf("role.") === 0 ? ' class="lanelbl rolelink-svg" data-role="' + esc(l) + '"' : ' class="lanelbl"';
    p.push('<text' + lblAttr + ' x="14" y="' + (top + i * LH + LH / 2) + '">' + esc(trunc(laneLabel(l), 20)) + "</text>");
  });
  var f0 = pos[m.tasks[0].id], fl = pos[m.tasks[m.tasks.length - 1].id];
  var sx = padX - 44, sy = f0.cy, ex = fl.x + NW + 44, ey = fl.cy;
  m.tasks.forEach(function (t, i) {
    var to = { cx: pos[t.id].x + NW / 2, cy: pos[t.id].cy };
    var from = i === 0 ? { cx: sx, cy: sy, circle: true } : { cx: pos[m.tasks[i - 1].id].x + NW / 2, cy: pos[m.tasks[i - 1].id].cy };
    var p1 = from.circle ? circPt(from.cx, from.cy, R, to.cx, to.cy) : edgePt(from.cx, from.cy, NW / 2, NH / 2, to.cx, to.cy);
    var p2 = edgePt(to.cx, to.cy, NW / 2, NH / 2, from.cx, from.cy);
    p.push('<line class="conn" x1="' + p1.x + '" y1="' + p1.y + '" x2="' + p2.x + '" y2="' + p2.y + '" marker-end="url(#ah_' + uid + ')"/>');
  });
  var le = edgePt(fl.x + NW / 2, fl.cy, NW / 2, NH / 2, ex, ey);
  p.push('<line class="conn" x1="' + le.x + '" y1="' + le.y + '" x2="' + circPt(ex, ey, R, fl.x + NW / 2, fl.cy).x + '" y2="' + ey + '" marker-end="url(#ah_' + uid + ')"/>');
  p.push('<circle class="tip" cx="' + sx + '" cy="' + sy + '" r="' + R + '"/><text class="tip" x="' + sx + '" y="' + (sy + 3) + '" text-anchor="middle">start</text>');
  p.push('<circle class="tip" cx="' + ex + '" cy="' + ey + '" r="' + R + '"/><text class="tip" x="' + ex + '" y="' + (ey + 3) + '" text-anchor="middle">end</text>');
  m.tasks.forEach(function (t) {
    var a = pos[t.id], ncls = "node" + (t.agents.length ? " agent" : "") + (t.override ? " override" : "");
    p.push('<g class="tnode lane-node" data-task="' + esc(t.id) + '" transform="translate(' + a.x + ',' + a.y + ')">');
    p.push('<rect class="' + ncls + (t.id === state.task ? " selrect" : "") + '" x="0" y="0" width="' + NW + '" height="' + NH + '" rx="9"/>');
    p.push('<text class="tseq" x="9" y="15">t' + t.seq + '</text>');
    if (t.agents.length) p.push('<rect class="badge-bg" x="' + (NW - 26) + '" y="-7" width="24" height="15" rx="3.5"/><text class="badge" x="' + (NW - 14) + '" y="3.5" text-anchor="middle">AI</text>');
    var lines = wrap(t.name, 22), yy = lines.length === 2 ? 26 : 33;
    lines.forEach(function (ln, k) { p.push('<text class="tname" x="10" y="' + (yy + k * 14) + '">' + esc(ln) + "</text>"); });
    p.push(subBadge(t) + "</g>");
  });
  p.push("</svg>");
  return p.join("");
}
function wireLanes(m) {
  var svg = $("#canvas svg"); if (!svg) return;
  var drag = null;
  svg.querySelectorAll("g.lane-node").forEach(function (g) {
    var tid = g.getAttribute("data-task");
    g.addEventListener("pointerdown", function (e) {
      if (e.button !== 0) return;
      var tr = g.getAttribute("transform").match(/translate\(([-\d.]+),([-\d.]+)\)/);
      drag = { sx: e.clientX, sy: e.clientY, ox: +tr[1], oy: +tr[2], moved: false };
      g.setPointerCapture(e.pointerId); g.classList.add("dragging"); e.preventDefault();
    });
    g.addEventListener("pointermove", function (e) {
      if (!drag) return;
      var dx = e.clientX - drag.sx, dy = e.clientY - drag.sy;
      if (Math.abs(dx) > 3 || Math.abs(dy) > 3) drag.moved = true;
      g.setAttribute("transform", "translate(" + (drag.ox + dx) + "," + (drag.oy + dy) + ")");
    });
    g.addEventListener("pointerup", function (e) {
      if (!drag) return;
      try { g.releasePointerCapture(e.pointerId); } catch (err) {}
      g.classList.remove("dragging");
      var moved = drag.moved; drag = null;
      if (!moved) { state.task = tid; state.gwsel = null; markSel(); renderProps(); return; }
      var pt = svgPoint(e.clientX, e.clientY);
      var idx = Math.max(0, Math.min(state.lanes.order.length - 1, Math.floor((pt.y - state.lanes.top) / state.lanes.LH)));
      var target = state.lanes.order[idx], t = taskById(tid);
      if (target === laneOf(t) || target.indexOf("__") === 0) { renderCenter(); return; }  // snap back
      postTask({ op: "edit", id: tid, changes: { performed_by: [target].concat(t.agents) }, actor: ACTOR, reason: "reassigned performer via swimlane" })
        .then(function (res) { if (res.ok) load(); else { alert("Rejected: " + res.error); renderCenter(); } });
    });
    g.addEventListener("dblclick", function () { var t = taskById(tid); if (t && t.subprocess) drillInto(t.subprocess); });
  });
}

// ================= Phase D: process landscape / repository =====================
function openProcess(id) {
  if (!state.procs.find(function (x) { return x.id === id; })) return;
  state.sel = id; state.view = "flow"; state.nav = []; state.task = null; state.gwsel = null;
  document.querySelectorAll(".views button").forEach(function (x) { x.classList.toggle("active", x.getAttribute("data-view") === "flow"); });
  renderNav(); renderTitle(); renderCenter(); renderProps();
}
function pchips(ids) { return ids.map(function (pid) { return '<a class="pchip" data-open="' + esc(pid) + '">' + esc(pid) + "</a>"; }).join(""); }
function renderLandscape(L) {
  var house = L.domains.map(function (d) {
    var cards = d.processes.map(function (p) {
      var ai = p.agent_steps ? p.agent_steps + " AI &middot; " : "";
      return '<div class="pcard" data-open="' + esc(p.id) + '">'
        + '<div class="pcid">' + esc(p.id) + "</div>"
        + '<div class="pcname">' + esc(p.name) + "</div>"
        + '<div class="pcmeta">' + p.steps + " steps &middot; " + ai + "owner " + esc(shortRole(p.owner)) + "</div>"
        + '<div class="pcbadges"><span class="gdot ' + (p.reviewed ? "good" : "warn") + '"></span>'
        + (p.reviewed ? "reviewed guardrail" : "default guardrail")
        + (p.risks ? ' &middot; <span class="rtag">' + p.risks + " risk</span>" : "")
        + (p.kpis ? " &middot; " + p.kpis + " KPI" : "") + "</div></div>";
    }).join("");
    return '<section class="domain"><h3><span class="dcode">' + esc(d.code) + '</span> ' + esc(d.name)
      + ' <span class="dcount">' + d.processes.length + "</span></h3>"
      + '<div class="pcards">' + cards + "</div></section>";
  }).join("");
  var C = L.catalogs;
  function catcol(title, rows) { return '<div class="catcol"><h4>' + title + "</h4>" + rows + "</div>"; }
  var roleRows = C.roles.map(function (r) {
    return '<div class="catrow"><div class="catmain"><span class="catname rolelink" data-role="' + esc(r.id) + '">' + esc(r.name) + '</span><span class="catcount">' + r.count + "</span></div>"
      + '<div class="catprocs">' + pchips(r.processes) + "</div></div>";
  }).join("");
  var kpiRows = C.kpis.map(function (k) {
    return '<div class="catrow"><div class="catmain"><span class="catname">' + esc(k.name) + '</span><span class="catcount">' + k.count + "</span></div>"
      + '<div class="catprocs">' + pchips(k.processes) + "</div></div>";
  }).join("");
  var riskRows = C.risks.map(function (x) {
    return '<div class="catrow"><div class="catmain"><span class="catname" title="' + esc(x.risk) + '">' + esc(x.id) + '</span></div>'
      + '<div class="catprocs">' + pchips([x.process]) + "</div></div>";
  }).join("");
  return '<div class="landscape">'
    + '<div class="lshead">Process landscape &mdash; <b>' + L.processes_total + "</b> processes across <b>" + L.domains.length + "</b> APQC domains. Click any process to open it.</div>"
    + '<div class="house">' + house + "</div>"
    + '<div class="catalogs"><div class="catshead">Catalogs &mdash; what threads across the org</div><div class="catgrid">'
    + catcol("Roles (" + C.roles.length + ")", roleRows)
    + catcol("KPIs (" + C.kpis.length + ")", kpiRows)
    + catcol("Risks (" + C.risks.length + ")", riskRows)
    + "</div></div></div>";
}
function wireLandscape() {
  var c = $("#canvas"); if (!c) return;
  c.querySelectorAll("[data-open]").forEach(function (el) {
    el.addEventListener("click", function () { openProcess(el.getAttribute("data-open")); });
  });
}
var lsBtn = document.getElementById("landscape-btn");
if (lsBtn) lsBtn.addEventListener("click", function () {
  state.view = "landscape";
  document.querySelectorAll(".views button").forEach(function (x) { x.classList.remove("active"); });
  renderCenter();
  if (!state.landscape) fetch("/api/landscape").then(function (r) { return r.json(); })
    .then(function (d) { state.landscape = d.landscape; if (state.view === "landscape") renderCenter(); });
});

// ---------- RACI view ----------
function renderRaci(m) {
  var roles = [m.owner];
  m.tasks.forEach(function (t) { t.roles.forEach(function (r) { if (roles.indexOf(r) < 0) roles.push(r); }); if (t.escalation_path && roles.indexOf(t.escalation_path) < 0) roles.push(t.escalation_path); });
  var head = '<tr><th class="role">Role</th>' + m.tasks.map(function (t) { return "<th>t" + t.seq + (t.agents.length ? " ᴬᴵ" : "") + "</th>"; }).join("") + "</tr>";
  var rows = roles.map(function (r) {
    var cells = m.tasks.map(function (t) {
      var parts = [];
      if (r === m.owner) parts.push('<span class="a">A</span>');
      if (t.roles.indexOf(r) >= 0) parts.push('<span class="r">R</span>');
      if (t.escalation_path === r) parts.push('<span class="c">C</span>');
      return "<td>" + parts.join(" ") + "</td>";
    }).join("");
    return '<tr><td class="role rolelink" data-role="' + esc(r) + '">' + esc(roleName(r)) + "</td>" + cells + "</tr>";
  }).join("");
  return '<table class="raci"><thead>' + head + "</thead><tbody>" + rows + "</tbody></table>"
    + '<div class="raci-legend"><b class="r" style="color:var(--accent)">R</b> responsible · '
    + '<b style="color:var(--crit)">A</b> accountable (process owner) · '
    + '<b style="color:var(--warn)">C</b> consulted on escalation · derived from the model, not hand-maintained</div>';
}

// ---------- Checklist view ----------
function renderChecklist(m) {
  return '<ul class="chklist">' + m.tasks.map(function (t) {
    var key = "cc-chk-" + t.id, done = false;
    try { done = localStorage.getItem(key) === "1"; } catch (e) {}
    var who = t.roles.map(shortRole).join(", ") + (t.agents.length ? " + agent" : "");
    var gr = t.guardrail_full ? ("allow: " + csv(t.allow) + (t.escalate_if ? " · escalate if " + t.escalate_if : "")) : "no guardrail";
    return '<li class="' + (done ? "done" : "") + '" data-t="' + esc(t.id) + '">'
      + '<input type="checkbox" ' + (done ? "checked" : "") + '>'
      + '<div><div class="cnm">t' + t.seq + " · " + esc(t.name) + "</div>"
      + '<div class="cmeta">' + esc(who) + "</div>"
      + '<div class="cgr">' + esc(gr) + "</div></div></li>";
  }).join("") + "</ul>";
}
$("#canvas").addEventListener("change", function (e) {
  var li = e.target.closest("li[data-t]"); if (!li) return;
  var key = "cc-chk-" + li.getAttribute("data-t");
  try { localStorage.setItem(key, e.target.checked ? "1" : "0"); } catch (err) {}
  li.classList.toggle("done", e.target.checked);
});

// ---------- properties panel ----------
function renderProps() {
  var p = getProc(), t = getTask();
  if (!p) return;
  if (state.evsel && p.explicit) {
    var ev = (p.events || []).find(function (e) { return e.id === state.evsel; });
    if (ev) { $("#props").innerHTML = evProps(ev); wireEvProps(ev); return; }
    state.evsel = null;
  }
  if (state.gwsel && p.explicit) {
    var gw = (p.gateways || []).find(function (g) { return g.id === state.gwsel; });
    if (gw) { $("#props").innerHTML = gwProps(gw); wireGwProps(gw); return; }
    state.gwsel = null;
  }
  if (!t) { $("#props").innerHTML = procProps(p); return; }
  $("#props").innerHTML = taskProps(p, t);
  var form = $("#gr-form");
  if (form) {
    form.addEventListener("submit", saveGuardrail);
    $("#gr-reset").addEventListener("click", function () { renderProps(); });
  }
  if ($("#t-save")) {
    $("#t-save").onclick = saveStruct;
    $("#t-up").onclick = function () { moveStep("up"); };
    $("#t-down").onclick = function () { moveStep("down"); };
    $("#t-remove").onclick = removeStep;
  }
  if ($("#t-bind")) $("#t-bind").onclick = function () { bindAgent("bind"); };
  if ($("#t-unbind")) $("#t-unbind").onclick = function () { bindAgent("unbind"); };
  if ($("#t-subp")) $("#t-subp").onchange = function () { setSubprocess(this.value); };
}
function procOptions(t) {
  return state.procs.filter(function (pp) { return pp.id !== getProc().id; }).map(function (pp) {
    return '<option value="' + esc(pp.id) + '"' + (t.subprocess === pp.id ? " selected" : "") + ">" + esc(pp.id) + " — " + esc(trunc(pp.name, 24)) + "</option>";
  }).join("");
}
function setSubprocess(v) {
  var t = getTask(); if (!t) return;
  postTask({ op: "edit", id: t.id, changes: { subprocess_ref: v || null }, actor: ACTOR, reason: ($("#t-reason") && $("#t-reason").value.trim()) || (v ? "set drill-down" : "cleared drill-down") })
    .then(function (res) { if (res.ok) load(); else structMsg("Rejected: " + res.error, "err"); });
}

function bindAgent(op) {
  var t = getTask(); if (!t) return;
  postTask({ op: op, id: t.id, actor: ACTOR, reason: $("#t-reason").value.trim() || (op === "bind" ? "make step agent-run" : "make step human-only") })
    .then(function (res) { if (res.ok) load(); else structMsg("Rejected: " + res.error, "err"); });
}

// ---------- structural edits (Task write path) ----------
var ACTOR = "role.ops.support_lead";
function postTask(body) {
  return fetch("/api/task", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).then(function (r) { return r.json(); });
}
function structMsg(txt, cls) { var m = $("#t-msg"); if (m) { m.textContent = txt; m.className = "msg " + cls; m.hidden = false; } }
function saveStruct() {
  var t = getTask(); if (!t) return;
  postTask({ op: "edit", id: t.id, changes: { name: $("#t-name").value.trim(), performed_by: parseCsv($("#t-perf").value) }, actor: ACTOR, reason: $("#t-reason").value.trim() })
    .then(function (res) { if (res.ok) { load().then(function () { structMsg("Saved v" + res.result.version + " — step updated.", "ok"); }); } else structMsg("Rejected: " + res.error, "err"); });
}
function moveStep(dir) {
  var t = getTask(); if (!t) return;
  postTask({ op: "move", id: t.id, dir: dir, actor: ACTOR, reason: "reorder step" })
    .then(function (res) { if (res.ok) load(); else structMsg("Rejected: " + res.error, "err"); });
}
function removeStep() {
  var t = getTask(); if (!t) return;
  if (!confirm("Remove step " + t.id + "? It is deprecated (retained on the audit trail), not destroyed.")) return;
  postTask({ op: "remove", id: t.id, actor: ACTOR, reason: $("#t-reason").value.trim() || "removed via canvas" })
    .then(function (res) { if (res.ok) { state.task = null; load(); } else structMsg("Rejected: " + res.error, "err"); });
}
function addStep() {
  var p = getProc(); if (!p) return;
  var name = prompt("New step name for " + p.id + ":"); if (!name) return;
  postTask({ op: "add", process: p.id, name: name, actor: ACTOR, reason: "added step via canvas" })
    .then(function (res) { if (res.ok) { state.task = res.result.id; load(); } else alert("Rejected: " + res.error); });
}
$("#add-step").addEventListener("click", addStep);

// ---------- drag-palette authoring ----------
var dragTile = null;
document.querySelectorAll(".palette .tile").forEach(function (tile) {
  tile.addEventListener("dragstart", function (e) {
    dragTile = { kind: tile.getAttribute("data-kind") || "task", gtype: tile.getAttribute("data-gtype") || "", name: tile.getAttribute("data-name") || "Step", ekind: tile.getAttribute("data-ekind") || "", trigger: tile.getAttribute("data-trigger") || "" };
    e.dataTransfer.setData("text/plain", dragTile.name);
    e.dataTransfer.effectAllowed = "copy";
  });
});
// client point -> SVG user coords (for placing a dropped gateway where it lands)
function svgPoint(clientX, clientY) {
  var svg = $("#canvas svg"); if (!svg) return { x: 200, y: 120 };
  var r = svg.getBoundingClientRect(), vb = svg.viewBox.baseVal;
  return { x: vb.x + (clientX - r.left) * (vb.width / r.width), y: vb.y + (clientY - r.top) * (vb.height / r.height) };
}
var canvas = $("#canvas");
canvas.addEventListener("dragover", function (e) { e.preventDefault(); e.dataTransfer.dropEffect = "copy"; canvas.classList.add("dropok"); });
canvas.addEventListener("dragleave", function () { canvas.classList.remove("dropok"); });
canvas.addEventListener("drop", function (e) {
  e.preventDefault(); canvas.classList.remove("dropok");
  var p = getProc(); if (!p) return;
  if (state.view !== "flow") { alert("Switch to the Flowchart view to drop here."); return; }
  var tile = dragTile || { kind: "task", name: e.dataTransfer.getData("text/plain") || "Step" };
  dragTile = null;
  if (tile.kind === "gateway") {
    if (!p.explicit) { alert("Enable branching first, then drop a gateway."); return; }
    var pt = svgPoint(e.clientX, e.clientY);
    postGateway({ op: "add", process: p.id, gtype: tile.gtype, name: "", actor: ACTOR, reason: "added gateway via palette" })
      .then(function (res) {
        if (!res.ok) { alert("Rejected: " + res.error); return; }
        var positions = JSON.parse(JSON.stringify(state.flowPos || {}));
        positions[res.result.id] = { x: Math.max(0, pt.x - GW / 2), y: Math.max(0, pt.y - GW / 2) };
        fetch("/api/layout", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ process: p.id, positions: positions }) })
          .then(function () { state.gwsel = res.result.id; load(); });
      });
    return;
  }
  if (tile.kind === "event") {
    if (!p.explicit) { alert("Enable branching first, then drop an event."); return; }
    var ept = svgPoint(e.clientX, e.clientY);
    postEvent({ op: "add", process: p.id, kind: tile.ekind || "intermediate", trigger: tile.trigger || "timer", name: "", actor: ACTOR, reason: "added event via palette" })
      .then(function (res) {
        if (!res.ok) { alert("Rejected: " + res.error); return; }
        var positions = JSON.parse(JSON.stringify(state.flowPos || {}));
        positions[res.result.id] = { x: Math.max(0, ept.x - EV / 2), y: Math.max(0, ept.y - EV / 2) };
        fetch("/api/layout", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ process: p.id, positions: positions }) })
          .then(function () { state.evsel = res.result.id; load(); });
      });
    return;
  }
  postTask({ op: "add", process: p.id, name: tile.name, after: p.explicit ? null : dropAfter(e.clientX), actor: ACTOR, reason: "added step via palette" })
    .then(function (res) { if (res.ok) { state.task = res.result.id; load(); } else alert("Rejected: " + res.error); });
});
function dropAfter(x) {
  var nodes = Array.prototype.slice.call(document.querySelectorAll("#canvas g.tnode[data-task]"));
  if (!nodes.length) return null;                       // empty process -> first step
  var items = nodes.map(function (n) { var r = n.querySelector("rect").getBoundingClientRect(); return { id: n.getAttribute("data-task"), c: r.left + r.width / 2 }; });
  if (x < items[0].c) return "__start__";               // dropped before the first step
  var after = items[0].id;
  items.forEach(function (it) { if (it.c < x) after = it.id; });
  return after;                                          // insert after the last step left of the drop
}
$("#new-proc").addEventListener("click", function () {
  var name = prompt("New process name:"); if (!name) return;
  var code = prompt("APQC-style code (e.g. QA.5.1.1):"); if (!code) return;
  var owner = prompt("Owner role:", "role.ops.support_lead"); if (!owner) return;
  fetch("/api/process", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ code: code.trim(), name: name.trim(), owner: owner.trim(), actor: ACTOR, reason: "authored via canvas" }) })
    .then(function (r) { return r.json(); })
    .then(function (res) { if (res.ok) { state.sel = res.result.id; state.task = null; state.view = "flow"; document.querySelectorAll(".views button").forEach(function (x) { x.classList.toggle("active", x.getAttribute("data-view") === "flow"); }); load(); } else alert("Rejected: " + res.error); });
});
// label any node for the connections list
function nodeLabel(id) {
  if (id === "__start__") return "start";
  if (id === "__end__") return "end";
  var p = getProc(); if (!p) return id;
  var t = p.tasks.find(function (x) { return x.id === id; }); if (t) return "t" + t.seq + " · " + t.name;
  var g = (p.gateways || []).find(function (x) { return x.id === id; }); if (g) return "◇ " + (g.name || g.type);
  var e = (p.events || []).find(function (x) { return x.id === id; }); if (e) return "○ " + (e.name || e.trigger);
  return id;
}
// the outgoing connections from a node, as an editable list (condition + remove)
function connList(nodeId) {
  var flows = (getProc().flows || []).filter(function (f) { return f.from === nodeId; });
  if (!flows.length) return '<div class="muted" style="font-size:12px">No outgoing connections yet. Use <b>Draw a connection</b> below.</div>';
  return flows.map(function (f) {
    return '<div class="conn-item" data-flow="' + esc(f.id) + '">'
      + '<div class="conn-to">&rarr; ' + esc(trunc(nodeLabel(f.to), 26)) + "</div>"
      + '<div class="conn-edit"><input class="cond-in" placeholder="condition (optional), e.g. amount &gt; 500" value="' + esc(f.condition || "") + '">'
      + '<button class="mini cond-save" type="button">Set</button>'
      + '<button class="mini danger cond-del" type="button">Remove</button></div></div>';
  }).join("");
}

function evProps(ev) {
  var kindLbl = { start: "Start event", intermediate: "Intermediate event", end: "End event" };
  return '<div class="p-head"><span class="p-id">' + esc(ev.id) + "</span></div>"
    + '<div class="p-sub">event</div>'
    + '<div class="struct"><div class="lbl">edit event</div>'
    + '<label>Name<input id="ev-name" type="text" value="' + esc(ev.name || "") + '" placeholder="e.g. 24h SLA"></label>'
    + '<label>Kind<select id="ev-kind">' + ["start", "intermediate", "end"].map(function (k) { return '<option value="' + k + '"' + (ev.kind === k ? " selected" : "") + ">" + kindLbl[k] + "</option>"; }).join("") + "</select></label>"
    + '<label>Trigger<select id="ev-trig">' + [["none", "Plain"], ["timer", "Timer"], ["message", "Message"]].map(function (k) { return '<option value="' + k[0] + '"' + (ev.trigger === k[0] ? " selected" : "") + ">" + k[1] + "</option>"; }).join("") + "</select></label>"
    + '<label id="ev-timer-l"' + (ev.trigger === "timer" ? "" : " hidden") + '>Schedule <span class="hint">ISO-8601 / cron</span><input id="ev-timer" type="text" value="' + esc(ev.timer || "") + '" placeholder="P1D · PT24H · 0 9 * * 1"></label>'
    + '<label id="ev-msg-l"' + (ev.trigger === "message" ? "" : " hidden") + '>Message<input id="ev-msg" type="text" value="' + esc(ev.message_ref || "") + '" placeholder="e.g. payment_received"></label>'
    + '<div class="btnrow"><button id="ev-save">Save event</button><button id="ev-remove" class="danger">Remove event</button></div></div>'
    + '<div class="p-sec"><div class="lbl">connections out</div>' + connList(ev.id) + '</div>'
    + '<div class="struct"><button id="node-connect" class="ghost-btn">Draw a connection from here</button>'
    + '<div class="p-row muted" style="margin-top:8px">Tip: <b>drag</b> the event to move it. Events are structural — they carry no role or guardrail.</div></div>';
}

function gwProps(gw) {
  return '<div class="p-head"><span class="p-id">' + esc(gw.id) + "</span></div>"
    + '<div class="p-sub">gateway</div>'
    + '<div class="struct"><div class="lbl">edit gateway</div>'
    + '<label>Name<input id="gw-name" type="text" value="' + esc(gw.name || "") + '" placeholder="e.g. amount over 500?"></label>'
    + '<label>Type<select id="gw-type">'
    + '<option value="exclusive"' + (gw.type === "exclusive" ? " selected" : "") + ">Exclusive — decision (XOR)</option>"
    + '<option value="parallel"' + (gw.type === "parallel" ? " selected" : "") + ">Parallel — fork/join (AND)</option>"
    + "</select></label>"
    + '<div class="btnrow"><button id="gw-save">Save gateway</button><button id="gw-remove" class="danger">Remove gateway</button></div></div>'
    + '<div class="p-sec"><div class="lbl">branches out</div>' + connList(gw.id)
    + (gw.type === "exclusive" ? '<div class="p-row muted" style="font-size:11.5px;margin-top:6px">On an exclusive gateway, label each branch with the condition that takes it.</div>' : "") + "</div>"
    + '<div class="struct"><button id="node-connect" class="ghost-btn">Draw a connection from here</button>'
    + '<div class="p-row muted" style="margin-top:8px">Tip: <b>drag</b> the diamond to move it. A gateway is structural — it carries no role; the steps it routes to do.</div></div>';
}

// shared wiring for the editable connections list (used by gw + ev panels)
function wireConnList(container) {
  container.querySelectorAll(".conn-item").forEach(function (row) {
    var fid = row.getAttribute("data-flow");
    var save = row.querySelector(".cond-save"), del = row.querySelector(".cond-del"), inp = row.querySelector(".cond-in");
    if (save) save.onclick = function () {
      postFlow({ op: "edit", id: fid, changes: { condition: inp.value.trim() }, actor: ACTOR, reason: "set branch condition via canvas" })
        .then(function (res) { if (res.ok) load(); else alert("Rejected: " + res.error); });
    };
    if (del) del.onclick = function () {
      if (!confirm("Remove this connection? (deprecated on the audit trail)")) return;
      postFlow({ op: "remove", id: fid, actor: ACTOR, reason: "removed flow via canvas" }).then(reloadIf);
    };
  });
}
function startConnectFrom(nodeId) {
  setConnect(true);
  state.connectFrom = nodeId;
  var el = $('#canvas [data-node="' + (window.CSS && CSS.escape ? CSS.escape(nodeId) : nodeId) + '"]');
  if (el) el.classList.add("connsrc");
}
function wireGwProps(gw) {
  var box = $("#props");
  $("#gw-save").onclick = function () {
    postGateway({ op: "edit", id: gw.id, changes: { name: $("#gw-name").value.trim(), type: $("#gw-type").value }, actor: ACTOR, reason: "edited gateway via canvas" })
      .then(function (res) { if (res.ok) load(); else alert("Rejected: " + res.error); });
  };
  $("#gw-remove").onclick = function () {
    if (!confirm("Remove gateway " + gw.id + "? Its connections are removed too (all on the audit trail).")) return;
    postGateway({ op: "remove", id: gw.id, actor: ACTOR, reason: "removed gateway via canvas" })
      .then(function (res) { if (res.ok) { state.gwsel = null; load(); } else alert("Rejected: " + res.error); });
  };
  $("#node-connect").onclick = function () { startConnectFrom(gw.id); };
  wireConnList(box);
}
function wireEvProps(ev) {
  var box = $("#props");
  var trig = $("#ev-trig");
  trig.onchange = function () {
    $("#ev-timer-l").hidden = trig.value !== "timer";
    $("#ev-msg-l").hidden = trig.value !== "message";
  };
  $("#ev-save").onclick = function () {
    var changes = { name: $("#ev-name").value.trim(), kind: $("#ev-kind").value, trigger: trig.value,
                    timer: trig.value === "timer" ? $("#ev-timer").value.trim() : null,
                    message_ref: trig.value === "message" ? $("#ev-msg").value.trim() : null };
    postEvent({ op: "edit", id: ev.id, changes: changes, actor: ACTOR, reason: "edited event via canvas" })
      .then(function (res) { if (res.ok) load(); else alert("Rejected: " + res.error); });
  };
  $("#ev-remove").onclick = function () {
    if (!confirm("Remove event " + ev.id + "? Its connections are removed too (all on the audit trail).")) return;
    postEvent({ op: "remove", id: ev.id, actor: ACTOR, reason: "removed event via canvas" })
      .then(function (res) { if (res.ok) { state.evsel = null; load(); } else alert("Rejected: " + res.error); });
  };
  $("#node-connect").onclick = function () { startConnectFrom(ev.id); };
  wireConnList(box);
}
function procProps(p) {
  var risks = p.risks.map(function (r) { return '<span class="pill risk" title="' + esc(r.risk) + '">' + esc(r.id) + "</span>"; }).join("");
  var kpis = p.kpis.map(function (k) { return '<span class="pill">' + esc(k) + "</span>"; }).join("");
  return '<div class="p-head"><span class="p-id">' + esc(p.id) + "</span></div>"
    + '<div class="p-sub">' + esc(p.name) + "</div>"
    + '<div class="p-sec"><div class="lbl">owner</div><div class="p-row">' + esc(p.owner) + "</div></div>"
    + '<div class="p-sec"><div class="lbl">guardrail</div><div class="p-row"><span class="pill gr">' + esc(p.guardrail || "none") + "</span></div></div>"
    + '<div class="p-sec"><div class="lbl">KPIs</div><div class="p-row">' + (kpis || '<span class="muted">none</span>') + "</div></div>"
    + '<div class="p-sec"><div class="lbl">risk &amp; control</div><div class="p-row">' + (risks || '<span class="muted">none</span>') + "</div></div>"
    + '<div class="p-sec"><div class="p-row muted">Click a step in the flowchart to edit its guardrail.</div></div>';
}
function taskProps(p, t) {
  var g = t.guardrail_full;
  var head = '<div class="p-head"><span class="p-id">t' + t.seq + "</span> " + esc(t.name) + "</div>"
    + '<div class="p-sub">' + esc(t.id) + (t.override ? ' · <span style="color:var(--warn)">task override</span>' : "") + "</div>"
    + '<div class="p-sec"><div class="lbl">performed by</div><div class="p-row">' + (t.roles.length ? t.roles.map(function (r) { return roleLink(r); }).join(", ") : "—") + (t.agents.length ? ' <span class="pill gr">' + esc(t.agents.map(lastSeg).join(", ")) + " (agent)</span>" : "") + "</div></div>"
    + (t.escalation_path ? '<div class="p-sec"><div class="lbl">escalates to</div><div class="p-row">' + roleLink(t.escalation_path) + "</div></div>" : "")
    + '<div class="p-sec"><div class="lbl">data</div><div class="p-row">in ' + esc(csv(t.inputs) || "—") + " · out " + esc(csv(t.outputs) || "—") + "</div>"
    + '<div class="p-row">' + t.kpi_refs.map(function (k) { return '<span class="pill">' + esc(k) + "</span>"; }).join("") + "</div></div>";
  var struct = '<div class="struct"><div class="lbl">step structure</div>'
    + '<label>Name<input id="t-name" type="text" value="' + esc(t.name) + '"></label>'
    + '<label>Performed by <span class="hint">comma refs · role.* / agent.*</span><input id="t-perf" type="text" value="' + esc(t.roles.concat(t.agents).join(", ")) + '"></label>'
    + '<label>Reason <span class="hint">required · §7.5</span><input id="t-reason" type="text" placeholder="why?"></label>'
    + '<div class="btnrow"><button id="t-save">Save step</button><button id="t-up">↑ up</button><button id="t-down">↓ down</button><button id="t-remove" class="danger">Remove step</button></div>'
    + (t.agents.length
        ? '<button id="t-unbind" class="bindbtn unbind">Unbind agent (make human-only)</button>'
        : '<button id="t-bind" class="bindbtn">Make this step agent-run</button>')
    + '<label>Drill-down to sub-process <span class="hint">this step expands into another process</span>'
    + '<select id="t-subp"><option value="">(none &mdash; leaf step)</option>' + procOptions(t) + "</select></label>"
    + '<div id="t-msg" class="msg" hidden></div></div>';
  if (!g) return head + struct + '<div class="p-sec"><div class="p-row muted">No guardrail on this step (inherits the process default, if any).</div></div>';
  return head + struct
    + '<div class="p-sec"><div class="lbl">guardrail ' + esc(g.id) + " v" + g.version + '</div>'
    + '<form id="gr-form">'
    + '<label>Allowed <span class="hint">comma-separated</span><textarea id="f-allow" rows="2">' + esc(csv(g.allowed_actions)) + "</textarea></label>"
    + '<label>Forbidden<textarea id="f-deny" rows="2">' + esc(csv(g.forbidden_actions)) + "</textarea></label>"
    + '<label>Escalate if <span class="hint">e.g. risk_score &gt; 0.7</span><input id="f-esc" type="text" value="' + esc(g.escalate_if || "") + '"></label>'
    + '<label>Data scope<textarea id="f-scope" rows="2">' + esc(csv(g.data_scope)) + "</textarea></label>"
    + '<label>Escalation path<input id="f-path" type="text" value="' + esc(g.escalation_path || "") + '"></label>'
    + '<label>Audit<select id="f-audit">'
    + ["timestamp_outcome", "inputs_outputs", "full_capture"].map(function (o) { return '<option ' + (o === g.audit_requirement ? "selected" : "") + ">" + o + "</option>"; }).join("")
    + "</select></label>"
    + '<label>Reason for change <span class="hint">required · §7.5</span><input id="f-reason" type="text" placeholder="why?"></label>'
    + '<div id="gr-msg" class="msg" hidden></div>'
    + '<div class="actions"><button type="button" id="gr-reset" class="ghost">Reset</button><button type="submit" class="save">Save new version</button></div>'
    + '<input type="hidden" id="f-grid" value="' + esc(g.id) + '"></form></div>';
}

function saveGuardrail(e) {
  e.preventDefault();
  var t = getTask(), g = t.guardrail_full;
  var changes = {
    allowed_actions: parseCsv($("#f-allow").value),
    forbidden_actions: parseCsv($("#f-deny").value),
    escalate_if: $("#f-esc").value.trim() || null,
    data_scope: parseCsv($("#f-scope").value),
    escalation_path: $("#f-path").value.trim(),
    audit_requirement: $("#f-audit").value,
    rate_limit: g.rate_limit,
  };
  var btn = $("#gr-form .save"); btn.disabled = true;
  fetch("/api/guardrail?id=" + encodeURIComponent($("#f-grid").value), {
    method: "PUT", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ changes: changes, actor: "role.ops.support_lead", reviewer: "role.qms.iso_advisor", reason: $("#f-reason").value.trim() }),
  }).then(function (r) { return r.json(); }).then(function (res) {
    btn.disabled = false;
    if (res.ok) {
      load().then(function () {
        var m = $("#gr-msg");
        if (m) { m.textContent = "Saved v" + res.guardrail.version + " — live for agents on their next call. No deploy."; m.className = "msg ok"; m.hidden = false; }
      });
    } else {
      var m = $("#gr-msg"); m.textContent = "Rejected: " + res.error; m.className = "msg err"; m.hidden = false;
    }
  });
}

// ---------- theme ----------
(function () {
  var order = ["auto", "light", "dark"], root = document.documentElement, btn = $("#themeBtn"), cur = "auto";
  try { cur = localStorage.getItem("cc-canvas-theme") || "auto"; } catch (e) {}
  function apply(x) { if (x === "auto") root.removeAttribute("data-theme"); else root.setAttribute("data-theme", x); btn.textContent = "theme: " + x; try { localStorage.setItem("cc-canvas-theme", x); } catch (e) {} }
  apply(cur);
  btn.addEventListener("click", function () { cur = order[(order.indexOf(cur) + 1) % order.length]; apply(cur); });
})();

// ---------- Phase E: publish / share ----------
function postPortal(body) { return fetch("/api/portal", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).then(function (r) { return r.json(); }); }
function portalUrl(token) { return location.origin + "/portal?token=" + encodeURIComponent(token); }
function openShare() { $("#share-modal").hidden = false; refreshShareList(); }
function closeShare() { $("#share-modal").hidden = true; }
function refreshShareList() {
  fetch("/api/portal").then(function (r) { return r.json(); }).then(function (d) {
    var links = d.links || [];
    if (!links.length) { $("#share-list").innerHTML = '<div class="muted">No links yet. Publish one above.</div>'; return; }
    $("#share-list").innerHTML = '<h3 class="share-h">Links</h3>' + links.map(function (l) {
      var live = l.status === "active";
      var meta = l.target === "__landscape__" ? "landscape" : esc(l.target);
      return '<div class="share-row ' + (live ? "" : "off") + '">'
        + '<div class="share-meta"><b>' + esc(l.title || meta) + '</b><span class="share-tag ' + esc(l.status) + '">' + esc(l.status) + '</span>'
        + '<div class="muted">' + meta + (live && !l.current ? " · model changed since shared" : "") + '</div></div>'
        + '<div class="share-btns">'
        + (live ? '<button type="button" class="mini" data-copy="' + esc(l.token) + '">Copy</button>'
                 + '<a class="mini" href="' + esc(portalUrl(l.token)) + '" target="_blank" rel="noopener">Open</a>'
                 + '<button type="button" class="mini danger" data-revoke="' + esc(l.token) + '">Revoke</button>' : "")
        + "</div></div>";
    }).join("");
    $("#share-list").querySelectorAll("[data-copy]").forEach(function (b) {
      b.addEventListener("click", function () {
        var url = portalUrl(b.getAttribute("data-copy"));
        var done = function () { b.textContent = "Copied ✓"; setTimeout(function () { b.textContent = "Copy"; }, 1500); };
        if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(url).then(done, done); else done();
      });
    });
    $("#share-list").querySelectorAll("[data-revoke]").forEach(function (b) {
      b.addEventListener("click", function () {
        postPortal({ op: "revoke", token: b.getAttribute("data-revoke") }).then(refreshShareList);
      });
    });
  });
}
(function () {
  var eb = $("#export-btn");
  if (eb) eb.addEventListener("click", function () {
    var p = getProc(); if (!p) { alert("Open a process first."); return; }
    window.open("/api/export/bpmn?process=" + encodeURIComponent(p.id), "_blank");
  });
})();

// ---------- Phase F: import BPMN ----------
function postImport(body) { return fetch("/api/import/bpmn", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).then(function (r) { return r.json(); }); }
(function () {
  var ib = $("#import-btn"); if (!ib) return;
  var modal = $("#import-modal"), out = $("#import-out"), apply = $("#import-apply");
  var vsdx = null;  // base64 of a loaded .vsdx (else we use the pasted/loaded XML)
  function reset() { $("#import-xml").value = ""; out.innerHTML = ""; apply.disabled = true; vsdx = null; }
  function open() { reset(); modal.hidden = false; }
  function close() { modal.hidden = true; }
  function payload() { return vsdx ? { format: "vsdx", data_b64: vsdx } : { xml: $("#import-xml").value.trim() }; }
  function haveInput() { return !!vsdx || !!$("#import-xml").value.trim(); }
  ib.addEventListener("click", open);
  $("#import-close").addEventListener("click", close);
  modal.addEventListener("click", function (e) { if (e.target === modal) close(); });
  $("#import-xml").addEventListener("input", function () { vsdx = null; });  // typing XML clears a loaded vsdx
  $("#import-file").addEventListener("change", function (e) {
    var f = e.target.files[0]; if (!f) return;
    apply.disabled = true;
    if (/\.vsdx?$/i.test(f.name)) {
      var rb = new FileReader();
      rb.onload = function () {
        var bytes = new Uint8Array(rb.result), bin = "";
        for (var i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
        vsdx = btoa(bin);
        $("#import-xml").value = "";
        out.innerHTML = '<div class="muted">Loaded Visio file <b>' + esc(f.name) + "</b> — press Preview.</div>";
      };
      rb.readAsArrayBuffer(f);
    } else {
      var rt = new FileReader();
      rt.onload = function () { vsdx = null; $("#import-xml").value = rt.result; out.innerHTML = '<div class="muted">Loaded ' + esc(f.name) + " — press Preview.</div>"; };
      rt.readAsText(f);
    }
  });
  $("#import-plan").addEventListener("click", function () {
    if (!haveInput()) { out.innerHTML = '<div class="msg err">Load a BPMN/Visio file, or paste BPMN XML, first.</div>'; return; }
    out.innerHTML = '<div class="muted">Reading…</div>';
    var body = payload(); body.op = "plan";
    postImport(body).then(function (res) {
      if (!res.ok) { out.innerHTML = '<div class="msg err">' + esc(res.error) + "</div>"; apply.disabled = true; return; }
      var c = res.plan.counts;
      var warns = res.plan.warnings.length ? '<div class="imp-warn"><b>' + res.plan.warnings.length + " note(s):</b><ul>"
        + res.plan.warnings.map(function (w) { return "<li>" + esc(w) + "</li>"; }).join("") + "</ul></div>" : "";
      out.innerHTML = '<div class="imp-plan"><div class="imp-name">' + esc(res.plan.name) + "</div>"
        + '<div class="imp-counts">' + c.steps + " steps (" + c.agent_steps + " agent) · " + c.gateways + " gateways · " + c.events + " events · " + c.flows + " flows</div>"
        + warns + "</div>";
      apply.disabled = false;
    });
  });
  apply.addEventListener("click", function () {
    if (!haveInput()) return;
    apply.disabled = true; out.innerHTML = '<div class="muted">Importing…</div>';
    var body = payload(); body.op = "apply"; body.actor = ACTOR; body.reason = "imported via canvas";
    postImport(body).then(function (res) {
      if (!res.ok) { out.innerHTML = '<div class="msg err">' + esc(res.error) + "</div>"; return; }
      var code = res.result.code;
      out.innerHTML = '<div class="msg ok">Imported as <b>' + esc(code) + "</b> — opening it…</div>";
      load().then(function () { close(); openProcess(code); });
    });
  });
})();
(function () {
  var sb = $("#share-btn"); if (!sb) return;
  sb.addEventListener("click", openShare);
  $("#share-close").addEventListener("click", closeShare);
  $("#share-modal").addEventListener("click", function (e) { if (e.target === this) closeShare(); });
  $("#share-proc").addEventListener("click", function () {
    var p = getProc(); if (!p) return;
    postPortal({ target: p.id, title: p.name, actor: ACTOR }).then(function (res) {
      if (res.ok) refreshShareList(); else alert("Could not publish: " + res.error);
    });
  });
  $("#share-land").addEventListener("click", function () {
    postPortal({ target: "__landscape__", title: "Process landscape", actor: ACTOR }).then(function (res) {
      if (res.ok) refreshShareList(); else alert("Could not publish: " + res.error);
    });
  });
})();

// ================= Roles: master data + click-through drawer =================
function postRole(body) { return fetch("/api/role", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).then(function (r) { return r.json(); }); }
function loadRoles(force) {
  if (state.roles && !force) return Promise.resolve(state.roles);
  return fetch("/api/roles").then(function (r) { return r.json(); }).then(function (d) { state.roles = d.roles || []; return state.roles; });
}
function roleById(id) { return (state.roles || []).find(function (x) { return x.id === id; }); }
function roleName(id) { var r = roleById(id); return r ? r.name : shortRole(id); }
// a clickable role reference — opens the drawer, never navigates
function roleLink(id, label) {
  if (!id) return "";
  if (String(id).indexOf("agent.") === 0) return '<span class="agentref">' + esc(label || shortRole(id)) + "</span>";
  return '<span class="rolelink" data-role="' + esc(id) + '" title="View role ' + esc(id) + '">' + esc(label || roleName(id)) + "</span>";
}

// delegated: any element carrying data-role opens the role drawer (works for the
// SVG flow node performer text, RACI cells, lane labels, props, landscape catalog)
document.addEventListener("click", function (e) {
  var el = e.target.closest ? e.target.closest("[data-role]") : null;
  if (el && el.getAttribute("data-role")) { e.stopPropagation(); openRoleDrawer(el.getAttribute("data-role")); }
}, true);

function openRoleDrawer(id) {
  state.roleEdit = false;
  loadRoles().then(function () { renderRoleDrawer(id); $("#role-drawer").hidden = false; });
}
function closeRoleDrawer() { $("#role-drawer").hidden = true; state.roleEdit = false; }

function usedByBlock(r) {
  function chips(ids, opener) {
    return ids.map(function (x) { return '<span class="usechip"' + (opener ? ' data-open="' + esc(opener(x)) + '"' : "") + ">" + esc(x) + "</span>"; }).join("");
  }
  var u = r.used_by, rows = [];
  if (u.owner.length) rows.push('<div class="dw-use"><div class="dw-lbl">Owns (process)</div><div>' + chips(u.owner, function (x) { return x; }) + "</div></div>");
  if (u.performer_processes.length) rows.push('<div class="dw-use"><div class="dw-lbl">Performs steps in</div><div>' + chips(u.performer_processes, function (x) { return x; }) + "</div></div>");
  if (u.escalation.length) rows.push('<div class="dw-use"><div class="dw-lbl">Escalation path for</div><div>' + chips(u.escalation, null) + "</div></div>");
  if (u.objectives.length) rows.push('<div class="dw-use"><div class="dw-lbl">Owns objective</div><div>' + chips(u.objectives, null) + "</div></div>");
  if (!rows.length) rows.push('<div class="muted" style="font-size:13px">Not referenced by any process yet.</div>');
  return rows.join("");
}
function raciChips(raci) {
  var map = [["responsible", "R"], ["accountable", "A"], ["consulted", "C"], ["informed", "I"]];
  return map.map(function (m) { return '<span class="raci-chip ' + (raci && raci[m[0]] ? "on" : "") + '">' + m[1] + "</span>"; }).join("");
}

function renderRoleDrawer(id) {
  var body = $("#role-drawer-body");
  if (String(id).indexOf("agent.") === 0) {
    body.innerHTML = '<div class="dw-top"><div><div class="dw-name">' + esc(shortRole(id)) + '</div><div class="dw-id">' + esc(id) + '</div></div>'
      + '<button class="x" id="dw-close" type="button">&times;</button></div>'
      + '<div class="muted" style="font-size:13px;margin-top:10px">This is an <b>agent</b>, not a human role — it runs the step automatically under a guardrail. Manage agent bindings from the step\'s properties panel.</div>';
    $("#dw-close").onclick = closeRoleDrawer; return;
  }
  var r = roleById(id);
  if (!r) {
    body.innerHTML = '<div class="dw-top"><div><div class="dw-name">' + esc(shortRole(id)) + '</div><div class="dw-id">' + esc(id) + '</div></div>'
      + '<button class="x" id="dw-close" type="button">&times;</button></div>'
      + '<div class="muted" style="font-size:13px;margin-top:10px">This role id isn\'t in the active master list (it may have been retired).</div>';
    $("#dw-close").onclick = closeRoleDrawer; return;
  }
  if (state.roleEdit) { renderRoleEdit(r); return; }
  body.innerHTML =
    '<div class="dw-top"><div><div class="dw-name">' + esc(r.name) + '</div><div class="dw-id">' + esc(r.id) + '</div></div>'
    + '<button class="x" id="dw-close" type="button">&times;</button></div>'
    + '<div class="dw-sec"><div class="dw-lbl">Standing RACI</div><div class="raci-row">' + raciChips(r.raci) + '</div></div>'
    + (r.skills && r.skills.length ? '<div class="dw-sec"><div class="dw-lbl">Skills</div><div>' + r.skills.map(function (s) { return '<span class="skilltag">' + esc(s) + "</span>"; }).join("") + "</div></div>" : "")
    + '<div class="dw-sec"><div class="dw-lbl">Used across the model</div>' + usedByBlock(r) + "</div>"
    + '<div class="dw-actions"><button class="add-btn" id="dw-edit" type="button">Edit</button>'
    + '<button class="add-btn ghost-btn danger" id="dw-remove" type="button"' + (r.in_use ? " disabled title=\"reassign its references first\"" : "") + ">Retire</button></div>";
  $("#dw-close").onclick = closeRoleDrawer;
  $("#dw-edit").onclick = function () { state.roleEdit = true; renderRoleDrawer(id); };
  var rm = $("#dw-remove");
  if (rm && !r.in_use) rm.onclick = function () {
    if (!confirm("Retire role " + r.id + "? (deprecated on the audit trail, not destroyed)")) return;
    postRole({ op: "remove", id: r.id, actor: ACTOR, reason: "retired role via drawer" }).then(function (res) {
      if (res.ok) { loadRoles(true).then(function () { closeRoleDrawer(); refreshRolesList(); }); } else alert("Rejected: " + res.error);
    });
  };
  body.querySelectorAll("[data-open]").forEach(function (c) { c.style.cursor = "pointer"; c.addEventListener("click", function () { closeRoleDrawer(); openProcess(c.getAttribute("data-open")); }); });
}

function renderRoleEdit(r) {
  var body = $("#role-drawer-body");
  var raci = r.raci || {};
  body.innerHTML =
    '<div class="dw-top"><div><div class="dw-name">Edit role</div><div class="dw-id">' + esc(r.id) + '</div></div>'
    + '<button class="x" id="dw-close" type="button">&times;</button></div>'
    + '<div class="dw-sec"><div class="dw-lbl">Display name</div><input id="dw-name" class="dw-input" value="' + esc(r.name) + '"></div>'
    + '<div class="dw-sec"><div class="dw-lbl">Skills (comma-separated)</div><input id="dw-skills" class="dw-input" value="' + esc((r.skills || []).join(", ")) + '"></div>'
    + '<div class="dw-sec"><div class="dw-lbl">Standing RACI</div><div class="raci-edit">'
    + ["responsible", "accountable", "consulted", "informed"].map(function (k) {
        return '<label><input type="checkbox" data-raci="' + k + '"' + (raci[k] ? " checked" : "") + "> " + k.charAt(0).toUpperCase() + k.slice(1) + "</label>";
      }).join("") + "</div></div>"
    + '<div id="dw-msg"></div>'
    + '<div class="dw-actions"><button class="add-btn" id="dw-save" type="button">Save new version</button>'
    + '<button class="add-btn ghost-btn" id="dw-cancel" type="button">Cancel</button></div>';
  $("#dw-close").onclick = closeRoleDrawer;
  $("#dw-cancel").onclick = function () { state.roleEdit = false; renderRoleDrawer(r.id); };
  $("#dw-save").onclick = function () {
    var raciObj = {};
    body.querySelectorAll("[data-raci]").forEach(function (c) { raciObj[c.getAttribute("data-raci")] = c.checked; });
    var changes = { name: $("#dw-name").value.trim(), skills: parseCsv($("#dw-skills").value), raci: raciObj };
    postRole({ op: "edit", id: r.id, changes: changes, actor: ACTOR, reason: "edited role via drawer" }).then(function (res) {
      if (!res.ok) { $("#dw-msg").innerHTML = '<div class="msg err">' + esc(res.error) + "</div>"; return; }
      state.roleEdit = false;
      loadRoles(true).then(function () { renderRoleDrawer(r.id); refreshRolesList(); load(); });
    });
  };
}

// ---- manage-roles modal ----
function refreshRolesList() {
  var host = $("#roles-list"); if (!host) return;
  loadRoles(true).then(function (roles) {
    if (!roles.length) { host.innerHTML = '<div class="muted">No roles yet.</div>'; return; }
    host.innerHTML = roles.map(function (r) {
      return '<div class="role-row" data-role="' + esc(r.id) + '">'
        + '<div class="role-main"><b>' + esc(r.name) + '</b><span class="role-id">' + esc(r.id) + '</span></div>'
        + '<div class="role-use">' + (r.in_use ? r.use_count + " use" + (r.use_count === 1 ? "" : "s") : '<span class="muted">unused</span>') + "</div></div>";
    }).join("");
  });
}
(function () {
  var rb = $("#roles-btn"); if (!rb) return;
  var modal = $("#roles-modal");
  rb.addEventListener("click", function () { modal.hidden = false; refreshRolesList(); });
  $("#roles-close").addEventListener("click", function () { modal.hidden = true; });
  modal.addEventListener("click", function (e) { if (e.target === modal) modal.hidden = true; });
  $("#role-add").addEventListener("submit", function (e) {
    e.preventDefault();
    var body = { op: "add", id: $("#role-add-id").value.trim(), name: $("#role-add-name").value.trim(),
                 skills: parseCsv($("#role-add-skills").value), actor: ACTOR, reason: "added role via manage panel" };
    postRole(body).then(function (res) {
      var m = $("#role-add-msg");
      if (!res.ok) { m.innerHTML = '<div class="msg err">' + esc(res.error) + "</div>"; return; }
      m.innerHTML = '<div class="msg ok">Added ' + esc(res.result.id) + "</div>";
      $("#role-add-id").value = ""; $("#role-add-name").value = ""; $("#role-add-skills").value = "";
      refreshRolesList(); load();
    });
  });
})();
