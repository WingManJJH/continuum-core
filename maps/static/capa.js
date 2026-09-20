"use strict";
// CAPA — corrective / preventive action register (ISO 9001 §10.2). A reported
// error becomes a CAR: an owned, dated record that moves through a lifecycle,
// flags the processes it affects, notifies owners, and feeds the AI insights.
// Classic script after app.js; reuses esc / ACTOR / state.

function capaActor() { return (typeof ACTOR !== "undefined" && ACTOR) ? ACTOR : "role.ops.support_lead"; }
function _caShort(r) { return String(r || "").replace(/^role\./, ""); }
function _caDate(d) { return d || "—"; }

// mirror of governance/capa.py TRANSITIONS — which states a CAR may move to next
var CAR_NEXT = {
  open: ["investigating", "cancelled"],
  investigating: ["action_planned", "open", "cancelled"],
  action_planned: ["implemented", "investigating", "cancelled"],
  implemented: ["verifying", "action_planned", "cancelled"],
  verifying: ["closed", "action_planned", "cancelled"],
  closed: ["investigating"],
  cancelled: [],
};
var CAR_SOURCES = ["internal_audit", "external_audit", "customer_complaint", "kpi_breach",
  "agent_escalation", "incident", "near_miss", "management_review", "supplier", "other"];
var CAR_SEV = ["minor", "major", "critical"];
var STATE_LABEL = { open: "open", investigating: "investigating", action_planned: "action planned",
  implemented: "implemented", verifying: "verifying", closed: "closed", cancelled: "cancelled" };

var _capaData = null;   // last /api/capa payload (register + summary + insights + notifications)

// ---- badge + live refresh ------------------------------------------------
function refreshCapaBadge() {
  var badge = document.getElementById("capa-badge");
  return fetch("/api/capa").then(function (r) { return r.json(); }).then(function (d) {
    _capaData = d;
    var open = (d.summary && d.summary.open) || 0, overdue = (d.summary && d.summary.overdue) || 0;
    if (badge) {
      badge.textContent = open;
      badge.hidden = open === 0;
      badge.classList.toggle("overdue", overdue > 0);   // red when something is past due
      badge.title = open + " open corrective action(s)" + (overdue ? ", " + overdue + " overdue" : "");
    }
    return d;
  }).catch(function () { return null; });
}
// called from app.js on a "changed" SSE event (CAR writes land in the edits log)
function onCapaChanged() {
  refreshCapaBadge().then(function () {
    var modal = document.getElementById("capa-modal");
    if (modal && !modal.hidden) loadCapa();
  });
}

// ---- open / render -------------------------------------------------------
var _capaFilter = "open";
function openCapa() {
  var modal = document.getElementById("capa-modal");
  _capaFilter = "open";
  document.querySelectorAll(".capa-tabs button").forEach(function (x) { x.classList.toggle("active", x.getAttribute("data-cf") === "open"); });
  modal.hidden = false;
  loadCapa();
}
function loadCapa() {
  var body = document.getElementById("capa-body");
  body.innerHTML = '<div class="muted" style="padding:12px">Loading…</div>';
  Promise.all([
    fetch("/api/capa").then(function (r) { return r.json(); }),
    (typeof loadApprRoles === "function" ? loadApprRoles() : Promise.resolve([])),
  ]).then(function (parts) {
    _capaData = parts[0];
    renderSummary();
    if (_capaFilter === "insights") { renderCapaInsights(); return; }
    var list = (_capaData.register || []).slice();
    if (_capaFilter === "open") list = list.filter(function (c) { return !c.closed; });
    else if (_capaFilter === "mine") list = list.filter(function (c) { return c.owner_role === capaActor(); });
    body.innerHTML = renderCapaList(list, _capaFilter);
    wireCapaCards();
  });
}
function renderSummary() {
  var el = document.getElementById("capa-summary"); if (!el || !_capaData) return;
  var s = _capaData.summary || {};
  el.innerHTML = '<span class="pill">' + (s.open || 0) + " open</span>"
    + (s.overdue ? '<span class="pill risk">' + s.overdue + " overdue</span>" : "")
    + (s.critical_open ? '<span class="pill risk">' + s.critical_open + " critical</span>" : "")
    + '<span class="muted">' + (s.total || 0) + " total</span>";
}

function _sevPill(sev) { return '<span class="capa-sev sev-' + esc(sev) + '">' + esc(sev) + "</span>"; }
function _statePill(st) { return '<span class="capa-state cst-' + esc(st) + '">' + esc(STATE_LABEL[st] || st) + "</span>"; }

