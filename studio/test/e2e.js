// End-to-end check of Continuum Studio + enterprise modules in headless Chromium.
// The bpmn-js CDN is blocked from this sandbox, so the exact same file is
// served from the npm package; fonts are stubbed.
const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");

const DIST = path.join(__dirname, "..", "dist");
const OUT = path.join(__dirname, "shots");
fs.mkdirSync(OUT, { recursive: true });
const BPMN = fs.readFileSync(require.resolve("bpmn-js/dist/bpmn-modeler.production.min.js"), "utf8");
const page1 = process.argv[2] || path.join(DIST, "studio.html");

let failures = 0;
function ok(cond, msg) { if (cond) console.log("  ✓ " + msg); else { failures++; console.log("  ✗ " + msg); } }

async function open(browser, file, opts = {}) {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, colorScheme: opts.dark ? "dark" : "light" });
  await ctx.route("https://cdn.jsdelivr.net/**", (r) => r.fulfill({ status: 200, contentType: "application/javascript", body: BPMN }));
  await ctx.route("https://fonts.googleapis.com/**", (r) => r.fulfill({ status: 200, contentType: "text/css", body: "" }));
  await ctx.route("https://fonts.gstatic.com/**", (r) => r.fulfill({ status: 200, body: "" }));
  await ctx.addInitScript(() => {
    window.__published = [];
    window.claude = {
      use: (name) => name === "artifact"
        ? Promise.resolve({ publish: (html) => { window.__published.push(html); return Promise.resolve(); } })
        : Promise.reject(new Error("no " + name))
    };
  });
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push("pageerror: " + e.message));
  page.on("console", (m) => { if (m.type() === "error") errors.push("console: " + m.text()); });
  await page.goto("file://" + file);
  await page.waitForSelector(".proc-card", { timeout: 15000 });
  await page.waitForFunction(() => window.__continuumStudio && window.__continuumStudio.state().registry);
  await page.waitForTimeout(400);
  return { ctx, page, errors };
}

const S = async (page, name) => { await page.waitForTimeout(250); return page.screenshot({ path: path.join(OUT, name + ".png") }); };
const state = (page) => page.evaluate(() => JSON.parse(JSON.stringify(window.__continuumStudio.state())));

