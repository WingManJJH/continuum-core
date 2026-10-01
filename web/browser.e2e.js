// Two real browser users on the multi-user canvas (run by web/test_browser.py).
const { chromium } = require("playwright");
const PORT = process.env.CC_PORT, SHOTS = process.env.CC_SHOTS, MODE = process.env.CC_MODE || "dev";
const BASE = `http://127.0.0.1:${PORT}`;
let pass = 0, fail = 0;
const ok = (c, m) => { if (c) { pass++; console.log("  ok   " + m); } else { fail++; console.log("  FAIL " + m); } };
const shot = async (page, name) => { if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: false }); };

async function user(browser, email, name) {
  const ctx = await browser.newContext({ viewport: { width: 1480, height: 920 } });
  if (MODE !== "off") await ctx.addCookies([{ name: "cc_ws", value: "acme", url: BASE }]);  // the test model, never data/
  const page = await ctx.newPage();
  page.errors = [];
  (global.__pages = global.__pages || []).push(page);
  page.on("pageerror", (e) => page.errors.push(e.message));
  page.on("console", (m) => { if (m.type() === "error" && !/status of 40[139]/.test(m.text())) page.errors.push(m.text()); });
  await page.goto(BASE + "/");
  if (email) {
    await page.waitForSelector("input[name=email]");
    await page.fill("input[name=email]", email);
    if (name) await page.fill("input[name=name]", name);
    await page.click("button[type=submit]");
  }
  await page.waitForSelector("#proc-list li:not(.muted)", { timeout: 15000 });
  await page.waitForTimeout(600);
  return { ctx, page };
}

async function singleUser(browser) {
  const { ctx, page } = await user(browser, null);
  ok(!(await page.$("body.signed-in")), "single-user mode: no sign-in, page loads as before");
  ok((await page.textContent("#who-btn")).startsWith("You:"), "single-user mode: the role picker is unchanged");
  await page.click("#enterprise-btn");
  await page.waitForSelector(".ea-tabs");
  ok(true, "single-user mode: Enterprise view opens");
  ok(page.errors.length === 0, "single-user mode: no console errors (" + page.errors.join(" | ") + ")");
  await ctx.close();
}

