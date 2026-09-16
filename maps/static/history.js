"use strict";
// Version history & compare — reads the audit trail (who / when / why + field diffs).
// Classic script after app.js. Read-only.

function _fmtTs(ts) { try { return new Date(ts).toLocaleString(); } catch (e) { return ts || ""; } }
function _short(r) { return String(r || "").replace(/^role\./, "").replace(/^agent\./, ""); }
function _val(v) {
  if (v == null) return '<span class="muted">∅</span>';
  if (typeof v === "object") return "<code>" + esc(JSON.stringify(v)) + "</code>";
  return "<code>" + esc(String(v)) + "</code>";
}

function renderChanges(C) {
  var types = Object.keys(C.by_type).sort();
  var summary = types.map(function (t) {
    var s = C.by_type[t];
    return '<span class="hsum">' + esc(t) + ' <b>' + s.entities + "</b> · +" + s.created + " ~" + s.updated + " −" + s.deprecated + "</span>";
  }).join("");
  var rows = C.recent.map(function (e) {
    return '<div class="hrow" data-type="' + esc(e.entity_type) + '" data-id="' + esc(e.entity_id) + '">'
      + '<div class="hop op-' + esc(e.op) + '">' + esc(e.op) + "</div>"
      + '<div class="hmain"><b>' + esc(e.entity_type) + "</b> " + esc(e.entity_id) + ' <span class="hver">v' + esc(String(e.version || "")) + "</span>"
      + '<div class="hmeta">' + esc(_short(e.actor)) + " · " + esc(_fmtTs(e.ts)) + " — " + esc(e.reason || "") + "</div></div>"
      + '<div class="hgo">›</div></div>';
  }).join("");
  return '<p class="modal-sub">Every governed change, versioned and hash-chained — who, when, and why. '
    + '<span class="' + (C.chain_intact ? "pill good" : "pill crit") + '">' + (C.chain_intact ? "audit chain intact" : "TAMPERED") + "</span> · "
    + "<b>" + C.total_changes + "</b> changes since the seed baseline.</p>"
    + '<div class="hsummary">' + summary + "</div>"
    + '<div class="hlist">' + (rows || '<div class="muted">No changes yet — the model is at its seed baseline.</div>') + "</div>";
}

function renderEntityHistory(H) {
  var rows = H.timeline.slice().reverse().map(function (r) {
    var diff = (r.changes || []).map(function (c) {
      return '<div class="hdiff"><span class="hfield">' + esc(c.field) + "</span> " + _val(c.old) + ' <span class="harrow">→</span> ' + _val(c.new) + "</div>";
    }).join("");
    return '<div class="htl"><div class="htlv">v' + esc(String(r.version || "")) + '<span class="htlop op-' + esc(r.op) + '">' + esc(r.op) + "</span></div>"
      + '<div class="htlmeta">' + esc(_short(r.actor)) + " · " + esc(_fmtTs(r.ts)) + "<div class=\"hreason\">" + esc(r.reason || "") + "</div></div>"
      + (diff ? '<div class="hdiffs">' + diff + "</div>" : '<div class="muted" style="font-size:12px">created</div>') + "</div>";
  }).join("");
  return '<button id="hist-back" class="mini" type="button">‹ All changes</button>'
    + '<h3 style="margin:10px 0 4px">' + esc(H.entity_type) + " · " + esc(H.entity_id) + "</h3>"
    + '<div class="muted" style="font-size:12.5px;margin-bottom:8px">' + H.revisions + " revision(s), newest first. Each shows the fields that changed (old → new).</div>"
    + (rows || '<div class="muted">No recorded changes (still at seed baseline).</div>');
}

function openHistory() {
  var modal = document.getElementById("hist-modal"), body = document.getElementById("hist-body");
  document.getElementById("hist-title").textContent = "Model history & compare";
  body.innerHTML = '<div class="muted">Loading…</div>';
  modal.hidden = false;
  fetch("/api/changes").then(function (r) { return r.json(); }).then(function (d) {
    body.innerHTML = renderChanges(d.changes);
    body.querySelectorAll(".hrow").forEach(function (row) {
      row.addEventListener("click", function () { openEntityHistory(row.getAttribute("data-type"), row.getAttribute("data-id")); });
    });
  });
}
function openEntityHistory(type, id) {
  var body = document.getElementById("hist-body");
  document.getElementById("hist-title").textContent = "History · " + id;
  body.innerHTML = '<div class="muted">Loading…</div>';
  fetch("/api/history?type=" + encodeURIComponent(type) + "&id=" + encodeURIComponent(id)).then(function (r) { return r.json(); }).then(function (d) {
    body.innerHTML = renderEntityHistory(d.history);
    var back = document.getElementById("hist-back");
    if (back) back.addEventListener("click", openHistory);
  });
}
(function () {
  var hb = document.getElementById("history-btn"); if (!hb) return;
  hb.addEventListener("click", openHistory);
  document.getElementById("hist-close").addEventListener("click", function () { document.getElementById("hist-modal").hidden = true; });
  document.getElementById("hist-modal").addEventListener("click", function (e) { if (e.target === this) this.hidden = true; });
})();
