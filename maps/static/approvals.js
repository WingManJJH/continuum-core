"use strict";
// Approval-gate workflow — Phase 3. A change can be submitted for review instead
// of saved directly; it waits here until a reviewer approves (applies it through
// the audited store) or rejects it. Classic script after app.js; reuses esc/$.

var APPR_PROPOSER = (typeof ACTOR !== "undefined" && ACTOR) ? ACTOR : "role.ops.support_lead";
var APPR_REVIEWER = "role.qms.iso_advisor";  // separation of duties by default

function _apShort(r) { return String(r || "").replace(/^role\./, "").replace(/^agent\./, ""); }
function _apTs(ts) { try { return new Date(ts).toLocaleString(); } catch (e) { return ts || ""; } }

// Submit a change for approval (used by the guardrail editor's "Submit for
// approval" path and reusable for any gated op). Returns the fetch promise.
function proposeChange(targetOp, args, title, reason) {
  return fetch("/api/approvals", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ op: "propose", target_op: targetOp, args: args,
      title: title, actor: APPR_PROPOSER, reason: reason }),
  }).then(function (r) { return r.json(); }).then(function (res) {
    refreshApprovalsBadge();
    return res;
  });
}

function refreshApprovalsBadge() {
  var badge = document.getElementById("appr-badge");
  if (!badge) return Promise.resolve(0);
  return fetch("/api/approvals?status=pending").then(function (r) { return r.json(); }).then(function (d) {
    var n = d.pending || 0;
    badge.textContent = n;
    badge.hidden = n === 0;
    return n;
  }).catch(function () { return 0; });
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
    return '<div class="muted" style="padding:12px">' +
      (filter === "pending" ? "No changes are waiting for review." : "No change requests yet.") +
      " Changes can be submitted for approval from the guardrail editor (“Submit for approval”).</div>";
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
    var actions = "";
    if (cr.status === "pending") {
      actions = '<div class="appr-actions">'
        + '<button class="save appr-approve" data-id="' + esc(cr.id) + '">Approve</button>'
        + '<button class="ghost appr-reject" data-id="' + esc(cr.id) + '">Reject</button>'
        + '<button class="ghost appr-withdraw" data-id="' + esc(cr.id) + '">Withdraw</button></div>';
    }
    return '<div class="appr-card">'
      + '<div class="appr-top">' + badge + '<b>' + esc(cr.title || cr.op) + "</b> "
      + '<span class="appr-op">' + esc(cr.op) + "</span></div>"
      + '<div class="appr-arg">' + argPreview + "</div>"
      + '<div class="appr-meta">proposed by ' + esc(_apShort(cr.proposed_by)) + " · " + esc(_apTs(cr.proposed_at))
      + (cr.reason ? " — " + esc(cr.reason) : "") + "</div>"
      + _apDecision(cr)
      + actions + "</div>";
  }).join("");
}

var _apprFilter = "pending";
function openApprovals() {
  var modal = document.getElementById("appr-modal"), body = document.getElementById("appr-body");
  body.innerHTML = '<div class="muted">Loading…</div>';
  modal.hidden = false;
  loadApprovals();
}
function loadApprovals() {
  var body = document.getElementById("appr-body");
  var qs = _apprFilter === "pending" ? "?status=pending" : "";
  fetch("/api/approvals" + qs).then(function (r) { return r.json(); }).then(function (d) {
    body.innerHTML = renderApprovals(d.approvals || [], _apprFilter);
    body.querySelectorAll(".appr-approve").forEach(function (b) {
      b.addEventListener("click", function () { decide("approve", b.getAttribute("data-id")); });
    });
    body.querySelectorAll(".appr-reject").forEach(function (b) {
      b.addEventListener("click", function () { decide("reject", b.getAttribute("data-id")); });
    });
    body.querySelectorAll(".appr-withdraw").forEach(function (b) {
      b.addEventListener("click", function () { decide("withdraw", b.getAttribute("data-id")); });
    });
    refreshApprovalsBadge();
  });
}
function decide(op, id) {
  var payload = { op: op, id: id, actor: APPR_PROPOSER };
  if (op === "approve") { payload.reviewer = APPR_REVIEWER; payload.decision_reason = "approved via canvas"; }
  if (op === "reject") {
    var rr = prompt("Reason for rejecting this change?"); if (!rr) return;
    payload.reviewer = APPR_REVIEWER; payload.decision_reason = rr;
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
      loadApprovals();
    });
  });
  refreshApprovalsBadge();
})();
