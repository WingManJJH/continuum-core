/* Continuum — seeded obligation packs.
 *
 * Clause numbers and titles identify the requirement so it can be mapped.
 * Every `summary` is Continuum's own plain-language wording, NOT ISO text:
 * ISO standards are copyrighted, so verbatim clause text is never stored.
 * Customers who hold a licence can attach their own copy.
 * Titles to be verified by the fractional QMS advisor before customer use.
 */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.ContinuumIsoPacks = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  var ISO9001 = [
    ["4.1", "Understanding the organization and its context", "Know the internal and external issues that shape what the quality system must achieve, and keep that view current."],
    ["4.2", "Understanding the needs and expectations of interested parties", "Identify who has a stake in quality and which of their requirements matter, and review them over time."],
    ["4.3", "Determining the scope of the quality management system", "State clearly which sites, products and services the quality system covers, and justify anything left out."],
    ["4.4", "Quality management system and its processes", "Define each process with an owner, inputs, outputs, sequence, resources, risks and measures, and keep them working together."],
    ["5.1", "Leadership and commitment", "Top management is visibly accountable for the quality system and for keeping customers at the centre."],
    ["5.2", "Policy", "Maintain a quality policy that fits the organization's purpose, is communicated and is understood."],
    ["5.3", "Organizational roles, responsibilities and authorities", "Assign and communicate who is responsible and has authority for each part of the quality system."],
    ["6.1", "Actions to address risks and opportunities", "Plan how risks and opportunities affecting quality will be handled, and check the actions work."],
    ["6.2", "Quality objectives and planning to achieve them", "Set measurable quality objectives and plan who does what, by when, to reach them."],
    ["6.3", "Planning of changes", "Change the quality system in a planned way, considering consequences, resources and responsibilities."],
    ["7.1", "Resources", "Provide the people, infrastructure, environment, measuring resources and knowledge the processes need."],
    ["7.2", "Competence", "Make sure people doing work that affects quality are competent, and keep evidence of it."],
    ["7.3", "Awareness", "People know the policy, relevant objectives, their contribution and the consequences of not conforming."],
    ["7.4", "Communication", "Decide what is communicated about the quality system, to whom, when and how."],
    ["7.5", "Documented information", "Create, approve, version, distribute, protect and retain the documents and records the system needs."],
    ["8.1", "Operational planning and control", "Plan and control the processes that deliver products and services, with criteria and records."],
    ["8.2", "Requirements for products and services", "Determine, review and communicate customer and other requirements before committing to deliver."],
    ["8.3", "Design and development of products and services", "Run design work through planned stages with inputs, controls, outputs and managed changes."],
    ["8.4", "Control of externally provided processes, products and services", "Select, evaluate and control suppliers and outsourced work that affect quality."],
    ["8.5", "Production and service provision", "Deliver under controlled conditions, with traceability, care of property, preservation and post-delivery activities."],
    ["8.6", "Release of products and services", "Verify requirements are met before release, and record who authorized it."],
    ["8.7", "Control of nonconforming outputs", "Identify and control outputs that do not conform so they are not used or delivered unintentionally."],
    ["9.1", "Monitoring, measurement, analysis and evaluation", "Decide what to measure, including customer satisfaction, and analyse results to judge performance."],
    ["9.2", "Internal audit", "Audit the quality system at planned intervals against criteria, and act on findings."],
    ["9.3", "Management review", "Top management reviews the system at planned intervals with defined inputs and records decisions."],
    ["10.1", "Improvement — general", "Pick and act on opportunities to improve products, services and the quality system."],
    ["10.2", "Nonconformity and corrective action", "React to nonconformities, find root causes, correct them and confirm the fix worked."],
    ["10.3", "Continual improvement", "Keep improving how suitable, adequate and effective the quality system is."]
  ];

  var ISO9004 = [
    ["4.1", "Quality of an organization", "Judge quality by how well the organization meets the needs of its interested parties over time."],
    ["4.2", "Managing for sustained success", "Balance short- and long-term needs to keep the organization successful."],
    ["5.1", "Context — general", "Understand context as the basis for strategy and sustained success."],
    ["5.2", "Relevant interested parties", "Identify the parties that matter, what they need, and how the relationship benefits both sides."],
    ["5.3", "External and internal issues", "Track the issues inside and outside the organization that can help or hinder its goals."],
    ["6.1", "Identity — general", "Define what the organization is and stands for as the anchor for decisions."],
    ["6.2", "Mission, vision, values and culture", "Keep mission, vision, values and culture explicit, shared and consistent with behaviour."],
    ["7.1", "Leadership — general", "Leaders create unity of purpose and the conditions for people to engage."],
    ["7.2", "Policy and strategy", "Turn identity into a policy and strategy that are deployed and reviewed."],
    ["7.3", "Objectives", "Set objectives at each level that follow from the strategy and can be measured."],
    ["7.4", "Communication", "Communicate strategy and objectives so people understand their part."],
    ["8.1", "Process management — general", "Manage activities as interrelated processes to get consistent, predictable results."],
    ["8.2", "Determination of processes", "Determine the processes needed, how they interact and what they must deliver."],
    ["8.3", "Responsibility and authority relating to processes", "Give each process an accountable owner with the authority to manage it."],
    ["8.4", "Managing processes", "Plan, run, measure and improve processes, managing their interactions and risks."],
    ["9.1", "Resource management — general", "Plan and provide the resources needed for sustained success."],
    ["9.2", "People", "Engage, develop and empower people, and recognise their contribution."],
    ["9.3", "Organizational knowledge", "Capture, share and protect the knowledge the organization depends on."],
    ["9.4", "Technology", "Evaluate and adopt technology that improves performance."],
    ["9.5", "Infrastructure and work environment", "Provide and maintain infrastructure and a work environment that support the work."],
    ["9.6", "Externally provided resources", "Manage suppliers and partners as part of the value chain."],
    ["9.7", "Natural resources", "Use natural resources responsibly and with an eye on future availability."],
    ["10.1", "Performance analysis — general", "Monitor, measure, analyse and evaluate performance to inform decisions."],
    ["10.2", "Performance indicators", "Choose indicators that show progress against objectives and strategy."],
    ["10.3", "Performance analysis", "Analyse indicator data to find trends, causes and opportunities."],
    ["10.4", "Performance evaluation", "Evaluate results against objectives and benchmarks to judge progress."],
    ["10.5", "Internal audit", "Use internal audits to check effectiveness and find improvement opportunities."],
    ["10.6", "Self-assessment", "Assess maturity regularly against the five-level scale to set improvement priorities."],
    ["10.7", "Reviews", "Review performance and context at planned intervals and decide what to change."],
    ["11.1", "Improvement, learning and innovation — general", "Treat improvement, learning and innovation as interdependent drivers of success."],
    ["11.2", "Improvement", "Improve processes, products and the organization in a structured way."],
    ["11.3", "Learning", "Learn from successes, failures and others, and turn it into practice."],
    ["11.4", "Innovation", "Encourage and manage innovation in products, processes and the organization."]
  ];

  function toObligations(rows, packId, source, prefix) {
    return rows.map(function (r) {
      return {
        id: "obl_" + prefix + "_" + r[0].replace(/\./g, "_"),
        pack: packId,
        source: source,
        clause: r[0],
        title: r[1],
        summary: r[2],
        jurisdiction: "International",
        effectiveDate: ""
      };
    });
  }

  return {
    packs: {
      iso9001: { id: "iso9001", source: "ISO 9001:2015", label: "ISO 9001:2015 Quality management systems — requirements", obligations: toObligations(ISO9001, "iso9001", "ISO 9001:2015", "iso9001") },
      iso9004: { id: "iso9004", source: "ISO 9004:2018", label: "ISO 9004:2018 Quality of an organization — guidance to achieve sustained success", obligations: toObligations(ISO9004, "iso9004", "ISO 9004:2018", "iso9004") }
    },
    notice: "Clause numbers and titles are used for mapping only. Summaries are Continuum's own wording, not ISO text. Verify against your licensed copy of the standard."
  };
});
