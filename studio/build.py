#!/usr/bin/env python3
"""Builds Continuum Studio with the enterprise modules.

template.orig.html  — the published Studio source (decoded self-template)
enterprise.css/.js  — the new modules
core/*.js           — the browser copy of the rules (parity-tested against enterprise/rules.py)

Outputs:
  dist/template.html — the new self-template (what gets base64-embedded)
  dist/studio.html   — the publishable page, state + template substituted
                       exactly as the page's own buildPublishHtml() does.

Every patch asserts its anchor exists exactly once, so a drift in the
source fails the build loudly instead of silently skipping a change.
"""
import base64, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
CORE = os.path.join(HERE, "core")
os.makedirs(os.path.join(HERE, "dist"), exist_ok=True)

src = open(os.path.join(HERE, "template.orig.html"), encoding="utf-8").read()
css = open(os.path.join(HERE, "enterprise.css"), encoding="utf-8").read()
ejs = open(os.path.join(HERE, "enterprise.js"), encoding="utf-8").read()
core_js = open(os.path.join(CORE, "continuum-core.js"), encoding="utf-8").read()
iso_js = open(os.path.join(CORE, "iso-packs.js"), encoding="utf-8").read()

for name, text in [("core", core_js), ("iso", iso_js), ("enterprise", ejs), ("css", css)]:
    assert "</script" not in text.lower(), name + " must not contain a closing script tag"
    assert "@@CONTINUUM_" not in text, name + " must not contain template tokens"


def patch(s, old, new, label):
    n = s.count(old)
    if n != 1:
        sys.exit("patch '%s': anchor found %d times" % (label, n))
    return s.replace(old, new)


RIPPLE_ICON = ('    "ripple": \'<svg viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">'
               '<circle cx="8" cy="8" r="1.6" fill="currentColor"/><circle cx="8" cy="8" r="4" stroke="currentColor" stroke-width="1.3"/>'
               '<circle cx="8" cy="8" r="6.6" stroke="currentColor" stroke-width="1.1" opacity="0.55"/></svg>\',\n')

s = src

# 1. icon
s = patch(s, '    "copy": ', RIPPLE_ICON + '    "copy": ', "icon")

# 2. styles
s = patch(s, ".djs-minimap { border-color: var(--border) !important; background: var(--canvas-bg) !important; }\n\n</style>",
          ".djs-minimap { border-color: var(--border) !important; background: var(--canvas-bg) !important; }\n\n" + css + "\n</style>", "css")

# 3. top bar: module navigation, group ids, Ripple button, spacer
s = patch(s, '''    <div class="tb-group">
      <button class="tb-btn icon-only" id="btn-toggle-library"''', '''    <div class="tb-group module-nav" id="module-nav">
      <button class="module-btn active" data-module="processes">Processes</button>
      <button class="module-btn" data-module="estate">Estate</button>
      <button class="module-btn" data-module="atlas">Atlas</button>
      <button class="module-btn" data-module="assure">Assure</button>
      <button class="module-btn" data-module="vitals">Vitals<span class="module-badge" id="vitals-badge"></span></button>
    </div>

    <div class="tb-group" id="tbg-library">
      <button class="tb-btn icon-only" id="btn-toggle-library"''', "nav")
s = patch(s, '''    <div class="tb-group">
      <button class="tb-btn" id="btn-new"''', '''    <div class="tb-group" id="tbg-proc">
      <button class="tb-btn" id="btn-new"''', "tbg-proc")
s = patch(s, '''    <div class="tb-group">
      <button class="tb-btn primary" id="btn-save"''', '''    <div class="tb-spacer"></div>
    <div class="tb-group">
      <button class="tb-btn" id="btn-ripple" title="Ripple — see everything a change touches"><span class="ic" data-icon="ripple"></span> Ripple</button>
      <button class="tb-btn primary" id="btn-save"''', "save-group")
s = patch(s, '''    <div class="tb-group">
      <button class="tb-btn icon-only" id="btn-toggle-panel"''', '''    <div class="tb-group" id="tbg-panel">
      <button class="tb-btn icon-only" id="btn-toggle-panel"''', "tbg-panel")

