const fs = require("fs");
const path = require("path");
// Derive Process.tasks from BPMN XML the same way Studio does (flow nodes that carry governance).
function tasksFromXml(xml) {
  const out = [];
  const re = /<bpmn:(task|userTask|serviceTask|manualTask|scriptTask|sendTask|receiveTask|businessRuleTask|subProcess|adHocSubProcess|callActivity|exclusiveGateway|parallelGateway|inclusiveGateway|eventBasedGateway|complexGateway)\b[^>]*\bid="([^"]+)"(?:[^>]*\bname="([^"]*)")?/g;
  let m;
  while ((m = re.exec(xml))) out.push({ id: m[2], name: m[3] || m[2], type: "bpmn:" + m[1][0].toUpperCase() + m[1].slice(1) });
  return out;
}
function loadSeedWorkspace() {
  const st = JSON.parse(fs.readFileSync(path.join(__dirname, "../state.orig.json"), "utf8"));
  Object.values(st.processes).forEach((p) => { p.tasks = tasksFromXml(p.bpmnXml); });
  return st;
}
module.exports = { tasksFromXml, loadSeedWorkspace };
