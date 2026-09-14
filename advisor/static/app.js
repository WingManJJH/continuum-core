"use strict";
var $ = function (s) { return document.querySelector(s); };
function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) { return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]; }); }

var SUBJECTS = {};
var kindSel = $("#kind"), subjSel = $("#subject"), contentBox = $("#content"), thread = $("#thread");

fetch("/api/subjects").then(function (r) { return r.json(); }).then(function (d) { SUBJECTS = d; syncComposer(); });

function syncComposer() {
  var k = kindSel.value;
  var picksId = (k === "process" || k === "guardrail" || k === "task");
  subjSel.hidden = !picksId;
  contentBox.hidden = (k !== "content");
  if (picksId) {
    var list = SUBJECTS[k] || [];
    subjSel.innerHTML = list.map(function (s) { return '<option value="' + esc(s.id) + '">' + esc(s.id) + (s.name && s.name !== s.id ? " — " + esc(s.name) : "") + "</option>"; }).join("");
  }
}
kindSel.addEventListener("change", syncComposer);

function addUser(text) {
  var el = document.createElement("div");
  el.className = "turn user";
  el.innerHTML = '<div class="bubble">' + esc(text) + "</div>";
  thread.appendChild(el); scroll();
}
function scoreClass(n) { return n >= 90 ? "good" : n >= 70 ? "warn" : "crit"; }

function addAnalysis(r) {
  var el = document.createElement("div");
  el.className = "turn assistant";
  if (r.error) { el.innerHTML = '<div class="bubble">Could not analyze: ' + esc(r.error) + "</div>"; thread.appendChild(el); scroll(); return; }
  var stds = [];
  r.checks.forEach(function (c) { if (stds.indexOf(c.standard) < 0) stds.push(c.standard); });
  var passed = r.n_checks - r.n_findings;
  var findings = r.findings.map(function (f) {
    return '<div class="find"><span class="sev ' + esc(f.severity) + '">' + esc(f.severity) + "</span>"
      + '<div><div class="t">' + esc(f.title) + '</div>'
      + '<div class="d">' + esc(f.detail) + "</div>"
      + (f.recommendation ? '<div class="r">' + esc(f.recommendation) + "</div>" : "")
      + '<span class="std">' + esc(f.standard) + "</span></div></div>";
  }).join("");
  var worst = (r.worst && r.worst.length)
    ? '<div class="worst">Lowest-scoring: ' + r.worst.map(function (w) { return "<code>" + esc(w.id) + "</code> " + w.score + "%"; }).join(" · ") + "</div>" : "";
  var passline = r.n_findings === 0
    ? '<div class="passline allpass">✓ All ' + r.n_checks + " checks passed — meets the standards reviewed.</div>"
    : '<div class="passline">' + passed + " of " + r.n_checks + " checks passed.</div>";
  el.innerHTML = '<div class="bubble">'
    + '<div class="scorecard"><span class="score ' + scoreClass(r.score) + '">' + r.score + '%</span>'
    + '<div class="sc-meta"><div class="subj">' + esc(r.subject) + '</div>'
    + '<div class="line">analyzed against: ' + esc(stds.join(" · ")) + "</div></div></div>"
    + findings + passline + worst + llmBlock(r)
    + (r.note ? '<div class="note">' + esc(r.note) + "</div>" : "")
    + "</div>";
  thread.appendChild(el); scroll();
}
function llmBlock(r) {
  if (!r.llm_status || r.llm_status === "off") return "";
  var head = '<div class="llm-head">AI reviewer <span>advisory &middot; does not change the score</span></div>';
  if (r.llm_status === "error")
    return '<div class="llm err">' + head + '<div class="llm-empty">Reviewer error: ' + esc(r.llm_note || "") + "</div></div>";
  if (r.llm_status === "on_empty" || !r.llm_findings || !r.llm_findings.length)
    return '<div class="llm">' + head + '<div class="llm-empty">The reviewer had nothing to add beyond the checks above.</div></div>';
  var items = r.llm_findings.map(function (f) {
    return '<div class="find"><span class="sev ' + esc(f.severity) + '">' + esc(f.severity) + "</span>"
      + '<div><div class="t">' + esc(f.title) + "</div>"
      + '<div class="d">' + esc(f.detail) + "</div>"
      + (f.recommendation ? '<div class="r">' + esc(f.recommendation) + "</div>" : "")
      + '<span class="std">AI reviewer</span></div></div>';
  }).join("");
  return '<div class="llm">' + head + items + "</div>";
}
function scroll() { thread.scrollTop = thread.scrollHeight; }

$("#analyze").addEventListener("click", function () {
  var k = kindSel.value, btn = $("#analyze");
  var body = { subject_type: k };
  var label;
  if (k === "model") { label = "Analyze the whole model against best practices"; }
  else if (k === "content") {
    body.content = contentBox.value;
    if (!body.content.trim()) { contentBox.focus(); return; }
    label = "Analyze this content against best practices";
  } else { body.id = subjSel.value; label = "Analyze " + subjSel.value + " against best practices"; }
  addUser(label);
  btn.disabled = true;
  fetch("/api/analyze", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
    .then(function (r) { return r.json(); })
    .then(function (r) { btn.disabled = false; addAnalysis(r); })
    .catch(function (e) { btn.disabled = false; addAnalysis({ error: String(e) }); });
});

(function () {
  var order = ["auto", "light", "dark"], root = document.documentElement, b = $("#themeBtn"), cur = "auto";
  try { cur = localStorage.getItem("cc-advisor-theme") || "auto"; } catch (e) {}
  function apply(t) { if (t === "auto") root.removeAttribute("data-theme"); else root.setAttribute("data-theme", t); b.textContent = "theme: " + t; try { localStorage.setItem("cc-advisor-theme", t); } catch (e) {} }
  apply(cur);
  b.addEventListener("click", function () { cur = order[(order.indexOf(cur) + 1) % order.length]; apply(cur); });
})();