# 4. module view container
s = patch(s, '''  <div id="statusbar">''', '''  <div id="module-view" aria-live="polite"></div>

  <div id="statusbar">''', "module-view")

# 5. core library scripts ahead of the app
s = patch(s, '<script src="https://cdn.jsdelivr.net/npm/bpmn-js@18.25.1/dist/bpmn-modeler.production.min.js"></script>',
          "<script>\n" + iso_js + "\n</script>\n<script>\n" + core_js + "\n</script>\n" +
          '<script src="https://cdn.jsdelivr.net/npm/bpmn-js@18.25.1/dist/bpmn-modeler.production.min.js"></script>', "core-scripts")

# 6. enterprise module code inside the app closure
s = patch(s, "  /* ---------------------------------------------------------------------\n     15. Boot",
          ejs + "\n  /* ---------------------------------------------------------------------\n     15. Boot", "enterprise-js")

# 7. dirty tracking: process edits vs. registry-only edits
s = patch(s, '''  function markDirty() {
    dirty = true;''', '''  function markDirty() {
    dirty = true;
    procChanged = true;''', "markDirty")

# 8. save: registry-only saves, keep meta, version bump only for process changes
s = patch(s, '''    if (!getActive()) { toast("Nothing to save yet — create a process first."); return; }
    setSaveState("saving", "Saving…");
    captureCurrentXml().then(function () {
      var proc = getActive();
      pruneOrphanedGovernance(proc);
      proc.updatedAt = nowIso();
      proc.version = (proc.version || 1) + 1;
      proc.history = proc.history || [];
      proc.history.unshift({ version: proc.version, savedAt: proc.updatedAt, note: "Saved from Continuum Studio" });
      if (proc.history.length > 25) proc.history.length = 25;
      STATE.meta = { updatedAt: proc.updatedAt };
''', '''    if (!getActive() && !STATE.registry) { toast("Nothing to save yet — create a process first."); return; }
    setSaveState("saving", "Saving…");
    (getActive() ? captureCurrentXml() : Promise.resolve()).then(function () {
      var proc = getActive();
      // Registry-only edits (Estate, Atlas, Assure) do not bump the open
      // process's document version — ISO 9001 §7.5 versioning stays honest.
      var bump = !!proc && (procChanged || !dirty);
      var stamp = nowIso();
      if (proc) pruneOrphanedGovernance(proc);
      syncTasks();
      if (bump) {
        proc.updatedAt = stamp;
        proc.version = (proc.version || 1) + 1;
        proc.history = proc.history || [];
        proc.history.unshift({ version: proc.version, savedAt: proc.updatedAt, note: "Saved from Continuum Studio" });
        if (proc.history.length > 25) proc.history.length = 25;
      }
      STATE.meta = Object.assign({}, STATE.meta, { updatedAt: stamp });
      procChanged = false;
''', "doSave")
s = patch(s, '''          setSaveState("saved", "Saved · v" + proc.version);''', '''          setSaveState("saved", proc ? "Saved · v" + proc.version : "Saved");''', "save-label")
s = patch(s, '''          setSaveState("saved", "Saved locally · v" + proc.version);''', '''          setSaveState("saved", proc ? "Saved locally · v" + proc.version : "Saved locally");''', "save-label-local")

# 9. governance panel: risks as records, enterprise links, structured actions
s = patch(s, '''      '<div class="field"><label for="f-risk">Risk references</label><input type="text" id="f-risk" placeholder="Comma-separated" value="' + escapeHtml(proc.riskRefs) + '"></div>' +''',
          '''      panelRiskLinker(proc) +''', "risk-field")
s = patch(s, '''      maturityPicker("f-maturity", proc.maturityScore) +
      "</div>" +''', '''      maturityPicker("f-maturity", proc.maturityScore) +
      "</div>" +
      panelProcessLinks(proc) +''', "proc-links")
s = patch(s, '''      "</div><div class=\\"hint\\">Inherited by every task in this process unless a task defines its own override.</div></div>" +''',
          '''      "</div>" + guardrailActionsHtml(g) + "<div class=\\"hint\\">Inherited by every task in this process unless a task defines its own override. Each comma-separated phrase becomes a structured action id agents are checked against.</div></div>" +''', "proc-actions")
