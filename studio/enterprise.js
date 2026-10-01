  /* ---------------------------------------------------------------------
     14b. Enterprise modules — Estate, Atlas, Assure, Vitals and Ripple.
          All read and write the same STATE through ContinuumCore, the
          library the Postgres platform also uses, so the Studio and the
          platform can never disagree about what an edge means.
     --------------------------------------------------------------------- */

  var Core = window.ContinuumCore;
  var IsoPacks = window.ContinuumIsoPacks;
  var activeModule = "processes";
  var estateTab = "system";
  var atlasHeat = "maturity";
  var assurePack = "ISO 9001:2015";
  var assureFilter = "all";
  var vitalsFilter = "all";
  var procChanged = false;
  var BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL";
  var TASK_TAGS = ["task", "userTask", "serviceTask", "manualTask", "scriptTask", "sendTask", "receiveTask", "businessRuleTask", "subProcess", "adHocSubProcess", "callActivity", "exclusiveGateway", "parallelGateway", "inclusiveGateway", "eventBasedGateway", "complexGateway"];
  var taskCache = {};

  var LABEL = {
    lifecycle: { plan: "Planned", active: "Active", sunset: "Sunset", retired: "Retired" },
    criticality: { low: "Low", medium: "Medium", high: "High", critical: "Critical" },
    dataClass: { public: "Public", internal: "Internal", confidential: "Confidential", restricted: "Restricted" },
    autonomy: { assist: "Assist only", act_with_approval: "Acts with approval", autonomous: "Autonomous" },
    controlType: { preventive: "Preventive", detective: "Detective", corrective: "Corrective" },
    frequency: { daily: "Daily", weekly: "Weekly", monthly: "Monthly", quarterly: "Quarterly", semiannual: "Every 6 months", annual: "Annual" },
    result: { pass: "Pass", fail: "Fail", not_tested: "Not tested" },
    treatment: { mitigate: "Mitigate", accept: "Accept", transfer: "Transfer", avoid: "Avoid" },
    type: { process: "Process", task: "Task", capability: "Capability", application: "System", agent: "Agent", obligation: "Obligation", control: "Control", risk: "Risk" }
  };

  function todayIso() { return new Date().toISOString().slice(0, 10); }
  function reg() { return STATE.registry; }

  /* ---- tasks: derived from the BPMN, live from the modeler when open ---- */

  function tasksFromXml(xml) {
    if (!xml) return [];
    if (taskCache[xml]) return taskCache[xml];
    var out = [];
    try {
      var doc = new DOMParser().parseFromString(xml, "application/xml");
      TASK_TAGS.forEach(function (tag) {
        var nodes = doc.getElementsByTagNameNS(BPMN_NS, tag);
        for (var i = 0; i < nodes.length; i++) {
          out.push({ id: nodes[i].getAttribute("id"), name: nodes[i].getAttribute("name") || nodes[i].getAttribute("id"), type: "bpmn:" + tag.charAt(0).toUpperCase() + tag.slice(1) });
        }
      });
    } catch (e) { /* unparseable XML: no tasks */ }
    taskCache[xml] = out;
    return out;
  }

  function syncTasks() {
    var active = getActive();
    Object.keys(STATE.processes).forEach(function (id) {
      var p = STATE.processes[id];
      if (active && p.id === active.id && modeler) {
        try {
          p.tasks = modeler.get("elementRegistry").getAll().filter(function (e) { return e.type !== "label" && isGovernableType(e.type); })
            .map(function (e) { return { id: e.id, name: (e.businessObject && e.businessObject.name) || e.id, type: e.type }; });
          return;
        } catch (e) { /* fall back to XML */ }
      }
      p.tasks = tasksFromXml(p.bpmnXml);
    });
    return STATE;
  }

  function ws() { syncTasks(); return STATE; }

  function enterpriseInit() {
    var changes = Core.ensureWorkspace(STATE, IsoPacks);
    syncTasks();
    if (changes.length) STATE.meta = Object.assign({}, STATE.meta, { enterpriseMigratedAt: nowIso() });
    renderModuleBadge();
    return changes;
  }

  function markRegistryDirty() {
    dirty = true;
    updateSaveIndicator();
    renderModuleBadge();
    if (activeModule !== "processes") renderModule();
  }

  /* ---- module navigation ---- */

  function switchModule(m) {
    activeModule = m;
    $all(".module-btn").forEach(function (b) { b.classList.toggle("active", b.getAttribute("data-module") === m); });
    $("#app").classList.toggle("in-module", m !== "processes");
    if (m === "processes") {
      try { modeler && modeler.get("canvas").resized(); } catch (e) { /* not ready */ }
      renderPanel();
      refreshActiveView();
    } else {
      renderModule();
      $("#module-view").scrollTop = 0;
    }
  }

  function renderModule() {
    var root = $("#module-view");
    if (activeModule === "estate") root.innerHTML = renderEstate();
    else if (activeModule === "atlas") root.innerHTML = renderAtlas();
    else if (activeModule === "assure") root.innerHTML = renderAssure();
    else if (activeModule === "vitals") root.innerHTML = renderVitals();
    applyIcons(root);
    wireModule(root);
  }

  function renderModuleBadge() {
    var b = $("#vitals-badge");
    if (!b || !STATE.registry) return;
    var v = Core.vitals(ws(), todayIso());
    b.textContent = v.bySeverity.critical ? String(v.bySeverity.critical) : "";
    b.title = v.bySeverity.critical + " critical finding" + (v.bySeverity.critical === 1 ? "" : "s");
  }

  /* ---- shared bits ---- */

  function tag(text, cls, attrs) { return '<span class="tag ' + (cls || "") + '"' + (attrs || "") + ">" + escapeHtml(text) + "</span>"; }
  function lifecycleTag(l) { return tag(LABEL.lifecycle[l] || l, l === "active" ? "t-good" : l === "sunset" ? "t-warn" : l === "retired" ? "t-bad" : "t-quiet"); }
  function sevTag(s) { return tag(s === "critical" ? "Critical" : s === "warning" ? "Warning" : "Info", s === "critical" ? "t-bad" : s === "warning" ? "t-warn" : "t-quiet"); }
  function statusTag(s) { return tag(s === "covered" ? "Covered" : s === "partial" ? "Partial" : "Gap", s === "covered" ? "t-good" : s === "partial" ? "t-warn" : "t-bad"); }
  function linkTag(id, name) { return '<span class="tag link" data-open="' + escapeHtml(id) + '">' + escapeHtml(name) + "</span>"; }
  function nodeName(id) { var n = Core.nodeIndex(ws())[id]; return n ? n.name : id; }

  function usesOf(appId) {
    var out = [];
    Object.keys(STATE.processes).forEach(function (pid) {
      var p = STATE.processes[pid];
      if (p.links && p.links.applicationIds.indexOf(appId) >= 0) out.push({ id: p.id, label: p.name });
      Object.keys(p.elementGovernance || {}).forEach(function (el) {
        var eg = p.elementGovernance[el];
        if (eg.links && eg.links.applicationIds && eg.links.applicationIds.indexOf(appId) >= 0) {
          var t = (p.tasks || []).filter(function (x) { return x.id === el; })[0];
          out.push({ id: Core.taskNodeId(p.id, el), label: p.name + " › " + Core.decodeEntities(t ? t.name : el), procId: p.id, elementId: el });
        }
      });
    });
    return out;
  }

  function modHead(title, lead, actions) {
    return '<div class="mod-head"><div class="mod-head-text"><h1 class="mod-title">' + escapeHtml(title) + '</h1><p class="mod-lead">' + lead + "</p></div>" +
      '<div class="mod-actions">' + (actions || "") + "</div></div>";
  }

  /* ---- Estate (E3, E4) ---- */

  function renderEstate() {
    syncTasks();
    var apps = Object.keys(reg().applications).map(function (k) { return reg().applications[k]; });
    var systems = apps.filter(function (a) { return a.kind !== "agent"; });
    var agents = apps.filter(function (a) { return a.kind === "agent"; });
    var list = estateTab === "agent" ? agents : systems;
    list.sort(function (a, b) { return a.name < b.name ? -1 : 1; });
    var html = '<div class="mod-wrap">' +
      modHead("Estate", "Every system and AI agent the business runs on, with owner, lifecycle and what depends on it. Agents are governed like any other application: owner, lifecycle, the tasks they are bound to, and the guardrail that applies.",
        '<button class="btn" data-act="ripple-pick"><span class="ic" data-icon="ripple"></span> Ripple</button>' +
        '<button class="btn primary" data-act="new-app" data-kind="' + escapeHtml(estateTab) + '"><span class="ic" data-icon="plus"></span> Add ' + (estateTab === "agent" ? "agent" : "system") + "</button>") +
      '<div class="mod-bar"><div class="seg">' +
      '<button data-estate-tab="system" class="' + (estateTab === "system" ? "on" : "") + '">Systems<span class="n">' + systems.length + "</span></button>" +
      '<button data-estate-tab="agent" class="' + (estateTab === "agent" ? "on" : "") + '">Agents<span class="n">' + agents.length + "</span></button>" +
      "</div></div>";
    if (!list.length) {
      html += '<div class="ent-table-wrap"><div class="ent-empty">No ' + (estateTab === "agent" ? "agents" : "systems") + " yet. Add one to start mapping what the business depends on.</div></div></div>";
      return html;
    }
    html += '<div class="ent-table-wrap"><table class="ent-table"><thead><tr>';
    if (estateTab === "agent") {
      html += "<th>Agent</th><th>Autonomy</th><th>Owner</th><th>Bound to</th><th>Guardrail</th><th>Lifecycle</th><th></th></tr></thead><tbody>";
      list.forEach(function (a) {
        var uses = usesOf(a.id);
        var guard = uses.map(function (u) {
          var g = Core.effectiveGuardrail(STATE.processes[u.procId || u.id], u.elementId || null);
          return Core.isBlankGuardrail(g) ? tag("None — blocked", "t-bad") : tag(g.source === "task" ? "Task override" : "Process default", "t-good");
        }).join(" ");
        html += '<tr class="clickable" data-edit="' + escapeHtml(a.id) + '"><td><div class="ent-name">' + escapeHtml(a.name) + '</div><div class="ent-sub">' + escapeHtml((a.agent && a.agent.model) || a.vendor || "") + "</div></td>" +
          "<td>" + escapeHtml(LABEL.autonomy[a.agent && a.agent.autonomy] || "—") + "</td>" +
          "<td>" + (a.owner ? escapeHtml(a.owner) : tag("No owner", "t-bad")) + "</td>" +
          '<td><div class="ent-list">' + (uses.length ? uses.map(function (u) { return linkTag(u.id, u.label); }).join("") : tag("Not bound", "t-quiet")) + "</div></td>" +
          "<td>" + (guard || "—") + "</td>" +
          "<td>" + lifecycleTag(a.lifecycle) + "</td>" +
          '<td><div class="row-actions"><button class="icon-btn" data-ripple="' + escapeHtml(a.id) + '">Ripple</button></div></td></tr>';
      });
    } else {
      html += "<th>System</th><th>Lifecycle</th><th>Criticality</th><th>Owner</th><th>Serves</th><th>Used by</th><th></th></tr></thead><tbody>";
      list.forEach(function (a) {
        var uses = usesOf(a.id);
        html += '<tr class="clickable" data-edit="' + escapeHtml(a.id) + '"><td><div class="ent-name">' + escapeHtml(a.name) + '</div><div class="ent-sub">' + escapeHtml([a.vendor, LABEL.dataClass[a.dataClass]].filter(Boolean).join(" · ")) + "</div></td>" +
          "<td>" + lifecycleTag(a.lifecycle) + (a.sunsetDate && a.lifecycle !== "active" ? '<div class="ent-sub">' + escapeHtml(a.sunsetDate) + "</div>" : "") + "</td>" +
          "<td>" + escapeHtml(LABEL.criticality[a.criticality] || "—") + "</td>" +
          "<td>" + (a.owner ? escapeHtml(a.owner) : tag("No owner", "t-warn")) + "</td>" +
          '<td><div class="ent-list">' + (a.capabilityIds.length ? a.capabilityIds.map(function (c) { return linkTag(c, nodeName(c)); }).join("") : '<span class="ent-sub">—</span>') + "</div></td>" +
          '<td><div class="ent-list">' + (uses.length ? uses.map(function (u) { return linkTag(u.id, u.label); }).join("") : '<span class="ent-sub">Nothing yet</span>') + "</div></td>" +
          '<td><div class="row-actions"><button class="icon-btn" data-ripple="' + escapeHtml(a.id) + '">Ripple</button></div></td></tr>';
      });
    }
    html += "</tbody></table></div>" +
      '<p class="mod-note">Link systems and agents to processes and tasks from the Governance panel, or here from each record. An agent bound to a task inherits that task’s guardrail, or the process default.</p></div>';
    return html;
  }

  /* ---- Atlas (E3) ---- */

  function heatStyle(node) {
    if (atlasHeat === "maturity") {
      if (!node.maturity) return { cls: " empty", style: "", score: "—" };
      var pct = 8 + Math.round((node.maturity / 5) * 42);
      return { cls: "", style: "background:color-mix(in srgb, var(--accent) " + pct + "%, var(--surface));", score: node.maturity.toFixed(1) };
    }
    var n = node.allProcesses.length + node.allApps.length;
    if (!n) return { cls: " empty", style: "", score: "0" };
    var p = Math.min(50, 8 + n * 9);
    return { cls: "", style: "background:color-mix(in srgb, var(--accent) " + p + "%, var(--surface));", score: String(n) };
  }

  function renderAtlas() {
    var tree = Core.atlas(ws());
    var html = '<div class="mod-wrap">' +
      modHead("Atlas", "What the business does, as capabilities, heat-mapped by ISO 9004 maturity of the processes that deliver them, or by how much supports them. Select a capability to edit it or see what it depends on.",
        '<button class="btn primary" data-act="new-cap"><span class="ic" data-icon="plus"></span> Add capability</button>') +
      '<div class="mod-bar"><div class="seg">' +
      '<button data-heat="maturity" class="' + (atlasHeat === "maturity" ? "on" : "") + '">Maturity</button>' +
      '<button data-heat="coverage" class="' + (atlasHeat === "coverage" ? "on" : "") + '">Coverage</button></div>' +
      '<div class="atlas-legend">' + (atlasHeat === "maturity"
        ? '<span class="sw" style="background:var(--surface);border-style:dashed"></span>No process <span class="sw" style="background:color-mix(in srgb, var(--accent) 16%, var(--surface))"></span>1–2 <span class="sw" style="background:color-mix(in srgb, var(--accent) 33%, var(--surface))"></span>3 <span class="sw" style="background:color-mix(in srgb, var(--accent) 50%, var(--surface))"></span>4–5'
        : '<span class="sw" style="background:var(--surface);border-style:dashed"></span>Nothing mapped <span class="sw" style="background:color-mix(in srgb, var(--accent) 20%, var(--surface))"></span>Some <span class="sw" style="background:color-mix(in srgb, var(--accent) 50%, var(--surface))"></span>Well supported') +
      "</div></div>";
    if (!tree.length) return html + '<div class="ent-table-wrap"><div class="ent-empty">No capabilities yet. Start with five to eight top-level capabilities — what the business does, not how.</div></div></div>';
    html += '<div class="atlas-grid">';
    tree.forEach(function (l1) {
      html += '<div class="atlas-l1"><div class="atlas-l1-head" data-edit="' + escapeHtml(l1.id) + '"><span class="atlas-l1-name">' + escapeHtml(l1.name) + '</span><span class="atlas-l1-meta">' +
        l1.allProcesses.length + "P · " + l1.allApps.length + "S</span></div><div class=\"atlas-tiles\">";
      var tiles = l1.children.length ? l1.children : [l1];
      tiles.forEach(function (c) {
        var h = heatStyle(c);
        var badges = "";
        if (c.overlap) badges += tag("Overlap: " + c.overlap.length + " systems", "t-warn", ' title="' + escapeHtml(c.overlap.join(", ")) + '"');
        if (c.importance === "critical") badges += tag("Critical", "t-accent");
        if (!c.allProcesses.length) badges += tag("No process", "t-quiet");
        html += '<div class="atlas-tile' + h.cls + '" style="' + h.style + '" data-edit="' + escapeHtml(c.id) + '">' +
          '<div class="atlas-tile-name">' + escapeHtml(c.name) + '</div><span class="atlas-tile-score" title="' + (atlasHeat === "maturity" ? "Average ISO 9004 maturity" : "Processes + systems") + '">' + h.score + "</span>" +
          '<div class="atlas-tile-meta">' + c.allProcesses.length + " process" + (c.allProcesses.length === 1 ? "" : "es") + " · " + c.allApps.length + " system" + (c.allApps.length === 1 ? "" : "s") + "</div>" +
          (badges ? '<div class="atlas-tile-badges">' + badges + "</div>" : "") +
          (c.children.length ? '<div class="atlas-l3">' + c.children.map(function (k) { return '<span class="tag link" data-edit="' + escapeHtml(k.id) + '">' + escapeHtml(k.name) + "</span>"; }).join("") + "</div>" : "") +
          "</div>";
      });
      html += "</div></div>";
    });
    html += '</div><p class="mod-note">Maturity is the average ISO 9004 self-assessment (1–5) of the processes that realize a capability, rolled up from its sub-capabilities. Overlap flags two or more active systems serving the same capability — a consolidation candidate.</p></div>';
    return html;
  }

  /* ---- Assure (E2) ---- */

  function renderAssure() {
    var a = Core.assure(ws(), todayIso());
    if (!a.packs.some(function (p) { return p.source === assurePack; }) && a.packs.length) assurePack = a.packs[0].source;
    var pk = a.packs.filter(function (p) { return p.source === assurePack; })[0];
    var html = '<div class="mod-wrap">' +
      modHead("Assure", "Every clause you are held to, mapped to the processes, systems and controls that meet it, with the evidence an auditor will ask for.",
        '<button class="btn" data-act="auditor-pack"><span class="ic" data-icon="download"></span> Auditor pack</button>' +
        '<button class="btn primary" data-act="new-obl"><span class="ic" data-icon="plus"></span> Add obligation</button>') +
      '<div class="mod-bar"><div class="seg">' + a.packs.map(function (p) {
        return '<button data-pack="' + escapeHtml(p.source) + '" class="' + (p.source === assurePack ? "on" : "") + '">' + escapeHtml(p.source) + '<span class="n">' + p.total + "</span></button>";
      }).join("") + "</div>" +
      '<div class="seg">' + ["all", "gap", "partial", "covered"].map(function (f) {
        return '<button data-afilter="' + f + '" class="' + (assureFilter === f ? "on" : "") + '">' + (f === "all" ? "All" : f === "gap" ? "Gaps" : f === "partial" ? "Partial" : "Covered") + "</button>";
      }).join("") + "</div></div>";
    if (!pk) return html + '<div class="ent-table-wrap"><div class="ent-empty">No obligations yet.</div></div></div>';
    var t = pk.total || 1;
    html += '<div class="assure-summary"><div class="big-num">' + pk.coverage + '%<small>covered</small></div><div>' +
      '<div class="stack-bar"><span class="s-cov" style="width:' + (pk.covered / t * 100) + '%"></span><span class="s-par" style="width:' + (pk.partial / t * 100) + '%"></span><span class="s-gap" style="width:' + (pk.gap / t * 100) + '%"></span></div>' +
      '<div class="stack-legend"><span><i style="background:var(--good)"></i>' + pk.covered + ' covered</span><span><i style="background:var(--warn)"></i>' + pk.partial + ' partial</span><span><i style="background:var(--surface-3);border:1px solid var(--border-strong)"></i>' + pk.gap + " gap</span></div></div></div>";
    var rows = pk.rows.filter(function (r) { return assureFilter === "all" || r.status === assureFilter; });
    html += '<div class="ent-table-wrap"><table class="ent-table"><thead><tr><th>Clause</th><th>Requirement</th><th>Mapped to</th><th>Evidence</th><th>Status</th></tr></thead><tbody>';
    if (!rows.length) html += '<tr><td colspan="5"><div class="ent-empty">Nothing in this filter.</div></td></tr>';
    rows.forEach(function (r) {
      var mapped = r.processes.map(function (p) { return linkTag(p.id, p.name); }).concat(r.applications.map(function (x) { return linkTag(x.id, x.name); }), r.controls.map(function (c) { return linkTag(c.id, c.name); })).join("");
      html += '<tr class="clickable" data-edit="' + escapeHtml(r.obligation.id) + '"><td class="clause">§' + escapeHtml(r.obligation.clause) + "</td>" +
        '<td><div class="ent-name">' + escapeHtml(r.obligation.title) + '</div><div class="ent-sub">' + escapeHtml(r.obligation.summary || "") + "</div></td>" +
        '<td><div class="ent-list">' + (mapped || '<span class="ent-sub">Nothing mapped</span>') + "</div></td>" +
        "<td>" + (r.evidence.length ? r.evidence.map(function (e) { return '<div class="ev-line ' + (e.failing ? "bad" : e.good ? "good" : "meh") + '">' + escapeHtml(e.label) + "</div>"; }).join("") : '<span class="ent-sub">—</span>') + "</td>" +
        '<td title="' + escapeHtml(r.reason) + '">' + statusTag(r.status) + (r.status === "partial" ? '<div class="ent-sub">' + escapeHtml(r.reason) + "</div>" : "") + "</td></tr>";
    });
    html += "</tbody></table></div>" +
      '<p class="mod-note">' + escapeHtml(IsoPacks.notice) + " Covered = an approved, in-review-date process or an in-date passing control is on record. A failed control always drops a clause to Partial.</p></div>";
    return html;
  }

  function downloadAuditorPack() {
    var a = Core.assure(ws(), todayIso());
    var pk = a.packs.filter(function (p) { return p.source === assurePack; })[0];
    if (!pk) return;
    var rowsHtml = pk.rows.map(function (r) {
      return "<tr><td>§" + escapeHtml(r.obligation.clause) + "</td><td><b>" + escapeHtml(r.obligation.title) + "</b><br><small>" + escapeHtml(r.obligation.summary || "") + "</small></td><td>" +
        r.processes.concat(r.applications, r.controls).map(function (x) { return escapeHtml(x.name); }).join("<br>") + "</td><td>" +
        r.evidence.map(function (e) { return (e.failing ? "✕ " : e.good ? "✓ " : "○ ") + escapeHtml(e.label); }).join("<br>") + "</td><td>" + r.status + "</td></tr>";
    }).join("");
    var doc = "<!doctype html><meta charset=\"utf-8\"><title>Auditor pack — " + escapeHtml(pk.source) + "</title>" +
      "<style>body{font:13px/1.5 system-ui,sans-serif;color:#152220;margin:32px;}h1{font-size:20px;margin:0 0 4px}p{color:#4E5F5A}table{border-collapse:collapse;width:100%;margin-top:16px}th,td{border:1px solid #D7E0DC;padding:7px 9px;vertical-align:top;text-align:left}th{background:#EEF2F0;font-size:11px;text-transform:uppercase;letter-spacing:.04em}small{color:#7C8C87}</style>" +
      "<h1>Auditor pack · " + escapeHtml(pk.source) + "</h1><p>Generated " + escapeHtml(todayIso()) + " from Continuum Studio. Coverage " + pk.coverage + "% — " + pk.covered + " covered, " + pk.partial + " partial, " + pk.gap + " gap.</p>" +
      "<p><small>" + escapeHtml(IsoPacks.notice) + "</small></p><table><thead><tr><th>Clause</th><th>Requirement</th><th>Mapped to</th><th>Evidence</th><th>Status</th></tr></thead><tbody>" + rowsHtml + "</tbody></table>";
    var base = "auditor-pack-" + pk.source.toLowerCase().replace(/[^a-z0-9]+/g, "-");
    offerDownload(base + ".html", doc, "text/html");
  }

  /* ---- Vitals (E10) ---- */

  function ring(score) {
    var r = 38, c = 2 * Math.PI * r, off = c * (1 - score / 100);
    var col = score >= 80 ? "var(--good)" : score >= 60 ? "var(--warn)" : "var(--danger)";
    return '<svg class="vitals-ring" viewBox="0 0 92 92" role="img" aria-label="Model health ' + score + '%"><circle cx="46" cy="46" r="' + r + '" fill="none" stroke="var(--surface-3)" stroke-width="9"/>' +
      '<circle cx="46" cy="46" r="' + r + '" fill="none" stroke="' + col + '" stroke-width="9" stroke-linecap="round" stroke-dasharray="' + c.toFixed(1) + '" stroke-dashoffset="' + off.toFixed(1) + '" transform="rotate(-90 46 46)"/>' +
      '<text x="46" y="51" text-anchor="middle" font-size="19" font-weight="700" fill="var(--ink)" font-family="var(--font-ui)">' + score + "%</text></svg>";
  }

  function renderVitals() {
    var v = Core.vitals(ws(), todayIso());
    var list = v.findings.filter(function (f) { return vitalsFilter === "all" || f.severity === vitalsFilter; });
    var html = '<div class="mod-wrap">' +
      modHead("Vitals", "Is the model still true? Vitals checks every process, system, agent, control and risk against simple rules — owners, review dates, guardrails, test results, sunset systems still in use — so stale records surface before an auditor or an agent finds them.", '<button class="btn" data-act="ripple-pick"><span class="ic" data-icon="ripple"></span> Ripple</button>') +
      '<div class="vitals-top">' + ring(v.score) + '<div><div class="ent-name" style="font-size:14px;margin-bottom:8px;">Model health · ' + v.passed + " of " + v.checks + ' checks pass</div><div class="sev-row">' +
      '<div class="sev-card"><div class="n" style="color:var(--danger)">' + v.bySeverity.critical + '</div><div class="l">Critical</div></div>' +
      '<div class="sev-card"><div class="n" style="color:var(--warn)">' + v.bySeverity.warning + '</div><div class="l">Warning</div></div>' +
      '<div class="sev-card"><div class="n" style="color:var(--ink-faint)">' + v.bySeverity.info + '</div><div class="l">Info</div></div></div></div></div>' +
      '<div class="mod-bar"><div class="seg">' + ["all", "critical", "warning", "info"].map(function (f) {
        return '<button data-vfilter="' + f + '" class="' + (vitalsFilter === f ? "on" : "") + '">' + (f === "all" ? "All" : f.charAt(0).toUpperCase() + f.slice(1)) + '<span class="n">' + (f === "all" ? v.findings.length : v.bySeverity[f]) + "</span></button>";
      }).join("") + "</div></div>";
    html += '<div class="ent-table-wrap">';
    if (!list.length) html += '<div class="ent-empty">' + (v.findings.length ? "Nothing in this filter." : "No findings — the model is in good health.") + "</div>";
    list.forEach(function (f) {
      var canRipple = f.nodeId && (f.nodeType === "application" || f.nodeType === "agent" || f.nodeType === "control" || f.nodeType === "risk");
      html += '<div class="finding"><div>' + sevTag(f.severity) + '</div><div><div class="finding-name">' +
        (f.nodeId ? '<span class="tag link type-tag" data-open="' + escapeHtml(f.nodeId) + '">' + escapeHtml(LABEL.type[f.nodeType] || f.nodeType) + "</span> " : '<span class="tag type-tag">' + escapeHtml(f.nodeType === "pack" ? "Assure" : f.nodeType) + "</span> ") +
        escapeHtml(f.name) + '</div><div class="finding-msg">' + escapeHtml(f.message) + '</div><div class="finding-hint">' + escapeHtml(f.hint) + "</div></div>" +
        '<div class="row-actions">' + (canRipple ? '<button class="icon-btn" data-ripple="' + escapeHtml(f.nodeId) + '">Ripple</button>' : "") +
        (f.nodeId ? '<button class="icon-btn" data-open="' + escapeHtml(f.nodeId) + '">Open</button>' : f.nodeType === "pack" ? '<button class="icon-btn" data-goto="assure" data-pack-name="' + escapeHtml(f.name) + '">Open Assure</button>' : "") + "</div></div>";
    });
    html += '</div><p class="mod-note">Health is the share of rule checks that pass. Critical findings also show as a badge on Vitals in the top bar.</p></div>';
    return html;
  }

  /* ---- module wiring ---- */

  function wireModule(root) {
    $all("[data-estate-tab]", root).forEach(function (b) { b.onclick = function () { estateTab = b.getAttribute("data-estate-tab"); renderModule(); }; });
    $all("[data-heat]", root).forEach(function (b) { b.onclick = function () { atlasHeat = b.getAttribute("data-heat"); renderModule(); }; });
    $all("[data-pack]", root).forEach(function (b) { b.onclick = function () { assurePack = b.getAttribute("data-pack"); renderModule(); }; });
    $all("[data-afilter]", root).forEach(function (b) { b.onclick = function () { assureFilter = b.getAttribute("data-afilter"); renderModule(); }; });
    $all("[data-vfilter]", root).forEach(function (b) { b.onclick = function () { vitalsFilter = b.getAttribute("data-vfilter"); renderModule(); }; });
    $all("[data-goto]", root).forEach(function (b) { b.onclick = function () { if (b.getAttribute("data-pack-name")) assurePack = b.getAttribute("data-pack-name"); switchModule(b.getAttribute("data-goto")); }; });
    $all("[data-ripple]", root).forEach(function (b) { b.onclick = function (e) { e.stopPropagation(); openRipple(b.getAttribute("data-ripple")); }; });
    $all("[data-open]", root).forEach(function (b) { b.onclick = function (e) { e.stopPropagation(); openNode(b.getAttribute("data-open")); }; });
    $all("[data-edit]", root).forEach(function (b) { b.onclick = function (e) { e.stopPropagation(); openEditor(b.getAttribute("data-edit")); }; });
    $all("[data-act]", root).forEach(function (b) {
      b.onclick = function () {
        var act = b.getAttribute("data-act");
        if (act === "new-app") openEditor(null, "application", { kind: b.getAttribute("data-kind") || "system" });
        else if (act === "new-cap") openEditor(null, "capability");
        else if (act === "new-obl") openEditor(null, "obligation");
        else if (act === "auditor-pack") downloadAuditorPack();
        else if (act === "ripple-pick") openRipplePicker();
      };
    });
  }

  /** Opens anything by node id: processes and tasks jump to the modeler,
   *  registry records open their editor. */
  function openNode(id) {
    var t = Core.parseTaskNodeId(id);
    if (STATE.processes[id] || t) {
      closeModal();
      var pid = t ? t.procId : id;
      switchModule("processes");
      if (STATE.activeId !== pid) switchToProcess(pid);
      if (!t) return;
      var tries = 0;
      (function selectWhenReady() {
        tries++;
        try {
          var el = STATE.activeId === pid && modeler && modeler.get("elementRegistry").get(t.elementId);
          if (el) { modeler.get("selection").select(el); activeTab = "governance"; renderPanelTabs(); renderPanel(); return; }
        } catch (e) { /* modeler still importing */ }
        if (tries < 30) setTimeout(selectWhenReady, 100);
      })();
      return;
    }
    openEditor(id);
  }

  /* ---- Ripple (E5) ---- */

  var GROUP_ORDER = [["task", "Tasks"], ["process", "Processes"], ["capability", "Capabilities"], ["application", "Systems"], ["agent", "Agents"], ["control", "Controls"], ["obligation", "Obligations"], ["risk", "Risks"]];

  function openRipple(id) {
    var r = Core.ripple(ws(), id);
    if (!r.start) { toast("Nothing to trace for that item."); return; }
    var PL = { task: ["task", "tasks"], process: ["process", "processes"], capability: ["capability", "capabilities"], application: ["system", "systems"], agent: ["agent", "agents"], obligation: ["obligation", "obligations"], control: ["control", "controls"], risk: ["risk", "risks"] };
    var counts = GROUP_ORDER.filter(function (g) { return r.counts[g[0]]; }).map(function (g) { var n = r.counts[g[0]]; return tag(n + " " + PL[g[0]][n === 1 ? 0 : 1], "t-accent"); }).join("") +
      (r.kpis.length ? tag(r.kpis.length + " KPI" + (r.kpis.length === 1 ? "" : "s"), "t-accent") : "");
    var body = '<div class="ripple-summary">' + escapeHtml(r.summary) + "</div>" + (counts ? '<div class="ripple-counts">' + counts + "</div>" : "");
    GROUP_ORDER.forEach(function (g) {
      var items = r.affected.filter(function (a) { return a.type === g[0]; }).sort(function (a, b) { return a.depth - b.depth; });
      if (!items.length) return;
      body += '<div class="ripple-group"><div class="ripple-group-title">' + g[1] + "</div>" + items.map(function (a) {
        var path = '<b>' + escapeHtml(r.start.name) + "</b> " + a.path.map(function (s, i) { return escapeHtml(s.verb) + " " + (i === a.path.length - 1 ? "" : "<b>" + escapeHtml(s.name) + "</b> "); }).join("");
        return '<div class="ripple-item" data-open="' + escapeHtml(a.id) + '"><div><div class="ripple-item-name">' + escapeHtml(a.name) + '</div><div class="ripple-path">' + path + '</div></div><div class="ripple-depth">' + a.depth + " hop" + (a.depth === 1 ? "" : "s") + "</div></div>";
      }).join("") + "</div>";
    });
    if (r.kpis.length) {
      body += '<div class="ripple-group"><div class="ripple-group-title">KPIs to watch</div><div class="ent-list">' + r.kpis.map(function (k) { return tag(k.name + " · " + k.procName + (k.task ? " › " + k.task : "")); }).join("") + "</div></div>";
    }
    if (r.guardrails.length) {
      body += '<div class="ripple-group"><div class="ripple-group-title">Agent guardrails in the path</div>' + r.guardrails.map(function (g) {
        return '<div class="ripple-item" data-open="' + escapeHtml(g.taskId) + '"><div><div class="ripple-item-name">' + escapeHtml(g.task) + " · " + escapeHtml(g.procName) + '</div><div class="ripple-path">' + escapeHtml(g.agents.join(", ")) + " act under <b>" + escapeHtml(g.version) + "</b> (" + (g.source === "task" ? "task override" : "process default") + ")</div></div><div>" + (g.blank ? tag("No guardrail", "t-bad") : tag("Re-check", "t-warn")) + "</div></div>";
      }).join("") + "</div>";
    }
    if (!r.affected.length) body += '<div class="ent-empty">Nothing else in the model depends on this yet. Link it to processes, tasks or controls to see its reach.</div>';
    openModal(
      '<div class="modal-head"><span class="modal-title">Ripple · ' + escapeHtml(r.start.name) + ' <span class="tag type-tag">' + escapeHtml(LABEL.type[r.start.type] || r.start.type) + "</span></span>" +
      '<button class="modal-close" id="modal-x"><span class="ic" data-icon="close"></span></button></div>' +
      '<div class="modal-body">' + body + "</div>" +
      '<div class="modal-foot"><span class="grow" style="font-size:11.5px;color:var(--ink-faint);align-self:center;">' + (r.mode === "upstream" ? "Showing what this capability depends on." : "Showing everything downstream of a change.") + '</span><button class="btn" id="rp-json"><span class="ic" data-icon="download"></span> Export (.json)</button><button class="btn primary" id="rp-close">Done</button></div>',
      function (root) {
        root.querySelector(".modal").classList.add("ripple");
        $("#modal-x", root).onclick = closeModal;
        $("#rp-close", root).onclick = closeModal;
        $("#rp-json", root).onclick = function () { offerDownload("ripple-" + Core.slug(r.start.name) + ".json", JSON.stringify(r, null, 2)); };
        $all("[data-open]", root).forEach(function (n) { n.onclick = function () { openNode(n.getAttribute("data-open")); }; });
      }
    );
  }

  function openRipplePicker() {
    var idx = Core.nodeIndex(ws());
    var all = Object.keys(idx).map(function (k) { return idx[k]; }).filter(function (n) { return n.type !== "obligation" || true; });
    function listHtml(q) {
      q = (q || "").toLowerCase();
      var out = "";
      GROUP_ORDER.forEach(function (g) {
        var items = all.filter(function (n) { return n.type === g[0] && (!q || n.name.toLowerCase().indexOf(q) >= 0); }).slice(0, g[0] === "obligation" ? 12 : 40);
        if (!items.length) return;
        out += '<div class="ripple-group-title" style="margin-top:8px">' + g[1] + "</div>" + items.map(function (n) {
          return '<div class="picker-item" data-pick="' + escapeHtml(n.id) + '"><span class="tag type-tag">' + escapeHtml(LABEL.type[n.type]) + "</span>" + escapeHtml(n.name) + "</div>";
        }).join("");
      });
      return out || '<div class="ent-empty">No match.</div>';
    }
    openModal(
      '<div class="modal-head"><span class="modal-title">Ripple — pick anything to see what it touches</span><button class="modal-close" id="modal-x"><span class="ic" data-icon="close"></span></button></div>' +
      '<div class="modal-body"><input class="mod-search" id="rp-q" style="width:100%" placeholder="Search systems, agents, processes, tasks, clauses, controls, risks…"><div class="picker-list" id="rp-list">' + listHtml("") + "</div></div>",
      function (root) {
        root.querySelector(".modal").classList.add("wide");
        $("#modal-x", root).onclick = closeModal;
        function wire() { $all("[data-pick]", root).forEach(function (n) { n.onclick = function () { openRipple(n.getAttribute("data-pick")); }; }); }
        wire();
        $("#rp-q", root).focus();
        $("#rp-q", root).addEventListener("input", function () { $("#rp-list", root).innerHTML = listHtml(this.value); applyIcons(root); wire(); });
      }
    );
  }

  /* ---- linkers ---- */

  function optionsFor(refType) {
    syncTasks();
    if (refType === "process") return STATE.order.filter(function (id) { return STATE.processes[id]; }).map(function (id) { return { id: id, label: STATE.processes[id].name }; });
    if (refType === "task") {
      var out = [];
      STATE.order.forEach(function (pid) {
        var p = STATE.processes[pid]; if (!p) return;
        (p.tasks || []).forEach(function (t) { out.push({ id: Core.taskNodeId(pid, t.id), label: p.name + " › " + Core.decodeEntities(t.name) }); });
      });
      return out;
    }
    var key = Core.KEY_OF_TYPE[refType === "agent" || refType === "system" ? "application" : refType];
    return Object.keys(reg()[key]).map(function (k) { return reg()[key][k]; })
      .filter(function (o) { return refType === "agent" ? o.kind === "agent" : refType === "system" ? o.kind !== "agent" : true; })
      .map(function (o) { return { id: o.id, label: refType === "obligation" ? o.source + " §" + o.clause + " " + o.title : o.name + (refType === "application" && o.kind === "agent" ? " (agent)" : "") }; })
      .sort(function (a, b) { return refType === "obligation" ? 0 : a.label < b.label ? -1 : 1; });
  }

  function linkerHtml(key, label, refType, ids, hint) {
    var opts = optionsFor(refType);
    var byId = {}; opts.forEach(function (o) { byId[o.id] = o.label; });
    var chips = ids.filter(function (id) { return byId[id]; }).map(function (id) {
      return '<span class="tag t-accent chip-l" title="' + escapeHtml(byId[id]) + '"><span class="tl">' + escapeHtml(byId[id]) + '</span><span class="x" data-unlink="' + escapeHtml(id) + '" title="Remove link">×</span></span>';
    }).join("");
    var rest = opts.filter(function (o) { return ids.indexOf(o.id) < 0; });
    var canNew = refType !== "process" && refType !== "task";
    return '<div class="field"><label>' + escapeHtml(label) + '</label><div class="linker" data-linker="' + key + '" data-ref="' + refType + '"><div class="linker-chips">' + chips + "</div>" +
      '<select><option value="">+ Link ' + escapeHtml(LABEL.type[refType === "system" ? "application" : refType] ? (LABEL.type[refType === "system" ? "application" : refType]).toLowerCase() : refType) + "…</option>" +
      rest.map(function (o) { return '<option value="' + escapeHtml(o.id) + '">' + escapeHtml(o.label) + "</option>"; }).join("") +
      (canNew ? '<option value="__new__">＋ New…</option>' : "") + "</select></div>" + (hint ? '<div class="hint">' + hint + "</div>" : "") + "</div>";
  }

  /** Wires every linker inside root. getIds(key) / setIds(key, ids) are the
   *  only way a linker touches data, so the canonical edge storage stays in
   *  one place (see continuum-core.js header). */
  function wireLinkers(root, getIds, setIds, rerender, hooks) {
    hooks = hooks || {};
    $all("[data-linker]", root).forEach(function (box) {
      var key = box.getAttribute("data-linker");
      var refType = box.getAttribute("data-ref");
      var sel = box.querySelector("select");
      sel.onchange = function () {
        var v = sel.value;
        if (!v) return;
        if (v === "__new__") {
          sel.value = "";
          var type = refType === "agent" || refType === "system" ? "application" : refType;
          if (hooks.beforeNew) hooks.beforeNew();
          openEditor(null, type, refType === "agent" ? { kind: "agent" } : refType === "system" ? { kind: "system" } : {}, function (newId) {
            setIds(key, getIds(key).concat([newId]));
            rerender();
          }, hooks.onChildClosed);
          return;
        }
        setIds(key, getIds(key).concat([v]));
        rerender();
      };
      $all("[data-unlink]", box).forEach(function (x) {
        x.onclick = function () {
          var id = x.getAttribute("data-unlink");
          setIds(key, getIds(key).filter(function (i) { return i !== id; }));
          rerender();
        };
      });
    });
  }

  /* ---- Governance panel additions ---- */

  function panelProcessLinks(proc) {
    Core.ensureProcLinks(proc);
    return '<div class="field-group"><div class="field-group-title">Enterprise links · Atlas, Estate, Assure</div>' +
      linkerHtml("capabilityIds", "Capabilities this process realizes", "capability", proc.links.capabilityIds) +
      linkerHtml("applicationIds", "Systems and agents used across the process", "application", proc.links.applicationIds, "Link a system to a single task from the task’s own Governance tab.") +
      linkerHtml("obligationIds", "Obligations this process helps meet", "obligation", proc.links.obligationIds) +
      '<button class="btn full panel-ripple" data-panel-ripple="' + escapeHtml(proc.id) + '"><span class="ic" data-icon="ripple"></span> Ripple this process</button></div>';
  }

  function panelRiskLinker(proc) {
    Core.ensureProcLinks(proc);
    return linkerHtml("riskIds", "Risks", "risk", proc.links.riskIds, "Risks are real records with likelihood, impact and controls. Edit them in Assure or from here.");
  }

  function panelElementLinks(proc, el) {
    var eg = Core.ensureElementLinks(proc, el.id);
    var g = Core.effectiveGuardrail(proc, el.id);
    var agentsHere = eg.links.applicationIds.filter(function (id) { return reg().applications[id] && reg().applications[id].kind === "agent"; });
    return '<div class="field-group"><div class="field-group-title">Systems, agents and controls</div>' +
      linkerHtml("applicationIds", "Systems and agents used in this step", "application", eg.links.applicationIds, agentsHere.length ? (Core.isBlankGuardrail(g) ? "<b style=\"color:var(--danger)\">An agent is bound here but no guardrail applies.</b>" : "Bound agents act under the " + (g.source === "task" ? "task override" : "process default") + " guardrail below.") : "") +
      linkerHtml("controlIds", "Controls performed in this step", "control", eg.links.controlIds) +
      '<button class="btn full panel-ripple" data-panel-ripple="' + escapeHtml(Core.taskNodeId(proc.id, el.id)) + '"><span class="ic" data-icon="ripple"></span> Ripple this step</button></div>';
  }

  function guardrailActionsHtml(g) {
    var a = Core.parseGuardrailActions(g.allow), d = Core.parseGuardrailActions(g.deny);
    if (!a.length && !d.length) return "";
    var note = g.source ? (g.source === "task" ? "Agents here are checked against this task’s override:" : "Agents here inherit the process actions:") : "";
    return (note ? '<div class="hint" style="margin-top:8px">' + note + "</div>" : "") + '<div class="action-chips" title="Structured action ids an agent is checked against">' +
      a.map(function (x) { return '<span class="tag t-good">' + escapeHtml(x.id) + "</span>"; }).join("") +
      d.map(function (x) { return '<span class="tag t-bad">' + escapeHtml(x.id) + "</span>"; }).join("") + "</div>";
  }

  function wirePanelEnterprise(proc, el) {
    var body = $("#panel-body");
    $all("[data-panel-ripple]", body).forEach(function (b) { b.onclick = function () { captureCurrentXml().then(function () { openRipple(b.getAttribute("data-panel-ripple")); }); }; });
    if (activeTab !== "governance") return;
    if (!el) {
      wireLinkers(body, function (k) { Core.ensureProcLinks(proc); return proc.links[k].slice(); }, function (k, ids) {
        proc.links[k] = ids;
        if (k === "riskIds") Core.syncRiskRefs(STATE, proc);
        markDirty();
        renderModuleBadge();
      }, renderPanel);
    } else if (isGovernableType(el.type)) {
      wireLinkers(body, function (k) { return Core.ensureElementLinks(proc, el.id).links[k].slice(); }, function (k, ids) {
        Core.ensureElementLinks(proc, el.id).links[k] = ids;
        markDirty();
        renderModuleBadge();
      }, renderPanel);
    }
  }

  /* ---- registry editors ---- */

  var EDITORS = {
    capability: {
      title: "capability",
      fields: [
        { k: "name", l: "Name", t: "text", span: 2 },
        { k: "level", l: "Level", t: "select", o: [["1", "L1 — top level"], ["2", "L2"], ["3", "L3"]], num: true },
        { k: "parentId", l: "Part of", t: "parent" },
        { k: "owner", l: "Owner", t: "text" },
        { k: "importance", l: "Strategic importance", t: "select", o: [["low", "Low"], ["medium", "Medium"], ["high", "High"], ["critical", "Critical"]] },
        { k: "description", l: "Description", t: "textarea", span: 2 }
      ],
      links: [
        { k: "realizedBy", l: "Realized by processes", ref: "process", rev: "proc:capabilityIds" },
        { k: "servedBy", l: "Served by systems and agents", ref: "application", rev: "app:capabilityIds" }
      ]
    },
    application: {
      title: "system",
      fields: [
        { k: "name", l: "Name", t: "text", span: 2 },
        { k: "kind", l: "Kind", t: "select", o: [["system", "System"], ["agent", "AI agent"]] },
        { k: "vendor", l: "Vendor / provider", t: "text" },
        { k: "owner", l: "Owner", t: "text" },
        { k: "lifecycle", l: "Lifecycle", t: "select", o: [["plan", "Planned"], ["active", "Active"], ["sunset", "Sunset"], ["retired", "Retired"]] },
        { k: "sunsetDate", l: "Sunset / retirement date", t: "date" },
        { k: "criticality", l: "Criticality", t: "select", o: [["low", "Low"], ["medium", "Medium"], ["high", "High"], ["critical", "Critical"]] },
        { k: "dataClass", l: "Data classification", t: "select", o: [["public", "Public"], ["internal", "Internal"], ["confidential", "Confidential"], ["restricted", "Restricted"]] },
        { k: "agent.model", l: "Model / runtime", t: "text", agentOnly: true },
        { k: "agent.autonomy", l: "Autonomy", t: "select", o: [["assist", "Assist only"], ["act_with_approval", "Acts with approval"], ["autonomous", "Autonomous"]], agentOnly: true },
        { k: "notes", l: "Notes", t: "textarea", span: 2 }
      ],
      links: [
        { k: "capabilityIds", l: "Serves capabilities", ref: "capability", own: true },
        { k: "supportsProc", l: "Supports processes", ref: "process", rev: "proc:applicationIds" },
        { k: "supportsTask", l: "Used in tasks", ref: "task", rev: "task:applicationIds" },
        { k: "obligationIds", l: "Obligations that apply to it", ref: "obligation", own: true },
        { k: "riskIds", l: "Risks affecting it", ref: "risk", own: true }
      ]
    },
    obligation: {
      title: "obligation",
      fields: [
        { k: "source", l: "Source (standard, law, policy)", t: "text" },
        { k: "clause", l: "Clause / reference", t: "text" },
        { k: "title", l: "Title", t: "text", span: 2 },
        { k: "summary", l: "Summary in your own words", t: "textarea", span: 2 },
        { k: "jurisdiction", l: "Jurisdiction", t: "text" },
        { k: "effectiveDate", l: "Effective date", t: "date" }
      ],
      links: [
        { k: "appliesProc", l: "Applies to processes", ref: "process", rev: "proc:obligationIds" },
        { k: "appliesApp", l: "Applies to systems", ref: "application", rev: "app:obligationIds" },
        { k: "satisfiedBy", l: "Satisfied by controls", ref: "control", rev: "ctl:obligationIds" }
      ]
    },
    control: {
      title: "control",
      fields: [
        { k: "name", l: "Name", t: "text", span: 2 },
        { k: "type", l: "Type", t: "select", o: [["preventive", "Preventive"], ["detective", "Detective"], ["corrective", "Corrective"]] },
        { k: "owner", l: "Owner", t: "text" },
        { k: "frequency", l: "Test frequency", t: "select", o: [["daily", "Daily"], ["weekly", "Weekly"], ["monthly", "Monthly"], ["quarterly", "Quarterly"], ["semiannual", "Every 6 months"], ["annual", "Annual"]] },
        { k: "lastTested", l: "Last tested", t: "date" },
        { k: "lastResult", l: "Last result", t: "select", o: [["not_tested", "Not tested"], ["pass", "Pass"], ["fail", "Fail"]] },
        { k: "description", l: "Description", t: "textarea", span: 2 }
      ],
      links: [
        { k: "obligationIds", l: "Satisfies obligations", ref: "obligation", own: true },
        { k: "riskIds", l: "Mitigates risks", ref: "risk", own: true },
        { k: "performedIn", l: "Performed in tasks", ref: "task", rev: "task:controlIds" }
      ]
    },
    risk: {
      title: "risk",
      fields: [
        { k: "name", l: "Name", t: "text", span: 2 },
        { k: "owner", l: "Owner", t: "text" },
        { k: "treatment", l: "Treatment", t: "select", o: [["mitigate", "Mitigate"], ["accept", "Accept"], ["transfer", "Transfer"], ["avoid", "Avoid"]] },
        { k: "likelihood", l: "Likelihood (1–5)", t: "select", o: [["1", "1 · Rare"], ["2", "2 · Unlikely"], ["3", "3 · Possible"], ["4", "4 · Likely"], ["5", "5 · Almost certain"]], num: true },
        { k: "impact", l: "Impact (1–5)", t: "select", o: [["1", "1 · Minor"], ["2", "2 · Moderate"], ["3", "3 · Serious"], ["4", "4 · Major"], ["5", "5 · Severe"]], num: true },
        { k: "notes", l: "Notes", t: "textarea", span: 2 }
      ],
      links: [
        { k: "affectsProc", l: "Affects processes", ref: "process", rev: "proc:riskIds" },
        { k: "affectsApp", l: "Affects systems", ref: "application", rev: "app:riskIds" },
        { k: "mitigatedBy", l: "Mitigated by controls", ref: "control", rev: "ctl:riskIds" }
      ]
    }
  };

  function getPath(o, k) { return k.split(".").reduce(function (a, p) { return a == null ? a : a[p]; }, o); }
  function setPath(o, k, v) { var ps = k.split("."); var last = ps.pop(); var t = ps.reduce(function (a, p) { if (!a[p]) a[p] = {}; return a[p]; }, o); t[last] = v; }

  function readRev(rev, id) {
    var kind = rev.split(":")[0], key = rev.split(":")[1];
    var out = [];
    if (kind === "proc") Object.keys(STATE.processes).forEach(function (pid) { var p = STATE.processes[pid]; Core.ensureProcLinks(p); if (p.links[key].indexOf(id) >= 0) out.push(pid); });
    if (kind === "app") Object.keys(reg().applications).forEach(function (aid) { if ((reg().applications[aid][key] || []).indexOf(id) >= 0) out.push(aid); });
    if (kind === "ctl") Object.keys(reg().controls).forEach(function (cid) { if ((reg().controls[cid][key] || []).indexOf(id) >= 0) out.push(cid); });
    if (kind === "task") Object.keys(STATE.processes).forEach(function (pid) {
      var p = STATE.processes[pid];
      Object.keys(p.elementGovernance || {}).forEach(function (el) { var L = p.elementGovernance[el].links; if (L && (L[key] || []).indexOf(id) >= 0) out.push(Core.taskNodeId(pid, el)); });
    });
    return out;
  }

  function writeRev(rev, id, ids) {
    var kind = rev.split(":")[0], key = rev.split(":")[1];
    function toggle(list, on) { var has = list.indexOf(id) >= 0; if (on && !has) list.push(id); if (!on && has) list.splice(list.indexOf(id), 1); }
    if (kind === "proc") Object.keys(STATE.processes).forEach(function (pid) { var p = STATE.processes[pid]; Core.ensureProcLinks(p); toggle(p.links[key], ids.indexOf(pid) >= 0); if (key === "riskIds") Core.syncRiskRefs(STATE, p); });
    if (kind === "app") Object.keys(reg().applications).forEach(function (aid) { var a = reg().applications[aid]; a[key] = a[key] || []; toggle(a[key], ids.indexOf(aid) >= 0); });
    if (kind === "ctl") Object.keys(reg().controls).forEach(function (cid) { var c = reg().controls[cid]; c[key] = c[key] || []; toggle(c[key], ids.indexOf(cid) >= 0); });
    if (kind === "task") {
      var want = {}; ids.forEach(function (t) { want[t] = 1; });
      Object.keys(STATE.processes).forEach(function (pid) {
        var p = STATE.processes[pid];
        (p.tasks || []).forEach(function (t) {
          var tid = Core.taskNodeId(pid, t.id);
          var has = p.elementGovernance && p.elementGovernance[t.id] && p.elementGovernance[t.id].links && (p.elementGovernance[t.id].links[key] || []).indexOf(id) >= 0;
          if (want[tid] && !has) toggle(Core.ensureElementLinks(p, t.id).links[key], true);
          if (!want[tid] && has) toggle(p.elementGovernance[t.id].links[key], false);
        });
      });
    }
  }

  function newId(type, name) {
    var pre = { capability: "cap_", application: "app_", obligation: "obl_", control: "ctl_", risk: "rsk_" }[type];
    var key = Core.KEY_OF_TYPE[type];
    var base = pre + Core.slug(name || type);
    var id = base, n = 2;
    while (reg()[key][id]) id = base + "_" + n++;
    return id;
  }

  function defaultsFor(type, extra) {
    var d = {
      capability: { name: "", level: 2, parentId: "", owner: "", importance: "medium", description: "" },
      application: { name: "", kind: "system", vendor: "", owner: "", lifecycle: "active", sunsetDate: "", criticality: "medium", dataClass: "internal", notes: "", capabilityIds: [], obligationIds: [], riskIds: [] },
      obligation: { source: "Internal policy", clause: "", title: "", summary: "", jurisdiction: "", effectiveDate: "", pack: "custom" },
      control: { name: "", type: "preventive", owner: "", frequency: "quarterly", lastTested: "", lastResult: "not_tested", description: "", obligationIds: [], riskIds: [] },
      risk: { name: "", owner: "", likelihood: 3, impact: 3, treatment: "mitigate", notes: "" }
    }[type];
    if (type === "application" && extra && extra.kind === "agent") { d.kind = "agent"; d.vendor = "Continuum agent"; d.agent = { model: "", autonomy: "assist" }; }
    return Object.assign(d, extra || {});
  }

  function typeOfId(id) {
    var found = null;
    Core.REGISTRY_KEYS.forEach(function (k) { if (reg()[k][id]) found = Core.TYPE_OF_KEY[k]; });
    return found;
  }

  /** One editor for all five registry types. Link edits are buffered in a
   *  draft and only applied on Save, so Cancel really cancels. */
  function openEditor(id, type, extra, onSaved, onClosed) {
    type = type || typeOfId(id);
    if (!type) return;
    var spec = EDITORS[type];
    var key = Core.KEY_OF_TYPE[type];
    var isNew = !id;
    var draft = JSON.parse(JSON.stringify(isNew ? defaultsFor(type, extra) : reg()[key][id]));
    var links = {};
    spec.links.forEach(function (L) { links[L.k] = L.own ? (draft[L.k] || []).slice() : isNew ? [] : readRev(L.rev, id); });
    var isAgent = function () { return type === "application" && draft.kind === "agent"; };

    function fieldHtml(f) {
      if (f.agentOnly && !isAgent()) return "";
      if (type === "application" && f.k === "sunsetDate" && draft.lifecycle === "active") return "";
      var v = getPath(draft, f.k); if (v == null) v = "";
      var idAttr = 'id="ed-' + f.k.replace(".", "-") + '" data-k="' + f.k + '"';
      var input;
      if (f.t === "select") input = "<select " + idAttr + ">" + f.o.map(function (o) { return '<option value="' + o[0] + '"' + (String(v) === o[0] ? " selected" : "") + ">" + escapeHtml(o[1]) + "</option>"; }).join("") + "</select>";
      else if (f.t === "parent") {
        var desc = {}; if (id) { desc[id] = 1; var grew = true; while (grew) { grew = false; Object.keys(reg().capabilities).forEach(function (k) { var c = reg().capabilities[k]; if (!desc[c.id] && desc[c.parentId]) { desc[c.id] = 1; grew = true; } }); } }
        var caps = Object.keys(reg().capabilities).map(function (k) { return reg().capabilities[k]; }).filter(function (c) { return !desc[c.id]; }).sort(function (a, b) { return a.name < b.name ? -1 : 1; });
        input = "<select " + idAttr + '><option value="">— None (top level) —</option>' + caps.map(function (c) { return '<option value="' + escapeHtml(c.id) + '"' + (v === c.id ? " selected" : "") + ">" + escapeHtml(c.name) + "</option>"; }).join("") + "</select>";
      }
      else if (f.t === "textarea") input = "<textarea " + idAttr + ">" + escapeHtml(v) + "</textarea>";
      else input = '<input type="' + (f.t === "date" ? "date" : "text") + '" ' + idAttr + ' value="' + escapeHtml(v) + '">';
      return '<div class="field' + (f.span === 2 ? " span2" : "") + '"><label for="ed-' + f.k.replace(".", "-") + '">' + escapeHtml(f.l) + "</label>" + input + "</div>";
    }

    function bodyHtml() {
      var title = type === "application" && isAgent() ? "agent" : spec.title;
      var score = type === "risk" ? '<div class="field span2"><div class="notice">Risk score ' + (Number(draft.likelihood) * Number(draft.impact)) + " of 25 (likelihood × impact)." + (Number(draft.likelihood) * Number(draft.impact) >= 15 ? " High — Vitals treats it as critical without a mitigating control." : "") + "</div></div>" : "";
      var iso = type === "obligation" && /^ISO/.test(draft.source || "") ? '<div class="field span2"><div class="notice">' + escapeHtml(IsoPacks.notice) + "</div></div>" : "";
      return '<div class="modal-head"><span class="modal-title">' + (isNew ? "New " + title : escapeHtml(draft.name || (draft.source + " §" + draft.clause))) + "</span>" +
        '<button class="modal-close" id="modal-x"><span class="ic" data-icon="close"></span></button></div>' +
        '<div class="modal-body"><div class="ed-grid">' + spec.fields.map(fieldHtml).join("") + score + iso + "</div>" +
        '<div class="field-group-title" style="margin-top:6px">Relationships</div>' +
        spec.links.map(function (L) { return linkerHtml(L.k, L.l, L.ref, links[L.k]); }).join("") + "</div>" +
        '<div class="modal-foot">' + (isNew ? "" : '<button class="btn danger" id="ed-del"><span class="ic" data-icon="trash"></span> Delete</button><button class="btn" id="ed-ripple"><span class="ic" data-icon="ripple"></span> Ripple</button>') +
        '<span class="grow"></span><button class="btn" id="ed-cancel">Cancel</button><button class="btn primary" id="ed-save">' + (isNew ? "Create" : "Save") + "</button></div>";
    }

    function collect(root) {
      $all("[data-k]", root).forEach(function (n) {
        var f = spec.fields.filter(function (x) { return x.k === n.getAttribute("data-k"); })[0];
        var v = n.value;
        if (f && f.num) v = parseInt(v, 10) || 0;
        setPath(draft, n.getAttribute("data-k"), v);
      });
    }

    function mount(root) {
      root.querySelector(".modal").classList.add("editor");
      childOpen = false;
      // every close path (buttons, Esc, overlay) runs the hook, so a nested
      // child editor always hands control back to its parent
      modalCloseHook = onClosed || null;
      var dismiss = function () { closeModal(); };
      $("#modal-x", root).onclick = dismiss;
      $("#ed-cancel", root).onclick = dismiss;
      $all("[data-k]", root).forEach(function (n) {
        n.addEventListener("change", function () {
          var k = n.getAttribute("data-k");
          if (k === "kind" || k === "lifecycle" || k === "likelihood" || k === "impact" || k === "source") { collect(root); if (k === "kind" && draft.kind === "agent" && !draft.agent) draft.agent = { model: "", autonomy: "assist" }; rerender(); }
        });
      });
      // A nested "+ New…" replaces this modal with the child editor; the
      // draft is collected first and the parent reopens when the child closes.
      wireLinkers(root, function (k) { return links[k].slice(); }, function (k, ids) { if (!childOpen) collect(root); links[k] = ids; }, rerender, {
        beforeNew: function () { collect(root); childOpen = true; },
        onChildClosed: function () { openModal(bodyHtml(), mount); }
      });
      if ($("#ed-ripple", root)) $("#ed-ripple", root).onclick = function () { openRipple(id); };
      if ($("#ed-del", root)) $("#ed-del", root).onclick = function () {
        if (!confirmDelete(root)) return;
        modalCloseHook = null;
        Core.removeRefs(STATE, id);
        delete reg()[key][id];
        closeModal();
        toast("Deleted.");
        markRegistryDirty();
        if (activeModule === "processes") renderPanel();
      };
      $("#ed-save", root).onclick = function () {
        collect(root);
        var label = draft.name || draft.title;
        if (!String(label || "").trim()) { toast("Give it a name first.", "warn"); return; }
        var theId = id || newId(type, type === "obligation" ? (draft.source + " " + draft.clause + " " + draft.title) : draft.name);
        draft.id = theId;
        if (type === "application" && draft.kind !== "agent") delete draft.agent;
        spec.links.forEach(function (L) { if (L.own) draft[L.k] = links[L.k]; });
        reg()[key][theId] = draft;
        spec.links.forEach(function (L) { if (!L.own) writeRev(L.rev, theId, links[L.k]); });
        modalCloseHook = null;
        closeModal();
        markRegistryDirty();
        if (onSaved) onSaved(theId);
        else if (activeModule === "processes") renderPanel();
        toast(isNew ? "Created — Save to keep it." : "Updated — Save to keep it.");
      };
    }

    var armed = false;
    var childOpen = false;
    function confirmDelete(root) {
      if (armed) return true;
      armed = true;
      var b = $("#ed-del", root);
      b.innerHTML = "Click again to delete";
      setTimeout(function () { armed = false; if (b) b.innerHTML = '<span class="ic" data-icon="trash"></span> Delete'; applyIcons(root); }, 2500);
      return false;
    }

    function rerender() {
      var root = $("#modal-root");
      var box = root.querySelector(".modal");
      if (!box || childOpen) { childOpen = false; openModal(bodyHtml(), mount); return; }
      var scroll = box ? box.querySelector(".modal-body").scrollTop : 0;
      box.innerHTML = bodyHtml();
      applyIcons(root);
      mount(root);
      box.querySelector(".modal-body").scrollTop = scroll;
    }

    openModal(bodyHtml(), mount);
  }

  /* ---- workspace export (feeds the Postgres platform's import) ---- */

  function workspaceExport() {
    var w = ws();
    return {
      schema: "continuum.workspace-export.v1",
      exportedAt: nowIso(),
      processes: w.processes,
      order: w.order,
      registry: w.registry,
      graph: Core.graphExport(w)
    };
  }

  window.__continuumStudio = { state: function () { return syncTasks(); }, core: Core };
