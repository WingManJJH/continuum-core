"use strict";
const $ = (s) => document.querySelector(s);

function metricTiles(m) {
  const gc = m.guardrail_coverage, tc = m.traceability_completeness;
  const a = m.agent_activity;
  const ep = m.escalation_precision;
  const tiles = [
    { v: gc.value + "%", l: "Guardrail coverage", sub: gc.detail, warn: gc.value < 100 },
    { v: tc.value + "%", l: "Traceability completeness", sub: tc.detail },
    { v: `${a.success}/${a.escalated}/${a.denied}`, l: "Agent acts ok / esc / deny", sub: "current log" },
    ep.value != null
      ? { v: ep.value, l: "Escalation precision", sub: `n=${ep.n}` }
      : { v: "needs data", l: "Escalation precision", sub: ep.needs_data, needs: true },
    { v: "needs data", l: "Drift → update latency", sub: m.drift_to_update_latency.needs_data, needs: true },
  ];
  $("#metrics").innerHTML = tiles.map((t) =>
    `<div class="tile ${t.warn ? "warn" : ""} ${t.needs ? "needs" : ""}">
      <div class="v">${t.v}</div><div class="l">${t.l}</div><div class="sub">${t.sub || ""}</div></div>`).join("");
}

function strategy(strat) {
  $("#strategy").innerHTML = strat.objectives.map((o) => `
    <div class="obj">
      <h3>${o.name}</h3>
      <div class="owner">${o.id} · owner ${o.owner} · ${o.horizon}</div>
      ${o.kpis.map((k) => `
        <div class="kpi">
          <div class="kline">
            <span class="kname">${k.name || k.id}</span>
            <span class="pill ${k.status}">${(k.status || "").replace("_", " ")}</span>
            <span class="kval">${k.live_value}/${k.target} ${k.unit || ""}</span>
          </div>
          ${(k.processes || []).flatMap((p) => p.agent_tasks.map((at) => {
            const c = at.activity.counts;
            return `<div class="atask">
              <span class="tid">${at.task}</span> via ${at.agents.join(", ")}
              <span class="gr">${at.guardrail}</span>
              <span class="acts"><span class="ok">${c.success}✓</span> <span class="esc">${c.escalated}⤴</span> <span class="deny">${c.denied}⛔</span></span>
            </div>`;
          })).join("") || '<div class="atask muted">no agent-bound tasks</div>'}
        </div>`).join("")}
    </div>`).join("");
}

function coverage(cov) {
  $("#coverage").innerHTML =
    `<div class="cov-row"><strong>${cov.reviewed}/${cov.total_agent_tasks} reviewed</strong>
       <span class="state ${cov.pct === 100 ? "reviewed" : "default"}">${cov.pct}%</span></div>` +
    cov.per_task.map((x) =>
      `<div class="cov-row"><span class="tid">${x.task}</span>
        <span><span class="gr">${x.guardrail || "none"}</span>
        <span class="state ${x.state}">${x.state}</span></span></div>`).join("");
}

function bottomUp(bu) {
  if (!bu.length) { $("#bottomup").innerHTML = '<div class="muted">No agent activity in the current log. Run enforcement/sweep.py --keep.</div>'; return; }
  $("#bottomup").innerHTML = bu.map((b) => {
    const c = b.activity;
    return `<div class="bu">
      <span class="tid">${b.task}</span> — ${c.success}✓ ${c.escalated}⤴ ${c.denied}⛔
      <div class="trace">${b.task} → ${b.process} → ${b.kpis.join(", ") || "—"} → ${b.objectives.join(", ") || "(no objective)"}</div>
    </div>`;
  }).join("");
}

fetch("/api/rollup").then((r) => r.json()).then((d) => {
  metricTiles(d.metrics);
  strategy(d.strategy);
  coverage(d.coverage);
  bottomUp(d.bottom_up);
}).catch((e) => { $("#metrics").innerHTML = '<div class="muted">failed to load: ' + e + "</div>"; });
