// Loads the built page once and saves the post-migration state (registry
// seeded, risks migrated, tasks derived) so the published page carries it.
const { chromium } = require("playwright");
const fs = require("fs"), path = require("path");
const BPMN = fs.readFileSync(require.resolve("bpmn-js/dist/bpmn-modeler.production.min.js"), "utf8");
(async () => {
  const b = await chromium.launch(); const ctx = await b.newContext();
  await ctx.route("https://cdn.jsdelivr.net/**", (r) => r.fulfill({ status: 200, contentType: "application/javascript", body: BPMN }));
  await ctx.route("https://fonts.**/**", (r) => r.fulfill({ status: 200, body: "" }));
  const p = await ctx.newPage();
  await p.goto("file://" + path.join(__dirname, "../dist/studio.html"));
  await p.waitForFunction(() => window.__continuumStudio && window.__continuumStudio.state().registry);
  await p.waitForTimeout(500);
  const st = await p.evaluate(() => JSON.parse(JSON.stringify(window.__continuumStudio.state())));
  fs.writeFileSync(path.join(__dirname, "../state.seeded.json"), JSON.stringify(st));
  console.log("seeded state:", Object.keys(st.registry).map((k) => k + "=" + Object.keys(st.registry[k]).length).join(" "));
  await b.close();
})();