(async () => {
  const browser = await chromium.launch();
  console.log("Generation 1:", path.basename(page1));
  const { page, errors } = await open(browser, page1);

  let st = await state(page);
  ok(Object.keys(st.registry.obligations).length === 61, "61 ISO obligations seeded (28 + 33)");
  ok(Object.keys(st.registry.applications).length === 8, "8 example systems and agents seeded");
  ok(st.processes.proc_onboarding.links.riskIds.length === 2, "free-text risks migrated to risk records");
  ok(st.processes.proc_onboarding.tasks.length >= 6, "tasks derived from the live diagram");
  await S(page, "01-processes");

  // Governance panel with enterprise links
  await page.click('.panel-tab[data-tab="governance"]');
  await page.waitForSelector('[data-linker="capabilityIds"]');
  ok(await page.isVisible('[data-linker="capabilityIds"] .tag'), "process panel shows linked capability");
  await page.locator("#panel-body").evaluate((n) => (n.scrollTop = 520));
  await S(page, "02-governance-links");

  // Link a second capability from the panel
  await page.selectOption('[data-linker="capabilityIds"] select', "cap_learning");
  st = await state(page);
  ok(st.processes.proc_onboarding.links.capabilityIds.includes("cap_learning"), "panel linker writes process.links");

  // Estate
  await page.click('.module-btn[data-module="estate"]');
  await page.waitForSelector(".ent-table");
  ok(await page.isHidden("#canvas"), "module view replaces the canvas");
  ok((await page.locator(".ent-table tbody tr").count()) === 6, "Estate lists 6 systems");
  await S(page, "03-estate-systems");
  await page.click('[data-estate-tab="agent"]');
  ok((await page.locator(".ent-table tbody tr").count()) === 2, "Estate lists 2 agents");
  await S(page, "04-estate-agents");

  // Ripple from a sunset system
  await page.click('[data-estate-tab="system"]');
  await page.click('tr[data-edit="app_legacy_helpdesk"] [data-ripple]');
  await page.waitForSelector(".modal.ripple");
  const rippleText = await page.textContent(".modal.ripple");
  ok(/Legacy Helpdesk reaches/.test(rippleText), "Ripple summary sentence");
  ok(/Root-cause review/.test(rippleText) && /§10\.2/.test(rippleText), "Ripple reaches control and ISO §10.2");
  await S(page, "05-ripple-helpdesk");
  // jump from Ripple to the affected task
  await page.click('.ripple-item[data-open="proc_complaint::Task_InvestigateResolve"]');
  await page.waitForFunction(() => document.querySelector("#sb-selection").textContent.indexOf("Investigate") >= 0, null, { timeout: 8000 });
  ok(true, "Ripple item opens the process and selects the task");
  await page.waitForSelector('[data-linker="controlIds"]');
  ok(/Root-cause review/.test(await page.textContent('[data-linker="controlIds"]')), "task panel shows its control");
  await S(page, "06-task-panel");

  // Atlas
  await page.click('.module-btn[data-module="atlas"]');
  await page.waitForSelector(".atlas-grid");
  ok((await page.locator(".atlas-l1").count()) === 4, "Atlas shows 4 top-level capabilities");
  await S(page, "07-atlas-maturity");
  await page.click('[data-heat="coverage"]');
  await S(page, "08-atlas-coverage");

  // Edit a system: make the legacy helpdesk active → overlap appears in Atlas
  await page.click('.module-btn[data-module="estate"]');
  await page.click('tr[data-edit="app_legacy_helpdesk"] .ent-name');
  await page.waitForSelector(".modal.editor");
  await S(page, "09-editor");
  await page.selectOption("#ed-lifecycle", "active");
  await page.click("#ed-save");
  await page.click('.module-btn[data-module="atlas"]');
  ok(/Overlap: 2 systems/.test(await page.textContent(".atlas-grid")), "Atlas flags overlapping systems");

  // Now retire it → critical Vitals finding + badge
  await page.click('.module-btn[data-module="estate"]');
  await page.click('tr[data-edit="app_legacy_helpdesk"] .ent-name');
  await page.selectOption("#ed-lifecycle", "retired");
  await page.click("#ed-save");
  await page.click('.module-btn[data-module="vitals"]');
  await page.waitForSelector(".vitals-top");
  ok(/Retired, but still supports/.test(await page.textContent("#module-view")), "Vitals flags a retired system still in use");
  ok(((await page.textContent("#vitals-badge")) || "").trim() !== "", "critical badge shows on Vitals");
  await S(page, "10-vitals");

  // Assure
  await page.click('.module-btn[data-module="assure"]');
  await page.waitForSelector(".assure-summary");
  await S(page, "11-assure-9001");
  await page.click('[data-afilter="gap"]');
  const gapRows = await page.locator(".ent-table tbody tr").count();
  ok(gapRows > 5, "Assure gap filter lists open clauses (" + gapRows + ")");
  // map §5.2 to a process from the obligation editor
  await page.click('[data-afilter="all"]');
  await page.click('tr[data-edit="obl_iso9001_5_2"] .ent-name');
  await page.waitForSelector(".modal.editor");
  await page.selectOption('[data-linker="appliesProc"] select', "proc_complaint");
  await page.click("#ed-save");
  st = await state(page);
  ok(st.processes.proc_complaint.links.obligationIds.includes("obl_iso9001_5_2"), "obligation editor writes process.links (reverse edge)");
  ok(/Customer Complaint Resolution/.test(await page.textContent('tr[data-edit="obl_iso9001_5_2"]')), "Assure row shows the new mapping");
  await page.click('[data-pack="ISO 9004:2018"]');
  await S(page, "12-assure-9004");

  // New capability from Atlas with a reverse link
  await page.click('.module-btn[data-module="atlas"]');
  await page.click('[data-act="new-cap"]');
  await page.fill("#ed-name", "Supplier management");
  await page.selectOption("#ed-level", "1");
  await page.click("#ed-save");
  st = await state(page);
  ok(Object.values(st.registry.capabilities).some((c) => c.name === "Supplier management"), "new capability created");

  // Ripple picker
  await page.click("#btn-ripple");
  await page.fill("#rp-q", "§10.2");
  await page.click('.picker-item[data-pick="obl_iso9001_10_2"]');
  await page.waitForSelector(".modal.ripple");
  ok(/Root-cause review/.test(await page.textContent(".modal.ripple")), "Ripple from an obligation finds its control");
  await S(page, "13-ripple-obligation");
  await page.click("#rp-close");

  // Review regression: nested "+ New…" inside an editor keeps the parent draft
  await page.click('.module-btn[data-module="estate"]');
  await page.click('[data-estate-tab="system"]');
  await page.click('[data-act="new-app"]');
  await page.fill("#ed-name", "Zendesk");
  await page.fill("#ed-vendor", "Zendesk Inc.");
  await page.selectOption('[data-linker="capabilityIds"] select', "__new__");
  await page.waitForSelector(".modal-title:has-text('New capability')");
  await page.fill("#ed-name", "Help centre");
  await page.click("#ed-save");
  await page.waitForSelector(".modal-title:has-text('New system')");
  ok((await page.inputValue("#ed-name")) === "Zendesk" && (await page.inputValue("#ed-vendor")) === "Zendesk Inc.", "parent editor draft survives a nested create");
  ok(/Help centre/.test(await page.textContent('[data-linker="capabilityIds"]')), "nested create is linked in the parent");
  // cancelling a nested create returns to the parent too
  await page.selectOption('[data-linker="riskIds"] select', "__new__");
  await page.waitForSelector(".modal-title:has-text('New risk')");
  await page.click("#ed-cancel");
  await page.waitForSelector(".modal-title:has-text('New system')");
  ok((await page.inputValue("#ed-name")) === "Zendesk", "cancelling a nested create returns to the parent");
  // Esc on a nested create also returns to the parent
  await page.selectOption('[data-linker="riskIds"] select', "__new__");
  await page.waitForSelector(".modal-title:has-text('New risk')");
  await page.keyboard.press("Escape");
  await page.waitForSelector(".modal-title:has-text('New system')");
  ok((await page.inputValue("#ed-name")) === "Zendesk", "Esc on a nested create returns to the parent");
  await page.click("#ed-save");
  st = await state(page);
  const zd = Object.values(st.registry.applications).find((a) => a.name === "Zendesk");
  ok(zd && zd.capabilityIds.length === 1 && st.registry.capabilities[zd.capabilityIds[0]].name === "Help centre", "system saved with its new capability");
  ok(errors.length === 0, "no errors in nested editor flow" + (errors.length ? ": " + errors.join(" | ") : ""));

  // Export the enterprise workspace (the platform's import format)
  await page.click('.module-btn[data-module="processes"]');
  await page.click("#btn-export");
  await page.click("#exp-ws");
  await page.waitForSelector("#copy-text");
  const exported = await page.inputValue("#copy-text");
  fs.writeFileSync(path.join(DIST, "workspace-export.json"), exported);
  const ex = JSON.parse(exported);
  ok(ex.schema === "continuum.workspace-export.v1" && ex.graph.edges.length > 40, "Enterprise workspace export (" + ex.graph.edges.length + " edges)");
  await page.click("#modal-x");

  // Save → self-republish
  await page.click('.module-btn[data-module="processes"]');
  const activeId = (await state(page)).activeId;
  const v0 = (await state(page)).processes[activeId].version;
  await page.click("#btn-save");
  await page.waitForFunction(() => window.__published.length === 1);
  const html2 = await page.evaluate(() => window.__published[0]);
  const v1 = (await state(page)).processes[activeId].version;
  ok(v1 === v0 + 1, "process edits bump the document version");
  fs.writeFileSync(path.join(DIST, "gen2.html"), html2);
  ok(errors.length === 0, "no console errors (generation 1)" + (errors.length ? ": " + errors.join(" | ") : ""));

  // Registry-only change must not bump the process version
  await page.click('.module-btn[data-module="estate"]');
  await page.click('tr[data-edit="app_hris"] .ent-name');
  await page.fill("#ed-owner", "HRIS Product Owner");
  await page.click("#ed-save");
  await page.click("#btn-save");
  await page.waitForFunction(() => window.__published.length === 2);
  ok((await state(page)).processes[activeId].version === v1, "registry-only save keeps process version");

  // Generation 2: the republished page must load with everything intact and republish again
  console.log("Generation 2: republished page");
  const g2 = await open(browser, path.join(DIST, "gen2.html"));
  const st2 = await state(g2.page);
  ok(st2.processes.proc_complaint.links.obligationIds.includes("obl_iso9001_5_2"), "links persist across republish");
  ok(st2.registry.applications.app_legacy_helpdesk.lifecycle === "retired", "registry edits persist across republish");
  ok(st2.meta.packsSeeded && st2.meta.packsSeeded.length === 2, "meta.packsSeeded survives save (no re-seeding)");
  await g2.page.click("#btn-save");
  await g2.page.waitForFunction(() => window.__published.length === 1);
  const html3 = await g2.page.evaluate(() => window.__published[0]);
  ok(html3.length > 300000 && html3.indexOf("@@CONTINUUM_STATE@@") > 0, "generation 3 builds with the template token intact");
  ok(g2.errors.length === 0, "no console errors (generation 2)" + (g2.errors.length ? ": " + g2.errors.join(" | ") : ""));
  await g2.ctx.close();

  // Dark theme pass
  const d = await open(browser, page1, { dark: true });
  await d.page.click('.module-btn[data-module="atlas"]');
  await d.page.waitForSelector(".atlas-grid");
  await S(d.page, "14-atlas-dark");
  await d.page.click('.module-btn[data-module="assure"]');
  await S(d.page, "15-assure-dark");
  await d.page.click('.module-btn[data-module="estate"]');
  await d.page.click('tr[data-edit="app_legacy_helpdesk"] [data-ripple]');
  await S(d.page, "16-ripple-dark");
  ok(d.errors.length === 0, "no console errors (dark)");
  await d.ctx.close();

  await browser.close();
  console.log(failures ? "\n" + failures + " FAILED" : "\nAll checks passed");
  process.exit(failures ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(2); });
