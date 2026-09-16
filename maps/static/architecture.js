"use strict";
// Architecture view (L1–L5 process hierarchy) + master-data panels.
// Classic script after app.js — reuses its globals ($, esc, state, renderCenter,
// openProcess, ACTOR, load, shortRole). All edits go through the audited API.

function postGroup(body) { return fetch("/api/group", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).then(function (r) { return r.json(); }); }
function postProcEdit(body) { return fetch("/api/process/edit", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).then(function (r) { return r.json(); }); }

// ---------- the hierarchy tree ----------
function renderArchitecture(A) {
  function proc(p) {
    var ai = p.agent_steps ? p.agent_steps + " AI · " : "";
    return '<div class="apcard" data-open="' + esc(p.id) + '"><div class="apcid">' + esc(p.id) + "</div>"
      + '<div class="apcname">' + esc(p.name) + "</div>"
      + '<div class="apcmeta">' + p.steps + " steps · " + ai + "owner " + esc(shortRole(p.owner))
      + (p.objective_refs && p.objective_refs.length ? " · <b>" + p.objective_refs.length + " objective</b>" : "")
      + (p.custom && Object.keys(p.custom).length ? " · " + Object.keys(p.custom).length + " field" : "") + "</div></div>";
  }
  function node(n) {
    var kids = (n.children || []).map(node).join("");
    var procs = (n.processes || []).map(proc).join("");
    return '<div class="agroup" data-lvl="' + n.level + '">'
      + '<div class="aghead"><span class="aglvl">L' + n.level + "</span>"
      + '<span class="agname">' + esc(n.name) + "</span>"
      + '<span class="agid">' + esc(n.id) + "</span>"
      + (n.owner_role ? '<span class="agowner">owner ' + esc(shortRole(n.owner_role)) + "</span>" : "")
      + (n.objective_refs && n.objective_refs.length ? '<span class="agobj">' + n.objective_refs.length + " objective</span>" : "")
      + '<button class="mini agmd" type="button" data-group="' + esc(n.id) + '">Master data</button></div>'
      + (n.description ? '<div class="agdesc">' + esc(n.description) + "</div>" : "")
      + '<div class="agbody">' + kids + (procs ? '<div class="apcards">' + procs + "</div>" : "") + "</div></div>";
  }
  var roots = (A.roots || []).map(node).join("");
  var orphans = A.orphans && A.orphans.length
    ? '<div class="agroup"><div class="aghead"><span class="aglvl warn">?</span><span class="agname">Unparented</span></div>'
      + '<div class="agbody"><div class="apcards">' + A.orphans.map(proc).join("") + "</div></div></div>" : "";
  return '<div class="arch"><div class="archhead">Process architecture — <b>' + (A.groups ? A.groups.length : 0)
    + "</b> groups, <b>" + A.process_total + "</b> processes across levels 1–5. Click a process to open it; <b>Master data</b> to edit a level.</div>"
    + roots + orphans + "</div>";
}
function wireArchitecture() {
  var c = document.getElementById("canvas"); if (!c) return;
  c.querySelectorAll("[data-open]").forEach(function (el) {
    el.addEventListener("click", function () { openProcess(el.getAttribute("data-open")); });
  });
  c.querySelectorAll(".agmd").forEach(function (b) {
    b.addEventListener("click", function (e) { e.stopPropagation(); openMasterData("group", b.getAttribute("data-group")); });
  });
}

// ---------- master-data modal (group or process) ----------
function _customEditor(custom) {
  var rows = Object.keys(custom || {}).map(function (k) { return _kvRow(k, custom[k]); }).join("");
  return '<div class="lbl">custom fields</div><div id="md-kv">' + rows + "</div>"
    + '<button id="md-addkv" class="mini" type="button">+ Add field</button>';
}
function _kvRow(k, v) {
  return '<div class="kvrow"><input class="kv-k" placeholder="field" value="' + esc(k || "") + '">'
    + '<input class="kv-v" placeholder="value" value="' + esc(v == null ? "" : String(v)) + '">'
    + '<button class="mini kv-x" type="button">&times;</button></div>';
}
function _collectKv() {
  var out = {};
  document.querySelectorAll("#md-kv .kvrow").forEach(function (r) {
    var k = r.querySelector(".kv-k").value.trim(), v = r.querySelector(".kv-v").value.trim();
    if (k) out[k] = v;
  });
  return out;
}
function _wireKv() {
  var add = document.getElementById("md-addkv");
  if (add) add.onclick = function () { document.getElementById("md-kv").insertAdjacentHTML("beforeend", _kvRow("", "")); _wireKvX(); };
  _wireKvX();
}
function _wireKvX() {
  document.querySelectorAll("#md-kv .kv-x").forEach(function (x) { x.onclick = function () { x.closest(".kvrow").remove(); }; });
}