s = patch(s, '''      "</div></div>" +
      '<div class="hint" style="padding:0 2px;">This is the exact shape an agent binding would read via <code>get_task_context</code> — see continuum-core-model.md §03.</div>\'''',
          '''      "</div>" + guardrailActionsHtml(Core.effectiveGuardrail(proc, el.id)) + "</div>" +
      panelElementLinks(proc, el) +
      '<div class="hint" style="padding:0 2px;">This is the exact shape an agent binding would read via <code>get_task_context</code> — see continuum-core-model.md §03.</div>\'''', "el-links")
s = patch(s, '''    wirePanelInputs(proc, el);
  }''', '''    wirePanelInputs(proc, el);
    wirePanelEnterprise(proc, el);
  }''', "wire-panel")

# 10. export: whole enterprise workspace (the platform's import format)
s = patch(s, '''      '<div class="select-btn-row"><button class="btn full" id="exp-json"><span class="ic" data-icon="download"></span> Governance &amp; task context (.json)</button></div>' +''',
          '''      '<div class="select-btn-row"><button class="btn full" id="exp-json"><span class="ic" data-icon="download"></span> Governance &amp; task context (.json)</button></div>' +
      '<div class="select-btn-row"><button class="btn full" id="exp-ws"><span class="ic" data-icon="download"></span> Enterprise workspace — every process, system, agent, obligation, control and risk (.json)</button></div>' +''', "export-btn")
s = patch(s, '''        $("#exp-json", root).onclick = function () {''', '''        $("#exp-ws", root).onclick = function () {
          captureCurrentXml().then(function () {
            closeModal();
            offerDownload("continuum-workspace.json", JSON.stringify(workspaceExport(), null, 2));
          });
        };
        $("#exp-json", root).onclick = function () {''', "export-handler")

# 11. boot + toolbar wiring
s = patch(s, '''    initCapabilities().then(function () {
      if (!STATE.order.length) {''', '''    initCapabilities().then(function () {
      enterpriseInit();
      if (!STATE.order.length) {''', "init")
s = patch(s, '''    $("#btn-save").addEventListener("click", doSave);''', '''    $("#btn-save").addEventListener("click", doSave);
    $("#btn-ripple").addEventListener("click", openRipplePicker);
    $all(".module-btn").forEach(function (b) {
      b.addEventListener("click", function () {
        var go = function () { switchModule(b.getAttribute("data-module")); };
        if (activeModule === "processes" && getActive() && modeler) captureCurrentXml().then(go); else go();
      });
    });''', "toolbar")

# 11b. a close hook every close path runs (Esc, overlay click, buttons)
s = patch(s, '''  function openModal(innerHtml, onMount) {
    var root = $("#modal-root");''', '''  var modalCloseHook = null;
  function openModal(innerHtml, onMount) {
    modalCloseHook = null;
    var root = $("#modal-root");''', "modal-hook-open")
s = patch(s, '''  function closeModal() {
    $("#modal-root").innerHTML = "";
    document.removeEventListener("keydown", modalEscHandler);
  }''', '''  function closeModal() {
    var hook = modalCloseHook;
    modalCloseHook = null;
    $("#modal-root").innerHTML = "";
    document.removeEventListener("keydown", modalEscHandler);
    if (hook) hook();
  }''', "modal-hook-close")

# 12. the export modal's open guard needs a process; Ripple from the
#     governance panel needs the live XML — both already covered above.

open(os.path.join(HERE, "dist", "template.html"), "w", encoding="utf-8").write(s)

# ---- assemble the publishable page exactly like buildPublishHtml() ----
state_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "state.orig.json")
state = json.load(open(state_path, encoding="utf-8"))
state_json = json.dumps(state, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
b64 = base64.b64encode(s.encode("utf-8")).decode("ascii")
page = s.replace("@@CONTINUUM_TEMPLATE_B64@@", b64, 1).replace("@@CONTINUUM_STATE@@", state_json, 1)
assert page.count("@@CONTINUUM_STATE@@") == 1, "second token (inside app.js source) must survive"
open(os.path.join(HERE, "dist", "studio.html"), "w", encoding="utf-8").write(page)
print("template %d bytes, page %d bytes, state from %s" % (len(s), len(page), os.path.basename(state_path)))
