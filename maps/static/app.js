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
  else $("#canvas").innerHTML = renderFlow(p);
}

// ---------- flowchart (clickable SVG) ----------
var PAD = 16, R = 14, NW = 160, NH = 62, GAP = 46, LANE = 26;
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
function renderFlow(m) {
  var uid = m.id.replace(/[^A-Za-z0-9]/g, "_"), tasks = m.tasks;
  if (!tasks.length) return renderEmptyFlow(m);
  var hasEsc = tasks.some(function (t) { return t.agents.length && t.escalate_if; });
  var escY = LANE + NH + 54, H = hasEsc ? escY + 44 : LANE + NH + 18;
  var firstX = PAD + 2 * R + GAP, lastX = firstX + (tasks.length - 1) * (NW + GAP);
  var endCx = lastX + NW + GAP + R, W = endCx + R + PAD, cy = LANE + NH / 2, p = [];
  p.push('<svg viewBox="0 0 ' + W + ' ' + H + '" width="' + W + '" height="' + H + '" xmlns="http://www.w3.org/2000/svg">');
  p.push('<defs><marker id="ah_' + uid + '" markerWidth="7" markerHeight="7" refX="6" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6 z" class="arrow"/></marker>'
    + '<marker id="eh_' + uid + '" markerWidth="7" markerHeight="7" refX="3" refY="6" orient="auto"><path d="M0,0 L6,0 L3,6 z" class="esc-arrow"/></marker></defs>');
  p.push('<circle class="tip" cx="' + (PAD + R) + '" cy="' + cy + '" r="' + R + '"/><text class="tip" x="' + (PAD + R) + '" y="' + (cy + 3) + '" text-anchor="middle">start</text>');
  p.push('<line class="conn" x1="' + (PAD + 2 * R) + '" y1="' + cy + '" x2="' + firstX + '" y2="' + cy + '" marker-end="url(#ah_' + uid + ')"/>');
  tasks.forEach(function (t, i) {
    var x = firstX + i * (NW + GAP);
    var ncls = "node" + (t.agents.length ? " agent" : "") + (t.override ? " override" : "");
    p.push('<g class="tnode' + (t.id === state.task ? " sel" : "") + '" data-task="' + esc(t.id) + '">');
    p.push('<rect class="' + ncls + '" x="' + x + '" y="' + LANE + '" width="' + NW + '" height="' + NH + '" rx="9"/>');
    p.push('<text class="tseq" x="' + (x + 9) + '" y="' + (LANE + 15) + '">t' + t.seq + '</text>');
    if (t.agents.length) { p.push('<rect class="badge-bg" x="' + (x + NW - 26) + '" y="' + (LANE - 7) + '" width="24" height="15" rx="3.5"/><text class="badge" x="' + (x + NW - 14) + '" y="' + (LANE + 3.5) + '" text-anchor="middle">AI</text>'); }
    if (t.override) p.push('<text class="tag" x="' + (x + NW - 6) + '" y="' + (LANE - 4) + '" text-anchor="end">override</text>');
    var lines = wrap(t.name, 22), sy = lines.length === 2 ? LANE + 24 : LANE + 31;
    lines.forEach(function (ln, k) { p.push('<text class="tname" x="' + (x + 10) + '" y="' + (sy + k * 14) + '">' + esc(ln) + "</text>"); });
    var who = t.agents.length ? ((t.roles[0] ? lastSeg(t.roles[0]) + " + agent" : "agent")) : (t.roles[0] ? lastSeg(t.roles[0]) : "");
    p.push('<text class="tperf" x="' + (x + 10) + '" y="' + (LANE + NH - 9) + '">' + esc(trunc(who, 24)) + "</text>");
    p.push("</g>");
    var nextX = i < tasks.length - 1 ? firstX + (i + 1) * (NW + GAP) : endCx - R;
    p.push('<line class="conn" x1="' + (x + NW) + '" y1="' + cy + '" x2="' + nextX + '" y2="' + cy + '" marker-end="url(#ah_' + uid + ')"/>');
    if (t.agents.length && t.escalate_if) {
      var bx = x + NW / 2, pw = 172, px = Math.max(PAD, bx - pw / 2);
      p.push('<line class="esc-line" x1="' + bx + '" y1="' + (LANE + NH) + '" x2="' + bx + '" y2="' + escY + '" marker-end="url(#eh_' + uid + ')"/>');
      p.push('<rect class="esc" x="' + px + '" y="' + escY + '" width="' + pw + '" height="34" rx="7"/>');
      p.push('<text class="esc" x="' + (px + 10) + '" y="' + (escY + 14) + '">escalate → ' + esc(shortRole(t.escalation_path || "")) + "</text>");
      p.push('<text class="esc-cond" x="' + (px + 10) + '" y="' + (escY + 27) + '">if ' + esc(trunc(t.escalate_if, 26)) + "</text>");
    }
  });
  p.push('<circle class="tip" cx="' + endCx + '" cy="' + cy + '" r="' + R + '"/><text class="tip" x="' + endCx + '" y="' + (cy + 3) + '" text-anchor="middle">end</text>');
  p.push("</svg>");
  return p.join("");
}
$("#canvas").addEventListener("click", function (e) {
  var g = e.target.closest("g.tnode[data-task]"); if (!g) return;
  state.task = g.getAttribute("data-task");
  renderCenter(); renderProps();
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
