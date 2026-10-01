// Runs the browser JS core on the shared fixture and prints every rule result
// as JSON, for enterprise/test_parity.py to compare against the Python engine.
//   node enterprise/parity/dump.js [today]
const path = require("path");
const STUDIO = path.join(__dirname, "..", "..", "studio");
const C = require(path.join(STUDIO, "core", "continuum-core.js"));
const ISO = require(path.join(STUDIO, "core", "iso-packs.js"));
const { loadSeedWorkspace } = require(path.join(STUDIO, "core", "test-helpers.js"));
const today = process.argv[2] || "2026-09-30";

const ws = loadSeedWorkspace();
C.ensureWorkspace(ws, ISO);
// widen the fixture: a failing control, a retired system still in use, an
// accepted risk, a capability cycle and a review date in the past
const R = ws.registry;
R.controls.ctl_doc_approval.lastResult = "fail";
R.applications.app_qms_docs.lifecycle = "retired";
ws.processes.proc_onboarding.links.applicationIds.push("app_qms_docs");
R.risks.rsk_late_it_provisioning.treatment = "accept";
R.capabilities.cap_loop_a = { id: "cap_loop_a", name: "Loop A", level: 2, parentId: "cap_loop_b", importance: "low", owner: "" };
R.capabilities.cap_loop_b = { id: "cap_loop_b", name: "Loop B", level: 2, parentId: "cap_loop_a", importance: "low", owner: "" };
ws.processes.proc_complaint.nextReviewDue = "2026-01-15";

const idx = C.nodeIndex(ws);
const ripple = {};
Object.keys(idx).forEach((id) => { ripple[id] = C.ripple(ws, id); });
process.stdout.write(JSON.stringify({ today, ws, ripple, assure: C.assure(ws, today), vitals: C.vitals(ws, today), atlas: C.atlas(ws) }));
