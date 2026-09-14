"use strict";
var $ = function (s) { return document.querySelector(s); };
function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) { return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]; }); }

var thread = $("#thread"), qBox = $("#q");
var KW = /\b(FROM|FOLLOW|WHERE|AND|NOT|SELECT|ORDER BY|LIMIT|GET|IS|ABSENT|PRESENT|INTERSECTS|ASC|DESC|EQ|NE|LT|GT|IN)\b/g;

fetch("/api/examples").then(function (r) { return r.json(); }).then(function (d) {
  $("#chips").innerHTML = (d.examples || []).map(function (e) {
    return '<button class="chip" type="button">' + esc(e) + "</button>";
  }).join("");
  Array.prototype.forEach.call(document.querySelectorAll(".chip"), function (c) {
    c.addEventListener("click", function () { qBox.value = c.textContent; submit(); });
  });
});

function scroll() { thread.scrollTop = thread.scrollHeight; }

function addUser(text) {
  var el = document.createElement("div");
  el.className = "turn user";
  el.innerHTML = '<div class="bubble">' + esc(text) + "</div>";
  thread.appendChild(el); scroll();
}

function table(cols, rows) {
  if (!rows || !rows.length) return '<div class="empty">No rows matched.</div>';
  var head = "<tr>" + cols.map(function (c) { return "<th>" + esc(c) + "</th>"; }).join("") + "</tr>";
  var body = rows.map(function (r) {
    return "<tr>" + cols.map(function (c, i) {
      return '<td class="' + (i === 0 ? "k" : "") + '">' + esc(r[c]) + "</td>";
    }).join("") + "</tr>";
  }).join("");
  return '<div class="tbl-wrap"><table class="res"><thead>' + head + "</thead><tbody>" + body + "</tbody></table></div>";
}

function highlightCql(s) {
  return esc(s).replace(KW, function (m) { return '<span class="kw">' + m + "</span>"; });
}

function addAnswer(r) {
  var el = document.createElement("div");
  el.className = "turn assistant";
  if (r.error) { el.innerHTML = '<div class="bubble">Something went wrong: ' + esc(r.error) + "</div>"; thread.appendChild(el); scroll(); return; }

  var html = '<div class="answer">' + esc(r.answer) + "</div>";

  if (r.matched) {
    html += table(r.columns, r.rows);
    if (r.assumptions && r.assumptions.length) {
      html += '<ul class="assume"><span class="h">Assumptions</span>'
        + r.assumptions.map(function (a) { return "<li>" + esc(a) + "</li>"; }).join("") + "</ul>";
    }
    if (r.cql) {
      var id = "cql" + Math.random().toString(36).slice(2);
      html += '<button class="qbtn" type="button" data-t="' + id + '">Show query</button>'
        + '<pre class="cql" id="' + id + '" hidden>' + highlightCql(r.cql) + "</pre>";
    }
  }
  if (r.note) html += '<div class="note">' + esc(r.note) + "</div>";
  if (!r.matched && r.suggestions && r.suggestions.length) {
    html += '<div class="chips">' + r.suggestions.map(function (s) {
      return '<button class="chip" type="button">' + esc(s) + "</button>";
    }).join("") + "</div>";
  }

  el.innerHTML = '<div class="bubble">' + html + "</div>";
  thread.appendChild(el);

  var toggle = el.querySelector(".qbtn");
  if (toggle) toggle.addEventListener("click", function () {
    var pre = document.getElementById(toggle.getAttribute("data-t"));
    pre.hidden = !pre.hidden; toggle.textContent = pre.hidden ? "Show query" : "Hide query";
  });
  Array.prototype.forEach.call(el.querySelectorAll(".chip"), function (c) {
    c.addEventListener("click", function () { qBox.value = c.textContent; submit(); });
  });
  scroll();
}

function submit() {
  var q = qBox.value.trim();
  if (!q) { qBox.focus(); return; }
  addUser(q);
  var btn = $("#ask"); btn.disabled = true; qBox.value = "";
  fetch("/api/ask", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question: q }) })
    .then(function (r) { return r.json(); })
    .then(function (r) { btn.disabled = false; addAnswer(r); })
    .catch(function (e) { btn.disabled = false; addAnswer({ error: String(e) }); });
}

$("#composer").addEventListener("submit", function (e) { e.preventDefault(); submit(); });

(function () {
  var order = ["auto", "light", "dark"], root = document.documentElement, b = $("#themeBtn"), cur = "auto";
  try { cur = localStorage.getItem("cc-ask-theme") || "auto"; } catch (e) {}
  function apply(t) { if (t === "auto") root.removeAttribute("data-theme"); else root.setAttribute("data-theme", t); b.textContent = "theme: " + t; try { localStorage.setItem("cc-ask-theme", t); } catch (e) {} }
  apply(cur);
  b.addEventListener("click", function () { cur = order[(order.indexOf(cur) + 1) % order.length]; apply(cur); });
})();
