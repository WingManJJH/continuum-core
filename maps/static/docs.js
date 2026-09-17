"use strict";
// Documentation panel + Guided Tour for the Continuum Process Canvas.
// A classic script loaded after app.js, so it reuses app.js globals ($, esc,
// openProcess, state, renderCenter, renderProps, setConnect, openRoleDrawer,
// closeRoleDrawer). Nothing here writes to the model — the tour only navigates,
// switches views, and opens panels; it never makes a governed edit.

// ======================= DOCUMENTATION =======================
var DOCS = [
  { id: "overview", title: "What Continuum is", html:
    "<p><b>Continuum</b> is a process modeler with governance built in. You draw how work actually flows — the steps, who does them, the decisions and events — and the same model governs any <b>AI agents</b> that run steps: each step carries a <b>guardrail</b> (what an agent may do, when it must escalate to a human), and every change is versioned and audited.</p>"
    + "<p>One model is the single source of truth. The picture you draw, the guardrails an agent reads, the dashboards, the audit trail, and the BPMN you export are all views of the same governed graph — change it once and everything updates.</p>"
    + "<ul><li><b>Left</b> — the list of processes and the authoring palette.</li><li><b>Center</b> — the canvas: the process as a flowchart, plus Lanes / RACI / Checklist views.</li><li><b>Right</b> — a properties panel for whatever you select.</li></ul>" },

  { id: "canvas", title: "The canvas & views", html:
    "<p>Open a process from the left list. The center shows it as a <b>Flowchart</b> — <code>start → steps → end</code>. A step run by an AI agent shows an <b>AI</b> badge and, if its guardrail escalates, a branch to a human.</p>"
    + "<p>Switch views with the buttons top-right of the canvas:</p>"
    + "<ul><li><b>Flowchart</b> — the flow, free-form. Drag any box to reposition it; <b>Tidy up</b> re-arranges left-to-right.</li>"
    + "<li><b>Lanes</b> — swimlanes grouped by the role that performs each step. Drag a step into another lane to reassign it.</li>"
    + "<li><b>RACI</b> — a Responsible / Accountable / Consulted chart, derived from the model (not hand-maintained).</li>"
    + "<li><b>Checklist</b> — a printable run sheet; tick items as you go.</li></ul>" },

  { id: "startend", title: "Start & end conditions (the value stream)", html:
    "<p>Every flow has a <b>start</b> (always <span style='color:#2fbf71'><b>green</b></span>) and an <b>end</b> (always <span style='color:#f0533a'><b>red</b></span>). These aren't just terminals — they chain processes into an <b>end-to-end value stream</b>.</p>"
    + "<ul><li>Click a process's <b>end</b> to set which process(es) it <b>hands off to</b> — its end links to the next process's start. (You can also set it under a process's <b>master data</b> → “Hands off to”.)</li>"
    + "<li>The <b>end</b> then shows <code>→ NEXT</code> and the <b>start</b> of the next process shows <code>← PRIOR</code> — click either to jump along the chain.</li>"
    + "<li>A start that nothing hands off to is marked <b>◆ origination</b> — the top of the value stream. Most starts have an inbound hand-off; a few originate the work.</li></ul>" },

  { id: "authoring", title: "Authoring a process", html:
    "<p>Build visually — every structural change is validated, versioned, and audited (no engineering ticket).</p>"
    + "<ul><li><b>Add a step</b> — click <b>+ Step</b>, or drag a <b>+ Step</b> / <b>+ Approval step</b> tile from the palette onto the flow to insert it at that point.</li>"
    + "<li><b>New process</b> — <b>+ New process</b> in the palette; it starts with the default guardrail template.</li>"
    + "<li><b>Move</b> — drag any box. Positions are decorative (they never change the model or what an agent reads).</li>"
    + "<li><b>Reorder / remove / rename</b> a step — select it and use its properties panel.</li></ul>" },

  { id: "branching", title: "Branching: gateways, events & Connect", html:
    "<p>A linear process becomes a real graph when you <b>Enable branching</b>. Then:</p>"
    + "<ul><li><b>Gateways</b> — drag a <b>× Decision</b> (exclusive / XOR) or <b>+ Parallel</b> (fork-join / AND) tile onto the flow.</li>"
    + "<li><b>Events</b> — drag a <b>⏱ Timer</b> or <b>✉ Message</b> event tile (a timer firing, a message arriving).</li>"
    + "<li><b>Connect</b> — turn on <b>Connect</b>, click a node then its target to draw a flow. A banner shows you're in Connect mode and <b>dragging is paused</b>; press <b>Esc</b> (or click empty canvas) to leave — you can't get stuck in a mode.</li></ul>"
    + "<p><b>Edit anything in place.</b> Select a gateway to rename it, switch its type, and edit its outgoing branches — set or clear each branch's <b>condition</b> (e.g. <code>amount &gt; 500</code>) or remove a connection. Select an event to change its trigger, timer, or message. Gateways and events are <b>structural</b> — they carry no role or guardrail; the steps they route to do.</p>" },

  { id: "drilldown", title: "Sub-process drill-down", html:
    "<p>A step can expand into another whole process. Set a step's <b>drill-down</b> target in its properties, and it shows a <b>SUB</b> badge — <b>double-click</b> it to navigate in, and use the breadcrumb to come back. This is how a high-level map stays readable while the detail lives one level down.</p>" },

  { id: "roles", title: "Roles", html:
    "<p>Roles are <b>master data</b> — a role, never a named person, so coverage survives turnover. A role is referenced by process owners, step performers, and guardrail escalation paths.</p>"
    + "<ul><li><b>Every role reference is a link.</b> Click a performer on a step, a swimlane label, a RACI row, or a role in the landscape catalog to open the <b>role drawer</b> — its standing RACI, skills, and everywhere it's used — without leaving the flow.</li>"
    + "<li><b>Manage roles</b> (toolbar) — add a role, edit its name / RACI / skills, or retire it. A role that's still in use can't be retired until you reassign it.</li></ul>" },

  { id: "guardrails", title: "Guardrails & governance", html:
    "<p>Each step's AI <b>guardrail</b> is editable right in its properties panel — allowed and forbidden actions, the data scope, and the <b>escalate-if</b> condition that hands off to a human. Saving bumps a version, records who/why, and is <b>instantly live for agents</b> on their next call. No deploy.</p>"
    + "<p>Everything is governed the same way: a guardrail edit, a new step, a drawn flow, a renamed role — each is a <b>versioned, hash-chained event</b> on an append-only audit trail (ISO 9001 §7.5). Nothing is overwritten or silently deleted; retired items are kept, deprecated. That chain is tamper-evident.</p>" },

  { id: "approvals", title: "Approvals (the review gate)", html:
    "<p>Some changes shouldn't go live the moment one person clicks Save. When you edit a guardrail you can tick <b>“Submit for approval instead of saving directly.”</b> That queues the change as a <b>Change Request</b> — it does <i>not</i> touch the live model — and it waits in the <b>Approvals</b> queue (top of the screen; the badge shows how many are pending).</p>"
    + "<p>A reviewer opens the queue and <b>Approves</b> it — which applies the change through the exact same audited, versioned, hash-chained path a direct edit uses — or <b>Rejects</b> it with a reason (no model change). The proposer can <b>Withdraw</b> a request they no longer want.</p>"
    + "<ul><li><b>Separation of duties</b> is recorded: if the reviewer is also the proposer the decision is allowed but flagged <b>self-approved</b> on the trail.</li>"
    + "<li>If the model moved on and a queued change no longer applies cleanly, Approve surfaces the reason and leaves the request pending.</li>"
    + "<li>Every proposal, approval, rejection and withdrawal is itself an event on a tamper-evident chain.</li>"
    + "<li>A request can be <b>assigned</b> to a reviewer, and the queue is <b>live</b> — a new request pops a toast and updates the badge in every open window without a reload.</li>"
    + "<li><b>You</b> (top of the screen) is your identity: pick the role you act as — it's stored in this browser, recorded as the actor on your changes, and drives the <b>Assigned to me</b> tab (with an “Assign to me” button on each request). Opt in there to <b>desktop notifications</b> when work is assigned to you, and the browser-tab title shows a pending count.</li></ul>"
    + "<p><b>Policy — which changes need review.</b> The <b>Policy</b> tab in the Approvals window sets a mode per kind of change: <b>required</b> (a direct edit is refused — it must be submitted), <b>optional</b> (the editor offers the “Submit for approval” choice), or <b>off</b> (commits directly). The gate toggle appears on the guardrail, role, master-data (process / hierarchy), and strategy (enterprise, objective, KPI, and — on the X-matrix — initiatives, which you can also add) editors; setting a kind to <i>required</i> forces every one of its edits through review. Changing the policy is itself governed (who / when / why).</p>" },

  { id: "board", title: "Live board (Present mode)", html:
    "<p><b>▶ Present</b> (top of the screen) turns the canvas into a full-screen, touch-friendly <b>board</b> a leadership team can drive on a video wall. A dark bar switches between <b>Landscape, Architecture, OKRs, X-matrix, Alignment</b>, or opens any process flow; app chrome hides and the canvas fills the screen. <b>Esc</b> or <b>Exit</b> returns.</p>"
    + "<p>The pulsing green <b>live dot</b> means the board updates in <b>real time</b>: whenever anyone commits a governed change — from any window — every open board and canvas refreshes within about a second and a half. No reload. Approve a change on one screen and watch it appear on the wall.</p>" },

  { id: "landscape", title: "Landscape (the repository)", html:
    "<p><b>Landscape</b> (toolbar) is the whole organization at a glance: every process grouped by <b>APQC domain</b>, each card showing steps, agent steps, and whether its guardrail is reviewed or still default. Below are <b>catalogs</b> — roles, KPIs, and risks — each listing the processes that reference it. Click any card or catalog item to open it.</p>"
    + "<p>At the top, the <b>Value stream</b> draws the whole end-to-end chain: every process laid out left-to-right by where it sits in the flow, with arrows for each end&rarr;start hand-off. <b>◆ origination</b> processes (nothing feeds them) start the stream and <b>terminal</b> ones end it; click any node to open it. Build the chain by linking a process's red end to the next process (see <i>Start &amp; end conditions</i>).</p>" },

  { id: "share", title: "Share (read-only portal)", html:
    "<p><b>Share</b> (toolbar) mints an unguessable, revocable link to a process — or the whole landscape. Whoever holds it sees a clean, <b>read-only</b> viewer (Flowchart, Lanes, RACI, Checklist, guardrail details) at <code>/portal?token=…</code> — no editing. The view is always live, you can time-box or revoke a link any time, and it reports whether the model changed since you shared it.</p>"
    + "<p class='docs-note'>The link is an unguessable capability URL, not viewer sign-in; genuine external hosting with per-viewer authentication is a deployment step.</p>" },

  { id: "interop", title: "Import & export (BPMN, Visio)", html:
    "<p>Continuum interoperates both ways:</p>"
    + "<ul><li><b>Export BPMN</b> (toolbar) — download any process as standards-compliant <b>BPMN 2.0 XML</b> with its diagram; it opens in Camunda, bpmn.io, or Signavio. Agent steps become service tasks, human steps user tasks, plus gateways and timer/message events.</li>"
    + "<li><b>Import</b> (toolbar) — bring in a <b>BPMN 2.0</b> file <i>or</i> a <b>Visio</b> flowchart (<code>.vsdx</code>) as a new governed process. Preview shows exactly what it will create; nothing is written until you confirm. Visio decisions become gateways and connector labels become branch conditions.</li></ul>"
    + "<p class='docs-note'>Legacy binary <code>.vsd</code> isn't supported — open it in Visio and Save As <code>.vsdx</code>.</p>" },

  { id: "apps", title: "The other apps", html:
    "<p>The canvas is one of five surfaces over the same model. From the project root, <code>python3 run.py</code> starts them all:</p>"
    + "<ul><li><b>Governance</b> (:8787) — edit guardrails with the full change-control trail.</li>"
    + "<li><b>Dashboard</b> (:8788) — the strategy-to-execution standing report and §12 coverage metrics.</li>"
    + "<li><b>Canvas</b> (:8789) — this app.</li>"
    + "<li><b>Advisor</b> (:8790) — analyze a process / guardrail / anything against ISO 9001, APQC, and the Core Model.</li>"
    + "<li><b>Ask</b> (:8791) — ask a plain-English question; it writes a read-only query over the graph and answers with a table.</li></ul>"
    + "<p>Set <code>CONTINUUM_LLM_API_KEY</code> to light up the Advisor's AI reviewer and the Ask planner.</p>" },

  { id: "tips", title: "Tips", html:
    "<ul><li><b>Esc</b> leaves Connect mode; clicking empty canvas leaves Connect or clears the selection.</li>"
    + "<li>Drag a box to move it; <b>Tidy up</b> auto-arranges.</li>"
    + "<li>Every role reference, and every process card in the landscape, is clickable.</li>"
    + "<li>Nothing is destroyed — removed items are deprecated and stay on the audit trail.</li>"
    + "<li>New to the app? Take the <b>Guided Tour</b> (top of the screen).</li></ul>" },
];

