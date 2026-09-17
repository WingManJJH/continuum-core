"use strict";
// Approval-gate workflow — Phase 3. A change can be submitted for review instead
// of saved directly; it waits here until a reviewer approves (applies it through
// the audited store) or rejects it. Classic script after app.js; reuses esc/$.

// Who is acting comes from the per-user identity (app.js ACTOR, reassigned live
// when the user changes identity). These read it at call time, never cached.
function apprActor() { return (typeof ACTOR !== "undefined" && ACTOR) ? ACTOR : "role.ops.support_lead"; }

function _apShort(r) { return String(r || "").replace(/^role\./, "").replace(/^agent\./, ""); }
function _apTs(ts) { try { return new Date(ts).toLocaleString(); } catch (e) { return ts || ""; } }

// Submit a change for approval (used by the guardrail editor's "Submit for
// approval" path and reusable for any gated op). Returns the fetch promise.
function proposeChange(targetOp, args, title, reason, assignee) {
  return fetch("/api/approvals", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ op: "propose", target_op: targetOp, args: args,
      title: title, actor: apprActor(), reason: reason,
      assignee: assignee || "" }),   // unassigned by default; route it in the queue
  }).then(function (r) { return r.json(); }).then(function (res) {
    refreshApprovalsBadge();
    return res;
  });
}

// roles (for the reassign picker), fetched lazily and cached
var _apprRoles = null;
function loadApprRoles() {
  if (_apprRoles) return Promise.resolve(_apprRoles);
  return fetch("/api/roles").then(function (r) { return r.json(); }).then(function (d) {
    _apprRoles = (d.roles || []).map(function (r) { return { id: r.id, name: r.name }; });
    return _apprRoles;
  }).catch(function () { _apprRoles = []; return _apprRoles; });
}

// ---- approval policy (which entity types need review) --------------------
var gatePolicy = null;  // { entityKey: "off"|"optional"|"required" }
function loadGatePolicy() {
  return fetch("/api/approval-policy").then(function (r) { return r.json(); }).then(function (d) {
    gatePolicy = {}; (d.entities || []).forEach(function (e) { gatePolicy[e.key] = e.mode; });
    return gatePolicy;
  }).catch(function () { return gatePolicy || {}; });
}
function gateModeFor(entity) { return (gatePolicy && gatePolicy[entity]) || "optional"; }

// The "Submit for approval" control for an editor form, driven by policy:
// off → nothing; optional → an unchecked checkbox; required → a locked notice.
function gateControlHTML(entity) {
  var mode = gateModeFor(entity);
  if (mode === "off") return "";
  if (mode === "required") {
    return '<div class="gate-required"><input type="checkbox" class="gate-ck" data-entity="' + esc(entity) + '" checked disabled>'
      + " This change <b>requires approval</b> — it will be submitted for review.</div>";
  }
  return '<label class="ck gate-optional"><input type="checkbox" class="gate-ck" data-entity="' + esc(entity) + '">'
    + ' Submit for approval instead of saving directly <span class="hint">routes through the review queue</span></label>';
}

// Decide the save path. Returns true if it routed the change through the gate
// (caller should stop); false to let the caller do its normal direct save.
function routeThroughGate(entity, containerEl, targetOp, args, title, reason, msgEl, onGated) {
  var mode = gateModeFor(entity);
  var ck = containerEl ? containerEl.querySelector(".gate-ck") : null;
  var wants = mode === "required" || (ck && ck.checked);
  if (!wants) return false;
  proposeChange(targetOp, args, title, reason).then(function (res) {
    if (msgEl) {
      msgEl.textContent = res.ok
        ? "Submitted for approval — it will go live once a reviewer approves it (see the Approvals queue)."
        : "Rejected: " + res.error;
      msgEl.className = "msg " + (res.ok ? "ok" : "err");
      msgEl.hidden = false;
    }
    refreshApprovalsBadge();
    if (onGated) onGated(res);
  });
  return true;
}

