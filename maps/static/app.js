"use strict";
var $ = function (s) { return document.querySelector(s); };
function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]; }); }
function trunc(s, n) { s = String(s); return s.length > n ? s.slice(0, n - 1) + "…" : s; }
function shortRole(r) { return r.replace(/^role\./, "").replace(/^agent\./, ""); }
function lastSeg(r) { return r.split(".").pop(); }

// layout constants (device-independent units; SVG scales)
var PAD = 16, R = 14, NW = 160, NH = 62, GAP = 46, LANE = 26;

function wrap(name, max) {
  var words = name.split(" "), lines = [], cur = "";
  for (var i = 0; i < words.length; i++) {
    var t = cur ? cur + " " + words[i] : words[i];
    if (t.length > max && cur) { lines.push(cur); cur = words[i]; } else { cur = t; }
    if (lines.length === 1 && cur.length > max) break; // cap at 2 lines
  }
  if (cur) lines.push(cur);
  if (lines.length > 2) { lines = [lines[0], trunc(lines.slice(1).join(" "), max)]; }
  return lines.slice(0, 2);
}

function renderFlow(m) {
  var uid = m.id.replace(/[^A-Za-z0-9]/g, "_");
  var tasks = m.tasks;
  var hasEsc = tasks.some(function (t) { return t.agents.length && t.escalate_if; });
  var escY = LANE + NH + 54;
  var H = hasEsc ? escY + 44 : LANE + NH + 18;
  var firstX = PAD + 2 * R + GAP;
  var lastX = firstX + (tasks.length - 1) * (NW + GAP);
  var endCx = lastX + NW + GAP + R;
  var W = endCx + R + PAD;
  var cy = LANE + NH / 2;
  var p = [];

  p.push('<svg viewBox="0 0 ' + W + ' ' + H + '" width="' + W + '" height="' + H + '" xmlns="http://www.w3.org/2000/svg">');
  p.push('<defs><marker id="ah_' + uid + '" markerWidth="7" markerHeight="7" refX="6" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6 z" class="arrow"/></marker>'
    + '<marker id="eh_' + uid + '" markerWidth="7" markerHeight="7" refX="3" refY="6" orient="auto"><path d="M0,0 L6,0 L3,6 z" class="esc-arrow"/></marker></defs>');

  // start terminal
  p.push('<circle class="tip" cx="' + (PAD + R) + '" cy="' + cy + '" r="' + R + '"/>');
  p.push('<text class="tip" x="' + (PAD + R) + '" y="' + (cy + 3) + '" text-anchor="middle">start</text>');
  p.push('<line class="conn" x1="' + (PAD + 2 * R) + '" y1="' + cy + '" x2="' + firstX + '" y2="' + cy + '" marker-end="url(#ah_' + uid + ')"/>');

  tasks.forEach(function (t, i) {
    var x = firstX + i * (NW + GAP);
    var cls = "node" + (t.agents.length ? " agent" : "") + (t.override ? " override" : "");
    p.push('<rect class="' + cls + '" x="' + x + '" y="' + LANE + '" width="' + NW + '" height="' + NH + '" rx="9"/>');
    p.push('<text class="tseq" x="' + (x + 9) + '" y="' + (LANE + 15) + '">t' + t.seq + '</text>');
    if (t.agents.length) {
      p.push('<rect class="badge-bg" x="' + (x + NW - 26) + '" y="' + (LANE - 7) + '" width="24" height="15" rx="3.5"/>');
      p.push('<text class="badge" x="' + (x + NW - 14) + '" y="' + (LANE + 3.5) + '" text-anchor="middle">AI</text>');
    }
    if (t.override) {
      p.push('<text class="tag" x="' + (x + NW - 6) + '" y="' + (LANE - 4) + '" text-anchor="end">override</text>');
    }
    var lines = wrap(t.name, 22);
    var startY = lines.length === 2 ? LANE + 24 : LANE + 31;
    lines.forEach(function (ln, k) {
      p.push('<text class="tname" x="' + (x + 10) + '" y="' + (startY + k * 14) + '">' + esc(ln) + '</text>');
    });
    var who = t.agents.length ? ((t.roles[0] ? lastSeg(t.roles[0]) + " + agent" : "agent")) : (t.roles[0] ? lastSeg(t.roles[0]) : "");
    p.push('<text class="tperf" x="' + (x + 10) + '" y="' + (LANE + NH - 9) + '">' + esc(trunc(who, 24)) + '</text>');

    // connector to next node / end
    var rightX = x + NW;
    var nextX = i < tasks.length - 1 ? firstX + (i + 1) * (NW + GAP) : endCx - R;
    p.push('<line class="conn" x1="' + rightX + '" y1="' + cy + '" x2="' + nextX + '" y2="' + cy + '" marker-end="url(#ah_' + uid + ')"/>');

    // escalation branch for an agent step with a condition
    if (t.agents.length && t.escalate_if) {
      var bx = x + NW / 2;
      p.push('<line class="esc-line" x1="' + bx + '" y1="' + (LANE + NH) + '" x2="' + bx + '" y2="' + escY + '" marker-end="url(#eh_' + uid + ')"/>');
      var pw = 172, px = Math.max(PAD, bx - pw / 2);
      p.push('<rect class="esc" x="' + px + '" y="' + escY + '" width="' + pw + '" height="34" rx="7"/>');
      p.push('<text class="esc" x="' + (px + 10) + '" y="' + (escY + 14) + '">escalate → ' + esc(shortRole(t.escalation_path || "")) + '</text>');
      p.push('<text class="esc-cond" x="' + (px + 10) + '" y="' + (escY + 27) + '">if ' + esc(trunc(t.escalate_if, 26)) + '</text>');
    }
  });

  // end terminal
  p.push('<circle class="tip" cx="' + endCx + '" cy="' + cy + '" r="' + R + '"/>');
  p.push('<text class="tip" x="' + endCx + '" y="' + (cy + 3) + '" text-anchor="middle">end</text>');
  p.push("</svg>");
  return p.join("");
}

