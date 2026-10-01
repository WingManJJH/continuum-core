// Backward-compatibility check: the ORIGINAL published Studio (before the
// EA/GRC work) and the NEW Studio are loaded with the SAME original data, and
// every pre-existing feature must produce identical output.
const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");
const BPMN = fs.readFileSync(require.resolve("bpmn-js/dist/bpmn-modeler.production.min.js"), "utf8");
const OLD = path.join(__dirname, "../original-artifact-v2.html"); // the published Studio before the EA/GRC work
const NEW = path.join(__dirname, "../dist/studio-from-original-state.html"); // python3 build.py state.orig.json, then copy dist/studio.html here

let failures = 0;
const ok = (c, m) => { if (c) console.log("  ✓ " + m); else { failures++; console.log("  ✗ " + m); } };

async function probe(browser, file) {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  await ctx.route("https://cdn.jsdelivr.net/**", (r) => r.fulfill({ status: 200, contentType: "application/javascript", body: BPMN }));
  await ctx.route("https://fonts.**/**", (r) => r.fulfill({ status: 200, body: "" }));
  await ctx.addInitScript(() => {
    window.__published = []; window.__downloads = [];
    window.claude = { use: (n) => n === "artifact" ? Promise.resolve({ publish: (h) => { window.__published.push(h); return Promise.resolve(); } })
      : n === "downloads" ? Promise.resolve({ save: (f) => { window.__downloads.push(f); return Promise.resolve(); } }) : Promise.reject(new Error("no")) };
  });
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
  await page.goto("file://" + file);
  await page.waitForSelector(".proc-card");
  await page.waitForTimeout(700);
  const out = { errors };
  for (const id of ["proc_onboarding", "proc_complaint"]) {
    await page.click('.proc-card[data-id="' + id + '"]');
    await page.waitForTimeout(500);
    await page.click('.view-btn[data-view="raci"]'); await page.waitForTimeout(200);
    out[id + ":raci"] = await page.innerHTML("#raci-content");
    await page.click('.view-btn[data-view="metro"]'); await page.waitForTimeout(200);
    out[id + ":metro"] = await page.innerHTML("#metro-content");
    await page.click('.view-btn[data-view="diagram"]'); await page.waitForTimeout(200);
    out[id + ":library"] = await page.innerText("#process-list");
    out[id + ":status"] = await page.innerText("#sb-apqc");
    await page.click('.panel-tab[data-tab="general"]');
    out[id + ":general"] = await page.innerText("#panel-body");
    // exports
    for (const btn of ["exp-xml", "exp-json"]) {
      await page.click("#btn-export"); await page.click("#" + btn); await page.waitForTimeout(300);
    }
  }
  const dl = await page.evaluate(() => window.__downloads);
  out.downloads = dl.map((d) => ({ filename: d.filename, data: d.data }));
  await page.click("#btn-save");
  await page.waitForFunction(() => window.__published.length === 1);
  const html = await page.evaluate(() => window.__published[0]);
  out.savedState = JSON.parse(html.match(/<script type="application\/json" id="continuum-state">([\s\S]*?)<\/script>/)[1]);
  await ctx.close();
  return out;
}

(async () => {
  const browser = await chromium.launch();
  const a = await probe(browser, OLD);
  const b = await probe(browser, NEW);
  console.log("Original Studio vs new Studio, same original data:");
  ok(a.errors.length === 0 && b.errors.length === 0, "no console errors in either (" + a.errors.length + " / " + b.errors.length + ")");
  for (const k of Object.keys(a).filter((k) => /:(raci|metro|library|status)$/.test(k))) ok(a[k] === b[k], k + " identical");
  for (const k of Object.keys(a).filter((k) => /:general$/.test(k))) ok(a[k] === b[k], k + " identical (process General tab)");
  // BPMN exports must be byte-identical; governance JSON must keep every original field unchanged
  const xmlA = a.downloads.filter((d) => /\.bpmn$/.test(d.filename)), xmlB = b.downloads.filter((d) => /\.bpmn$/.test(d.filename));
  ok(xmlA.length === 2 && xmlA.every((d, i) => d.data === xmlB[i].data), "BPMN 2.0 XML exports byte-identical");
  const jA = a.downloads.filter((d) => /\.json$/.test(d.filename)).map((d) => JSON.parse(d.data).process);
  const jB = b.downloads.filter((d) => /\.json$/.test(d.filename)).map((d) => JSON.parse(d.data).process);
  let same = jA.length === 2;
  jA.forEach((p, i) => Object.keys(p).forEach((k) => {
    if (k === "elementGovernance") {
      Object.keys(p[k]).forEach((el) => Object.keys(p[k][el]).forEach((f) => { if (JSON.stringify(p[k][el][f]) !== JSON.stringify(jB[i][k][el][f])) { same = false; console.log("    differs:", k, el, f); } }));
    } else if (JSON.stringify(p[k]) !== JSON.stringify(jB[i][k])) { same = false; console.log("    differs:", k); }
  }));
  ok(same, "governance JSON export: every original field unchanged (new fields are additive: " + Object.keys(jB[0]).filter((k) => !(k in jA[0])).join(", ") + ")");
  // saved state: every original process field survives a save in the new Studio
  const sA = a.savedState.processes, sB = b.savedState.processes;
  let kept = true;
  Object.keys(sA).forEach((id) => Object.keys(sA[id]).forEach((k) => {
    if (["updatedAt", "history", "version"].includes(k)) return;
    if (k === "elementGovernance") { Object.keys(sA[id][k]).forEach((el) => Object.keys(sA[id][k][el]).forEach((f) => { if (JSON.stringify(sA[id][k][el][f]) !== JSON.stringify(sB[id][k][el][f])) { kept = false; console.log("    lost:", id, el, f); } })); return; }
    if (JSON.stringify(sA[id][k]) !== JSON.stringify(sB[id][k])) { kept = false; console.log("    lost/changed:", id, k); }
  }));
  ok(kept, "saving in the new Studio keeps every original field of the original data");
  ok(b.savedState.registry && Object.keys(b.savedState.registry.obligations).length === 61, "new Studio adds the registry alongside (additive)");
  await browser.close();
  console.log(failures ? failures + " FAILED" : "Backward compatibility confirmed");
  process.exit(failures ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(2); });
