---
name: res_sdk_doc_navigator
description: "Upstream SDK Documentation Navigator (Research & Evidence Synthesis) — Capabilities: api_signature_lookup, sdk_version_compatibility_check, deprecation_detection"
family: "Research & Evidence Synthesis"
resource_class: "LIGHT"
max_token_budget: 8000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Upstream SDK Documentation Navigator (`res_sdk_doc_navigator`)

- **Family**: Research & Evidence Synthesis
- **Execution Mode**: `IN_PROCESS_TOOL_WORKER`
- **Primary Capabilities**: api_signature_lookup, sdk_version_compatibility_check, deprecation_detection
- **Required Tools**: file_reader, grounded_research
- **Max Token Budget**: `8000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.
