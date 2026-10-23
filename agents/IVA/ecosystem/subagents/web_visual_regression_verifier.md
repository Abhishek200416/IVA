---
name: web_visual_regression_verifier
description: "HTML Dashboard & Layout Verifier (Browser & Web Automation) — Capabilities: html_structure_validation, metric_binding_verification, broken_asset_link_detection"
family: "Browser & Web Automation"
resource_class: "LIGHT"
max_token_budget: 6000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# HTML Dashboard & Layout Verifier (`web_visual_regression_verifier`)

- **Family**: Browser & Web Automation
- **Execution Mode**: `IN_PROCESS_TOOL_WORKER`
- **Primary Capabilities**: html_structure_validation, metric_binding_verification, broken_asset_link_detection
- **Required Tools**: file_reader, evidence_verifier
- **Max Token Budget**: `6000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.