function openMasterData(kind, id) {
  var modal = document.getElementById("md-modal");
  document.getElementById("md-kind").textContent = kind === "group" ? "hierarchy level" : "process";
  document.getElementById("md-title").textContent = "Master data · " + id;
  document.getElementById("md-msg").innerHTML = "";
  var body = document.getElementById("md-body");
  if (kind === "group") {
    var g = (state.architecture && state.architecture.groups || []).find(function (x) { return x.id === id; }) || {};
    body.innerHTML =
      '<label>Name<input id="md-name" value="' + esc(g.name || "") + '"></label>'
      + '<label>Owner role <span class="hint">role.*</span><input id="md-owner" value="' + esc(g.owner_role || "") + '"></label>'
      + '<label>Objectives <span class="hint">comma · obj.*</span><input id="md-obj" value="' + esc((g.objective_refs || []).join(", ")) + '"></label>'
      + '<label>Description<input id="md-desc" value="' + esc(g.description || "") + '"></label>'
      + '<div class="p-sec">' + _customEditor(g.custom) + "</div>"
      + (typeof gateControlHTML === "function" ? '<div class="p-sec">' + gateControlHTML("ProcessGroup") + "</div>" : "")
      + '<div class="import-actions"><button id="md-save" class="add-btn" type="button">Save</button>'
      + '<button id="md-remove" class="add-btn ghost-btn danger" type="button">Retire level</button></div>';
    modal.hidden = false; _wireKv();
    document.getElementById("md-save").onclick = function () {
      var changes = { name: document.getElementById("md-name").value.trim(),
                      owner_role: document.getElementById("md-owner").value.trim() || null,
                      description: document.getElementById("md-desc").value.trim(),
                      objective_refs: parseCsv(document.getElementById("md-obj").value),
                      custom: _collectKv() };
      if (typeof routeThroughGate === "function" && routeThroughGate(
          "ProcessGroup", body, "edit_group", { group_id: id, changes: changes },
          "Group change · " + id, "edited master data via panel", document.getElementById("md-msg"))) {
        return;
      }
      postGroup({ op: "edit", id: id, changes: changes, actor: ACTOR, reason: "edited master data via panel" })
        .then(function (res) { _mdDone(res); });
    };
    document.getElementById("md-remove").onclick = function () {
      if (!confirm("Retire hierarchy level " + id + "?")) return;
      postGroup({ op: "remove", id: id, actor: ACTOR, reason: "retired level via panel" }).then(function (res) { _mdDone(res, true); });
    };
  } else {
    var p = (state.procs || []).find(function (x) { return x.id === id; }) || {};
    var opts = ['<option value="">—</option>'].concat((state.architecture && state.architecture.groups || []).map(function (x) {
      return '<option value="' + esc(x.id) + '"' + (p.parent_ref === x.id ? " selected" : "") + ">" + esc(x.id) + " · " + esc(x.name) + "</option>";
    })).join("");
    body.innerHTML =
      '<label>Parent (hierarchy)<select id="md-parent">' + opts + "</select></label>"
      + '<label>Objectives <span class="hint">comma · obj.*</span><input id="md-obj" value="' + esc((p.objective_refs || []).join(", ")) + '"></label>'
      + '<div class="p-sec">' + _customEditor(p.custom) + "</div>"
      + (typeof gateControlHTML === "function" ? '<div class="p-sec">' + gateControlHTML("Process") + "</div>" : "")
      + '<div class="import-actions"><button id="md-save" class="add-btn" type="button">Save</button></div>';
    modal.hidden = false; _wireKv();
    document.getElementById("md-save").onclick = function () {
      var changes = { parent_ref: document.getElementById("md-parent").value || null,
                      objective_refs: parseCsv(document.getElementById("md-obj").value),
                      custom: _collectKv() };
      if (typeof routeThroughGate === "function" && routeThroughGate(
          "Process", body, "edit_process", { process_id: id, changes: changes },
          "Process change · " + id, "edited process master data via panel", document.getElementById("md-msg"))) {
        return;
      }
      postProcEdit({ id: id, changes: changes, actor: ACTOR, reason: "edited process master data via panel" })
        .then(function (res) { _mdDone(res); });
    };
  }
}
function _mdDone(res, close) {
  if (!res.ok) { document.getElementById("md-msg").innerHTML = '<div class="msg err">' + esc(res.error) + "</div>"; return; }
  document.getElementById("md-msg").innerHTML = '<div class="msg ok">Saved — versioned &amp; audited.</div>';
  // load() invalidates the architecture cache, so refetch AFTER it, then render
  load().then(function () {
    return fetch("/api/architecture").then(function (r) { return r.json(); }).then(function (d) {
      state.architecture = d.architecture;
      if (close || state.view !== "architecture") document.getElementById("md-modal").hidden = true;
      else renderCenter();
    });
  });
}

// ---------- button wiring ----------
(function () {
  var ab = document.getElementById("arch-btn");
  if (ab) ab.addEventListener("click", function () {
    state.view = "architecture";
    document.querySelectorAll(".views button").forEach(function (x) { x.classList.remove("active"); });
    renderCenter();
    if (!state.architecture) fetch("/api/architecture").then(function (r) { return r.json(); })
      .then(function (d) { state.architecture = d.architecture; if (state.view === "architecture") renderCenter(); });
  });
  var mc = document.getElementById("md-close");
  if (mc) mc.addEventListener("click", function () { document.getElementById("md-modal").hidden = true; });
  var mm = document.getElementById("md-modal");
  if (mm) mm.addEventListener("click", function (e) { if (e.target === mm) mm.hidden = true; });
})();