function renderCapaList(list, filter) {
  if (!list.length) {
    var m = filter === "mine" ? "No corrective actions are owned by you."
          : filter === "open" ? "No open corrective actions. Raise one when an error is reported."
          : "No corrective actions yet.";
    return '<div class="muted" style="padding:12px">' + m + "</div>";
  }
  return list.map(renderCapaCard).join("");
}
function renderCapaCard(c) {
  var affected = (c.affected || []).map(function (a) {
    return '<span class="mdchip capa-proc" data-proc="' + esc(a.id) + '" title="' + esc(a.name) + '">⚑ ' + esc(a.id) + "</span>";
  }).join("");
  var overdue = c.overdue ? '<span class="capa-overdue">overdue</span>' : "";
  var due = c.date_due ? ("due " + esc(c.date_due) + (c.overdue ? "" : (c.days_to_due != null ? " (" + c.days_to_due + "d)" : ""))) : "no due date";
  var next = (CAR_NEXT[c.state] || []).map(function (ns) {
    return '<button class="mini capa-move" data-id="' + esc(c.id) + '" data-to="' + esc(ns) + '">→ ' + esc(STATE_LABEL[ns] || ns) + "</button>";
  }).join("");
  function field(lbl, val, key, edit) {
    var show = val ? '<div class="capa-fv">' + esc(val) + "</div>" : '<div class="capa-fv muted">—</div>';
    return '<div class="capa-field"><div class="capa-fl">' + esc(lbl) + "</div>" + show
      + (edit ? '<textarea class="capa-edit" data-id="' + esc(c.id) + '" data-k="' + key + '" rows="2" placeholder="' + esc(lbl) + '…">' + esc(val || "") + "</textarea>" : "") + "</div>";
  }
  var detail = '<div class="capa-detail" data-id="' + esc(c.id) + '" hidden>'
    + field("Nonconformity (what went wrong)", c.nonconformance, "nonconformance", true)
    + field("Containment (immediate correction)", c.containment, "containment", true)
    + field("Root cause", c.root_cause, "root_cause", true)
    + field("Corrective action (fix the cause)", c.corrective_action, "corrective_action", true)
    + field("Preventive action (stop recurrence)", c.preventive_action, "preventive_action", true)
    + field("Effectiveness check (verify it worked)", c.effectiveness_check, "effectiveness_check", true)
    + '<div class="capa-editrow"><label>Owner <input class="capa-eo" data-id="' + esc(c.id) + '" value="' + esc(c.owner_role) + '"></label>'
    + '<label>Severity <select class="capa-es" data-id="' + esc(c.id) + '">' + CAR_SEV.map(function (s) { return '<option ' + (s === c.severity ? "selected" : "") + ">" + s + "</option>"; }).join("") + "</select></label>"
    + '<label>Due <input type="date" class="capa-ed" data-id="' + esc(c.id) + '" value="' + esc(c.date_due || "") + '"></label></div>'
    + '<div class="capa-lifecycle"><span class="muted">move to:</span> ' + (next || '<span class="muted">— terminal —</span>') + "</div>"
    + '<div class="capa-cardactions"><button class="save capa-save" data-id="' + esc(c.id) + '">Save changes</button>'
    + '<span class="capa-msg" data-id="' + esc(c.id) + '"></span></div></div>';
  return '<div class="capa-cardw">'
    + '<div class="capa-top" data-toggle="' + esc(c.id) + '">' + _sevPill(c.severity) + " " + _statePill(c.state) + overdue
    + ' <code>' + esc(c.id) + "</code> <b>" + esc(c.title) + "</b></div>"
    + '<div class="capa-meta">owner <b>' + esc(_caShort(c.owner_role)) + "</b> · " + esc(c.source.replace(/_/g, " "))
    + " · raised " + esc(c.date_raised) + " · " + due + (c.age_days != null ? " · " + c.age_days + "d old" : "") + "</div>"
    + (affected ? '<div class="capa-affected">' + affected + "</div>" : "")
    + detail + "</div>";
}
function wireCapaCards() {
  var body = document.getElementById("capa-body");
  body.querySelectorAll(".capa-top[data-toggle]").forEach(function (el) {
    el.addEventListener("click", function () {
      var d = body.querySelector('.capa-detail[data-id="' + CSS.escape(el.getAttribute("data-toggle")) + '"]');
      if (d) d.hidden = !d.hidden;
    });
  });
  body.querySelectorAll(".capa-save").forEach(function (b) {
    b.addEventListener("click", function () { saveCar(b.getAttribute("data-id")); });
  });
  body.querySelectorAll(".capa-move").forEach(function (b) {
    b.addEventListener("click", function () { moveCar(b.getAttribute("data-id"), b.getAttribute("data-to")); });
  });
  body.querySelectorAll(".capa-proc").forEach(function (b) {
    b.addEventListener("click", function () {
      document.getElementById("capa-modal").hidden = true;
      if (typeof openProcess === "function") openProcess(b.getAttribute("data-proc"));
    });
  });
}
function _carEdits(id) {
  var body = document.getElementById("capa-body"), changes = {};
  body.querySelectorAll('.capa-edit[data-id="' + CSS.escape(id) + '"]').forEach(function (t) { changes[t.getAttribute("data-k")] = t.value; });
  var o = body.querySelector('.capa-eo[data-id="' + CSS.escape(id) + '"]'); if (o) changes.owner_role = o.value.trim();
  var s = body.querySelector('.capa-es[data-id="' + CSS.escape(id) + '"]'); if (s) changes.severity = s.value;
  var d = body.querySelector('.capa-ed[data-id="' + CSS.escape(id) + '"]'); if (d) changes.date_due = d.value || null;
  return changes;
}
function _carMsg(id, txt, cls) {
  var m = document.querySelector('.capa-msg[data-id="' + CSS.escape(id) + '"]');
  if (m) { m.textContent = txt; m.className = "capa-msg " + (cls || ""); }
}
function saveCar(id) {
  var reason = prompt("Reason for this change? (recorded on the §7.5 trail)");
  if (!reason) return;
  fetch("/api/capa", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ op: "edit", id: id, changes: _carEdits(id), actor: capaActor(), reason: reason }) })
    .then(function (r) { return r.json(); }).then(function (res) {
      if (!res.ok) { _carMsg(id, "Rejected: " + res.error, "err"); return; }
      _carMsg(id, "Saved v" + res.car.version + ".", "ok");
      loadCapa(); if (typeof load === "function") load();
    });
}
function moveCar(id, to) {
  var reason = prompt("Move this CAR to “" + (STATE_LABEL[to] || to) + "” — reason?");
  if (!reason) return;
  fetch("/api/capa", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ op: "transition", id: id, to_state: to, actor: capaActor(), reason: reason }) })
    .then(function (r) { return r.json(); }).then(function (res) {
      if (!res.ok) { _carMsg(id, "Rejected: " + res.error, "err"); return; }
      loadCapa(); if (typeof load === "function") load();
    });
}