var _lastPending = null, _lastMine = 0, _titleBase = null;
function _setTitleBadge(n) {
  if (_titleBase == null) _titleBase = document.title;
  document.title = (n > 0 ? "(" + n + ") " : "") + _titleBase;
}
function refreshApprovalsBadge() {
  var badge = document.getElementById("appr-badge");
  if (!badge) return Promise.resolve(0);
  return fetch("/api/approvals?status=pending").then(function (r) { return r.json(); }).then(function (d) {
    var list = d.approvals || [], n = d.pending || 0;
    badge.textContent = n;
    badge.hidden = n === 0;
    _lastPending = n;
    _lastMine = list.filter(function (c) { return c.assignee === apprActor(); }).length;
    _setTitleBadge(n);
    return n;
  }).catch(function () { return 0; });
}

// ---- live handlers (typed SSE events) ------------------------------------
function apprToast(msg) {
  var t = document.getElementById("appr-toast");
  if (!t) { t = document.createElement("div"); t.id = "appr-toast"; t.className = "appr-toast"; document.body.appendChild(t); }
  t.innerHTML = '<b>Approvals</b> ' + esc(msg) + ' <button type="button" id="appr-toast-open">Review</button>';
  t.classList.add("show");
  var open = document.getElementById("appr-toast-open");
  if (open) open.onclick = function () { t.classList.remove("show"); openApprovals(); };
  clearTimeout(apprToast._t);
  apprToast._t = setTimeout(function () { t.classList.remove("show"); }, 6000);
}
function onApprovalsChanged() {
  var prev = _lastPending, prevMine = _lastMine;
  refreshApprovalsBadge().then(function (n) {
    if (prev != null && n > prev) {
      var mineUp = _lastMine > prevMine;
      var msg = mineUp ? (_lastMine === 1 ? "A change is assigned to you." : _lastMine + " changes are assigned to you.")
                       : (n === 1 ? "A change is awaiting review." : n + " changes are awaiting review.");
      apprToast(msg);
      if (typeof notifyDesktop === "function") notifyDesktop("Continuum · Approvals", msg);
    }
  });
  var modal = document.getElementById("appr-modal");
  if (modal && !modal.hidden && _apprFilter !== "policy") loadApprovals();
}
function onPolicyChanged() {
  loadGatePolicy().then(function () {
    // re-render an open editor so its gate control reflects the new policy
    if (typeof renderProps === "function" && document.getElementById("gr-form")) renderProps();
    var modal = document.getElementById("appr-modal");
    if (modal && !modal.hidden && _apprFilter === "policy") renderPolicy();
  });
}

function _apDecision(cr) {
  var d = cr.decision; if (!d) return "";
  var who = _apShort(d.by), when = _apTs(d.at);
  var self = d.self_approved ? ' <span class="pill warn" title="reviewer was also the proposer">self-approved</span>' : "";
  var applied = d.applied && d.applied.version ? " → v" + d.applied.version : (d.applied && d.applied.id ? " → " + esc(d.applied.id) : "");
  return '<div class="appr-dec">' + esc(cr.status) + " by " + esc(who) + self + applied
    + '<div class="appr-meta">' + esc(when) + (d.reason ? " — " + esc(d.reason) : "") + "</div></div>";
}