function renderDocs() {
  var toc = DOCS.map(function (s) { return '<a href="#doc-' + s.id + '" data-doc="' + s.id + '">' + esc(s.title) + "</a>"; }).join("");
  var body = DOCS.map(function (s) { return '<section id="doc-' + s.id + '" class="docs-sec"><h2>' + esc(s.title) + "</h2>" + s.html + "</section>"; }).join("");
  document.getElementById("docs-toc").innerHTML = toc;
  document.getElementById("docs-content").innerHTML = body;
  document.getElementById("docs-toc").querySelectorAll("[data-doc]").forEach(function (a) {
    a.addEventListener("click", function (e) {
      e.preventDefault();
      var el = document.getElementById("doc-" + a.getAttribute("data-doc"));
      if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  });
}
(function () {
  var btn = document.getElementById("docs-btn"); if (!btn) return;
  var modal = document.getElementById("docs-modal");
  var built = false;
  btn.addEventListener("click", function () { if (!built) { renderDocs(); built = true; } modal.hidden = false; });
  document.getElementById("docs-close").addEventListener("click", function () { modal.hidden = true; });
  modal.addEventListener("click", function (e) { if (e.target === modal) modal.hidden = true; });
  document.getElementById("docs-search").addEventListener("input", function (e) {
    var q = e.target.value.trim().toLowerCase();
    document.querySelectorAll("#docs-content .docs-sec").forEach(function (sec) {
      sec.hidden = q && sec.textContent.toLowerCase().indexOf(q) < 0;
    });
    document.querySelectorAll("#docs-toc [data-doc]").forEach(function (a) {
      var sec = document.getElementById("doc-" + a.getAttribute("data-doc"));
      a.style.display = sec && sec.hidden ? "none" : "block";
    });
  });
})();

// ======================= GUIDED TOUR =======================
function tourReset() {
  ["share-modal", "roles-modal", "import-modal", "docs-modal", "appr-modal"].forEach(function (id) {
    var e = document.getElementById(id); if (e) e.hidden = true;
  });
  try { if (typeof closeRoleDrawer === "function") closeRoleDrawer(); } catch (e) {}
  try { if (typeof setConnect === "function") setConnect(false); } catch (e) {}
  if (window.state) { state.task = null; state.gwsel = null; state.evsel = null; }
}
function tourOpen(id) { tourReset(); try { if (typeof openProcess === "function") openProcess(id); } catch (e) {} }
function tourView(v) {
  var b = document.querySelector('.views [data-view="' + v + '"]'); if (b) b.click();
}
function tourOpenModalBtn(id) { tourReset(); var b = document.getElementById(id); if (b) b.click(); }
function openModalCard() { var m = document.querySelector(".modal:not([hidden]) .modal-card"); return m || null; }

var TOUR = [
  { title: "Welcome", steps: [
    { sel: ".brand", before: function () { tourOpen("CO.3.2.7"); }, title: "Welcome to Continuum",
      body: "This is the Process Canvas — an easy visual modeler on top of a <b>governed</b> process model. In a few minutes you'll see the whole thing, end to end. Use <b>Next</b>, or jump around with <b>Chapters</b>." },
    { sel: "#proc-list", title: "Your processes",
      body: "Every process in the organization is listed here. Selecting one opens it on the canvas." },
    { sel: "#canvas", title: "Three panes",
      body: "Center is the canvas. The left holds the palette; the right shows details for whatever you select. Let's read a process." },
  ]},
  { title: "Read a process", steps: [
    { sel: function () { return document.querySelector("#canvas g.tnode"); }, before: function () { tourOpen("CO.3.2.7"); tourView("flow"); },
      title: "The flowchart", body: "A process reads left to right: <code>start → steps → end</code>. The step with an <b>AI</b> badge is run by an agent; if its guardrail escalates, a branch to a human travels with it." },
    { sel: "#props", before: function () { tourOpen("CO.3.2.7"); state.task = "CO.3.2.7.t3"; if (typeof renderCenter === "function") renderCenter(); if (typeof renderProps === "function") renderProps(); },
      title: "A step's details", body: "Selecting a step shows who performs it, its data and KPIs, and its <b>guardrail</b> — right here, editable." },
    { sel: function () { return document.querySelector('#canvas .tip-node[data-node="__end__"]') || document.querySelector("#canvas circle.tip.end"); },
      before: function () { tourOpen("CO.3.2.7"); tourView("flow"); },
      title: "Start & end conditions", body: "The <b>green start</b> and <b>red end</b> chain processes together: click an <b>end</b> to link it to the next process's start. A start nothing feeds is an <b>◆ origination</b>; the rest show where the work comes from and goes next." },
  ]},
  { title: "The four views", steps: [
    { sel: ".views", before: function () { tourOpen("CO.3.2.7"); tourView("lanes"); }, title: "Lanes (swimlanes)",
      body: "Group steps by the role that performs them. Drag a step into another lane to reassign it." },
    { sel: ".views", before: function () { tourView("raci"); }, title: "RACI",
      body: "An accountability chart — Responsible / Accountable / Consulted — derived from the model, not hand-maintained." },
    { sel: ".views", before: function () { tourView("checklist"); }, title: "Checklist",
      body: "A printable run sheet you can tick through. Now back to the flow." },
  ]},
  { title: "Roles", steps: [
    { sel: function () { return document.querySelector("#canvas [data-role]"); }, before: function () { tourOpen("CO.3.2.7"); tourView("flow"); },
      title: "Roles are links", body: "The underlined name under a step is its role. Every role reference — here, in Lanes, in RACI, in the landscape — is clickable." },
    { sel: "#role-drawer", before: function () { tourOpen("CO.3.2.7"); if (typeof openRoleDrawer === "function") openRoleDrawer("role.ops.support_tier1"); },
      title: "The role drawer", body: "It opens as an overlay — the flow stays put underneath. See the role's standing RACI, skills, and everywhere it's used, and edit it in place." },
    { sel: function () { return openModalCard(); }, before: function () { tourOpenModalBtn("roles-btn"); },
      title: "Manage roles", body: "Add a role, or edit its name / RACI / skills. Roles are master data — a role, never a named person. A role still in use can't be retired until you reassign it." },
  ]},
  { title: "Guardrails & governance", steps: [
    { sel: "#props", before: function () { tourOpen("CO.3.2.7"); state.task = "CO.3.2.7.t3"; if (typeof renderCenter === "function") renderCenter(); if (typeof renderProps === "function") renderProps(); },
      title: "Edit a guardrail without a deploy", body: "A step's AI guardrail lives here — allowed actions, data scope, and the escalate-if that hands off to a human. Save it and it's versioned and <b>instantly live</b> for agents. No engineering ticket." },
    { sel: null, title: "Everything is audited",
      body: "A guardrail edit, a new step, a drawn flow, a renamed role — each is a <b>versioned, hash-chained event</b> on a tamper-evident trail. Nothing is overwritten; retired items are kept. One source of truth for the picture, the agents, and the reports." },
  ]},
  { title: "Build & branch", steps: [
    { sel: ".palette", before: function () { tourOpen("CO.3.2.7"); tourView("flow"); }, title: "Build visually",
      body: "Drag a tile onto the flow to add a step, a decision (× / +), or a timer/message event. Drag any box to move it; <b>Tidy up</b> auto-arranges." },
    { sel: "#connect", before: function () { tourOpen("CO.3.2.7"); tourView("flow"); }, title: "Connect mode",
      body: "Turn on <b>Connect</b> to draw a flow between two nodes. A banner shows you're connecting and dragging is paused — press <b>Esc</b> to leave. Select any decision afterward to rename it, switch its type, or label each branch with a condition." },
  ]},
  { title: "Review & present", steps: [
    { sel: "#f-approve", before: function () { tourOpen("CO.3.2.7"); state.task = "CO.3.2.7.t3"; if (typeof renderCenter === "function") renderCenter(); if (typeof renderProps === "function") renderProps(); },
      title: "Submit for approval", body: "Editing a guardrail? Tick this to route the change through <b>review</b> instead of saving it directly. It queues as a Change Request and doesn't touch the live model until someone approves it." },
    { sel: function () { return openModalCard(); }, before: function () { tourOpenModalBtn("approvals-btn"); },
      title: "The approval queue", body: "Pending changes wait here. A reviewer <b>Approves</b> — applying it through the same audited, versioned path a direct edit uses — or <b>Rejects</b> it with a reason; the proposer can <b>Withdraw</b>. Self-approval is allowed but flagged. Every decision is on the tamper-evident trail." },
    { sel: function () { return document.querySelector('.appr-tabs [data-af="policy"]'); },
      before: function () { tourReset(); document.getElementById("approvals-btn").click(); var t = document.querySelector('.appr-tabs [data-af="policy"]'); if (t) t.click(); },
      title: "Set what needs review", body: "The <b>Policy</b> tab decides which <i>kinds</i> of change need approval: <b>required</b> (must be submitted), <b>optional</b> (the editor offers the choice), or <b>off</b>. Set guardrails to <i>required</i> and every guardrail edit routes through review automatically." },
    { sel: "#who-btn", before: function () { tourReset(); },
      title: "Who you are", body: "Pick the role you act as — it's recorded as the actor on your changes and powers the <b>Assigned to me</b> view. Opt in to <b>desktop notifications</b> so new work reaches you even when this tab is in the background." },
    { sel: function () { return document.querySelector(".strat-edit"); },
      before: function () { tourReset(); state.stratTab = "okr"; document.getElementById("strategy-btn").click(); },
      title: "Edit strategy in place", body: "Objectives, KPIs, and the enterprise mission / vision / values are editable right on the OKR board — the <b>✎</b> pencil opens a governed edit, and the same approval policy applies as everywhere else." },
    { sel: "#present-btn", before: function () { tourReset(); tourOpen("CO.3.2.7"); tourView("flow"); },
      title: "Present — the live board", body: "Go full-screen and touch-friendly for a video wall: switch between <b>Landscape, OKRs, the X-matrix</b>, or open any process. <b>Esc</b> exits." },
    { sel: "#live-dot", title: "Everything is live",
      body: "The green dot means <b>real time</b>: commit a change in any window — approve one here — and every open board and canvas refreshes within about a second and a half. No reload." },
  ]},
  { title: "The big picture", steps: [
    { sel: "#canvas", before: function () { tourOpenModalBtn("landscape-btn"); }, title: "Landscape",
      body: "The whole organization by APQC domain, plus catalogs of roles, KPIs, and risks that thread across processes. At the top, the <b>Value stream</b> draws every end→start hand-off as one end-to-end chain. Click anything to open it." },
    { sel: function () { return openModalCard(); }, before: function () { tourOpenModalBtn("share-btn"); },
      title: "Share read-only", body: "Publish an unguessable, revocable link so anyone can <b>view</b> a process — flow, lanes, RACI, checklist — with no editing." },
    { sel: function () { return openModalCard(); }, before: function () { tourOpenModalBtn("import-btn"); },
      title: "Import & export", body: "Bring in <b>BPMN 2.0</b> or a <b>Visio</b> (.vsdx) diagram as a new governed process, or export any process to BPMN for Camunda / bpmn.io." },
    { sel: ".brand", before: function () { tourReset(); tourView("flow"); }, title: "That's the tour",
      body: "Explore freely — every edit is governed and audited. Open <b>Documentation</b> (top of the screen) for the full reference, or replay any <b>Chapter</b> of this tour." },
  ]},
];

var tour = { ci: 0, si: 0, active: false, onResize: null };
function tourStepsIn(ci) { return TOUR[ci] ? TOUR[ci].steps : []; }
function tourStart(ci, si) {
  tour.ci = ci || 0; tour.si = si || 0; tour.active = true;
  document.getElementById("tour-overlay").hidden = false;
  tour.onResize = function () { tourPosition(); };
  window.addEventListener("resize", tour.onResize);
  window.addEventListener("scroll", tour.onResize, true);
  tourShow();
}
function tourEnd() {
  tour.active = false;
  document.getElementById("tour-overlay").hidden = true;
  document.getElementById("tour-chaplist").hidden = true;
  if (tour.onResize) { window.removeEventListener("resize", tour.onResize); window.removeEventListener("scroll", tour.onResize, true); }
  tourReset();
}
function tourAdvance(d) {
  var steps = tourStepsIn(tour.ci);
  var ni = tour.si + d;
  if (ni < 0) { if (tour.ci > 0) { tour.ci--; tour.si = tourStepsIn(tour.ci).length - 1; } }
  else if (ni >= steps.length) { if (tour.ci < TOUR.length - 1) { tour.ci++; tour.si = 0; } else { tourEnd(); return; } }
  else { tour.si = ni; }
  tourShow();
}
function tourShow() {
  var step = tourStepsIn(tour.ci)[tour.si]; if (!step) return;
  try { if (step.before) step.before(); } catch (e) {}
  document.getElementById("tour-chap").textContent = TOUR[tour.ci].title;
  document.getElementById("tour-title").innerHTML = step.title;
  document.getElementById("tour-body").innerHTML = step.body;
  var total = 0, done = 0, idx = 0;
  TOUR.forEach(function (c, i) { total += c.steps.length; if (i < tour.ci) done += c.steps.length; });
  done += tour.si + 1;
  document.getElementById("tour-count").textContent = "Step " + done + " / " + total;
  document.getElementById("tour-back").disabled = (tour.ci === 0 && tour.si === 0);
  var last = (tour.ci === TOUR.length - 1 && tour.si === tourStepsIn(tour.ci).length - 1);
  document.getElementById("tour-next").textContent = last ? "Done" : "Next";
  // let the app render, then measure
  setTimeout(tourPosition, 90);
}
function tourPosition() {
  if (!tour.active) return;
  var step = tourStepsIn(tour.ci)[tour.si]; if (!step) return;
  var el = null;
  try { el = typeof step.sel === "function" ? step.sel() : (step.sel ? document.querySelector(step.sel) : null); } catch (e) {}
  var spot = document.getElementById("tour-spot"), pop = document.getElementById("tour-pop");
  if (!el) {
    spot.style.width = "0px"; spot.style.height = "0px";
    spot.style.left = (window.innerWidth / 2) + "px"; spot.style.top = (window.innerHeight * 0.42) + "px";
    pop.style.left = "50%"; pop.style.top = "50%"; pop.style.transform = "translate(-50%,-50%)";
    return;
  }
  try { el.scrollIntoView({ block: "center", inline: "center" }); } catch (e) {}
  var r = el.getBoundingClientRect(), pad = 6;
  spot.style.left = (r.left - pad) + "px"; spot.style.top = (r.top - pad) + "px";
  spot.style.width = (r.width + pad * 2) + "px"; spot.style.height = (r.height + pad * 2) + "px";
  pop.style.transform = "none";
  var pw = pop.offsetWidth || 320, ph = pop.offsetHeight || 190, gap = 14;
  var left = Math.min(Math.max(10, r.left), window.innerWidth - pw - 10);
  var top;
  if (r.bottom + gap + ph < window.innerHeight) top = r.bottom + gap;
  else if (r.top - gap - ph > 10) top = r.top - gap - ph;
  else { top = Math.max(10, window.innerHeight - ph - 10); left = Math.min(left, window.innerWidth - pw - 10); }
  pop.style.left = left + "px"; pop.style.top = top + "px";
}
function tourChapterMenu() {
  var box = document.getElementById("tour-chaplist");
  if (!box.hidden) { box.hidden = true; return; }
  box.innerHTML = TOUR.map(function (c, i) {
    return '<button type="button" data-ch="' + i + '" class="' + (i === tour.ci ? "on" : "") + '"><b>' + (i + 1) + ".</b> " + esc(c.title) + "</button>";
  }).join("");
  box.querySelectorAll("[data-ch]").forEach(function (b) {
    b.addEventListener("click", function () { box.hidden = true; tourStart(+b.getAttribute("data-ch"), 0); });
  });
  box.hidden = false;
}
(function () {
  var btn = document.getElementById("tour-btn"); if (!btn) return;
  btn.addEventListener("click", function () { tourStart(0, 0); });
  document.getElementById("tour-next").addEventListener("click", function () { tourAdvance(1); });
  document.getElementById("tour-back").addEventListener("click", function () { tourAdvance(-1); });
  document.getElementById("tour-x").addEventListener("click", tourEnd);
  document.getElementById("tour-chapters").addEventListener("click", tourChapterMenu);
  document.addEventListener("keydown", function (e) {
    if (!tour.active) return;
    if (e.key === "Escape") { var box = document.getElementById("tour-chaplist"); if (!box.hidden) { box.hidden = true; return; } tourEnd(); }
    else if (e.key === "ArrowRight") tourAdvance(1);
    else if (e.key === "ArrowLeft") tourAdvance(-1);
  });
})();