function renderProcess(m) {
  var chips = [];
  chips.push('<span class="chip">owner ' + esc(shortRole(m.owner)) + "</span>");
  if (m.guardrail) chips.push('<span class="chip gr">' + esc(m.guardrail) + "</span>");
  m.kpis.forEach(function (k) { chips.push('<span class="chip">' + esc(k) + "</span>"); });
  m.risks.forEach(function (r) { chips.push('<span class="chip risk" title="' + esc(r.risk) + '">' + esc(r.id) + "</span>"); });
  return '<div class="map"><div class="mhead"><span class="pid">' + esc(m.id) + '</span>'
    + '<span class="pname">' + esc(m.name) + '</span>'
    + '<span class="chips">' + chips.join("") + '</span></div>'
    + '<div class="flow">' + renderFlow(m) + '</div></div>';
}

fetch("/api/maps").then(function (r) { return r.json(); }).then(function (d) {
  $("#maps").innerHTML = d.processes.map(renderProcess).join("");
}).catch(function (e) { $("#maps").innerHTML = '<div class="muted">failed to load: ' + esc(e) + "</div>"; });

// theme toggle
(function () {
  var order = ["auto", "light", "dark"], root = document.documentElement, btn = $("#themeBtn"), cur = "auto";
  try { cur = localStorage.getItem("cc-maps-theme") || "auto"; } catch (e) {}
  function apply(t) { if (t === "auto") root.removeAttribute("data-theme"); else root.setAttribute("data-theme", t); btn.textContent = "theme: " + t; try { localStorage.setItem("cc-maps-theme", t); } catch (e) {} }
  apply(cur);
  btn.addEventListener("click", function () { cur = order[(order.indexOf(cur) + 1) % order.length]; apply(cur); });
})();