function renderApprovals(list, filter) {
  if (!list.length) {
    var m = filter === "mine" ? "Nothing is assigned to you right now."
          : filter === "pending" ? "No changes are waiting for review." : "No change requests yet.";
    return '<div class="muted" style="padding:12px">' + m +
      " Changes can be submitted from the guardrail, role, master-data, and strategy editors (“Submit for approval”).</div>";
  }
  return list.map(function (cr) {
    var badge = '<span class="appr-st st-' + esc(cr.status) + '">' + esc(cr.status) + "</span>";
    var argPreview = "";
    try {
      var a = cr.args || {};
      var t = a.gr_id || a.task_id || a.id || cr.target || a.process_ref || "";
      var ch = a.changes ? Object.keys(a.changes).join(", ") : "";
      argPreview = (t ? "<code>" + esc(t) + "</code>" : "") + (ch ? ' <span class="muted">— ' + esc(ch) + "</span>" : "");
    } catch (e) { argPreview = ""; }
    var actions = "", assignRow = "";
    if (cr.status === "pending") {
      var roleList = (_apprRoles || []).slice();
      // keep the current assignee selectable even if it isn't a HumanRole (e.g. a
      // governance/reviewer role that lives outside the roles master list)
      if (cr.assignee && !roleList.some(function (r) { return r.id === cr.assignee; })) {
        roleList.unshift({ id: cr.assignee, name: _apShort(cr.assignee) });
      }
      var opts = '<option value="">— unassigned —</option>' + roleList.map(function (r) {
        return '<option value="' + esc(r.id) + '"' + (r.id === cr.assignee ? " selected" : "") + ">" + esc(r.name) + "</option>";
      }).join("");
      var mine = cr.assignee === apprActor();
      assignRow = '<div class="appr-assign"><span class="muted">Assigned to</span>'
        + '<select class="appr-assignee" data-id="' + esc(cr.id) + '">' + opts + "</select>"
        + (mine ? '<span class="appr-mine-tag">you</span>'
                : '<button class="mini appr-mine" data-id="' + esc(cr.id) + '">Assign to me</button>') + "</div>";
      actions = '<div class="appr-actions">'
        + '<button class="save appr-approve" data-id="' + esc(cr.id) + '">Approve</button>'
        + '<button class="ghost appr-reject" data-id="' + esc(cr.id) + '">Reject</button>'
        + '<button class="ghost appr-withdraw" data-id="' + esc(cr.id) + '">Withdraw</button></div>';
    } else if (cr.assignee) {
      assignRow = '<div class="appr-meta">was assigned to ' + esc(_apShort(cr.assignee)) + "</div>";
    }
    return '<div class="appr-card">'
      + '<div class="appr-top">' + badge + '<b>' + esc(cr.title || cr.op) + "</b> "
      + '<span class="appr-op">' + esc(cr.op) + "</span></div>"
      + '<div class="appr-arg">' + argPreview + "</div>"
      + '<div class="appr-meta">proposed by ' + esc(_apShort(cr.proposed_by)) + " · " + esc(_apTs(cr.proposed_at))
      + (cr.reason ? " — " + esc(cr.reason) : "") + "</div>"
      + assignRow
      + _apDecision(cr)
      + actions + "</div>";
  }).join("");
}

var _apprFilter = "pending";
function openApprovals() {
  var modal = document.getElementById("appr-modal"), body = document.getElementById("appr-body");
  _apprFilter = "pending";
  document.querySelectorAll(".appr-tabs button").forEach(function (x) { x.classList.toggle("active", x.getAttribute("data-af") === "pending"); });
  body.innerHTML = '<div class="muted">Loading…</div>';
  modal.hidden = false;
  loadApprovals();
}
function loadApprovals() {
  var body = document.getElementById("appr-body");
  // "mine" = pending requests assigned to my identity; others use the server filter
  var qs = (_apprFilter === "pending" || _apprFilter === "mine") ? "?status=pending" : "";
  Promise.all([
    fetch("/api/approvals" + qs).then(function (r) { return r.json(); }),
    loadApprRoles(),
  ]).then(function (parts) {
    var d = parts[0];
    var list = d.approvals || [];
    if (_apprFilter === "mine") list = list.filter(function (c) { return c.assignee === apprActor(); });
    body.innerHTML = renderApprovals(list, _apprFilter);
    body.querySelectorAll(".appr-approve").forEach(function (b) {
      b.addEventListener("click", function () { decide("approve", b.getAttribute("data-id")); });
    });
    body.querySelectorAll(".appr-reject").forEach(function (b) {
      b.addEventListener("click", function () { decide("reject", b.getAttribute("data-id")); });
    });
    body.querySelectorAll(".appr-withdraw").forEach(function (b) {
      b.addEventListener("click", function () { decide("withdraw", b.getAttribute("data-id")); });
    });
    body.querySelectorAll(".appr-assignee").forEach(function (sel) {
      sel.addEventListener("change", function () { reassign(sel.getAttribute("data-id"), sel.value); });
    });
    body.querySelectorAll(".appr-mine").forEach(function (b) {
      b.addEventListener("click", function () { reassign(b.getAttribute("data-id"), apprActor(), true); });
    });
    refreshApprovalsBadge();
  });
}
function reassign(id, assignee, reload) {
  fetch("/api/approvals", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ op: "assign", id: id, assignee: assignee, actor: apprActor(), reason: "reassigned via queue" }),
  }).then(function (r) { return r.json(); }).then(function (res) {
    if (!res.ok) { alert("Could not reassign: " + res.error); return; }
    if (reload) loadApprovals();
  });
}
function decide(op, id) {
  var payload = { op: op, id: id, actor: apprActor() };
  if (op === "approve") { payload.reviewer = apprActor(); payload.decision_reason = "approved via canvas"; }
  if (op === "reject") {
    var rr = prompt("Reason for rejecting this change?"); if (!rr) return;
    payload.reviewer = apprActor(); payload.decision_reason = rr;
  }
  if (op === "withdraw") {
    if (!confirm("Withdraw this change request?")) return;
    payload.decision_reason = "withdrawn by proposer";
  }
  fetch("/api/approvals", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  }).then(function (r) { return r.json(); }).then(function (res) {
    if (!res.ok) { alert("Could not " + op + ": " + res.error); }
    loadApprovals();
    if (typeof load === "function") load();  // an approved edit changed the model
  });
}