// ---- AI insights tab -----------------------------------------------------
function renderCapaInsights() {
  var body = document.getElementById("capa-body");
  var ins = (_capaData && _capaData.insights) || [], notif = (_capaData && _capaData.notifications) || {};
  var insHtml = ins.length ? ins.map(function (f) {
    return '<div class="capa-insight sev-' + esc(f.severity) + '"><div class="capa-ih">' + esc(f.title) + "</div>"
      + '<div class="capa-id">' + esc(f.detail) + "</div>"
      + (f.recommendation ? '<div class="capa-ir">→ ' + esc(f.recommendation) + "</div>" : "") + "</div>";
  }).join("") : '<div class="muted" style="padding:12px">No corrective-action findings — nothing overdue, critical, or clustering.</div>';
  var roles = (notif.by_role && Object.keys(notif.by_role)) || [];
  var notifHtml = roles.length ? roles.map(function (r) {
    var items = notif.by_role[r];
    return '<div class="capa-notif"><b>' + esc(_caShort(r)) + "</b> <span class=\"muted\">" + items.length + " item(s)</span>"
      + items.map(function (i) {
        return '<div class="capa-nrow">' + (i.overdue ? '<span class="capa-overdue">overdue</span> ' : "")
          + '<code>' + esc(i.car_id) + "</code> " + esc(i.title)
          + ' <span class="muted">(' + (i.kind === "owner" ? "you own this" : "affects " + esc(i.process)) + ")</span></div>";
      }).join("") + "</div>";
  }).join("") : '<div class="muted" style="padding:12px">No owners to notify — no open corrective actions.</div>';
  body.innerHTML = '<div class="capa-section-h">Insights <span class="muted">— deterministic ISO 9001 §10.2 findings, also shown in the AI advisor</span></div>'
    + insHtml
    + '<div class="capa-section-h">Owners to notify</div>' + notifHtml;
}

