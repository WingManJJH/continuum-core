"use strict";
// Phase 3 — Present / live board mode. Full-screen, big, touch-friendly; a
// leadership team drives the model on a video board and edits stay live (SSE).
// Classic script after app.js; reuses its globals (state, renderCenter,
// openProcess, and the view buttons).

(function () {
  var btn = document.getElementById("present-btn"); if (!btn) return;
  var bar = document.getElementById("present-bar");

  function fillProcs() {
    var sel = document.getElementById("pb-proc"); if (!sel) return;
    sel.innerHTML = '<option value="">— Open a process flow —</option>'
      + (state.procs || []).map(function (p) { return '<option value="' + p.id + '">' + p.id + " · " + p.name + "</option>"; }).join("");
  }
  function markView(pv) {
    document.querySelectorAll(".pb-views button").forEach(function (b) { b.classList.toggle("active", b.getAttribute("data-pv") === pv); });
    var sel = document.getElementById("pb-proc"); if (sel && pv) sel.value = "";
  }
  function setView(pv) {
    markView(pv);
    if (pv === "landscape") { document.getElementById("landscape-btn").click(); }
    else if (pv === "architecture") { document.getElementById("arch-btn").click(); }
    else if (pv === "okr" || pv === "xmatrix" || pv === "align") {
      state.stratTab = pv;
      document.getElementById("strategy-btn").click();
    }
  }
  function enter() {
    document.body.classList.add("presenting");
    bar.hidden = false;
    fillProcs();
    try { var rf = document.documentElement.requestFullscreen; if (rf) rf.call(document.documentElement).catch(function () {}); } catch (e) {}
    setView("landscape");
  }
  function exit() {
    document.body.classList.remove("presenting");
    bar.hidden = true;
    try { if (document.fullscreenElement) document.exitFullscreen(); } catch (e) {}
  }

  btn.addEventListener("click", enter);
  document.getElementById("pb-exit").addEventListener("click", exit);
  document.querySelectorAll(".pb-views button").forEach(function (b) {
    b.addEventListener("click", function () { setView(b.getAttribute("data-pv")); });
  });
  document.getElementById("pb-proc").addEventListener("change", function () {
    if (this.value) { markView(null); openProcess(this.value); }
  });
  document.addEventListener("fullscreenchange", function () {
    if (!document.fullscreenElement && document.body.classList.contains("presenting")) exit();
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && document.body.classList.contains("presenting")) exit();
  });
})();