// ---- policy settings tab -------------------------------------------------
function renderPolicy() {
  var body = document.getElementById("appr-body");
  body.innerHTML = '<div class="muted">Loading…</div>';
  fetch("/api/approval-policy").then(function (r) { return r.json(); }).then(function (d) {
    var modes = d.modes || ["off", "optional", "required"];
    gatePolicy = {}; (d.entities || []).forEach(function (e) { gatePolicy[e.key] = e.mode; });
    var rows = (d.entities || []).map(function (e) {
      var opts = modes.map(function (m) { return '<option value="' + m + '"' + (m === e.mode ? " selected" : "") + ">" + m + "</option>"; }).join("");
      return '<div class="pol-row"><div class="pol-label">' + esc(e.label) + "</div>"
        + '<select class="pol-mode" data-entity="' + esc(e.key) + '">' + opts + "</select></div>";
    }).join("");
    body.innerHTML = '<p class="modal-sub">Which <b>kinds</b> of change must go through review. '
      + "<b>required</b> — a direct edit is refused, the change must be submitted; "
      + "<b>optional</b> — the editor offers a “Submit for approval” choice; "
      + "<b>off</b> — commits directly. Each change is itself governed (who / when / why).</p>"
      + '<div class="pol-grid">' + rows + "</div>"
      + '<div id="pol-msg" class="msg" hidden></div>';
    body.querySelectorAll(".pol-mode").forEach(function (sel) {
      sel.addEventListener("change", function () { setPolicy(sel.getAttribute("data-entity"), sel.value); });
    });
  });
}
function setPolicy(entity, mode) {
  fetch("/api/approval-policy", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ entity: entity, mode: mode, actor: apprActor(), reason: "set approval policy for " + entity }),
  }).then(function (r) { return r.json(); }).then(function (res) {
    var m = document.getElementById("pol-msg");
    if (res.ok) { if (gatePolicy) gatePolicy[entity] = mode; if (m) { m.textContent = entity + " → " + mode + ". Saved."; m.className = "msg ok"; m.hidden = false; } }
    else if (m) { m.textContent = "Rejected: " + res.error; m.className = "msg err"; m.hidden = false; }
  });
}

(function () {
  var ab = document.getElementById("approvals-btn"); if (!ab) return;
  ab.addEventListener("click", openApprovals);
  var close = document.getElementById("appr-close");
  if (close) close.addEventListener("click", function () { document.getElementById("appr-modal").hidden = true; });
  var modal = document.getElementById("appr-modal");
  if (modal) modal.addEventListener("click", function (e) { if (e.target === this) this.hidden = true; });
  document.querySelectorAll(".appr-tabs button").forEach(function (b) {
    b.addEventListener("click", function () {
      _apprFilter = b.getAttribute("data-af");
      document.querySelectorAll(".appr-tabs button").forEach(function (x) { x.classList.toggle("active", x === b); });
      if (_apprFilter === "policy") renderPolicy(); else loadApprovals();
    });
  });
  loadGatePolicy();
  refreshApprovalsBadge();
})();