// ---- raise a CAR ---------------------------------------------------------
function raiseForm(prefillProc) {
  var procOpts = ((typeof state !== "undefined" && state.procs) || []).map(function (p) {
    return '<option value="' + esc(p.id) + '"' + (p.id === prefillProc ? " selected" : "") + ">" + esc(p.id) + " — " + esc(p.name) + "</option>";
  }).join("");
  var roleOpts = (_apprRoles || []).map(function (r) { return '<option value="' + esc(r.id) + '">' + esc(r.name) + "</option>"; }).join("");
  return '<form id="capa-form" class="capa-form">'
    + '<div class="capa-formh">Raise a corrective action</div>'
    + '<label>Title<input id="cf-title" required placeholder="Short problem summary"></label>'
    + '<label>What went wrong (nonconformity)<textarea id="cf-nc" rows="3" required placeholder="Describe the reported error"></textarea></label>'
    + '<div class="capa-formrow">'
    + '<label>Source<select id="cf-source">' + CAR_SOURCES.map(function (s) { return "<option>" + s + "</option>"; }).join("") + "</select></label>"
    + '<label>Severity<select id="cf-sev">' + CAR_SEV.map(function (s) { return "<option" + (s === "major" ? " selected" : "") + ">" + s + "</option>"; }).join("") + "</select></label>"
    + '<label>Due date<input type="date" id="cf-due"></label></div>'
    + '<label>Accountable owner (role)<select id="cf-owner" required>' + roleOpts + "</select></label>"
    + '<label>Affected processes <span class="hint">the CAR flags these on the canvas</span>'
    + '<select id="cf-affected" multiple size="4">' + procOpts + "</select></label>"
    + '<label>Containment (immediate correction, optional)<textarea id="cf-cont" rows="2"></textarea></label>'
    + '<label>Reason for the record <span class="hint">required · §7.5</span><input id="cf-reason" placeholder="why raise this now?" required></label>'
    + '<div id="cf-msg" class="msg" hidden></div>'
    + '<div class="actions"><button type="button" id="cf-cancel" class="ghost">Cancel</button><button type="submit" class="save">Raise CAR</button></div>'
    + "</form>";
}
function openRaise(prefillProc) {
  (typeof loadApprRoles === "function" ? loadApprRoles() : Promise.resolve([])).then(function () {
    var body = document.getElementById("capa-body");
    body.innerHTML = raiseForm(prefillProc);
    document.getElementById("cf-cancel").addEventListener("click", loadCapa);
    document.getElementById("capa-form").addEventListener("submit", submitRaise);
  });
}
function submitRaise(e) {
  e.preventDefault();
  var affected = Array.prototype.map.call(document.getElementById("cf-affected").selectedOptions, function (o) { return o.value; });
  var payload = {
    op: "raise", title: $("#cf-title").value, nonconformance: $("#cf-nc").value,
    source: $("#cf-source").value, severity: $("#cf-sev").value, owner_role: $("#cf-owner").value,
    affected_process_refs: affected, date_due: $("#cf-due").value || null,
    containment: $("#cf-cont").value, actor: capaActor(), reason: $("#cf-reason").value,
  };
  var msg = document.getElementById("cf-msg"), btn = document.querySelector("#capa-form .save");
  btn.disabled = true;
  fetch("/api/capa", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) })
    .then(function (r) { return r.json(); }).then(function (res) {
      btn.disabled = false;
      if (!res.ok) { msg.textContent = "Rejected: " + res.error; msg.className = "msg err"; msg.hidden = false; return; }
      _capaFilter = "open";
      document.querySelectorAll(".capa-tabs button").forEach(function (x) { x.classList.toggle("active", x.getAttribute("data-cf") === "open"); });
      loadCapa();
      if (typeof load === "function") load();   // the new flag shows on the canvas
    });
}
// entry point used from the process properties panel
function raiseCarFor(procId) {
  document.getElementById("capa-modal").hidden = false;
  refreshCapaBadge();
  openRaise(procId);
}

// ---- wiring --------------------------------------------------------------
(function () {
  var btn = document.getElementById("capa-btn"); if (!btn) return;
  btn.addEventListener("click", openCapa);
  var close = document.getElementById("capa-close");
  if (close) close.addEventListener("click", function () { document.getElementById("capa-modal").hidden = true; });
  var modal = document.getElementById("capa-modal");
  if (modal) modal.addEventListener("click", function (e) { if (e.target === this) this.hidden = true; });
  var neu = document.getElementById("capa-new");
  if (neu) neu.addEventListener("click", function () { openRaise(null); });
  document.querySelectorAll(".capa-tabs button").forEach(function (b) {
    b.addEventListener("click", function () {
      _capaFilter = b.getAttribute("data-cf");
      document.querySelectorAll(".capa-tabs button").forEach(function (x) { x.classList.toggle("active", x === b); });
      loadCapa();
    });
  });
  refreshCapaBadge();
})();
