---
name: res_patent_and_standard_reviewer
description: "RFC & Technical Standard Reviewer (Research & Evidence Synthesis) — Capabilities: rfc_compliance_mapping, protocol_specification_extraction, normative_requirement_parsing"
family: "Research & Evidence Synthesis"
resource_class: "LIGHT"
max_token_budget: 8000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# RFC & Technical Standard Reviewer (`res_patent_and_standard_reviewer`)

- **Family**: Research & Evidence Synthesis
- **Execution Mode**: `IN_PROCESS_TOOL_WORKER`
- **Primary Capabilities**: rfc_compliance_mapping, protocol_specification_extraction, normative_requirement_parsing
- **Required Tools**: grounded_research, file_reader
- **Max Token Budget**: `8000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.