(async () => {
  const browser = await chromium.launch();
  try {
    if (MODE === "off") { await singleUser(browser); return; }
    // --- alice: first person -> organization admin
    const A = await user(browser, "alice@example.com", "Alice");
    ok((await A.page.textContent("#who-btn")).includes("Alice · admin"), "signed in: header shows the person and their role");
    await shot(A.page, "01-canvas-signed-in");

    // Enterprise: Atlas -> add a capability
    await A.page.click("#enterprise-btn");
    await A.page.waitForSelector(".ea-tabs");
    ok(await A.page.isVisible("text=No capabilities yet"), "Atlas starts empty with guidance");
    await A.page.click("[data-ea-add=Capability]");
    await A.page.fill("#ea-form input[name=name]", "Customer onboarding");
    await A.page.selectOption("#ea-form select[name=importance]", "critical");
    await A.page.selectOption("#ea-form select[name=process_refs]", ["CO.3.2.7"]);
    await A.page.fill("#ea-form input[name=__reason]", "first capability map");
    await A.page.click("#ea-form .save");
    await A.page.waitForSelector(".cap-card");
    ok(await A.page.isVisible(".cap-card >> text=Customer onboarding"), "capability saved and shown in Atlas with its process");
    await A.page.click(".cap-card .ea-chip.k-process");
    await A.page.waitForSelector(".ripple .rsum");
    ok((await A.page.textContent(".ripple .rsum")).startsWith("A change to"), "clicking a process shows its Ripple in the side pane");
    await shot(A.page, "02-atlas-ripple");

    // Obligations: add ISO 9001, map a clause
    await A.page.click("[data-ea-tab=obligations]");
    await A.page.click("[data-seed-pack=iso9001]");
    await A.page.waitForSelector(".assure tbody tr");
    ok((await A.page.$$(".assure tbody tr")).length === 28, "ISO 9001 pack adds 28 clauses to Assure");
    const sel = await A.page.$("[data-map-sel='obl.iso9001.4_4']");
    await sel.selectOption("CO.3.2.7");
    await A.page.waitForFunction(() => { const s = document.querySelector("[data-map-sel='obl.iso9001.4_4']"); const tr = s && s.closest("tr");
      return tr && tr.querySelector(".ev .ea-chip") && tr.querySelector(".ea-pill.st-covered"); });
    ok(true, "mapping a clause to an active process makes it covered, with the process as evidence");
    await shot(A.page, "03-assure");

    // Risks & controls: control fails its test -> Vitals critical
    await A.page.click("[data-ea-tab=risks]");
    await A.page.click("[data-ea-add=Control]");
    await A.page.fill("#ea-form input[name=name]", "Second-look on high-risk KYC");
    await A.page.selectOption("#ea-form select[name=frequency]", "monthly");
    await A.page.fill("#ea-form input[name=__reason]", "new control");
    await A.page.click("#ea-form .save");
    await A.page.waitForSelector("[data-test=fail]");
    await A.page.click("[data-test=fail]");
    await A.page.waitForSelector(".ea-pill.res-fail");
    ok(await A.page.isVisible(".ea-pill.res-fail"), "recording a failed test marks the control");
    await A.page.click("[data-ea-tab=vitals]");
    await A.page.waitForSelector(".vf.sev-critical");
    ok(await A.page.isVisible(".vf.sev-critical >> text=Failed its last test"), "Vitals raises the failed control as critical");
    await shot(A.page, "04-vitals");

    // Members: give bob viewer access
    await A.page.click("#who-btn");
    await A.page.click("#acct-members");
    await A.page.waitForSelector("#m-add");
    await A.page.fill("#m-email", "bob@example.com");
    await A.page.selectOption("#m-role", "viewer");
    await A.page.click("#m-add button");
    await A.page.waitForSelector("tr[data-email='bob@example.com']");
    ok(true, "admin gives bob viewer access");
    await shot(A.page, "05-members");
    await A.page.click("#who-close");

    // Imports: staged change with a field diff -> accept
    await A.page.click("#imports-btn");
    await A.page.waitForSelector(".stg");
    ok(await A.page.isVisible(".diff >> text=Match POs — our wording"), "staged import shows our value next to the incoming one");
    await shot(A.page, "06-import-review");

    // --- bob: viewer, live updates
    const B = await user(browser, "bob@example.com", "Bob");
    ok((await B.page.textContent("#who-btn")).includes("viewer"), "bob is signed in as a viewer");
    ok(!(await B.page.isVisible("#new-proc")), "viewer does not see editing tools");
    const before = await B.page.textContent("#proc-list");
    // alice accepts the staged change; bob's list updates live
    await A.page.click("[data-accept]");
    await A.page.waitForSelector(".cc-toast.ok");
    await B.page.waitForFunction(() => document.querySelector("#proc-list").textContent.includes("Match purchase orders (vendor)"), null, { timeout: 15000 });
    ok(!before.includes("(vendor)"), "bob's canvas updates live when alice accepts the import");
    const r = await B.page.evaluate(async () => (await fetch("/api/process/edit", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: "CO.3.2.7", changes: { name: "x" }, reason: "try" }) })).status);
    ok(r === 403, "a viewer's write is refused by the server (403)");
    await shot(B.page, "07-viewer-live");

    ok(A.page.errors.length === 0, "no console errors for alice (" + A.page.errors.join(" | ") + ")");
    ok(B.page.errors.length === 0, "no console errors for bob (" + B.page.errors.join(" | ") + ")");
    await A.ctx.close(); await B.ctx.close();
  } catch (e) {
    fail++; console.log("  FAIL " + (e && e.stack || e));
    for (const pg of (global.__pages || [])) { console.log("  page errors: " + pg.errors.join(" | ")); if (SHOTS) await pg.screenshot({ path: `${SHOTS}/zz-failure.png` }); }
  } finally {
    await browser.close();
    console.log(`\n${pass} passed, ${fail} failed`);
    process.exit(fail ? 1 : 0);
  }
})();
