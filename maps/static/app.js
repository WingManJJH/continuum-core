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

// ---------- load ----------
function load() {
  return fetch("/api/maps").then(function (r) { return r.json(); }).then(function (d) {
    state.procs = d.processes;
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
  state.sel = li.getAttribute("data-p"); state.task = null;
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

function renderCenter() {
  var p = getProc(); if (!p) return;
  if (state.view === "raci") $("#canvas").innerHTML = renderRaci(p);
  else if (state.view === "checklist") $("#canvas").innerHTML = renderChecklist(p);
  else { $("#canvas").innerHTML = renderFlow(p); if (p.tasks.length) wireFlow(p); }
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

function renderFlow(m) {
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
    p.push('<text class="tperf" x="10" y="' + (NH - 9) + '">' + esc(trunc(who, 24)) + "</text>");
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
      else { state.task = tid; renderCenter(); renderProps(); }
    });
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
    return '<tr><td class="role">' + esc(shortRole(r)) + "</td>" + cells + "</tr>";
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
document.querySelectorAll(".palette .tile").forEach(function (tile) {
  tile.addEventListener("dragstart", function (e) {
    e.dataTransfer.setData("text/plain", tile.getAttribute("data-name"));
    e.dataTransfer.effectAllowed = "copy";
  });
});
var canvas = $("#canvas");
canvas.addEventListener("dragover", function (e) { e.preventDefault(); e.dataTransfer.dropEffect = "copy"; canvas.classList.add("dropok"); });
canvas.addEventListener("dragleave", function () { canvas.classList.remove("dropok"); });
canvas.addEventListener("drop", function (e) {
  e.preventDefault(); canvas.classList.remove("dropok");
  var p = getProc(); if (!p) return;
  if (state.view !== "flow") { alert("Switch to the Flowchart view to drop a step."); return; }
  var name = e.dataTransfer.getData("text/plain") || "Step";
  postTask({ op: "add", process: p.id, name: name, after: dropAfter(e.clientX), actor: ACTOR, reason: "added step via palette" })
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
    + '<div class="p-sec"><div class="lbl">performed by</div><div class="p-row">' + esc(t.roles.map(shortRole).join(", ") || "—") + (t.agents.length ? ' <span class="pill gr">' + esc(t.agents.map(lastSeg).join(", ")) + " (agent)</span>" : "") + "</div></div>"
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
