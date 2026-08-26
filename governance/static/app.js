"use strict";
const $ = (s) => document.querySelector(s);
const api = (p, opts) => fetch(p, opts).then((r) => r.json());
const csv = (arr) => (arr || []).join(", ");
const parseCsv = (s) => s.split(",").map((x) => x.trim()).filter(Boolean);

let processes = [];
let current = null; // {procId, guardrailId}

// ---- load process list ----------------------------------------------------
async function loadProcesses() {
  processes = await api("/api/processes");
  const ul = $("#proc-list");
  ul.innerHTML = "";
  processes.forEach((p) => {
    const li = document.createElement("li");
    li.dataset.id = p.id;
    const gr = p.guardrail;
    const ovr = p.task_overrides.length
      ? `<span class="chip override" title="${p.task_overrides.join(", ")}">${p.task_overrides.length} override</span>` : "";
    li.innerHTML = `<div class="pname">${p.id}</div>
      <div class="li-meta">${p.name}</div>
      <div class="pmeta">
        <span class="chip">${gr ? gr.id + " v" + gr.version : "no guardrail"}</span>
        ${p.risks.length ? `<span class="chip">${p.risks.length} risk</span>` : ""}
        ${ovr}
      </div>`;
    li.onclick = () => selectProcess(p);
    ul.appendChild(li);
  });
}

// ---- open a guardrail ------------------------------------------------------
async function selectProcess(p) {
  if (!p.guardrail) return;
  current = { procId: p.id, guardrailId: p.guardrail.id };
  document.querySelectorAll(".proc-list li").forEach((li) =>
    li.classList.toggle("active", li.dataset.id === p.id));
  const data = await api("/api/guardrail?id=" + encodeURIComponent(p.guardrail.id));
  fillEditor(p, data.guardrail);
  renderRisks(data.risks);
  renderHistory(data.history);
  hideMsg();
}

function fillEditor(p, gr) {
  $("#editor-empty").hidden = true;
  $("#editor-form").hidden = false;
  $("#gr-id").textContent = gr.id;
  $("#gr-proc").textContent = `${p.id} — ${p.name} · owner ${p.owner_role}`;
  $("#gr-version").textContent = "v" + gr.version;
  $("#f-allowed").value = csv(gr.allowed_actions);
  $("#f-forbidden").value = csv(gr.forbidden_actions);
  $("#f-escalate").value = gr.escalate_if || "";
  $("#f-scope").value = csv(gr.data_scope);
  $("#f-rate-max").value = gr.rate_limit ? gr.rate_limit.max_actions : "";
  $("#f-rate-per").value = gr.rate_limit ? gr.rate_limit.per_seconds : "";
  $("#f-escpath").value = gr.escalation_path || "";
  $("#f-audit").value = gr.audit_requirement;
  $("#f-reason").value = "";
  $("#editor-form").dataset.snapshot = JSON.stringify(gr);
}

function currentSnapshot() {
  return JSON.parse($("#editor-form").dataset.snapshot);
}

// ---- save ------------------------------------------------------------------
async function save(e) {
  e.preventDefault();
  const changes = {
    allowed_actions: parseCsv($("#f-allowed").value),
    forbidden_actions: parseCsv($("#f-forbidden").value),
    escalate_if: $("#f-escalate").value.trim() || null,
    data_scope: parseCsv($("#f-scope").value),
    rate_limit: {
      max_actions: parseInt($("#f-rate-max").value, 10),
      per_seconds: parseInt($("#f-rate-per").value, 10),
    },
    escalation_path: $("#f-escpath").value.trim(),
    audit_requirement: $("#f-audit").value,
  };
  $("#btn-save").disabled = true;
  const res = await api("/api/guardrail?id=" + encodeURIComponent(current.guardrailId), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      changes,
      actor: $("#f-actor").value.trim(),
      reviewer: $("#f-reviewer").value.trim(),
      reason: $("#f-reason").value.trim(),
    }),
  });
  $("#btn-save").disabled = false;
  if (res.ok) {
    showMsg(`Saved. New version v${res.guardrail.version} is live — agents read it on their next call. No deploy.`, "ok");
    await loadProcesses();
    const p = processes.find((x) => x.id === current.procId);
    await selectProcess(p);
  } else {
    showMsg("Rejected: " + res.error, "err");
  }
}

function resetForm() {
  const p = processes.find((x) => x.id === current.procId);
  fillEditor(p, currentSnapshot());
  hideMsg();
}

// ---- side panels -----------------------------------------------------------
function renderRisks(risks) {
  const el = $("#tab-risk");
  if (!risks.length) { el.innerHTML = '<div class="muted">No risk & control entries linked to this guardrail.</div>'; return; }
  el.innerHTML = risks.map((r) => `
    <div class="card">
      <div class="risk-title">${r.id}</div>
      <div class="li-meta">${r.risk}</div>
      <div style="margin-top:6px"><strong>Control:</strong> ${r.control}</div>
      <div class="matrix" style="margin-top:6px">likelihood ${r.likelihood}/5 · impact ${r.impact}/5 · ${r.control_type || ""}</div>
    </div>`).join("");
}

function renderHistory(hist) {
  const el = $("#tab-history");
  el.innerHTML = `<ul class="timeline">${hist.map((h) => `
    <li><span class="v">v${h.version}</span> ${h.source === "baseline" ? "· baseline" : ""}
      <div class="li-meta">${(h.ts || "").replace("T", " ").slice(0, 19)} · ${h.actor}</div>
      <div>${h.reason || ""}</div></li>`).join("")}</ul>`;
}

async function loadAudit() {
  const rows = await api("/api/audit");
  const el = $("#tab-audit");
  if (!rows.length) { el.innerHTML = '<div class="muted">No events yet. Edit a guardrail to create a change-control record.</div>'; return; }
  el.innerHTML = rows.map((a) => `
    <div class="aud">
      <span class="k ${a.kind}">${a.kind}</span>
      <span class="det"> ${a.entity}</span>
      <div class="det">${a.detail}</div>
      <div class="who">${(a.ts || "").replace("T", " ").slice(0, 19)} · ${a.actor}</div>
    </div>`).join("");
}

// ---- tabs ------------------------------------------------------------------
document.querySelectorAll(".tabs button").forEach((b) => {
  b.onclick = () => {
    document.querySelectorAll(".tabs button").forEach((x) => x.classList.toggle("active", x === b));
    ["risk", "history", "audit"].forEach((t) => $("#tab-" + t).hidden = t !== b.dataset.tab);
    if (b.dataset.tab === "audit") loadAudit();
  };
});

function showMsg(t, cls) { const m = $("#msg"); m.textContent = t; m.className = "msg " + cls; m.hidden = false; }
function hideMsg() { $("#msg").hidden = true; }

$("#editor-form").addEventListener("submit", save);
$("#btn-reset").addEventListener("click", resetForm);
loadProcesses();
